"""Network topology discovery for FREQ — LLDP/CDP-based mapping.

Domain: freq net topology <action>
What: Crawl network switches via LLDP/CDP neighbors to build a complete
      topology graph. Show connections, export to DOT/JSON, diff against
      previous snapshots to detect changes.
Replaces: Manual network diagrams, Visio/draw.io, LibreNMS auto-discovery
Architecture:
    - Uses WS1 deployer get_neighbors() to pull LLDP/CDP from each switch
    - Builds an adjacency graph as a dict of edges
    - Stores topology snapshots in conf/topology/ as JSON
    - Diff compares current vs stored topology to find changes
Design decisions:
    - Graph is edge-list, not adjacency matrix. Simpler to serialize/diff.
    - Crawl is breadth-first from known switches in hosts.toml.
    - DOT export for Graphviz rendering — ops teams already use it.
    - No external graph library. Dict-based adjacency is enough.
"""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOPOLOGY_DIR = "topology"


# ---------------------------------------------------------------------------
# Topology Storage
# ---------------------------------------------------------------------------


def _topo_dir(cfg):
    """Return topology data directory, creating if needed."""
    path = os.path.join(cfg.conf_dir, TOPOLOGY_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _save_topology(cfg, topo):
    """Save a topology snapshot with timestamp."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    filepath = os.path.join(_topo_dir(cfg), f"topology-{ts}.json")
    with open(filepath, "w") as f:
        json.dump(topo, f, indent=2)
    # Also save as "latest"
    latest = os.path.join(_topo_dir(cfg), "topology-latest.json")
    with open(latest, "w") as f:
        json.dump(topo, f, indent=2)
    return filepath


def _load_latest(cfg):
    """Load the most recent topology snapshot."""
    latest = os.path.join(_topo_dir(cfg), "topology-latest.json")
    if not os.path.exists(latest):
        return None
    with open(latest) as f:
        return json.load(f)


def _list_snapshots(cfg):
    """List all topology snapshots, newest first."""
    path = _topo_dir(cfg)
    files = []
    for f in sorted(os.listdir(path), reverse=True):
        if f.startswith("topology-") and f.endswith(".json") and f != "topology-latest.json":
            files.append(os.path.join(path, f))
    return files


# ---------------------------------------------------------------------------
# Discovery Engine
# ---------------------------------------------------------------------------


def discover_topology(cfg):
    """Crawl all switches via LLDP/CDP and build topology graph.

    Returns dict with:
        nodes: list of {name, ip, platform, ...}
        edges: list of {from_device, from_port, to_device, to_port}
        discovered_at: timestamp
    """
    from freq.modules.switch_orchestration import _get_switch_hosts, _get_deployer, _vendor_for_host

    switches = _get_switch_hosts(cfg)
    nodes = []
    edges = []
    seen_edges = set()

    for h in switches:
        vendor = _vendor_for_host(h)
        deployer = _get_deployer(vendor)
        if not deployer:
            continue

        # Get facts for node info
        facts = deployer.get_facts(h.ip, cfg)
        node = {
            "name": facts.get("hostname", h.label) if facts else h.label,
            "ip": h.ip,
            "label": h.label,
            "model": facts.get("model", "") if facts else "",
            "type": "switch",
        }
        nodes.append(node)

        # Get neighbors for edges
        neighbors = deployer.get_neighbors(h.ip, cfg)
        if not neighbors:
            continue

        for n in neighbors:
            # Create a canonical edge key to avoid duplicates
            edge_key = _edge_key(h.label, n.get("local_port", ""), n.get("device", ""), n.get("remote_port", ""))
            reverse_key = _edge_key(n.get("device", ""), n.get("remote_port", ""), h.label, n.get("local_port", ""))

            if edge_key not in seen_edges and reverse_key not in seen_edges:
                seen_edges.add(edge_key)
                edges.append(
                    {
                        "from_device": h.label,
                        "from_port": n.get("local_port", ""),
                        "to_device": n.get("device", ""),
                        "to_port": n.get("remote_port", ""),
                        "to_ip": n.get("ip", ""),
                        "to_platform": n.get("platform", ""),
                    }
                )

                # Add neighbor as a node if not already known
                neighbor_name = n.get("device", "")
                if neighbor_name and not any(nd["name"] == neighbor_name for nd in nodes):
                    nodes.append(
                        {
                            "name": neighbor_name,
                            "ip": n.get("ip", ""),
                            "label": neighbor_name,
                            "model": n.get("platform", ""),
                            "type": "discovered",
                        }
                    )

    return {
        "nodes": nodes,
        "edges": edges,
        "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "switch_count": len(switches),
    }


def _edge_key(dev_a, port_a, dev_b, port_b):
    """Create a canonical edge key for deduplication."""
    return f"{dev_a}:{port_a}->{dev_b}:{port_b}"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_topology_discover(cfg: FreqConfig, pack, args) -> int:
    """Discover network topology via LLDP/CDP."""
    fmt.header("Topology Discovery", breadcrumb="FREQ > Net > Topology")
    fmt.blank()

    fmt.step_start("Crawling switches for LLDP/CDP neighbors")
    topo = discover_topology(cfg)

    if not topo["nodes"]:
        fmt.step_fail("No topology data — no switches responded")
        fmt.footer()
        return 1

    fmt.step_ok(f"{len(topo['nodes'])} nodes, {len(topo['edges'])} links")
    fmt.blank()

    # Save snapshot
    filepath = _save_topology(cfg, topo)
    fmt.step_ok(f"Saved to {filepath}")
    fmt.blank()

    # Display summary
    _display_topology(topo)

    logger.info("topology_discover", nodes=len(topo["nodes"]), edges=len(topo["edges"]))
    fmt.footer()
    return 0


def cmd_topology_show(cfg: FreqConfig, pack, args) -> int:
    """Show the most recent topology discovery."""
    topo = _load_latest(cfg)
    if not topo:
        fmt.warn("No topology data. Run: freq net topology discover")
        return 1

    fmt.header("Network Topology", breadcrumb="FREQ > Net > Topology")
    fmt.blank()
    fmt.line(f"{fmt.C.DIM}Discovered: {topo.get('discovered_at', '?')}{fmt.C.RESET}")
    fmt.blank()

    _display_topology(topo)

    fmt.footer()
    return 0


def cmd_topology_export(cfg: FreqConfig, pack, args) -> int:
    """Export topology as DOT (Graphviz) or JSON."""
    export_format = getattr(args, "format", "dot")
    topo = _load_latest(cfg)
    if not topo:
        fmt.warn("No topology data. Run: freq net topology discover")
        return 1

    if export_format == "json":
        print(json.dumps(topo, indent=2))
        return 0

    # DOT format
    dot = _to_dot(topo)
    output = getattr(args, "output", None)
    if output:
        with open(output, "w") as f:
            f.write(dot)
        fmt.success(f"DOT graph written to {output}")
        fmt.info("Render with: dot -Tpng -o topology.png " + output)
    else:
        print(dot)

    return 0


def cmd_topology_diff(cfg: FreqConfig, pack, args) -> int:
    """Compare current topology against a previous snapshot."""
    snapshots = _list_snapshots(cfg)
    if len(snapshots) < 2:
        fmt.warn("Need at least 2 snapshots to diff. Run discover again.")
        return 1

    fmt.header("Topology Diff", breadcrumb="FREQ > Net > Topology")
    fmt.blank()

    # Load newest and second-newest
    with open(snapshots[0]) as f:
        new_topo = json.load(f)
    with open(snapshots[1]) as f:
        old_topo = json.load(f)

    fmt.line(f"{fmt.C.DIM}Comparing: {os.path.basename(snapshots[1])} → {os.path.basename(snapshots[0])}{fmt.C.RESET}")
    fmt.blank()

    # Node diff
    old_nodes = {n["name"] for n in old_topo.get("nodes", [])}
    new_nodes = {n["name"] for n in new_topo.get("nodes", [])}
    added_nodes = new_nodes - old_nodes
    removed_nodes = old_nodes - new_nodes

    if added_nodes:
        fmt.line(f"{fmt.C.GREEN}+ New nodes:{fmt.C.RESET}")
        for n in sorted(added_nodes):
            fmt.line(f"  {fmt.C.GREEN}+ {n}{fmt.C.RESET}")
        fmt.blank()

    if removed_nodes:
        fmt.line(f"{fmt.C.RED}- Removed nodes:{fmt.C.RESET}")
        for n in sorted(removed_nodes):
            fmt.line(f"  {fmt.C.RED}- {n}{fmt.C.RESET}")
        fmt.blank()

    # Edge diff
    old_edges = {
        _edge_key(e["from_device"], e["from_port"], e["to_device"], e["to_port"]) for e in old_topo.get("edges", [])
    }
    new_edges = {
        _edge_key(e["from_device"], e["from_port"], e["to_device"], e["to_port"]) for e in new_topo.get("edges", [])
    }
    added_edges = new_edges - old_edges
    removed_edges = old_edges - new_edges

    if added_edges:
        fmt.line(f"{fmt.C.GREEN}+ New links:{fmt.C.RESET}")
        for e in sorted(added_edges):
            fmt.line(f"  {fmt.C.GREEN}+ {e}{fmt.C.RESET}")
        fmt.blank()

    if removed_edges:
        fmt.line(f"{fmt.C.RED}- Removed links:{fmt.C.RESET}")
        for e in sorted(removed_edges):
            fmt.line(f"  {fmt.C.RED}- {e}{fmt.C.RESET}")
        fmt.blank()

    if not added_nodes and not removed_nodes and not added_edges and not removed_edges:
        fmt.success("No topology changes detected")

    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Display Helpers
# ---------------------------------------------------------------------------


def _display_topology(topo):
    """Display topology summary."""
    nodes = topo.get("nodes", [])
    edges = topo.get("edges", [])

    # Nodes by type
    switch_nodes = [n for n in nodes if n.get("type") == "switch"]
    discovered_nodes = [n for n in nodes if n.get("type") == "discovered"]

    fmt.line(f"{fmt.C.BOLD}Nodes ({len(nodes)}){fmt.C.RESET}")
    fmt.table_header(("Device", 24), ("IP", 16), ("Model", 24), ("Type", 12))
    for n in nodes:
        type_color = fmt.C.CYAN if n["type"] == "switch" else fmt.C.DIM
        fmt.table_row(
            (n.get("name", "?"), 24),
            (n.get("ip", ""), 16),
            (n.get("model", ""), 24),
            (f"{type_color}{n.get('type', '?')}{fmt.C.RESET}", 12),
        )
    fmt.blank()

    if edges:
        fmt.line(f"{fmt.C.BOLD}Links ({len(edges)}){fmt.C.RESET}")
        fmt.table_header(("From", 20), ("Port", 20), ("To", 20), ("Port", 20))
        for e in edges:
            fmt.table_row(
                (e.get("from_device", ""), 20),
                (e.get("from_port", ""), 20),
                (e.get("to_device", ""), 20),
                (e.get("to_port", ""), 20),
            )
        fmt.blank()


def _to_dot(topo):
    """Convert topology to Graphviz DOT format."""
    lines = ["graph network {", "  rankdir=LR;", "  node [shape=box, style=filled, fillcolor=lightblue];", ""]

    # Nodes
    for n in topo.get("nodes", []):
        name = n.get("name", "?").replace('"', '\\"')
        ip = n.get("ip", "")
        model = n.get("model", "")
        label = f"{name}"
        if ip:
            label += f"\\n{ip}"
        if model:
            label += f"\\n{model}"
        fill = "lightblue" if n.get("type") == "switch" else "lightyellow"
        lines.append(f'  "{name}" [label="{label}", fillcolor={fill}];')

    lines.append("")

    # Edges
    for e in topo.get("edges", []):
        from_dev = e.get("from_device", "").replace('"', '\\"')
        to_dev = e.get("to_device", "").replace('"', '\\"')
        from_port = e.get("from_port", "")
        to_port = e.get("to_port", "")
        label = ""
        if from_port or to_port:
            label = f"{from_port} -- {to_port}"
        lines.append(f'  "{from_dev}" -- "{to_dev}" [label="{label}"];')

    lines.append("}")
    return "\n".join(lines)
