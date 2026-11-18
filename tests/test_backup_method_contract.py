from types import SimpleNamespace
from unittest.mock import patch
import pytest
from freq.api import dr, helpers

@pytest.mark.parametrize("method", ["GET", "HEAD", "PUT", "DELETE", "POST"])
@pytest.mark.parametrize("action", ["create", "export", "prune", "list", "status"])
def test_dispatch_obeys_method(method, action):
    handler = SimpleNamespace(command=method, path="/api/backup?action=" + action)
    with patch.object(dr, "_check_session_role", return_value=("operator", None)), patch.object(dr, "load_config"), patch.object(dr, "json_response"), patch.object(helpers, "json_response") as refused, patch("freq.modules.backup.cmd_backup", return_value=0) as run:
        dr.handle_backup(handler)
        allowed = method == "POST" or action in {"list", "status"}
        assert run.call_count == int(allowed)
        if not allowed:
            assert refused.call_args.args[2] == 405
