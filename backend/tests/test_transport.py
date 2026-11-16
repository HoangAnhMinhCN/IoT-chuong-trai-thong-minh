from __future__ import annotations

import asyncio
import re
import ssl
import threading
from types import SimpleNamespace

import pytest

from iot_core import transport as module
from iot_core.config import GatewayConfig
from iot_core.gateway import DeviceGateway


class FakePaho:
    def __init__(self, *args, **kwargs):
        self.mid = 0
        self.stopped = False
        self.retained = False
        self.connected = False

    def username_pw_set(self, *args):
        pass

    def tls_set_context(self, context):
        self.tls_context = context

    def reconnect_delay_set(self, *args):
        assert args == (1, 10)

    def connect_async(self, *args):
        pass

    def is_connected(self):
        return self.connected

    def loop_start(self):
        self.connected = True
        self.on_connect(self, None, None, SimpleNamespace(is_failure=False), None)

    def loop_stop(self):
        self.stopped = True

    def disconnect(self):
        pass

    def subscribe(self, topic, qos):
        self.mid += 1
        self.on_subscribe(self, None, self.mid, [SimpleNamespace(is_failure=False)], None)
        if self.retained:
            self.on_message(self, None, SimpleNamespace(topic='iot/v1/test/status', payload=b'retained'))
        return (0, self.mid)

    def publish(self, *args, **kwargs):
        self.mid += 1
        # Exercise the paho callback arriving before publish() returns its mid.
        self.on_publish(self, None, self.mid, None, None)
        return SimpleNamespace(rc=0, mid=self.mid)


def test_gateway_broker_endpoint_defaults_and_local_overrides(monkeypatch, tmp_path):
    monkeypatch.setattr(module.mqtt, 'Client', FakePaho)
    for key in ('IOT_BROKER_HOST', 'IOT_BROKER_PORT', 'IOT_BROKER_TLS'):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / 'deployment.env'
    env_file.write_text('IOT_BROKER_HOST=127.0.0.1\nIOT_BROKER_PORT=1883\nIOT_BROKER_TLS=0\n')
    transport = DeviceGateway.from_config(GatewayConfig.from_env(env_file)).transport
    assert (transport.host, transport.port) == ('127.0.0.1', 1883)
    assert not hasattr(transport._client, 'tls_context')

    monkeypatch.setenv('IOT_BROKER_HOST', 'mqtt.example.com')
    monkeypatch.setenv('IOT_BROKER_PORT', '20883')
    monkeypatch.setenv('IOT_BROKER_TLS', '1')
    transport = DeviceGateway.from_config(GatewayConfig.from_env(env_file)).transport
    assert (transport.host, transport.port) == ('mqtt.example.com', 20883)
    assert transport._client.tls_context.verify_mode == ssl.CERT_REQUIRED
    assert transport._client.tls_context.check_hostname

    monkeypatch.setenv('IOT_BROKER_TLS', 'typo')
    with pytest.raises(ValueError, match='IOT_BROKER_TLS'):
        GatewayConfig.from_env(env_file)


async def test_callback_order_thread_handoff_and_publish(monkeypatch, caplog):
    monkeypatch.setattr(module.mqtt, 'Client', FakePaho)
    transport = module.MqttTransport('localhost', 1883, client_id='backend')
    assert re.fullmatch(r'backend-[0-9a-f]{6}', transport.client_id)
    order = []
    loop_thread = threading.get_ident()
    async def connected(value):
        await asyncio.sleep(0)
        order.append(('connected', value, threading.get_ident()))
    def handler(topic, payload):
        order.append(('message', payload, threading.get_ident()))
        raise RuntimeError('handler exploded')
    transport.on_connection_change(connected)
    await transport.subscribe('iot/v1/+/status', handler)
    transport._client.retained = True
    await transport.start()
    await asyncio.sleep(0)
    await transport.publish('test', b'payload', qos=0)
    await transport.publish('test', b'payload', qos=1)
    assert order[:2] == [('connected', True, loop_thread), ('message', b'retained', loop_thread)]
    assert 'handler exploded' in caplog.text
    order.clear()
    await asyncio.to_thread(transport._on_connect, transport._client, None, None,
                            SimpleNamespace(is_failure=False), None)
    for _ in range(5):
        await asyncio.sleep(0)
    assert order[:2] == [('connected', True, loop_thread), ('message', b'retained', loop_thread)]
    await transport.stop()
    assert not transport.connected and transport._client.stopped


async def test_connect_timeout_cleanup(monkeypatch):
    monkeypatch.setattr(module.mqtt, 'Client', FakePaho)
    transport = module.MqttTransport('localhost', 1883, connect_timeout_s=0.01)
    transport._client.loop_start = lambda: None
    with pytest.raises(TimeoutError):
        await transport.start()
    assert transport._client.stopped
