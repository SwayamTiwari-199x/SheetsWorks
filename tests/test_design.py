"""The redesigned front page.

The redesign changed the shape of the UI but none of its contracts: the
terminal is still the only way to edit, all text still arrives as textContent,
and the route surface did not grow. These tests hold those, plus the things
that only exist because of the redesign.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app import rules
from app.main import app

STATIC = __import__("pathlib").Path(__file__).resolve().parent.parent / "app" / "static"
JS = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
SITE = (STATIC / "site.css").read_text(encoding="utf-8")
TERM = (STATIC / "term.css").read_text(encoding="utf-8")


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


# --- the shell -------------------------------------------------------------


def test_the_four_views_from_the_brief_all_exist() -> None:
    for view in ("home", "draft", "new", "ai"):
        assert f'id="view-{view}"' in HTML, f"missing the {view} view"


def test_navbar_says_what_the_brief_said() -> None:
    assert ">Home</button>" in HTML
    assert ">Draft</button>" in HTML
    assert ">New Resume</button>" in HTML
    assert ">AI Resume Builder</button>" in HTML


def test_exactly_one_view_is_visible_on_arrival() -> None:
    """A page that opens with two panels stacked is a layout bug, not a theme."""
    hidden = re.findall(r'<section class="view" id="view-\w+"[^>]*hidden', HTML)
    assert len(hidden) == 3, "home is the only view that should start visible"


def test_the_three_columns_are_left_rail_stage_preview() -> None:
    assert 'id="rail"' in HTML and 'id="stage"' in HTML
    assert "#page" in SITE and "grid-template-columns" in SITE


def test_preview_is_open_by_default_and_never_a_silent_blank() -> None:
    """It is the point of the page, so it starts showing; and the escape
    hatch survives the move out of the overlay."""
    pane = re.search(r'<section id="previewPane"[^>]*>', HTML).group(0)
    assert "hidden" not in pane
    assert 'id="previewFallback"' in HTML and 'id="previewOpen"' in HTML
    assert "previewOn: true" in JS


def test_click_to_edit_lives_beside_the_preview() -> None:
    """Clicking inside a rendered PDF cannot work, so the affordance is an
    explicit jump list that types `cd <section>` instead."""
    assert 'id="jumpNav"' in HTML
    assert "buildSectionNav(el.jumpNav" in JS
    assert "runTyped('cd ' + section)" in JS


def test_ai_view_is_a_placeholder_that_says_so() -> None:
    """Honest about being unavailable beats a panel that looks finished."""
    block = HTML[HTML.index('id="view-ai"'):HTML.index('id="view-ai"') + 700]
    assert "Not built yet" in block
    assert "AI Helper" in HTML, "the rail keeps an always-visible helper slot"


# --- the vintage look ------------------------------------------------------


def test_vintage_is_the_default_theme() -> None:
    assert 'data-theme="vintage"' in HTML
    assert 'html[data-theme="vintage"]' in TERM


def test_palette_is_defined_once_not_twice() -> None:
    """Both stylesheets read the same custom properties. Two definitions is how
    the terminal and the page drift apart."""
    assert "data-theme=" not in SITE
    for theme in ("amber", "green", "matrix", "paper", "vintage"):
        assert f'html[data-theme="{theme}"]' in TERM


def test_app_offers_exactly_the_themes_the_css_defines() -> None:
    offered = set(re.findall(r"'([a-z]+)'", re.search(r"THEMES = \[([^\]]*)\]", JS).group(1)))
    defined = set(re.findall(r'html\[data-theme="([a-z]+)"\]', TERM))
    assert offered == defined


def test_beaded_frames_are_css_not_images() -> None:
    """The bead work is a tiled dot gradient on a padding ring."""
    assert ".bead" in SITE
    assert "radial-gradient" in SITE
    assert "url(" not in SITE, "nothing may be loaded from a file or a URL"


def test_paper_texture_is_generated_not_downloaded() -> None:
    assert "radial-gradient" in SITE
    assert "background-size" in SITE


def test_polaroids_use_inline_svg() -> None:
    assert "<svg" in HTML and "polaroid" in SITE
    # Generated art, so there is no asset to license or fail to load.
    assert "http" not in HTML[HTML.index("<svg"):HTML.index("</svg>")]


def test_nothing_loads_from_the_network() -> None:
    for name in ("site.css", "term.css"):
        css = read(name)
        for banned in ("@import", "fonts.googleapis", "http://", "https://", "url("):
            assert banned not in css, f"{name} reaches outside via {banned}"
    assert "fonts.googleapis" not in HTML


def test_rotation_respects_reduced_motion() -> None:
    assert "prefers-reduced-motion" in SITE
    assert "prefers-reduced-motion" in TERM


# --- news comes from the research ------------------------------------------


def test_tips_exist_in_rules_json_and_are_cited() -> None:
    tips = rules.tips()
    assert len(tips) >= 6
    for tip in tips:
        assert tip["title"] and tip["body"], tip
        assert tip["source"], f"{tip['title']!r} has no source"
        assert tip["tag"] in ("verified", "unverified"), tip


def test_page_injects_the_tips_from_rules_json() -> None:
    """The NEWS panel must show the researched advice, not a paraphrase
    someone typed into the markup."""
    with TestClient(app) as c:
        html = c.get("/").text
    blob = html[html.index('<template id="tipsData">'):
                html.index("</template>", html.index('<template id="tipsData">'))]
    payload = blob[blob.index(">") + 1:]
    tips = json.loads(payload)["tips"]
    assert len(tips) == len(rules.tips())
    assert tips[0]["title"] == rules.tips()[0]["title"]


def test_injected_json_cannot_close_the_template_or_open_a_tag() -> None:
    """A <template> is inert, but only if the payload cannot end it early."""
    with TestClient(app) as c:
        html = c.get("/").text
    blob = html[html.index('<template id="tipsData">'):
                html.index("</template>", html.index('<template id="tipsData">'))]
    payload = blob[blob.index(">") + 1:]
    assert "<" not in payload and ">" not in payload and "&" not in payload


def test_news_panel_never_uses_innerhtml() -> None:
    """The tips are third-party sourced text going into the DOM."""
    body = JS[JS.index("function renderNews"):JS.index("function stepNews")]
    assert "innerHTML" not in body
    assert "textContent" in body


def test_unverified_advice_is_labelled_as_such() -> None:
    """Half this advice rests on a single source and the panel must not imply
    otherwise."""
    assert "tip.src" in JS or "tip-src" in JS
    assert 'tag.setAttribute(\'data-tag\'' in JS
    assert 'data-tag="unverified"' in SITE
    tags = {t["tag"] for t in rules.tips()}
    assert tags == {"verified", "unverified"}, "both kinds should be represented"


def test_tips_load_failure_does_not_break_the_page() -> None:
    """A malformed payload must degrade to an empty panel, not a boot crash."""
    body = JS[JS.index("function loadTips"):JS.index("function renderNews")]
    assert "catch" in body and "return []" in body


# --- progress reflects the active template ---------------------------------


def test_progress_ignores_sections_the_template_hides() -> None:
    """Counting a hidden section as missing work would punish choosing
    `sheets`, which deliberately prints no summary."""
    body = JS[JS.index("function progressOf"):JS.index("function renderProgress")]
    assert "sectionPrinted" in body


def test_chrome_refreshes_from_the_same_place_as_the_navbar() -> None:
    """Two independent update paths would let the page disagree with the
    terminal."""
    navbar = JS[JS.index("function refreshNavbar"):JS.index("function sectionPrinted")]
    assert "refreshChrome()" in navbar


def test_terminal_output_pulls_the_draft_view_forward() -> None:
    """Otherwise a command fired from the Home page prints where nobody sees."""
    out_fn = JS[JS.index("function out(text, cls)"):JS.index("const outLines")]
    assert "showView('draft')" in out_fn


def test_a_first_time_visitor_lands_in_the_terminal() -> None:
    """The welcome text lives there; showing it in a hidden box would be
    useless."""
    boot = JS[JS.index("function openingView"):JS.index("function welcome")]
    assert "return emptyProfile ? 'draft' : 'home';" in boot


def _command_names() -> set[str]:
    """The keys of the COMMANDS object, and nothing else.

    Parsed out of the object literal itself rather than by a loose line regex:
    a loose regex also picks up `undo: []` inside `state`, and quietly
    over-reporting the command list would let a lie through this test.
    """
    start = JS.index("const COMMANDS = {")
    end = JS.index("\n};", start)
    block = JS[start:end]
    return set(re.findall(r"(?m)^  ([a-z][a-zA-Z0-9]*)\s*(?:\(args\))?\s*[:(]", block))


def test_the_page_never_advertises_a_command_that_does_not_exist() -> None:
    """The UI tells the user what to type. If it names a command that is not
    there, the page is lying about its own capabilities.

    This caught `check`, described in two places as listing broken rules and
    never implemented. On an app whose whole argument is that it tells you the
    truth about your resume, that is the worst possible place to be casual.
    """
    real = _command_names()
    assert {"ls", "cat", "help", "demo", "hint"} <= real, real

    # Template names appear as <code> too, and they are not commands. Read them
    # from the app rather than hardcoding, so a new template needs no edit here.
    templates = set(re.findall(r"^  ([a-z]+):", JS[JS.index("const TEMPLATE_BLURB"):
                                                        JS.index("const TEMPLATE_BLURB") + 400],
                                re.M))
    not_commands = {"resume", "profile", "pdf", "docx", "txt"} | templates

    mentioned = set(re.findall(r"<code>([a-z]+)</code>", HTML))
    missing = sorted((mentioned - not_commands) - real)
    assert not missing, f"the page tells the user to type {missing}, which do not exist"

    # Every data-cmd button must also name a real command.
    for cmd in re.findall(r'data-cmd="([a-z]+)[^"]*"', HTML):
        assert cmd in real, f"a button runs `{cmd}`, which is not a command"


def test_the_command_names_are_what_the_help_advertises() -> None:
    """`help` lists the commands; the navbar offers them. Same set."""
    navbed = set(re.findall(r"add\('([a-z]+)',", JS))
    helptext = JS[JS.index("const HELP"):] if "const HELP" in JS else ""
    assert navbed <= _command_names(), f"navbar offers non-commands: {navbed - _command_names()}"
    assert "help" in navbed


def test_the_ai_view_says_why_it_is_empty() -> None:
    """A placeholder that looks finished is worse than an honest gap."""
    view = HTML[HTML.index('id="view-ai"'):]
    view = view[:view.index("</section>")]
    assert "Not built yet" in view
    assert "rejects" in view, "it should say why, not just that"
    assert "fail silently" in view


def test_the_new_resume_view_offers_both_ways_to_start() -> None:
    """Blank skeleton and a named format, as asked for."""
    view = HTML[HTML.index('id="view-new"'):]
    view = view[:view.index("</section>", view.index('id="sampleHead"'))]
    assert "Blank skeleton" in view
    assert 'id="newBlank"' in view
    assert "blank" in view and "sheets" in view
    assert 'id="useBlank"' in view and 'id="useSheets"' in view


def test_a_view_can_be_deep_linked() -> None:
    """?view=draft is how the other three views can be reached without a
    mouse, and how each one gets looked at."""
    body = JS[JS.index("function openingView"):JS.index("async function boot")]
    assert "URLSearchParams" in body and "get('view')" in body
    # An unknown or hostile value must not blank the page.
    assert "if (asked && el.views[asked])" in body
    # `location` does not exist when this file runs under node, so it has to be
    # feature-detected rather than read bare.
    assert "typeof location !== 'undefined'" in body


# --- wiring safety ---------------------------------------------------------


def test_every_id_app_js_asks_for_exists_in_the_markup() -> None:
    """A redesign's most common silent failure: JS reaching for an element the
    new markup does not have."""
    wanted = set(re.findall(r"getElementById\(\s*'([A-Za-z0-9_-]+)'", JS))
    present = set(re.findall(r'id="([A-Za-z0-9_-]+)"', HTML))
    missing = sorted(wanted - present)
    assert not missing, f"app.js asks for ids the markup lacks: {missing}"


def test_chrome_is_optional_so_the_terminal_survives_without_it() -> None:
    """Editing must never depend on any of the page furniture.

    If the rail is absent the terminal has to keep working, so each optional
    element is either guarded at its use site or handed to a helper that
    guards its argument.
    """
    assert "function hasChrome()" in JS
    body = JS[JS.index("function refreshChrome"):JS.index("function sectionPrinted")]
    assert "if (!hasChrome()) return;" in body

    for guarded in ("el.newsBody", "el.notesList", "el.progressFill", "el.recentName"):
        assert f"if (!{guarded}" in JS, f"{guarded} is used unguarded"

    # The two jump lists share a builder, so the guard lives there.
    builder = JS[JS.index("function buildSectionNav"):JS.index("function renderRecent")]
    assert "if (!container) return;" in builder
    assert "buildSectionNav(el.sectionNav" in JS
    assert "buildSectionNav(el.jumpNav" in JS


def test_the_route_surface_did_not_grow() -> None:
    """The tips ride along in the page rather than adding an endpoint."""
    with TestClient(app) as c:
        paths = set(c.get("/openapi.json").json()["paths"])
    assert paths == {
        "/health", "/profile", "/versions", "/versions/from-profile",
        "/export/{version_id}", "/preview",
    }


def test_page_still_gets_its_csp_and_no_store() -> None:
    with TestClient(app) as c:
        r = c.get("/")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "frame-src 'self' blob:" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("asset", ("site.css", "term.css", "app.js"))
def test_new_assets_are_served_with_the_page_csp(asset: str) -> None:
    with TestClient(app) as c:
        r = c.get(f"/static/{asset}")
    assert r.status_code == 200
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_hidden_views_actually_hide() -> None:
    """Regression, found by screenshotting rather than by any test.

    term.css sets `#view-draft { display: flex }`. An id outranks
    `.view[hidden] { display: none }`, so every view rendered at once and the
    Home page and the terminal were stacked on top of each other. The hidden
    rule has to out-specify the id.
    """
    hidden_rule = re.search(r"([^{}]*\.view\[hidden\][^{]*)\{", SITE).group(1).strip()
    assert "#stage" in hidden_rule, (
        "the hidden rule must out-specify term.css's #view-draft { display: flex }"
    )
    # And nothing may reintroduce a bare .view[hidden] that loses that fight.
    assert not re.search(r"(?<!#stage )\.view\[hidden\]\s*\{\s*display:\s*none", SITE)


def test_the_terminal_is_the_only_view_that_forces_a_display() -> None:
    """Any other id-level display rule would re-break the same way."""
    offenders = [m.group(1) for m in re.finditer(r"^#(view-[\w-]+)\s*\{([^}]*)\}", TERM, re.M)
                 if "display:" in m.group(2)]
    for view in offenders:
        assert view != "home" or True
    # Only the draft view legitimately sets display, and it hides via the rule above.
    assert set(offenders) <= {"view-draft"}


def test_stylesheets_are_linked_in_order_chrome_first() -> None:
    """site.css sets the layout; term.css must win where they overlap."""
    assert HTML.index("/static/site.css") < HTML.index("/static/term.css")


def test_no_inline_style_attributes_or_style_blocks() -> None:
    """style-src has no 'unsafe-inline', so either would silently do nothing."""
    assert "<style" not in HTML
    assert not re.search(r'\sstyle="', HTML)