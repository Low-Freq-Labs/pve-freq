"""Durable selection contracts for zero-state browser setup.

The contract is non-secret operator intent. Credential values remain in the
encrypted vault; this module stores only normalized inventory and presence
metadata needed to validate later setup stages.
"""

import base64
import hashlib
import json
import os
import secrets
import time
import uuid

from freq.core.setup_state import SCHEMA

MAX_SELECTIONS = 4096
MAX_CREDENTIAL_REQUEST_IDS = 32
MAX_RESOURCE_ID_BYTES = 512
_CONTRACT_FILENAME = "zero-state-contract.json"
_PLACEMENTS = {"production", "lab"}
_DISPOSITIONS = {"owned", "acknowledged"}
_SECRET_FIELDS = {"password", "api_key", "ssh_private_key", "sudo_password"}
_DEVICE_REQUIREMENTS = {
    "truenas": [["username", "password"], ["api_key"], ["username", "ssh_private_key"]],
    "pfsense": [["username", "password"], ["api_key"], ["username", "ssh_private_key"]],
    "idrac": [["username", "password"], ["username", "ssh_private_key"]],
    "switch": [["username", "password"], ["username", "ssh_private_key"]],
}
_DEVICE_ALLOWED_FIELDS = {
    "truenas": {"username", "password", "api_key", "ssh_private_key", "sudo_password"},
    "pfsense": {"username", "password", "api_key", "ssh_private_key", "sudo_password"},
    "idrac": {"username", "password", "ssh_private_key"},
    "switch": {"username", "password", "ssh_private_key", "sudo_password"},
}


class SetupContractError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        field: str = "",
        status: int = 400,
        details: list | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.field = field
        self.status = status
        self.details = list(details or [])[:50]


def contract_path(cfg) -> str:
    return os.path.join(cfg.data_dir, "setup", _CONTRACT_FILENAME)


def _atomic_write(path: str, payload: dict) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    os.chmod(tmp, 0o600)
    if os.path.exists(path):
        try:
            stat = os.stat(path)
            os.chown(tmp, stat.st_uid, stat.st_gid)
        except OSError:
            pass
    os.replace(tmp, path)


def save_setup_contract(cfg, contract: dict) -> None:
    _atomic_write(contract_path(cfg), contract)


def load_setup_contract(cfg) -> dict:
    try:
        with open(contract_path(cfg), encoding="utf-8") as handle:
            contract = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(contract, dict) or contract.get("schema") != SCHEMA:
        return {}
    return contract


def clear_setup_contract(cfg) -> None:
    try:
        os.unlink(contract_path(cfg))
    except FileNotFoundError:
        pass


def _request_uuid(value, field="client_request_id") -> str:
    request_id = str(value or "").strip()
    if not request_id:
        return ""
    try:
        uuid.UUID(request_id)
    except ValueError as exc:
        raise SetupContractError(
            "invalid_client_request_id",
            "client_request_id must be a UUID.",
            field,
        ) from exc
    return request_id


def _resource_index(discovery: dict) -> dict:
    results = discovery.get("results") if isinstance(discovery, dict) else None
    if not isinstance(results, dict):
        raise SetupContractError(
            "discovery_state_invalid",
            "Discovery results are unavailable or malformed.",
            status=500,
        )
    indexed = {}
    for group, rows in (("virtual", results.get("resources")), ("device", results.get("devices"))):
        if not isinstance(rows, list):
            raise SetupContractError(
                "discovery_state_invalid",
                "Discovery results are unavailable or malformed.",
                status=500,
            )
        for row in rows:
            resource_id = str((row or {}).get("id") or "") if isinstance(row, dict) else ""
            if (
                not resource_id
                or len(resource_id.encode("utf-8")) > MAX_RESOURCE_ID_BYTES
                or resource_id in indexed
            ):
                raise SetupContractError(
                    "discovery_state_invalid",
                    "Discovery contains an invalid resource identity.",
                    status=500,
                )
            indexed[resource_id] = (group, row)
    if len(indexed) > MAX_SELECTIONS:
        raise SetupContractError(
            "discovery_result_limit_exceeded",
            "Discovery contains too many selectable resources.",
            status=422,
        )
    return indexed


