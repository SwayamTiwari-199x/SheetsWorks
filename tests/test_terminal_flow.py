"""Drive app.js's command logic for real, outside a browser.

app.js is an IIFE with no exports, so each test loads it into a minimal DOM stub
under node and then types commands into it. This catches the logic bugs that
static grepping cannot: a draft that never commits, an edit that silently does
nothing, a reorder that corrupts the array.

Skipped when node is not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "app" / "static" / "app.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to execute app.js"
)

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

function mk() {
  const el = {
    _text: '', _cls: '', children: [], attrs: {}, style: {}, _l: {},
    set textContent(v){ this._text = String(v); }, get textContent(){ return this._text; },
    set className(v){ this._cls = v; },      get className(){ return this._cls; },
    set hidden(v){ this._hidden = v; },      get hidden(){ return this._hidden; },
    set innerHTML(v){ throw new Error('innerHTML was set — XSS risk'); },
    appendChild(c){ this.children.push(c); }, removeChild(){}, click(){}, focus(){},
    append(...kids){ kids.forEach((k) => this.children.push(k)); },
    setAttribute(k,v){ this.attrs[k]=v; },
    getAttribute(k){ return k in this.attrs ? this.attrs[k] : null; },
    addEventListener(ev,fn){ this._l[ev]=fn; },
    scrollTop:0, scrollHeight:0, value:'', src:'',
  };
  return el;
}
const els = {};
for (const id of ['navbar','nbItems','nbStatus','scrollback','promptForm','cmd',
                   'promptPath','previewPane','previewFrame','previewMeta',
                   'previewClose','previewRefresh']) { els[id] = mk(); }

const store = {};
const localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k,v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; },
};

const server = { profile: null, saved: null, calls: [], previewCalls: 0 };
// Seeded before app.js is evaluated, because boot() reads /profile during load.
if (process.argv[3]) {
  server.profile = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
}
const H = { 'X-Pages':'1', 'X-Page-Limit':'1', 'X-Page-Budget':'ok', 'X-Density':'normal' };
function okResp(body, headers) {
  return { ok:true, status:200,
    headers:{ get: h => (headers && headers[h]) || null },
    json: async () => (typeof body === 'string' ? JSON.parse(body) : body),
    blob: async () => ({ size: 1 }) };
}
const fetchStub = async (path, opts) => {
  const method = (opts && opts.method) || 'GET';
  server.calls.push({ path, method });
  if (path === '/profile' && method === 'GET') {
    if (!server.profile) return { ok:false, status:404,
      headers:{get:()=> 'application/json'},
      json: async()=>({detail:'no profile yet; PUT /profile first'}) };
    return okResp(server.profile);
  }
  if (path === '/profile' && method === 'PUT') {
    server.profile = JSON.parse(opts.body); server.saved = server.profile;
    return okResp(server.profile);
  }
  if (path === '/preview') {
    server.previewCalls++;
    return { ok:true, status:200, headers:{get:h=>H[h]}, blob: async () => ({ size: 1 }) };
  }
  if (path.indexOf('/versions/from-profile') === 0) {
    return okResp({ id:'aaaaaaaaaaaa', name:'resume' });
  }
  if (path.indexOf('/export/') === 0) {
    return { ok:true, status:200, headers:{get:h=>H[h]}, blob: async () => ({ size: 1 }) };
  }
  throw new Error('unhandled ' + path);
};

const URLStub = { createObjectURL: () => 'blob:x', revokeObjectURL(){} };
const winListeners = {};
global.window = { addEventListener: (ev,fn) => { (winListeners[ev] = winListeners[ev]||[]).push(fn); } };
global.document = {
  documentElement: { attrs:{'data-theme':'amber'},
                     setAttribute(k,v){this.attrs[k]=v;},
                     getAttribute(k){ return k in this.attrs ? this.attrs[k] : null; } },
  createElement: mk,
  getElementById: (id) => els[id] || mk(),
  body: { appendChild(){}, removeChild(){} },
  addEventListener(){},
};
global.localStorage = localStorage;
global.fetch = fetchStub;
global.URL = URLStub;
global.structuredClone = (v) => JSON.parse(JSON.stringify(v));

new Function('window','document','localStorage','fetch','URL','structuredClone',
             'setTimeout','clearTimeout', src)
  (global.window, global.document, localStorage, fetchStub, URLStub,
   global.structuredClone, () => 0, () => {});

const lines = [];
function collect() {
  lines.length = 0;
  const walk = (el) => {
    if (el.children && el.children.length) el.children.forEach(walk);
    else if (el._text !== '') lines.push((el._cls ? '[' + el._cls + '] ' : '') + el._text);
  };
  walk(els.scrollback);
}
collect();
global.__collect = collect;
global.__lines = lines;
global.__els = els;
global.__server = server;
global.__win = winListeners;

// Drive the app the way a browser does: type into the input and submit the
// form. app.js is an IIFE that exports nothing, and it must not grow test-only
// hooks, so there is deliberately no way to reach inside it.
global.__type = async function (text) {
  els.cmd.value = text;
  els.promptForm._l.submit({ preventDefault() {} });
  for (let i = 0; i < 12; i++) await new Promise((r) => setImmediate(r));
};
global.__settle = async function () {
  for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r));
};
"""


