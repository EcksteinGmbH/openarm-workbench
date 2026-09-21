# OpenARM Workstation Changelog

This file records workstation-level software changes that can affect factory
testing, report output, hardware operation, or operator workflow.

Current workstation version: `0.25.0-report-states-its-method`

## Versioning Rule

- `MAJOR`: incompatible workflow, report, or hardware-control changes.
- `MINOR`: new factory-test capability, report template change, UI workflow change, or safety behavior change.
- `PATCH`: bug fix, wording/layout correction, data mapping fix, or maintenance update.
- Suffixes such as `-factory-report` may be used while the workstation is still evolving rapidly.

## Update Log

### 0.25.0-report-states-its-method - 2026-09-21

Summary: a factory report now states how it was produced, and the official gripper
parameters are on record with their source. Two corrections to yesterday's audit.

Why the report change matters more than the method question behind it: the three
shipped arms' reports name no workstation version, no official tool version, no gripper
control mode and no acceptance threshold. A customer holding one of those and a later
report cannot tell whether a difference is the arm or the procedure. Until a report can
say how it was made, *any* method improvement turns every earlier report into an
unexplainable one.

Changes:

- The report carries a **Test Method And Basis** table beside Document Control: product
  version, profile revision, workstation version, official tool version, bus mode,
  gripper control mode with its gains or limits, gripper targets, gripper criteria, and
  the zero method with whether it moves the arm. Everything is read from the product
  registry and the running workstation, so it states what was applied rather than what
  was intended.
- It is deliberately **not** a numbered section. Customers may already cite "section 4";
  adding one would renumber the rest. The golden baseline for all three real arms grew
  by exactly four lines each and is otherwise byte-identical.
- A report produced by a workstation that did not record this says so, rather than
  leaving the row blank.

Two corrections to the 0.24.0 audit, both found by re-checking on request:

- **"Official does not publish the 2.0 gripper motor" was wrong.** It is in the code:
  `init_gripper_motor(MotorType::DM4310, 0x08, 0x18)` in `examples/demo.cpp:41` and
  `examples/gripper_posforce.cpp:33`.
- **"The +/-90 deg figure has no source" was wrong.** `3.14 / 2.0` is exactly what the
  official gripper example commands (`gripper_posforce.cpp:45`, and the Python
  counterpart). The `unverified_from_v5_plan` marking is removed.
- Both errors had the same cause as the camera one before them: checking the
  documentation pages and not the examples. Official hardware figures often live only
  in example code.

Recorded from official, each with its source line:

- 2.0 gripper: DM4310, ESC 0x08 / MST 0x18, **POS_FORCE**, +/-1.5708 rad, speed limit
  25 rad/s, torque limit 0.15 pu. MIT carries no torque ceiling, so a gripper commanded
  onto a hard object keeps adding force until it overheats - reported as
  `openarm_can#81`, accepted by the maintainers, which is why the posforce examples
  exist. The travel threshold stays unset: official publishes none.
- The left-arm sign is the one the official example uses (it runs on can1); the right
  arm is its mirror and is marked as not independently sourced.
- 1.0 gripper records the method actually in use - MIT, kp 5.0, kd 0.6, no torque
  ceiling - plus a `pending_change` to POS_FORCE naming the reason and what blocks it.
  A recorded decision, not an oversight.
- `zero_multiple_arms_on_bus`: zero calibration is run one arm at a time
  (`openarm_can#101`). This matters here because Plan A puts both arms on can0.
- `gripper_control_mode_not_applied`: the control mode write is RAM-only and
  unacknowledged, so a lost write leaves the motor in its flash mode while every later
  command is silently discarded - it reads as a disconnected gripper. Check RID 10.

Also fixed while recording the above:

- `_official_demo_gripper_targets()` preferred a single `open_target_rad` over a
  per-side table. On a mirroring product that would have opened one arm into its
  mechanical stop. A per-side table now always wins, and an unknown arm side is an
  error rather than a default.

Verification:

- `.venv/bin/python -m pytest -q`: 245 passed, including that a 1.0 report states MIT
  with its gains and a 2.0 report states POS_FORCE with its limits, that a 2.0 report
  prints "threshold undecided" rather than an invented number, and that the section
  numbering is unchanged.

### 0.24.0-official-audit - 2026-09-21

Summary: re-checked everything 2.0 against the whole of official - the 1.4.0 source and
the documentation - rather than one half of it. One real defect found and fixed, one
value found to be unsourced, and four official diagnostic rules that were never carried
over.

What matched, checked value by value:

- All 45 Damiao register IDs are identical to
  `include/openarm/damiao_motor/dm_motor_constants.hpp`.
- All 9 motor error codes match by value; three differ only in spelling
  (MOS_OVERTEMP / MOS_OVERHEAT, COIL_OVERTEMP / COIL_OVERHEAT, COMM_LOST /
  COMMUNICATION_LOST).
- The baudrate register codes, and the CAN timing applied by `can_configure`, match
  (0.22.0).
- The 2.0 zero method matches the official procedure (0.23.0).

**Defect found and fixed: DM4340 velocity limit.**

- `LIMIT_PARAM` carried VMAX 8 for DM4340 where official has 10. These values scale
  every packed and unpacked MIT figure, so velocity read from J3 and J4 was recorded
  20% low on every arm this workstation has tested.
- The 16 motors commissioned on 2026-09-17 read VMAX 10.0 back from the motor itself,
  so the official table is right and ours was wrong. Three tests now pin the table to
  official, to our own enum's indexing, and to what those 16 motors reported.
- Blast radius: reporting only. Every MIT command this workstation sends uses dq=0.0,
  so nothing was commanded wrongly, and the zero calibration script reads velocity
  through the official library rather than ours, so limit detection was unaffected.

**Value found to be unsourced: the 2.0 gripper angles.**

- The registry carried right -90 deg / left +90 deg as though established. Re-checking
  official found no gripper angle anywhere: the 2.0 gripper and general hardware pages
  state no angle, direction, motor or camera model, and openarm_can 1.4.0 has no
  gripper angle constant. The values came from the V5 plan, whose own source could not
  be traced.
- They are now marked `open_target_rad_source: unverified_from_v5_plan`, the lock
  reason says plainly that there is no official source, and a test keeps them from
  ever looking authoritative. 1.0's -1.0472 is left alone: twelve arm-sides ran it.

**Four official diagnostic rules added**, from `diagnose --explain`
(`setup/cli/commands/diagnose_commands.cpp`). These separate faults that look identical
from outside, which an operator cannot do unaided:

- `bus_reply_on_unlistened_id` - frames coming back on ids nothing listens for. MST_ID
  defaults to 0, so an unconfigured motor answers on 0x00. A configuration fault, not
  a wiring one.
- `bus_daisy_chain_break` - a contiguous run of silent joints. The joints are
  daisy-chained, so a break silences everything past it; the operator is pointed at the
  link between the last answering joint and the first silent one.
- `bus_silent_scattered` - silent joints that are not contiguous, which reads as
  individual connectors rather than one break.
- `bus_nothing_acknowledges` - no ACK at all. Missing termination, a wrong bitrate and
  an unpowered bus are indistinguishable from the counters, so the entry says so and
  gives the three measurements that separate them: 60 ohm across CAN_H/CAN_L is
  correct (120 means one terminator, 40 means three), retry at a lower dbitrate, and
  `ip -details link show`.

Also recorded: `docs/official/setup-tutorial.md` now lists what official does **not**
provide for 2.0 - gripper angle, direction, gripper motor, in-hand camera model, camera
resolution/framerate/format, any camera acceptance criterion, joint limits, TIMEOUT.

Verification:

- `.venv/bin/python -m pytest -q`: 239 passed.

### 0.23.0-official-docs-and-2-0-zero - 2026-09-21

Summary: the official documentation is now kept in the repo alongside the official
code, and reading it settled the 2.0 zero method, which was down as an open decision.

Why this was needed: official content lives in two places - the `openarm_can` package
and `docs.openarm.dev` - and only the code was vendored. Grepping the code alone
produced the conclusion "official has nothing about cameras", which is wrong: the setup
tutorial carries a complete camera identification scheme. An answer built from half the
sources is worth less than no answer.

Changes:

- `docs/official/` holds extracts of the pages the workstation's behaviour depends on,
  each with its source URL and fetch date, plus the rule that a superseded version is
  kept rather than overwritten - a shipped arm was tested against the procedure as it
  read then. Two pages so far: the 2.0 setup tutorial and the Cell calibration workflow.
- **The 2.0 zero method is no longer an open question.** Official is: clamp the arm in
  the calibration jig until no joint can move, then `openarm-can-cli -i can0 set_zero
  --arm`. The implementation sends a disable frame and a set-zero frame per motor and
  nothing else, over classic CAN - **the arm is not driven at all**. The registry now
  records the method, the subcommand and the per-side target IDs.
- Plan A needs `--id` rather than `--arm` for our left arm: official runs the left arm
  on can1 at IDs 1-8, ours sits at 0x09-0x10 on the same can0, and `--id` overrides
  `--arm` (openarm_cli.cpp:245). Using `--arm` for our left arm would zero the right
  one. The IDs are recorded per side so this cannot be got wrong by hand.
- A wizard step can take its `motion` flag from the product registry. 零位校准 now reads
  "moves the arm" for 1.0, which searches the limits, and "does not" for 2.0, which is
  held by the jig. Telling an operator the arm will move when it will not is how a
  warning stops being read.

What the official docs do **not** give, confirmed by reading them:

- No camera resolution, framerate or format, and no acceptance criteria of any kind.
  Official camera setup stops at identification: udev symlinks, Arducams matched by a
  serial flashed with ArducamUvcConfigUpdateTool, the ZED by VID 2b03 / PID f682. The
  identification pattern is worth copying for our DCXGW20 and D435i; the pass/fail
  numbers still have to come from us (V5 §9-3).

Verification:

- `.venv/bin/python -m pytest -q`: 233 passed, including that the 2.0 zero entry
  matches the official procedure, that the target IDs follow Plan A rather than the
  official default, that zeroing moves a 1.0 arm and not a 2.0 one, and that every
  stored official page carries its URL and fetch date.

Operational Notes:

- The 2.0 zero step stays locked: the method is settled, but it has never been run on a
  2.0 arm and the line needs the jig (HNTP6-6 nuts, M6 screws) before it can be.

### 0.22.0-official-1.4.0-alignment - 2026-09-21

Summary: vendored the official openarm_can 1.4.0 source, aligned CAN interface
configuration with what its CLI applies, and gave the driver CAN-FD support. Groundwork
for the 2.0 steps that had a lock but no implementation behind it.

Why: a customer testing with the official tools and this workstation should be
configuring the same bus the same way. Where the two differ, the difference has to be a
decision, not an accident.

