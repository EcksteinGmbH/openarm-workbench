"""Guard: no test may write into the repo's real production directories.

A fake PASS task in the real `artifacts/jobs` is indistinguishable from one
produced on hardware, and `factory_release_gate()` picks its evidence from exactly
that directory. Since real-hardware runs are the only source of truth this project
has, polluting them costs more than any test is worth.
"""
from __future__ import annotations

from pathlib import Path

import src.workstation as workstation
from tests.conftest import WORKSTATION_OUTPUT_DIRS
from tests.test_workstation import shared_socketcan_factory


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_every_workstation_output_dir_is_redirected_away_from_the_repo():
    for name in WORKSTATION_OUTPUT_DIRS:
        target = Path(getattr(workstation, name))
        assert not target.is_relative_to(REPO_ROOT), f"{name} still points inside the repo: {target}"


def test_the_guard_covers_every_output_path_the_module_declares():
    # A new FACTORY_*/VENDOR_*/ARTIFACTS_* constant must be added to the conftest
    # redirect, or it silently starts writing to the repo again.
    declared = {
        name
        for name in dir(workstation)
        if name.endswith("_DIR") and name.startswith(("ARTIFACTS", "FACTORY", "VENDOR"))
    }
    assert declared <= set(WORKSTATION_OUTPUT_DIRS), f"not redirected: {sorted(declared - set(WORKSTATION_OUTPUT_DIRS))}"


def test_building_a_service_does_not_touch_the_real_artifacts_dir(monkeypatch):
    monkeypatch.setattr(workstation, "DamiaoSocketCANDriver", shared_socketcan_factory())
    real_jobs = REPO_ROOT / "artifacts" / "jobs"
    before = sorted(item.name for item in real_jobs.iterdir()) if real_jobs.exists() else []

    service = workstation.WorkstationService()
    session = service.connect_device("socketcan", {"channel": "can0", "bitrate": 1000000})
    service.create_job("arm_verification", session["device_session_id"], "openarm_v1")

    after = sorted(item.name for item in real_jobs.iterdir()) if real_jobs.exists() else []
    assert after == before
