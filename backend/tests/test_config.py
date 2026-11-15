import pytest

from iot_core import GatewayConfig


def test_adopt_devices_defaults_to_false(monkeypatch):
    monkeypatch.delenv('IOT_ADOPT_DEVICES', raising=False)
    assert GatewayConfig().adopt_devices is False
    assert GatewayConfig.from_env().adopt_devices is False


@pytest.mark.parametrize('value, expected', [
    ('1', True), ('true', True), ('TRUE', True), ('TrUe', True),
    ('yes', True), ('YES', True), ('YeS', True),
    ('0', False), ('false', False), ('FALSE', False), ('no', False),
    ('', False), ('2', False), ('on', False), ('invalid', False),
])
def test_adopt_devices_from_process_env(monkeypatch, value, expected):
    monkeypatch.setenv('IOT_ADOPT_DEVICES', value)
    assert GatewayConfig.from_env().adopt_devices is expected


@pytest.mark.parametrize('value, expected', [('YeS', True), ('invalid', False)])
def test_adopt_devices_from_env_file(monkeypatch, tmp_path, value, expected):
    monkeypatch.delenv('IOT_ADOPT_DEVICES', raising=False)
    env_file = tmp_path / 'gateway.env'
    env_file.write_text(f'IOT_ADOPT_DEVICES={value}\n', encoding='utf-8')
    assert GatewayConfig.from_env(env_file).adopt_devices is expected


@pytest.mark.parametrize('file_value, process_value, expected', [
    ('yes', 'false', False), ('no', 'TRUE', True), ('yes', '', False),
])
def test_adopt_devices_process_env_overrides_file(
        monkeypatch, tmp_path, file_value, process_value, expected):
    env_file = tmp_path / 'gateway.env'
    env_file.write_text(f'IOT_ADOPT_DEVICES={file_value}\n', encoding='utf-8')
    monkeypatch.setenv('IOT_ADOPT_DEVICES', process_value)
    assert GatewayConfig.from_env(env_file).adopt_devices is expected