Changes:

- `external/openarm_can_1.4.0/` holds the official source at 1.4.0 (commit f340d4b).
  1.2.2 stays exactly where it was: the 1.0 flow calls its four scripts and the shipped
  arms were tested through them, so it is not being replaced, only joined.
- CAN interface configuration now applies the parameters the official
  `openarm-can-cli can_configure` applies - sample point 0.75, data sample point 0.75,
  DSJW 2, restart-ms 0 - taken from
  `setup/cli/commands/can_configure_commands.cpp` and `setup/cli/cli.hpp`. The command
  this workstation builds is now character-for-character what the official CLI builds.
  The sample point is not cosmetic: at 5 Mbps a controller sampling elsewhere can fail
  to agree with the motors at all. `restart-ms 0` is deliberate in the official code -
  leaving the controller stopped after a bus-off surfaces the fault rather than hiding
  it behind a silent recovery.
- `DamiaoSocketCANDriver` takes `fd=`, opens the socket with `CAN_RAW_FD_FRAMES` as the
  official `CANSocket` does, and sends FD frames with the bit rate switch set, matching
  `create_canfd_frame` in `dm_motor_device.cpp`. Default stays classic, so nothing on
  the 1.0 path changes. This closes the gap that made every 2.0 step after the FD
  switch impossible.
- `OPENARM_SUPPORTED_BAUDRATES` gains 8 Mbps and 10 Mbps, which official supports, and
  the Damiao register codes from the official `BAUDRATE_MAP` are recorded as
  `OFFICIAL_BAUDRATE_CODES`. 5 Mbps is code 9, matching the 2.0 registry.

Also fixed, found by the golden report baseline when the day rolled over:

- The report's signature rows - Test Engineer, Project Lead, Whole-Arm Serial - were
  dated `datetime.now()` rather than the report's own date. Regenerating an August
  report in September dated its signatures September. They now follow `report_date`,
  which reads identically for a report produced on the day. `Generated UTC` still
  records when the file was rendered, which is correct and now tested to stay separate.
  The baseline moved by exactly those three lines per report; everything else is
  byte-identical.

Verification:

- `.venv/bin/python -m pytest -q`: 229 passed.
- The generated `ip link` command was compared against the official C++ string by hand
  and matches exactly, in both classic and FD form.

Operational Notes:

- Nothing here was run on hardware. The FD driver path in particular has never sent a
  frame; it is written to match the official library's behaviour, not verified against
  a motor.
- The official 1.4.0 CLI is vendored as source but not built. The workstation still
  calls the 1.2.2 scripts.

### 0.21.2-step-timeline - 2026-09-20

Summary: the steps are drawn as a timeline with everything visible, instead of rows
that had to be clicked open.

The accordion was a leftover from when all twelve steps shared one page. Since 0.21.0 a
phase holds at most five, so hiding their contents bought nothing and cost a click to
read what a step even does.

Changes:

- Each step is a numbered node on a vertical rail with its name, what it does, and
  whether the arm moves - all visible without clicking. The rail runs green behind
  completed steps, so progress reads at a glance.
- The node marker carries the state: a filled green tick for done, a filled accent
  circle for the step you are on, an amber outline with a lock for a step that is not
  yet available, a dashed outline for one this product skips.
- Only the step you are about to run gets a surface - a bordered card with its safety
  checks and confirm button. The others stay flat, so the eye lands on one. Fifteen
  safety checkboxes on screen at once would be ticked without being read.
- Any other step can be armed with 改做这一步 or 重测这一步, which moves the card to it.
- Lock reasons and the "no record" note render inside the node rather than in a drawer.

Verification:

- `.venv/bin/python -m pytest -q`: 228 passed.
- Restarted and confirmed the stylesheet and module served carry the timeline rules;
  `.aw-tag`, `.aw-lock` and `.aw-safety` were briefly dropped with the accordion block
  and are restored, which the page test caught.

### 0.21.1-motor-records-explained - 2026-09-20

Summary: the 电机记录 view said nothing about what those records are or where they came
from, and two golden tests treated any newly built arm as a failure.

Changes:

- The view is renamed 关节电机 and opens by explaining itself: each motor was configured
  on its own at the single-motor station before assembly, the workstation kept a record
  per motor, and attaching one to a joint states which physical motor this arm's R-J1
  actually is. It also says the report cites these records, and that attaching sends
  nothing to the motor.
- Each joint card shows the date the motor was commissioned, so the evidence carries
  its date on the face of it. The attach button reads 挂到这个关节 and a joint with no
  record reads 还没配过这颗, instead of the bare 缺记录.
- `arm_wizard_status()` now returns each attached record's commissioning date, not only
  when it was linked to the arm. The commissioning date is the evidence.

Two tests fixed, both the same mistake:

- `test_the_fixture_still_matches_the_real_records` compared the *whole* production arms
  directory against the baseline, and `test_the_shipped_arms_are_all_undeletable`
  asserted that every arm on disk carries evidence. Now that the wizard can build arms,
  both turned ordinary production work into a test failure - an arm being built right
  now legitimately has no evidence yet, which is exactly why it can be discarded. Both
  now check only the arms named in the baseline.

Verification:

- `.venv/bin/python -m pytest -q`: 228 passed, with a new 2.0 arm present in the
  production directory - the case that broke both tests before.
- Checked live: the view lists all 16 motors commissioned on 2026-09-17 for that arm,
  with their joint, model and date.

### 0.21.0-arm-wizard-phase-views - 2026-09-20

Summary: one phase on screen at a time instead of twelve steps stacked together, and
deleting an arm asks which kind of delete is meant.

Changes:

- The three phases are now separate views behind a tab strip - 静态测试, 动态测试,
  出厂放行 - each showing only its own steps and carrying its own progress count. The
  commissioned motors get a fourth view, 电机记录, so that evidence is findable without
  crowding a test phase. Grouping them into blocks on one page (0.20.0) still left
  everything on one screen; this is what was actually asked for.
- The wizard opens on the phase the arm is actually in, so an operator lands where they
  left off rather than at the top.
- Deleting asks rather than deciding: 仅删除，保留记录 moves the file to
  `deleted_arms/` and can be looked up later, 彻底删除 removes it outright. Each button
  says underneath exactly what it does. The archived copy records which mode was used.
  Both modes keep the evidence guard: anything recorded against the arm refuses both.

Also fixed:

- `test_the_three_shipped_arms_could_never_be_deleted` called the real delete method
  against the production arms directory. It passed only because all three carry
  evidence - one changed condition away from destroying a factory record. It now checks
  the same property through the read-only evidence count, on copies of the records.

Verification:

- `.venv/bin/python -m pytest -q`: 228 passed, including that both delete modes respect
  the evidence guard, that an archived delete leaves a copy carrying `deleted_mode`,
  that a purge leaves nothing in either directory, and that an unrecognised mode is
  refused without touching the record.
- Checked live: a new 2.0 arm shows 静态测试 1/5, 动态测试 0/5, 出厂放行 0/2 and
  电机记录 0/16 as four views, opening on 静态测试; a purge removed it from both the
  arms directory and `deleted_arms/`.

Operational Notes:

- `deleted_arms/` currently holds one record from an archived delete. Records from a
  purge are not recoverable, which is the point of offering both.

### 0.20.0-arm-wizard-groups-and-delete - 2026-09-20

Summary: the twelve steps are grouped into three phase blocks, and an archive created
by mistake can be discarded.

Changes:

- Each step now declares which phase it belongs to, and the wizard renders one block
  per phase with its own progress count: 静态测试 (建档, 连接自检, 静态验收, 参数标准化,
  切换 CAN-FD), 动态测试 (低增益使能检查, 零位校准, 夹爪测试, 相机测试, 官方 Demo) and
  出厂放行 (放行检查, 报告签核). Each block carries one line about what that phase is,
  so an operator reads where they are instead of scanning twelve similar rows. The
  official order is unchanged; the blocks only break it into readable pieces.
- `arm_wizard_delete()` discards an arm archive, for the case it exists for: the wrong
  product version or a mistyped serial, caught straight away. It refuses the moment
  anything has been recorded against the arm - a linked job, a zero or demo record,
  evidence, a report, a command run, an attached motor record, a joint binding - since
  at that point the archive is evidence, and evidence is not something an operator
  deletes from a wizard. The file is moved to `deleted_arms/`, not removed, and the
  page confirms before calling. `arm_wizard_status()` reports `evidence_count` and
  `deletable`, and the delete button only appears when the archive is empty.
- A new problem entry `arm_has_evidence` explains the refusal and says that an arm you
  simply do not want to continue can be left alone; it affects nothing else.

Verification:

- `.venv/bin/python -m pytest -q`: 225 passed, including that nothing which moves the
  arm sits in the 静态测试 group, that the official order survives the grouping, that a
  single attached motor record is enough to block a delete, and that each of the three
  shipped arms is refused (they carry 34, 39 and 16 entries).
- Checked live end to end: create a 2.0 arm, read back three blocks with 1/5, 0/5 and
  0/2 and the five 2.0 steps locked, delete it, and see the serial become available
  again.
- Tried against a real arm: `OAF26080401` is refused with "上已有 34 条记录".

Operational Notes:

- An arm archive created by hand while the wizard was being built (`OAF26092001`) was
  found in the production directory by the golden regression and removed through this
  new path, which is what it is for.
- The eleven steps after 整机建档 still hand over to the engineer tools.

### 0.19.0-arm-wizard-new-arm-first - 2026-09-20

Summary: the arm wizard starts from building a new arm, not from picking one of the
three that have already shipped. Step 1, 整机建档, is now executed by the wizard itself.

The previous version listed every arm on file, and all of them are sold units. That
made the page read as a tool for re-testing delivered arms rather than the acceptance
flow for the arm being built - the opposite of what it is for.

Changes:

- 新建机械臂 is the first thing on the page: product version (write-once), Follower or
  Leader, and a serial that is pre-filled with the next free number for today, so the
  usual case is one click. The form says plainly that the 整机编号 is the arm's identity
  and that everything is filed under it.
- An arm counts as finished once it is released *and* its report is filed. Those are
  kept on record - the report has to stay reachable - but they fold away behind
  已出厂的机械臂（N）, collapsed, and are never auto-selected. Released but unsigned
  still counts as under test, because it still needs its report.
- `arm_wizard_create()` executes step 1 and is the first step the wizard runs itself:
  it validates the serial against the factory naming rule, refuses one already in use,
  refuses an unknown product version, and opens the file. Two new problem entries,
  `arm_cn_invalid` and `arm_cn_taken`; the latter points out that continuing that arm
  is probably what was meant, rather than a new one.
- Failure messages now appear where the action was: creating an arm fails in the
  picker, running a step fails among the steps.

