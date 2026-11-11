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
from app.models import Profile, VersionSummary

STATIC = __import__("pathlib").Path(__file__).resolve().parent.parent / "app" / "static"
SHELL = (STATIC / "win" / "shell.js").read_text(encoding="utf-8")
APP = (STATIC / "win" / "app.js").read_text(encoding="utf-8")
EDITOR = (STATIC / "win" / "editor.js").read_text(encoding="utf-8")
MODEL = (STATIC / "win" / "editor-model.js").read_text(encoding="utf-8")
FAILURES_JS = (STATIC / "win" / "failures.js").read_text(encoding="utf-8")
SAMPLE = (STATIC / "win" / "sample.js").read_text(encoding="utf-8")
CSS = (STATIC / "win" / "win95.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def _sample_profile() -> dict:
    """The smallest profile the API will accept.

    Built from the real model rather than a literal, so it cannot drift out of
    sync with the required fields -- which is the mistake this file exists to
    catch elsewhere.
    """
    # Not the placeholder "Anon": POST /versions/from-profile refuses to
    # snapshot one, and most tests in this file snapshot to set up.
    return Profile(
        contact={"name": "Sample Applicant", "email": "anon@example.com",
                 "phone": "+91 98765 43210"},
    ).model_dump(mode="json")


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
    # The editor's window is created in editor.js, the rest in app.js. Search
    # both, or this test quietly stops covering the editor.
    everywhere = APP + EDITOR
    assert f"id: '{window_id}'" in everywhere, f"{window_id} has no id"
    assert f"function {opener}(" in APP, f"{opener} is missing"
    assert opener in APP.split("window.Sheetsworks =")[1], \
        f"{opener} is not reachable from the app surface"


def test_the_file_manager_is_a_resume_browser_and_a_version_browser() -> None:
    """Both, chosen by a tab bar.

    It started as a section browser and was described in PROGRESS.md as the
    version browser it was not. Snapshots were write-only -- you could make one
    and never list or remove it. The Versions tab is the fix, and it is why
    GET /versions and DELETE /versions/{id} exist.
    """
    assert "data-section" in APP, "the Resume pane still needs its section rows"
    assert "data-mode" in APP and "'versions'" in APP, "no Versions tab"
    for section in ("contact", "summary", "experience", "projects", "skills"):
        assert f"M.ORDER" in APP, (
            "the section list must come from the model, not a hand-written "
            "array that can disagree with the editor"
        )
    # Versions mode must list, select, export and delete -- not just display.
    assert "GET /versions" in APP or "'/versions'" in APP
    assert "data-version" in APP, "version rows are not addressable"
    assert "fmSnapshot" in APP, "there must be a way to create a snapshot"
    assert "doExport" in APP, "a listed version must be exportable"
    assert "'/versions/' + encodeURIComponent(v.id)" in APP, (
        "a listed version must be deletable"
    )
    # And a failure to load must not look like an empty database.
    assert "Could not load versions" in APP


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
    assert "openLink.setAttribute('href', url)" in APP
    # Both states must go through showFallback(), never `hidden` directly --
    # see test_the_fallback_is_hidden_by_display_not_by_the_hidden_property.
    assert "showFallback(fallback, true)" in APP
    assert "showFallback(fallback, false)" in APP


def _strip_comments(src: str) -> str:
    """Source with block and line comments removed.

    Necessary because these tests assert on strings that also appear in the
    comments explaining why they matter -- so a comment saying "the old code did
    X" makes a test forbidding X fail on its own documentation.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", src, flags=re.MULTILINE)


def _function(src: str, signature: str, limit: int = 12000) -> str:
    """The body of a top-level function, up to the next one.

    Slicing a fixed number of characters was how three of these tests started
    failing when an unrelated comment grew -- a test that breaks because
    documentation got longer is a test measuring the wrong thing.
    """
    assert signature in src, f"{signature} not found"
    rest = src.split(signature, 1)[1]
    nxt = re.search(r"\n(?:function|const|let|var|\})", rest)
    return rest[: nxt.start()] if nxt else rest[:limit]


def test_auto_height_dialogs_really_auto_height() -> None:
    """Regression.

    `h: 'auto'` was passed through `place(o.w, o.h === 'auto' ? 200 : o.h)` and
    then tested as `geom.h === 'auto'` -- which could never be true, because the
    'auto' had already been replaced by 200. So every auto-height dialog was
    silently locked to 200px tall.

    It went unnoticed because message boxes are short, and a short dialog clipped
    at 200px just looks like a dialog. The Export dialog's content finally
    exceeded 200px and pushed its OK and Cancel buttons outside the window: a
    dialog that could be neither confirmed nor cancelled. Asserting its
    textContent contained "Cancel" passed the whole time.
    """
    code = _strip_comments(SHELL)
    body = _function(code, "function createWindow(")
    assert "const autoH = o.h === 'auto';" in body, (
        "the auto flag must be latched BEFORE place() rewrites it"
    )
    assert "place(o.w, autoH ? 200 : o.h)" in body
    assert "if (autoH) win.style.height = 'auto';" in body, (
        "and it must be the flag that decides, not the post-place() value"
    )
    assert "geom.h === 'auto'" not in code, (
        "this comparison is dead code that hides the bug -- remove it"
    )


def test_every_auto_height_dialog_can_be_confirmed_and_cancelled() -> None:
    """A dialog with no button bar cannot be dismissed except by Escape, which
    is not how a dialog is used.

    This exists because the Export dialog did have buttons -- they were simply
    outside the window, which no textContent assertion could see. The browser
    harness now checks the geometry instead; this checks the buttons exist at
    all, which is the cheaper half.
    """
    for src, name, fn in ((APP, "app.js", "function openExport("),
                          (EDITOR, "editor.js", "function askText(")):
        body = _function(_strip_comments(src), fn)
        assert "h: 'auto'" in body, f"{name}:{fn} should size to its content"
        assert re.search(r"el\('button'|\.btn|createElement\('button'|button\(", body), (
            f"{name}:{fn} creates no buttons, so it can be neither confirmed "
            "nor cancelled"
        )
        assert "Cancel" in body, f"{name}:{fn} offers no way out"


def test_the_message_box_takes_its_buttons_from_the_caller() -> None:
    """`messageBox` is the one dialog whose buttons vary, so it must not hardcode
    a list -- it reads `o.buttons` with a single OK as the default.

    Worth asserting separately because "offers no way out" and "hardcodes Cancel"
    are the same failure for every other dialog and the opposite requirement here.
    """
    body = _function(_strip_comments(SHELL), "function messageBox(")
    assert "o.buttons" in body, (
        "the message box must take its button list from the caller"
    )
    assert "['OK']" in body, "and must default to a single OK"
    assert re.search(r"\bbuttons\.(forEach|map)\b", body), (
        "and must actually render the buttons it was given, not just read them"
    )


def test_the_app_publishes_a_readiness_signal() -> None:
    """Regression. A window existing is not the app being ready.

    `state.profile` does not settle until boot's `/profile` fetch returns. The
    screenshot harness used "is the editor window there?" as its ready signal,
    seeded a profile into the gap, and then had boot overwrite it with null --
    which surfaced as five failures that read like five unrelated bugs in the
    version list and the preview.

    So the app publishes `Sheetsworks.ready`, and it must resolve on BOTH boot
    paths. The `?open=` branch returns early, and it is exactly the URL the
    harness uses for screenshots, so a `finally` is the whole difference between
    that working and hanging forever.
    """
    assert "const ready = new Promise" in APP, "no readiness promise"
    assert "ready," in APP, "readiness must be on the public surface"
    assert "markReady()" in APP
    inner = APP.split("async function bootPromise(", 1)[1][:400]
    assert "finally" in inner, (
        "readiness must resolve even when boot returns early for ?open="
    )


def test_a_version_list_reports_each_version_s_own_template() -> None:
    """Regression, and a case of a shortcut looking reasonable.

    `template` lives inside the JSON body column. The first version of
    `GET /versions` deliberately did not read that column -- it holds the whole
    resume, and reading fifty of them to print one word in a listbox is
    indefensible. So it reported the default, `"blank"`, for every row.

    That is worse than not reporting it: a File Manager showing "Template:
    blank" above a version actually rendered from the `sheets` template is not a
    rough edge, it is a lie about the user's own files. The fix was to promote
    `template` to a real column, so the index carries it and the body is still
    never touched.
    """
    with TestClient(app) as c:
        c.put("/profile", json=_sample_profile())
        a = c.post("/versions/from-profile?name=a&template=blank").json()
        b = c.post("/versions/from-profile?name=b&template=sheets").json()
        rows = {r["name"]: r["template"] for r in c.get("/versions").json()}
        assert rows == {"a": "blank", "b": "sheets"}, rows
        # And the snapshot itself is unchanged by the promotion.
        assert b["template"] == "sheets"
        assert a["template"] == "blank"


def test_an_existing_database_gains_the_template_column(tmp_path) -> None:
    """`CREATE TABLE IF NOT EXISTS` does nothing for a table that already
    exists, so a developer with a resume.db from before this column would get an
    OperationalError on the first write instead of a working app.

    The migration is exercised by building the OLD table by hand and opening it,
    which is the only way to actually test a migration.
    """
    import sqlite3

    from app import db as dbmod

    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    # Exactly the Stage 2 schema: no `template` column.
    conn.execute(
        """CREATE TABLE versions (
               id TEXT PRIMARY KEY, name TEXT NOT NULL, jd_id TEXT,
               body TEXT NOT NULL, created_at TEXT NOT NULL)"""
    )
    conn.execute(
        "INSERT INTO versions VALUES (?,?,?,?,?)",
        ("v1", "an old version", None, "{}", "2026-01-01"),
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(old)
    try:
        dbmod._add_column_if_missing(conn, "versions", "template",
                                     "TEXT NOT NULL DEFAULT 'blank'")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(versions)")}
        assert "template" in cols, cols
        # The existing row survives, with the default filled in.
        row = conn.execute("SELECT name, template FROM versions").fetchone()
        assert row == ("an old version", "blank"), row
        # Running it twice is harmless.
        dbmod._add_column_if_missing(conn, "versions", "template",
                                     "TEXT NOT NULL DEFAULT 'blank'")
        assert conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 1
    finally:
        conn.close()


def test_clicking_anywhere_in_a_window_raises_it() -> None:
    """Regression, and a whole class of them.

    `focusWindow` was reachable from exactly three places: creating a window,
    dragging its title bar, and restoring. So the only way to bring an overlapped
    window forward was to drag it, and clicking its body or one of its controls
    did nothing -- the click went to a window sitting behind others.

    No test caught it because every test either opened a window (which focuses
    it) or clicked a control that was already on top. Same lesson as the veil
    that covered every modal: a control can exist, be focusable and respond, and
    still be unusable.
    """
    assert "raiseOnPointerDown" in SHELL
    assert "raiseOnPointerDown(id, win);" in SHELL, (
        "the listener must actually be attached when a window is created"
    )
    helper = SHELL.split("function raiseOnPointerDown(", 1)[1][:700]
    assert "pointerdown" in helper, (
        "pointerdown, not click: focus must move before the control's own handler"
    )
    assert "focusWindow(id)" in helper


def test_the_ai_window_says_why_it_is_empty() -> None:
    """The AI notice window is now dynamic: it reads the injected LLM config
    and shows either a ready message (if OpenRouter configured) or an error.
    Both branches must be present in the source.
    """
    body = APP.split("async function openAiNotice(", 1)[1][:900]
    # Must contain the unavailable branch (for unconfigured state)
    assert "not available" in body
    assert "missing LLM_MODEL" in body
    # Must contain the ready branch (for OpenRouter configured)
    assert "AI Resume Builder is ready" in body
    assert "OpenRouter is configured" in body
    assert "Tell the AI" in body


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
    surface = APP.split("window.Sheetsworks = {", 1)[1][:500]
    for opener in ("openEditor", "openFileManager", "openReadMe", "openPreview",
                   "loadSample"):
        assert opener in surface, f"{opener} is not on the app surface"


# --- the sample resume -----------------------------------------------------


def test_a_sample_resume_exists_and_is_loadable() -> None:
    """You cannot test a resume builder with nothing to look at."""
    assert "window.SampleResume" in APP
    src = (STATIC / "win" / "sample.js").read_text(encoding="utf-8")
    assert "Sample Analytics" in src
    assert "Sample Institute of Technology" in src
    assert "Anon" in src


def test_the_sample_is_obviously_fake() -> None:
    """A demo that reads like a real CV is a demo somebody sends by accident."""
    src = (STATIC / "win" / "sample.js").read_text(encoding="utf-8")
    body = APP.split("async function loadSample(", 1)[1][:900]
    assert "not a real person" in body or "does not exist" in body
    assert "Sample Analytics" in src


def test_loading_the_sample_refuses_to_clobber_real_work() -> None:
    src = (STATIC / "win" / "sample.js").read_text(encoding="utf-8")
    body = APP.split("async function loadSample(", 1)[1][:900]
    assert "isEmpty(state.profile)" in body
    assert "overwrite" in body
    assert "Replace" in body
    assert "isEmpty: function" in src


def test_the_sample_is_reachable_from_the_desktop_and_the_start_menu() -> None:
    assert "'Sample Resume'" in APP
    assert APP.count("'Sample Resume'") >= 2, "icon and Start menu item"


def test_the_sample_satisfies_every_field_the_model_requires() -> None:
    """A sample the API rejects is worse than no sample."""
    import re as _re
    src = (STATIC / "win" / "sample.js").read_text(encoding="utf-8")
    for field in ("contact", "summary", "interests", "education", "experience",
                  "projects", "skills", "certifications", "achievements",
                  "extracurriculars", "publications"):
        assert f"{field}:" in src, f"the sample is missing {field}"
    for sub in ("name:", "email:", "phone:"):
        assert sub in src, f"contact is missing {sub}"
    assert _re.search(r"grade:\s*\{\s*value:", src), "grade must be {value, scale}"


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


def test_the_route_surface_is_exactly_what_the_app_uses() -> None:
    """Renamed from `..._did_not_grow`, which is no longer the property worth
    holding.

    "Exactly six routes" was true when written and became a false comfort: it
    said the surface was minimal, not that it was right. Adding `GET /versions`
    and `DELETE /versions/{version_id}` broke it -- correctly. Snapshots were
    write-only, so the File Manager could not be the version browser it claimed
    to be, and there was no way to remove one.

    The list is now pinned to what the app actually calls, so an endpoint cannot
    appear or vanish unnoticed. It is still an exact set: this is not a test that
    was loosened to make a change pass.
    """
    with TestClient(app) as c:
        paths = set(c.get("/openapi.json").json()["paths"])
    assert paths == {
        "/health", "/profile",
        "/versions", "/versions/{version_id}", "/versions/from-profile",
        "/export/{version_id}", "/preview",
        "/assist/{section}", "/assist/answer",
    }


def test_the_version_list_carries_no_profile_snapshot() -> None:
    """A list of fifty snapshots must not ship fifty complete resumes.

    `VersionSummary` exists only for this: `Version` requires
    `profile_snapshot`, which is the whole resume. The endpoint also does not
    read the `body` column at all, so a version list never touches personal
    details it has no use for.
    """
    assert VersionSummary is not None
    with TestClient(app) as c:
        assert "profile_snapshot" not in VersionSummary.model_fields
        assert "name" in VersionSummary.model_fields
        assert "created_at" in VersionSummary.model_fields
        c.put("/profile", json=_sample_profile())
        created = c.post("/versions/from-profile?name=one")
        assert created.status_code == 201
        listed = c.get("/versions")
        assert listed.status_code == 200
        assert listed.headers.get("Cache-Control") == "no-store"
        rows = listed.json()
        assert len(rows) == 1
        assert rows[0]["name"] == "one"
        assert rows[0]["id"] == created.json()["id"]
        assert "profile_snapshot" not in rows[0]
        # The name on a snapshot is often a real person's name, so no-store.
        assert "contact" not in rows[0]


def test_a_version_can_be_deleted_and_deleting_it_twice_is_a_404() -> None:
    with TestClient(app) as c:
        c.put("/profile", json=_sample_profile())
        created = c.post("/versions/from-profile?name=temporary").json()
        assert len(c.get("/versions").json()) == 1
        assert c.delete(f"/versions/{created['id']}").status_code == 204
        assert c.get("/versions").json() == []
        # Second delete must not pretend to succeed.
        assert c.delete(f"/versions/{created['id']}").status_code == 404
        assert c.delete("/versions/does-not-exist").status_code == 404


def test_the_version_list_is_newest_first() -> None:
    """`created_at` is a plain ISO date, so several snapshots taken on one day
    would come back in arbitrary order. A browser that reshuffles on reload is
    worse than one that is merely unsorted, so the id breaks the tie."""
    with TestClient(app) as c:
        c.put("/profile", json=_sample_profile())
        ids = [c.post("/versions/from-profile?n=1").json()["id"],
               c.post("/versions/from-profile?n=2").json()["id"],
               c.post("/versions/from-profile?n=3").json()["id"]]
        listed = [row["id"] for row in c.get("/versions").json()]
        assert listed == list(reversed(ids)), (listed, ids)


def test_the_route_surface_limit_is_bounded() -> None:
    """A GET list that ignores its limit is a way to dump the whole table into
    one response."""
    with TestClient(app) as c:
        c.put("/profile", json=_sample_profile())
        for i in range(5):
            c.post(f"/versions/from-profile?n={i}")
        assert len(c.get("/versions?limit=2").json()) == 2
        assert len(c.get("/versions?limit=500").json()) == 5
        assert c.get("/versions?limit=0").status_code == 422
        assert c.get("/versions?limit=9999").status_code == 422


def test_every_window_record_property_that_is_read_is_also_written() -> None:
    """Regression, and a whole class of them.

    `createWindow` builds a record and every other function reads properties off
    it. `rec.dialog` was read by the Escape handler and by toggleMax() but never
    assigned. Undefined is falsy, so nothing threw and nothing looked broken --
    Escape simply could not dismiss a modal dialog, and a dialog would have been
    maximisable. Only found by dispatching a real key event at the real page.

    So: any `rec.<name>` read anywhere in the shell must appear in the record
    literal. That catches the next one before it ships.
    """
    start = SHELL.index("const rec = {")
    end = SHELL.index("};", start)
    literal = SHELL[start:end]
    written = set(re.findall(r"(\w+)\s*[,:]", literal))

    body = SHELL.replace(literal, "")
    read = set(re.findall(r"\brec\.(\w+)", body))

    # el/title/body are destructured in the literal itself, and iconName is
    # assigned just after it; both are legitimate.
    missing = sorted(read - written - {"iconName"})
    assert not missing, (
        f"read off a window record but never assigned to it: {missing}"
    )


def test_no_file_references_a_global_that_does_not_exist() -> None:
    """Regression, caught the moment the editor landed.

    `editor.js` is wrapped as `(function (global) {...})(window)`, so inside it
    `global` is a parameter. `app.js` is `(function () {...})()` -- no parameter
    -- and browsers do not define a global `global` at all. Writing
    `global.EditorForm` there is a ReferenceError, and it happened during boot,
    so the desktop never came up.

    The harness reported it as one line: "boot never completed". A guard that
    fails loudly beats a blank page.
    """
    for name, src in (("app.js", APP), ("editor.js", EDITOR),
                      ("shell.js", SHELL), ("editor-model.js", MODEL),
                      ("failures.js", FAILURES_JS)):
        takes_global = re.search(r"\(function\s*\(\s*global\s*\)", src)
        body = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
        for i, line in enumerate(body.splitlines(), 1):
            if not re.search(r"(?<![\w.])global\.", line):
                continue
            if takes_global:
                continue
            # Otherwise it must be node's own `global`, which only exists in the
            # modules that fall back to globalThis so node can drive them.
            assert name in ("editor-model.js", "failures.js"), (
                f"{name}:{i} uses `global.` but does not take it as a parameter"
            )


def test_a_fresh_install_starts_as_the_placeholder_not_a_real_name() -> None:
    """emptyProfile() is what a new install opens with.

    It has to start as 'Anon', the same string POST /versions/from-profile
    refuses, so the refusal is the real first-run state instead of a rule that
    only triggers after the user typed the word 'Anon' themselves.
    """
    body = re.sub(r"/\*.*?\*/", "", APP, flags=re.DOTALL)
    start = body.index("function emptyProfile()")
    chunk = body[start:start + 600]
    assert "name: 'Anon'" in chunk, "a fresh install opens with a blank name"

    # No real personal data anywhere in the shipped front end. Expressed as
    # "only placeholder contact values are present" rather than as a list of
    # banned surnames, because a test that spells out the name it is banning
    # puts the name back into the repository -- which is the thing it exists to
    # prevent.
    for src in (APP, EDITOR, SAMPLE):
        for m in re.finditer(r"email:\s*'([^']+)'", src):
            assert m.group(1).endswith("@example.com"), \
                f"{m.group(1)} is not a reserved example address"
        for m in re.finditer(r"phone:\s*'([^']+)'", src):
            assert m.group(1).startswith("555-01"), \
                f"{m.group(1)} is not the reserved 555-01xx fake range"
        assert not re.search(r"city:\s*'[A-Z][a-z]", src), \
            "an invented city is present"


def test_the_ai_dialogs_show_the_servers_words_not_the_status_code() -> None:
    """"HTTP 400" is not a diagnosis.

    The provider's message names the field it rejected. Every AI fetch in
    editor.js has to read it out of the response body instead of interpolating
    res.status, or a real provider failure is reported as a meaningless number.

    Both calls now share one `callAssist`, so this asserts on that instead of on a
    call count: a second fetch added later would bypass the reader unless it also
    goes through the helper, which the two `callAssist(` checks below require.
    """
    body = re.sub(r"/\*.*?\*/", "", EDITOR, flags=re.DOTALL)
    bad = [
        i for i, line in enumerate(body.splitlines(), 1)
        if re.search(r"throw new Error\(\s*'HTTP ' \+ res\.status", line)
    ]
    assert not bad, f"editor.js:{bad}: throws away the server's error message"

    for path in ("/assist/' + encodeURIComponent(sectionKey)", "/assist/answer"):
        assert path in EDITOR, f"the AI flow no longer calls {path}"

    # Each AI endpoint is reached through the shared helper, exactly once each.
    assert EDITOR.count("await callAssist(") == 2, (
        "the two AI calls no longer both go through callAssist, so one of them "
        "has lost its waiting state, timeout and error message"
    )
    assert "await explainFailure(res)" in EDITOR, "editor.js lost the body reader"
    # The reader itself now lives in failures.js so app.js and editor.js cannot
    # report the same 422 two different ways. tests/test_failures.py drives that
    # module and asserts the single definition; this is only the wiring.
    assert "global.Failures.explainFailure" in EDITOR, (
        "editor.js does not take the shared body reader from failures.js"
    )
    assert "window.Failures.explainFailure" in APP, (
        "app.js does not take the shared body reader from failures.js"
    )


def test_a_slow_ai_call_has_a_waiting_state_and_a_timeout() -> None:
    """A call that takes 80 seconds must not look like a frozen dialog.

    The last real run took 80 seconds and spent three provider calls, because a
    truncated reply makes the server retry with a bigger token allowance. Nothing
    on screen said so. `callAssist` therefore shows a visible wait line, arms an
    AbortController, and on timeout says what happened rather than hanging.
    """
    assert "async function callAssist(" in EDITOR, "editor.js lost callAssist"
    assert "const AI_TIMEOUT_MS" in EDITOR, "the client has no timeout constant"

    # History.push stringifies what it is given. A caller that stringifies first
    # therefore snapshots a *string*, and undo then restores that string's
    # characters as keys -- every section vanishes on the first refused write.
    # It happened silently for every rejected write until a refused date exposed
    # it, which is why this is pinned by name rather than left to review.
    for src, name in ((EDITOR, "editor.js"), (MODEL, "editor-model.js")):
        bad = re.search(r"history\.push\(\s*JSON\.stringify\(", src)
        assert bad is None, (
            f"{name} pushes an already-stringified profile into History.push, "
            "so a rollback restores a string's characters instead of the profile"
        )

    body = re.sub(r"/\*.*?\*/", "", EDITOR, flags=re.DOTALL)
    start = body.index("async function callAssist(")
    call = body[start:start + 3000]

    assert "AbortController" in call, "callAssist never aborts"
    assert "AI_TIMEOUT_MS" in call, "callAssist never arms the timeout"
    assert "setTimeout" in call, "callAssist never schedules the abort"
    assert "ai-waiting" in call, "callAssist shows no waiting state"
    # The timeout path must say the request was sent and nothing was saved,
    # rather than reporting a bare network error.
    assert "timedOut" in call, "callAssist cannot tell a timeout from other errors"
    assert "nothing was saved" in call, "the timeout message is not actionable"

    # The timeout must outlast the server's own, or we abort requests the server
    # is still legitimately working on.
    client_ms = re.search(r"AI_TIMEOUT_MS\s*=\s*(\d+)", EDITOR)
    assert client_ms, "AI_TIMEOUT_MS is not a literal number of milliseconds"
    config_src = (STATIC.parent / "config.py").read_text(encoding="utf-8")
    server_s = re.search(r"llm_timeout_seconds\s*:\s*\S+\s*=\s*([\d.]+)", config_src)
    assert server_s, "app/config.py lost llm_timeout_seconds"
    assert float(server_s.group(1)) * 1000 < int(client_ms.group(1)), (
        f"the client gives up at {client_ms.group(1)}ms but the server still "
        f"tries until {server_s.group(1)}s, plus its own retries"
    )


def test_a_write_only_redraws_the_section_when_it_asks_to() -> None:
    """Typing must not take the caret away.

    Rebuilding the section replaces the input element, so the browser drops the
    caret onto the body and the next keystroke lands nowhere. Every text field
    used to lose focus after one character -- a word cost one click per letter.

    The cause was `if (redraw !== false)`: a flag nobody passed counted as "yes,
    rebuild", and the only callback that passed one was the list-entry field.
    So the default is now opt-in, and this asserts both halves that make that
    safe: the guard cannot be loosened back, and every call site which changes
    the *shape* of a section asks for its rebuild on purpose.
    """
    body = re.sub(r"/\*.*?\*/", "", EDITOR, flags=re.DOTALL)

    # The guard itself.
    guard = re.search(r"function applyFn\(([^)]*)\)\s*\{(.*?)\n\}", body, re.DOTALL)
    assert guard, "editor.js lost applyFn"
    assert re.search(r"redrawOk\s*===\s*true", guard.group(2)), (
        "applyFn rebuilds unless a caller positively asked: `redrawOk !== false` "
        "means every write that forgets the flag destroys the input being typed "
        "into, and the caret with it"
    )
    assert not re.search(r"redrawOk\s*!==\s*false", guard.group(2)), (
        "applyFn is back to treating a missing flag as permission to rebuild"
    )

    # The text path can only rebuild on an explicit commit.
    setter = re.search(r"function apply\(([^)]*)\)\s*\{(.*?)\n\}", body, re.DOTALL)
    assert setter, "editor.js lost apply"
    assert "done === true" in setter.group(2), (
        "apply forwards a bare `done`, so a text field that drops the argument "
        "hands applyFn an undefined flag and loses the caret"
    )

    # Every structural write asks, rather than relying on the old default. These
    # are the ones that add or remove a row: if they stop redrawing, the change
    # is invisible until the section is reopened.
    structural = {
        "'bullet'": "adding a bullet",
        "M.setItem": "editing a list item",
        "M.removeItem": "removing a list item",
        "M.updateLink": "editing a link",
        "M.removeLink": "removing a link",
        "M.addLink": "adding a link",
    }

    def apply_fn_calls(src: str) -> list[str]:
        """Every applyFn(...) call, matched by paren depth so that arguments
        containing their own calls are not cut short at the first ')'. A regex
        that stops at the first paren reports a `, true` two characters further
        on as missing, which is the shape of a bug it would invent."""
        found = []
        for m in re.finditer(r"applyFn\(", src):
            depth = 0
            for i in range(m.end() - 1, len(src)):
                if src[i] == "(":
                    depth += 1
                elif src[i] == ")":
                    depth -= 1
                    if depth == 0:
                        found.append(src[m.start():i + 1])
                        break
        return found

    for needle, what in structural.items():
        hits = [c for c in apply_fn_calls(body) if needle in c]
        assert hits, f"the {what} call to applyFn has gone; the test needs updating"
        for call in hits:
            assert re.search(r",\s*true\s*\)\s*$", call), (
                f"{what} calls applyFn without asking for a rebuild, so the row "
                "it changed will not appear until the section is reopened"
            )

    # And the date box still rebuilds on commit, which is the one text write
    # that legitimately replaces what was typed with the stored form.
    assert "input.addEventListener('change', () => onInput(input.value, true))" in body, (
        "a date field no longer commits on blur, so a half-typed date is never "
        "reported and the stored form is never shown"
    )


def test_the_harness_page_loads_the_same_scripts_as_the_app() -> None:
    """tools/_verify.html is a third copy of the page's script list.

    Adding a script to index.html and not to the harness page boots fine in the
    app and dies in the harness -- or, worse, boots fine in the app and the
    harness quietly skips the check that would have caught the bug it was
    written for. That is how failures.js went missing from the harness run and
    the first symptom was `boot never completed`, which says nothing about the
    script list being wrong.
    """
    harness = (STATIC.parent.parent / "tools" / "_verify.html").read_text(
        encoding="utf-8")

    def app_scripts(src: str) -> list[str]:
        found = re.findall(r'src="(/static/win/[^"]+)"', src)
        return [f[len("/static/win/"):] for f in found]

    assert app_scripts(harness) == app_scripts(HTML), (
        "the harness page and the app load different scripts: "
        f"harness {app_scripts(harness)} vs app {app_scripts(HTML)}"
    )


def test_the_wait_state_is_announced_and_animation_is_optional() -> None:
    """A blinking icon is not feedback on its own; the words are."""
    assert "ai-waiting-text" in EDITOR, "the wait line has no text"
    css = CSS
    assert ".ai-waiting" in css, "win95.css has no .ai-waiting rule"
    assert "prefers-reduced-motion" in css, (
        "the wait animation ignores prefers-reduced-motion"
    )


def test_every_front_end_script_is_loaded_in_order() -> None:
    """shell, then sample and model, then failures, then the form, then the app
    that opens it. Getting this wrong is a ReferenceError at boot, and both
    editor.js and app.js read Failures at load time rather than lazily."""
    order = ["shell.js", "sample.js", "editor-model.js", "failures.js",
             "editor.js", "app.js"]
    positions = []
    for name in order:
        tag = f'src="/static/win/{name}"'
        assert tag in HTML, f"{name} is not loaded by index.html"
        positions.append(HTML.index(tag))
    assert positions == sorted(positions), f"loaded out of order: {order}"


def test_the_editor_form_only_talks_to_the_model() -> None:
    """The split is the whole point: rules in the model, drawing in the form.
    If the form starts building profile shapes itself, the two drift."""
    assert "EditorModel" in EDITOR
    assert "M.setField" in EDITOR
    assert "M.addEntry" in EDITOR
    assert "M.removeEntry" in EDITOR
    assert "M.moveEntry" in EDITOR
    assert "M.validate" in EDITOR
    # And it must not hand-roll the shapes the model exists to guarantee.
    for forbidden in ("raw_facts", "Object.assign({}, BULLET",
                      "grade: { value:", "bullets: ['"):
        assert forbidden not in EDITOR, f"the form is building {forbidden} itself"


def test_the_form_adopts_a_reloaded_profile() -> None:
    """Regression, caught by screenshotting.

    app.js and editor.js each hold a reference to the profile, and the app
    reloads it from the server on every boot. The form kept the empty object it
    had been opened with, so the window said "My Resume - Anon" while
    every section read as empty. The form's refresh must take the new object.
    """
    body = EDITOR.split("function refresh(", 1)[1][:600]
    assert "newProfile" in body, "refresh must be able to accept a new profile"
    assert "state.profile = newProfile" in body, (
        "and must actually adopt it, or the form shows stale data"
    )
    # Every caller must pass it.
    for call in re.findall(r"EditorForm\.refresh\([^)]*\)", APP):
        assert "state.profile" in call, f"refresh called without the profile: {call}"
    # And the title must come from the form, not be written behind its back.
    assert "titleBase()" in EDITOR


def test_read_only_fields_do_not_look_editable() -> None:
    """The contact links box looked like a field, accepted typing, and discarded
    it. Silently dropping what someone typed is worse than not offering the box.

    There is no longer a box at all: links are rows with a real Edit and a real
    Remove. That is a stronger answer to the same complaint, so the test now
    asserts the box is gone rather than that it is read-only."""
    body = EDITOR.split("if (spec.kind === 'contact')", 1)[1][:1400]
    assert "renderLinks(host, 'Links'" in body, (
        "contact links must be rendered as a list of rows"
    )
    assert "readOnly" not in body, (
        "a read-only links field is the shape this replaced"
    )
    links = EDITOR.split("function renderLinks(", 1)[1][:2600]
    assert "'Edit this link'" in links, "each link row must offer an edit"
    assert "'Remove this link'" in links, "each link row must offer a remove"
    assert "askLink(" in links, "adding and editing must use the two-box dialog"


def test_escape_can_dismiss_a_modal_dialog() -> None:
    """The user must always have a way out of a modal."""
    handler = SHELL.split("document.addEventListener('keydown'", 1)[1][:900]
    assert "rec.dialog" in handler, "Escape must target the dialog"
    assert "close(rec.id)" in handler


def test_a_message_box_does_not_veto_its_own_close() -> None:
    """onClose used to return false, which made Escape resolve the promise but
    leave the dialog and the modal veil on screen -- a trap, because a Win95
    modal has no close box either."""
    body = SHELL.split("function messageBox(", 1)[1][:2400]
    on_close = body.split("onClose:", 1)[1].split("}),", 1)[0]
    assert "return true" in on_close, "the close must be allowed to proceed"
    assert "return false" not in on_close
    # One exit point, shared by the buttons and by Escape.
    assert "const finish = (value)" in body
    assert "finish(label)" in body, "the buttons must go through it"


def test_icons_contribute_no_characters_to_the_dom() -> None:
    """Regression. The ? and i icons were drawn with <text>, and an SVG text
    node becomes part of its ancestors' textContent -- so the Read Me desktop
    icon announced itself as "?Read Me" to a screen reader, and any lookup by
    label matched "?Read Me"."""
    icons = SHELL.split("const ICONS = {", 1)[1].split("\n};", 1)[0]
    # Strip comments first: the note explaining WHY there are no text nodes
    # necessarily mentions <text>, and a comment is not a DOM node.
    icons = re.sub(r"/\*.*?\*/", "", icons, flags=re.DOTALL)
    icons = re.sub(r"(?<!:)//[^\n]*", "", icons)
    assert "<text" not in icons, "an icon must contain no text nodes"
    for name in ("help", "info"):
        entry = icons.split(name + ":", 1)[1].split("\n  ", 1)[0]
        assert ">" not in entry.replace("/>", ""), \
            f"the {name} icon contains a text node"


def test_the_preview_link_is_set_as_an_attribute() -> None:
    """Assigning a.href reads it back resolved against the document, so the
    handler stored the page URL instead of the blob and the fallback link pointed
    back at the app."""
    body = APP.split("async function refreshPreview(", 1)[1][:2600]
    assert "openLink.setAttribute('href', url)" in body
    assert "openLink.href = url" not in body


def test_the_profile_is_never_cached() -> None:
    """A resume is a name, an email and a phone number. Exports and previews
    were already no-store; GET /profile was not, so it could be left in a disk
    cache or a shared proxy. Swept for rather than assumed."""
    profile = {"contact": {"name": "Anon", "email": "anon@example.com",
                           "phone": "+91 98765 43210"}}
    with TestClient(app) as c:
        c.put("/profile", json=profile)
        r = c.get("/profile")
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-store"


def css_block(css: str, selector: str) -> str:
    """The rule for one selector, braces included."""
    i = css.index(selector + " {")
    return css[i:css.index("}", i)]


def test_a_modal_dialog_stacks_above_its_own_veil() -> None:
    """Regression, and the worst one yet: clicking Sample Resume froze the
    entire desktop.

    The veil sat at z-index 900 while windows stacked from 20, so every modal
    dialog rendered *underneath* the thing meant to dim it -- visible through 18%
    black and completely unclickable, because a full-screen div was swallowing
    every click aimed at it. The taskbar and Start menu were above the veil,
    which is why the Start menu still opened while no window responded.

    It survived 435 passing tests because nothing asked what was under the
    cursor. Escape still worked, so the synthetic key event the harness
    dispatched never touched the veil.
    """
    veil_z = int(re.search(r"z-index:\s*(\d+)", css_block(CSS, "#veil")).group(1))
    assert veil_z > 0

    # The shell names the same numbers, so the two files cannot drift apart.
    assert f"const Z_VEIL = {veil_z};" in SHELL, (
        "the stylesheet's veil z-index and the shell's Z_VEIL disagree"
    )
    modal_z = int(re.search(r"const Z_MODAL = (\d+)", SHELL).group(1))
    assert modal_z > veil_z, "a modal must clear the veil it raises"

    # And focusWindow must apply it, not merely define it.
    focus = SHELL.split("function focusWindow(", 1)[1][:700]
    assert "Z_MODAL" in focus, "focusWindow never raises a modal above the veil"
    assert "rec.modal" in focus

    # Nothing may sit between the veil and a modal.
    every = {int(z) for z in re.findall(r"z-index:\s*(\d+);", CSS)}
    between = sorted(z for z in every if veil_z < z < modal_z)
    assert not between, f"something is layered over a modal: {between}"


def test_the_taskbar_and_start_menu_stay_above_a_modal() -> None:
    """They must stay usable while a dialog is up -- which is also why the freeze
    was so confusing: the Start menu opened and nothing else did."""
    modal_z = int(re.search(r"const Z_MODAL = (\d+)", SHELL).group(1))
    for anchor in ("#taskbar", "#startMenu"):
        block = css_block(CSS, anchor)
        z = int(re.search(r"z-index:\s*(\d+)", block).group(1))
        assert z > modal_z, f"{anchor} must stay above a modal, got {z}"


def test_the_veil_never_swallows_a_click() -> None:
    """The veil exists to dim the desktop, not to catch the pointer. Were it
    above a dialog again the failure would be silent: the app would look alive
    and respond to nothing."""
    assert "pointer-events" not in css_block(CSS, "#veil")


def test_the_opening_animation_never_owns_the_resting_state() -> None:
    """Regression. `createWindow` added the `opening` class and removed it on
    `animationend` alone. animationend does not fire when an animation is
    cancelled, when the tab is backgrounded, or when prefers-reduced-motion sets
    `animation: none` -- and a stuck `opening` class means opacity 0, so the
    window is present, focusable and completely invisible.

    `close()` already had a timeout fallback for exactly this reason; the open
    path did not, which is why one was found by looking and the other was not.
    """
    body = SHELL.split("function createWindow(", 1)[1][:12000]
    assert "win.classList.add('opening')" in body
    assert "animationend" in body
    assert "setTimeout(opened" in body, (
        "the opening class needs a timeout fallback, not only animationend"
    )
    # The closing path must keep its own fallback.
    assert "setTimeout(() => { if (rec.el.parentNode) done(); }" in SHELL


def test_a_window_paints_its_own_face() -> None:
    """A dialog must be opaque. Checked in the browser harness by hit-testing the
    middle of one, but the invariant belongs here too: a window that shows what
    is behind it looks broken even when it behaves."""
    face = css_block(CSS, ".win")
    assert "background: var(--face)" in face
    assert "transparent" not in face


def test_nothing_loads_from_the_network() -> None:
    for banned in ("@import", "fonts.googleapis", "http://", "https://", "url("):
        assert banned not in CSS, f"win95.css reaches outside via {banned}"
    assert "http://" not in HTML.replace("http://www.w3.org", "")