"""rules.json is the single source of truth for conventions (CLAUDE.md).

These tests exist because Stage 2 shipped a silent data-loss bug caused by a gap
in section_order, and because a heading was hardcoded in Python rather than read
from rules.json.
"""

from __future__ import annotations


import pytest

from app import rules
from app.rules import load_rules


def test_rules_json_parses() -> None:
    assert isinstance(load_rules(), dict)


def test_every_level_order_lists_achievements() -> None:
    """Regression: `experienced` omitted achievements_awards, so renderers
    iterating section_order dropped that section with no error."""
    for level in ("student", "experienced"):
        order = rules.section_order(level)
        assert "achievements_awards" in order, f"{level} order omits achievements"


def test_fallback_append_exists_and_covers_the_gap() -> None:
    """Belt and braces: even an unlisted populated section must be appended."""
    fallback = rules.fallback_append()
    assert "achievements_awards" in fallback
    for level in ("student", "experienced"):
        order = rules.section_order(level)
        for key in ("publications",):
            if key not in order:
                assert key in fallback, f"{key} would be dropped for {level}"


def test_order_starts_with_contact_and_summary() -> None:
    for level in ("student", "experienced"):
        order = rules.section_order(level)
        assert order[0] == "contact"
        assert "summary" in order


def test_student_leads_with_education_experienced_with_work() -> None:
    assert rules.section_order("student").index("education") < rules.section_order("student").index("skills")
    assert rules.section_order("experienced").index("work_experience") < rules.section_order("experienced").index("education")


@pytest.mark.parametrize("key", sorted({
    "summary", "work_experience", "projects", "skills", "education",
    "certifications", "achievements_awards", "publications",
    "internships_experience",
}))
def test_every_mappable_section_has_a_sanctioned_heading(key: str) -> None:
    """rules.heading() must not raise, and the result must be ATS-safe."""
    label = rules.heading(key)
    assert label.lower() in {h.lower() for h in load_rules()["safe_headings"]["acceptable"]}


def test_unknown_section_raises_rather_than_inventing() -> None:
    with pytest.raises(rules.RulesError):
        rules.heading("my_invented_section")


def test_banned_phrases_available_for_stage4_voice_lint() -> None:
    banned = rules.banned_phrases()
    assert "team player" in banned
    assert "results-driven" in banned


def test_page_limits_match_research() -> None:
    assert rules.page_limit("student") == 1
    assert rules.page_limit("fresher") == 1
    assert rules.page_limit("experienced") == 2


def test_layout_is_ats_safe() -> None:
    lr = " ".join(rules.layout_rules()).lower()
    assert "single column" in lr
    assert "left-aligned" in lr
    assert "reverse chronological" in lr


def test_font_and_margin_come_from_research() -> None:
    assert rules.font_family().startswith("Calibri")
    assert 10.5 <= rules.body_size_pt() <= 12.0
    assert rules.margins_inches() == 1.0


def test_market_snapshot_staleness_is_machine_checkable() -> None:
    snap = load_rules()["market_snapshot"]
    assert snap["stale_after"] > snap["date"]
    # stale ON the expiry date, not the day after
    assert rules.market_snapshot_is_stale(snap["stale_after"]) is True
    assert rules.market_snapshot_is_stale(snap["date"]) is False


def test_stale_after_matches_stale_after_days() -> None:
    """Regression: the two fields drifted apart (90 days vs a 92-day date)."""
    from datetime import date, timedelta

    snap = load_rules()["market_snapshot"]
    collected = date.fromisoformat(snap["date"])
    expected = collected + timedelta(days=snap["stale_after_days"])
    assert date.fromisoformat(snap["stale_after"]) == expected


def test_market_snapshot_is_current_today() -> None:
    from datetime import date

    assert not rules.market_snapshot_is_stale(date.today().isoformat())


def test_source_metadata_is_self_consistent() -> None:
    meta = load_rules()["meta"]
    assert meta["source_count"] >= 15
    assert meta["source_domain_count"] <= meta["source_count"]
    assert "RULES.md" in meta["source_count_method"]


def test_no_heading_is_hardcoded_outside_rules_json() -> None:
    """build.py must not contain display headings as literals."""
    import inspect

    from app.render import build

    src = inspect.getsource(build)
    # a Section(...) call must get its heading from rules.heading(...)
    for line in src.splitlines():
        if "Section(" in line and "key," in line:
            assert "rules.heading(" in line, f"hardcoded heading: {line.strip()}"
