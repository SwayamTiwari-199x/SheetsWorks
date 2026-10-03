"""The Windows 95 desktop: structure, and the promises it makes.

Split from test_frontend.py on purpose. That file checks properties of the code
as text -- no innerHTML, no remote assets, the CSP. This one checks that the
desktop is actually built out of the parts the reference image is made of, and
that the app's windows are reachable and honestly labelled.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app import rules
from app.main import app

STATIC = __import__("pathlib").Path(__file__).resolve().parent.parent / "app" / "static"
SHELL = (STATIC / "win" / "shell.js").read_text(encoding="utf-8")
APP = (STATIC / "win" / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "win" / "win95.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


# --- the shell ------------------------------------------------------------


def test_the_desktop_is_the_page() -> None:
    for anchor in ('id="desktop"', 'id="taskbar"', 'id="startBtn"',
                   'id="startMenu"', 'id="tray"'):
        assert anchor in HTML, f"missing {anchor}"


def test_the_taskbar_exists_because_windows_overlap() -> None:
    """Free-floating windows hide behind each other. The taskbar is the fix, and
    the user asked for free-floating, so it is not optional decoration."""
    assert 'id="taskButtons"' in HTML
    assert "function buildTaskButtons()" in SHELL
    assert "topmostVisible" in SHELL


def test_the_start_menu_lists_the_applications() -> None:
    assert "function buildTaskbar()" in APP
    for label in ("My Resume", "File Manager", "Preview", "Read Me",
                  "Display Properties", "AI Resume Builder", "Exit"):
        assert f"'{label}'" in APP, f"the Start menu is missing {label}"


def test_every_window_has_a_caption_with_the_usual_three_buttons() -> None:
    assert "captionBtn('min'" in SHELL
    assert "captionBtn('max'" in SHELL
    assert "captionBtn('close'" in SHELL


def test_dialogs_have_no_minimise_or_maximise() -> None:
    """A dialog with a minimise button is not a dialog."""
    body = SHELL.split("function createWindow(", 1)[1][:2600]
    assert "if (!o.dialog) {" in body, "caption buttons must be conditional"


def test_windows_cascade_instead_of_landing_on_one_spot() -> None:
    body = SHELL.split("function place(", 1)[1][:900]
    assert "cascade" in body
    assert "maxSteps" in body, "the cascade must wrap"


def test_the_cascade_clears_the_desktop_icons() -> None:
    """Cascading from the very corner buried the icon column. Found by
    screenshot; the source looked right."""
    body = SHELL.split("function place(", 1)[1][:900]
    assert "originX = 104" in body


def test_the_screen_fits_the_desktop_and_the_taskbar() -> None:
    assert "inset: 0 0 var(--taskbar-h) 0" in CSS


# --- the windows the reference image is made of ----------------------------


@pytest.mark.parametrize("window_id, opener", [
    ("editor", "openEditor"),
    ("fm", "openFileManager"),
    ("readme", "openReadMe"),
    ("preview", "openPreview"),
    ("display", "openDisplay"),
    ("about", "openAbout"),
])
def test_each_window_opens_and_is_reachable(window_id: str, opener: str) -> None:
    assert f"id: '{window_id}'" in APP, f"{window_id} has no id"
    assert f"function {opener}(" in APP, f"{opener} is missing"
    assert opener in APP.split("window.Sheetsworks =")[1], \
        f"{opener} is not reachable from the app surface"


def test_the_file_manager_shows_sections_and_entries() -> None:
    """The reference's folder tree and file list, mapped onto the resume."""
    assert "data-section" in APP and "data-role', 'entries'" in APP
    for section in ("contact", "summary", "experience", "projects", "skills"):
        assert f"'{section}'" in APP, f"the tree is missing {section}"


def test_the_display_dialog_offers_both_templates() -> None:
    body = APP.split("function openDisplay(", 1)[1][:3200]
    assert "'blank'" in body and "'sheets'" in body
    assert "Resume format" in body
    assert "button('OK'" in body and "button('Cancel'" in body
    assert "button('Help'" in body


