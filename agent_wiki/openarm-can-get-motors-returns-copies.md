---
title: openarm_can get_motors() Returns Copies, Not Handles
category: debugging
tags:
  - openarm
  - openarm_can
  - gripper
  - demo
  - nanobind
sources:
  - external/openarm_can_1.2.2/src/openarm/damiao_motor/dm_motor_device_collection.cpp:126
  - external/openarm_can_1.2.2/include/openarm/damiao_motor/dm_motor_device.hpp:40
  - tools/openarm-can-demo:98
  - docs/WORKSTATION_CHANGELOG.md
confidence: high
---

# openarm_can get_motors() Returns Copies, Not Handles

`DMDeviceCollection::get_motors()` returns fresh **copies** of the motors on every
call. A `Motor` captured into a variable is a snapshot frozen at that instant and will
never reflect later CAN feedback, in C++ or through the Python bindings.

## Evidence

```cpp
// include/openarm/damiao_motor/dm_motor_device.hpp:40
Motor& DMCANDevice::get_motor() { return motor_; }          // live reference

// src/openarm/damiao_motor/dm_motor_device_collection.cpp:126
std::vector<Motor> DMDeviceCollection::get_motors() const {
    std::vector<Motor> motors;
    for (auto dm_device : get_dm_devices()) {
        motors.push_back(dm_device->get_motor());            // push_back copies
    }
    return motors;                                           // returned by value
}
```

`get_motor()` hands out a live reference, but `get_motors()` copies each one into a
vector returned by value. The Python binding (`nanobind`) therefore yields snapshots.

## How it bit us

`tools/openarm-can-demo`'s `command_gripper_position()` did:

```python
motor = gripper.get_motors()[0]          # snapshot, frozen from here on
while ...:
    gripper.mit_control_all([...])       # commands sent, gripper really moves
    openarm.recv_all()                   # feedback received, live motor_ updates
    observed.append(float(motor.get_position()))   # re-reads the frozen snapshot
```

Result: **every demo log in the repo** - 15 arm-sides, Follower and Leader, 2026-05
through 2026-09 - printed `travel=0.000000` with `min == max == start == end` for all
~600 samples of a phase, without one exception. The gripper moved exactly as operators
observed; only the measurement was blind. Endpoint values stayed correct because each
phase re-reads at entry, which is why `_parse_official_demo_stdout()` derives travel
from `open_observed_at_close_start` (the *next* phase's start) rather than from the
phase's own `travel=`.

It was the only one of ten `get_motors()` call sites in that file that cached the
result; every other site calls `get_motors()` fresh each time and was unaffected.

## Rule

Never hold a `Motor` from `get_motors()` across a control loop or any wait. Read it
fresh each time:

```python
def _gripper_position(gripper):
    return float(gripper.get_motors()[0].get_position())
```

Reading once at entry is fine and often correct - a ramp must interpolate from where
the phase began, so `start` should NOT be re-read. Only repeated sampling is affected.

## Related

- The zero calibration script carries its own guard for a related symptom:
  `raise RuntimeError("openarm_can gripper position feedback is not synchronized; refusing dynamic zero")`.
- Fixed in workstation `0.14.0-gripper-sampling-and-progress-check`, together with a
  midpoint progress check that stops a gripper which is not following, instead of
  holding it against its hard stop (openarm_can#81 overheating).
- Not yet checked against openarm_can 1.4.0; the upstream code may or may not differ.
- See [[openarm-factory-arm-acceptance-flow]].