def drive(commands: list[str], profile: dict | None = None) -> dict:
    """Type a list of commands into the terminal and report what happened."""
    script = [HARNESS, "\n", "(async () => {\n"]
    # boot() is async: wait for it so we type into a loaded app, as a user would.
    script.append("  await __settle();\n")
    for c in commands:
        script.append(f"  await __type({json.dumps(c)});\n")
    script.append(
        "  await __settle();\n"
        "  collect();\n"
        "  console.log(JSON.stringify({lines, profile: server.saved || server.profile,"
        " calls: server.calls, previewCalls: server.previewCalls,"
        " theme: document.documentElement.getAttribute('data-theme')}));\n"
        "})();\n"
    )
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "drive.js"
        p.write_text("".join(script), encoding="utf-8")
        seed = Path(td) / "profile.json"
        seed.write_text(json.dumps(profile), encoding="utf-8")
        proc = subprocess.run(
            ["node", str(p), str(APP_JS), str(seed)],
            capture_output=True, text=True, cwd=ROOT, timeout=120,
        )
    if proc.returncode != 0:
        raise AssertionError("harness failed:\n" + proc.stderr[-3000:])
    return json.loads(proc.stdout.strip().splitlines()[-1])


def has(res: dict, needle: str, cls: str | None = None) -> bool:
    """cls matches the element's class token; collected lines look like
    '[line ok] theme: green', so the check is on 'line <cls>'."""
    for ln in res["lines"]:
        if needle not in ln:
            continue
        if cls is None:
            return True
        if f"[line {cls}]" in ln:
            return True
    return False


BASE = {
    "contact": {"name": "Dusht", "email": "a@b.com", "phone": "12345"},
    "summary": {"text": "Backend engineer."},
    "education": [],
    "experience": [
        {"org": "PayFlow", "role": "Backend", "start": "2022-01", "end": "Present", "bullets": []},
        {"org": "Nimbus", "role": "Intern", "start": "2021-01", "end": "2021-06", "bullets": []},
    ],
    "projects": [],
    "skills": [{"name": "Backend", "items": ["FastAPI"]}],
    "certifications": [],
    "achievements": [],
    "extracurriculars": [],
    "publications": [],
}


# --- navigation and help ---------------------------------------------------


def test_help_lists_commands() -> None:
    r = drive(["help"])
    assert has(r, "help [topic]")
    assert has(r, "draft <section>")
    assert has(r, "undo")


def test_help_topic_detail() -> None:
    r = drive(["help draft"])
    assert has(r, "draft <section>")


def test_slash_and_bare_syntax_both_work() -> None:
    bare = drive(["help"])
    slashed = drive(["/help"])
    assert bare["lines"][-len(bare["lines"]):] is not None
    assert has(slashed, "help [topic]"), "slash prefix must be optional"