Verification:

- `.venv/bin/python -m pytest -q`: 216 passed, including that a shipped arm is kept but
  separated, that a released-without-report arm is still under test, that the suggested
  serial skips numbers already used, and that a bad or duplicate serial is refused
  without writing anything.
- Checked live: the wizard opens on 新建机械臂 with `OAF26092001` suggested, no arms
  under test, and the three sold arms folded away with their report counts.

Operational Notes:

- The other eleven steps still hand over to the engineer tools; step 1 is the first one
  the wizard performs.

### 0.18.0-arm-wizard-layout - 2026-09-20

Summary: reworked the arm wizard after the first version was tried. All twelve steps
are now laid out on the page with their own buttons, the engineer tools are one place
instead of two, and picking an arm is a list of arms rather than a bare dropdown.

What was wrong with 0.17.0, in the order it was reported:

- The arm dropdown did not say what it was for. It is now a section headed 选择要测试的
  机械臂 with one card per arm showing its product, type and how many motor records are
  attached, plus a line explaining that the 整机编号 is that arm's identity and that the
  report is filed under it.
- Selecting an arm appeared to do nothing. All three real arms have passed, so the old
  layout - which only rendered the single "current" step - had nothing to show and fell
  back to a completion card. With every step listed, the state of each one is visible
  whatever the arm's progress.
- Steps were driven through a dialog. They are not any more: each step is a row that
  expands in place to show what it does, the safety checks if it moves the arm, and its
  own button. Dialogs are back to what they are for in the other two wizards - failures
  the operator cannot clear from the page.
- Re-testing was not reachable. A finished step now carries 重新测这一步, and any step
  can be opened by clicking its row.
- 高级工具（工程师）and tab 04 整臂工程工具 were two doors to the same room. The
  engineer workbench moved inside tab 03 as a hidden advanced view, exactly as tabs 01
  and 02 hold theirs, and its tab is gone. Tabs are now 01 准备建链, 02 单电机测试,
  03 整臂测试, 04 报告归档.
- The old 官方动态测试 view had become hard to find. It is reachable again from the
  advanced view's own subtab bar, which gained a button for it - that panel previously
  had no way in except the tab that 0.17.0 removed.

The move was mechanical and checked: all 110 element ids inside the engineer workbench
survive, none duplicated, section tags balanced.

Verification:

- `.venv/bin/python -m pytest -q`: 208 passed. The page test now asserts there is no
  second tab for the engineer tools, that the workbench panels are still present inside
  the advanced section, and that re-running a finished step is reachable.
- The golden regression caught a real slip while this was being built: a 2.0 arm
  created by hand to inspect the locked steps had landed in the production
  `artifacts/factory/arms/`. It was moved to the archive, not deleted. This is exactly
  the case that baseline exists for.

Operational Notes:

- Step execution is still not wired; pressing a step explains, on the step itself, that
  the entry point is in the engineer tools for now.

### 0.17.0-arm-wizard-page - 2026-09-20

Summary: tab 03 is now the whole-arm wizard, in the same shape as the link and
single-motor wizards. Twelve steps in the official order, each saying in plain words
what it does and whether the arm will move; 2.0's steps are visible and locked.

Changes:

- Tab 03 is 整臂测试, the new wizard. The two engineer views collapse into one tab 04
  整臂工程工具, reachable from the wizard's 高级工具（工程师）button, matching how 01
  and 02 keep their advanced tools out of the operator's way. The official-dynamic
  panel gained an in-panel subtab button, since the old tab 04 was its only way in and
  collapsing the tabs would otherwise have stranded it.
- The step rail runs down the left rather than across the top: twelve steps do not fit
  the horizontal strip the shorter wizards use. Each rail entry shows its state and a
  one-word note - 只读 / 写入电机，不运动 / 机械臂会运动 / 待真机验证 / 本版本不需要.
- Before any step that moves the arm, three safety items must be ticked (急停在手边,
  活动范围无人无障碍, 手远离夹爪). The primary button stays disabled until they are.
- A locked step raises the blocking dialog carrying the registry's reason; the side
  panel lists every locked step so an operator can see what the arm is waiting on
  without clicking through.
- The commissioned motors are shown as a joint grid with a 挂载 button per joint, so
  the 16 records configured on 2026-09-17 can be attached to the arm that will carry
  them into its report.

Two defects found by running the wizard against the three real arms:

- TIMEOUT standardization and the low-gain enable check wrote nothing to the arm
  record - not to `command_run_history`, not anywhere - so nothing could tell whether
  they had run. Both now take an optional `arm_cn` and record themselves when given
  one; every existing caller passes nothing and behaves exactly as before.
- Because of that, the wizard first showed a passed 1.0 arm with 参数标准化 as its
  current step, which would have sent an operator to repeat a Flash write on a
  finished arm. An applicable step with no evidence on an arm that already cleared the
  release gate is now `no_record` - 无执行记录 - and the completion card names those
  steps and says plainly that it does not mean they were skipped.

Verification:

- `.venv/bin/python -m pytest -q`: 208 passed, including that a passed arm is never
  pointed at a no-record step, that a step run with an `arm_cn` records itself and
  then reads back as done, and that one run without an `arm_cn` writes no arm file.
- Checked against live data: `OAF26080401` (1.0, PASS) shows 下一步=None with 参数标准化
  and 低增益使能检查 as 无执行记录, and skips 切换 CAN-FD and 相机测试. A fresh 2.0 arm
  shows HOLD, 连接自检 as current, and 切换 CAN-FD / 零位校准 / 夹爪测试 / 相机测试 /
  官方 Demo locked with their reasons.
- The golden release-gate and formal-report baselines are unchanged.

Operational Notes:

- Step execution is not wired yet: pressing a step opens a dialog pointing to the
  engineer tools, and progress updates when you come back. The per-step handlers are
  the next release.
- **Not exercised on hardware.** The methods each step will call are the ones the three
  shipped arms went through, but the wizard's own sequencing has never run against a
  real arm. Worth a supervised first run.

### 0.16.0-arm-wizard-backend - 2026-09-20

Summary: the whole-arm acceptance flow is now a sequenced twelve-step wizard behind the
API, in the official order, with 2.0's steps present but locked. The 16 motors
commissioned for the next 2.0 arm are protected and can now be attached to it.

This is the service layer; the page comes next. The wizard only sequences and guards -
every step delegates to the method the engineer tools already called, so a 1.0 arm is
judged by exactly the code that judged the three arms already shipped, and the golden
release-gate and report baselines are unchanged.

The 16 commissioned motors:

- `tests/golden/fixture/single_motor_records/` holds a committed copy of all 16 records
  from 2026-09-17, plus the legacy by-SN file. They live under `artifacts/`, which is
  gitignored, and they are the only evidence that each motor was configured and read
  back on hardware.
- `tests/test_single_motor_records_intact.py` guards the invariant rather than byte
  equality, since a record gains fields when it is attached to an arm: all 16 joints
  present, all PASS, all `openarm_2_0`, each with the ESC/MST pair Plan A calls for,
  and every recorded value a readback rather than a target. It also checks the live
  directory still matches wherever it exists. R-J1 predates the decoded `verified`
  field (it was commissioned on 0.8.0); a test pins that this is the only exemption.
- `arm_wizard_available_motor_records()` lists the commissioned motors whose product
  version matches the arm, and `arm_wizard_attach_motor_record()` attaches one to its
  joint. The record id is the key, never the SN - Damiao's SN register is not unique
  across motors. Attaching a record from the other product version is refused, as is a
  record that did not pass; re-attaching a joint replaces rather than duplicates.

The wizard:

- `ARM_WIZARD_STEPS` is the official order: 整机建档, 连接自检, 静态验收, 参数标准化,
  切换 CAN-FD, 低增益使能检查, 零位校准, 夹爪测试, 相机测试, 官方 Demo, 放行检查,
  报告签核. Each step carries a plain-language purpose, whether it moves the arm, and
  whether it writes to the motors without moving them - so an operator knows before
  pressing, not after.
- Steps resolve per product. 1.0 skips 切换 CAN-FD and 相机测试 and has nothing locked.
  2.0 shows both, and locks 切换 CAN-FD, 零位校准, 夹爪测试, 相机测试 and 官方 Demo
  with the reason from the registry. Its read-only and parameter steps stay reachable,
  so a 2.0 arm can still be scanned and checked.
- `arm_wizard_status()` reads progress from evidence already on record, so an arm
  tested through the engineer tools before this wizard existed shows its real state
  instead of starting from zero.
- Four problem-catalog entries with beginner-readable fixes: `arm_not_found`,
  `arm_step_locked`, `arm_step_out_of_order`, `arm_motor_record_mismatch`. Only
  `arm_step_locked` is blocking, because it needs a hardware verification or a
  decision the operator cannot make on that page; the others they can clear themselves.
- API: `GET /api/arm/wizard/options`, `GET /api/arm/wizard/<arm_cn>/status`,
  `GET|POST /api/arm/wizard/<arm_cn>/motor-records`.

Verification:

- `.venv/bin/python -m pytest -q`: 204 passed, including 16 wizard tests and 5 record
  guards. The golden release-gate and formal-report baselines for the three real arms
  are unchanged.
- Not exercised on hardware: none is attached.

Operational Notes:

- No step executes anything yet; this release defines and reports the flow. The per-step
  handlers reuse the existing engineer methods and land with the page.

### 0.15.0-registry-driven-criteria - 2026-09-20

Summary: the values that define a product - TIMEOUT, bus mode, gripper geometry - are
now read from the product registry instead of restated in four different places. A 2.0
arm can no longer be issued a report claiming it was tested on CAN 2.0.

Nothing about a 1.0 arm changed. The release-gate and formal-report goldens for the
three real arms are byte-identical before and after every step below; that is the
whole reason they were built first.

New guard, built before the migration it protects:

- `tests/golden/fixture/reports/` freezes the full formal acceptance report of each
  golden arm, HTML and JSON, with the generation timestamp normalised and
  `report_date` pinned. Two runs of the same input are otherwise byte-identical.
  `tests/test_golden_formal_report.py` regenerates and shows a unified diff on any
  change; `tests/golden/build_report_baseline.py` refreshes it and refuses to emit a
  baseline that is not reproducible. The reports are generated from the fixture, which
  carries only what the gate reads, so some evidence resolves to placeholders - the
  baseline exists to detect change, not to be a specimen of a complete report.

Migrated:

- `commissioning_policy.whole_arm_timeout_policy` is derived from the registry rather
  than restating `5000` per arm side. The registry already has to agree with the
  profiles, so reading it is the only way this table cannot drift from them. Output is
  unchanged; a product that ever targets a different value surfaces here on its own.
