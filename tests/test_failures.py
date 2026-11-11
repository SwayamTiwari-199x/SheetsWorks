"""Drive failures.js for real, outside a browser.

`explainFailure` turned a failed response into words a person can act on, and
there were two copies of it: one in app.js and one in editor.js. They behaved
the same on the happy path and differently on every other one -- the editor's
copy dropped the entry number and left "Value error," at the start of the
sentence, so the same 422 read two different ways depending on which window
asked. They now share one implementation, and this drives that one for real.

The module is DOM-free on purpose, so node can run it: a Response here is a
plain object with `status` and `json()`, which is all `explainFailure` reads.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "app" / "static" / "win" / "failures.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to execute the module"
)

PRELUDE = """
const fs = require('fs');
new Function(fs.readFileSync(process.argv[2], 'utf8'))();
const F = globalThis.Failures;
if (!F) { console.log('MODULE DID NOT LOAD'); process.exit(2); }
const FAILURES = [];
let COUNT = 0;
function ok(label, cond, detail) {
  if (!cond) { console.log('FAIL  ' + label + (detail ? '   ' + detail : '')); FAILURES.push(label); }
  else { console.log('PASS  ' + label + (detail ? '   ' + detail : '')); COUNT += 1; }
}
async function throwsAsync(fn, label) {
  try { await fn(); ok(label, false, 'did not throw'); }
  catch (e) { ok(label, true, e.message); }
}
/* A Response, reduced to the two members explainFailure reads. */
function reply(status, body) {
  return {
    status: status,
    json: async function () {
      if (body === NOT_JSON) throw new SyntaxError('Unexpected token < in JSON');
      return body;
    },
  };
}
const NOT_JSON = Symbol('not json');
"""


def run(body: str) -> dict:
    # The body awaits, and `require` above makes the file CommonJS, so top-level
    # await is ambiguous to node. Wrap it and report after the promise settles,
    # otherwise the RESULT line is printed before any check has run.
    script = PRELUDE + """
(async function main() {
""" + body + """
})().then(function () {
  console.log('---RESULT---' + COUNT + '|' + FAILURES.length + '|' + FAILURES.join(' ;; '));
}).catch(function (e) {
  console.log('FAIL  the harness itself threw  ' + e.message);
  console.log('---RESULT---' + COUNT + '|' + (FAILURES.length + 1) + '|harness threw');
});
"""
    with __import__("tempfile").TemporaryDirectory() as td:
        path = Path(td) / "f.js"
        path.write_text(script, encoding="utf-8")
        proc = subprocess.run(["node", str(path), str(MODULE)],
                              capture_output=True, text=True, cwd=ROOT, timeout=120)
    if proc.returncode != 0:
        pytest.fail("node failed:\n" + proc.stderr[-2000:])
    out = proc.stdout
    assert "---RESULT---" in out, out[-2000:]
    _, _, fails = out.split("---RESULT---", 1)[1].strip().split("|", 2)
    return {"checks": int(out.split("---RESULT---")[1].split("|")[0]),
            "failures": [f for f in fails.split(" ;; ") if f],
            "log": out}


def passing(body: str) -> str:
    result = run(body)
    assert not result["failures"], (
        "failed: " + "; ".join(result["failures"]) + "\n" + result["log"])
    return result["log"]


def test_a_validation_error_names_the_entry_it_is_about() -> None:
    """Pydantic reports a JSON path. A JSON path is not something a person filling
    in a form can act on, so the index becomes an entry number.

    Note what is *not* asserted: that the field name appears. The tail of the
    path is dropped on the assumption that the message names the field, which
    pydantic's own messages do and this project's custom `raise ValueError(...)`
    ones do not -- "'Jul' is not a date I can read" names no field. So two bad
    dates in one entry read identically. Recorded in BACKLOG.md rather than
    changed here, because it was not part of the merge."""
    passing("""