def _selection_details(indexed: dict, selections) -> tuple[dict, list]:
    if not isinstance(selections, list) or len(selections) > MAX_SELECTIONS:
        raise SetupContractError(
            "invalid_selections",
            f"selections must be a list with at most {MAX_SELECTIONS} rows.",
            "selections",
        )
    selected = {}
    errors = []
    for index, selection in enumerate(selections):
        if not isinstance(selection, dict):
            errors.append({"resource_id": "", "code": "invalid_selection"})
            continue
        unknown = sorted(set(selection) - {"resource_id", "disposition", "placement"})
        resource_id = str(selection.get("resource_id") or "").strip()
        bounded_id = resource_id[:256]
        if unknown:
            errors.append({"resource_id": bounded_id, "code": "unsupported_field"})
            continue
        if not resource_id:
            errors.append({"resource_id": "", "code": "required_resource_id"})
            continue
        if len(resource_id.encode("utf-8")) > MAX_RESOURCE_ID_BYTES:
            errors.append({"resource_id": bounded_id, "code": "invalid_resource_id"})
            continue
        if resource_id in selected:
            errors.append({"resource_id": bounded_id, "code": "duplicate_resource"})
            continue
        if resource_id not in indexed:
            errors.append({"resource_id": bounded_id, "code": "unknown_resource"})
            continue
        disposition = str(selection.get("disposition") or "").strip().lower()
        placement = str(selection.get("placement") or "").strip().lower()
        if disposition not in _DISPOSITIONS:
            errors.append({"resource_id": bounded_id, "code": "invalid_disposition"})
            continue
        if disposition == "owned" and placement not in _PLACEMENTS:
            errors.append({"resource_id": bounded_id, "code": "placement_required"})
            continue
        if disposition == "acknowledged" and placement:
            errors.append({"resource_id": bounded_id, "code": "placement_not_allowed"})
            continue
        selected[resource_id] = {
            "resource_id": resource_id,
            "disposition": disposition,
            **({"placement": placement} if disposition == "owned" else {}),
        }
    missing = sorted(set(indexed) - set(selected))
    errors.extend({"resource_id": resource_id, "code": "missing_selection"} for resource_id in missing)
    return selected, errors


def _device_row(resource_id: str, raw: dict, placement: str = "") -> dict:
    row = {
        "resource_id": resource_id,
        "kind": str(raw.get("kind") or "unknown").strip().lower(),
        "label": str(raw.get("label") or raw.get("name") or resource_id)[:160],
        "host": str(raw.get("host") or "")[:255],
    }
    if placement:
        row["placement"] = placement
    return row


def build_setup_contract(
    body: dict,
    discovery: dict,
    *,
    setup_id: str,
    previous: dict | None = None,
    now: float | None = None,
) -> dict:
    """Validate complete selections and return one normalized contract."""
    if not isinstance(body, dict):
        raise SetupContractError("invalid_json", "JSON object required.")
    allowed = {"schema", "setup_id", "discovery_id", "client_request_id", "selections"}
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise SetupContractError(
            "unsupported_field",
            f"Unsupported contract field: {unknown[0]}",
            unknown[0],
        )
    if str(body.get("schema") or "") != SCHEMA:
        raise SetupContractError("unsupported_schema", "Unsupported setup schema.", "schema")
    if str(body.get("setup_id") or "") != setup_id:
        raise SetupContractError("setup_expired", "The setup identity is stale.", "setup_id", 410)
    discovery_id = str(body.get("discovery_id") or "").strip()
    if not discovery_id or discovery_id != str(discovery.get("id") or ""):
        raise SetupContractError("stale_discovery", "The discovery identity is stale.", "discovery_id", 409)
    request_id = _request_uuid(body.get("client_request_id"))
    indexed = _resource_index(discovery)
    selected, errors = _selection_details(indexed, body.get("selections"))
    if errors:
        raise SetupContractError(
            "incomplete_selections",
            "Every discovered resource requires exactly one valid disposition.",
            "selections",
            422,
            errors,
        )

    owned_vmids = []
    template_vmids = []
    acknowledged_vmids = []
    owned_devices = []
    acknowledged_devices = []
    requirements = []
    normalized_selections = []
    for resource_id in sorted(selected):
        choice = selected[resource_id]
        group, raw = indexed[resource_id]
        normalized_selections.append(choice)
        if group == "virtual":
            try:
                vmid = int(raw.get("vmid"))
            except (TypeError, ValueError) as exc:
                raise SetupContractError(
                    "discovery_state_invalid",
                    "Discovery contains an invalid VM identity.",
                    status=500,
                ) from exc
            if choice["disposition"] == "acknowledged":
                acknowledged_vmids.append(vmid)
            elif str(raw.get("kind") or "").lower() == "template":
                template_vmids.append(vmid)
            else:
                owned_vmids.append(vmid)
            continue

        kind = str(raw.get("kind") or "unknown").strip().lower()
        if choice["disposition"] == "acknowledged":
            acknowledged_devices.append(_device_row(resource_id, raw))
            continue
        if kind not in _DEVICE_REQUIREMENTS:
            raise SetupContractError(
                "unsupported_device_kind",
                "Unknown device kinds are acknowledged-only in zero-state-web-v1.",
                "selections",
                422,
                [{"resource_id": resource_id, "code": "unsupported_device_kind"}],
            )
        owned_devices.append(_device_row(resource_id, raw, choice["placement"]))
        requirements.append(
            {
                "resource_id": resource_id,
                "kind": kind,
                "required_any": _DEVICE_REQUIREMENTS[kind],
                "allowed_fields": sorted(_DEVICE_ALLOWED_FIELDS[kind]),
            }
        )

    normalized = {
        "schema": SCHEMA,
        "discovery_id": discovery_id,
        "selections": normalized_selections,
        "owned_vmids": sorted(set(owned_vmids)),
        "template_vmids": sorted(set(template_vmids)),
        "acknowledged_out_of_contract_vmids": sorted(set(acknowledged_vmids)),
        "owned_devices": owned_devices,
        "acknowledged_devices": acknowledged_devices,
    }
    digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    old = previous if isinstance(previous, dict) else {}
    clock = time.time() if now is None else now
    revision = int(old.get("revision") or 0) + 1
    return {
        **normalized,
        "setup_id": setup_id,
        "contract_id": secrets.token_urlsafe(24),
        "revision": revision,
        "sha256": digest,
        "client_request_id": request_id,
        "credential_request_ids": [],
        "credential_requirements": requirements,
        "created_at": clock,
        "updated_at": clock,
    }