def test_the_display_dialog_puts_its_buttons_after_the_content() -> None:
    """Appending the button bar first put OK/Cancel/Help above the group box
    they act on. Found by screenshot."""
    body = APP.split("function openDisplay(", 1)[1][:2600]
    assert body.index("rec.body.appendChild(fill)") < body.index("'msg-buttons'"), \
        "content must be appended before the buttons"


def test_the_preview_window_keeps_its_escape_hatch() -> None:
    """Regression, twice over. The live preview is fed a blob: URL into an
    iframe, and a browser that refuses it reports nothing visible -- so it once
    rendered as a blank white rectangle. A blocked frame must never be silent."""
    assert 'previewFallback' in APP
    assert 'previewOpen' in APP
    assert "openLink.href = url" in APP
    assert "fallback.hidden = false" in APP
    assert "fallback.hidden = true" in APP


def test_the_ai_window_says_why_it_is_empty() -> None:
    body = APP.split("async function openAiNotice(", 1)[1][:900]
    assert "not available" in body
    assert "rejects every available model" in body
    assert "worse than no assistant" in body


def test_the_exit_dialog_is_honest_about_what_it_does() -> None:
    """There is no server session to end. Saying so beats a fake shutdown."""
    body = APP.split("async function confirmExit(", 1)[1][:900]
    assert "Nothing to close" in body
    assert "whether or not this page is open" in body


def test_the_read_me_serves_the_research() -> None:
    """Advice on screen must be the cited research, not a paraphrase typed into
    the markup."""
    assert "state.tips" in APP
    assert "tag" in APP, "each tip must show its verified/unverified tag"
    assert "RULES.md" in (APP + HTML)


def test_the_read_me_colours_the_two_kinds_of_advice_differently() -> None:
    body = APP.split("function openReadMe(", 1)[1][:2000]
    assert "verified" in body and "unverified" in body
    assert "#006000" in body and "#a00000" in body


# --- loading and motion ---------------------------------------------------


def test_loading_states_exist_and_look_of_the_period() -> None:
    """Hourglass cursor, an ellipsis in the title, and a status bar message.
    A 1995 app that gave no feedback while working felt broken."""
    assert "is-busy" in CSS
    assert "cursor: wait" in CSS
    assert "function setBusy(" in SHELL
    body = SHELL.split("function setBusy(", 1)[1][:700]
    assert "'...'" in body, "the title must show progress"
    assert "setStatus(winId, label" in body


def test_there_is_an_indeterminate_progress_bar() -> None:
    assert ".bar.indeterminate" in CSS
    assert "@keyframes barslide" in CSS


def test_there_is_a_status_bar_marquee() -> None:
    """'325 MB, 300 MB, total' is in the reference. Ours scrolls the file
    count instead."""
    assert ".marquee" in CSS
    assert "@keyframes marquee" in CSS


def test_the_busy_state_is_always_cleared() -> None:
    """One failed request must not leave the app permanently busy."""
    body = APP.split("async function working(", 1)[1][:900]
    assert "finally" in body
    assert "W.setBusy(winId, false)" in body


def test_the_motion_is_small_and_optional() -> None:
    """1995 had no animation. What is here is an addition, so it is short and
    it is switched off for anyone who asked."""
    for name in ("win-open", "win-close", "barslide", "marquee"):
        assert f"@keyframes {name}" in CSS
    assert css_reduced_motion_disables_motion()


def css_reduced_motion_disables_motion() -> bool:
    block = CSS.split("prefers-reduced-motion", 1)[1]
    for rule in (".win.opening, .win.closing { animation: none; }",
                 "animation: none"):
        if rule in block:
            return True
    return False


def test_reduced_motion_actually_stops_the_animations() -> None:
    block = CSS.split("prefers-reduced-motion", 1)[1]
    assert "animation: none" in block
    assert "transition-duration: 0s" in block


# --- sound ----------------------------------------------------------------


def test_sound_is_generated_not_downloaded() -> None:
    """WebAudio oscillators only: nothing to fetch, nothing to fail."""
    assert "AudioContext" in SHELL or "webkitAudioContext" in SHELL
    assert "createOscillator" in SHELL
    assert "new Audio(" not in SHELL
    assert ".mp3" not in SHELL and ".wav" not in SHELL


