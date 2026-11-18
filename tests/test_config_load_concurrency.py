"""Concurrent original config loading stays coherent without bypassing source gates."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from freq.core import config, read_source_epoch
from freq.api import pve_read


@pytest.fixture
def isolated_cache(monkeypatch):
    for name, value in {'_config_cache': None, '_config_cache_ts': 0,
                        '_config_cache_install_dir': None, '_config_cache_file_state': None}.items():
        monkeypatch.setattr(config, name, value)
    for name, value in {'_gate': threading.RLock(), '_table_gate': threading.Lock(),
                        '_writers': {}, '_readers': {}, '_epoch': object(), '_reads_retired': False}.items():
        monkeypatch.setattr(read_source_epoch, name, value)
    monkeypatch.setattr(config, '_detect_ssh_key', lambda cfg: '')
    monkeypatch.setattr(config, '_detect_rsa_key', lambda cfg: '')
    monkeypatch.setattr(config, 'validate_config', lambda cfg: [])


def test_concurrent_cold_original_loads_share_one_complete_configuration(tmp_path, monkeypatch, isolated_cache):
    installation = tmp_path / 'installation'
    conf = installation / 'conf'
    conf.mkdir(parents=True)
    (conf / 'freq.toml').write_text('[pve]\nnodes = []\n')
    entered, release, second_started, second_finished = (threading.Event() for _ in range(4))
    original_listdir = config.os.listdir
    first_visits = []

    def paused_listdir(path):
        if str(path) == str(conf) and threading.current_thread().name == 'cfg-first':
            first_visits.append(path)
            entered.set()
            assert release.wait(3)
        return original_listdir(path)

    monkeypatch.setattr(config.os, 'listdir', paused_listdir)
    results, errors = [], []

    def load(second=False):
        if second:
            second_started.set()
        try:
            results.append(config.load_config(str(installation)))
        except BaseException as failure:
            errors.append(failure)
        finally:
            if second:
                second_finished.set()

    first = threading.Thread(target=load, name='cfg-first')
    second = threading.Thread(target=lambda: load(True), name='cfg-second')
    first.start()
    try:
        assert entered.wait(3)
        second.start()
        assert second_started.wait(3)
        second_finished.wait(0.15)
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert not errors, [type(error).__name__ for error in errors]
    assert len(results) == 2 and results[0] is results[1]
    assert len(first_visits) == 1
    assert read_source_epoch._writers == {} and read_source_epoch._readers == {}


@pytest.mark.parametrize('path', ['inventory', 'endpoints'])
@pytest.mark.parametrize('failure', [read_source_epoch.SourceWriteUnavailable, config.ConfigurationLoadUnavailable])
def test_configuration_source_contention_is_typed_unavailable(path, failure, monkeypatch):
    monkeypatch.setattr(pve_read, '_admit', lambda handler, role: True)
    monkeypatch.setattr(pve_read, 'load_config', Mock(side_effect=failure()))
    handler = SimpleNamespace(command='GET', _json_response=Mock())
    getattr(pve_read, 'handle_' + path)(handler)
    handler._json_response.assert_called_once_with({'error': 'configuration_unavailable'}, 503)


def test_busy_loader_does_not_start_bootstrap_or_release_an_unowned_lock(monkeypatch):
    gate = Mock()
    gate.acquire.return_value = False
    load = Mock()
    monkeypatch.setattr(config, '_CONFIG_LOAD_LOCK', gate)
    monkeypatch.setattr(config, '_load_config_unlocked', load)
    with pytest.raises(config.ConfigurationLoadUnavailable):
        config.load_config()
    load.assert_not_called()
    gate.release.assert_not_called()
