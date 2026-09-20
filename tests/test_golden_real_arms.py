"""Golden regression against the three 1.0 arms that were actually built and tested.

Real hardware runs are the only ground truth this project has, and right now they
cannot be repeated - there is no adapter or arm attached. What survives from those
runs is their recorded evidence, so it is frozen here: any change that alters the
release verdict or the linked evidence of a real arm fails this test. This is the
strongest check available while hardware is out of reach, and it guards the 1.0 path
specifically, which must not move while 2.0 is being added.

The evidence is committed under `tests/golden/fixture/` because `artifacts/` is
gitignored - a baseline that only exists on one machine is not protection. The fixture
is the minimum the gate reads, with command output stripped, and
`tests/golden/build_fixture.py` refuses to produce one whose verdict differs from the
real records'. `test_the_fixture_still_matches_the_real_records` re-checks that on any
machine that still has them.

Refreshing the baseline is a deliberate act: re-run
`tests/golden/refresh_release_gate_baseline.py` and review the diff. A baseline that
changes without a decision behind it means 1.0 behaviour changed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.workstation as workstation


REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = Path(__file__).parent / "golden"
FIXTURE_DIR = GOLDEN_DIR / "fixture"
REAL_ARMS_DIR = REPO_ROOT / "artifacts" / "factory" / "arms"
BASELINE = json.loads((GOLDEN_DIR / "release_gate_real_arms.json").read_text(encoding="utf-8"))


def _gate_view(gate: dict) -> dict:
    return {
        "release_decision": gate["release_decision"],
        "release_ready": gate["release_ready"],
        "blocking_items": gate["blocking_items"],
        "warning_items": gate["warning_items"],
        "linked_jobs": [
            {k: v for k, v in item.items() if k in ("job_id", "job_type", "status", "has_blocking_issues", "profile_id")}
            for item in gate["evidence"]["linked_jobs"]
        ],
        "zero_records": gate["evidence"]["zero_records"],
        "demo_records": gate["evidence"]["demo_records"],
        "evidence_records": gate["evidence"]["evidence_records"],
        "raw_status_frame_evidence": gate["evidence"]["raw_status_frame_evidence"],
    }


def _captured_output(node, path: str = "") -> list[str]:
    """Every stdout/stderr value still carrying real command output.

    Checks the values, not the word: the workflow step instructions legitimately say
    "记录 stdout/stderr", and that text is content, not a log dump.
    """
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if key in ("stdout", "stderr") and isinstance(value, str) and value and not value.startswith("<stripped:"):
                found.append(here)
            else:
                found.extend(_captured_output(value, here))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(_captured_output(item, f"{path}[{index}]"))
    return found


def materialise_fixture(tmp_path: Path) -> Path:
    """Lay the committed fixture out on disk with real absolute paths.

    Arm records reference their job directories by absolute path, so the fixture
    stores a `{JOBS}` placeholder and it is substituted here. Returns the arms dir.
    """
    jobs_dir = tmp_path / "golden_jobs"
    arms_dir = tmp_path / "golden_arms"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    arms_dir.mkdir(parents=True, exist_ok=True)

    for source in (FIXTURE_DIR / "jobs").iterdir():
        target = jobs_dir / source.name
        target.mkdir(exist_ok=True)
        for path in source.iterdir():
            (target / path.name).write_bytes(path.read_bytes())

    for source in (FIXTURE_DIR / "arms").glob("*.json"):
        (arms_dir / source.name).write_text(
            source.read_text(encoding="utf-8").replace("{JOBS}", str(jobs_dir)), encoding="utf-8"
        )
    return arms_dir


@pytest.fixture()
def golden_service(monkeypatch, tmp_path):
    """A service reading the committed fixture. The release gate is read-only."""
    monkeypatch.setattr(workstation, "FACTORY_ARMS_DIR", materialise_fixture(tmp_path))
    return workstation.WorkstationService()


@pytest.mark.parametrize("arm_cn", sorted(BASELINE))
def test_release_gate_verdict_for_a_real_arm_is_unchanged(golden_service, arm_cn):
    assert _gate_view(golden_service.factory_release_gate(arm_cn)) == BASELINE[arm_cn]


def test_every_arm_in_the_fixture_is_covered_by_the_baseline():
    # A new arm added to the fixture must be added to the baseline, or it goes unguarded.
    in_fixture = {path.stem for path in (FIXTURE_DIR / "arms").glob("*.json")}
    assert in_fixture == set(BASELINE), f"not in baseline: {sorted(in_fixture - set(BASELINE))}"


def test_the_fixture_holds_only_what_the_gate_reads():
    # `events.jsonl`, `report.html`, `motors/` and the command output dumps are not read
    # by the gate; keeping them would put megabytes of production logs in the repo.
    for job_dir in (FIXTURE_DIR / "jobs").iterdir():
        names = {path.name for path in job_dir.iterdir()}
        assert names <= {"job.json", "issues.json"}, f"{job_dir.name} carries {sorted(names - {'job.json', 'issues.json'})}"
    for arm in (FIXTURE_DIR / "arms").glob("*.json"):
        assert _captured_output(json.loads(arm.read_text(encoding="utf-8"))) == [], arm.name


def test_the_gate_writes_nothing(golden_service, tmp_path):
    arm_cn = sorted(BASELINE)[0]
    path = workstation.FACTORY_ARMS_DIR / f"{arm_cn}.json"
    before = path.read_bytes()
    golden_service.factory_release_gate(arm_cn)
    assert path.read_bytes() == before


@pytest.mark.skipif(not REAL_ARMS_DIR.exists(), reason="real production records are not on this machine")
def test_the_fixture_still_matches_the_real_records(monkeypatch):
    """The committed fixture is a reduction of the real records - it must stay faithful.

    Where the real records exist, the reduced copy has to produce the same verdict. If
    it stops doing so, the fixture is stale and `build_fixture.py` needs re-running.
    """
    monkeypatch.setattr(workstation, "FACTORY_ARMS_DIR", REAL_ARMS_DIR)
    service = workstation.WorkstationService()
    real = {path.stem: _gate_view(service.factory_release_gate(path.stem)) for path in sorted(REAL_ARMS_DIR.glob("*.json"))}
    assert real == BASELINE