def test_typo_suggests_the_right_command() -> None:
    r = drive(["exporr pdf"])
    assert has(r, "command not found")
    assert has(r, "did you mean `export`")


def test_typo_suggests_the_right_section() -> None:
    r = drive(["cd experiance"])
    assert has(r, "no such section")
    assert has(r, "did you mean `cd experience`")


def test_unknown_field_suggests_the_right_field() -> None:
    r = drive(["draft experience", "org PayFlow", "orgg Acme"], BASE)
    assert has(r, 'unknown field "orgg"')
    assert has(r, "valid: org, role")


def test_hint_uses_real_state() -> None:
    r = drive(["hint"], BASE)
    assert has(r, "next up") or has(r, "looks complete")


# --- drafts ---------------------------------------------------------------


def test_draft_then_done_commits_and_saves() -> None:
    r = drive(
        ["draft experience", "org Acme", "role SRE", "start 2023-01",
         "end Present", "bullet Cut latency by 40%.", "done", "save"],
        BASE,
    )
    assert has(r, "added to experience (3 entries)", "ok")
    assert any(e["org"] == "Acme" for e in r["profile"]["experience"])
    assert any(e["role"] == "SRE" for e in r["profile"]["experience"])


def test_bare_field_lines_work_inside_a_draft() -> None:
    r = drive(["draft projects", "name Scheduler", "done", "save"], BASE)
    assert has(r, "added to projects (1 entries)", "ok")
    assert r["profile"]["projects"][0]["name"] == "Scheduler"


def test_add_is_equivalent_to_a_bare_field() -> None:
    r = drive(["draft projects", "add name Scheduler", "done", "save"], BASE)
    assert r["profile"]["projects"][0]["name"] == "Scheduler"


def test_appenders_accumulate() -> None:
    r = drive(["draft experience", "org Acme", "bullet One.", "bullet Two.", "done", "save"],
              BASE)
    entry = [e for e in r["profile"]["experience"] if e["org"] == "Acme"][0]
    assert [b["text"] for b in entry["bullets"]] == ["One.", "Two."]


def test_bullets_are_objects_like_the_api_expects() -> None:
    """Regression: bullets came back as strings and the server would 422.

    The API models a bullet as {raw_facts, text, metrics, tags, tools}. Writing a
    bare string produced a payload the server rejects, and printing one showed
    "[object Object]".
    """
    r = drive(["draft experience", "org Acme", "bullet Cut latency by 40%.", "done", "save"],
              BASE)
    entry = [e for e in r["profile"]["experience"] if e["org"] == "Acme"][0]
    bullet = entry["bullets"][0]
    assert isinstance(bullet, dict), f"expected an object, got {type(bullet).__name__}"
    assert bullet["text"] == "Cut latency by 40%."
    assert bullet["raw_facts"] == "Cut latency by 40%."
    for key in ("metrics", "tags", "tools"):
        assert bullet[key] == []


def test_cat_prints_object_bullets_as_text() -> None:
    """Regression: `cat` rendered bullets as '[object Object]'."""
    server_shape = json.loads(json.dumps(BASE))
    server_shape["experience"][0]["bullets"] = [
        {"id": "b1", "raw_facts": "900->240",
         "text": "Cut p99 latency from 900ms to 240ms with Redis.",
         "metrics": [], "tags": [], "tools": ["Redis"]},
    ]
    r = drive(["cat experience"], server_shape)
    assert has(r, "Cut p99 latency from 900ms to 240ms with Redis.")
    assert not any("[object Object]" in ln for ln in r["lines"])


def test_appending_to_existing_object_bullets_keeps_the_shape() -> None:
    """`edit 1 bullet X` adds a bullet; it must not corrupt the existing ones."""
    server_shape = json.loads(json.dumps(BASE))
    server_shape["experience"][0]["bullets"] = [
        {"id": "b1", "raw_facts": "x", "text": "Existing bullet.",
         "metrics": [], "tags": [], "tools": []},
    ]
    r = drive(["cd experience", "edit 1 bullet Added bullet.", "save"], server_shape)
    entry = r["profile"]["experience"][0]
    assert len(entry["bullets"]) == 2
    assert all(isinstance(b, dict) for b in entry["bullets"])
    assert entry["bullets"][0]["text"] == "Existing bullet."
    assert entry["bullets"][1]["text"] == "Added bullet."


