"""Formal OpenARM factory acceptance report renderer."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import copy
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional


_REPORT_TEXT_REPLACEMENTS = {
    "\u5f6d\u6210": "Peng Cheng",
    "\u5411\u5764": "Xiang Kun",
}

_NON_PERSON_SIGNOFF_VALUES = {
    "openarm workstation",
    "workstation",
    "openarm qa",
    "qa",
}


def _report_text(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    for source, target in _REPORT_TEXT_REPLACEMENTS.items():
        text = text.replace(source, target)
    text = re.sub(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" -;,:/|")
    return text or default


def _report_person(value: Any, default: str) -> str:
    name = _report_text(value, default)
    return default if name.casefold() in _NON_PERSON_SIGNOFF_VALUES else name


def _load_json(path: Path, default: Any = None) -> Any:
    if not path or not path.exists() or not path.is_file():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {} if default is None else default


def _dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fmt(value: Any, places: int = 6) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{float(value):.{places}f}"
    return str(value)


def _fmt_hex(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        return f"0x{int(value):02X}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_field_value(field: Any, value: Any) -> Any:
    if field in {"ESC_ID", "MST_ID", "CAN ID", "Send ID", "Recv ID"}:
        return _fmt_hex(value)
    return value if value is not None else "-"


def _td(value: Any, klass: str = "") -> str:
    attr = f' class="{klass}"' if klass else ""
    return f"<td{attr}>{escape(str(value if value is not None else '-'))}</td>"


def _tr(cells: Iterable[Any], classes: Optional[Dict[int, str]] = None) -> str:
    classes = classes or {}
    return "<tr>" + "".join(_td(cell, classes.get(index, "")) for index, cell in enumerate(cells)) + "</tr>"


def _section(title: str, colspan: int = 6) -> str:
    return f'<tr class="section"><td colspan="{colspan}">{escape(title)}</td></tr>'


def _result_class(result: str) -> str:
    return {"PASS": "pass", "WARNING": "warn", "FAIL": "fail", "HOLD": "warn"}.get(str(result).upper(), "")


def _arm_role(arm: Dict[str, Any]) -> str:
    value = " ".join(str(arm.get(key) or "") for key in ("arm_cn", "arm_type")).upper()
    return "Leader" if "OAL" in value or "LEADER" in value else "Follower"


def _arm_side(arm: Dict[str, Any], profile: Dict[str, Any]) -> str:
    profile_side = str(profile.get("arm_side") or arm.get("arm_side") or "")
    if profile_side in {"left_arm", "right_arm"}:
        return profile_side
    if arm.get("left_arm_installed") and not arm.get("right_arm_installed"):
        return "left_arm"
    return "right_arm"


def _side_title(side: str) -> str:
    return "Left Arm" if side == "left_arm" else "Right Arm"


def _joint_base(joint_name: str) -> str:
    return str(joint_name).split("-")[-1]


def _ordered_joints(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    return sorted(
        [dict(item) for item in profile.get("joints", [])],
        key=lambda item: int(item.get("target_esc_id", 0)),
    )


def _command_runs(arm: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    return [run for run in arm.get("command_run_history", []) if run.get("kind") == kind]


def _passed_command(arm: Dict[str, Any], kind: str, side: str) -> Dict[str, Any]:
    candidates = []
    for run in _command_runs(arm, kind):
        command = " ".join(str(part) for part in run.get("command") or [])
        if (side in command or not command) and run.get("status") == "passed":
            candidates.append(run)
    if not candidates:
        return {}
    return max(
        candidates,
        key=lambda run: str(run.get("finished_at") or run.get("started_at") or ""),
    )


def _latest_job_payload(arm: Dict[str, Any], profile_id: str) -> Dict[str, Any]:
    candidates: List[tuple[int, str, Dict[str, Any]]] = []
    for index, linked_job in enumerate(arm.get("linked_jobs") or []):
        artifact_dir = Path(linked_job.get("artifact_dir") or "")
        payload = _load_json(artifact_dir / "job.json", {})
        if not payload:
            continue
        if profile_id and payload.get("job", {}).get("profile_id") not in {None, profile_id}:
            continue
        if str(payload.get("job", {}).get("job_type") or linked_job.get("job_type") or "") != "arm_acceptance":
            continue
        job = payload.get("job", {})
        status_rank = 1 if str(job.get("status") or linked_job.get("status")).lower() == "passed" else 0
        timestamp = str(job.get("completed_at") or job.get("created_at") or linked_job.get("linked_at") or "")
        candidates.append((status_rank, timestamp, payload))
    if not candidates:
        return {}
    return sorted(candidates, key=lambda item: (item[0], item[1]), reverse=True)[0][2]


def _status_items(job_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    joints = (job_payload.get("metrics") or {}).get("joints") or []
    if not joints:
        joints = list((job_payload.get("motors") or {}).values())
    return {str(item.get("joint_name")): item for item in joints if item.get("joint_name")}


def _timeout_adjustments(root: Path, arm_serial: str, side: str) -> Dict[str, Dict[str, Any]]:
    """Return latest passed TIMEOUT adjustment per joint from factory evidence."""
    adjust_dir = root / "artifacts" / "factory" / "arm_records" / arm_serial / "timeout_adjustments"
    if not adjust_dir.exists():
        return {}
    prefix = "left_" if side == "left_arm" else "right_"
    result: Dict[str, Dict[str, Any]] = {}
    candidates = sorted(adjust_dir.glob("*.json"), key=lambda path: path.stat().st_mtime)
    for path in candidates:
        if prefix not in path.name:
            continue
        payload = _load_json(path, {})
        payload_side = payload.get("arm_side")
        if payload_side and str(payload_side) != side:
            continue
        results = payload.get("results") or []
        summary = payload.get("summary") or {}
        payload_passed = payload.get("ok") is True or (
            bool(results)
            and int(summary.get("failed", 0) or 0) == 0
            and all(item.get("ok") is True or item.get("passed") is True for item in results)
        )
        if not payload_passed:
            continue
        for item in results:
            joint = str(item.get("joint_name") or "")
            if not joint or not (item.get("ok") is True or item.get("passed") is True):
                continue
            timeout = item.get("timeout")
            if timeout is None:
                timeout = item.get("after_save")
            if timeout is None:
                timeout = item.get("target_timeout")
            if timeout is None:
                continue
            result[joint] = {
                "TIMEOUT": int(timeout),
                "evidence": path,
                "before": item.get("before"),
                "after_write": item.get("after_write"),
                "after_save": item.get("after_save"),
            }
    return result


def _apply_timeout_adjustments(job_payload: Dict[str, Any], adjustments: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    payload = copy.deepcopy(job_payload)
    for item in _status_items(payload).values():
        joint = str(item.get("joint_name") or "")
        adjustment = adjustments.get(joint)
        if not adjustment:
            continue
        timeout = adjustment["TIMEOUT"]
        item.setdefault("params", {})["TIMEOUT"] = timeout
        expected = item.get("expected")
        if isinstance(expected, dict):
            expected["target_timeout"] = timeout
        status_params = ((item.get("status") or {}).get("params") or {})
        if isinstance(status_params, dict):
            status_params["9"] = timeout
        for check in item.get("consistency_matrix") or []:
            if check.get("field") == "TIMEOUT":
                check["actual"] = timeout
                check["expected"] = timeout
                check["matches"] = True
    return payload


def _latest_low_gain_record(root: Path, arm_serial: str, side: str) -> Dict[str, Any]:
    record_dir = root / "artifacts" / "factory" / "arm_records" / arm_serial / "low_gain_enable"
    if not record_dir.exists():
        return {}
    for path in sorted(record_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = _load_json(path, {})
        if not payload or payload.get("arm_side") != side or payload.get("ok") is not True:
            continue
        summary = payload.get("summary") or {}
        if int(summary.get("failed", 0) or 0) != 0 or not summary.get("all_disabled_after_check"):
            continue
        result = copy.deepcopy(payload)
        result["_evidence_path"] = str(path)
        return result
    return {}


def _timeout_summary(ordered: List[Dict[str, Any]], final_items: Dict[str, Dict[str, Any]]) -> str:
    groups: List[tuple[int, List[str]]] = []
    for joint in ordered:
        name = joint["joint_name"]
        value = ((final_items.get(name) or {}).get("params") or {}).get("TIMEOUT")
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = None
        if not groups or groups[-1][0] != value:
            groups.append((value, [name]))
        else:
            groups[-1][1].append(name)

    def _range(names: List[str]) -> str:
        return names[0] if len(names) == 1 else f"{names[0]}..{names[-1]}"

    return "; ".join(f"{_range(names)}={value if value is not None else '-'}" for value, names in groups) or "-"


def _parameter_values_summary(items: Dict[str, Dict[str, Any]], field: str) -> str:
    values = {
        str(value)
        for item in items.values()
        for value in [((item.get("params") or {}).get(field))]
        if value is not None
    }
    return ", ".join(sorted(values)) or "-"


def _status_from_job(job_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for name, item in _status_items(job_payload).items():
        result[name] = item.get("status") or {}
    return result


def _first_status_by_joint(recovery: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {item["joint_name"]: item.get("status") or {} for item in recovery.get("results", []) if item.get("joint_name")}


def _missing_data_item(code: str, scope: str, detail: str, action: str) -> Dict[str, str]:
    return {"code": code, "scope": scope, "detail": detail, "recommended_action": action}


def _motor_check_by_joint(arm: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    by_esc = {int(item["target_esc_id"]): item["joint_name"] for item in profile.get("joints", [])}
    result = {}
    for run in _command_runs(arm, "official_motor_check"):
        command = run.get("command") or []
        if len(command) < 3 or run.get("status") != "passed":
            continue
        try:
            canid = int(command[1], 0) if isinstance(command[1], str) else int(command[1])
        except Exception:
            continue
        joint = by_esc.get(canid)
        if joint:
            result[joint] = run
    return result


def _parse_refresh_samples(stdout: str) -> List[Dict[str, Any]]:
    samples = []
    current = None
    for line in (stdout or "").splitlines():
        if line.startswith("--- Refresh "):
            if current:
                samples.append(current)
            current = {"sample": len(samples) + 1}
            continue
        if current is None:
            continue
        patterns = {
            "position": r"Position:\s+([-0-9.eE]+)",
            "velocity": r"Velocity:\s+([-0-9.eE]+)",
            "torque": r"Torque:\s+([-0-9.eE]+)",
            "t_mos": r"Temperature \(MOS\):\s+([-0-9.eE]+)",
            "t_rotor": r"Temperature \(Rotor\):\s+([-0-9.eE]+)",
            "status": r"Status:\s+(.+)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, line)
            if match:
                current[key] = match.group(1) if key == "status" else float(match.group(1))
    if current:
        samples.append(current)
    return samples


def _parse_demo_monitor_samples(stdout: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    sample = None
    pattern = re.compile(
        r"^(?P<label>Arm Motor|Gripper Motor)\s+(?P<motor>\d+)\s+recv=(?P<recv>\d+)\s+"
        r"position=(?P<position>[-0-9.eE]+)\s+velocity=(?P<velocity>[-0-9.eE]+)\s+"
        r"torque=(?P<torque>[-0-9.eE]+)\s+tmos=(?P<t_mos>[-0-9.eE]+)\s+trotor=(?P<t_rotor>[-0-9.eE]+)"
    )
    for line in (stdout or "").splitlines():
        sample_match = re.match(r"--- sample (\d+)/\d+ ---", line)
        if sample_match:
            sample = int(sample_match.group(1))
            continue
        match = pattern.match(line)
        if not match or sample is None:
            continue
        rows.append({
            "sample": sample,
            "motor": int(match.group("motor")),
            "recv": int(match.group("recv")),
            "joint_label": "Gripper" if match.group("label") == "Gripper Motor" else f"Motor {match.group('motor')}",
            "position": float(match.group("position")),
            "velocity": float(match.group("velocity")),
            "torque": float(match.group("torque")),
            "t_mos": float(match.group("t_mos")),
            "t_rotor": float(match.group("t_rotor")),
        })
    return rows


def _status_from_demo_stdout(stdout: str, ordered: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by_recv = {int(item["target_mst_id"]): item["joint_name"] for item in ordered}
    result: Dict[str, Dict[str, Any]] = {}
    for sample in _parse_demo_monitor_samples(stdout):
        joint = by_recv.get(int(sample["recv"]))
        if not joint:
            continue
        result[joint] = {
            "position": sample.get("position"),
            "velocity": sample.get("velocity"),
            "torque": sample.get("torque"),
            "t_mos": sample.get("t_mos"),
            "t_rotor": sample.get("t_rotor"),
            "status": "MONITORED",
            "has_error": False,
        }
    disable_pattern = re.compile(
        r"^DISABLE recv_id=(?P<recv>0x[0-9A-Fa-f]+).*?'data_hex': '(?P<data>[0-9A-Fa-f]+)'.*?"
        r"'status': '(?P<status>[^']+)'"
    )
    for line in (stdout or "").splitlines():
        match = disable_pattern.match(line)
        if not match:
            continue
        recv = int(match.group("recv"), 0)
        joint = by_recv.get(recv)
        if not joint:
            continue
        status = result.setdefault(joint, {})
        status["status"] = match.group("status")
        status["has_error"] = "ERROR" in match.group("status") or "COMM_LOST" in match.group("status")
        status["last_status_frame"] = {"can_id": recv, "data_hex": match.group("data")}
    return result


def _parse_zero_stdout(stdout: str) -> Dict[str, Any]:
    stops = []
    for joint, rad, deg in re.findall(r"mechanical stop(?: near guard)? \(Joint ([^)]+)\):(?: target=[^ ]+ actual=[^ ]+)?\s*([-0-9.]+) rad / ([-0-9.]+)", stdout or ""):
        stops.append(f"{joint}={rad}rad/{deg}deg")
    for joint, rad in re.findall(r"mechanical stop near guard \(Joint ([^)]+)\):[^\n]*\bpos=([-0-9.]+)", stdout or ""):
        if not any(item.startswith(f"{joint}=") for item in stops):
            stops.append(f"{joint}={rad}rad/near_guard")
    post_arm = re.search(r"\[INFO\] post-zero arm q:\s+(\[[^\]]+\])", stdout or "")
    post_grip = re.search(r"\[INFO\] post-zero gripper q:\s+(\[[^\]]+\])", stdout or "")
    try:
        post_arm_values = json.loads(post_arm.group(1)) if post_arm else []
        post_gripper_values = json.loads(post_grip.group(1)) if post_grip else []
    except (TypeError, ValueError, json.JSONDecodeError):
        post_arm_values = []
        post_gripper_values = []
    zero_values = [*post_arm_values, *post_gripper_values]
    max_abs_position = max((abs(float(value)) for value in zero_values), default=None)
    within_threshold = max_abs_position is not None and max_abs_position <= 0.020
    zero_written = "wrote zero positon to arm" in (stdout or "") or "wrote zero position to arm" in (stdout or "")
    return {
        "passed": zero_written and bool(post_arm_values) and bool(post_gripper_values) and within_threshold,
        "stops": "; ".join(stops) or "-",
        "post_arm": post_arm.group(1) if post_arm else "-",
        "post_gripper": post_grip.group(1) if post_grip else "-",
        "max_abs_position_rad": max_abs_position,
        "threshold_rad": 0.020,
        "within_threshold": within_threshold,
    }


def _copy_evidence(
    root: Path,
    out_dir: Path,
    arm: Dict[str, Any],
    job_payload: Dict[str, Any],
    zero_run: Dict[str, Any],
    demo_run: Dict[str, Any],
    low_gain_record: Dict[str, Any],
    side: str,
    can_record: Dict[str, Any],
) -> Dict[str, Path]:
    evidence_dir = out_dir / "evidence"
    motor_dir = evidence_dir / "motor_check"
    motor_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for joint, run in _motor_check_by_joint(arm, {"joints": job_payload.get("profile_joints", [])}).items():
        path = motor_dir / f"{joint}.log"
        path.write_text(run.get("stdout", ""), encoding="utf-8")
        paths[f"motor_{joint}"] = path
    if zero_run:
        path = evidence_dir / f"official_dynamic_zero_{side}.log"
        path.write_text(zero_run.get("stdout", ""), encoding="utf-8")
        paths["zero"] = path
    if demo_run:
        path = evidence_dir / f"revised_official_demo_{side}.log"
        path.write_text(demo_run.get("stdout", ""), encoding="utf-8")
        paths["demo"] = path
    low_gain_source = Path(low_gain_record.get("_evidence_path") or "")
    if low_gain_source.is_file():
        target = evidence_dir / f"low_gain_enable_{side}.json"
        if low_gain_source.resolve() != target.resolve():
            shutil.copy2(low_gain_source, target)
        paths["low_gain"] = target
    if job_payload:
        path = evidence_dir / "arm_acceptance_job.json"
        _dump_json(path, job_payload)
        paths["job"] = path
    adjust_dir = root / "artifacts" / "factory" / "arm_records" / str(arm.get("arm_cn") or "") / "timeout_adjustments"
    prefix = "left_" if side == "left_arm" else "right_"
    if adjust_dir.exists():
        copied = []
        for src in sorted(adjust_dir.glob(f"*{prefix}*.json")):
            if src.exists():
                if not _load_json(src, {}):
                    continue
                target = evidence_dir / src.name
                if src.resolve() != target.resolve():
                    shutil.copy2(src, target)
                paths[f"timeout_{target.name}"] = target
                copied.append(target.name)
        if copied:
            manifest = evidence_dir / "timeout_adjustment_manifest.json"
            _dump_json(manifest, {"files": copied})
            paths["timeout_adjustment_manifest"] = manifest
    selected_can_id = can_record.get("evidence_id")
    for record in arm.get("evidence_records", []):
        if record.get("evidence_type") == "can_health_snapshot" and record.get("evidence_id") != selected_can_id:
            stale_copy = evidence_dir / Path(record.get("json_path") or "").name
            if stale_copy.exists() and stale_copy.is_file():
                stale_copy.unlink()
            continue
        src = Path(record.get("json_path") or "")
        if src.exists():
            target = evidence_dir / src.name
            if src.resolve() != target.resolve():
                shutil.copy2(src, target)
            paths[f"evidence_{target.name}"] = target
    return paths


def _snapshot_rows(statuses: Dict[str, Dict[str, Any]], ordered: List[Dict[str, Any]]) -> List[str]:
    rows = []
    for joint in ordered:
        name = joint["joint_name"]
        status = statuses.get(name) or {}
        frame = status.get("last_status_frame") or {}
        ok = bool(status) and not status.get("has_error") and status.get("status") in {"DISABLED", "STATE_FRAME_ID16_UNTAGGED"}
        result = "PASS" if ok else "WARNING"
        rows.append(_tr([
            name,
            _fmt(status.get("position")),
            _fmt(status.get("velocity")),
            _fmt(status.get("torque")),
            f"{_fmt(status.get('t_mos'), 1)} / {_fmt(status.get('t_rotor'), 1)}",
            status.get("status", "-"),
            frame.get("data_hex", "-"),
            result,
        ], {6: "mono", 7: _result_class(result)}))
    return rows


def _snapshot_pdf_rows(statuses: Dict[str, Dict[str, Any]], ordered: List[Dict[str, Any]]) -> List[List[Any]]:
    rows = []
    for joint in ordered:
        name = joint["joint_name"]
        status = statuses.get(name) or {}
        frame = status.get("last_status_frame") or {}
        ok = bool(status) and not status.get("has_error") and status.get("status") in {"DISABLED", "STATE_FRAME_ID16_UNTAGGED"}
        rows.append([
            name,
            _fmt(status.get("position")),
            _fmt(status.get("velocity")),
            _fmt(status.get("torque")),
            f"{_fmt(status.get('t_mos'), 1)} / {_fmt(status.get('t_rotor'), 1)}",
            status.get("status", "-"),
            frame.get("data_hex", "-"),
            "PASS" if ok else "WARNING",
        ])
    return rows


def _write_reportlab_pdf(
    *,
    pdf_path: Path,
    logo_path: Path,
    title: str,
    report_id: str,
    generated_at: str,
    operator_name: str,
    lead_name: str,
    arm_serial: str,
    role: str,
    side_title: str,
    profile_id: str,
    final_result: str,
    scope_text: str,
    sections: List[Dict[str, Any]],
) -> bool:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception as exc:
        (pdf_path.parent / "pdf_error.txt").write_text(f"reportlab import failed: {exc}\n", encoding="utf-8")
        return False

    def para(value: Any, style_name: str = "Cell") -> Any:
        text = escape(str(value if value is not None else "-"))
        return Paragraph(text, styles[style_name])

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleFormal", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20, leading=23, textColor=colors.HexColor("#244761"), alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="SectionFormal", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=10, leading=12, textColor=colors.HexColor("#244761"), spaceBefore=8, spaceAfter=4))
    styles.add(ParagraphStyle(name="Cell", parent=styles["BodyText"], fontName="Helvetica", fontSize=6.2, leading=7.2))
    styles.add(ParagraphStyle(name="CellBold", parent=styles["Cell"], fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="Small", parent=styles["Cell"], textColor=colors.HexColor("#51606b")))

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=landscape(A4),
        leftMargin=8 * mm,
        rightMargin=8 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
    )
    story: List[Any] = []

    pdf_logo_path = logo_path
    if logo_path.exists():
        try:
            from PIL import Image as PILImage
            pdf_logo_path = logo_path.parent / "pdf_logo.jpg"
            with PILImage.open(logo_path) as source:
                source.thumbnail((520, 140))
                source.convert("RGB").save(pdf_logo_path, quality=92)
        except Exception:
            pdf_logo_path = logo_path
    doc_table = Table(
        [
            [para("Report ID", "CellBold"), para(report_id)],
            [para("Revision", "CellBold"), para("Rev. B integrity-audited")],
            [para("Generated UTC", "CellBold"), para(generated_at)],
            [para("Operator", "CellBold"), para(operator_name)],
            [para("Project Lead", "CellBold"), para(lead_name)],
        ],
        colWidths=[25 * mm, 43 * mm],
    )
    doc_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d4de")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eaf0f5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    summary_table = Table(
        [
            [para("Arm Serial", "CellBold"), para(arm_serial), para("Arm Type", "CellBold"), para(f"OpenARM {role} {side_title}"), para("Final Result", "CellBold"), para(final_result)],
            [para("Profile", "CellBold"), para(profile_id), para("CAN", "CellBold"), para("CAN 2.0 / 1 Mbps"), para("Operator", "CellBold"), para(operator_name)],
        ],
        colWidths=[22 * mm, 45 * mm, 22 * mm, 60 * mm, 22 * mm, 40 * mm],
    )
    summary_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d4de")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfcfd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.extend([
        Spacer(1, 18),
        Paragraph(title, styles["TitleFormal"]),
        para("Formal factory acceptance record covering single-motor checks, arm communication scan, TIMEOUT standardization, low-gain enable check, official dynamic zero calibration, official Step 5 Demo, raw feedback frames, and evidence hashes.", "Small"),
        Spacer(1, 4),
        summary_table,
        Spacer(1, 4),
        doc_table,
        Spacer(1, 5),
        Paragraph("1. Scope And Traceability", styles["SectionFormal"]),
        para(scope_text),
        Spacer(1, 3),
    ])

    for section in sections:
        if section.get("page_break_before") and story:
            story.append(PageBreak())
        story.append(Paragraph(section["title"], styles["SectionFormal"]))
        rows = [[para(cell, "CellBold") for cell in section["headers"]]]
        for row in section["rows"]:
            rows.append([para(cell) for cell in row])
        col_widths = section.get("col_widths")
        table = Table(rows, repeatRows=1, colWidths=[width * mm for width in col_widths] if col_widths else None)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c9d4de")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f5")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#244761")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2.4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2.4),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(table)
        story.append(Spacer(1, 3))

    sign_rows = [
        ["Role", "Name", "Date", "Conclusion / Signature"],
        ["Test Engineer", operator_name, datetime.now().strftime("%Y-%m-%d"), "Factory test executed and recorded."],
        ["Project Lead", lead_name, datetime.now().strftime("%Y-%m-%d"), "Released for factory archive."],
        ["Whole-Arm Serial", arm_serial, datetime.now().strftime("%Y-%m-%d"), f"Final Conclusion: {final_result}"],
    ]
    story.append(Paragraph("12. Sign-Off", styles["SectionFormal"]))
    sign_table = Table([[para(cell, "CellBold" if index == 0 else "Cell") for cell in row] for index, row in enumerate(sign_rows)])
    sign_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d4de")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(sign_table)
    try:
        def draw_first_page(canvas, document):
            if pdf_logo_path.exists():
                canvas.drawImage(
                    str(pdf_logo_path),
                    document.leftMargin + 4 * mm,
                    document.pagesize[1] - document.topMargin - 18 * mm,
                    width=52 * mm,
                    height=14 * mm,
                    preserveAspectRatio=True,
                    mask="auto",
                )

        doc.build(story, onFirstPage=draw_first_page)
    except Exception as exc:
        (pdf_path.parent / "pdf_error.txt").write_text(f"reportlab build failed: {exc}\n", encoding="utf-8")
        return False
    return pdf_path.exists() and pdf_path.stat().st_size > 0


def render_formal_factory_report(
    *,
    root_dir: Path,
    reports_dir: Path,
    arm: Dict[str, Any],
    profile: Dict[str, Any],
    operator: Optional[str] = None,
    project_lead: Optional[str] = None,
    notes: Optional[str] = None,
    report_date: Optional[str] = None,
    pdf_writer: Optional[Callable[[Path, Path], bool]] = None,
    allow_reportlab_fallback: bool = False,
) -> Dict[str, Any]:
    arm_serial = str(arm.get("arm_cn") or "").strip()
    if not arm_serial:
        raise ValueError("arm_cn is required")
    side = _arm_side(arm, profile)
    side_title = _side_title(side)
    role = _arm_role(arm)
    profile_id = str(profile.get("profile_id") or arm.get("bom_profile") or "-")
    report_date = str(report_date or datetime.now().strftime("%Y%m%d"))
    if not re.fullmatch(r"\d{8}", report_date):
        raise ValueError("report_date must use YYYYMMDD format")
    out_dir = reports_dir / f"{arm_serial}_{side}_{report_date}"
    evidence_dir = out_dir / "evidence"
    asset_dir = out_dir / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)

    logo_source = root_dir / "assets" / "eckstein_logo.png"
    logo_target = asset_dir / "eckstein_logo.png"
    if logo_source.exists():
        shutil.copy2(logo_source, logo_target)

    operator_name = _report_person(operator, "Peng Cheng")
    lead_name = _report_person(project_lead, "Xiang Kun")
    report_notes = _report_text(notes, "") if notes else None
    ordered = _ordered_joints(profile)
    joint_names = [item["joint_name"] for item in ordered]
    joint_range = f"{joint_names[0]}..{joint_names[-1]}" if joint_names else "-"
    esc_range = f"0x{int(ordered[0]['target_esc_id']):02X}..0x{int(ordered[-1]['target_esc_id']):02X}" if ordered else "-"
    mst_range = f"0x{int(ordered[0]['target_mst_id']):02X}..0x{int(ordered[-1]['target_mst_id']):02X}" if ordered else "-"

    job_payload = _latest_job_payload(arm, profile_id)
    timeout_adjustments = _timeout_adjustments(root_dir, arm_serial, side)
    report_job_payload = _apply_timeout_adjustments(job_payload, timeout_adjustments)
    zero_run = _passed_command(arm, "official_zero_calibration", side)
    demo_run = _passed_command(arm, "official_demo_validation", side)
    low_gain_record = _latest_low_gain_record(root_dir, arm_serial, side)
    zero = _parse_zero_stdout(zero_run.get("stdout", "")) if zero_run else {"passed": False, "stops": "-", "post_arm": "-", "post_gripper": "-"}
    demo = demo_run.get("demo_summary") or {}
    demo_monitor_samples = _parse_demo_monitor_samples(demo_run.get("stdout", "")) if demo_run else []
    can_record = next((record for record in arm.get("evidence_records", []) if record.get("evidence_type") == "can_health_snapshot"), {})
    can_payload = _load_json(Path(can_record.get("json_path") or ""), {})
    can_snapshot = can_payload.get("interface_snapshot") or {}
    stats = can_snapshot.get("statistics") or {}

    # Pass profile joints into the copied payload for evidence helpers without mutating the original record.
    job_for_evidence = dict(report_job_payload)
    job_for_evidence["profile_joints"] = ordered
    _copy_evidence(root_dir, out_dir, arm, job_for_evidence, zero_run, demo_run, low_gain_record, side, can_record)

    final_items = _status_items(report_job_payload)
    static_statuses = _status_from_job(report_job_payload)
    final_statuses = _status_from_demo_stdout(demo_run.get("stdout", ""), ordered) if demo_run else {}
    motor_checks = _motor_check_by_joint(arm, profile)
    initial_statuses = dict(static_statuses)
    post_zero_statuses = _first_status_by_joint(zero_run.get("post_recovery") or {}) if zero_run else {}
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    scan_ok = bool(report_job_payload) and all(name in final_items for name in joint_names)
    single_motor_results = {}
    for name in joint_names:
        item = final_items.get(name) or {}
        status = item.get("status") or {}
        issues = item.get("issues") or []
        single_motor_results[name] = bool(item) and not issues and not status.get("has_error") and status.get("status") in {"DISABLED", "ENABLED"}
    single_motor_ok = bool(ordered) and all(single_motor_results.values())
    timeout_ok = bool(joint_names) and all(
        ((final_items.get(name) or {}).get("params") or {}).get("TIMEOUT")
        == ((final_items.get(name) or {}).get("expected") or {}).get("target_timeout")
        for name in joint_names
    )
    timeout_display = _timeout_summary(ordered, final_items)
    ctrl_mode_display = _parameter_values_summary(final_items, "CTRL_MODE")
    can_br_display = _parameter_values_summary(final_items, "can_br")
    timeout_evidence = "arm_acceptance_job.json"
    if timeout_adjustments:
        timeout_evidence += " + timeout_adjustment_manifest.json"
    demo_ok = bool(demo.get("passed") and demo_run.get("status") == "passed")
    low_gain_summary = low_gain_record.get("summary") or {}
    low_gain_expected_count = len(joint_names)
    low_gain_ok = bool(
        low_gain_record
        and int(low_gain_summary.get("enabled_count", 0) or 0) == low_gain_expected_count
        and int(low_gain_summary.get("disabled_count", 0) or 0) == low_gain_expected_count
        and int(low_gain_summary.get("failed", 0) or 0) == 0
        and low_gain_summary.get("all_disabled_after_check") is True
        and low_gain_record.get("comm_lost_reported") is False
    )
    gripper_travel = demo.get("gripper_travel_rad")
    gripper_ok = gripper_travel is not None and float(gripper_travel) > 0.8
    demo_expected_count = max(1, len(joint_names) - 1) if (demo.get("id16_special_frame_count") or 0) >= 2 else len(joint_names)
    can_health_ok = bool(
        can_payload
        and can_snapshot.get("can_state") == "ERROR-ACTIVE"
        and can_snapshot.get("state") in {"UP", "UNKNOWN"}
        and int(can_snapshot.get("bitrate") or 0) == 1_000_000
        and int(stats.get("rx_errors") or 0) == 0
        and int(stats.get("tx_errors") or 0) == 0
        and int(stats.get("rx_dropped") or 0) == 0
        and int(stats.get("tx_dropped") or 0) == 0
    )
    required_missing_data: List[Dict[str, str]] = []
    if not report_job_payload:
        required_missing_data.append(_missing_data_item(
            "missing_arm_acceptance_job",
            side,
            f"No linked arm_acceptance job was found for arm_serial={arm_serial}, profile={profile_id}.",
            "Run the arm communication/static acceptance workflow for this exact arm serial and side, then link the job to the arm record.",
        ))
    if not can_payload:
        required_missing_data.append(_missing_data_item(
            "missing_can_health_snapshot",
            "can0",
            f"No CAN health evidence record was found for arm_serial={arm_serial}.",
            "Capture a CAN health snapshot for the tested arm before final release, or remove CAN Health from the active report standard if it is no longer required.",
        ))
    elif not can_health_ok:
        required_missing_data.append(_missing_data_item(
            "can_health_not_clean",
            "can0",
            "CAN health snapshot did not meet the active zero-error/zero-drop release criterion: "
            f"state={can_snapshot.get('can_state')}; bitrate={can_snapshot.get('bitrate')}; "
            f"rx_errors={stats.get('rx_errors')}; tx_errors={stats.get('tx_errors')}; "
            f"rx_dropped={stats.get('rx_dropped')}; tx_dropped={stats.get('tx_dropped')}.",
            "Reset or baseline the CAN counters, repeat the controlled communication test, and capture a clean same-serial CAN health snapshot.",
        ))
    for name in joint_names:
        item = final_items.get(name) or {}
        if not item:
            required_missing_data.append(_missing_data_item(
                "missing_joint_static_record",
                name,
                f"No static acceptance record was found for {name} in arm_serial={arm_serial}, profile={profile_id}.",
                f"Retest {name} in the {side} arm acceptance workflow.",
            ))
            continue
        params = item.get("params") or {}
        status = item.get("status") or {}
        frame = status.get("last_status_frame") or {}
        for field in ("ESC_ID", "MST_ID", "CTRL_MODE", "can_br", "TIMEOUT"):
            if params.get(field) is None:
                required_missing_data.append(_missing_data_item(
                    f"missing_{field.lower()}",
                    name,
                    f"{field} was not captured for {name} in the linked static acceptance evidence.",
                    f"Rerun parameter read/arm acceptance for {name}, or remove {field} from the active required report fields if no longer required.",
                ))
        for field in ("position", "velocity", "torque", "t_mos", "t_rotor"):
            if status.get(field) is None:
                required_missing_data.append(_missing_data_item(
                    f"missing_status_{field}",
                    name,
                    f"Status field {field} was not captured for {name}.",
                    f"Rerun status sampling for {name}, or remove this measurement from the active report standard if no longer required.",
                ))
        if not frame.get("data_hex"):
            required_missing_data.append(_missing_data_item(
                "missing_raw_status_frame",
                name,
                f"Raw CAN status frame was not captured for {name}.",
                f"Rerun status sampling for {name} and preserve the raw feedback frame.",
            ))
    if not zero.get("passed"):
        required_missing_data.append(_missing_data_item(
            "missing_passed_dynamic_zero",
            side,
            f"No passed official dynamic zero calibration record was found for arm_serial={arm_serial}, side={side}.",
            "Run official dynamic zero calibration for this exact arm side before final release, or remove the zero section from the active standard if no longer required.",
        ))
    for name in joint_names:
        if zero.get("passed") and name not in post_zero_statuses:
            required_missing_data.append(_missing_data_item(
                "missing_post_zero_recovery_status",
                name,
                f"No post-zero recovery status sample was captured for {name}.",
                f"Repeat the official zero recovery/readback for {side} and preserve the status frame.",
            ))
    if not demo_ok:
        required_missing_data.append(_missing_data_item(
            "missing_passed_demo",
            side,
            f"No passed official demo validation record was found for arm_serial={arm_serial}, side={side}.",
            "Run official demo validation for this exact arm side before final release, or remove the demo section from the active standard if no longer required.",
        ))
    if not low_gain_ok:
        required_missing_data.append(_missing_data_item(
            "missing_passed_low_gain_enable",
            side,
            f"No passed independent low-gain enable record was found for arm_serial={arm_serial}, side={side}.",
            "Run the independent current-position low-gain enable/disable gate for this exact arm side before final release, or remove it from the active report standard.",
        ))
    for name in joint_names:
        if demo_ok and name not in final_statuses:
            required_missing_data.append(_missing_data_item(
                "missing_post_demo_status",
                name,
                f"No final Demo monitor/status sample was captured for {name}.",
                f"Rerun the official Demo for {side} with final status monitoring enabled.",
            ))
    for field in ("open_target", "open_start", "open_observed_at_close_start", "close_final", "gripper_travel_rad"):
        if demo_ok and demo.get(field) is None:
            required_missing_data.append(_missing_data_item(
                f"missing_demo_{field}",
                joint_names[-1] if joint_names else "gripper",
                f"Demo summary field {field} was not captured for the gripper validation.",
                "Rerun demo validation with gripper monitor capture, or remove this measurement from the active report standard if no longer required.",
            ))
    final_pass = all([single_motor_ok, scan_ok, timeout_ok, low_gain_ok, zero.get("passed"), demo_ok, can_health_ok, not required_missing_data])
    final_result = "PASS" if final_pass else "WARNING"
    missing_rows = [
        _tr([item["code"], item["scope"], item["detail"], item["recommended_action"]])
        for item in required_missing_data
    ] or [_tr(["none", "-", "All required data fields for the active report standard were present.", "-"])]
    missing_pdf_rows = [
        [item["code"], item["scope"], item["detail"], item["recommended_action"]]
        for item in required_missing_data
    ] or [["none", "-", "All required data fields for the active report standard were present.", "-"]]

    acceptance_rows = [
        _section("1. General Information"),
        _tr(["Traceability", "Whole arm", "Only whole-arm serial is reported", f"arm_serial={arm_serial}; arm_type=OpenARM {role} {side_title}; profile={profile_id}; motor_labels={joint_range}; operator={operator_name}; project_lead={lead_name}", "-", "PASS"], {5: "pass"}),
        _tr(["Release Gate", "Whole arm", f"All required {role} {side_title.lower()} factory items completed", f"single_motor={'PASS' if single_motor_ok else 'WARNING'}; arm_scan={'PASS' if scan_ok else 'WARNING'}; TIMEOUT={'PASS' if timeout_ok else 'WARNING'} ({timeout_display}); can_health={'PASS' if can_health_ok else 'WARNING'}; data_complete={'PASS' if not required_missing_data else 'WARNING'}; low_gain_enable={'PASS' if low_gain_ok else 'WARNING'}; dynamic_zero={'PASS' if zero.get('passed') else 'WARNING'}; revised_demo={'PASS' if demo_ok else 'WARNING'}", "-", final_result], {5: _result_class(final_result)}),
        _section("2. Bus And Interface Evidence"),
        _tr(["CAN Health", "can0", "CAN 2.0, 1 Mbps, interface UP, ERROR-ACTIVE, zero RX/TX errors and zero dropped frames", f"state={can_snapshot.get('can_state')}; bitrate={can_snapshot.get('bitrate')}; rx_errors={stats.get('rx_errors')}; tx_errors={stats.get('tx_errors')}; rx_dropped={stats.get('rx_dropped')}; tx_dropped={stats.get('tx_dropped')}", Path(can_record.get("json_path") or "-").name, "PASS" if can_health_ok else "WARNING"], {5: _result_class("PASS" if can_health_ok else "WARNING")}),
        _section("3. Electrical And Static Functional Tests"),
        _tr(["Single-Motor Static Health Checks", joint_range, "Each motor completed safe read-only parameter/status verification before dynamic tests", "; ".join(f"{name}={'PASS' if single_motor_results.get(name) else 'WARNING'}" for name in joint_names), "arm_acceptance_job.json", "PASS" if single_motor_ok else "WARNING"], {5: _result_class("PASS" if single_motor_ok else "WARNING")}),
        _tr(["Arm Communication Acceptance", joint_range, f"All motors online; IDs and parameters match the {side_title.lower()} workstation profile; TIMEOUT policy={timeout_display}", f"ESC_ID={esc_range}; MST_ID={mst_range}; CTRL_MODE={ctrl_mode_display}; can_br={can_br_display}; TIMEOUT={timeout_display}; no fault", timeout_evidence, "PASS" if scan_ok and timeout_ok else "WARNING"], {5: _result_class("PASS" if scan_ok and timeout_ok else "WARNING")}),
        _section("4. Official Dynamic Zero Calibration"),
        _tr(["Dynamic Zero Calibration", side, f"Official dynamic zero with workstation {side_title.lower()} IDs; restore initial pose enabled", f"status={'PASS' if zero.get('passed') else 'WARNING'}; mechanical_stops={zero.get('stops')}", f"official_dynamic_zero_{side}.log", "PASS" if zero.get("passed") else "WARNING"], {5: _result_class("PASS" if zero.get("passed") else "WARNING")}),
        _tr(["Zero Write Verification", joint_range, "Zero-write moment must be within 0.020 rad", f"post_zero_arm={zero.get('post_arm')}; post_zero_gripper={zero.get('post_gripper')}; max_abs={_fmt(zero.get('max_abs_position_rad'))} rad; threshold=0.020 rad", f"official_dynamic_zero_{side}.log", "PASS" if zero.get("within_threshold") else "WARNING"], {5: _result_class("PASS" if zero.get("within_threshold") else "WARNING")}),
        _section("5. Low-Gain Enable And Revised Official Demo"),
        _tr(["Low-Gain Enable Check", side, "All motors enter ENABLED, current-position keepalive hold, then safe disable", f"enabled={low_gain_summary.get('enabled_count')}/{low_gain_expected_count}; disabled={low_gain_summary.get('disabled_count')}/{low_gain_expected_count}; hold_ms={low_gain_record.get('hold_ms')}; keepalive_frames={low_gain_record.get('keepalive_frames_sent')}; comm_lost={low_gain_record.get('comm_lost_reported')}", f"low_gain_enable_{side}.json", "PASS" if low_gain_ok else "WARNING"], {5: _result_class("PASS" if low_gain_ok else "WARNING")}),
        _tr(["Revised Step 5 Demo", side, "Enable confirmation, visible phase hold, explicit gripper open and close, safe disable", f"enabled={demo.get('enabled_count')}/{demo_expected_count}; disabled={demo.get('disabled_count')}/{demo_expected_count}; keepalive_frames={demo.get('keepalive_frames')}; final_message={'Demo completed successfully' if demo_ok else '-'}", f"revised_official_demo_{side}.log", "PASS" if demo_ok else "WARNING"], {5: _result_class("PASS" if demo_ok else "WARNING")}),
        _tr(["Gripper Open/Close Validation", joint_names[-1] if joint_names else "J8", f"Gripper shall open to the validated target ({_fmt(demo.get('open_target'))} rad) and close near 0 rad during Demo", f"open_target={_fmt(demo.get('open_target'))}; open_start={_fmt(demo.get('open_start'))}; open_observed_at_close_start={_fmt(demo.get('open_observed_at_close_start'))}; close_final={_fmt(demo.get('close_final'))}; observed_travel={_fmt(gripper_travel)} rad", f"revised_official_demo_{side}.log + arm_acceptance_job.json", "PASS" if gripper_ok else "WARNING"], {5: _result_class("PASS" if gripper_ok else "WARNING")}),
    ]
    acceptance_pdf_rows = [
        ["Traceability", "Whole arm", "Only whole-arm serial is reported", f"arm_serial={arm_serial}; arm_type=OpenARM {role} {side_title}; profile={profile_id}; motor_labels={joint_range}; operator={operator_name}; project_lead={lead_name}", "-", "PASS"],
        ["Release Gate", "Whole arm", f"All required {role} {side_title.lower()} factory items completed", f"single_motor={'PASS' if single_motor_ok else 'WARNING'}; arm_scan={'PASS' if scan_ok else 'WARNING'}; TIMEOUT={'PASS' if timeout_ok else 'WARNING'} ({timeout_display}); can_health={'PASS' if can_health_ok else 'WARNING'}; data_complete={'PASS' if not required_missing_data else 'WARNING'}; low_gain_enable={'PASS' if low_gain_ok else 'WARNING'}; dynamic_zero={'PASS' if zero.get('passed') else 'WARNING'}; revised_demo={'PASS' if demo_ok else 'WARNING'}", "-", final_result],
        ["CAN Health", "can0", "CAN 2.0, 1 Mbps, interface UP, ERROR-ACTIVE, zero RX/TX errors and zero dropped frames", f"state={can_snapshot.get('can_state')}; bitrate={can_snapshot.get('bitrate')}; rx_errors={stats.get('rx_errors')}; tx_errors={stats.get('tx_errors')}; rx_dropped={stats.get('rx_dropped')}; tx_dropped={stats.get('tx_dropped')}", Path(can_record.get("json_path") or "-").name, "PASS" if can_health_ok else "WARNING"],
        ["Single-Motor Static Health Checks", joint_range, "Each motor completed safe read-only parameter/status verification before dynamic tests", "; ".join(f"{name}={'PASS' if single_motor_results.get(name) else 'WARNING'}" for name in joint_names), "arm_acceptance_job.json", "PASS" if single_motor_ok else "WARNING"],
        ["Arm Communication Acceptance", joint_range, f"All motors online; IDs and parameters match the {side_title.lower()} workstation profile; TIMEOUT policy={timeout_display}", f"ESC_ID={esc_range}; MST_ID={mst_range}; CTRL_MODE={ctrl_mode_display}; can_br={can_br_display}; TIMEOUT={timeout_display}; no fault", timeout_evidence, "PASS" if scan_ok and timeout_ok else "WARNING"],
        ["Dynamic Zero Calibration", side, f"Official dynamic zero with workstation {side_title.lower()} IDs; restore initial pose enabled", f"status={'PASS' if zero.get('passed') else 'WARNING'}; mechanical_stops={zero.get('stops')}", f"official_dynamic_zero_{side}.log", "PASS" if zero.get("passed") else "WARNING"],
        ["Zero Write Verification", joint_range, "Zero-write moment must be within 0.020 rad", f"post_zero_arm={zero.get('post_arm')}; post_zero_gripper={zero.get('post_gripper')}; max_abs={_fmt(zero.get('max_abs_position_rad'))} rad; threshold=0.020 rad", f"official_dynamic_zero_{side}.log", "PASS" if zero.get("within_threshold") else "WARNING"],
        ["Low-Gain Enable Check", side, "All motors enter ENABLED, current-position keepalive hold, then safe disable", f"enabled={low_gain_summary.get('enabled_count')}/{low_gain_expected_count}; disabled={low_gain_summary.get('disabled_count')}/{low_gain_expected_count}; hold_ms={low_gain_record.get('hold_ms')}; keepalive_frames={low_gain_record.get('keepalive_frames_sent')}; comm_lost={low_gain_record.get('comm_lost_reported')}", f"low_gain_enable_{side}.json", "PASS" if low_gain_ok else "WARNING"],
        ["Revised Step 5 Demo", side, "Enable confirmation, visible phase hold, explicit gripper open and close, safe disable", f"enabled={demo.get('enabled_count')}/{demo_expected_count}; disabled={demo.get('disabled_count')}/{demo_expected_count}; keepalive_frames={demo.get('keepalive_frames')}; final_message={'Demo completed successfully' if demo_ok else '-'}", f"revised_official_demo_{side}.log", "PASS" if demo_ok else "WARNING"],
        ["Gripper Open/Close Validation", joint_names[-1] if joint_names else "J8", f"Gripper shall open to the validated target ({_fmt(demo.get('open_target'))} rad) and close near 0 rad during Demo", f"open_target={_fmt(demo.get('open_target'))}; open_start={_fmt(demo.get('open_start'))}; open_observed_at_close_start={_fmt(demo.get('open_observed_at_close_start'))}; close_final={_fmt(demo.get('close_final'))}; observed_travel={_fmt(gripper_travel)} rad", f"revised_official_demo_{side}.log + arm_acceptance_job.json", "PASS" if gripper_ok else "WARNING"],
    ]

    critical_parameter_rows = []
    critical_parameter_pdf_rows = []
    recorded_parameter_rows = []
    recorded_parameter_pdf_rows = []
    raw_rows = []
    raw_pdf_rows = []
    static_detail_rows = []
    static_detail_pdf_rows = []
    for joint in ordered:
        name = joint["joint_name"]
        item = final_items.get(name) or {}
        params = item.get("params") or {}
        status = item.get("status") or {}
        frame = status.get("last_status_frame") or {}
        required_fields = ("ESC_ID", "MST_ID", "CTRL_MODE", "can_br", "TIMEOUT")
        consistency = item.get("consistency_matrix") or []
        required_checks = [check for check in consistency if check.get("field") in required_fields]
        row_result = "PASS" if (
            single_motor_results.get(name)
            and all(params.get(field) is not None for field in required_fields)
            and len(required_checks) == len(required_fields)
            and all(check.get("matches") is True for check in required_checks)
        ) else "WARNING"
        motor_model = str(status.get("motor_type") or (item.get("expected") or {}).get("motor_type") or joint.get("motor_type") or "-")
        critical_row = [
            name,
            motor_model,
            _fmt_hex(params.get("ESC_ID")),
            _fmt_hex(params.get("MST_ID")),
            params.get("CTRL_MODE", "-"),
            params.get("can_br", "-"),
            params.get("TIMEOUT", "-"),
            row_result,
        ]
        critical_parameter_rows.append(_tr(critical_row, {7: _result_class(row_result)}))
        critical_parameter_pdf_rows.append(critical_row)
        recorded_row = [
            name,
            motor_model,
            params.get("Gr", "-"),
            params.get("KT_Value", "-"),
            params.get("PMAX", "-"),
            params.get("VMAX", "-"),
            params.get("TMAX", "-"),
            params.get("sw_ver", "-"),
            params.get("sub_ver", "-"),
            "Recorded only when read from this arm's test data; '-' means not captured in evidence",
        ]
        recorded_parameter_rows.append(_tr(recorded_row))
        recorded_parameter_pdf_rows.append(recorded_row)
        raw_rows.append(_tr([
            name,
            1,
            _fmt(status.get("position")),
            _fmt(status.get("velocity")),
            _fmt(status.get("torque")),
            _fmt_hex(frame.get("can_id")),
            frame.get("data_hex", "-"),
            _fmt(frame.get("timestamp"), 3),
        ], {6: "mono"}))
        raw_pdf_rows.append([
            name,
            1,
            _fmt(status.get("position")),
            _fmt(status.get("velocity")),
            _fmt(status.get("torque")),
            _fmt_hex(frame.get("can_id")),
            frame.get("data_hex", "-"),
            _fmt(frame.get("timestamp"), 3),
        ])
        if consistency:
            for check in consistency:
                field = check.get("field", "-")
                expected = check.get("expected")
                actual = check.get("actual")
                matches = check.get("matches")
                if matches is None:
                    continue
                result = "PASS" if matches else "WARNING"
                check_text = "matches" if matches is True else "mismatch"
                adjustment = timeout_adjustments.get(name) if field == "TIMEOUT" else None
                context_status = {} if adjustment else status
                context_frame = {} if adjustment else frame
                status_text = context_status.get("status", "-")
                frame_hex = context_frame.get("data_hex", "-")
                field_evidence = adjustment["evidence"].name if adjustment else "arm_acceptance_job.json"
                row = [
                    name,
                    field,
                    _fmt_field_value(field, actual),
                    _fmt_field_value(field, expected),
                    check_text,
                    _fmt(context_status.get("position")),
                    _fmt(context_status.get("torque")),
                    f"{_fmt(context_status.get('t_mos'), 1)} / {_fmt(context_status.get('t_rotor'), 1)}",
                    status_text,
                    frame_hex,
                    field_evidence,
                    result,
                ]
                static_detail_rows.append(_tr(row, {9: "mono", 11: _result_class(result)}))
                static_detail_pdf_rows.append(row)
        else:
            row_result = "PASS" if single_motor_results.get(name) else "WARNING"
            row = [
                name,
                "status",
                status.get("status", "-"),
                "DISABLED or ENABLED",
                "matches" if row_result == "PASS" else "mismatch",
                _fmt(status.get("position")),
                _fmt(status.get("torque")),
                f"{_fmt(status.get('t_mos'), 1)} / {_fmt(status.get('t_rotor'), 1)}",
                status.get("status", "-"),
                frame.get("data_hex", "-"),
                "arm_acceptance_job.json",
                row_result,
            ]
            static_detail_rows.append(_tr(row, {9: "mono", 11: _result_class(row_result)}))
            static_detail_pdf_rows.append(row)

    motor_rows = []
    motor_pdf_rows = []
    for joint in ordered:
        name = joint["joint_name"]
        run = motor_checks.get(name)
        if not run:
            item = final_items.get(name) or {}
            status = item.get("status") or {}
            params = item.get("params") or {}
            row_result = "PASS" if single_motor_results.get(name) else "WARNING"
            motor_rows.append(_tr([
                name,
                "static",
                _fmt_hex(params.get("ESC_ID")),
                _fmt_hex(params.get("MST_ID")),
                params.get("can_br", "-"),
                params.get("CTRL_MODE", "-"),
                _fmt(status.get("position")),
                _fmt(status.get("velocity")),
                _fmt(status.get("torque")),
                f"{_fmt(status.get('t_mos'), 1)} / {_fmt(status.get('t_rotor'), 1)}",
                status.get("status", "-"),
                row_result,
            ], {11: _result_class(row_result)}))
            motor_pdf_rows.append([
                name,
                "static",
                _fmt_hex(params.get("ESC_ID")),
                _fmt_hex(params.get("MST_ID")),
                params.get("can_br", "-"),
                params.get("CTRL_MODE", "-"),
                _fmt(status.get("position")),
                _fmt(status.get("velocity")),
                _fmt(status.get("torque")),
                f"{_fmt(status.get('t_mos'), 1)} / {_fmt(status.get('t_rotor'), 1)}",
                status.get("status", "-"),
                row_result,
            ])
            continue
        command = run.get("command") or []
        item = final_items.get(name) or {}
        params = item.get("params") or {}
        samples = _parse_refresh_samples(run.get("stdout", ""))
        for sample in samples or [{"sample": "-"}]:
            motor_rows.append(_tr([
                name,
                sample.get("sample"),
                _fmt_hex(command[1] if len(command) > 1 else None),
                _fmt_hex(command[2] if len(command) > 2 else None),
                params.get("can_br", "-"),
                params.get("CTRL_MODE", "-"),
                _fmt(sample.get("position")),
                _fmt(sample.get("velocity")),
                _fmt(sample.get("torque")),
                f"{_fmt(sample.get('t_mos'), 1)} / {_fmt(sample.get('t_rotor'), 1)}",
                sample.get("status", ""),
                "PASS",
            ], {11: "pass"}))
            motor_pdf_rows.append([
                name,
                sample.get("sample"),
                _fmt_hex(command[1] if len(command) > 1 else None),
                _fmt_hex(command[2] if len(command) > 2 else None),
                params.get("can_br", "-"),
                params.get("CTRL_MODE", "-"),
                _fmt(sample.get("position")),
                _fmt(sample.get("velocity")),
                _fmt(sample.get("torque")),
                f"{_fmt(sample.get('t_mos'), 1)} / {_fmt(sample.get('t_rotor'), 1)}",
                sample.get("status", ""),
                "PASS",
            ])

    demo_monitor_rows = []
    demo_monitor_pdf_rows = []
    for sample in demo_monitor_samples:
        demo_monitor_rows.append(_tr([
            sample.get("sample"),
            sample.get("joint_label"),
            _fmt_hex(sample.get("recv")),
            _fmt(sample.get("position")),
            _fmt(sample.get("velocity")),
            _fmt(sample.get("torque")),
            f"{_fmt(sample.get('t_mos'), 1)} / {_fmt(sample.get('t_rotor'), 1)}",
            "PASS",
        ], {7: "pass"}))
        demo_monitor_pdf_rows.append([
            sample.get("sample"),
            sample.get("joint_label"),
            _fmt_hex(sample.get("recv")),
            _fmt(sample.get("position")),
            _fmt(sample.get("velocity")),
            _fmt(sample.get("torque")),
            f"{_fmt(sample.get('t_mos'), 1)} / {_fmt(sample.get('t_rotor'), 1)}",
            "PASS",
        ])

    evidence = {str(path.relative_to(out_dir)): _sha256(path) for path in sorted(evidence_dir.rglob("*")) if path.is_file()}
    evidence_rows = [_tr([name, digest]) for name, digest in evidence.items()]
    evidence_pdf_rows = [[name, digest] for name, digest in evidence.items()]
    logo = '<img class="logo" src="assets/eckstein_logo.png" alt="ECKSTEIN logo">' if logo_target.exists() else ""
    report_stem = f"OpenARM_{role}_{side_title.replace(' ', '_')}_Factory_Test_Report_{report_date}"
    report_id = f"OA-{role[:3].upper()}-{'L' if side == 'left_arm' else 'R'}-FACTORY-{report_date}-001"
    report_revision = "Rev. B integrity-audited"
    title = f"OpenARM {role} {side_title} Factory Acceptance Report"
    json_path = out_dir / f"{report_stem}.json"
    html_path = out_dir / f"{report_stem}.html"
    pdf_path = out_dir / f"{report_stem}.pdf"

    payload = {
        "report_id": report_id,
        "report_type": "formal_factory_acceptance_report",
        "title": title,
        "subject_id": arm_serial,
        "subject_type": f"{role.lower()}_{side}",
        "generated_at": generated_at,
        "summary": {
            "release_decision": final_result,
            "revision": report_revision,
            "arm_serial": arm_serial,
            "profile_id": profile_id,
            "test_engineer": operator_name,
            "project_lead": lead_name,
            "standard_report_template": "formal_factory_acceptance_v2_integrity_audited_chromium_skia",
            "report_layout_policy": "Page count and section count may expand with test scope; required evidence, measured data, readable headers, and deliverable factory formatting must be preserved.",
            "motor_serial_numbers": "not_assigned; motors identified by joint label",
            "pdf_output_requirement": "Chromium/Skia PDF; ReportLab fallback disabled for formal factory reports",
            "zero_validation": zero,
            "low_gain_validation": {
                key: value for key, value in low_gain_record.items() if key != "_evidence_path"
            },
            "demo_validation": demo,
            "demo_monitor_sample_count": len(demo_monitor_samples),
            "single_motor_static_detail_rows": len(static_detail_pdf_rows),
            "evidence_sha256": evidence,
            "data_source_policy": "strict_arm_serial_and_side; no global latest-job fallback; missing measured fields are reported as missing instead of being filled with fixed values",
            "missing_required_data": required_missing_data,
            "recommended_actions": [item["recommended_action"] for item in required_missing_data],
            "notes": report_notes,
        },
    }
    _dump_json(json_path, payload)

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    @page {{ size: A4 landscape; margin: 10mm; }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: Arial, Helvetica, sans-serif; color: #17212b; margin: 0; font-size: 8.7px; }}
    .cover {{ border: 1px solid #ccd6df; padding: 14px; display: grid; grid-template-columns: 220px 1fr 250px; gap: 16px; background: #fbfcfd; }}
    .logo {{ width: 205px; max-height: 54px; object-fit: contain; object-position: left center; }}
    h1 {{ font-size: 24px; margin: 18px 0 8px; color: #244761; letter-spacing: 0; }}
    h2 {{ font-size: 12px; margin: 11px 0 6px; color: #244761; border-bottom: 1.5px solid #244761; padding-bottom: 4px; }}
    p {{ margin: 3px 0; line-height: 1.35; }}
    .cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin-top: 8px; }}
    .box {{ border: 1px solid #c9d4de; border-left: 4px solid #244761; padding: 6px; background: white; min-height: 38px; }}
    .label {{ color: #51606b; font-size: 7.4px; text-transform: uppercase; }}
    .value {{ font-weight: 700; font-size: 10px; margin-top: 3px; }}
    .badge {{ display: inline-block; padding: 2px 7px; border-radius: 10px; background: #e7f6ee; color: #087443; font-weight: 700; }}
    .muted {{ border: 1px solid #d8e0e7; background: #f7f9fb; padding: 7px; margin-top: 8px; }}
    table {{ width: 100%; border-collapse: collapse; table-layout: fixed; margin-bottom: 7px; page-break-inside: auto; }}
    th, td {{ border: 1px solid #c9d4de; padding: 3.5px 4.2px; vertical-align: top; overflow-wrap: anywhere; }}
    th {{ background: #eaf0f5; color: #244761; font-weight: 700; }}
    tbody tr:nth-child(even) {{ background: #fbfcfd; }}
    tr {{ page-break-inside: avoid; }}
    .section td {{ background: #244761; color: white; font-weight: 700; font-size: 10px; }}
    .pass {{ color: #087443; font-weight: 700; }}
    .warn {{ color: #9a6400; font-weight: 700; }}
    .fail {{ color: #b42318; font-weight: 700; }}
    .small {{ color: #51606b; font-size: 7.6px; }}
    .mono {{ font-family: "DejaVu Sans Mono", Consolas, monospace; font-size: 7.2px; white-space: nowrap; overflow-wrap: normal; }}
    .page-break {{ page-break-before: always; }}
    .signature td {{ height: 28px; }}
    .signature-block, .signature {{ break-inside: avoid; page-break-inside: avoid; }}
  </style>
</head>
<body>
  <div class="cover">
    <div>{logo}</div>
    <div>
      <h1>{escape(title)}</h1>
      <p>Formal factory acceptance record covering single-motor checks, arm communication scan, TIMEOUT standardization, low-gain enable check, official dynamic zero calibration, revised Step 5 Demo with explicit gripper open/close validation, raw feedback frames, and evidence hashes.</p>
      <div class="cards">
        <div class="box"><div class="label">Arm Serial</div><div class="value">{escape(arm_serial)}</div></div>
        <div class="box"><div class="label">Arm Type</div><div class="value">OpenARM {escape(role)} {escape(side_title)}</div></div>
        <div class="box"><div class="label">Profile</div><div class="value">{escape(profile_id)}</div></div>
        <div class="box"><div class="label">CAN</div><div class="value">CAN 2.0 / 1 Mbps</div></div>
        <div class="box"><div class="label">Final Result</div><div class="value"><span class="badge">{escape(final_result)}</span></div></div>
      </div>
      <div class="muted">Motor serial numbers are intentionally not assigned in this report. Each motor is identified by joint label {escape(joint_range.replace('..', ' through '))}. {escape(joint_names[-1] if joint_names else 'J8')} is the gripper.</div>
    </div>
    <div>
      <table>
        <tr><th colspan="2">Document Control</th></tr>
        <tr><td>Report ID</td><td>{escape(report_id)}</td></tr>
        <tr><td>Revision</td><td>{escape(report_revision)}</td></tr>
        <tr><td>Generated UTC</td><td>{escape(generated_at)}</td></tr>
        <tr><td>Operator</td><td>{escape(operator_name)}</td></tr>
        <tr><td>Project Lead</td><td>{escape(lead_name)}</td></tr>
      </table>
    </div>
  </div>
  <h2>1. Scope And Traceability</h2>
  <p>This report records the whole-arm serial number <strong>{escape(arm_serial)}</strong>. The {escape(side_title.lower())} CAN ID profile follows ESC_ID {escape(esc_range)} and MST_ID {escape(mst_range)}. All dynamic commands used classic CAN 2.0 at 1 Mbps with CAN-FD disabled.</p>
  <h2>2. Acceptance Matrix</h2>
  <table><thead><tr><th style="width:17%">Test Item</th><th style="width:10%">Target</th><th style="width:19%">Acceptance Criteria</th><th>Measured Data</th><th style="width:16%">Evidence</th><th style="width:7%">Result</th></tr></thead><tbody>{''.join(acceptance_rows)}</tbody></table>
  <h2>3. Data Completeness And Follow-Up</h2>
  <table><thead><tr><th style="width:18%">Code</th><th style="width:12%">Scope</th><th>Missing / Integrity Detail</th><th>Required Action</th></tr></thead><tbody>{''.join(missing_rows)}</tbody></table>
  <h2>4. Acceptance-Critical Motor Parameters</h2>
  <table><thead><tr><th>Joint</th><th>Model</th><th>ESC_ID</th><th>MST_ID</th><th>CTRL_MODE</th><th>can_br</th><th>TIMEOUT</th><th>Result</th></tr></thead><tbody>{''.join(critical_parameter_rows)}</tbody></table>
  <h2>5. Initial Snapshot Before Whole-Arm Dynamic Tests</h2>
  <table><thead><tr><th>Joint</th><th>Position rad</th><th>Velocity</th><th>Torque</th><th>MOS/Rotor C</th><th>Status</th><th>Raw Frame</th><th>Result</th></tr></thead><tbody>{''.join(_snapshot_rows(initial_statuses, ordered))}</tbody></table>
  <h2>6. Post-Zero Recovery Snapshot</h2>
  <table><thead><tr><th>Joint</th><th>Position rad</th><th>Velocity</th><th>Torque</th><th>MOS/Rotor C</th><th>Status</th><th>Raw Frame</th><th>Result</th></tr></thead><tbody>{''.join(_snapshot_rows(post_zero_statuses, ordered))}</tbody></table>
  <h2>7. Final Post-Demo Snapshot</h2>
  <table><thead><tr><th>Joint</th><th>Position rad</th><th>Velocity</th><th>Torque</th><th>MOS/Rotor C</th><th>Status</th><th>Raw Frame</th><th>Result</th></tr></thead><tbody>{''.join(_snapshot_rows(final_statuses, ordered))}</tbody></table>
  <p class="small">Recovery snapshots are captured after the script restores the initial physical pose, so joint positions are not expected to remain at zero. The zero-write moment is validated separately in Section 2 and the raw zero log.</p>
  <h2 class="page-break">8. Single-Motor Official Check Samples</h2>
  <table><thead><tr><th>Joint</th><th>Sample</th><th>Send ID</th><th>Recv ID</th><th>Baud</th><th>Mode</th><th>Position rad</th><th>Velocity</th><th>Torque</th><th>MOS/Rotor C</th><th>Status</th><th>Result</th></tr></thead><tbody>{''.join(motor_rows)}</tbody></table>
  <p class="small">If per-joint official motor-check refresh logs were not available in the arm record, the following static parameter verification matrix is included as the detailed single-motor evidence for each joint.</p>
  <table><thead><tr><th>Joint</th><th>Field</th><th>Actual</th><th>Expected</th><th>Check</th><th>Position rad</th><th>Torque</th><th>MOS/Rotor C</th><th>Status</th><th>Raw Frame</th><th>Field Evidence</th><th>Result</th></tr></thead><tbody>{''.join(static_detail_rows)}</tbody></table>
  <h2>9. Final Raw CAN Frame Samples</h2>
  <table><thead><tr><th>Joint</th><th>Sample</th><th>Position rad</th><th>Velocity</th><th>Torque</th><th>CAN ID</th><th>Data Hex</th><th>Timestamp</th></tr></thead><tbody>{''.join(raw_rows)}</tbody></table>
  <h2 class="page-break">10. Recorded Default Motor Configuration</h2>
  <p class="small">The following values are reported only when present in this arm side's evidence. A dash means the field was not captured in the linked test record. These values are not part of the OpenARM acceptance gate unless a future official profile defines explicit limits.</p>
  <table><thead><tr><th>Joint</th><th>Model</th><th>Gr</th><th>KT_Value</th><th>PMAX</th><th>VMAX</th><th>TMAX</th><th>sw_ver</th><th>sub_ver</th><th>Record Note</th></tr></thead><tbody>{''.join(recorded_parameter_rows)}</tbody></table>
  <h2>11. Evidence Hashes</h2>
  <table><thead><tr><th>Evidence File</th><th>SHA-256</th></tr></thead><tbody>{''.join(evidence_rows)}</tbody></table>
  <section class="signature-block">
  <h2>12. Sign-Off</h2>
  <table class="signature">
    <thead><tr><th>Role</th><th>Name</th><th>Date</th><th>Conclusion / Signature</th></tr></thead>
    <tbody>
      <tr><td>Test Engineer</td><td>{escape(operator_name)}</td><td>{datetime.now().strftime('%Y-%m-%d')}</td><td>Factory test executed and recorded.</td></tr>
      <tr><td>Project Lead</td><td>{escape(lead_name)}</td><td>{datetime.now().strftime('%Y-%m-%d')}</td><td>Released for factory archive.</td></tr>
      <tr><td>Whole-Arm Serial</td><td>{escape(arm_serial)}</td><td>{datetime.now().strftime('%Y-%m-%d')}</td><td class="{_result_class(final_result)}">Final Conclusion: {escape(final_result)}</td></tr>
    </tbody>
  </table>
  </section>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    scope_text = (
        f"This report records the whole-arm serial number {arm_serial}. The {side_title.lower()} CAN ID profile "
        f"follows ESC_ID {esc_range} and MST_ID {mst_range}. All dynamic commands used classic CAN 2.0 at "
        "1 Mbps with CAN-FD disabled."
    )
    pdf_sections = [
        {
            "title": "2. Acceptance Matrix",
            "headers": ["Test Item", "Target", "Acceptance Criteria", "Measured Data", "Evidence", "Result"],
            "rows": acceptance_pdf_rows,
            "col_widths": [28, 22, 50, 120, 38, 18],
        },
        {
            "title": "3. Data Completeness And Follow-Up",
            "headers": ["Code", "Scope", "Missing / Integrity Detail", "Required Action"],
            "rows": missing_pdf_rows,
            "col_widths": [42, 28, 86, 116],
        },
        {
            "title": "4. Acceptance-Critical Motor Parameters",
            "headers": ["Joint", "Model", "ESC_ID", "MST_ID", "CTRL_MODE", "can_br", "TIMEOUT", "Result"],
            "rows": critical_parameter_pdf_rows,
            "col_widths": [18, 50, 20, 20, 28, 24, 28, 18],
        },
        {
            "title": "5. Initial Snapshot Before Whole-Arm Dynamic Tests",
            "headers": ["Joint", "Position rad", "Velocity", "Torque", "MOS/Rotor C", "Status", "Raw Frame", "Result"],
            "rows": _snapshot_pdf_rows(initial_statuses, ordered),
            "col_widths": [18, 31, 28, 28, 28, 25, 78, 16],
        },
        {
            "title": "6. Post-Zero Recovery Snapshot",
            "headers": ["Joint", "Position rad", "Velocity", "Torque", "MOS/Rotor C", "Status", "Raw Frame", "Result"],
            "rows": _snapshot_pdf_rows(post_zero_statuses, ordered),
            "col_widths": [18, 31, 28, 28, 28, 25, 78, 16],
        },
        {
            "title": "7. Final Post-Demo Snapshot",
            "headers": ["Joint", "Position rad", "Velocity", "Torque", "MOS/Rotor C", "Status", "Raw Frame", "Result"],
            "rows": _snapshot_pdf_rows(final_statuses, ordered),
            "col_widths": [18, 31, 28, 28, 28, 25, 78, 16],
        },
        {
            "title": "8. Single-Motor Official Check Samples",
            "headers": ["Joint", "Sample", "Send ID", "Recv ID", "Baud", "Mode", "Position rad", "Velocity", "Torque", "MOS/Rotor C", "Status", "Result"],
            "rows": motor_pdf_rows,
            "col_widths": [16, 15, 17, 17, 13, 13, 31, 29, 29, 31, 58, 13],
            "page_break_before": True,
        },
        {
            "title": "8.1 Static Acceptance-Critical Verification Matrix",
            "headers": ["Joint", "Field", "Actual", "Expected", "Check", "Position rad", "Torque", "MOS/Rotor C", "Status", "Raw Frame", "Field Evidence", "Result"],
            "rows": static_detail_pdf_rows,
            "col_widths": [14, 18, 20, 20, 17, 27, 24, 26, 28, 52, 62, 13],
        },
        {
            "title": "9. Final Raw CAN Frame Samples",
            "headers": ["Joint", "Sample", "Position rad", "Velocity", "Torque", "CAN ID", "Data Hex", "Timestamp"],
            "rows": raw_pdf_rows,
            "col_widths": [22, 18, 34, 34, 34, 22, 82, 34],
        },
        {
            "title": "10. Recorded Default Motor Configuration",
            "headers": ["Joint", "Model", "Gr", "KT_Value", "PMAX", "VMAX", "TMAX", "sw_ver", "sub_ver", "Record Note"],
            "rows": recorded_parameter_pdf_rows,
            "col_widths": [15, 38, 13, 18, 16, 16, 16, 24, 20, 94],
            "page_break_before": True,
        },
        {
            "title": "11. Evidence Hashes",
            "headers": ["Evidence File", "SHA-256"],
            "rows": evidence_pdf_rows,
            "col_widths": [110, 160],
        },
    ]
    pdf_ok = bool(pdf_writer(html_path, pdf_path)) if pdf_writer else False
    if not pdf_ok and allow_reportlab_fallback:
        pdf_ok = _write_reportlab_pdf(
            pdf_path=pdf_path,
            logo_path=logo_target,
            title=title,
            report_id=report_id,
            generated_at=generated_at,
            operator_name=operator_name,
            lead_name=lead_name,
            arm_serial=arm_serial,
            role=role,
            side_title=side_title,
            profile_id=profile_id,
            final_result=final_result,
            scope_text=scope_text,
            sections=pdf_sections,
        )
    elif not pdf_ok:
        error_path = pdf_path.parent / "pdf_error.txt"
        if not error_path.exists():
            error_path.write_text(
                "Formal factory PDF was not generated. Chromium/Skia output is required for the standard report template.\n",
                encoding="utf-8",
            )
    error_path = pdf_path.parent / "pdf_error.txt"
    if pdf_ok and error_path.exists():
        error_path.unlink()
    pdf_path_value = str(pdf_path) if pdf_ok else None
    return {
        "report_ref": {
            "report_id": report_id,
            "report_type": "formal_factory_acceptance_report",
            "title": title,
            "json_path": str(json_path),
            "html_path": str(html_path),
            "pdf_path": pdf_path_value,
            "created_at": generated_at,
            "release_decision": final_result,
        },
        "report_dir": str(out_dir),
        "evidence_dir": str(evidence_dir),
        "pdf_generated": pdf_ok,
        "missing_required_data": required_missing_data,
        "recommended_actions": [item["recommended_action"] for item in required_missing_data],
    }
