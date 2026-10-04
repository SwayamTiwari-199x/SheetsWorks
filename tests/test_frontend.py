"""Static analysis of the shipped front end.

Mostly greps over the JavaScript and CSS. These tests lock in properties that
are easy to break by accident and hard to notice: no innerHTML, no eval, no
inline script or style, no remote assets, and a CSP that actually permits the
page while keeping the API locked down.

They used to cover BOTH front ends, because both were in the tree: the shipped
Windows 95 desktop, and the archived terminal page. The terminal has now been
deleted along with its own tests, so there is one front end and these cover it.
That matters because the two pages disagreed about several of these properties,
and the disagreements were the interesting part.
"""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

STATIC = "app/static"

# The shipped front end -- which is now all of it.
JS = f"{STATIC}/win/shell.js"
APP_JS = f"{STATIC}/win/app.js"
CSS = f"{STATIC}/win/win95.css"
HTML = f"{STATIC}/index.html"

MODEL_JS = f"{STATIC}/win/editor-model.js"
EDITOR_JS = f"{STATIC}/win/editor.js"
SAMPLE_JS = f"{STATIC}/win/sample.js"

# The archived terminal page (terminal.html, old-app.js, old-term.css,
# old-site.css) has been deleted. These two tuples used to include it, which
# meant the no-innerHTML and no-eval sweeps covered two pages; they now cover the
# one that ships.
ALL_JS = (JS, APP_JS, MODEL_JS, EDITOR_JS, SAMPLE_JS)
ALL_CSS = (CSS,)


