"""Bounded, credential-safe discovery for zero-state browser setup."""

import concurrent.futures
import ipaddress
import json
import re
import ssl
import subprocess
import urllib.error
import urllib.request
import uuid

MAX_PVE_NODES = 16
MAX_DERIVED_NETWORKS = 16
MAX_DISCOVERY_HOSTS = 4096
PING_WORKERS = 50
PROBE_WORKERS = 24
MAX_IDENTIFIED_HOSTS = 1024


class DiscoveryInputError(ValueError):
    def __init__(self, code: str, message: str, field: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.field = field
        self.status = status


def validate_discovery_request(body: dict, schema: str) -> dict:
    if not isinstance(body, dict):
        raise DiscoveryInputError("invalid_json", "JSON object required.", "")
    allowed = {"schema", "setup_id", "client_request_id", "cluster", "bootstrap"}
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise DiscoveryInputError(
            "unsupported_field",
            f"Unsupported discovery field: {unknown[0]}",
            unknown[0],
        )
    if str(body.get("schema") or "") != schema:
        raise DiscoveryInputError("unsupported_schema", "Unsupported setup schema.", "schema")
    setup_id = str(body.get("setup_id") or "").strip()
    if not setup_id:
        raise DiscoveryInputError("required_field", "setup_id is required.", "setup_id")

    cluster = body.get("cluster")
    if not isinstance(cluster, dict):
        raise DiscoveryInputError("required_field", "cluster is required.", "cluster")
    unknown_cluster = sorted(set(cluster) - {"name", "nodes"})
    if unknown_cluster:
        raise DiscoveryInputError(
            "unsupported_field",
            f"Unsupported cluster field: {unknown_cluster[0]}",
            f"cluster.{unknown_cluster[0]}",
        )
    cluster_name = str(cluster.get("name") or "").strip()
    if not cluster_name:
        raise DiscoveryInputError("required_field", "Cluster name is required.", "cluster.name")
    nodes = cluster.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_PVE_NODES:
        raise DiscoveryInputError(
            "invalid_node_count",
            f"cluster.nodes must contain 1-{MAX_PVE_NODES} PVE nodes.",
            "cluster.nodes",
        )
    normalized_nodes = []
    seen = set()
    for index, raw in enumerate(nodes):
        if not isinstance(raw, dict):
            raise DiscoveryInputError("invalid_node", "PVE node must be an object.", f"cluster.nodes[{index}]")
        unknown_node = sorted(set(raw) - {"host", "name"})
        if unknown_node:
            raise DiscoveryInputError(
                "unsupported_field",
                f"Unsupported PVE node field: {unknown_node[0]}",
                f"cluster.nodes[{index}].{unknown_node[0]}",
            )
        host = str(raw.get("host") or "").strip()
        try:
            parsed = ipaddress.ip_address(host)
        except ValueError as exc:
            raise DiscoveryInputError(
                "invalid_node_ip",
                f"PVE node {index + 1} must be an IPv4 or IPv6 address.",
                f"cluster.nodes[{index}].host",
            ) from exc
        canonical = str(parsed)
        if canonical in seen:
            raise DiscoveryInputError(
                "duplicate_node_ip",
                "PVE node IPs must be unique.",
                f"cluster.nodes[{index}].host",
            )
        seen.add(canonical)
        name = str(raw.get("name") or f"pve{index + 1:02d}").strip()
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$", name):
            raise DiscoveryInputError(
                "invalid_node_name",
                "PVE node name contains unsupported characters.",
                f"cluster.nodes[{index}].name",
            )
        normalized_nodes.append({"host": canonical, "name": name})

    bootstrap = body.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise DiscoveryInputError("required_field", "bootstrap credentials are required.", "bootstrap")
    unknown_bootstrap = sorted(set(bootstrap) - {"username", "password"})
    if unknown_bootstrap:
        raise DiscoveryInputError(
            "unsupported_field",
            f"Unsupported bootstrap field: {unknown_bootstrap[0]}",
            f"bootstrap.{unknown_bootstrap[0]}",
        )
    username = str(bootstrap.get("username") or "").strip()
    password = str(bootstrap.get("password") or "")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$", username):
        raise DiscoveryInputError("invalid_username", "Bootstrap username is invalid.", "bootstrap.username")
    if not password:
        raise DiscoveryInputError("required_field", "Bootstrap password is required.", "bootstrap.password")

    client_request_id = str(body.get("client_request_id") or "").strip()
    if client_request_id:
        try:
            uuid.UUID(client_request_id)
        except ValueError as exc:
            raise DiscoveryInputError(
                "invalid_client_request_id",
                "client_request_id must be a UUID.",
                "client_request_id",
            ) from exc
    if len(password.encode("utf-8")) > 4096:
        raise DiscoveryInputError(
            "secret_too_large",
            "Bootstrap password exceeds the 4096-byte limit.",
            "bootstrap.password",
        )

    return {
        "schema": schema,
        "setup_id": setup_id,
        "client_request_id": client_request_id,
        "cluster": {"name": cluster_name, "nodes": normalized_nodes},
        "bootstrap": {"username": username, "password": password},
    }


def derived_ipv4_networks(nodes: list[dict]) -> list[ipaddress.IPv4Network]:
    """Derive only /24 management networks from declared literal node IPs."""
    networks = []
    seen = set()
    for node in nodes:
        address = ipaddress.ip_address(str(node.get("host") or ""))
        if not isinstance(address, ipaddress.IPv4Address):
            continue
        network = ipaddress.ip_network(f"{address}/24", strict=False)
        key = str(network)
        if key in seen:
            continue
        seen.add(key)
        networks.append(network)
        if len(networks) >= MAX_DERIVED_NETWORKS:
            break
    if sum(max(0, network.num_addresses - 2) for network in networks) > MAX_DISCOVERY_HOSTS:
        raise DiscoveryInputError(
            "derived_scope_too_large",
            "Derived management scope exceeds the discovery host limit.",
            "cluster.nodes",
            422,
        )
    return networks


def normalize_pve_resources(resources: list) -> list[dict]:
    normalized = []
    for raw in resources:
        if not isinstance(raw, dict):
            continue
        try:
            vmid = int(raw.get("vmid") or 0)
        except (TypeError, ValueError):
            continue
        if vmid <= 0:
            continue
        pve_type = str(raw.get("type") or "qemu").lower()
        node = str(raw.get("node") or "unknown")
        name = str(raw.get("name") or f"resource-{vmid}")
        template = bool(raw.get("template")) or "template" in name.lower() or 9000 <= vmid < 9100
        kind = "template" if template else "container" if pve_type == "lxc" else "vm"
        ips = []
        raw_ips = raw.get("ips") or ([raw.get("ip")] if raw.get("ip") else [])
        for value in raw_ips if isinstance(raw_ips, list) else []:
            try:
                address = str(ipaddress.ip_address(str(value)))
            except ValueError:
                continue
            if address not in ips:
                ips.append(address)
        normalized.append(
            {
                "id": f"pve:{node}:{pve_type}:{vmid}",
                "kind": kind,
                "vmid": vmid,
                "name": name,
                "node": node,
                "status": str(raw.get("status") or "unknown"),
                "ips": ips,
                "suggested_disposition": "owned",
                "suggested_placement": "production",
            }
        )
    return sorted(normalized, key=lambda item: (item["vmid"], item["id"]))


def _ssh_cluster_resources(host: str, username: str, password_file: str) -> tuple[list, str]:
    known_hosts = f"{password_file}.known-hosts"
    pvesh = "pvesh get /cluster/resources --type vm --output-format json 2>/dev/null"
    command = (
        f'if [ "$(id -u)" -eq 0 ]; then {pvesh}; '
        f"elif sudo -n true 2>/dev/null; then sudo -n {pvesh}; "
        f"else sudo -S -p '' {pvesh}; fi"
    )
    args = [
        "sshpass",
        "-f",
        password_file,
        "ssh",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={known_hosts}",
        "-o",
        "PubkeyAuthentication=no",
        f"{username}@{host}",
        command,
    ]
    try:
        with open(password_file) as password_stdin:
            result = subprocess.run(args, stdin=password_stdin, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return [], "bootstrap_unreachable"
    if result.returncode != 0:
        return [], "bootstrap_rejected"
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError):
        return [], "invalid_pve_response"
    return (payload, "") if isinstance(payload, list) else ([], "invalid_pve_response")


def query_declared_pve_nodes(nodes: list[dict], username: str, password_file: str) -> tuple[list, list, list]:
    """Query only declared nodes; any healthy node returns cluster-wide truth."""
    node_results = []
    resources = []
    warnings = []
    had_success = False
    for node in nodes:
        payload, error = _ssh_cluster_resources(node["host"], username, password_file)
        reachable = not error
        had_success = had_success or reachable
        node_results.append(
            {
                "id": f"pve-node:{node['host']}",
                "host": node["host"],
                "name": node["name"],
                "reachable": reachable,
                "version": "",
            }
        )
        if reachable and not resources:
            resources = payload
        if error:
            warnings.append({"code": error, "resource_id": f"pve-node:{node['host']}"})
    if not had_success:
        raise RuntimeError("pve_bootstrap_failed")
    return node_results, resources, warnings


def _ping(ip: str) -> bool:
    try:
        return subprocess.run(
            ["ping", "-c", "1", "-W", "1", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _http_fingerprint(ip: str) -> tuple[str, str]:
    context = ssl._create_unverified_context()

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(context=context),
    )
    for scheme in ("https", "http"):
        try:
            request = urllib.request.Request(
                f"{scheme}://{ip}/",
                headers={"User-Agent": "freq-zero-state-discovery/1"},
            )
            with opener.open(request, timeout=2) as response:
                server = str(response.headers.get("Server") or "")
                body = response.read(32768).decode("utf-8", "ignore")
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            continue
        text = f"{server}\n{body}".lower()
        markers = (
            ("truenas", ("truenas", "freenas")),
            ("idrac", ("idrac", "integrated dell remote access")),
            ("idrac", ("integrated lights-out", "hewlett packard enterprise ilo")),
            ("pfsense", ("pfsense", "opnsense")),
            ("pve", ("proxmox virtual environment", "pve manager")),
        )
        for kind, needles in markers:
            if any(needle in text for needle in needles):
                return kind, scheme
    return "unknown", ""


def _device_credential_fields(kind: str) -> list[str]:
    return {
        "truenas": ["username", "password", "api_key"],
        "idrac": ["username", "password"],
        "pfsense": ["username", "password", "api_key"],
        "switch": ["username", "password"],
    }.get(kind, [])


def scan_derived_devices(nodes: list[dict], resource_ips: set[str], progress=None) -> tuple[list, list]:
    networks = derived_ipv4_networks(nodes)
    declared = {str(node["host"]) for node in nodes}
    candidates = [
        str(host)
        for network in networks
        for host in network.hosts()
        if str(host) not in declared and str(host) not in resource_ips
    ]
    if progress:
        progress("network-scan", 0, len(candidates), "Scanning derived management networks.")
    with concurrent.futures.ThreadPoolExecutor(max_workers=PING_WORKERS) as pool:
        alive = [ip for ip, found in zip(candidates, pool.map(_ping, candidates), strict=True) if found]
    truncated = len(alive) > MAX_IDENTIFIED_HOSTS
    alive = alive[:MAX_IDENTIFIED_HOSTS]
    if progress:
        progress("device-identification", 0, len(alive), "Identifying responding devices without credentials.")
    with concurrent.futures.ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
        fingerprints = list(pool.map(_http_fingerprint, alive))
    devices = []
    for ip, (kind, method) in zip(alive, fingerprints, strict=True):
        if kind == "pve":
            continue
        devices.append(
            {
                "id": f"device:{kind}:{ip}",
                "kind": kind,
                "label": f"{kind}-{ip.replace('.', '-')}",
                "host": ip,
                "source": "credential-free-http" if method else "credential-free-ping",
                "reachable": True,
                "credential_fields": _device_credential_fields(kind),
                "suggested_disposition": "acknowledged" if kind == "unknown" else "owned",
                "suggested_placement": "production",
            }
        )
    warnings = []
    if truncated:
        warnings.append({"code": "device_result_limit_reached", "resource_id": "cluster"})
    if any(ipaddress.ip_address(node["host"]).version == 6 for node in nodes):
        warnings.append({"code": "ipv6_network_scan_not_supported", "resource_id": "cluster"})
    return sorted(devices, key=lambda item: item["host"]), warnings


def run_setup_discovery(cluster: dict, username: str, password_file: str, progress=None) -> dict:
    nodes = cluster["nodes"]
    if progress:
        progress("pve-bootstrap", 0, len(nodes), "Querying declared PVE nodes.")
    pve_nodes, raw_resources, warnings = query_declared_pve_nodes(nodes, username, password_file)
    resources = normalize_pve_resources(raw_resources)
    resource_ips = {ip for resource in resources for ip in resource["ips"]}
    verified_nodes = [
        {"host": node["host"], "name": node["name"]}
        for node in pve_nodes
        if node.get("reachable")
    ]
    devices, scan_warnings = scan_derived_devices(verified_nodes, resource_ips, progress=progress)
    warnings.extend(scan_warnings)
    return {
        "pve_nodes": pve_nodes,
        "resources": resources,
        "devices": devices,
        "warnings": warnings,
    }