# --- dot notation: fixing one bullet without losing the entry ------------


def _two_bullet_entry():
    shape = json.loads(json.dumps(BASE))
    shape["experience"][0]["bullets"] = [
        {"id": "b1", "raw_facts": "900->240",
         "text": "Cut p99 latency from 900ms to 240ms.", "metrics": [], "tags": [], "tools": []},
        {"id": "b2", "raw_facts": "11->15",
         "text": "Migrated Postgres 11 to 15.", "metrics": [], "tags": [], "tools": []},
    ]
    return shape


def test_edit_dotted_replaces_a_single_bullet() -> None:
    """Regression: there was no way to fix a typo in one bullet."""
    r = drive(["cd experience", "edit 1.1 Rewritten first bullet.", "save"], _two_bullet_entry())
    entry = r["profile"]["experience"][0]
    assert entry["bullets"][0]["text"] == "Rewritten first bullet."
    assert entry["bullets"][0]["raw_facts"] == "900->240", "original facts must survive"
    assert entry["bullets"][1]["text"] == "Migrated Postgres 11 to 15."
    assert len(entry["bullets"]) == 2


def test_rm_dotted_deletes_a_single_bullet() -> None:
    r = drive(["cd experience", "rm 1.2", "save"], _two_bullet_entry())
    entry = r["profile"]["experience"][0]
    assert len(entry["bullets"]) == 1
    assert entry["bullets"][0]["text"] == "Cut p99 latency from 900ms to 240ms."
    assert len(r["profile"]["experience"]) == 2, "the entry itself must survive"


def test_rm_dotted_out_of_range_explains() -> None:
    r = drive(["cd experience", "rm 1.9", "save"], _two_bullet_entry())
    assert has(r, "has 2 bullets, not 9")
    assert len(r["profile"]["experience"][0]["bullets"]) == 2


def test_dotted_operations_are_undoable() -> None:
    r = drive(["cd experience", "rm 1.1", "save", "undo", "save"], _two_bullet_entry())
    assert len(r["profile"]["experience"][0]["bullets"]) == 2


def test_dotted_edit_works_on_string_bullets() -> None:
    legacy = json.loads(json.dumps(BASE))
    legacy["experience"][0]["bullets"] = ["First.", "Second."]
    r = drive(["cd experience", "edit 1.2 Changed.", "save"], legacy)
    assert r["profile"]["experience"][0]["bullets"][1] == "Changed."


def test_help_rm_documents_dot_notation() -> None:
    r = drive(["help rm"], BASE)
    assert has(r, "rm <n>.<m>")
    assert has(r, "rm 1.2")


def test_string_bullets_still_work_for_legacy_data() -> None:
    """Older profiles may hold plain strings; do not break them."""
    legacy = json.loads(json.dumps(BASE))
    legacy["experience"][0]["bullets"] = ["A plain string bullet."]
    r = drive(["cat experience"], legacy)
    assert has(r, "A plain string bullet.")
    assert not any("[object Object]" in ln for ln in r["lines"])


def test_courses_and_tech_stay_plain_strings() -> None:
    r = drive(["draft education", "institution X", "course Databases", "done", "save"], BASE)
    assert r["profile"]["education"][0]["coursework"] == ["Databases"]
    r2 = drive(["draft projects", "name P", "tech Python", "done", "save"], BASE)
    assert r2["profile"]["projects"][0]["tech"] == ["Python"]


def test_grade_and_scale_combine() -> None:
    r = drive(
        ["draft education", "institution BITS", "grade 8.7", "scale 10", "done", "save"],
        BASE,
    )
    edu = r["profile"]["education"][0]
    assert edu["grade"] == {"value": "8.7", "scale": "10"}


