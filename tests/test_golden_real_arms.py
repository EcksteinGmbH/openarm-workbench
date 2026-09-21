"""Change detector for the release verdict of the three arms tested on hardware.

NOT a specification, and not a constraint on how testing should work. These verdicts
are what the workstation decided in 2026-05..09 under the procedure of that time. If
following official more closely moves them, move the baseline - see
tests/golden/README.md for the authority order and when to replace this set entirely.

The evidence is committed under tests/golden/fixture/ because artifacts/ is gitignored
and a detector that only exists on one machine detects nothing.
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
def test_release_gate_verdict_for_a_real_arm_has_not_moved_unnoticed(golden_service, arm_cn):
    actual = _gate_view(golden_service.factory_release_gate(arm_cn))
    assert actual == BASELINE[arm_cn], (
        f"{arm_cn}'s release verdict moved. This reports change, it does not judge it.\n"
        "If the change is intended, refresh and record why:\n"
        "  .venv/bin/python tests/golden/refresh_release_gate_baseline.py"
    )


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

    Only the arms in the baseline are checked. Arms built after it was taken are normal
    production work and are none of this test's business; comparing the whole directory
    would turn every new arm into a failure.
    """
    monkeypatch.setattr(workstation, "FACTORY_ARMS_DIR", REAL_ARMS_DIR)
    service = workstation.WorkstationService()
    for arm_cn, expected in BASELINE.items():
        if not (REAL_ARMS_DIR / f"{arm_cn}.json").exists():
            pytest.skip(f"{arm_cn} is no longer on this machine")
        assert _gate_view(service.factory_release_gate(arm_cn)) == expected, arm_cn


def test_the_baseline_says_what_it_is_and_what_it_is_not():
    """A frozen output is one rename away from being mistaken for a specification.

    These three arms were tested under the procedure and the official version of
    2026-05..09. They are a change detector. Official and the motors decide what is
    correct. Someone reaching for this directory has to meet that in writing.
    """
    readme = (GOLDEN_DIR / "README.md").read_text(encoding="utf-8")
    assert "不是标准答案" in readme
    # The authority order, in order.
    assert readme.index("官方") < readme.index("真机实测") < readme.index("本目录")
    # Refreshing has to read as normal, not as defeat.
    assert "基准让路，不是流程让路" in readme
    assert "refresh_release_gate_baseline.py" in readme
    assert "build_report_baseline.py" in readme
    # And it has to say when this set stops being the right reference at all.
    assert "什么时候该换掉" in readme


def test_a_failure_tells_the_reader_it_is_reporting_change_not_judging_it():
    from pathlib import Path as _Path

    for name in ("test_golden_real_arms.py", "test_golden_formal_report.py"):
        source = (_Path(__file__).parent / name).read_text(encoding="utf-8")
        assert "NOT a specification" in source, name
        # The refresh command belongs in the failure, not in a doc nobody opens.
        assert "tests/golden/" in source and "refresh" in source.lower(), name