- A single-motor record's `can_mode` comes from the product's commissioning bus
  instead of the literal `"CAN 2.0"`.
- The formal report takes a `bus` argument describing the operation bus, and builds
  its header box, CAN-health expectation and scope sentence from it. Five hardcoded
  occurrences of "CAN 2.0 / 1 Mbps" and "classic CAN 2.0 at 1 Mbps with CAN-FD
  disabled" are gone. `generate_formal_factory_acceptance_report()` passes the bus of
  the arm's recorded product, so a 2.0 arm's report reads "CAN FD / 1 Mbps
  arbitration / 5 Mbps data" and contains no "CAN 2.0" anywhere - asserted by test.
- `_official_demo_gripper_open_target()` is gone. It returned -1.0472 for an OAF arm
  and +1.0472 for an OAL one, a rule that came from what those historical runs
  happened to pass, not from any specification: the official limit table in
  openarm-can-zero-position-calibration is [-60 deg, 0 deg] for every arm. The demo
  now reads the target from the product. 1.0 states one value for Follower and Leader
  alike; 2.0 keys it on arm side (right -90 deg, left +90 deg) and refuses to build a
  command that does not state `--arm_side`, since guessing would open a 2.0 gripper
  into its mechanical limit.
- The 1.0 registry records the Leader anomaly as `historical_anomaly` with
  `status: recorded_only_not_applied`: three Leader arm-sides on 2026-06-02/03 were
  commanded +1.0472 and physically reached +0.956..+0.970 rad, signed off PASS. The
  cause is unexplained - the demo tool's own default is +1.0472, contradicting the
  limit table in the same package, and the earliest Follower has an operator-recorded
  gripper stop at +1.0739, so the positive side is not a Leader trait. A 1.0 Leader is
  now tested with the official -1.0472 like any other arm; the 0.14.0 midpoint
  progress check stops the phase if it does not follow. That measurement breaks the
  entry.
- `run_official_demo_validation()` refuses to execute while the product's gripper is
  unverified, naming the lock. The lock has to hold where the motor is driven, not
  only at the release gate. Dry runs are unaffected.

Verification:

- `.venv/bin/python -m pytest -q`: 180 passed. The golden release-gate and formal
  report for all three real arms are unchanged at every step; each migration was run
  and checked separately rather than as one batch.
- No hardcoded `1.0472` or `startswith("OAF"/"OAL")` remains in `src/workstation.py`.
- Not exercised on hardware: none is attached.

Operational Notes:

- A 2.0 arm is blocked from a formal report, and now from executing the demo, until
  its gripper direction and travel have been confirmed on hardware.
- 1.0 Leader arms will be commanded -1.0472 rather than the +1.0472 used in 2026-06.
  This is the intended change; the progress check is the guard if that turns out to be
  the wrong direction for that hardware.

### 0.14.0-gripper-sampling-and-progress-check - 2026-09-20

Summary: the demo's gripper position sampling read a frozen copy for the whole of
every phase, in every run ever recorded. Fixed, and a midpoint progress check now
stops a gripper that is not following instead of holding it against a stop.

Root cause: `DMDeviceCollection::get_motors()` builds a `std::vector<Motor>` with
push_back and returns it by value, so each call yields fresh COPIES of the motors,
not handles on the live ones. `command_gripper_position()` captured one copy before
its control loop and then re-read that snapshot ~600 times per phase. Every demo log
in this repo - 15 arm-sides, Follower and Leader, 2026-05 through 2026-09 - shows
`travel=0.000000` with min == max == start == end, without a single exception. The
gripper moved exactly as the operator observed; only the measurement was blind. The
script is the only one of ten `get_motors()` call sites that cached the result.

Changes:

- `tools/openarm-can-demo` reads the gripper through a fresh `get_motors()` call on
  every sample. `start` is still read once at entry, because the ramp interpolates
  from where the phase began - so the commanded targets are unchanged.