def contract_counts(contract: dict) -> dict:
    return {
        "owned_virtual": len(contract.get("owned_vmids") or []),
        "templates": len(contract.get("template_vmids") or []),
        "acknowledged_virtual": len(contract.get("acknowledged_out_of_contract_vmids") or []),
        "owned_devices": len(contract.get("owned_devices") or []),
        "acknowledged_devices": len(contract.get("acknowledged_devices") or []),
    }


def credential_vault_key(resource_id: str, field: str) -> str:
    digest = hashlib.sha256(resource_id.encode("utf-8")).hexdigest()[:24]
    return f"device_{digest}_{field}"


def credential_presence(contract: dict, getter) -> list[dict]:
    rows = []
    for requirement in contract.get("credential_requirements") or []:
        resource_id = requirement["resource_id"]
        allowed = set(requirement.get("allowed_fields") or [])
        stored = sorted(field for field in allowed if getter(credential_vault_key(resource_id, field)))
        stored_set = set(stored)
        complete = any(set(option).issubset(stored_set) for option in requirement.get("required_any") or [])
        rows.append(
            {
                "resource_id": resource_id,
                "required_any": [list(option) for option in requirement.get("required_any") or []],
                "stored_fields": stored,
                "complete": complete,
            }
        )
    return rows


def contract_payload(contract: dict, getter) -> dict:
    presence = credential_presence(contract, getter)
    return {
        "id": contract.get("contract_id"),
        "discovery_id": contract.get("discovery_id"),
        "revision": contract.get("revision"),
        "sha256": contract.get("sha256"),
        "counts": contract_counts(contract),
        "credential_requirements": presence,
        "ready": all(row["complete"] for row in presence),
    }


