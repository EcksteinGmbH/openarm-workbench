from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Every workstation output path, in one place. `FACTORY_DIR` also backs
# `_single_motor_records_dir()`, which builds its path from it at call time.
# Nested under a reserved name so a test inspecting its own tmp_path root never
# trips over the redirected output.
ISOLATION_ROOT = "_workstation_artifacts"

WORKSTATION_OUTPUT_DIRS = {
    "ARTIFACTS_DIR": ("artifacts", "jobs"),
    "FACTORY_DIR": ("artifacts", "factory"),
    "FACTORY_MOTORS_DIR": ("artifacts", "factory", "motors"),
    "FACTORY_ARMS_DIR": ("artifacts", "factory", "arms"),
    "FACTORY_BUNDLES_DIR": ("artifacts", "factory", "bundles"),
    "FACTORY_ARM_RECORDS_DIR": ("artifacts", "factory", "arm_records"),
    "FACTORY_REPORTS_DIR": ("artifacts", "factory", "reports"),
    "FACTORY_EVIDENCE_DIR": ("artifacts", "factory", "evidence"),
    "FORMAL_REPORTS_DIR": ("artifacts", "reports"),
    "VENDOR_MAINTENANCE_DIR": ("artifacts", "factory", "vendor_maintenance"),
    "VENDOR_MAINTENANCE_RECORDS_DIR": ("artifacts", "factory", "vendor_maintenance", "records"),
    "VENDOR_MAINTENANCE_LOGS_DIR": ("artifacts", "factory", "vendor_maintenance", "logs"),
}


@pytest.fixture(autouse=True)
def isolate_workstation_artifacts(monkeypatch, tmp_path):
    """Point every workstation output path at this test's tmp_path.

    Without this, constructing a WorkstationService writes jobs into the repo's real
    `artifacts/jobs`, where a test's fake PASS task is indistinguishable from a real
    one produced on hardware - and the release gate picks its evidence from exactly
    that directory. Individual test modules redirect these too; this is the backstop
    that also covers tests which forget, including ones not written yet.
    """
    import src.workstation as workstation

    for name, parts in WORKSTATION_OUTPUT_DIRS.items():
        monkeypatch.setattr(workstation, name, tmp_path.joinpath(ISOLATION_ROOT, *parts))
    return tmp_path.joinpath(ISOLATION_ROOT)
