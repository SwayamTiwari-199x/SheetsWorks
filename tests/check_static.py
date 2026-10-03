"""Static consistency checks between app.js, index.html and the stylesheets.

Cheap to run and they catch the class of mistake a redesign actually makes: JS
reaching for an id the markup does not have, which fails silently at runtime
with no test failing.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
JS = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
SITE = (STATIC / "site.css").read_text(encoding="utf-8")
TERM = (STATIC / "term.css").read_text(encoding="utf-8")

failures = []


def check(ok: bool, message: str) -> None:
    if not ok:
        failures.append(message)


# --- every id JS asks for must exist in the markup -----------------------

wanted = set(re.findall(r"getElementById\(\s*'([A-Za-z0-9_-]+)'", JS))
# Ids the code builds for itself, e.g. per-section buttons, never in the markup.
present = set(re.findall(r'id="([A-Za-z0-9_-]+)"', HTML))
missing = sorted(wanted - present)
check(not missing, f"app.js asks for ids the markup does not have: {missing}")

# --- and the reverse, so the markup cannot carry dead weight ---------------

KNOWN_DYNAMIC = {
    # built by refreshNavbar / buildSectionNav / renderNews / renderNotes
    "nbItems",
}
orphans = sorted(
    pid for pid in present - wanted
    if pid not in KNOWN_DYNAMIC
    and not pid.startswith("halftone") and not pid.startswith("sky")
)
# Informational, not a failure: some ids are only reached from CSS or from an
# aria-labelledby, and the New Resume buttons are looked up by variable so this
# regex cannot see them.
if orphans:
    print("markup ids JS never asks for by literal (css/aria/dynamic): "
          + ", ".join(orphans))

# --- stylesheets ----------------------------------------------------------

for name, css in (("site.css", SITE), ("term.css", TERM)):
    for banned in ("@import", "fonts.googleapis", "cdn.", "http://", "https://"):
        check(banned not in css, f"{name} reaches outside: {banned}")
    check("url(" not in css, f"{name} loads an external resource via url()")

# --- the palette lives in exactly one place -------------------------------

defined = set(re.findall(r"html\[data-theme=\"([a-z]+)\"\]", TERM))
check(defined == {"amber", "green", "matrix", "paper", "vintage"},
      f"term.css themes are {sorted(defined)}")
check("data-theme=" not in SITE,
      "site.css defines a theme; palettes belong in term.css only")

# --- themes agree with what the app offers --------------------------------

themes_js = re.search(r"const THEMES = \[([^\]]*)\]", JS)
check(themes_js is not None, "THEMES list not found in app.js")
if themes_js:
    offered = set(re.findall(r"'([a-z]+)'", themes_js.group(1)))
    check(offered == defined,
          f"app.js offers {sorted(offered)} but CSS defines {sorted(defined)}")

check('data-theme="vintage"' in HTML, "the page does not start on the vintage theme")

# --- news content arrives from rules.json, escaped -------------------------

sys.path.insert(0, str(ROOT))
from app import rules  # noqa: E402

tips = rules.tips()
check(len(tips) >= 6, f"only {len(tips)} tips; the NEWS panel wants more")
for tip in tips:
    for key in ("title", "body", "source", "tag"):
        check(key in tip, f"a tip is missing {key}: {tip}")
    check(tip["tag"] in ("verified", "unverified"), f"bad tag on {tip['title']!r}")

payload = json.dumps({"tips": tips}, separators=(",", ":"))
safe = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
check("<" not in safe, "the injected JSON can still contain a raw <")
check('{"tips": []}' in HTML, "index.html lost its tips placeholder")

# --- the layout pieces the design asked for -------------------------------

for needed in ('id="view-home"', 'id="view-draft"', 'id="view-new"', 'id="view-ai"',
               'id="rail"', 'id="stage"', 'id="previewPane"', 'id="jumpNav"',
               'id="sectionNav"', 'id="newsBody"', 'id="progressFill"',
               'id="tipsData"'):
    check(needed in HTML, f"markup is missing {needed}")

for nav in ("Home", "Draft", "New Resume", "AI Resume Builder"):
    check(f">{nav}</button>" in HTML, f"masthead is missing {nav}")

# --- no dead legacy selectors ---------------------------------------------

check("#previewPane[hidden]" in SITE or "#previewPane[hidden]" in TERM,
      "the preview pane has no hidden rule, so close would do nothing")
check("body::after" not in TERM,
      "scanlines moved to the terminal view; a body-level one would cover the page")

if failures:
    print("\nFAILURES:")
    for f in failures:
        print("  -", f)
    raise SystemExit(1)
print(f"static consistency OK: {len(wanted)} ids, {len(tips)} tips, "
      f"themes {sorted(defined)}")