def test_contact_draft_requires_name_email_phone() -> None:
    """An empty contact cannot be committed, and the profile is left alone."""
    empty = json.loads(json.dumps(BASE))
    empty["contact"] = {"name": "", "email": "", "phone": ""}
    r = drive(["draft contact", "done", "save"], empty)
    assert has(r, "contact needs at least name, email and phone")
    assert r["profile"]["contact"]["name"] == ""


def test_contact_draft_updates_an_existing_contact() -> None:
    r = drive(["draft contact", "city Pune", "done", "save"], BASE)
    assert has(r, "contact updated", "ok")
    assert r["profile"]["contact"]["city"] == "Pune"


def test_summary_draft_updates_the_single_value() -> None:
    r = drive(["draft summary", "text A new summary line.", "done", "save"], BASE)
    assert r["profile"]["summary"]["text"] == "A new summary line."


def test_cancel_discards_the_draft() -> None:
    r = drive(["draft projects", "name Ghost", "cancel", "save"], BASE)
    assert has(r, "draft discarded")
    assert r["profile"]["projects"] == []


def test_bad_experience_type_is_refused() -> None:
    r = drive(["draft experience", "org Acme", "type wizard", "done"], BASE)
    assert has(r, "type must be one of")
    assert len(r["profile"]["experience"]) == 2


# --- edit / rm / mv --------------------------------------------------------


def test_edit_a_list_entry_persists() -> None:
    r = drive(["cd experience", "edit 1 org Renamed", "save"], BASE)
    assert r["profile"]["experience"][0]["org"] == "Renamed"


def test_edit_a_single_value_section_persists() -> None:
    """Regression: this used to read state.draft after nulling it and no-op."""
    r = drive(["cd summary", "edit text A brand new summary.", "save"], BASE)
    assert r["profile"]["summary"]["text"] == "A brand new summary."


def test_edit_contact_persists() -> None:
    r = drive(["cd contact", "edit city Pune", "save"], BASE)
    assert r["profile"]["contact"]["city"] == "Pune"


def test_rm_removes_the_right_entry() -> None:
    r = drive(["cd experience", "rm 1", "save"], BASE)
    assert [e["org"] for e in r["profile"]["experience"]] == ["Nimbus"]


def test_rm_out_of_range_is_refused() -> None:
    r = drive(["cd experience", "rm 9", "save"], BASE)
    assert has(r, "no entry 9")
    assert len(r["profile"]["experience"]) == 2


def test_mv_down_reorders() -> None:
    r = drive(["cd experience", "mv 1 down", "save"], BASE)
    assert [e["org"] for e in r["profile"]["experience"]] == ["Nimbus", "PayFlow"]


def test_mv_up_reorders() -> None:
    r = drive(["cd experience", "mv 2 up", "save"], BASE)
    assert [e["org"] for e in r["profile"]["experience"]] == ["Nimbus", "PayFlow"]


def test_mv_to_explicit_position() -> None:
    r = drive(["draft projects", "name Third", "done",
               "cd experience", "mv 1 2", "save"], BASE)
    assert [e["org"] for e in r["profile"]["experience"]] == ["Nimbus", "PayFlow"]


def test_mv_at_the_top_says_so() -> None:
    r = drive(["cd experience", "mv 1 up"], BASE)
    assert has(r, "already at the top")


def test_rm_without_cd_explains_itself() -> None:
    r = drive(["rm 1"], BASE)
    assert has(r, "cd into a section first")


# --- undo ------------------------------------------------------------------


def test_undo_reverts_an_rm() -> None:
    r = drive(["cd experience", "rm 1", "save", "undo", "save"], BASE)
    assert has(r, "undone", "ok")
    assert len(r["profile"]["experience"]) == 2
    assert r["profile"]["experience"][0]["org"] == "PayFlow"


def test_undo_reverts_an_edit() -> None:
    r = drive(["cd summary", "edit text Changed.", "save", "undo", "save"], BASE)
    assert r["profile"]["summary"]["text"] == "Backend engineer."


