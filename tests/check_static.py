"""Static consistency checks across the front end.

Cheap, and they catch what a redesign actually gets wrong: JS reaching for an
element the markup does not have, a palette defined in two places, or a
stylesheet that quietly started loading something remote.

Not part of pytest on purpose -- it is a pre-commit sweep, not a contract.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"

SHELL = (STATIC / "win" / "shell.js").read_text(encoding="utf-8")
APP = (STATIC / "win" / "app.js").read_text(encoding="utf-8")
EDITOR = (STATIC / "win" / "editor.js").read_text(encoding="utf-8")
MODEL = (STATIC / "win" / "editor-model.js").read_text(encoding="utf-8")
SAMPLE = (STATIC / "win" / "sample.js").read_text(encoding="utf-8")
CSS = (STATIC / "win" / "win95.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")

# Everything that ships as the front end. That is all of it now: the archived
# terminal (terminal.html, old-app.js, old-term.css, old-site.css) has been
# deleted, so there is no longer a second page whose assets need resolving.
NEW_JS = (SHELL, APP, EDITOR, MODEL, SAMPLE)

failures = []


def check(ok, message):
    if not ok:
        failures.append(message)


# --- every id the code asks for must exist -------------------------------

wanted = set(re.findall(r"getElementById\(\s*'([A-Za-z0-9_-]+)'",
                        "\n".join(NEW_JS)))
present = set(re.findall(r'id="([A-Za-z0-9_-]+)"', HTML))
missing = sorted(wanted - present)
check(not missing, f"code asks for ids the markup lacks: {missing}")

# Scripts must load in dependency order: the model and the form before the app
# that opens them, or boot throws a ReferenceError.
order = ["shell.js", "sample.js", "editor-model.js", "editor.js", "app.js"]
positions = []
for name in order:
    tag = f'src="/static/win/{name}"'
    check(tag in HTML, f"index.html does not load {name}")
    if tag in HTML:
        positions.append((name, HTML.index(tag)))
check([n for n, _ in positions] == order,
      f"scripts load out of dependency order: {[n for n, _ in positions]}")

# Every script the page loads must exist on disk.
for ref in re.findall(r'src="(/static/[^"]+)"', HTML):
    check((STATIC / ref[len("/static/"):]).exists(), f"{ref} does not exist")
for ref in re.findall(r'href="(/static/[^"]+)"', HTML):
    check((STATIC / ref[len("/static/"):]).exists(), f"{ref} does not exist")

# --- nothing loads from the network ---------------------------------------

for banned in ("@import", "fonts.googleapis", "cdn.", "http://",
               "https://", "url("):
    check(banned not in CSS, f"win95.css reaches outside via {banned}")

check("@font-face" not in re.sub(r"/\*.*?\*/", "", CSS, flags=re.DOTALL),
      "no font may be embedded")

# --- the palette lives in exactly one place -------------------------------

palette = set(re.findall(r"(--[a-z-]+):", CSS.split("*/", 1)[1]))
for token in ("--face", "--hilite", "--light", "--shadow", "--dark", "--teal"):
    check(token in palette, f"{token} missing from the palette")

# --- bevels ---------------------------------------------------------------

for token in ("--bevel-out", "--bevel-in", "--bevel-out-thin", "--bevel-in-thin"):
    check(token in CSS, f"{token} missing; the bevels are the whole look")

# --- motion is declared and then switched off -----------------------------

check("@keyframes win-open" in CSS, "no window-open animation")
reduced = CSS.split("prefers-reduced-motion", 1)
check(len(reduced) > 1, "no reduced-motion block")
if len(reduced) > 1:
    check("animation: none" in reduced[1], "reduced motion does not stop anything")

# --- the tips come from rules.json, escaped -------------------------------

sys.path.insert(0, str(ROOT))
from app import rules  # noqa: E402

tips = rules.tips()
check(len(tips) >= 6, f"only {len(tips)} tips; the Read Me wants more")
for tip in tips:
    for key in ("title", "body", "source", "tag"):
        check(key in tip, f"a tip is missing {key}: {tip}")
    check(tip["tag"] in ("verified", "unverified"), f"bad tag on {tip['title']!r}")

payload = json.dumps({"tips": tips}, separators=(",", ":"))
safe = (payload.replace("<", "\\u003c").replace(">", "\\u003e")
        .replace("&", "\\u0026"))
check("<" not in safe, "the injected JSON can still contain a raw <")
check('{"tips": []}' in HTML, "index.html lost its tips placeholder")

# --- the desktop is built out of the reference's parts ---------------------

for needed in ('id="desktop"', 'id="taskbar"', 'id="startMenu"',
               'id="tipsData"', 'id="startBtn"'):
    check(needed in HTML, f"markup is missing {needed}")

# --- every window named in ?open= actually opens something ---------------
# Parsed out of the two places that must agree: the KNOWN allow-list and the
# name-to-opener map. A name in one and not the other is a deep link that
# silently does nothing.

known = re.findall(r"'([a-z]+)'",
                   APP.split("const KNOWN = [", 1)[1].split("]", 1)[0])
map_block = APP.split("const map = {", 1)[1].split("};", 1)[0]
mapped = dict(re.findall(r"([a-z]+):\s*([A-Za-z_$][\w$]*)", map_block))

check(set(known) == set(mapped),
      f"?open= names and the opener map disagree: "
      f"only-known={sorted(set(known) - set(mapped))} "
      f"only-mapped={sorted(set(mapped) - set(known))}")
for name, fn in mapped.items():
    check(f"function {fn}(" in APP or f"async function {fn}(" in APP,
          f"?open={name} maps to {fn}, which does not exist")

# --- the new UI must not smuggle the old one back -------------------------

body = re.sub(r"(?<!:)//[^\n]*", "",
              re.sub(r"/\*.*?\*/", "", SHELL + APP, flags=re.DOTALL))
for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
    check(banned not in body, f"{banned} in the new front end")

if failures:
    print("\nFAILURES:")
    for f in failures:
        print("  -", f)
    raise SystemExit(1)

print(f"static consistency OK: {len(wanted)} ids, {len(tips)} tips, "
      f"{len(known)} deep-linkable windows")