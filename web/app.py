"""
OpenARM Damiao motor commissioning workstation web server.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from flask_socketio import SocketIO
import threading


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.workstation import WorkstationService  # noqa: E402


app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)
app.config["SECRET_KEY"] = "openarm_motor_commissioning_station"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
service = WorkstationService(socketio=socketio)
_interface_status_task = None
_interface_status_task_lock = threading.Lock()


def _json_ok(payload):
    return jsonify({"success": True, **payload})


def _json_error(message: str, status: int):
    return jsonify({"success": False, "message": message}), status


def _body():
    return request.get_json(silent=True) or {}


@app.errorhandler(KeyError)
def handle_key_error(error):
    return _json_error(str(error), 404)


@app.errorhandler(ValueError)
def handle_value_error(error):
    return _json_error(str(error), 400)


@app.errorhandler(RuntimeError)
def handle_runtime_error(error):
    return _json_error(str(error), 409 if "support" in str(error) else 502)


@app.errorhandler(FileNotFoundError)
def handle_file_not_found(error):
    return _json_error(str(error), 404)


@app.errorhandler(PermissionError)
def handle_permission_error(error):
    return _json_error(str(error), 409)


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/config")
def get_config():
    return _json_ok(service.config())


@app.get("/api/vendor/dmtool/status")
def vendor_dmtool_status():
    return _json_ok(service.vendor_tool_status())


@app.post("/api/vendor/dmtool/launch")
def launch_vendor_dmtool():
    return _json_ok(service.launch_vendor_dmtool())


@app.get("/api/vendor/maintenance-records")
def list_vendor_maintenance_records():
    limit = int(request.args.get("limit", 20))
    return _json_ok(service.list_vendor_maintenance_records(limit=limit))


@app.post("/api/vendor/maintenance-records")
def record_vendor_maintenance():
    data = _body()
    return _json_ok(
        service.record_vendor_maintenance(
            target_label=data.get("target_label", ""),
            maintenance_stage=data.get("maintenance_stage", "single_motor_pre_assembly"),
            motor_encoder_calibration=data.get("motor_encoder_calibration", "not_performed"),
            output_encoder_calibration=data.get("output_encoder_calibration", "not_performed"),
            zero_save=data.get("zero_save", "not_performed"),
            operator=data.get("operator"),
            notes=data.get("notes"),
            linked_job_id=data.get("linked_job_id"),
        )
    )


@app.get("/api/factory/overview")
def factory_overview():
    return _json_ok(service.factory_overview())


@app.post("/api/factory/serials/arm-cn")
def generate_factory_arm_cn():
    data = _body()
    return _json_ok(
        service.generate_factory_arm_cn(
            role=data.get("role", "F"),
            date_code=data.get("date_code"),
            sequence=int(data.get("sequence", 1)),
        )
    )


@app.post("/api/factory/serials/motor-sn")
def generate_factory_motor_sn():
    data = _body()
    return _json_ok(
        service.generate_factory_motor_sn(
            motor_type=data["motor_type"],
            role=data.get("role", "F"),
            can_id=int(data.get("can_id", 1)),
            date_code=data.get("date_code"),
            sequence=int(data.get("sequence", 1)),
        )
    )


@app.post("/api/factory/serials/validate")
def validate_factory_serial():
    data = _body()
    serial_type = data.get("type")
    value = data.get("value", "")
    if serial_type == "arm_cn":
        return _json_ok(service.validate_factory_arm_cn(value))
    if serial_type == "motor_sn":
        return _json_ok(service.validate_factory_motor_sn(value))
    raise ValueError("type must be arm_cn or motor_sn")


@app.get("/api/factory/official-commands")
def official_command_status():
    return _json_ok(service.official_command_status())


@app.post("/api/factory/arms")
def bind_arm_identity():
    data = _body()
    return _json_ok(
        service.bind_arm_identity(
            arm_cn=data["arm_cn"],
            arm_type=data.get("arm_type", "OpenARM Follower"),
            bom_profile=data.get("bom_profile", "openarm_v1"),
            left_arm_installed=bool(data.get("left_arm_installed", True)),
            right_arm_installed=bool(data.get("right_arm_installed", True)),
            notes=data.get("notes"),
            product_version=data.get("product_version"),
        )
    )


@app.post("/api/factory/motors")
def bind_motor_identity():
    data = _body()
    return _json_ok(
        service.bind_motor_identity(
            motor_sn=data["motor_sn"],
            motor_type=data["motor_type"],
            installed_joint=data.get("installed_joint"),
            arm_cn=data.get("arm_cn"),
            esc_id=data.get("esc_id"),
            mst_id=data.get("mst_id"),
            vendor=data.get("vendor", "DaMiao"),
            hw_revision=data.get("hw_revision"),
            fw_version=data.get("fw_version"),
            notes=data.get("notes"),
        )
    )


@app.post("/api/factory/assign-joint")
def assign_joint_motor():
    data = _body()
    return _json_ok(
        service.assign_joint_motor(
            arm_cn=data["arm_cn"],
            joint_name=data["joint_name"],
            motor_sn=data["motor_sn"],
            esc_id=data.get("esc_id"),
            mst_id=data.get("mst_id"),
            motor_type=data.get("motor_type"),
        )
    )


@app.post("/api/factory/attach-job-to-motor")
def attach_job_to_motor():
    data = _body()
    return _json_ok(service.attach_job_to_motor(data["motor_sn"], data["job_id"]))


@app.post("/api/factory/attach-job-to-arm")
def attach_job_to_arm():
    data = _body()
    return _json_ok(service.attach_job_to_arm(data["arm_cn"], data["job_id"]))


@app.post("/api/factory/build-bundle")
def build_factory_bundle():
    data = _body()
    return _json_ok(service.build_factory_bundle(data["arm_cn"]))


@app.post("/api/factory/can-health")
def capture_can_health():
    data = _body()
    return _json_ok(
        service.capture_can_health(
            interface=data.get("interface", "can0"),
            arm_cn=data.get("arm_cn"),
            job_id=data.get("job_id"),
            notes=data.get("notes"),
        )
    )


@app.post("/api/factory/candump-evidence")
def capture_candump_evidence():
    data = _body()
    return _json_ok(
        service.capture_candump_evidence(
            interface=data.get("interface", "can0"),
            duration_s=float(data.get("duration_s", 2.0)),
            arm_cn=data.get("arm_cn"),
            job_id=data.get("job_id"),
            label=data.get("label", "factory_can_trace"),
            notes=data.get("notes"),
        )
    )


@app.get("/api/factory/release-gate/<arm_cn>")
def factory_release_gate(arm_cn: str):
    return _json_ok(service.factory_release_gate(arm_cn))


@app.post("/api/factory/reports/motor-parameter")
def generate_motor_parameter_report():
    data = _body()
    return _json_ok(
        service.generate_motor_parameter_report(
            motor_sn=data["motor_sn"],
            job_id=data.get("job_id"),
            operator=data.get("operator"),
            notes=data.get("notes"),
        )
    )


@app.post("/api/factory/reports/zero-calibration")
def generate_zero_calibration_report():
    data = _body()
    return _json_ok(
        service.generate_zero_calibration_report(
            arm_cn=data["arm_cn"],
            operator=data.get("operator"),
            notes=data.get("notes"),
        )
    )


@app.post("/api/factory/reports/safety-test")
def generate_safety_test_report():
    data = _body()
    return _json_ok(
        service.generate_safety_test_report(
            arm_cn=data["arm_cn"],
            operator=data.get("operator"),
            notes=data.get("notes"),
        )
    )


@app.post("/api/factory/reports/factory-acceptance")
def generate_factory_acceptance_report():
    data = _body()
    return _json_ok(
        service.generate_factory_acceptance_report(
            arm_cn=data["arm_cn"],
            operator=data.get("operator"),
            notes=data.get("notes"),
        )
    )


@app.post("/api/factory/reports/formal-factory-acceptance")
def generate_formal_factory_acceptance_report():
    data = _body()
    return _json_ok(
        service.generate_formal_factory_acceptance_report(
            arm_cn=data["arm_cn"],
            operator=data.get("operator"),
            project_lead=data.get("project_lead"),
            notes=data.get("notes"),
            profile_id=data.get("profile_id"),
            report_date=data.get("report_date"),
        )
    )


@app.post("/api/factory/zero-calibration")
def record_zero_calibration():
    data = _body()
    return _json_ok(
        service.record_zero_calibration(
            arm_cn=data["arm_cn"],
            calibration_scope=data.get("calibration_scope", "whole_arm"),
            status=data.get("status", "passed"),
            operator=data.get("operator"),
            zero_pose_name=data.get("zero_pose_name", "openarm_home"),
            linked_job_id=data.get("linked_job_id"),
            notes=data.get("notes"),
            joints=data.get("joints"),
        )
    )


@app.post("/api/factory/demo-validation")
def record_demo_validation():
    data = _body()
    return _json_ok(
        service.record_demo_validation(
            arm_cn=data["arm_cn"],
            demo_name=data.get("demo_name", "official_demo"),
            status=data.get("status", "passed"),
            operator=data.get("operator"),
            validation_scope=data.get("validation_scope", "official_demo"),
            linked_job_id=data.get("linked_job_id"),
            notes=data.get("notes"),
            command=data.get("command"),
        )
    )


@app.post("/api/factory/zero-workflows/start")
def start_zero_workflow():
    data = _body()
    return _json_ok(
        service.start_factory_workflow(
            arm_cn=data["arm_cn"],
            workflow_type="zero_calibration",
            operator=data.get("operator"),
            linked_job_id=data.get("linked_job_id"),
            notes=data.get("notes"),
            calibration_scope=data.get("calibration_scope", "whole_arm"),
            zero_pose_name=data.get("zero_pose_name", "openarm_home"),
            joints=data.get("joints") or [],
        )
    )


@app.post("/api/factory/zero-workflows/advance")
def advance_zero_workflow():
    data = _body()
    return _json_ok(
        service.advance_factory_workflow(
            arm_cn=data["arm_cn"],
            workflow_type="zero_calibration",
            action=data["action"],
            notes=data.get("notes"),
            final_status=data.get("final_status", "passed"),
        )
    )


@app.post("/api/factory/zero-workflows/run-official")
def run_official_zero_workflow():
    data = _body()
    return _json_ok(
        service.run_official_zero_calibration(
            arm_cn=data["arm_cn"],
            canport=data.get("canport", "can0"),
            arm_side=data.get("arm_side", "right_arm"),
            execute=bool(data.get("execute", False)),
            confirmations=data.get("confirmations") or {},
            timeout_s=int(data.get("timeout_s", 180)),
            max_bump_deg=data.get("max_bump_deg"),
            max_bump_time_s=data.get("max_bump_time_s"),
            bump_step_deg=data.get("bump_step_deg"),
            bump_dt_s=data.get("bump_dt_s"),
            restore_initial_pose=bool(data.get("restore_initial_pose", False)),
            restore_max_deg=data.get("restore_max_deg"),
            skip_gripper_limit_search=bool(data.get("skip_gripper_limit_search", True)),
        )
    )


@app.post("/api/factory/demo-workflows/start")
def start_demo_workflow():
    data = _body()
    return _json_ok(
        service.start_factory_workflow(
            arm_cn=data["arm_cn"],
            workflow_type="demo_validation",
            operator=data.get("operator"),
            linked_job_id=data.get("linked_job_id"),
            notes=data.get("notes"),
            demo_name=data.get("demo_name", "official_demo"),
            validation_scope=data.get("validation_scope", "official_demo"),
            command=data.get("command"),
        )
    )


@app.post("/api/factory/demo-workflows/advance")
def advance_demo_workflow():
    data = _body()
    return _json_ok(
        service.advance_factory_workflow(
            arm_cn=data["arm_cn"],
            workflow_type="demo_validation",
            action=data["action"],
            notes=data.get("notes"),
            final_status=data.get("final_status", "passed"),
        )
    )


@app.post("/api/factory/demo-workflows/run-official")
def run_official_demo_workflow():
    data = _body()
    return _json_ok(
        service.run_official_demo_validation(
            arm_cn=data["arm_cn"],
            command=data["command"],
            execute=bool(data.get("execute", False)),
            confirmations=data.get("confirmations") or {},
            timeout_s=int(data.get("timeout_s", 300)),
        )
    )


@app.post("/api/openarm/motor-check")
def run_official_motor_check():
    data = _body()
    return _json_ok(
        service.run_official_motor_check(
            canid=int(data["canid"]),
            recvid=int(data["recvid"]),
            socketcan=data.get("socketcan", "can0"),
            fd=bool(data.get("fd", False)),
            execute=bool(data.get("execute", False)),
            confirmations=data.get("confirmations") or {},
            arm_cn=data.get("arm_cn"),
            timeout_s=int(data.get("timeout_s", 30)),
        )
    )


@app.post("/api/openarm/change-baudrate")
def run_official_baudrate_change():
    data = _body()
    return _json_ok(
        service.run_official_baudrate_change(
            canid=int(data["canid"]),
            baudrate=int(data["baudrate"]),
            socketcan=data.get("socketcan", "can0"),
            flash=bool(data.get("flash", False)),
            execute=bool(data.get("execute", False)),
            confirmations=data.get("confirmations") or {},
            arm_cn=data.get("arm_cn"),
            timeout_s=int(data.get("timeout_s", 60)),
        )
    )


@app.get("/api/device/interface-status")
def interface_status():
    return _json_ok(service.interface_status())


@app.get("/api/system/can-interfaces")
def system_can_interfaces():
    return _json_ok(service.system_can_interfaces())


@app.post("/api/system/can-interfaces/configure")
def configure_can_interface():
    data = _body()
    return _json_ok(
        service.configure_can_interface(
            name=data["name"],
            mode=data.get("mode", "can20"),
            bitrate=data["bitrate"],
            dbitrate=data.get("dbitrate"),
            fd_enabled=bool(data.get("fd_enabled", False)),
            tool=data.get("tool", "ip_link"),
        )
    )


@app.post("/api/system/can-interfaces/up")
def system_can_interface_up():
    data = _body()
    return _json_ok(service.can_interface_up(data["name"]))


@app.post("/api/system/can-interfaces/down")
def system_can_interface_down():
    data = _body()
    return _json_ok(service.can_interface_down(data["name"]))


@app.post("/api/device/connect")
def connect_device():
    data = _body()
    return _json_ok(
        service.connect_device(
            transport=data.get("transport", "serial_bridge"),
            connection=data.get("connection", {}),
        )
    )


@app.post("/api/device/disconnect")
def disconnect_device():
    data = _body()
    return _json_ok(service.disconnect_device(data["device_session_id"]))


@app.post("/api/device/scan")
def scan_device():
    data = _body()
    return _json_ok(
        service.scan_device(
            session_id=data["device_session_id"],
            job_type=data["job_type"],
            profile_id=data.get("profile_id"),
            current_id=data.get("current_id"),
            expert_mode=bool(data.get("expert_mode", False)),
            repeat_count=int(data.get("repeat_count", 1)),
            repeat_delay_ms=int(data.get("repeat_delay_ms", 120)),
            allow_motion=bool(data.get("allow_motion", False)),
        )
    )


@app.post("/api/device/line-inventory")
def line_inventory():
    data = _body()
    return _json_ok(
        service.line_inventory(
            session_id=data["device_session_id"],
            profile_id=data.get("profile_id"),
        )
    )


@app.post("/api/device/probe-joint")
def probe_joint():
    data = _body()
    return _json_ok(
        service.probe_joint_params(
            session_id=data["device_session_id"],
            joint_name=data["joint_name"],
            profile_id=data.get("profile_id", "openarm_v1"),
            timeout_per_param=float(data.get("timeout_per_param", 0.4)),
            force_inventory=bool(data.get("force_inventory", False)),
        )
    )


@app.post("/api/device/joint-link-test")
def joint_link_test():
    data = _body()
    return _json_ok(
        service.joint_link_test(
            session_id=data["device_session_id"],
            joint_name=data["joint_name"],
            profile_id=data.get("profile_id", "openarm_v1"),
            force_inventory=bool(data.get("force_inventory", False)),
            allow_enable=bool(data.get("allow_enable", False)),
            job_id=data.get("job_id"),
        )
    )


@app.post("/api/device/joint-micro-response-test")
def joint_micro_response_test():
    data = _body()
    return _json_ok(
        service.joint_micro_response_test(
            session_id=data["device_session_id"],
            joint_name=data["joint_name"],
            profile_id=data.get("profile_id", "openarm_v1"),
            force_inventory=bool(data.get("force_inventory", False)),
            q_offset=float(data.get("q_offset", 0.02)),
            kp=float(data.get("kp", 6.0)),
            kd=float(data.get("kd", 0.12)),
            dwell_ms=int(data.get("dwell_ms", 120)),
            job_id=data.get("job_id"),
        )
    )


@app.post("/api/device/arm-status-check")
def arm_status_check():
    data = _body()
    return _json_ok(
        service.arm_status_check(
            session_id=data["device_session_id"],
            profile_id=data.get("profile_id", "openarm_right_arm_v1"),
            sample_count=int(data.get("sample_count", 1)),
            sample_delay_ms=int(data.get("sample_delay_ms", 80)),
        )
    )


@app.post("/api/device/arm-safe-enable-check")
def arm_safe_enable_check():
    data = _body()
    return _json_ok(
        service.arm_safe_enable_check(
            session_id=data["device_session_id"],
            profile_id=data.get("profile_id", "openarm_right_arm_v1"),
            hold_ms=int(data.get("hold_ms", 300)),
        )
    )


@app.post("/api/device/arm-timeout-standardization")
def arm_timeout_standardization():
    data = _body()
    if data.get("timeout") is not None:
        raise ValueError(
            "整臂 TIMEOUT 标准化不接受统一 timeout；请使用 Profile 的逐关节目标值"
        )
    return _json_ok(
        service.arm_timeout_standardization(
            session_id=data["device_session_id"],
            profile_id=data.get("profile_id", "openarm_right_arm_v1"),
            save_flash=bool(data.get("save_flash", True)),
            confirmed=bool(data.get("confirmed", False)),
        )
    )


@app.post("/api/device/arm-zero-calibration")
def arm_zero_calibration():
    data = _body()
    return _json_ok(
        service.calibrate_arm_zero(
            session_id=data["device_session_id"],
            profile_id=data.get("profile_id", "openarm_right_arm_v1"),
            arm_cn=data.get("arm_cn"),
            operator=data.get("operator"),
            notes=data.get("notes"),
            confirmations=data.get("confirmations") or {},
            save_flash=bool(data.get("save_flash", True)),
            zero_pose_name=data.get("zero_pose_name", "openarm_home"),
        )
    )


@app.post("/api/jobs")
def create_job():
    data = _body()
    return _json_ok(
        service.create_job(
            job_type=data["job_type"],
            session_id=data["device_session_id"],
            profile_id=data.get("profile_id"),
            target_joint=data.get("target_joint"),
            expert_mode=bool(data.get("expert_mode", False)),
        )
    )


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    return _json_ok(service.get_job(job_id))


@app.get("/api/jobs/<job_id>/issues")
def get_job_issues(job_id: str):
    return _json_ok(service.issues(job_id))


@app.post("/api/jobs/<job_id>/apply-profile")
def apply_profile(job_id: str):
    data = _body()
    return _json_ok(
        service.apply_profile(
            job_id=job_id,
            target_joint=data.get("target_joint"),
            profile_id=data["profile_id"],
            overrides=data.get("overrides"),
        )
    )


@app.post("/api/jobs/<job_id>/write-params")
def write_params(job_id: str):
    data = _body()
    return _json_ok(service.write_params(job_id, data["target_config"]))


@app.post("/api/jobs/<job_id>/verify-params")
def verify_params(job_id: str):
    return _json_ok(service.verify_params(job_id))


@app.post("/api/jobs/<job_id>/save-flash")
def save_flash(job_id: str):
    return _json_ok(service.save_flash(job_id))


@app.post("/api/jobs/<job_id>/zero")
def zero(job_id: str):
    data = _body()
    return _json_ok(service.zero(job_id, confirmed=bool(data.get("confirmed"))))


@app.post("/api/jobs/<job_id>/test")
def run_test(job_id: str):
    data = _body()
    return _json_ok(service.test(job_id, confirmed=bool(data.get("confirmed"))))


def _wizard_call(func, *args, **kwargs):
    try:
        return _json_ok(func(*args, **kwargs))
    except (KeyError, ValueError):
        raise
    except Exception as error:  # hardware/driver errors become operator guidance, not a raw 502
        return _json_ok(service._wizard_problem("unknown_error", str(error)))


@app.get("/api/single-motor/wizard/options")
def single_wizard_options():
    return _json_ok(service.single_wizard_options())


@app.get("/api/arm/wizard/options")
def arm_wizard_options():
    return _wizard_call(service.arm_wizard_options, product_version=request.args.get("product_version"))


@app.get("/api/arm/wizard/arms")
def arm_wizard_arms():
    return _wizard_call(service.arm_wizard_arms)


@app.post("/api/arm/wizard/create")
def arm_wizard_create():
    data = _body()
    return _wizard_call(
        service.arm_wizard_create,
        arm_cn=str(data.get("arm_cn") or ""),
        product_version=str(data.get("product_version") or ""),
        arm_type=str(data.get("arm_type") or "OpenARM Follower"),
        notes=data.get("notes"),
    )


@app.delete("/api/arm/wizard/<arm_cn>")
def arm_wizard_delete(arm_cn: str):
    return _wizard_call(
        service.arm_wizard_delete,
        arm_cn=arm_cn,
        mode=str(request.args.get("mode") or "archive"),
    )


@app.get("/api/arm/wizard/<arm_cn>/status")
def arm_wizard_status(arm_cn: str):
    return _wizard_call(service.arm_wizard_status, arm_cn=arm_cn)


@app.get("/api/arm/wizard/<arm_cn>/motor-records")
def arm_wizard_motor_records(arm_cn: str):
    return _wizard_call(service.arm_wizard_available_motor_records, arm_cn=arm_cn)


@app.post("/api/arm/wizard/<arm_cn>/motor-records")
def arm_wizard_attach_motor_record(arm_cn: str):
    data = _body()
    return _wizard_call(
        service.arm_wizard_attach_motor_record,
        arm_cn=arm_cn,
        record_id=str(data.get("record_id") or ""),
    )


@app.post("/api/link/wizard/detect")
def link_wizard_detect():
    return _wizard_call(service.link_wizard_detect)


@app.post("/api/link/wizard/prepare")
def link_wizard_prepare():
    data = _body()
    return _wizard_call(
        service.link_wizard_prepare,
        channel=str(data.get("channel", "can0")),
        mode=str(data.get("mode", "can20")),
        bitrate=int(data.get("bitrate", 1000000)),
        dbitrate=int(data["dbitrate"]) if data.get("dbitrate") else None,
    )


@app.post("/api/link/wizard/connect")
def link_wizard_connect():
    data = _body()
    return _wizard_call(
        service.link_wizard_connect,
        channel=str(data.get("channel", "can0")),
        bitrate=int(data.get("bitrate", 1000000)),
    )


@app.post("/api/link/wizard/bus-check")
def link_wizard_bus_check():
    data = _body()
    return _wizard_call(
        service.link_wizard_bus_check,
        channel=str(data.get("channel", "can0")),
        bitrate=int(data.get("bitrate", 1000000)),
    )


@app.post("/api/link/wizard/disconnect")
def link_wizard_disconnect():
    data = _body()
    return _wizard_call(service.link_wizard_disconnect, channel=str(data.get("channel", "can0")))


@app.post("/api/single-motor/inspect")
def single_motor_inspect():
    data = _body()
    return _wizard_call(
        service.single_motor_inspect,
        channel=str(data.get("channel", "can0")),
        bitrate=int(data.get("bitrate", 1000000)),
    )


@app.post("/api/single-motor/wizard/identify")
def single_wizard_identify():
    data = _body()
    return _wizard_call(
        service.single_wizard_identify,
        channel=str(data.get("channel", "can0")),
        bitrate=int(data.get("bitrate", 1000000)),
        arm_side=str(data.get("arm_side", "right_arm")),
        joint=str(data.get("joint", "J1")),
        product_line=str(data.get("product_line", "openarm_2_0")),
    )


@app.post("/api/single-motor/wizard/<job_id>/write")
def single_wizard_write(job_id: str):
    return _wizard_call(service.single_wizard_write, job_id)


@app.post("/api/single-motor/wizard/<job_id>/save")
def single_wizard_save(job_id: str):
    return _wizard_call(service.single_wizard_save, job_id)


@app.post("/api/single-motor/wizard/<job_id>/finish")
def single_wizard_finish(job_id: str):
    return _wizard_call(service.single_wizard_finish, job_id)


@app.get("/api/single-motor/records")
def single_motor_records():
    return _json_ok(service.list_single_motor_records(limit=int(request.args.get("limit", 50))))


@app.post("/api/jobs/<job_id>/run-comm-check")
def run_comm_check(job_id: str):
    data = _body()
    return _json_ok(service.run_comm_check(job_id, confirmed=bool(data.get("confirmed", True))))


@app.post("/api/jobs/<job_id>/run-arm-scan")
def run_arm_scan(job_id: str):
    data = _body()
    return _json_ok(
        service.run_arm_scan(
            job_id,
            confirmed=bool(data.get("confirmed", True)),
            repeat_count=int(data.get("repeat_count", 1)),
            repeat_delay_ms=int(data.get("repeat_delay_ms", 120)),
            allow_motion=bool(data.get("allow_motion", False)),
        )
    )


@app.post("/api/jobs/<job_id>/run-arm-acceptance")
def run_arm_acceptance(job_id: str):
    data = _body()
    return _json_ok(
        service.run_arm_acceptance(
            job_id,
            confirmed=bool(data.get("confirmed", True)),
            repeat_count=int(data.get("repeat_count", 1)),
            repeat_delay_ms=int(data.get("repeat_delay_ms", 120)),
            allow_motion=bool(data.get("allow_motion", False)),
        )
    )


@app.post("/api/jobs/<job_id>/cancel")
def cancel(job_id: str):
    return _json_ok(service.cancel(job_id))


@app.get("/api/jobs/<job_id>/report")
def report(job_id: str):
    return _json_ok(service.report(job_id))


@socketio.on("connect")
def handle_connect():
    global _interface_status_task
    socketio.emit("job_state", {"job_id": None, "status": "connected", "step": "socket", "message": "WebSocket connected", "progress": 0})
    with _interface_status_task_lock:
        if _interface_status_task is None:
            _interface_status_task = socketio.start_background_task(_publish_interface_status)


def _publish_interface_status():
    while True:
        try:
            socketio.emit("interface_status", service.interface_status())
        except Exception:
            pass
        socketio.sleep(1)


if __name__ == "__main__":
    print("OpenARM Damiao 电机初始化工作站启动中...")
    print("访问地址: http://localhost:5000")
    debug_enabled = os.getenv("OPENARM_WORKSTATION_DEBUG", "0").lower() in {"1", "true", "yes"}
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=debug_enabled,
        use_reloader=debug_enabled,
        allow_unsafe_werkzeug=True,
    )
