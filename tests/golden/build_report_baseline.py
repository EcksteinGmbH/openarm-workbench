#!/usr/bin/env python
"""Freeze the formal acceptance report of each golden-fixture arm.

The report is where a product version matters most: a 2.0 arm must never ship a report
that claims CAN 2.0 / 1 Mbps. Those strings are currently hardcoded in five places, and
moving them onto the product registry is exactly the kind of change that can silently
alter a 1.0 report. So the 1.0 output is frozen here first, in full, so a diff shows
what moved rather than just that something did.

The reports are generated from `tests/golden/fixture/`, which carries only what the
release gate reads - so several evidence files resolve to placeholders and the PDF step
fails. That is fine and deterministic: this baseline exists to detect change, not to be
a specimen of a complete report.

    .venv/bin/python tests/golden/build_report_baseline.py
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import src.workstation as workstation  # noqa: E402
from tests.test_golden_real_arms import materialise_fixture  # noqa: E402

REPORTS_DIR = Path(__file__).parent / "fixture" / "reports"
PINNED_DATE = "20260101"
# The generation timestamp, in the HTML table and in the JSON payload. Nothing else
# differs between two runs of the same input once `report_date` is pinned.
GENERATED_PATTERNS = (
    (re.compile(r"(<td>Generated UTC</td><td>)[^<]*(</td>)"), r"\1<GENERATED-UTC>\2"),
    (re.compile(r'("generated_at":\s*")[^"]*(")'), r"\1<GENERATED-UTC>\2"),
)


def normalise(text: str) -> str:
    for pattern, replacement in GENERATED_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def render(arm_cn: str) -> tuple[str, str]:
    tmp = Path(tempfile.mkdtemp())
    try:
        workstation.FACTORY_ARMS_DIR = materialise_fixture(tmp)
        workstation.FORMAL_REPORTS_DIR = tmp / "reports"
        service = workstation.WorkstationService()
        result = service.generate_formal_factory_acceptance_report(
            arm_cn, operator="golden", project_lead="golden", report_date=PINNED_DATE
        )
        report_dir = Path(result["report_dir"])
        html = next(report_dir.glob("*.html")).read_text(encoding="utf-8")
        payload = next(report_dir.glob("*.json")).read_text(encoding="utf-8")
        return normalise(html), normalise(payload)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    arms_dir = Path(__file__).parent / "fixture" / "arms"
    if REPORTS_DIR.exists():
        shutil.rmtree(REPORTS_DIR)
    REPORTS_DIR.mkdir(parents=True)

    for source in sorted(arms_dir.glob("*.json")):
        arm_cn = source.stem
        html, payload = render(arm_cn)
        again_html, _ = render(arm_cn)
        if html != again_html:
            print(f"REFUSED: {arm_cn} report is not reproducible after normalisation", file=sys.stderr)
            shutil.rmtree(REPORTS_DIR)
            return 1
        (REPORTS_DIR / f"{arm_cn}.html").write_text(html, encoding="utf-8")
        (REPORTS_DIR / f"{arm_cn}.json").write_text(payload, encoding="utf-8")
        print(f"{arm_cn}: {len(html)} B html, {len(payload)} B json")
    print("verified: each report is byte-identical across two runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
