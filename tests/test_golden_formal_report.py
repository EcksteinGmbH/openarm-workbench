"""Golden regression on the formal acceptance report of the three real 1.0 arms.

The report is where the product version matters most: a 2.0 arm must never ship a
report claiming CAN 2.0 / 1 Mbps. Moving those hardcoded strings onto the product
registry is exactly the change that can silently alter a 1.0 report, so the 1.0 output
is frozen in full - a failure shows a diff of what moved, not just that something did.

Refresh deliberately with `tests/golden/build_report_baseline.py` and review the diff.
"""
from __future__ import annotations

import difflib
from pathlib import Path
import shutil
import tempfile

import pytest

import src.workstation as workstation
from tests.golden.build_report_baseline import PINNED_DATE, normalise
from tests.test_golden_real_arms import materialise_fixture


REPORTS_DIR = Path(__file__).parent / "golden" / "fixture" / "reports"
ARM_CNS = sorted(path.stem for path in REPORTS_DIR.glob("*.html"))


def _render(arm_cn: str) -> tuple[str, str]:
    tmp = Path(tempfile.mkdtemp())
    try:
        workstation.FACTORY_ARMS_DIR = materialise_fixture(tmp)
        workstation.FORMAL_REPORTS_DIR = tmp / "reports"
        service = workstation.WorkstationService()
        result = service.generate_formal_factory_acceptance_report(
            arm_cn, operator="golden", project_lead="golden", report_date=PINNED_DATE
        )
        report_dir = Path(result["report_dir"])
        return (
            normalise(next(report_dir.glob("*.html")).read_text(encoding="utf-8")),
            normalise(next(report_dir.glob("*.json")).read_text(encoding="utf-8")),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _assert_same(actual: str, expected: str, label: str):
    if actual == expected:
        return
    diff = "\n".join(list(difflib.unified_diff(expected.splitlines(), actual.splitlines(), "baseline", "current", lineterm="", n=1))[:40])
    pytest.fail(f"{label} changed:\n{diff}")


@pytest.mark.parametrize("arm_cn", ARM_CNS)
def test_the_formal_report_of_a_real_arm_is_unchanged(arm_cn, monkeypatch):
    monkeypatch.setattr(workstation, "FACTORY_ARMS_DIR", workstation.FACTORY_ARMS_DIR)
    html, payload = _render(arm_cn)
    _assert_same(html, (REPORTS_DIR / f"{arm_cn}.html").read_text(encoding="utf-8"), f"{arm_cn} report HTML")
    _assert_same(payload, (REPORTS_DIR / f"{arm_cn}.json").read_text(encoding="utf-8"), f"{arm_cn} report JSON")


def test_every_fixture_arm_has_a_frozen_report():
    in_fixture = {path.stem for path in (Path(__file__).parent / "golden" / "fixture" / "arms").glob("*.json")}
    assert set(ARM_CNS) == in_fixture, f"no frozen report for: {sorted(in_fixture - set(ARM_CNS))}"


def test_the_1_0_reports_state_the_can_mode_they_were_tested_with():
    # Pinned on purpose: these are the strings the registry migration has to take over,
    # and for a 1.0 arm they must keep saying exactly this afterwards.
    html = (REPORTS_DIR / "OAF26080401.html").read_text(encoding="utf-8")
    assert "CAN 2.0 / 1 Mbps" in html
    assert "classic CAN 2.0 at 1 Mbps with CAN-FD disabled" in html


def test_a_2_0_arm_report_states_can_fd_not_can_2_0(monkeypatch, tmp_path):
    """The whole point of the migration: the report follows the product, not a constant.

    A 2.0 arm runs CAN FD 1M/5M. Shipping it a report that says "classic CAN 2.0 at
    1 Mbps with CAN-FD disabled" would be a false statement about how it was tested.
    """
    import json
    import shutil

    arms_dir = materialise_fixture(tmp_path)
    # Same evidence, relabelled as a 2.0 arm, so only the product version differs.
    source = arms_dir / "OAF26080401.json"
    record = json.loads(source.read_text(encoding="utf-8"))
    record["arm_cn"] = "OAF26092020"
    record["product_version"] = "openarm_2_0"
    (arms_dir / "OAF26092020.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(workstation, "FACTORY_ARMS_DIR", arms_dir)
    monkeypatch.setattr(workstation, "FORMAL_REPORTS_DIR", tmp_path / "out")
    service = workstation.WorkstationService()
    result = service.generate_formal_factory_acceptance_report(
        "OAF26092020", operator="golden", project_lead="golden", report_date=PINNED_DATE
    )
    html = next(Path(result["report_dir"]).glob("*.html")).read_text(encoding="utf-8")
    shutil.rmtree(result["report_dir"], ignore_errors=True)

    assert "CAN FD / 1 Mbps arbitration / 5 Mbps data" in html
    assert "All dynamic commands used CAN FD at 1 Mbps arbitration / 5 Mbps data" in html
    assert "CAN 2.0" not in html
    assert "CAN-FD disabled" not in html