def test_undo_reverts_a_mv() -> None:
    r = drive(["cd experience", "mv 1 down", "save", "undo", "save"], BASE)
    assert [e["org"] for e in r["profile"]["experience"]] == ["PayFlow", "Nimbus"]


def test_undo_with_nothing_to_undo_is_graceful() -> None:
    r = drive(["undo"], BASE)
    assert has(r, "nothing to undo")


# --- grep / profile --------------------------------------------------------


def test_grep_finds_a_word() -> None:
    r = drive(["grep payflow"], BASE)
    assert has(r, "PayFlow")
    assert has(r, "match", "dim")


def test_grep_with_no_match() -> None:
    r = drive(["grep zzzznothing"], BASE)
    assert has(r, "no matches")


def test_profile_summary_lists_sections() -> None:
    r = drive(["profile"], BASE)
    assert has(r, "Dusht")
    assert has(r, "experience")


# --- themes ----------------------------------------------------------------


def test_theme_switches() -> None:
    r = drive(["theme green"])
    assert r["theme"] == "green"
    assert has(r, "theme: green", "ok")


def test_theme_lists_options() -> None:
    r = drive(["theme"])
    assert has(r, "amber, green, matrix, paper")


def test_theme_typo_suggests() -> None:
    r = drive(["theme grene"])
    assert has(r, "no such theme")
    assert has(r, "did you mean `green`")


def test_bad_theme_does_not_change_anything() -> None:
    r = drive(["theme neon"])
    assert r["theme"] == "amber"


# --- preview ---------------------------------------------------------------


def test_preview_toggle_calls_the_endpoint() -> None:
    r = drive(["preview on"], BASE)
    assert r["previewCalls"] >= 1
    assert has(r, "preview on")


def test_preview_off() -> None:
    r = drive(["preview on", "preview off"], BASE)
    assert has(r, "preview off")


# --- resilience ------------------------------------------------------------


def test_a_bad_command_does_not_kill_the_session() -> None:
    r = drive(["nonsense", "cd experience", "ls"], BASE)
    assert has(r, "command not found")
    assert has(r, "Backend", "out") or has(r, "Backend"), "session still usable"


def test_blank_input_is_harmless() -> None:
    r = drive(["", "   ", "pwd"], BASE)
    assert any("~" in ln for ln in r["lines"])


def test_rm_on_a_single_value_section_is_refused() -> None:
    r = drive(["cd summary", "rm 1"], BASE)
    assert has(r, "single value")


def test_global_error_handlers_are_registered() -> None:
    r = drive(["help"], BASE)
    # window listeners were captured; assert the file registered them
    src = APP_JS.read_text(encoding="utf-8")
    assert "window.addEventListener('error'" in src
    assert "window.addEventListener('unhandledrejection'" in src
    assert r is not None


def test_export_flow_snapshots_then_downloads() -> None:
    r = drive(["export pdf"], BASE)
    paths = [c["path"] for c in r["calls"]]
    assert any("/versions/from-profile" in p for p in paths)
    assert any("/export/" in p for p in paths)
    assert has(r, "downloaded resume.pdf", "ok")


def test_export_rejects_a_bad_format() -> None:
    r = drive(["export exe"], BASE)
    assert has(r, "format must be one of")


def test_startup_against_an_empty_db_welcomes_and_orients() -> None:
    """A new user must be told what to type, not just handed an error."""
    r = drive(["pwd"])
    assert has(r, "Welcome")
    assert has(r, "home")
    assert has(r, "setup contact")
    assert has(r, "demo")


def test_home_lists_every_section_with_status() -> None:
    r = drive(["home"], BASE)
    assert has(r, "your resume, as a set of sections")
    assert has(r, "section")
    assert has(r, "filled")
    assert has(r, "empty")


def test_home_tells_you_where_to_start_when_empty() -> None:
    empty = json.loads(json.dumps(BASE))
    for k in ("education", "experience", "projects", "skills",
              "certifications", "achievements"):
        empty[k] = []
    r = drive(["home"], empty)
    assert has(r, "start here:")
    assert has(r, "draft experience")


