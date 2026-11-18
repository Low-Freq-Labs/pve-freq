from types import SimpleNamespace as NS
from unittest.mock import patch
import pytest
from freq.api import observe
from freq.core.types import Host, CmdResult

@pytest.mark.parametrize('since', ['1h', '7d', "1h'; touch /tmp/no; #", '', '0h', '-1h'])
def test_stats_scope_and_query_validation(since):
    allowed = Host(ip='192.0.2.1', label='allowed', htype='linux', vmid=101)
    excluded = Host(ip='192.0.2.2', label='excluded', htype='linux', vmid=102, managed=False)
    cfg = NS(hosts=[allowed, excluded], ssh_key_path='synthetic', ssh_connect_timeout=1, ssh_max_parallel=1)
    with patch.object(observe, 'load_config', return_value=cfg), patch.object(observe, 'get_params', return_value={'since': [since]}), patch('freq.core.ssh.run_many', return_value={allowed.ip: CmdResult('2 example error', '', 0)}) as run, patch.object(observe, 'json_response') as response:
        observe.handle_logs_stats(NS())
        if since not in ['1h', '7d']:
            run.assert_not_called()
            assert response.call_args.args[2] == 400
        else:
            assert run.call_args.kwargs['hosts'] == [allowed]
            assert run.call_args.kwargs['cfg'] is cfg
            assert response.call_args.args[1]['total_errors'] == 2
            assert response.call_args.args[1]['hosts_scanned'] == 1
