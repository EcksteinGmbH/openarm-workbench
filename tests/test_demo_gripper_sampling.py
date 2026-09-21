"""The demo's gripper sampling, and the midpoint progress check.

`DMDeviceCollection::get_motors()` returns copies, not handles: it builds a
`std::vector<Motor>` with push_back and returns it by value. A copy captured before a
loop is a snapshot that never updates, which is why every demo log in this repo shows
`travel=0.000000` with min == max == start == end across ~600 samples of a phase. The
gripper moved exactly as the operator saw; the script re-read one frozen number.

These tests run the real `command_gripper_position` against a fake OpenArm that models
that copy semantics, so they fail if the frozen-snapshot pattern ever comes back. They
also pin the rule that matters most: this function's command stream must not change.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest


DEMO_PATH = Path(__file__).resolve().parent.parent / "tools" / "openarm-can-demo"


@pytest.fixture(scope="module")
def demo():
    """Load the extension-less script as a module, with openarm_can stubbed out."""
    stub = types.ModuleType("openarm_can")

    class MITParam:
        def __init__(self, kp, kd, q, dq, tau):
            self.kp, self.kd, self.q, self.dq, self.tau = kp, kd, q, dq, tau

        def as_tuple(self):
            return (self.kp, self.kd, self.q, self.dq, self.tau)

    stub.MITParam = MITParam
    # The demo pulls in tools/openarm_official_enable_check.py, which reads real motor
    # type constants at import time.
    stub.MotorType = type("MotorType", (), {name: name for name in ("DM8009", "DM4340", "DM4310")})
    for name in ("CANSocketType", "Motor", "OpenArm"):
        setattr(stub, name, type(name, (), {}))
    saved = sys.modules.get("openarm_can")
    sys.modules["openarm_can"] = stub

    spec = importlib.util.spec_from_loader(
        "openarm_can_demo_script", importlib.machinery.SourceFileLoader("openarm_can_demo_script", str(DEMO_PATH))
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    yield module
    if saved is None:
        del sys.modules["openarm_can"]
    else:
        sys.modules["openarm_can"] = saved


class FakeMotor:
    """A by-value snapshot, exactly like the one nanobind hands back."""

    def __init__(self, position):
        self._position = position

    def get_position(self):
        return self._position


class FakeGripper:
    def __init__(self, live):
        self._live = live

    def get_motors(self):
        # Fresh copies each call, as the C++ does. A caller that caches one gets a
        # value frozen at the moment of the call.
        return [FakeMotor(self._live.position)]

    def mit_control_all(self, params):
        self._live.commands.append(params[0].as_tuple())


class FakeArmComponent:
    def __init__(self, live):
        self._live = live

    def get_motors(self):
        return [FakeMotor(0.0) for _ in range(7)]

    def mit_control_all(self, params):
        self._live.arm_commands.append([p.as_tuple() for p in params])


class FakeOpenArm:
    """Models one gripper whose position follows the last command by `follow`."""

    def __init__(self, start=0.0, follow=1.0):
        self.position = start
        self.follow = follow
        self.commands = []
        self.arm_commands = []
        self._pending = start

    def get_arm(self):
        return FakeArmComponent(self)

    def get_gripper(self):
        return FakeGripper(self)

    def recv_all(self):
        # Feedback arrives: the live position moves toward the last commanded target.
        if self.commands:
            target = self.commands[-1][2]
            self.position += (target - self.position) * self.follow


def test_samples_track_the_moving_gripper(demo):
    arm = FakeOpenArm(start=0.0, follow=1.0)
    start, end = demo.command_gripper_position(arm, -1.0472, "OPEN", duration_s=0.15, arm_hold_q=[0.0] * 7)

    assert start == 0.0
    # The whole point: the samples must show motion, not one repeated number.
    assert end == pytest.approx(-1.0472, abs=1e-6)
    assert end != start


def test_a_cached_motor_would_have_frozen_the_samples(demo):
    # Guards the diagnosis itself: if get_motors() did return a live handle, this test
    # would be meaningless. It asserts the fake reproduces the real copy semantics.
    arm = FakeOpenArm(start=0.0, follow=1.0)
    cached = arm.get_gripper().get_motors()[0]
    arm.position = -0.9
    assert cached.get_position() == 0.0, "a captured motor must not see later feedback"
    assert arm.get_gripper().get_motors()[0].get_position() == -0.9


class FakeClock:
    """Deterministic stand-in for the `time` module: only sleep() advances it."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += float(seconds)


def test_the_command_stream_does_not_depend_on_the_sampled_position(demo, monkeypatch):
    # The ramp interpolates from `start`, read once at entry, so nothing in the
    # sampling path can feed back into the commands. With the clock pinned, a gripper
    # that follows perfectly and one that does not move at all must receive a
    # byte-identical sequence of targets - up to the point the progress check stops
    # the second one. This is what makes the sampling fix safe to ship without
    # hardware: it provably cannot change how the motor is driven.
    runs = []
    for follow in (1.0, 0.0):
        monkeypatch.setattr(demo, "time", FakeClock())
        arm = FakeOpenArm(start=0.0, follow=follow)
        demo.command_gripper_position(arm, -1.0472, "OPEN", duration_s=0.15, arm_hold_q=[0.0] * 7)
        runs.append(arm.commands)

    moving, stuck = runs
    shared = min(len(moving), len(stuck))
    assert shared > 1
    assert [cmd[2] for cmd in moving[:shared]] == [cmd[2] for cmd in stuck[:shared]]
    assert {cmd[:2] for cmd in moving} == {(5.0, 0.6)}
    # The healthy run ends commanding exactly the requested target.
    assert moving[-1][2] == pytest.approx(-1.0472, abs=1e-9)


def test_a_gripper_that_does_not_follow_is_stopped_at_the_midpoint(demo, capsys):
    # Commanding a gripper the wrong way holds it against its own hard stop for the
    # rest of the phase. That is the sustained-force case that overheats a DM4310.
    stuck = FakeOpenArm(start=0.0, follow=0.0)
    demo.command_gripper_position(stuck, -1.0472, "OPEN", duration_s=0.4, arm_hold_q=[0.0] * 7)

    output = capsys.readouterr().out
    assert "GRIPPER_ABORT" in output
    assert "aborted=True" in output
    # It stopped partway: a full run sends commands for the whole ramp plus a 20-frame tail.
    assert max(abs(cmd[2]) for cmd in stuck.commands) < 1.0472


def test_a_healthy_gripper_is_never_stopped(demo, capsys):
    # Every arm on record reached 90-98% of its target. Even a sluggish one that only
    # closes 40% of the remaining gap per cycle must run to completion.
    for follow in (1.0, 0.4, 0.2):
        arm = FakeOpenArm(start=0.0, follow=follow)
        demo.command_gripper_position(arm, -1.0472, "OPEN", duration_s=0.4, arm_hold_q=[0.0] * 7)
        assert "GRIPPER_ABORT" not in capsys.readouterr().out, f"tripped at follow={follow}"


def test_a_short_move_is_not_progress_checked(demo, capsys):
    # Below the minimum delta the check means nothing, e.g. closing from nearly closed.
    arm = FakeOpenArm(start=0.0, follow=0.0)
    demo.command_gripper_position(arm, 0.05, "CLOSE", duration_s=0.4, arm_hold_q=[0.0] * 7)
    assert "GRIPPER_ABORT" not in capsys.readouterr().out
