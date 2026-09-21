"""Change detector for the formal report of the three arms tested on hardware.

NOT a specification. These outputs are what the workstation produced in 2026-05..09,
under the procedure and the official version (openarm_can 1.2.2) of that time. When a
deliberate change to the procedure moves them, move the baseline - official and the
motors themselves decide what is correct, not this file. See tests/golden/README.md
for the authority order.

The full text is stored rather than a hash so a failure shows *what* moved, which is
the only way reviewing the diff is realistic.
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
    diff = "\n".join(
        list(difflib.unified_diff(expected.splitlines(), actual.splitlines(), "baseline", "current", lineterm="", n=1))[:40]
    )
    pytest.fail(
        f"{label} moved. This is a report of change, not a verdict on correctness.\n"
        "If the change is intended, refresh the baseline and record why:\n"
        "  .venv/bin/python tests/golden/build_report_baseline.py\n"
        "  git diff tests/golden/fixture/reports/\n"
        f"\n{diff}"
    )


@pytest.mark.parametrize("arm_cn", ARM_CNS)
def test_the_formal_report_of_a_real_arm_has_not_moved_unnoticed(arm_cn, monkeypatch):
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


def test_the_signature_dates_follow_the_report_date(monkeypatch, tmp_path):
    """A regenerated report must not claim it was signed today.

    The signature rows record when the test was executed and released. They used to
    read `datetime.now()`, so regenerating an August report in September dated its
    signatures September - and the golden baseline broke every time the day rolled
    over, which is how this was found.
    """
    monkeypatch.setattr(workstation, "FACTORY_ARMS_DIR", materialise_fixture(tmp_path))
    monkeypatch.setattr(workstation, "FORMAL_REPORTS_DIR", tmp_path / "out")
    service = workstation.WorkstationService()
    result = service.generate_formal_factory_acceptance_report(
        "OAF26080401", operator="op", project_lead="lead", report_date="20260811"
    )
    html = next(Path(result["report_dir"]).glob("*.html")).read_text(encoding="utf-8")

    assert "<td>2026-08-11</td><td>Factory test executed and recorded.</td>" in html
    assert "<td>2026-08-11</td><td>Released for factory archive.</td>" in html
    assert "<td>2026-08-11</td>" in html.split("Whole-Arm Serial")[1][:200]

    # The two dates mean different things and must stay separate: Generated UTC is when
    # the file was rendered, and it is correct for that to be today.
    import datetime as _dt

    generated = html.split("<td>Generated UTC</td><td>")[1][:10]
    assert generated == _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def test_the_report_states_the_method_it_was_produced_with(monkeypatch, tmp_path):
    """A report that cannot say how it was made cannot be reconciled with a later one.

    Before this, a customer holding an August report and a later one could not tell
    whether a difference was the arm or the procedure: the report named no workstation
    version, no official tool version, no gripper control mode and no criteria.
    """
    monkeypatch.setattr(workstation, "FACTORY_ARMS_DIR", materialise_fixture(tmp_path))
    monkeypatch.setattr(workstation, "FORMAL_REPORTS_DIR", tmp_path / "out")
    service = workstation.WorkstationService()
    html = next(
        Path(
            service.generate_formal_factory_acceptance_report(
                "OAF26080401", operator="op", project_lead="lead", report_date=PINNED_DATE
            )["report_dir"]
        ).glob("*.html")
    ).read_text(encoding="utf-8")

    assert "Test Method And Basis" in html
    assert workstation.WORKSTATION_VERSION in html
    assert workstation.OFFICIAL_TOOL_VERSION in html
    # A 1.0 arm is still driven in MIT, and the report says so rather than leaving a
    # reader to assume the current official method was used.
    assert "MIT (kp=5.0, kd=0.6, 无力矩上限)" in html
    assert "-1.0472" in html and "0.8 rad" in html
    assert "limit_search" in html


def test_a_2_0_report_states_the_official_gripper_method(monkeypatch, tmp_path):
    import json
    import shutil

    arms_dir = materialise_fixture(tmp_path)
    record = json.loads((arms_dir / "OAF26080401.json").read_text(encoding="utf-8"))
    record["arm_cn"] = "OAF26092120"
    record["product_version"] = "openarm_2_0"
    (arms_dir / "OAF26092120.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(workstation, "FACTORY_ARMS_DIR", arms_dir)
    monkeypatch.setattr(workstation, "FORMAL_REPORTS_DIR", tmp_path / "out")
    service = workstation.WorkstationService()
    result = service.generate_formal_factory_acceptance_report(
        "OAF26092120", operator="op", project_lead="lead", report_date=PINNED_DATE
    )
    html = next(Path(result["report_dir"]).glob("*.html")).read_text(encoding="utf-8")
    shutil.rmtree(result["report_dir"], ignore_errors=True)

    assert "POS_FORCE (速度上限 25.0 rad/s, 力矩上限 0.15 pu)" in html
    assert "CAN FD / 1 Mbps arb + 5 Mbps data" in html
    assert "cell_jig_set_zero（不运动）" in html
    # No invented threshold: the report says the number is undecided rather than
    # printing one nobody agreed to.
    assert "行程阈值未定" in html


def test_the_method_block_does_not_renumber_the_sections():
    # Customers may already cite "section 4". The method table sits with Document
    # Control rather than taking a number of its own.
    html = (REPORTS_DIR / "OAF26080401.html").read_text(encoding="utf-8")
    assert "<h2>1. Scope And Traceability</h2>" in html
    assert "<h2>2. Acceptance Matrix</h2>" in html
