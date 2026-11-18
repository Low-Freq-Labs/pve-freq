from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "freq/data/web/js/app.js"
OWNER_PATH = REPO_ROOT / "tests/support/e1_f12_lab_tool_save_browser_owner.js"
NODE = shutil.which("node")

if NODE is None:
    raise RuntimeError("F12 browser owner requires Node; missing tooling is not a skip")


def _run_owner(*, payload: dict[str, str] | None = None, list_cases: bool = False) -> subprocess.CompletedProcess[str]:
    command = [NODE, str(OWNER_PATH)]
    if list_cases:
        command.append("--list")
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        input="" if payload is None else json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )


def _derived_cases() -> tuple[dict[str, object], ...]:
    completed = _run_owner(list_cases=True)
    if completed.returncode != 0:
        raise RuntimeError("F12 browser case derivation failed; Playwright/tooling errors are not skips")
    try:
        rows = tuple(json.loads(completed.stdout))
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("F12 browser case derivation returned invalid JSON") from exc
    ids = [row.get("id") for row in rows]
    if len(rows) != 8 or len(set(ids)) != len(ids) or any(not isinstance(case_id, str) for case_id in ids):
        raise RuntimeError("F12 browser case derivation is incomplete or duplicated")
    return rows


DERIVED_CASES = _derived_cases()


@pytest.mark.parametrize("case_row", DERIVED_CASES, ids=[str(row["id"]) for row in DERIVED_CASES])
def test_lt_save_config_governed_behavior(case_row: dict[str, object]) -> None:
    key = os.environ.get("PVE_FREQ_F12_TEST_KEY") or f"F12_KEY_{secrets.token_hex(24)}"
    host = f"f12-host-{secrets.token_hex(8)}.invalid"
    completed = _run_owner(
        payload={"caseId": str(case_row["id"]), "appPath": str(APP_PATH), "host": host, "key": key}
    )

    if key in completed.stdout or key in completed.stderr:
        pytest.fail("F12 browser owner leaked the entered key into process output")
    if completed.returncode != 0:
        raise RuntimeError("F12 browser owner failed; browser/tooling failures carry no behavioral credit")
    try:
        observation = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("F12 browser owner returned invalid JSON") from exc

    expected = case_row["expected"]
    assert isinstance(expected, dict)
    assert observation["caseId"] == case_row["id"]
    assert observation["dispatchCount"] == 1
    assert observation["urlMatches"] is True
    assert observation["thenable"] is True
    assert observation["keyRetained"] is expected["keyRetained"]
    assert observation["keyCleared"] is expected["keyCleared"]
    assert observation["eventClasses"] == [expected["eventClass"]]
    if expected["eventType"] == "success":
        assert observation["successCount"] == 1
        assert observation["errorCount"] == 0
        assert observation["terminalErrorClass"] is None
    else:
        assert observation["successCount"] == 0
        assert observation["errorCount"] == 1
        assert observation["terminalErrorClass"] == expected["eventClass"]