- A midpoint progress check: halfway through the ramp, if the gripper has covered
  less than 15% of the requested travel (and the move is at least 0.2 rad), the phase
  stops and prints `GRIPPER_ABORT: ...`. Commanding a gripper the wrong way otherwise
  holds it against its own hard stop for the rest of the phase, which is the
  sustained-force case that overheats a DM4310 (openarm_can#81). Every arm on record
  reached 90-98% of target, so it sits near 48% at the midpoint: 15% is a 3x margin.
- `_parse_official_demo_stdout()` collects `gripper_abort_messages` and raises the
  blocking item `gripper_progress_aborted`, so an aborted phase is reported as its own
  cause rather than only as short travel.

Verification:

- `.venv/bin/python -m pytest -q`: 163 passed. Six new tests run the real
  `command_gripper_position` against a fake OpenArm that reproduces the C++ copy
  semantics, including one that asserts the fake really does freeze a captured motor -
  without that, the other tests would prove nothing.
- The command stream is proven unchanged: with the clock pinned to a deterministic
  fake, a gripper that follows perfectly and one that does not move at all receive a
  byte-identical sequence of targets, up to the point the check stops the second.
- The progress check does not trip on a gripper that only closes 20% of the remaining
  gap per cycle, nor on moves below 0.2 rad.
- Parsing a real recorded Follower run is unchanged, including its `travel=0.000000`.
- Not exercised on hardware: none is attached.

Operational Notes:

- Phase-internal `travel=` in demo logs will now show real motion instead of
  0.000000. The pass criterion still uses the endpoint values
  (`open_observed_at_close_start` and `close_final`), so verdicts are unchanged.
- This matters most for 2.0, whose gripper acceptance thresholds are still undecided:
  any criterion beyond endpoint-to-endpoint needs the per-sample data that was
  previously unavailable.

### 0.13.0-product-version-registry - 2026-09-20

Summary: one place now answers "what is a 1.0 arm" and "what is a 2.0 arm". An arm
carries its product version for life, the release gate refuses to mix evidence across
versions, and every 2.0 behaviour that has not been confirmed on hardware is locked.

Context: no CAN adapter or arm can be attached to this machine, so nothing here was
run against hardware. The release deliberately stops at description: the scan,
acceptance and report paths still read their own tables, so 1.0 judgement is
byte-for-byte unchanged. Migrating those tables onto the registry is a separate step,
because that is the step that can change a 1.0 verdict.

Changes:

- `profiles/products/openarm_1_0.yaml` and `openarm_2_0.yaml` record IDs, motor types,
  CAN modes per stage, CTRL_MODE/TIMEOUT, gripper geometry, zero method, cameras and
  the firmware baseline. Everything in the 1.0 file is already in production and was
  verified by the three arms that were built with it; every 2.0 entry that drives a
  motor carries `hardware_verified: false` plus a `locked_reason`.
- `ProductRegistry` loads and validates them at startup: exactly J1-J8, eight unique
  in-range IDs per arm, no ID shared between the two arms, a known CAN mode, a
  `dbitrate` whenever the mode is FD, and a stated reason behind every lock. It then
  cross-checks each registry against the profile it names - ESC ID, MST ID, motor type,
  TIMEOUT and bus, per joint - and `WorkstationService.__init__` refuses to start on a
  disagreement. The registry has to describe the system, never redefine it.
- `bind_arm_identity()` takes `product_version`. It is write-once: re-binding the same
  version is fine, switching it raises, because it would retroactively reinterpret
  every piece of evidence already collected under the other version's rules. Records
  written before the registry existed carry none and are read as `openarm_1_0` - all
  three real arms on disk are 1.0 Followers, so that is a statement of fact rather
  than a fallback guess, and it is marked `product_version_source: default_legacy`.
- `factory_release_gate()` now reports `product_version` and `product_version_locks`,
  and blocks on two new grounds: linked evidence whose *stated* version differs from
  the arm's, and any product that still has unverified locked sections - a product
  whose motion behaviour has never been confirmed cannot produce a formal report,
  whatever the rest of the evidence says. Evidence that states no version is not a
  conflict; holding the existing arms would be rewriting history, not catching a
  mistake. New job links record `product_version` so future evidence does state it.
- `2.0` gripper direction is keyed on arm side (right 0 to -90 deg, left 0 to +90 deg)
  while 1.0 keys on the CN prefix (OAF/OAL, +/-60 deg). That is a different scheme, not
  a different number, and the registry keeps them as separate fields so they cannot be
  read interchangeably. The 2.0 travel threshold is deliberately left null: no official
  figure exists, and an invented one becomes a PASS/FAIL verdict nobody decided.
- `/api/config` exposes `product_versions` (with each product's locked sections) and
  `default_product_version`; `POST /api/factory/arms` accepts `product_version`.

Also fixed, unrelated to the registry but found while reviewing the left-arm path:

- The status-frame decoder special-cases L-J8 at ESC 0x10, which does not fit the
  4-bit ID field, and had no test at all. Reading its high nibble as status reports a
  DISABLED motor as ENABLED - the most dangerous misread available, since "already
  enabled" changes what an operator does next. Four tests now pin the behaviour down,
  including that the special case does not swallow ordinary frames sent to that motor.

Verification:

- `.venv/bin/python -m pytest -q`: 152 passed, including 23 registry tests (nine
  malformed-registry shapes rejected at load, a contradicting registry stopping the
  service, write-once version binding, both new gate blocks, and the explicit case
  that unstated evidence is NOT a conflict) and the four status-frame tests.
- The golden regression on the three real arms is unchanged: all three still PASS with
  no blocking or warning items, and each is now reported as `openarm_1_0`.
- Server restarted; `/api/config` serves both products with 2.0's locks.

Operational Notes:

- An arm bound as `openarm_2_0` is held by the gate today, by design: `can.operation`,
  `gripper`, `zero` and both cameras are locked. Each lock names what has to be settled
  - the R-J1 CAN-FD bench test, the gripper acceptance thresholds, whether a Cell
  calibration jig exists.
- Binding an existing arm to a different product version now fails. Correcting a
  genuine mis-binding means editing the record under `artifacts/factory/arms/`
  deliberately, not through the API.

### 0.12.0-test-isolation-and-timeout-baseline - 2026-09-20

Summary: tests can no longer write into the production record directories, the three
real arms that were built on hardware are frozen as a regression baseline, and the
operational TIMEOUT target is one value across every profile.

Context: no CAN adapter or arm can be attached to this machine for the time being, so
no change can be confirmed on hardware. This release is the groundwork that makes the
following changes verifiable without it.

Changes:

- `tests/conftest.py` now redirects every workstation output path
  (`ARTIFACTS_DIR`, all `FACTORY_*`, all `VENDOR_*`) into the test's `tmp_path` for
  every test, present and future. Previously `tests/test_arm_can_scan_cli.py`
  constructed a real `WorkstationService` and wrote one `arm_verification` job with
  `status: passed` into the repo's real `artifacts/jobs` on every `pytest` run. Such a
  job is indistinguishable from one produced on hardware, and `factory_release_gate()`
  selects its evidence from exactly that directory.
- `tests/test_artifact_isolation.py` guards the above: every redirected path must
  resolve outside the repo, every `ARTIFACTS_*`/`FACTORY_*`/`VENDOR_*` directory
  constant the module declares must be covered by the redirect (so a new one cannot
  silently start writing to the repo), and building a service plus creating a job must
  leave the real `artifacts/jobs` untouched.
- 114 job directories with no reference from any arm record or single-motor record
  were moved to `artifacts/_archive_20260920/jobs/`. Nothing was deleted. The 29
  directories referenced by the three real arms and the 16 single-motor records stay
  in place. The release-gate output for all three arms is byte-identical before and
  after the move.
- `tests/golden/release_gate_real_arms.json` freezes the release-gate verdict, linked
  evidence and record counts of `OAF26062401`, `OAF26080401` and `OAF26090301` - the
  three 1.0 arms that were actually built and tested on hardware.
  `tests/test_golden_real_arms.py` asserts a change cannot move them, that a new arm
  record on disk cannot go unguarded, and that the gate writes nothing. Refresh with
  `tests/golden/refresh_release_gate_baseline.py`, reviewing the diff, and only when a
  baseline move is an actual decision.
- The operational TIMEOUT target is now `WHOLE_ARM_TARGET_TIMEOUT = 5000` in one
  place. The generic `openarm_v1` profile (the API and CLI default) carried a
  superseded `1000` on J1-J4 while the derived arm profiles and
  `commissioning_policy.whole_arm_timeout_policy` both said 5000, so an arm scan run
  with the default profile would have reported four false TIMEOUT mismatches. No
  production job was affected: all 29 real jobs on disk used the derived
  `openarm_left_arm_v1` / `openarm_right_arm_v1` profiles, never the generic one.

Verification:

- `.venv/bin/python -m pytest -q`: 123 passed, including the golden regression on the
  three real arms, the artifact-isolation guards, and a new test that the generic
  profile, both derived profiles and the commissioning policy all agree on the
  TIMEOUT target.
- Measured directly: a full `pytest` run left `artifacts/jobs` at 29 entries, where
  before this change every run added one.
- The archive move was verified by diffing the release-gate JSON for all three arms
  before and after: byte-identical.

Operational Notes:

- Archived jobs are at `artifacts/_archive_20260920/jobs/` and can be moved back.
- `artifacts/` is gitignored, so the golden baseline data lives only on this machine.
  `tests/test_golden_real_arms.py` skips with a stated reason where it is absent.
- No hardware behaviour changed; nothing in this release writes to a motor.

### 0.11.0-scan-coverage-and-blocking-dialog - 2026-09-20

Summary: a connected motor is now always found, an interface restart no longer makes
a live motor look dead, and problems the operator cannot work around are raised in a
blocking dialog.

Changes:

- `DEFAULT_SCAN_IDS` now spans 0x01-0x20 instead of 0x01-0x08 plus 0x11-0x18. The old
  range left out left-arm ESC IDs 0x09-0x10, so a correctly configured L-J1..L-J8
  reported `detected=0` on the advanced (engineer) path unless the operator typed the
  ID by hand. Confirmed on hardware on 2026-09-18 with an ESC 0x10 / MST 0x20 motor.
  The two wizards already scanned the full range and are unchanged.
- Anything that takes a CAN link down now closes the workstation's sockets on that
  channel first: `configure_can_interface`, `can_interface_down`, and the wizard
  precheck, which restarts the link with raw `ip` commands and so bypassed the other
  two. A socket opened before the restart survived as a deaf handle and reported an
  empty bus, which reads exactly like a dead motor and sent the operator hunting for
  power and wiring faults. Reproduced on hardware on 2026-09-18; restarting the
  service made the same motor identify immediately.
- A session is no longer reused when the adapter was unplugged and replugged: the
  interface's `ifindex` is recorded when the session is opened and compared on reuse.
- When a wizard scan comes back empty on a session it reused rather than just opened,
  it rebuilds the session once and rescans before reporting `no_motor_found` /
  `bus_no_motor`. An empty scan on a reused socket is ambiguous, and one reconnect
  rules out our own side before the hardware is blamed. A session the wizard just
  opened is not rescanned, so the happy path costs nothing extra.
- A failed connect now raises `WizardConnectError` instead of being caught together
  with scan failures, so a scan error keeps its own classification rather than being
  reported as `connect_failed`.
- Problem envelopes carry `blocking: true` for the six codes the operator cannot work
  around from inside the wizard (`adapter_missing`, `can_interface_missing`,
  `can_interface_down`, `interface_prepare_failed`, `connect_failed`,
  `can_bus_error`). Both wizards raise these in a new modal dialog
  (`web/static/js/problem-modal.js`) carrying the same title, cause and numbered fix
  steps as the in-page panel, plus 我已处理，重试 which re-runs the failed step, and
  关闭. The dialog does not dismiss on a click outside. Bus and motor states the
  operator can fix in place (`bus_no_motor`, `no_motor_found`, `multiple_motors`,
  `motor_fault`, ...) stay in the in-page panel only, so the dialog does not fire on
  every normal power-up step.
- Each wizard's click dispatcher and its dialog retry button now share one action
  table, so the retry runs exactly the step the operator would have clicked.

Verification:

- `.venv/bin/python -m pytest -q`: 114 passed, including new regression tests that
  the default scan finds a left-arm ESC 0x10 motor; that `can_interface_down`,
  `configure_can_interface` and the wizard precheck each close the cached socketcan
  session; that a replugged adapter (changed `ifindex`) is not reused; that a wizard
  reconnects once and rescans before reporting no motor; that it does NOT rescan on a
  session it just opened; that `adapter_missing` is flagged blocking while
  `bus_no_motor` is not; and that the dialog markup, stylesheet and both wizard
  modules are wired together.
- `node --check` on the four touched JS modules; server restarted and the page,
  `problem-modal.js` and the dialog markup are served.
- Not yet exercised on hardware: no USB-CAN adapter is attached to this machine.

Operational Notes:

- The advanced-path single scan now probes 32 IDs instead of 16, so it takes about
  twice as long. The wizards are unaffected.
- Asset cache keys bumped to `20260920-problem-modal`.

### 0.10.2-wizard-rail-fix - 2026-09-18

Summary: fixed the task rail reappearing on the wizard tabs after a page load or refresh.

Changes:

- The rails are hidden by CSS keyed on `body[data-primary-flow]`, but nothing set that attribute until the operator clicked a tab, so a fresh load of the default 准备建链 tab showed the engineer task rail next to the wizard. The template now ships `<body data-primary-flow="connectTab">`, so the wizard owns the full width from first paint.
- Boot now also calls `switchPrimaryTab(currentPrimaryTab())` so the attribute always matches the active tab, including when the active tab is restored by other code.
- Asset cache keys bumped so browsers pick up the corrected template and script.

Verification:

- `.venv/bin/python -m pytest -q`: 103 passed, including a new regression test that asserts the served page carries the default `data-primary-flow`, that both wizard rail-hiding selectors exist in the stylesheet, and that boot syncs the attribute.
- Server restarted; the served page and script contain both fixes.

Operational Notes:

- The task rail and live monitor remain available under 高级工具（工程师）on both wizard tabs.

### 0.10.1-advanced-tools-layout - 2026-09-18

Summary: reordered the engineer advanced tools into labelled sections that follow the actual work order; no behaviour change.

Changes:

- The single-motor advanced page is now five titled sections in workflow order: 参数写入与保存 (the existing step subtabs), 参数核对 (target vs. measured), 单关节诊断 (the joint test buttons together with their recent-result summary, previously split between the body and the side rail), 官方命令 (motor-check and baudrate change) and 报告与厂商维护 (motor report, DMTool, maintenance records).
- Each section header carries a one-line purpose note; the diagnostics header states that 参数诊断/链路测试 are read-only while 极小幅响应 moves the motor.
- The side rail keeps only the two cards that are context rather than tools: 电机工站建议 and 关联整臂任务.
- The link advanced page labels its manual connection area and marks the two transport forms (串口桥参数 / SocketCAN 参数).
- Any adapter Linux exposes as SocketCAN is reported by its real state; the previous "非 gs_usb 驱动" text no longer overrides a healthy non-gs_usb adapter (e.g. peak_usb).

Verification:

- `.venv/bin/python -m pytest -q`: 102 passed, including a new assertion that a healthy `peak_usb` CAN FD interface is reported as 正常.
- Markup check after the restructure: HTML tags balanced, no element id lost, added or duplicated (compared against the pre-change template), so all existing JS bindings keep working.
- Server restarted; the reordered sections render under 高级工具（工程师）.

Operational Notes:

- No tool was removed. Zero save, safe_mit_ping, 极小幅响应 and 受控执行 remain engineer-only and still move or write to the motor.

### 0.10.0-link-wizard - 2026-09-18

Summary: tab 01 is now a beginner link wizard with the same layout and troubleshooting behaviour as the single-motor wizard.

Changes:

- The connection tab leads with a four-step wizard (detect adapter -> configure and start the CAN port -> connect the workstation -> read-only bus check -> done), one primary button per step, a step rail, a per-step help panel and a live connection status chip.
- New backend endpoints `POST /api/link/wizard/detect|prepare|connect|bus-check|disconnect` and the matching `WorkstationService.link_wizard_*` methods. Detect lists every SocketCAN port with beginner-readable health, mode and bitrate text; prepare configures the port (CAN 2.0 1 Mbps by default, CAN FD 1M/5M optional) and brings it up; connect reuses an open session for the same port instead of stacking CAN sockets; the bus check is a read-only inventory of ESC IDs 0x01-0x20 that reports matched Profile joints, factory-default IDs, duplicate ESC IDs and faulted motors.
- Every failure returns a structured problem (title, cause, ordered fix steps, technical detail) and can be retried at the step that produced it. New catalog entries: `adapter_missing` (no CAN port at all, including the gs_usb firmware hint), `interface_prepare_failed` (with the exact `ip link` commands) and `bus_no_motor` (power, wiring, termination, wrong channel).
- No step writes motor parameters, enables a motor or sends a motion command.
- The previous manual connection form, interface list and system CAN configuration remain unchanged under "高级工具（工程师）".

Verification:

- `.venv/bin/python -m pytest -q`: 102 passed, including detect with no adapter, interface health text for an UP/DOWN port, prepare issuing the `ip link` sequence, connect reusing an existing session, disconnect closing it, a permission-denied prepare failure, an empty-bus check and joint matching on a populated bus.
- Live, 2026-09-18: with the adapter unplugged, all four endpoints returned the `adapter_missing` problem with operator guidance instead of a raw error. The happy path could not be re-run live because the adapter was disconnected; it remains to be walked through on hardware.

Operational Notes:

- Operators start here before any test; after re-plugging the adapter or restarting a CAN port, run the wizard again so the workstation opens a fresh CAN socket.
- The bus check is the fastest way to see whether a motor answers at all before opening the single-motor or whole-arm workflow.

### 0.9.0-single-motor-inspect - 2026-09-18

Summary: added a read-only motor parameter viewer to the single-motor page, so operators can look at what a motor carries without starting a commissioning job.

Changes:

- New "查看电机参数" button in the single-motor wizard header opens a read-only dialog: it scans ESC IDs 0x01-0x20 on the selected CAN port and shows, per answering motor, the communication identity (ESC_ID, MST_ID, control mode, bitrate, TIMEOUT), motor parameters (Gr, KT, PMAX, VMAX, TMAX), protection thresholds, versions and the raw SN register, plus live status, position and temperatures.
- New backend `POST /api/single-motor/inspect` and `WorkstationService.single_motor_inspect()`. The call only reads parameters and refreshes status: it never enables, writes, saves Flash or zeroes, and it creates no job and no record.
- The viewer reports the matched Profile joint for the motor's current ID pair, marks factory-default IDs, infers the motor family from the limit registers, and lists every motor on the bus instead of blocking when more than one answers; duplicate ESC IDs are called out.
- Failures reuse the operator troubleshooting catalog (missing adapter, interface down, bus error, connect failure, no motor found), so a read attempt explains the cause and the fix instead of failing silently.
- `can_br` display accepts both the raw register code and an already decoded bitrate; `TIMEOUT=0` is shown as not enabled.

Verification:

- `.venv/bin/python -m pytest -q`: 99 passed, including a service-level test asserting no write/enable/zero call and no job is created during inspection, ID-to-joint matching, display formatting, the multi-motor listing, and the API-level rows and problem envelope.
- Live hardware, 2026-09-18: read back a right-arm J8 motor on can0 (ESC 0x08 / MST 0x18, MIT, can_br code 4 = 1 Mbps, TIMEOUT 0, Gr 10.0, PMAX/VMAX/TMAX 12.5/30/10, DISABLED, no fault) using the same read path.

Operational Notes:

- The viewer is safe to use at any time, including on an already commissioned motor; it sends no motion or write command.
- Use it before commissioning to confirm which joint a motor is currently configured as, and after assembly to check a joint without creating a job.

### 0.8.0-single-motor-wizard - 2026-09-17

Summary: the single-motor page is now a beginner wizard with built-in troubleshooting, and loose-motor commissioning saves a traceable record instead of generating a per-motor report.

Changes:

- New operator wizard on the single-motor tab: choose product line (OpenArm 2.0 default / 1.0), arm side, joint and CAN port -> identify -> review current vs target parameters -> write and verify -> save Flash -> power cycle -> saved readback -> PASS. One primary button per step; the page never offers zero save or motion commands.
- New backend endpoints `GET /api/single-motor/wizard/options`, `POST /api/single-motor/wizard/identify`, `POST /api/single-motor/wizard/<job_id>/write|save|finish`, and `GET /api/single-motor/records`.
- Identify auto-starts the selected SocketCAN port at the requested bitrate when it is down or misconfigured (`sudo -n ip link`), scans ESC IDs 0x01-0x20, and blocks on no motor, multiple motors, fault status, unknown status codes or over-temperature before any job is created.
- Every wizard failure returns a structured problem (title, explanation, ordered fix steps, technical detail) from a single troubleshooting catalog; hardware exceptions are converted to an `unknown_error` problem instead of a raw 502. Retryable problems (CAN, identification, save, no answer after power cycle) can be retried in place; the finish step keeps the job retryable when the motor has not answered yet after the power cycle.
- A completed single-motor ID test (pass or fail) no longer writes `report.html`; it saves one immutable single-motor commissioning record per run under `artifacts/factory/single_motor_records/<record_id>.json` (target IDs, before/after readback, recorded TIMEOUT, firmware, final status, product line, joint, job reference, workstation version). These records are inputs for the later whole-arm factory report.
- The Damiao `SN` register is not unique per motor: during the 2026-09-17 live batch, four different factory-new motors all read `SN=1412444213`. It is stored only as raw `sn_register` evidence and never used as a motor identity. "Already configured" is judged from the IDs the motor currently carries (factory default MST_ID 0x00 vs. a Profile joint's ESC/MST pair). Legacy SN-grouped record files are split automatically into per-record files and the original is kept under `_legacy_by_sn/`.
- The wizard lists recent saved records. The completion card and records table show the post-power-cycle readback (ESC_ID, MST_ID, control mode, bitrate with raw `can_br` code, bus mode, TIMEOUT); new records also store these under `verified`.
- Identify shows the motor model check: Damiao motors expose no model register, so the family is inferred from the factory limit registers (PMAX/VMAX/TMAX, matched against the driver's `LIMIT_PARAM` table; Gr shown as evidence) and compared with the joint's Profile motor type. A mismatch or unknown result shows a warning and keeps "写入并校验" disabled until the operator confirms the nameplate. J3 (DM-J4340P) and J4 (DM-J4340) share limits and must be distinguished by nameplate. The check is stored in the record as `model_check`.
- "配置下一颗电机" advances to the next joint, and identify warns when the selected joint already has a PASS record from a different motor SN.
- The previous single-motor controls, official commands, diagnostics and vendor maintenance tools remain available unchanged under "高级工具（工程师）"; the left task rail and live monitor rail are hidden while the wizard is shown.

Verification:

- `.venv/bin/python -m pytest -q`: 96 passed, including two motors sharing an SN register value producing two separate records, legacy SN-grouped record migration, including motor model inference (DM8009 match, DM4310-on-J1 mismatch, DM4340 match, unreadable limits), wizard happy path (ID change, no motion/zero/write/save during finish, record content, no report.html, previous-record lookup), no-motor / multiple-motor blocking, fault blocking, retryable no-answer readback, readback drift failure record, and the API-level wizard flow with problem envelope.
- Headless Chromium walkthrough against a fake-driver server on port 5055: all five steps, the parameter-change highlight, the problem panel and the advanced-tools view rendered without page errors.
- Live hardware, 2026-09-17: R-J1, R-J2, L-J1 and L-J2 (four factory-new DM8009-family motors, all reporting SN register 1412444213) configured PASS; migrated to four separate records. First motor on can0 (CAN 2.0, 1 Mbps). MST_ID changed 0x00 -> 0x11, ESC_ID stayed 0x01, CTRL_MODE MIT, `can_br` code 4 (1 Mbps), TIMEOUT 0 recorded; saved readback after power cycle PASS with no motion.

Operational Notes:

- Operators should use the wizard; engineers use the advanced tools. Neither path saves a loose-motor zero by default.
- The whole-arm factory report does not yet read `single_motor_records`; linking those records into the final report is a follow-up.

### 0.7.0-single-saved-readback - 2026-09-17

Summary: loose-motor ID commissioning now completes with a no-motion saved-parameter readback instead of zero save and a motion ping.

Changes:

- Default (non-expert) single-motor ID jobs no longer offer `zero`; the backend rejects zero save unless the job is an expert `single_id_config` job, enforcing `single_motor_zero_save_default=False`.
- After `save_flash`, the `test` action runs a `saved_readback` check: it reads back ESC_ID, MST_ID, CTRL_MODE, can_br and the other target fields plus motor status, never enables the motor or sends motion frames, and passes the job with a report only when readback matches and the motor is fault-free, disabled and within temperature limits.
- `safe_mit_ping` (absolute `q=0.05 -> 0` MIT command) is only reachable from the `zeroed` state of an expert job, so an un-zeroed motor is never driven toward absolute zero.
- A failed single-motor test now also writes the job report for traceability.
- `run_comm_check` on a saved single-motor ID job previously dispatched to the motion ping; it now resolves to the same no-motion saved readback.
- Single-motor ID target configs report `requires_zero=False` and `test_profile=saved_readback`.
- UI: the single-motor step bar, execute panel, primary workflow action and confirmation dialog show the saved-readback step (with a power-cycle-before-readback hint); the zero button is hidden for non-expert jobs; the write-params hint no longer claims TIMEOUT is written.

Verification:

- `.venv/bin/python -m pytest -q`: 90 passed, including new coverage for the no-motion default flow (no enable/MIT/zero/write/save calls during readback), the expert zero plus motion ping flow, a readback MST_ID drift failure, and the API-level flow (zero rejected, saved readback passes).
- `node --check web/static/js/app.js`: passed.
- Not yet verified on live hardware (no USB-CAN adapter attached on 2026-09-17).

Operational Notes:

- Loose-motor commissioning flow: write params -> readback verify -> save Flash -> (power cycle recommended) -> saved readback -> report. No zero is saved and no motion command is sent.
- Operational zero remains an assembled-arm step (official dynamic zero calibration). Expert zero on a loose motor is only for documented service fixtures with a known mechanical reference.

### 0.6.18-esc-id-ack-transition - 2026-09-01

Summary: eliminated false ESC ID write failures when a motor acknowledges with its newly assigned ID.

Changes:

- Serial and SocketCAN drivers temporarily recognize both the old and target ESC IDs while waiting for the parameter-write acknowledgement.
- A successful acknowledgement atomically updates the driver's motor mapping; a timeout removes the temporary target mapping and preserves the original identity.
- Added regression coverage for new-ID acknowledgements on both transports.

### 0.6.17-single-timeout-stage-guard - 2026-09-01

Summary: enforced the existing rule that operational TIMEOUT standardization belongs to assembled-arm acceptance, not loose-motor commissioning.

Changes:

- Non-expert single-motor ID/parameter jobs now keep the measured `TIMEOUT` as read-only evidence instead of inheriting the assembled-arm Profile target.
- Default single-motor writes are limited to communication identity fields; `TIMEOUT`, `Gr`, `KT_Value`, `PMAX`, `VMAX`, and `TMAX` require an explicit expert parameter-service job.
- The single-motor comparison UI labels `TIMEOUT` as a read-only record.
- Restored the live R-J1 under test from the mistakenly applied `TIMEOUT=5000` to its pre-test measured value `0`, with Flash save and readback verification.

### 0.6.16-left-timeout-unification - 2026-08-05

Summary: standardized the assembled left arm to the same TIMEOUT policy as the right arm.

Changes:

- The left-arm Profile now requires `TIMEOUT=5000` for L-J1 through L-J8.
- The commissioning policy and live checklist now expose J1-J8=`5000` for both arm sides.
- The TIMEOUT-only maintenance tool accepts repeatable exact joint-name filters, so scoped writes do not touch unrelated motors.
- The live L-J1 through L-J4 update followed `disable -> write -> readback -> save Flash -> readback`; the whole left arm then passed a no-motion readback at `5000`.

### 0.6.15-report-field-integrity - 2026-08-05

Summary: made formal-report test rows and snapshots traceable to their actual measurement stages.

Changes:

- The Low-Gain Enable row now reads the independent same-CN, same-side low-gain record instead of reusing Demo counts.
- The pre-dynamic snapshot now comes only from the arm acceptance job; later motor-check recovery frames cannot be mislabeled as pre-dynamic data.
- TIMEOUT detail rows identify their adjustment evidence and no longer display unrelated static status/frame context from an earlier sample.
- Independent low-gain evidence is copied into the report bundle and included in the evidence hash manifest.

### 0.6.14-report-timeout-evidence - 2026-08-05

Summary: fixed formal-report TIMEOUT overlays for current write and power-cycle evidence formats.

Changes:

- Formal reports now accept passed timeout evidence that uses either `after_save` or power-cycle `timeout` fields.
- Evidence remains restricted to the same whole-arm CN and arm side; the latest passed per-joint value overrides an older static acceptance snapshot.
- Added a regression test proving a later right-arm `TIMEOUT=5000` power-cycle record supersedes an earlier `1000` record.

### 0.6.13-demo-flow-dedup - 2026-08-05

Summary: removed a duplicate post-zero motor-check stage and corrected per-joint motor type decoding.

Changes:

- The zero-calibration workflow now follows the live checklist: pre-zero motor-check, official dynamic zero, power-cycle verification, then Demo.
- Removed the duplicate post-zero `openarm-can-motor-check` step. Existing measured records remain unchanged and are treated as extra verification evidence.
- The safe motor-check wrapper now maps J1-J2 to DM8009, J3-J4 to DM4340, and J5-J8 to DM4310 for both arm ID ranges.
- Added regression coverage for the workflow step order and right/left motor type mapping.

### 0.6.12-right-arm-timeout5000 - 2026-08-05

Summary: synchronized the right-arm workstation policy with the live `OAF26080401` communication-watchdog correction.

Changes:

- Right-arm J1-J8 now require `TIMEOUT=5000`; the left-arm Profile keeps J1-J4=`1000` and J5-J8=`5000`.
- Dynamic readiness reads expected TIMEOUT values from the selected side-specific Profile instead of using hard-coded joint indices.
- API configuration, operator prompts, report guidance, and automated tests now expose the same side-specific policy.
- Live R-J1 through R-J4 values were written, saved to Flash, and independently verified after a power cycle; R-J5 through R-J8 remained at `5000` without redundant Flash writes.
- No motion command was used for the parameter correction or persistence verification.

### 0.6.11-traceability-readiness-sync - 2026-08-05

Summary: aligned optional motor identity handling and the no-motion dynamic readiness gate with the established whole-arm traceability and split TIMEOUT rules.

Changes:

- Reconfirmed from the factory specification and prior formal reports that only the whole-arm CN is required; motors are identified by their side/joint labels, while an internal per-motor traceability number is optional.
- Zero Damiao controller SN/HW readbacks remain preserved as measured values but no longer generate a warning or metadata note when no per-motor identity is assigned.
- Updated the no-motion dynamic readiness tool to require J1-J4 `TIMEOUT=1000` and J5-J8 `TIMEOUT=5000` instead of the obsolete all-joint `1000` rule.
- Control-critical parameter, state, position-stability, CAN, and script-safety checks remain unchanged.

### 0.6.10-metadata-classification - 2026-08-05

Summary: classified zero-valued Damiao controller SN/HW fields according to the factory traceability standard after a raw-frame comparison of R-J4, R-J5, and R-J6.

Changes:

- Confirmed R-J5 repeatedly returns literal zero payloads for RID `0x0F` (SN) and RID `0x0D` (HW); this is not a dropped frame or parser substitution.
- Zero SN/HW values are now retained as `sn_unprogrammed` and `hw_ver_unprogrammed` metadata notes instead of failing an otherwise healthy joint.
- Motor traceability remains strictly based on the matching whole-arm CN and joint label. The workstation does not synthesize or copy controller metadata from another motor.
- Control-critical fields remain blocking: ESC_ID, MST_ID, CTRL_MODE, CAN bitrate, TIMEOUT, online state, fault state, and temperature checks are unchanged.

### 0.6.9-arm-status-policy - 2026-08-05

Summary: corrected the read-only arm status gate after the first right-arm scan under the split TIMEOUT policy.

Changes:

- Read-only arm status checks now compare ESC_ID, MST_ID, control mode, CAN bitrate, and each joint's TIMEOUT against the selected Profile.
- A joint with a mismatched TIMEOUT can no longer be reported as passed merely because it is online, disabled, and fault-free.
- Zero-valued motor `SN` or `hw_ver` readbacks are retained as measured data and explicitly flagged for identity readback investigation.
- No motor parameter write or motion command is part of this status-check correction.

### 0.6.8-timeout-workflow-sync - 2026-08-04

Summary: enforced the current split TIMEOUT policy in the workstation control path, UI, API configuration, tests, and operator documentation.

Changes:

- The assembled-arm TIMEOUT action now reads each joint target from the selected Profile: J1-J4 use `1000`, and J5-J8 use `5000`.
- Removed the browser's hard-coded all-joint `1000` payload. The API now rejects obsolete scalar TIMEOUT overrides so an old client cannot silently overwrite J5-J8.
- The backend validates every Profile target before starting any motor write, then performs the existing disable, write, readback, Flash save, and final readback sequence per joint.
- `/api/config`, workstation guidance, report rules, and both active arm Profiles now expose the same current policy.
- Single-motor testing remains read-only for TIMEOUT by default. Formal reports continue to use measured values from the same arm CN and side rather than substituting Profile targets as measurements.

Verification:

- Added backend coverage for split per-joint writes and API coverage for current policy exposure and rejection of uniform overrides.

### 0.6.7-j4310-timeout-policy - 2026-08-04

Summary: synchronized the active J4310 timeout rule with the actual arm verification profiles after a clean live left-arm read-only scan exposed four stale template mismatches.

Changes:

- Updated the built-in OpenARM profile and code fallback so J1-J4 require `TIMEOUT=1000` and J5-J8 require `TIMEOUT=5000`.
- Both `openarm_right_arm_v1` and `openarm_left_arm_v1` now inherit the same current timeout rule during static acceptance and read-only arm scans.
- No motor parameters were rewritten during this correction; live `OAF26080401` already reported the intended J5-J8 value `5000`.
- Added profile assertions and updated scan fixtures so future changes cannot silently revert J5-J8 to `1000`.
- Formal report packaging now includes only the CAN health record selected for the current release decision, preventing an older superseded snapshot from remaining in the regenerated evidence bundle.

Verification:

- Live pre-fix scan found all eight left-arm joints online, disabled, healthy, with zero CAN errors/drops; its only four mismatches were the stale J5-J8 timeout expectations.
- `pytest -q tests/test_arm_can_scan_cli.py tests/test_workstation.py tests/test_web_api.py`: 71 passed.

### 0.6.6-report-audit - 2026-08-04

Summary: corrected formal report sign-off ownership, evidence evaluation, snapshot provenance, archive deduplication, and PDF readability after auditing `OAF26080401` against previous factory reports.

Changes:

- Restored the established sign-off defaults to test engineer `Peng Cheng` and project lead `Xiang Kun`; generic service labels such as `OpenARM workstation` and `OpenARM QA` are no longer accepted as person names.
- Added sign-off names and report revision to the structured report JSON for machine-readable traceability.
- CAN Health now requires ERROR-ACTIVE, 1 Mbps, interface up, zero RX/TX errors, and zero dropped frames. Existing evidence with `tx_dropped=10` correctly produces `WARNING` and a recapture action.
- TIMEOUT passes only when every measured joint value matches the same-arm expected/adjusted value; mere field presence no longer passes the gate.
- Zero-write PASS now numerically enforces the `0.020 rad` threshold and reports the maximum absolute readback. Near-guard stops such as L-J5 are preserved in the stop summary.
- Final Post-Demo Snapshot values now come from the matching Demo monitor and disable feedback instead of being copied from the static acceptance scan.
- Renamed the post-zero table to Post-Zero Recovery Snapshot to reflect that it is captured after restoring the initial physical pose.
- Motor model, control mode, and CAN baud fields are sourced from the matching profile/evidence instead of fixed report values.
- Formal report generation now rejects opposite-side command fallback and warns when required post-zero or post-Demo status samples are absent.
- Repeated generation of the same report ID replaces its arm archive reference instead of accumulating contradictory duplicate entries.
- PDF output suppresses local file-path headers/footers, keeps Sign-Off together, and prevents raw CAN frames from splitting across lines.

Verification:

- `pytest -q tests/test_workstation.py tests/test_web_api.py`: 70 passed.
- Focused integrity tests cover CAN dropped-frame warnings, numeric zero threshold enforcement, sign-off placeholder replacement, and Demo final-status extraction.

### 0.6.5-report-integrity - 2026-08-04

Summary: locked down formal factory report data integrity after live `OAF26080401` left-arm testing and R-J5 timeout investigation.

Changes:

- Updated the active workstation version to `0.6.5-report-integrity`.
- Formal factory reports now enforce strict same-arm data selection: the arm serial, requested side, requested `profile_id`, and linked `arm_acceptance` job must match before measured data can enter the report.
- Removed the previous global "latest passed job for profile" fallback from formal report generation. A report can no longer borrow data from another arm with the same profile.
- Added structured `missing_required_data` and `recommended_actions` to formal report API responses and JSON output. Missing required evidence now makes the report `WARNING` and tells the operator what to retest or what standard item to remove.
- Added a report "Data Completeness And Follow-Up" section to HTML/PDF output.
- Formal reports no longer fill measured/default motor parameter cells from nominal constants. Missing measured fields are rendered as `-` and listed as missing when they belong to the active report standard.
- ID values in formal reports are shown in hex format such as `0x05`, `0x0D`, and `0x1D`.
- TIMEOUT report overlay now reads same-arm timeout adjustment evidence and supports the live rule used on `OAF26080401`: J1-J4 remain `1000`; J5-J8 J4310 motors are `5000` after the same-arm evidence is present.
- Timeout evidence copying now skips invalid or empty JSON files so stale 0-byte evidence cannot enter the report hash manifest.
- Added `/api/config.report_data_policy` so AI-assisted workflows and browser-only workflows use the same integrity rules.
- Updated the workbench report UI to display final decision, missing required data, recommended actions, and the report data-source policy after report generation.

Verification:

- Syntax checked `src/workstation.py` and `src/formal_factory_report.py` with direct Python compilation.
- Regenerated `OAF26080401` left-arm formal report after attaching same-serial CAN health evidence.
- Confirmed report result is `PASS`, `missing_required_data=[]`, J5-J8 TIMEOUT values are `5000`, CAN health evidence is under `OAF26080401`, and evidence hashes include no 0-byte files.
- Confirmed workbench service restarted and `/api/config` exposes `workstation_version = 0.6.5-report-integrity`.

Operational Notes:

- Report templates may keep fixed section structure and wording, but measured values, status frames, parameter values, evidence paths, and PASS/WARNING decisions must come from the corresponding arm serial and side.
- If a required item was actually measured but not linked, attach or recapture same-serial evidence before final report generation.
- If a future test standard removes an item, remove it from the active report standard instead of emitting blank or fixed values.
- Right-arm `R-J5` remains on hold pending its separate issue resolution; the current PASS report is for `OAF26080401` left arm only.

### 0.6.4-factory-flow-sync - 2026-06-24

Summary: synchronized the latest live Follower right/left arm factory flow into the workstation so the next arm can follow the same steps from the UI.

Changes:

- Updated the active workstation version to `0.6.4-factory-flow-sync`.
- Added a controlled whole-arm `TIMEOUT=1000` standardization action to the static acceptance area.
- The new TIMEOUT action performs `disable -> write TIMEOUT -> readback -> save Flash -> readback` per joint and does not send motion commands.
- Kept loose single-motor ID commissioning separate from operational TIMEOUT standardization; TIMEOUT is standardized after assembled-arm static acceptance and before official zero/Demo.
- Formal factory reports now prefer the latest passed arm acceptance job for the requested arm side/profile so old failed pre-standardization scans do not contaminate final PASS reports.
- Formal zero parsing now treats successful official zero write/readback as pass even when initial-pose restore is performed as a separate evidence step.
- Preserved the current official zero defaults used in live testing: max bump `90 deg`, timeout `20 s`, velocity threshold `0.2 deg/s`, control step `0.005 s`, gripper skipped during zero, initial-pose restore enabled, restore max `120 deg`.
- Preserved the `L-J8` / CAN ID `0x10` special status-frame handling used during left-arm Demo validation.
- Confirmed `OAF26062401` Follower right-arm and left-arm final reports are PASS using the synchronized flow.

Verification:

- `PYTHONPYCACHEPREFIX=/tmp/openarm_pycache python3 -m py_compile src/workstation.py src/formal_factory_report.py web/app.py`
- `node --check web/static/js/app.js web/static/js/event-bindings.js web/static/js/store.js`
- Live `OAF26062401` right-arm factory report: `artifacts/reports/OAF26062401_right_arm_20260624/OpenARM_Follower_Right_Arm_Factory_Test_Report_20260624.pdf`
- Live `OAF26062401` left-arm factory report: `artifacts/reports/OAF26062401_left_arm_20260624/OpenARM_Follower_Left_Arm_Factory_Test_Report_20260624.pdf`

Operational Notes:

- Recommended assembled-arm order is now: static acceptance scan -> whole-arm TIMEOUT standardization when needed -> official dynamic zero -> restore initial pose -> official Demo -> formal report generation.
- The TIMEOUT standardization action is a parameter write/save action. Operators must still confirm correct side/profile, clear workspace, and available emergency stop or power cut before running it.

### 0.6.3-single-id-safety - 2026-06-22

Summary: locked in the current single-motor ID commissioning rule and fixed a Damiao status-frame parsing edge case found during live motor setup.

Changes:

- Updated the active workstation version to `0.6.3-single-id-safety`.
- Standardized the single-motor ID commissioning rule: write only communication-critical fields by default (`ESC_ID`, `MST_ID`, `CTRL_MODE`, `can_br`, and recorded `TIMEOUT=0` when required by the current ID setup flow).
- Kept `Gr`, `KT_Value`, `PMAX`, `VMAX`, and `TMAX` as read/record fields during single-motor ID setup unless an operator intentionally performs a separate parameter service step.
- Confirmed `TIMEOUT` remains read/record-only during loose-motor ID setup; OpenARM acceptance-stage standardization is handled later in the assembled-arm workflow.
- Fixed SocketCAN Damiao frame classification so status frames whose third payload byte equals `0x33` or `0x55` are not misclassified as parameter frames.
- Added a regression test for the L-J4 case where a valid status frame such as `0C5F557FF8001F1C` previously produced zero position/temperature feedback in the workstation.
- Reconfirmed left-arm `L-J8` with `ESC_ID=0x10` / `MST_ID=0x20` remains supported.

Verification:

- `./.venv/bin/python -m pytest tests/test_workstation.py::test_socketcan_status_payload_with_0x55_position_byte_is_not_param_frame tests/test_workstation.py::test_status_payload_reads_error_from_first_byte_not_position_byte tests/test_workstation.py::test_probe_joint_unknown_status_is_not_passed -q` -> `3 passed`
- `PYTHONPYCACHEPREFIX=/tmp/openarm_pycache ./.venv/bin/python -m py_compile src/damiao_motor_driver.py src/workstation.py`
- Live L-J4 retest after restart: `ESC_ID=0x0C`, `MST_ID=0x1C`, status frame `0C5F557FF7FD1F1C`, position `-3.1901 rad`, MOS/rotor `31/28 C`, no fault, CAN error counters `0`.
- Live single-motor ID commissioning completed for the current set: right arm `R-J1` to `R-J8` and left arm `L-J1` to `L-J8`.

Operational Notes:

- This update changes the workstation status-frame parser and the documented default single-motor ID commissioning rule.
- It does not add automatic Damiao vendor encoder calibration, output-shaft calibration, or loose-motor zero-save.
- Operators should continue using Damiao upper software or an approved fixture for vendor encoder/output-shaft calibration only when abnormal feedback or Damiao support guidance requires it.

### 0.6.2-vendor-maintenance - 2026-06-10

Summary: added safe Damiao DMTool integration for manual vendor maintenance records.

Changes:

- Added workstation API endpoints to report DMTool availability, launch the DMTool AppImage, and store manual vendor maintenance records.
- Added a single-motor page card for opening DMTool and recording motor encoder calibration, output shaft encoder calibration, and zero-save status.
- Stored vendor maintenance records under `artifacts/factory/vendor_maintenance/records`.
- Kept vendor encoder calibration as manual-record-only; the workstation still does not automatically execute encoder calibration or zero-save vendor actions.
- Updated web API tests to use temporary artifact directories so test runs do not touch real factory records.
- Kept arm-scan missing parameter reads as unknown matrix cells instead of reporting false parameter mismatches.
- Updated tests to reflect the current safe default that single-joint link tests are read-only unless enable is explicitly allowed.
- Removed obsolete one-off report generator scripts that could still emit old `Motor SN` / `Not assigned` report tables.
- Updated the V4 factory QA spec and UI wording to use optional internal motor trace IDs instead of required motor SN wording.
- Added `pytest.ini` so default test discovery only runs workstation tests and does not collect external OpenARM example scripts that require live `can0`.

Verification:

- `PYTHONPYCACHEPREFIX=/tmp/openarm_pycache python3 -m py_compile src/workstation.py web/app.py`
- `node --check web/static/js/app.js web/static/js/event-bindings.js web/static/js/store.js`
- `./.venv/bin/python -m pytest tests/test_web_api.py -q`
- `./.venv/bin/python -m pytest tests/test_web_api.py tests/test_workstation.py -q` -> `67 passed`
- `./.venv/bin/python -m pytest -q` -> `73 passed`
- Confirmed `/api/config` exposes `workstation_version = 0.6.2-vendor-maintenance`.

Operational Notes:

- This update does not change single-motor parameter writes, whole-arm scan, official zero calibration, Demo, or factory report PASS/FAIL gates.

### 0.6.1-calibration-policy - 2026-06-10

Summary: documented the Damiao encoder calibration, zero-save, and TIMEOUT policy without changing the active test flow.

Changes:

- Added `docs/DAMIAO_CALIBRATION_POLICY.md` to separate vendor encoder calibration, OpenARM zero save, and TIMEOUT standardization rules.
- Exposed a non-invasive `commissioning_policy` block through `/api/config` so the UI and reports can reference the current policy later.
- Clarified that single-motor ID commissioning should not routinely write `TIMEOUT` or save an operational arm zero.
- Clarified that whole-arm factory acceptance remains the stage for OpenARM `TIMEOUT` standardization, official dynamic zero calibration, and Demo.

Verification:

- `PYTHONPYCACHEPREFIX=/tmp/openarm_pycache python3 -m py_compile src/workstation.py`
- Confirmed `/api/config` data exposes `workstation_version = 0.6.1-calibration-policy` and the new `commissioning_policy` block.

Operational Notes:

- No motor-control sequence, endpoint behavior, report generation rule, or UI action gating was changed in this update.

### 0.6.0-factory-report - 2026-06-10

Summary: factory report format and traceability cleanup for the OpenARM Damiao workstation.

Changes:

- Added the workstation version file `VERSION`.
- Added this workstation changelog and versioning rule.
- Standardized the factory report rule that motor serial numbers are not reported; motors are identified by joint labels such as `R-J1` and `L-J1`.
- Separated acceptance-critical test items from recorded default motor configuration items.
- Ensured recorded default motor parameters do not appear as `RECORDED` results and do not affect PASS/FAIL acceptance gates.
- Corrected report model labels so `J3` is `DM-J4340P-2EC` and `J4` is `DM-J4340-2EC`.
- Regenerated the `OAF26060901` left-arm and right-arm factory reports with corrected model labels and formal report layout.
- Fixed the left-arm 2026-06-09 report regeneration path to avoid producing compact fallback PDFs as formal deliverables.
- Exposed the workstation version through the `/api/config` response as `workstation_version`.

Verification:

- `python3 -m py_compile src/formal_factory_report.py tools/generate_follower_left_factory_report_20260609.py tools/generate_follower_right_factory_report_20260610.py`
- Confirmed the left-arm report is a Chromium/Skia PDF, `PASS`, and contains no `Motor SN`, `Not assigned`, or `RECORDED` result fields.
- Confirmed the right-arm report lists `R-J3 = DM-J4340P-2EC` and `R-J4 = DM-J4340-2EC`.

Operational Notes:

- Snap Chromium may require `snapd.apparmor` to be running before formal PDF generation.
- Formal factory reports should fail or preserve the last valid formal PDF rather than silently replacing it with a fallback layout.

## Entry Template

### x.y.z[-suffix] - YYYY-MM-DD

Summary:

- Short purpose of the update.

Changes:

- Change 1.
- Change 2.

Verification:

- Command or test result.
- Manual check result, if applicable.

Operational Notes:

- Any hardware, safety, report, or operator impact.
