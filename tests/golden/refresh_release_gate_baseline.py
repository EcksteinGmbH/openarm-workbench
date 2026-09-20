#!/usr/bin/env python
"""Regenerate tests/golden/release_gate_real_arms.json from the real arm records.

Run this ONLY when a real arm record legitimately changed (a new arm was built, or
a gate rule changed by decision). Review the diff before committing: a baseline that
moves without a decision behind it means the 1.0 path changed by accident.

    .venv/bin/python tests/golden/refresh_release_gate_baseline.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import src.workstation as workstation  # noqa: E402
from tests.test_golden_real_arms import _gate_view  # noqa: E402


def main() -> int:
    service = workstation.WorkstationService()
    arms = sorted(path.stem for path in workstation.FACTORY_ARMS_DIR.glob("*.json"))
    baseline = {arm_cn: _gate_view(service.factory_release_gate(arm_cn)) for arm_cn in arms}
    out = Path(__file__).parent / "release_gate_real_arms.json"
    out.write_text(json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out} for {len(arms)} arms: {', '.join(arms)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