def test_home_reports_zero_for_an_empty_singleton() -> None:
    """An empty contact is 0 entries, not 1 -- otherwise `home` lies."""
    empty = json.loads(json.dumps(BASE))
    empty["contact"] = {"name": "", "email": "", "phone": ""}
    r = drive(["home"], empty)
    line = [ln for ln in r["lines"] if "contact" in ln and "empty" in ln]
    assert line, "contact row missing"
    assert " 0 " in line[0] or line[0].split()[-2] == "0", line[0]
def test_home_is_where_cd_without_argument_goes() -> None:
    r = drive(["cd contact", "cd"], BASE)
    assert has(r, "your resume, as a set of sections")


# --- the intuition fix -----------------------------------------------------


def test_cd_explains_the_section_and_gives_the_next_command() -> None:
    """Regression: clicking a navbar section left you with nothing to do."""
    empty = json.loads(json.dumps(BASE))
    empty["contact"] = {"name": "", "email": "", "phone": ""}
    r = drive(["cd contact"], empty)
    assert has(r, "How employers reach you")
    assert has(r, "next: draft contact")
    assert has(r, "then type name / email / phone")


def test_cd_on_a_populated_section_shows_the_alternatives() -> None:
    r = drive(["cd experience"], BASE)
    assert has(r, "entries here")
    assert has(r, "cat experience")
    assert has(r, "draft experience")


def test_cd_offers_reorder_and_delete_hints_for_list_sections() -> None:
    r = drive(["cd experience"], BASE)
    assert has(r, "mv 1 down")
    assert has(r, "rm 1")


def test_cd_offers_edit_for_single_value_sections() -> None:
    r = drive(["cd contact"], BASE)
    assert has(r, "edit contact")


def test_cd_unknown_section_suggests_home() -> None:
    r = drive(["cd nowhere"], BASE)
    assert has(r, "no such section")
    assert has(r, "home")


def test_cat_explains_the_section() -> None:
    r = drive(["cat contact"], BASE)
    assert has(r, "How employers reach you")


def test_cat_on_empty_section_says_how_to_start() -> None:
    empty = json.loads(json.dumps(BASE))
    empty["projects"] = []
    r = drive(["cat projects"], empty)
    assert has(r, "nothing here yet")
    assert has(r, "draft projects")


def test_cat_with_no_argument_explains_usage() -> None:
    r = drive(["cat"], BASE)
    assert has(r, "which section?")
    assert has(r, "cat experience")


def test_cat_shows_entries_and_how_to_change_them() -> None:
    r = drive(["cd experience", "cat"], BASE)
    assert has(r, "Backend")
    assert has(r, "edit 1")


# --- setup ----------------------------------------------------------------


def test_setup_without_argument_explains_every_section() -> None:
    r = drive(["setup"], BASE)
    assert has(r, "setup contact")
    assert has(r, "setup experience")


def test_setup_opens_a_draft() -> None:
    r = drive(["setup experience"], BASE)
    assert has(r, "~/experience")
    assert has(r, "drafting experience")
    assert has(r, "org / role")


def test_setup_typo_suggests() -> None:
    r = drive(["setup experiance"], BASE)
    assert has(r, "no such section")
    assert has(r, "did you mean `setup experience`")


# --- notes scratchpad -----------------------------------------------------


def test_note_adds_and_lists() -> None:
    r = drive(["note cut latency from 900ms to 240ms", "note led a team of 5", "notes"])
    assert has(r, "noted (1 total)", "ok")
    assert has(r, "noted (2 total)", "ok")
    assert has(r, "cut latency from 900ms to 240ms")
    assert has(r, "led a team of 5")
    assert has(r, "notes  (2)")


def test_notes_when_empty_explains_itself() -> None:
    r = drive(["notes"], BASE)
    assert has(r, "no notes yet")
    assert has(r, "note cut p99 latency")


def test_note_rm_deletes_one() -> None:
    r = drive(["note first thing", "note second thing", "note rm 1", "notes"])
    assert has(r, "deleted: first thing", "ok")
    # ignore the echoed command lines and the deletion message itself
    body = [ln for ln in r["lines"] if not ln.startswith("[line cmd]")
            and "deleted:" not in ln]
    assert not any("first thing" in ln for ln in body)
    assert any("second thing" in ln for ln in body)


