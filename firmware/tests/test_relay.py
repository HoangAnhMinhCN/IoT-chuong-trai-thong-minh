import pytest

from actuators import build_actuators
from actuators.relay import Relay
from app import App
from test_actuators import tick_at
from test_commands import invoke


def config(**extra):
    return dict(driver="relay", name="relay", pin=25, **extra)


@pytest.fixture
def actuator_app(ctx):
    cfg = dict(ctx.config, actuators=[
        dict(driver="servo", name="servo", pin=26), config()])
    instance = App(cfg, ctx.identity)
    instance.link = ctx.link
    try:
        yield instance
    finally:
        instance._timer.deinit()
        for actuator in instance.actuators:
            actuator.deinit()


def test_build_relay_and_meta():
    actuators = build_actuators([config()])
    assert len(actuators) == 1
    relay = actuators[0]
    assert isinstance(relay, Relay)
    assert relay.meta() == dict(name="relay", driver="relay", pin=25)
    assert relay.output.pin == 25


@pytest.mark.parametrize("active_low,off_level", [(False, 0), (True, 1)])
def test_boot_stays_off_without_on_glitch(active_low, off_level, board_environment):
    relay = Relay(config(active_low=active_low))
    assert relay.output.values
    assert all(level == off_level for level in relay.output.values)
    assert relay.output.value() == off_level
    assert relay.state() == {"on": False}
    tick_at(relay, board_environment, 10000)
    assert relay.output.value() == off_level
    assert all(level == off_level for level in relay.output.values)
    assert relay.state() == {"on": False}


@pytest.mark.parametrize("active_low,off_level,on_level", [(False, 0, 1), (True, 1, 0)])
def test_initial_true_turns_on(active_low, off_level, on_level):
    relay = Relay(config(active_low=active_low, initial=True))
    assert relay.output.values[0] == off_level
    assert relay.output.values[-1] == on_level
    assert relay.state() == {"on": True}


@pytest.mark.parametrize("active_low,on_level,off_level", [(False, 1, 0), (True, 0, 1)])
def test_set_writes_levels_for_both_polarities(active_low, on_level, off_level):
    relay = Relay(config(active_low=active_low))
    writes = relay.output.values[:]
    relay.set(True)
    assert relay.output.values == writes + [on_level]
    assert relay.state() == {"on": True}
    relay.set(False)
    assert relay.output.values == writes + [on_level, off_level]
    assert relay.state() == {"on": False}


@pytest.mark.parametrize("on", [1, "true", None])
def test_set_rejects_non_boolean_on(on):
    relay = Relay(config())
    writes = relay.output.values[:]
    with pytest.raises(ValueError):
        relay.set(on)
    assert relay.output.values == writes
    assert relay.state() == {"on": False}


@pytest.mark.parametrize("origin", [250, (1 << 30) - 50])
@pytest.mark.parametrize("duration_ms", [100, 86400000])
def test_duration_auto_off_at_deadline(board_environment, origin, duration_ms):
    board_environment[0] = origin
    relay = Relay(config())
    relay.set(True, duration_ms=duration_ms)
    assert relay.state() == dict(on=True, off_in_ms=duration_ms)
    writes = relay.output.values[:]
    tick_at(relay, board_environment, origin + duration_ms - 1)
    assert relay.state() == dict(on=True, off_in_ms=1)
    assert relay.output.values == writes
    tick_at(relay, board_environment, origin + duration_ms)
    assert relay.state() == {"on": False}
    assert relay.output.values == writes + [0]
    tick_at(relay, board_environment, origin + duration_ms + 1000)
    assert relay.output.values == writes + [0]


def test_duration_requires_on():
    relay = Relay(config())
    with pytest.raises(ValueError):
        relay.set(False, duration_ms=100)
    assert relay.state() == {"on": False}


@pytest.mark.parametrize("duration_ms", [99, 86400001, 1.5, True])
def test_invalid_duration(duration_ms):
    relay = Relay(config())
    writes = relay.output.values[:]
    with pytest.raises(ValueError):
        relay.set(True, duration_ms=duration_ms)
    assert relay.output.values == writes
    assert relay.state() == {"on": False}