def test_sound_is_off_until_asked_for() -> None:
    """A chime that ambushes you on page load is not nostalgia."""
    assert "let enabled = false" in SHELL
    assert "if (enabled)" in SHELL
    assert "store.get('rb.sound', false)" in APP


def test_there_is_a_startup_sting_and_an_error_beep() -> None:
    assert "startup()" in SHELL
    assert "error()" in SHELL
    assert "click()" in SHELL


# --- reachability ---------------------------------------------------------


def test_windows_can_be_deep_linked() -> None:
    """?open=fm,readme,preview. Also the only way to review a multi-window
    desktop without a mouse."""
    body = APP.split("function requestedWindows(", 1)[1][:700]
    assert "URLSearchParams" in body
    assert "get('open')" in body
    assert "typeof location === 'undefined'" in body, \
        "the flow tests run this under node, where location does not exist"


def test_an_unknown_window_name_is_ignored_rather_than_fatal() -> None:
    body = APP.split("function requestedWindows(", 1)[1][:700]
    assert "KNOWN.indexOf(s) !== -1" in body


def test_the_app_surface_is_exported() -> None:
    """The same reason Win95 exposed its windows to the shell."""
    assert "window.Sheetsworks = {" in APP
    surface = APP.split("window.Sheetsworks = {", 1)[1][:400]
    for opener in ("openEditor", "openFileManager", "openReadMe", "openPreview"):
        assert opener in surface, f"{opener} is not on the app surface"


def test_every_id_the_shell_looks_up_exists_in_the_markup() -> None:
    wanted = set(re.findall(r"getElementById\(\s*'([A-Za-z0-9_-]+)'", SHELL + APP))
    present = set(re.findall(r'id="([A-Za-z0-9_-]+)"', HTML))
    missing = sorted(wanted - present)
    assert not missing, f"the code asks for ids the markup lacks: {missing}"


# --- honesty --------------------------------------------------------------


def test_the_page_never_advertises_a_command_that_does_not_exist() -> None:
    """Carried over from the terminal UI, where it caught a `check` command
    described in two places that was never implemented. On an app whose whole
    argument is that it tells you the truth about your resume, that is the worst
    possible place to be casual."""
    for banned in ("`check`", "<code>check</code>"):
        assert banned not in HTML, f"the page advertises {banned}, which is not real"


def test_the_tips_are_served_and_escaped() -> None:
    with TestClient(app) as c:
        page = c.get("/").text
    i = page.index('<template id="tipsData">')
    blob = page[page.index(">", i) + 1:page.index("</template>", i)]
    assert "<" not in blob and ">" not in blob and "&" not in blob
    tips = json.loads(blob)["tips"]
    assert len(tips) == len(rules.tips())
    assert tips[0]["title"] == rules.tips()[0]["title"]


def test_every_tip_is_cited() -> None:
    for tip in rules.tips():
        assert tip["source"], f"{tip['title']!r} has no source"
        assert tip["tag"] in ("verified", "unverified")


def test_no_innerhtml_in_the_new_ui() -> None:
    """Icons go through DOMParser instead. A <template> and an SVG string must
    never become live markup."""
    for name, src in (("shell.js", SHELL), ("app.js", APP)):
        body = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
        body = re.sub(r"(?<!:)//[^\n]*", "", body)
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert banned not in body, f"{banned} in {name}"


def test_icons_are_parsed_not_assigned() -> None:
    """image/svg+xml has no script execution and no HTML fallback."""
    assert "DOMParser" in SHELL
    assert "'image/svg+xml'" in SHELL
    assert "parsererror" in SHELL, "a malformed icon must not throw"
    assert "createElementNS" in SHELL, "and must fall back rather than crash"


def test_the_route_surface_did_not_grow() -> None:
    with TestClient(app) as c:
        paths = set(c.get("/openapi.json").json()["paths"])
    assert paths == {
        "/health", "/profile", "/versions", "/versions/from-profile",
        "/export/{version_id}", "/preview",
    }


def test_nothing_loads_from_the_network() -> None:
    for banned in ("@import", "fonts.googleapis", "http://", "https://", "url("):
        assert banned not in CSS, f"win95.css reaches outside via {banned}"
    assert "http://" not in HTML.replace("http://www.w3.org", "")