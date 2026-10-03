"""Stage 3: the terminal UI.

Mostly static analysis. These tests exist to lock in properties that are easy to
break by accident and hard to notice: no innerHTML, no eval, no mouse handlers,
no inline script/style, and a CSP that actually permits the page while keeping
the API locked down.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

STATIC = "app/static"
JS = f"{STATIC}/app.js"
CSS = f"{STATIC}/term.css"
HTML = f"{STATIC}/index.html"


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
    return read(JS)


@pytest.fixture(scope="module")
def js_code() -> str:
    """app.js with comments removed — what actually executes."""
    return strip_js_comments(read(JS))


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
    assert 'href="/static/term.css"' in html
    assert 'src="/static/app.js"' in html
    assert "cdn." not in html and "http://" not in html.replace("http://www.w3.org", "")


def test_no_external_font_or_script_dependency() -> None:
    """Font stack must be local; a CDN would break the offline-first property."""
    assert "@import" not in read(CSS)
    assert "fonts.googleapis" not in read(CSS)
    assert "cdn" not in read(CSS)


# --- mouse policy ---------------------------------------------------------


def test_no_mouse_handlers_beyond_the_agreed_chrome(js_code: str) -> None:
    """No onclick attributes and no hover/down handlers, anywhere.

    Exactly three click listeners are allowed, and they are the deliberate
    boundary agreed for this UI:
      1. navbar section buttons -> type `cd <section>` into the terminal
      2. #previewClose         -> close the preview pane
      3. #previewRefresh       -> re-render the preview
    The last two are window chrome mirroring the title bar in the reference
    image, and they are real <button>s so Enter and Space work too. Anything
    that edits the resume must go through a command.
    """
    for banned in ("onclick", "onmouseover", "onmousedown", "onmouseenter"):
        assert banned not in js_code, f"{banned} must not appear in app.js"

    all_listeners = re.findall(r"addEventListener\(\s*'([a-z]+)'", js_code)
    mouse = [e for e in all_listeners
             if e == "click" or e.startswith("mouse") or e.startswith("pointer")
             or e in ("dblclick", "contextmenu", "wheel")]

    # submit / keydown / error / unhandledrejection are exactly what we want too.
    for wanted in ("submit", "keydown", "error", "unhandledrejection"):
        assert wanted in all_listeners, f"missing {wanted} listener"

    assert mouse == ["click", "click", "click", "mouseup"], f"mouse listeners: {mouse}"

    assert "btn.addEventListener('click'" in js_code
    assert "previewClose').addEventListener('click'" in js_code
    assert "previewRefresh').addEventListener('click'" in js_code


def test_no_command_is_bound_directly_to_the_mouse(js_code: str) -> None:
    """A click may not call a COMMANDS.* handler directly.

    That is the rule that keeps the terminal the single interface: the navbar
    must route through runTyped(), never straight into an action. The handler
    body sits on the lines after the registration, so inspect those too.
    """
    lines = js_code.splitlines()
    for i, line in enumerate(lines):
        if "addEventListener('click'" not in line:
            continue
        body = "\n".join(lines[i:i + 4])
        assert "runTyped" in body or "togglePreview" in body or "doPreview" in body, (
            f"click handler acts directly instead of typing a command: {line.strip()}"
        )
        assert "COMMANDS." not in body, (
            f"click handler reaches into COMMANDS directly: {line.strip()}"
        )


def test_navbar_uses_click_but_types_the_command(js: str) -> None:
    """The navbar may be buttons, but they must dispatch a command, not act."""
    assert "btn.addEventListener('click'" in js
    assert "runTyped(command)" in js


def test_navbar_offers_home_and_quick_actions(js: str) -> None:
    """Regression: the navbar had no home and nothing but section links."""
    assert "add('home', 'home'" in js
    for label in ("notes", "hint", "help", "preview"):
        assert f"add('{label}'" in js, f"navbar is missing {label}"
    assert "notesCount()" in js, "navbar should show how many notes exist"


def test_navbar_buttons_carry_their_command_as_a_title(js: str) -> None:
    """Hover text without a hover handler, so a mouse user can still read them."""
    assert "btn.title = command" in js


def test_mouseup_only_restores_focus(js_code: str) -> None:
    """A stray click must do nothing except return focus to the prompt."""
    assert js_code.count("mouseup") == 1
    assert "document.addEventListener('mouseup', () => el.input.focus())" in js_code


def test_text_stays_selectable() -> None:
    """Copying a bullet out with the mouse must keep working."""
    css = read(CSS)
    assert "user-select: text" in css
    assert "user-select: none" not in css


# --- themes ---------------------------------------------------------------


def test_four_themes_defined() -> None:
    css = read(CSS)
    for theme in ("amber", "green", "matrix", "paper"):
        assert f'html[data-theme="{theme}"]' in css


def test_terminal_font_stack_present() -> None:
    css = read(CSS)
    for face in ("JetBrains Mono", "Cascadia Code", "Menlo", "Monaco",
                 "DejaVu Sans Mono", "Consolas"):
        assert face in css, f"{face} missing from the font stack"


def test_theme_is_persisted() -> None:
    js = read(JS)
    assert "rb.theme" in js
    assert "localStorage" in js


def test_reduced_motion_is_respected() -> None:
    assert "prefers-reduced-motion" in read(CSS)


# --- reliability ----------------------------------------------------------


def test_global_error_boundary_present(js: str) -> None:
    """A thrown command must never kill the UI."""
    assert "window.addEventListener('error'" in js
    assert "window.addEventListener('unhandledrejection'" in js
    assert "runLineSafely" in js


def test_command_dispatch_is_wrapped(js: str) -> None:
    assert "try {" in js and "catch (err)" in js


def test_network_failure_is_handled(js: str) -> None:
    assert "cannot reach the server" in js
    assert "save failed" in js


def test_localstorage_is_guarded(js: str) -> None:
    """localStorage throws in private mode; boot must survive it."""
    store_block = js.split("const store =", 1)[1][:400]
    assert "try {" in store_block and "catch (_)" in store_block


def test_undo_stack_exists() -> None:
    js = read(JS)
    assert "MAX_UNDO" in js
    assert "snapshotForUndo" in js
    assert "COMMANDS.u = COMMANDS.undo" in js
    assert "ev.key === 'z' && ev.ctrlKey" in js


def test_tab_completion_exists() -> None:
    js = read(JS)
    assert "ev.key === 'Tab'" in js
    assert "candidatesFor" in js


def test_history_navigation_exists() -> None:
    js = read(JS)
    assert "ArrowUp" in js and "ArrowDown" in js


def test_typo_suggestions_exist() -> None:
    js = read(JS)
    assert "levenshtein" in js
    assert "did you mean" in js


def test_accessibility_affordances() -> None:
    html = read(HTML)
    assert 'aria-live="polite"' in html
    assert 'aria-label=' in html
    css = read(CSS)
    assert ":focus-visible" in css, "keyboard-only UI needs a visible focus ring"


# --- server side ----------------------------------------------------------


def test_root_serves_the_terminal() -> None:
    with TestClient(app) as c:
        r = c.get("/")
    assert r.status_code == 200
    assert "resume-builder" in r.text


def test_static_files_served() -> None:
    with TestClient(app) as c:
        assert c.get("/static/app.js").status_code == 200
        assert c.get("/static/term.css").status_code == 200


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
    """A frame the browser refuses must never be a silent blank rectangle."""
    html = read(HTML)
    assert 'id="previewFallback"' in html
    assert 'id="previewOpen"' in html
    js = read(JS)
    assert "previewOpen.href = url" in js
    assert "el.previewFallback.hidden = false" in js


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
    for later in ("/assist/{section}", "/jd/analyze", "/tailor", "/applications"):
        assert later not in paths, f"{later} belongs to a later stage"