def test_note_rm_out_of_range() -> None:
    r = drive(["note only one", "note rm 5"])
    assert has(r, "no note 5")


def test_note_clear() -> None:
    r = drive(["note a", "note b", "note clear", "notes"])
    assert has(r, "notes cleared")
    assert has(r, "no notes yet")


def test_notes_never_touch_the_profile() -> None:
    """Notes are raw material, not resume content."""
    r = drive(["note something secret", "save"], BASE)
    blob = json.dumps(r["profile"])
    assert "secret" not in blob


def test_note_alias_works() -> None:
    r = drive(["note via alias"], BASE)
    assert has(r, "noted (1 total)", "ok")


# --- demo -----------------------------------------------------------------


def test_demo_loads_a_sample_when_empty() -> None:
    r = drive(["demo"], None)
    assert has(r, "loaded a sample resume", "ok")
    assert has(r, "replace it with your own")
    assert r["profile"]["contact"]["name"] == "Dusht"
    assert r["profile"]["experience"]


def test_demo_refuses_to_clobber_real_data() -> None:
    r = drive(["demo"], BASE)
    assert has(r, "would replace the profile")
    assert has(r, "demo --force")
    assert r["profile"]["contact"]["name"] == "Dusht" or "Dusht" in json.dumps(r["profile"])


def test_demo_refusal_leaves_the_profile_alone() -> None:
    r = drive(["demo"], BASE)
    assert r["profile"]["experience"][0]["org"] == "PayFlow", "must not be overwritten"


def test_demo_force_overwrites() -> None:
    r = drive(["demo --force"], BASE)
    assert has(r, "loaded a sample resume", "ok")
    assert r["profile"]["contact"]["name"] == "Dusht"


def test_demo_is_undoable() -> None:
    r = drive(["demo --force", "save", "undo", "save"], BASE)
    assert r["profile"]["experience"][0]["org"] == "PayFlow"


def test_sample_data_is_clearly_fake() -> None:
    r = drive(["demo"], None)
    blob = json.dumps(r["profile"])
    assert "example.com" in blob, "sample must use a reserved example domain"


def test_reset_requires_force() -> None:
    r = drive(["reset"], BASE)
    assert has(r, "empties your profile")
    assert r["profile"]["experience"], "must not have reset"


def test_reset_force_empties() -> None:
    r = drive(["reset --force"], BASE)
    assert has(r, "profile cleared")
    assert r["profile"]["experience"] == []


def test_reset_is_undoable() -> None:
    r = drive(["reset --force", "save", "undo", "save"], BASE)
    assert len(r["profile"]["experience"]) == 2


# --- help -----------------------------------------------------------------


def test_help_covers_the_new_commands() -> None:
    r = drive(["help"], BASE)
    for cmd in ("home", "setup", "demo", "notes", "cat", "reset"):
        assert has(r, cmd), f"help does not mention {cmd}"


def test_every_command_has_a_help_topic() -> None:
    """Nobody should hit a command with `help <cmd>` saying 'no help topic'."""
    for cmd in ("home", "setup", "ls", "cd", "cat", "pwd", "notes", "note",
                "demo", "reset", "draft", "edit", "rm", "mv", "export",
                "theme", "undo", "preview", "grep", "hint", "profile", "clear",
                "help"):
        got = drive(["help " + cmd], BASE)
        assert not has(got, "no help topic"), f"no help topic for {cmd}"


def test_help_help_lists_every_topic() -> None:
    r = drive(["help help"], BASE)
    assert has(r, "Topics:")
    for topic in ("home", "setup", "cat", "notes", "demo", "reset"):
        assert has(r, topic), f"topic list omits {topic}"


def test_help_cat_is_written_for_a_beginner() -> None:
    r = drive(["help cat"], BASE)
    assert has(r, "read a section back in full")
    assert has(r, "If the section is empty")