const res = reply(422, { detail: [
  { loc: ['body', 'experience', 0, 'start'], msg: "Value error, 'Jul' is not a date I can read." },
]});
const text = await F.explainFailure(res);
ok('the entry number is in the sentence', /entry 1/.test(text), text);
ok('the section is in the sentence', /experience/.test(text), text);
ok('the machine prefix is gone', !/Value error/.test(text), text);
ok("the user's own words survive", /'Jul' is not a date I can read/.test(text), text);
ok('and it reads as a sentence, not a JSON path', !/\\["|", /.test(text), text);
""")


def test_a_second_entry_is_numbered_from_the_data_not_the_path() -> None:
    """Index 0 in the payload is the second entry on screen. Reporting 'entry 0'
    is the kind of thing that makes people hunt through the wrong one."""
    passing("""
const res = reply(422, { detail: [
  { loc: ['body', 'experience', 1, 'bullets', 3, 'text'], msg: 'too long' },
]});
const text = await F.explainFailure(res);
ok('it says entry 2, not entry 1', /entry 2/.test(text), text);
ok('and not entry 0', !/entry 0/.test(text), text);
""")


def test_every_problem_is_reported_not_just_the_first() -> None:
    """A form with three bad fields must not be fixed one dialog at a time."""
    passing("""
const res = reply(422, { detail: [
  { loc: ['body', 'contact', 'email'], msg: 'not an email' },
  { loc: ['body', 'contact', 'phone'], msg: 'too short' },
]});
const text = await F.explainFailure(res);
ok('both problems are in the text', /not an email/.test(text) && /too short/.test(text), text);
ok('on separate lines', text.split('\\n').length === 2, JSON.stringify(text));
""")


def test_a_plain_string_detail_is_used_as_written() -> None:
    passing("""
const res = reply(400, { detail: 'that is not a date range I can read' });
ok('a string detail comes straight through',
   (await F.explainFailure(res)) === 'that is not a date range I can read');
""")


def test_a_body_that_is_not_json_still_says_the_status() -> None:
    """A proxy error page or a gateway timeout is not JSON. Reporting 'unexpected
    token' tells the user nothing they can act on; the status code is the one
    fact worth keeping."""
    passing("""
const res = reply(502, NOT_JSON);
ok('an unparseable body falls back to the status',
   (await F.explainFailure(res)) === 'HTTP 502');
ok('and it throws nothing', true);
""")


def test_a_bare_message_is_not_dropped() -> None:
    passing("""
ok('a top-level msg is used',
   (await F.explainFailure(reply(409, { msg: 'that name is taken' }))) === 'that name is taken');
const odd = await F.explainFailure(reply(500, { weird: true }));
ok('an unrecognised body is shown rather than swallowed',
   /weird/.test(odd), odd);
""")


def test_nothing_raises_on_a_body_it_has_never_seen() -> None:
    """explainFailure runs in a catch block. Throwing from there replaces a real
    message with a confusing one and loses the error entirely."""
    passing("""
const bodies = [null, [], {}, { detail: [] }, { detail: [{}] },
                { detail: null }, { detail: 42 }, { detail: [null] }];
for (const b of bodies) {
  let text = null;
  try { text = await F.explainFailure(reply(500, b)); }
  catch (e) { ok('body ' + JSON.stringify(b) + ' does not throw', false, e.message); }
  ok('body ' + JSON.stringify(b) + ' produces text', typeof text === 'string' && text.length > 0, text);
}
""")


def test_the_where_and_say_helpers_are_shared_too() -> None:
    """They were part of the duplicate, not incidental. app.js used them; the
    editor's copy inlined the weaker version."""
    passing("""
ok('where names the entry', F.whereInPlainEnglish(['body', 'projects', 2, 'bullets']) === 'projects entry 3: ',
   JSON.stringify(F.whereInPlainEnglish(['body', 'projects', 2, 'bullets'])));
ok('where is empty for a top-level field',
   F.whereInPlainEnglish(['body', 'template']) === '', JSON.stringify(F.whereInPlainEnglish(['body', 'template'])));
ok('say drops the prefix', F.say({ msg: 'Value error, too short' }) === 'too short', F.say({ msg: 'Value error, too short' }));
ok('say survives a problem with no msg', typeof F.say({}) === 'string');
""")


def test_there_is_exactly_one_explain_failure() -> None:
    """The point of the merge. One definition, and both callers routed to it, so
    the two windows cannot start reporting a 422 differently again."""
    static = ROOT / "app" / "static" / "win"
    sources = {p.name: p.read_text(encoding="utf-8")
               for p in static.glob("*.js")}
    # `async function explainFailure` also contains `function explainFailure`,
    # so counting both spellings would double-count every definition.
    defined = {name: len(re.findall(r"\bfunction explainFailure\b", src))
               for name, src in sources.items()}
    total = sum(defined.values())
    assert total == 1, (
        "explainFailure is defined "
        f"{total} times ({defined}); it must exist once and be shared"
    )
    holder = next(name for name, n in defined.items() if n)
    assert holder == "failures.js", (
        f"explainFailure should live in failures.js, not {holder}"
    )
    for name in ("app.js", "editor.js"):
        assert "async function explainFailure" not in sources[name], (
            f"{name} still has its own explainFailure; the two copies are the bug"
        )
        assert "Failures.explainFailure" in sources[name], (
            f"{name} does not call the shared explainFailure"
        )