# Damiao Calibration and TIMEOUT Policy

This document records the workstation rule for Damiao motor service operations.
It is intentionally policy-only: it does not change the current factory test
sequence or motor-control behavior.

## Scope

The OpenARM workstation is responsible for:

- single-motor communication, ID/MST_ID setup, parameter readback, and safe feedback checks;
- whole-arm scan, OpenARM profile verification, official zero calibration, official Demo, and report output;
- preserving raw evidence and final factory acceptance data.

The workstation should not routinely perform vendor encoder calibration unless
Damiao provides a stable protocol, safety requirements, and a verified fixture
procedure.

## Encoder Calibrations in the Damiao Upper Software

Damiao upper software exposes two different calibration concepts:

- **Motor encoder calibration**: aligns the motor-side rotor encoder with the
  motor electrical angle used by FOC/current control. If this is wrong, the
  motor can enable abnormally, jitter, draw abnormal current, lose torque, or
  enter a fault state.
- **Output shaft encoder calibration**: aligns the output-side absolute encoder
  or reducer/output reference with the mechanical output shaft. If this is
  wrong, the reported joint position can have a large offset, jump, or disagree
  with the physical arm pose. This can look like a joint reporting an unexpected
  value such as about `0.6954 rad` after setup.

These calibrations are service/factory operations. They are different from
OpenARM zero calibration and different from changing CAN IDs.

## Recommended Commissioning Flow

1. For a new or replaced loose motor, use the Damiao upper software or a vendor
   service fixture to perform encoder calibration only when required:
   abnormal enable behavior, abnormal position feedback, repaired/replaced
   encoder, output shaft service, or Damiao technical support request.
2. Use the workstation single-motor function to set and verify `ESC_ID` and
   `MST_ID`. Do not save an arm operational zero for a loose motor.
3. Read and record default motor parameters. During routine single-motor ID
   commissioning, write only the communication-critical fields required for the
   target joint identity: `ESC_ID`, `MST_ID`, `CTRL_MODE`, `can_br`, and the
   current safe `TIMEOUT` value used by the ID setup flow. Do not routinely
   rewrite `Gr`, `KT_Value`, `PMAX`, `VMAX`, or `TMAX` as part of ID setup.
4. Assemble the arm.
5. Run whole-arm workstation acceptance: scan all joints, standardize required
   OpenARM parameters, run official dynamic zero calibration, run official Demo,
   and generate the factory report.

## Single-Motor ID Setup Rule

For loose-motor CAN ID setup, the workstation default is deliberately narrow:

- Set `ESC_ID` and `MST_ID` to the joint target.
- Keep `CTRL_MODE` and `can_br` aligned with the OpenARM communication profile.
- Read and record the existing default motor parameters.
- Do not change gear ratio, torque constant, position/velocity/torque limits, or
  other motor-performance parameters unless a separate approved parameter
  service task explicitly requires it.
- Do not run encoder calibration, output-shaft calibration, or save-zero as an
  automatic part of CAN ID setup.

This prevents a partial or unnecessary parameter-service operation from
interfering with the fast ID setup workflow.

## Zero Save Rule

Saving zero means the controller stores the current output position as the
position reference used as `0 rad`. Saving to Flash makes that zero survive a
power cycle. It is not the same as motor encoder calibration or output shaft
encoder calibration.

For OpenARM production, the operational zero should be saved only when the
assembled arm is in the official zero-calibration flow, or when a documented
service fixture gives a known mechanical reference. A loose motor on the bench
does not yet have its final installed mechanical reference, so saving a final
arm zero at that stage can create misleading offsets after assembly.

## TIMEOUT Rule

`TIMEOUT` is treated as a CAN command watchdog parameter. When it is set to a
finite value, the motor may require continuous valid control
or keepalive frames while enabled. Some vendor upper-software debug flows do not
send the same continuous frame cadence as the OpenARM official scripts, so the
motor can enable briefly and then enter a blinking-red timeout/fault state.

Therefore:

- During single-motor ID/MST_ID commissioning, read and record `TIMEOUT`, but do
  not write it by default.
- During whole-arm factory acceptance, standardize `TIMEOUT` only after IDs are
  correct and the workstation/OpenARM scripts are ready to provide the expected
  command cadence.
- The current right-arm and left-arm Profiles both use `J1-J8 TIMEOUT=5000`.
- The whole-arm workstation action must read each joint target from the selected
  Profile. It must not apply one scalar value to all eight joints.
- Before writing any joint, the workstation must validate that all eight Profile
  targets are present and positive. Each write then follows
  `disable -> write -> readback -> save Flash -> readback` and sends no motion
  command.
- If Damiao technical support asks not to modify `TIMEOUT` during upper-software
  debug, follow that advice and leave `TIMEOUT` as a recorded item until the
  whole-arm workstation acceptance stage.

## Report Interpretation

Encoder calibration status can be recorded as a pre-assembly service checkpoint
when the operator performed it with the Damiao upper software. It should not be
used as an automatic PASS/FAIL item unless the workstation actually executes and
verifies a supported calibration procedure.

Zero save and `TIMEOUT` standardization remain acceptance-critical only in the
assembled-arm factory workflow. Reports must use same-arm, same-side measured
readbacks; Profile targets are acceptance criteria, not substitute measurements.
