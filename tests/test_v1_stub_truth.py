from types import SimpleNamespace
from unittest.mock import patch
import pytest
from freq.api import v1_stubs
routes = {}
v1_stubs.register(routes)

@pytest.mark.parametrize("route", sorted(routes))
def test_stub_emits_unavailable(route):
    with patch.object(v1_stubs, "get_param", return_value="example.invalid"), patch.object(v1_stubs, "json_response") as response:
        routes[route](SimpleNamespace())
        body = response.call_args.args[1]
        assert body["implemented"] is False
        assert body["available"] is False
        assert body["capability_status"] == "unimplemented"