def test_switching_off_cancels_auto_off(board_environment):
    relay = Relay(config())
    relay.set(True, duration_ms=100)
    tick_at(relay, board_environment, 50)
    relay.set(False)
    assert relay.state() == {"on": False}
    writes = relay.output.values[:]
    tick_at(relay, board_environment, 100)
    assert relay.output.values == writes
    # A later unlimited activation must also survive the old deadline.
    relay.set(True)
    tick_at(relay, board_environment, 1000)
    assert relay.state() == {"on": True}
    assert relay.output.value() == 1


@pytest.mark.parametrize("duration_ms,expected_ms", [(None, 500), (1000, 500), (100, 100)])
def test_max_on_caps_duration(board_environment, duration_ms, expected_ms):
    relay = Relay(config(max_on_ms=500))
    relay.set(True, duration_ms=duration_ms)
    assert relay.state() == dict(on=True, off_in_ms=expected_ms)
    tick_at(relay, board_environment, expected_ms - 1)
    assert relay.state() == dict(on=True, off_in_ms=1)
    tick_at(relay, board_environment, expected_ms)
    assert relay.state() == {"on": False}
    assert relay.output.value() == 0


def test_commands_select_only_matching_driver(actuator_app, board_environment):
    relay = actuator_app.actuator("relay")
    servo = actuator_app.actuator("servo")
    assert invoke(actuator_app, "relay_set", dict(on=True, duration_ms=100)) == dict(
        re="cmd-1", ok=True, result=dict(on=True, off_in_ms=100))
    assert relay.output.value() == 1
    assert invoke(actuator_app, "servo_set", dict(angle=45)) == dict(
        re="cmd-1", ok=True, result=dict(angle=45, running=False, angles=[], step_ms=1000))
    assert servo.angle == 45
    board_environment[0] = 100
    actuator_app._timer.fire()
    assert relay.state() == {"on": False}
    assert relay.output.value() == 0


@pytest.mark.parametrize("command,args", [
    ("relay_set", dict(name="servo", on=True)),
    ("servo_set", dict(name="relay", angle=45)),
])
def test_commands_reject_wrong_driver(actuator_app, command, args):
    response = invoke(actuator_app, command, args)
    assert response["ok"] is False
    assert response["error"]["code"] == "actuator_not_found"


@pytest.mark.parametrize("args", [
    {}, dict(on="yes"), dict(on=True, extra=1), dict(on=False, duration_ms=100),
])
def test_relay_command_bad_args(actuator_app, args):
    response = invoke(actuator_app, "relay_set", args)
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_args"


def test_relay_command_without_actuators(ctx):
    assert ctx.actuators == []
    response = invoke(ctx, "relay_set", dict(on=True))
    assert response["ok"] is False
    assert response["error"]["code"] == "actuator_not_found"


def test_actuator_state_all_and_named(actuator_app):
    invoke(actuator_app, "relay_set", dict(on=True, duration_ms=100))
    invoke(actuator_app, "servo_set", dict(angle=45))
    relay_state = dict(on=True, off_in_ms=100)
    assert invoke(actuator_app, "actuator_state", {}) == dict(
        re="cmd-1", ok=True, result=dict(
            relay=relay_state, servo=dict(angle=45, running=False, angles=[], step_ms=1000)))
    assert invoke(actuator_app, "actuator_state", dict(name="relay")) == dict(
        re="cmd-1", ok=True, result=relay_state)


@pytest.mark.parametrize("args,code", [
    (dict(name="missing"), "actuator_not_found"),
    (dict(extra=1), "bad_args"),
])
def test_actuator_state_errors(actuator_app, args, code):
    response = invoke(actuator_app, "actuator_state", args)
    assert response["ok"] is False
    assert response["error"]["code"] == code


def test_app_lookup_filters_by_driver(actuator_app):
    assert actuator_app.actuator(None) is None
    assert actuator_app.actuator(None, "relay") is actuator_app.actuator("relay")
    assert isinstance(actuator_app.actuator(None, "relay"), Relay)
    assert actuator_app.actuator(None, "servo") is actuator_app.actuator("servo")