def validate_credential_request(body: dict, contract: dict, setup_id: str) -> dict:
    if not isinstance(body, dict):
        raise SetupContractError("invalid_json", "JSON object required.")
    allowed = {"schema", "setup_id", "contract_id", "client_request_id", "credentials"}
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise SetupContractError(
            "unsupported_field",
            f"Unsupported credential field: {unknown[0]}",
            unknown[0],
        )
    if str(body.get("schema") or "") != SCHEMA:
        raise SetupContractError("unsupported_schema", "Unsupported setup schema.", "schema")
    if str(body.get("setup_id") or "") != setup_id:
        raise SetupContractError("setup_expired", "The setup identity is stale.", "setup_id", 410)
    if str(body.get("contract_id") or "") != str(contract.get("contract_id") or ""):
        raise SetupContractError("stale_contract", "The selection contract is stale.", "contract_id", 409)
    request_id = _request_uuid(body.get("client_request_id"))
    credentials = body.get("credentials")
    if not isinstance(credentials, list) or len(credentials) > MAX_SELECTIONS:
        raise SetupContractError("invalid_credentials", "credentials must be a bounded list.", "credentials")
    requirements = {
        item["resource_id"]: item for item in contract.get("credential_requirements") or []
    }
    normalized = []
    seen = set()
    for index, item in enumerate(credentials):
        field = f"credentials[{index}]"
        if not isinstance(item, dict):
            raise SetupContractError("invalid_credential", "Credential row must be an object.", field)
        unknown_item = sorted(set(item) - {"resource_id", "username", "secrets"})
        if unknown_item:
            raise SetupContractError(
                "unsupported_field",
                f"Unsupported credential field: {unknown_item[0]}",
                f"{field}.{unknown_item[0]}",
            )
        resource_id = str(item.get("resource_id") or "").strip()
        if len(resource_id.encode("utf-8")) > MAX_RESOURCE_ID_BYTES:
            raise SetupContractError(
                "invalid_resource_id",
                "Credential resource identity is too large.",
                f"{field}.resource_id",
                422,
            )
        if resource_id not in requirements:
            raise SetupContractError("unknown_resource", "Credential resource is not owned.", f"{field}.resource_id", 422)
        if resource_id in seen:
            raise SetupContractError("duplicate_resource", "Credential resources must be unique.", f"{field}.resource_id", 422)
        seen.add(resource_id)
        values = {}
        if "username" in item:
            values["username"] = item.get("username")
        secrets_body = item.get("secrets", {})
        if not isinstance(secrets_body, dict):
            raise SetupContractError("invalid_credentials", "secrets must be an object.", f"{field}.secrets")
        unsupported_secrets = sorted(set(secrets_body) - _SECRET_FIELDS)
        if unsupported_secrets:
            raise SetupContractError(
                "unsupported_credential_field",
                "Credential field is not an allowed secret value.",
                f"{field}.secrets.{unsupported_secrets[0]}",
                422,
            )
        values.update(secrets_body)
        if not values:
            raise SetupContractError("required_field", "At least one credential value is required.", field)
        allowed_fields = set(requirements[resource_id].get("allowed_fields") or [])
        for name, value in values.items():
            if name not in allowed_fields:
                raise SetupContractError(
                    "unsupported_credential_field",
                    "Credential field is not allowed for this device kind.",
                    f"{field}.{name}",
                    422,
                )
            if (
                not isinstance(value, str)
                or not value
                or "\x00" in value
                or (name != "ssh_private_key" and ("\n" in value or "\r" in value))
            ):
                raise SetupContractError(
                    "invalid_credential_value",
                    "Credential value has an invalid or unsafe format.",
                    f"{field}.{name}",
                    422,
                )
            limit = 65536 if name == "ssh_private_key" else 4096
            if len(value.encode("utf-8")) > limit:
                raise SetupContractError(
                    "credential_too_large",
                    "Credential value exceeds its size limit.",
                    f"{field}.{name}",
                    422,
                )
        normalized.append({"resource_id": resource_id, "values": values})
    return {"client_request_id": request_id, "credentials": normalized}


def record_credential_request(contract: dict, request_id: str, *, now: float | None = None) -> dict:
    if request_id:
        ids = list(contract.get("credential_request_ids") or [])
        if request_id not in ids:
            ids.append(request_id)
        contract["credential_request_ids"] = ids[-MAX_CREDENTIAL_REQUEST_IDS:]
    contract["updated_at"] = time.time() if now is None else now
    return contract


def credential_storage_value(field: str, value: str) -> str:
    """Encode multiline private keys for the vault's line-oriented format."""
    if field == "ssh_private_key":
        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
        return f"base64:{encoded}"
    return value


def credential_runtime_value(field: str, value: str) -> str:
    """Decode a setup-vault value for the later init adapter."""
    if field == "ssh_private_key" and value.startswith("base64:"):
        try:
            return base64.b64decode(value[7:].encode("ascii"), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return ""
    return value


def contract_credential_keys(contract: dict) -> list[str]:
    keys = []
    for requirement in contract.get("credential_requirements") or []:
        for field in requirement.get("allowed_fields") or []:
            keys.append(credential_vault_key(requirement["resource_id"], field))
    return sorted(set(keys))