def test_the_archived_terminal_is_gone() -> None:
    """The terminal UI and its tests were removed once the Windows 95 desktop
    replaced it.

    Kept as a check rather than left implicit, because these files used to be
    load-bearing in three places (a served page, the XSS sweeps, and a 90-test
    file) and "nothing references them any more" is exactly the kind of claim
    that rots the moment someone adds a fifth reference.
    """
    for name in ("terminal.html", "old-app.js", "old-term.css", "old-site.css"):
        assert not os.path.exists(f"{STATIC}/win/{name}"), (
            f"{name} was archived, not deleted"
        )
    assert not os.path.exists(
        os.path.join(os.path.dirname(__file__), "test_terminal_flow.py")
    ), "the terminal flow tests should have gone with the terminal"


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def strip_js_comments(source: str) -> str:
    """Remove comments so documentation of a banned name does not trip a grep.

    Deliberately not a full parser: it only has to be good enough that
    'innerHTML' in a comment is not mistaken for a call to it.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    # drop // comments, but not the // inside a URL such as https://
    return re.sub(r"(?<!:)//[^\n]*", "", source)


@pytest.fixture(scope="module")
def js() -> str:
    return "\n".join(read(p) for p in (JS, APP_JS, MODEL_JS, EDITOR_JS, SAMPLE_JS))


@pytest.fixture(scope="module")
def js_code() -> str:
    """Every shipped script with comments removed — what actually executes."""
    return "\n".join(strip_js_comments(read(p)) for p in ALL_JS)


# --- XSS posture ----------------------------------------------------------


def test_no_innerhtml_anywhere(js_code: str) -> None:
    """The terminal echoes user input and server output; innerHTML would be XSS."""
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert banned not in js_code, f"{banned} must not appear in app.js"


def test_no_eval_or_function_constructor(js_code: str) -> None:
    for banned in ("eval(", "new Function"):
        assert banned not in js_code, f"{banned} must not appear in app.js"


def test_no_inline_script_or_style_in_html() -> None:
    html = read(HTML)
    assert "<style" not in html
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handler in HTML"
    assert "<script>" not in html, "inline script block in HTML"


def test_html_uses_external_assets_only() -> None:
    html = read(HTML)
    assert 'href="/static/win/win95.css"' in html
    assert 'src="/static/win/shell.js"' in html
    assert 'src="/static/win/app.js"' in html
    assert "cdn." not in html and "http://" not in html.replace("http://www.w3.org", "")


def test_no_external_font_or_script_dependency() -> None:
    """Font stack must be local; a CDN would break the offline-first property."""
    for css_path in ALL_CSS:
        css = read(css_path)
        assert "@import" not in css, css_path
        assert "fonts.googleapis" not in css, css_path
        assert "cdn" not in css, css_path


# --- mouse policy ---------------------------------------------------------
# The terminal era forbade the mouse and every control had to type a command.
# This UI is a mouse UI, so the rule inverted: the pointer is the primary input
# and the desktop has to feel solid under it. What is still banned is the
# HTML-level shortcut, because an onclick attribute bypasses the listeners that
# can actually be audited.


def test_no_inline_event_handlers_in_javascript_either(js_code: str) -> None:
    """No element.onclick = anywhere; every handler is addEventListener."""
    assert not re.search(r"\.onclick\s*=", js_code)
    assert not re.search(r"\.onmousedown\s*=", js_code)


def test_the_desktop_listens_for_the_events_a_desktop_needs(js_code: str) -> None:
    """Drag, click, double-click and keyboard. A window manager with no
    mousedown/mousemove cannot be dragged at all."""
    listeners = re.findall(r"addEventListener\(\s*'([a-z]+)'", js_code)
    for wanted in ("click", "mousedown", "mousemove", "mouseup",
                   "dblclick", "keydown", "error", "unhandledrejection"):
        assert wanted in listeners, f"missing {wanted} listener"
    # No hover-driven behaviour: 1995 had tooltips, not hover states, and a
    # hover-only affordance cannot be reached from the keyboard.
    for banned in ("mouseover", "mouseenter", "contextmenu"):
        assert banned not in listeners, f"{banned} should not be used"


def test_dragging_is_measured_from_the_pointer(js_code: str) -> None:
    """A window that jumps to the cursor on grab feels broken. The drag must
    record where the pointer went down and apply the delta from there."""
    assert "startX" in js_code and "startY" in js_code
    assert "e.clientX - startX" in js_code
    assert "e.clientY - startY" in js_code


def test_drag_listeners_are_released(js_code: str) -> None:
    """A mousemove listener left attached makes a window follow the pointer
    forever. Both the drag and the resize must clean up on mouseup."""
    assert js_code.count("removeEventListener('mousemove'") >= 2
    assert js_code.count("removeEventListener('mouseup'") >= 2


def test_windows_cannot_be_dragged_out_of_reach(js_code: str) -> None:
    """A title bar may go under the taskbar, but enough of the window must stay
    on screen to be grabbed again."""
    assert "maxX" in js_code and "maxY" in js_code
    assert "-w + 60" in js_code


def test_focus_is_visible() -> None:
    """A keyboard user must be able to see where they are."""
    assert ":focus-visible" in read(CSS)


def test_text_stays_selectable_where_it_matters() -> None:
    """Resume text must be copyable. Chrome opting out of selection is fine --
    that is what a window frame is for -- but the list boxes holding your words
    must not."""
    css = read(CSS)
    assert "user-select: none" in css, "the chrome should opt out of selection"
    for selectable in (".listbox", ".field"):
        block = css.split(selectable, 1)[1].split("}", 1)[0]
        assert "user-select: text" in block, f"{selectable} must stay selectable"


# --- look and feel --------------------------------------------------------


def test_the_system_colours_are_defined() -> None:
    """Win95's chrome is a fixed palette. Miss any of these and the bevels
    collapse, taking the whole illusion with them."""
    css = read(CSS)
    for token in ("--face", "--hilite", "--light", "--shadow", "--dark",
                  "--teal", "--title-a", "--title-b", "--sel-bg"):
        assert token in css, f"{token} missing from the palette"


def test_both_bevel_directions_are_defined() -> None:
    """Raised for chrome, sunken for anything you type into or read as a well.
    Both are needed; either one alone does not look like Windows."""
    css = read(CSS)
    for token in ("--bevel-out", "--bevel-in", "--bevel-out-thin", "--bevel-in-thin"):
        assert token in css, f"{token} missing"


def test_buttons_press_rather_than_merely_changing_colour() -> None:
    """The 1px content shift on :active is the entire reason a 1995 button
    feels pressed. A colour change alone does not read as a press."""
    css = read(CSS)
    active = css.split(".btn:active", 1)[1].split("}", 1)[0]
    assert "bevel-in" in active, "a pressed button must invert its bevel"
    assert "padding" in active, "a pressed button must shift its content by 1px"


def test_the_chunky_scrollbar_is_styled() -> None:
    """16px arrows and a checkerboard track. The default scrollbar is the
    fastest way to make a period piece look like 2026."""
    css = read(CSS)
    assert "::-webkit-scrollbar" in css
    assert "width: 16px" in css
    assert "linear-gradient(45deg" in css, "the checkerboard track is missing"


def test_the_type_is_the_windows_stack() -> None:
    """Tahoma is the closest metric match to MS Sans Serif and ships with
    Windows. Nothing may be downloaded."""
    css = read(CSS)
    assert "Tahoma" in css
    assert "'MS Sans Serif'" in css
    assert "Fixedsys" in css, "the DOS-era face is part of the look"
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert "@font-face" not in body, "no font may be embedded"


def test_the_desktop_and_taskbar_exist() -> None:
    css = read(CSS)
    for anchor in ("#desktop", "#taskbar", "#startMenu"):
        assert anchor in css, f"{anchor} missing"
    assert "--teal" in css, "the teal desktop is half the reference image"


def test_the_title_bar_gradient_is_defined() -> None:
    """An active title bar fades navy to blue; an inactive one goes grey. That
    fade is what tells you which window has focus at a glance."""
    css = read(CSS)
    assert "linear-gradient(90deg, var(--title-a), var(--title-b))" in css
    assert 'data-active="false"' in css or "data-active" in css


def test_motion_is_declared_and_then_disabled() -> None:
    """The motion is an addition; reduced-motion must actually stop it."""
    css = read(CSS)
    assert "@keyframes win-open" in css
    assert "prefers-reduced-motion" in css
    reduced = css.split("prefers-reduced-motion", 1)[1]
    assert "animation: none" in reduced


# --- reliability ----------------------------------------------------------


def test_global_error_boundary_present(js: str) -> None:
    """A throw inside a window must never take the desktop down with it."""
    assert "window.addEventListener('error'" in js
    assert "window.addEventListener('unhandledrejection'" in js


def test_every_server_call_is_wrapped(js_code: str) -> None:
    """Anything that touches the network reports its own failure.

    A 1995 program that hung with no message was normal. This one must not: a
    failed save shows a dialog rather than silently discarding the edit.
    """
    assert "catch (err)" in js_code
    assert "async function working(" in js_code, "there must be one wrapper"
    body = js_code.split("async function working(", 1)[1][:900]
    assert "messageBox" in body, "a failure must surface as a dialog"
    assert "finally" in body, "the busy state must always be cleared"


def test_a_failed_request_cannot_strand_the_busy_state(js_code: str) -> None:
    """The hourglass and the status bar are set together and must be cleared
    together, or one failed request leaves the app permanently 'busy'."""
    assert "W.setBusy(winId, true" in js_code
    assert "W.setBusy(winId, false" in js_code


def test_localstorage_is_guarded(js: str) -> None:
    """localStorage throws in private mode; boot must survive it."""
    store_block = js.split("const store =", 1)[1][:400]
    assert "try {" in store_block and "catch (_)" in store_block


def test_the_desktop_is_announced_to_assistive_tech() -> None:
    """Windows are regions, the Start menu is a menu, and the tray is a live
    region -- otherwise a screen reader has no idea what any of it is."""
    js = read(APP_JS) + read(EDITOR_JS) + read(JS)
    html = read(HTML)
    assert "setAttribute('role'" in js, "windows and controls must declare a role"
    assert 'aria-label' in js, "windows must announce themselves"
    assert 'aria-label="Start menu"' in html
    assert 'aria-haspopup="true"' in html
    assert 'aria-expanded="false"' in html


def test_windows_are_labelled_and_their_state_exposed() -> None:
    """A window must announce its title and whether it has focus, which is how
    the active-window styling is exposed rather than only drawn."""
    js = read(JS)
    assert "'aria-label'" in js or "aria-label" in js
    assert "data-active" in js
    assert "setAttribute('role'" in js


def test_every_icon_button_carries_an_accessible_name() -> None:
    """Icon-only buttons are unusable with a screen reader unless labelled."""
    js = read(JS)
    assert "aria-label" in js
    assert js.count("setAttribute('aria-label'") >= 3


def test_keyboard_shortcuts_exist(js: str) -> None:
    """Escape closes, Alt+letter opens a menu, and Windows or Ctrl+Escape opens
    Start. A desktop with no keyboard route is a desktop for mice only."""
    assert "ev.key === 'Escape'" in js
    assert "ev.altKey" in js
    assert "Meta" in js
    # Menus and Start items must be reachable, so they carry a tabindex.
    assert "setAttribute('tabindex'" in js


# --- the shell's own contract ---------------------------------------------


def test_one_window_per_application_is_reused(js: str) -> None:
    """Opening "My Resume" twice must raise the existing window, not stack two
    copies of the same form on top of each other."""
    assert "const open = new Map()" in js
    assert "W.restore(id)" in js


def test_the_modal_veil_follows_the_modal_windows(js: str) -> None:
    """A dialog dims the desktop only while it is actually on screen."""
    assert "function syncVeil()" in js
    body = js.split("function syncVeil()", 1)[1][:400]
    assert "!r.minimised" in body, "a minimised modal must not dim anything"
    assert "veil" in js


def test_window_close_can_be_vetoed(js: str) -> None:
    """The unsaved-changes prompt needs a way to say no."""
    assert "rec.onClose()" in js
    assert "=== false" in js, "returning false must cancel the close"


def test_focus_and_z_order_are_managed_together(js: str) -> None:
    """The focused window must be the topmost one, or clicking a background
    window appears to do nothing."""
    body = js.split("function focusWindow(", 1)[1][:600]
    assert "zTop" in body
    assert "data-active" in body
    assert "topmostVisible" in js, "focus must fall to the next visible window"


def test_maximise_restores_the_previous_geometry(js: str) -> None:
    """A maximise button that cannot be undone is a trap."""
    body = js.split("function toggleMax(", 1)[1][:900]
    assert "rec.restore" in body
    assert "rec.maximised = false" in body


def test_close_survives_motion_being_disabled(js: str) -> None:
    """Close waits for animationend, which never fires under reduced motion, so
    there must be a fallback or windows cannot be closed at all."""
    body = js.split("function close(", 1)[1][:900]
    assert "setTimeout" in body, "a fallback path is required"


# --- server side ----------------------------------------------------------


def test_root_serves_the_desktop() -> None:
    with TestClient(app) as c:
        r = c.get("/")
    assert r.status_code == 200
    assert "Sheetsworks" in r.text
    assert 'id="desktop"' in r.text and 'id="taskbar"' in r.text


def test_static_files_served() -> None:
    with TestClient(app) as c:
        for asset in ("/static/win/win95.css", "/static/win/shell.js",
                      "/static/win/app.js"):
            assert c.get(asset).status_code == 200, asset
        # The archived terminal used to be asserted 200 here. It is deleted now,
        # and test_the_archived_terminal_is_gone checks that it stays deleted --
        # which is a stronger statement than "it is still served".
        assert c.get("/static/win/terminal.html").status_code == 404


def test_page_csp_allows_the_preview_blob_frame() -> None:
    """Regression: the preview pane rendered as a blank white box.

    The iframe is fed a blob: URL. CSP 'self' matches on scheme+host+port, so a
    blob: frame was blocked outright and the browser reported nothing visible.
    """
    with TestClient(app) as c:
        csp = c.get("/").headers["content-security-policy"]
    assert "frame-src 'self' blob:" in csp
    assert "object-src 'none'" in csp


def test_preview_pane_has_a_visible_fallback() -> None:
    """A frame the browser refuses must never be a silent blank rectangle.

    The fallback lives in the Preview window's script now rather than in the
    markup, because the window is built at runtime. The guarantee is what
    matters, not which file spells it.
    """
    app_js = read(APP_JS)
    assert "previewFallback" in app_js
    assert "previewOpen" in app_js
    assert "openLink.setAttribute('href', url)" in app_js
    assert "showFallback(fallback, true)" in app_js, (
        "a failed preview must say so rather than showing an empty frame"
    )


def test_the_fallback_is_hidden_by_display_not_by_the_hidden_property() -> None:
    """Regression, and the reason `hidden` is not used on its own anywhere here.

    `hidden` contributes only a user-agent-level `[hidden] { display: none }`
    rule. The fallback panel needs an inline `display:flex` to centre its
    message, and an inline declaration outranks the UA stylesheet. So the panel
    stayed painted on top of the PDF at all times, and every preview in the app
    showed "The preview could not be shown in place" instead of the resume.

    Nothing caught it because `element.hidden === true` was true the whole time:
    the property said hidden and the pixels said otherwise.
    """
    app_js = read(APP_JS)
    helper = app_js.split("function showFallback(", 1)[1][:600]
    assert "node.style.display" in helper, (
        "hiding must move `display`, which is what actually gets painted"
    )
    # Setting `hidden` alone anywhere near this panel brings the bug straight
    # back, so forbid it.
    body = app_js.split("function refreshPreview(", 1)[1][:2400]
    assert "fallback.hidden" not in body, (
        "do not set `.hidden` on the fallback -- it does not hide it"
    )
    assert "showFallback(fallback, false)" in body, (
        "a successful render must hide the panel by display"
    )
    assert "showFallback(fallback, true)" in body, (
        "a failed render must show it"
    )


def test_page_gets_a_csp_that_allows_its_own_assets() -> None:
    """Regression: the API's default-src 'none' would have blanked the page."""
    with TestClient(app) as c:
        csp = c.get("/").headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp


def test_api_still_gets_the_locked_down_csp() -> None:
    with TestClient(app) as c:
        csp = c.get("/health").headers["content-security-policy"]
    assert "default-src 'none'" in csp


def test_static_assets_get_the_page_csp() -> None:
    with TestClient(app) as c:
        csp = c.get("/static/app.js").headers["content-security-policy"]
    assert "default-src 'self'" in csp


def test_nosniff_on_everything() -> None:
    with TestClient(app) as c:
        for path in ("/", "/static/app.js", "/health", "/profile"):
            r = c.get(path)
            assert r.headers["x-content-type-options"] == "nosniff", path


def test_preview_renders_the_sent_profile() -> None:
    with TestClient(app) as c:
        r = c.post("/preview", json={
            "contact": {"name": "Dusht", "email": "a@b.com", "phone": "12345"},
            "summary": "Engineer.",
            "experience": [{
                "org": "PayFlow", "role": "Backend", "start": "2022-01", "end": "Present",
                "bullets": [{"raw_facts": "x", "text": "Cut latency by 40%."}],
            }],
        })
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    assert r.headers["X-Pages"] == "1"
    assert r.headers["Cache-Control"] == "no-store"


def test_preview_does_not_persist_anything() -> None:
    """Preview must be read-only: it renders the body, it does not save it."""
    with TestClient(app) as c:
        body = {"contact": {"name": "Ghost", "email": "g@b.com", "phone": "12345"}}
        c.post("/preview", json=body)
        assert c.get("/profile").status_code == 404


def test_preview_validates_like_the_rest_of_the_api() -> None:
    with TestClient(app) as c:
        assert c.post("/preview", json={}).status_code == 422
        assert c.post("/preview", json={"contact": {"name": "A", "email": "bad",
                                                    "phone": "1"}}).status_code == 422


def test_preview_rejects_invisible_characters() -> None:
    with TestClient(app) as c:
        r = c.post("/preview", json={"contact": {
            "name": "A\u202eB", "email": "a@b.com", "phone": "12345"}})
    assert r.status_code == 422


def test_export_still_requires_a_version() -> None:
    with TestClient(app) as c:
        assert c.post("/export/nope").status_code == 404


def test_route_set_grew_by_exactly_the_ui() -> None:
    with TestClient(app) as c:
        paths = set(c.get("/openapi.json").json()["paths"])
    assert "/preview" in paths
    assert "/profile" in paths
    assert "/export/{version_id}" in paths
    for later in ("/jd/analyze", "/tailor", "/applications"):
        assert later not in paths, f"{later} belongs to a later stage"
