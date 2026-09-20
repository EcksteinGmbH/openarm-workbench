#!/usr/bin/env python
"""Build the committed golden fixture from this machine's real production records.

`artifacts/` is gitignored, so the three real 1.0 arms exist only where they were
built. Without them in the repo the golden regression silently skips on any other
machine - which is the same as having no protection at all.

What goes in is the minimum the release gate actually reads:
  - the three arm records, with command stdout/stderr dumps replaced by a marker
    (the gate never reads them, and they are 80% of the bytes)
  - `job.json` and `issues.json` from each linked job directory, and nothing else
    (`events.jsonl`, `report.html`, `motors/` are not read by the gate)

Absolute `artifact_dir` paths are rewritten to a `{JOBS}` placeholder so the fixture
works from any checkout; the test substitutes the real path when it materialises it.

The reduction is only valid if it changes nothing, so this script refuses to write a
fixture whose gate verdict differs from the real records'.

    .venv/bin/python tests/golden/build_fixture.py
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import src.workstation as workstation  # noqa: E402

FIXTURE_DIR = Path(__file__).parent / "fixture"
REAL_ARMS_DIR = REPO_ROOT / "artifacts" / "factory" / "arms"
GATE_FILES = ("job.json", "issues.json")
STRIPPED = "<stripped: command output, not read by the release gate>"


def strip_logs(node):
    """Drop captured command output wherever it appears, keeping the structure."""
    if isinstance(node, dict):
        return {
            key: (STRIPPED if key in ("stdout", "stderr") and isinstance(value, str) and value else strip_logs(value))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [strip_logs(item) for item in node]
    return node


def build():
    if FIXTURE_DIR.exists():
        shutil.rmtree(FIXTURE_DIR)
    (FIXTURE_DIR / "arms").mkdir(parents=True)
    (FIXTURE_DIR / "jobs").mkdir(parents=True)

    job_dirs = set()
    for source in sorted(REAL_ARMS_DIR.glob("*.json")):
        record = strip_logs(json.loads(source.read_text(encoding="utf-8")))
        for linked_job in record.get("linked_jobs", []):
            artifact_dir = linked_job.get("artifact_dir")
            if not artifact_dir:
                continue
            name = Path(artifact_dir).name
            job_dirs.add(name)
            linked_job["artifact_dir"] = f"{{JOBS}}/{name}"
        (FIXTURE_DIR / "arms" / source.name).write_text(
            json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )

    for name in sorted(job_dirs):
        source_dir = REPO_ROOT / "artifacts" / "jobs" / name
        target_dir = FIXTURE_DIR / "jobs" / name
        target_dir.mkdir(parents=True)
        for filename in GATE_FILES:
            source_file = source_dir / filename
            if source_file.exists():
                payload = strip_logs(json.loads(source_file.read_text(encoding="utf-8")))
                (target_dir / filename).write_text(
                    json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
                )
    return sorted(job_dirs)


def gate_views(arms_dir: Path, jobs_dir: Path | None = None) -> dict:
    from tests.test_golden_real_arms import _gate_view

    if jobs_dir is not None:
        staged = jobs_dir.parent / "staged_arms"
        staged.mkdir(parents=True, exist_ok=True)
        for path in arms_dir.glob("*.json"):
            (staged / path.name).write_text(
                path.read_text(encoding="utf-8").replace("{JOBS}", str(jobs_dir)), encoding="utf-8"
            )
        arms_dir = staged

    workstation.FACTORY_ARMS_DIR = arms_dir
    service = workstation.WorkstationService()
    return {path.stem: _gate_view(service.factory_release_gate(path.stem)) for path in sorted(arms_dir.glob("*.json"))}


def main() -> int:
    real = gate_views(REAL_ARMS_DIR)
    job_dirs = build()
    reduced = gate_views(FIXTURE_DIR / "arms", FIXTURE_DIR / "jobs")

    if real != reduced:
        shutil.rmtree(FIXTURE_DIR)
        print("REFUSED: the reduced fixture does not reproduce the real gate verdict", file=sys.stderr)
        for arm_cn in sorted(set(real) | set(reduced)):
            if real.get(arm_cn) != reduced.get(arm_cn):
                print(f"  {arm_cn}:\n    real   {real.get(arm_cn)}\n    fixture {reduced.get(arm_cn)}", file=sys.stderr)
        return 1

    shutil.rmtree(FIXTURE_DIR / "jobs" / "staged_arms", ignore_errors=True)
    shutil.rmtree(FIXTURE_DIR.parent / "fixture" / "staged_arms", ignore_errors=True)
    size = sum(path.stat().st_size for path in FIXTURE_DIR.rglob("*") if path.is_file())
    print(f"fixture: {len(list((FIXTURE_DIR / 'arms').glob('*.json')))} arms, {len(job_dirs)} job dirs, {size / 1024:.0f} KB")
    print("verified: the reduced fixture reproduces the real gate verdict exactly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
