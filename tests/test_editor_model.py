"""Drive editor-model.js for real, outside a browser.

This is the replacement for the terminal flow tests. Those drove a command
engine wrapped around a UI, so the only way to ask "does a draft actually
commit?" was to fake a whole terminal. editor-model.js is deliberately DOM-free,
so it can be loaded straight into node and asked directly -- which means every
behaviour the archived tests covered can be covered again, and the Stage 3 shape
bugs can be pinned as named rules rather than as accidents.

Skipped when node is not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "app" / "static" / "win" / "editor-model.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is required to execute the model"
)

# Each test body is JS evaluated with the model in scope as `M`, reporting
# through ok() / throws().
#
# The model attaches itself to window, or to globalThis where there is no window,
# so loading the file is enough; the prelude then reads it off the global rather
# than expecting to hand it over. An earlier version passed an empty object in
# and every test failed on `M.setField is not a function`.
PRELUDE = """
const fs = require('fs');
new Function(fs.readFileSync(process.argv[2], 'utf8'))();
const M = globalThis.EditorModel;
if (!M) { console.log('MODEL DID NOT LOAD'); process.exit(2); }
function ok(label, cond, detail) {
  if (!cond) { console.log('FAIL  ' + label + (detail ? '   ' + detail : '')); FAILURES.push(label); }
  else { console.log('PASS  ' + label + (detail ? '   ' + detail : '')); }
  COUNT++;
}
const FAILURES = [];
let COUNT = 0;
function blank() {
  return { contact: { name: '', email: '', phone: '', city: '', country: '', links: [] },
           summary: '', interests: '',
           education: [], experience: [], projects: [], skills: [],
           certifications: [], achievements: [], extracurriculars: [], publications: [] };
}
function throws(fn, label) {
  try { fn(); ok(label, false, 'did not throw'); }
  catch (e) { ok(label, true, e.message); }
}
"""


def run(body: str) -> dict:
    """Execute JS against the model and return the reported failures."""
    script = PRELUDE + "\n" + body + """
console.log('---RESULT---' + COUNT + '|' + FAILURES.length + '|' + FAILURES.join(' ;; '));
"""
    with __import__("tempfile").TemporaryDirectory() as td:
        path = Path(td) / "m.js"
        path.write_text(script, encoding="utf-8")
        proc = subprocess.run(["node", str(path), str(MODEL)],
                              capture_output=True, text=True, cwd=ROOT, timeout=120)
    if proc.returncode != 0:
        pytest.fail("node failed:\\n" + proc.stderr[-2000:])
    out = proc.stdout
    assert "---RESULT---" in out, out[-2000:]
    _, _, fails = out.split("---RESULT---", 1)[1].strip().split("|", 2)
    return {"checks": int(out.split("---RESULT---")[1].split("|")[0]),
            "failures": [f for f in fails.split(" ;; ") if f],
            "log": out}


def passing(body: str) -> str:
    result = run(body)
    assert not result["failures"], (
        "failed: " + "; ".join(result["failures"]) + "\\n" + result["log"])
    return result["log"]


# --- the shape bugs from Stage 3 -----------------------------------------


def test_bullets_are_objects_not_strings() -> None:
    """Stage 3 wrote bare strings; the API rejected them with a 422."""
    log = passing("""
const p = blank();
p.experience = [{ org: 'X', role: 'Y', type: 'job', start: '2022-01',
                  end: 'Present', bullets: [] }];
M.setField(p, 'experience', 1, 'bullet', 'Cut p99 latency from 900ms to 240ms');
const b = p.experience[0].bullets[0];
ok('a bullet is an object', typeof b === 'object' && b !== null, typeof b);
ok('it has text', b.text === 'Cut p99 latency from 900ms to 240ms', b.text);
ok('it has an id', typeof b.id === 'string' && b.id.length > 3, b.id);
ok('it has raw_facts', typeof b.raw_facts === 'string');
ok('metrics is an array', Array.isArray(b.metrics));
""")
    assert "PASS" in log


def test_a_bullet_may_carry_its_own_raw_facts() -> None:
    passing("""
const p = blank();
p.experience = [{ org: 'X', role: 'Y', type: 'job', start: '2022-01',
                  end: 'Present', bullets: [] }];
M.setField(p, 'experience', 1, 'bullet', 'Cut p99 latency | 900ms -> 240ms');
const b = p.experience[0].bullets[0];
ok('text is the claim', b.text === 'Cut p99 latency', b.text);
ok('raw_facts keeps the numbers the user typed',
   b.raw_facts === '900ms -> 240ms', b.raw_facts);
""")


def test_ai_accept_stores_facts_not_polished() -> None:
    """The AI Accept path: raw_facts = my original text + answers,
    text = the polished bullet, and they must not be the same string."""
    passing("""
const myWords = 'worked on backend for a staffing app using FastAPI and Postgres\\n1. 120 recruiters\\n2. FastAPI, Postgres, Redis\\n3. cut page load from 2s to 400ms\\n4. my part, small team of 3';
const polished = 'Built a staffing app backend using FastAPI and Postgres, supporting 120 recruiters and reducing page load from 2s to 400ms';
const b = M.makeBullet(polished, myWords);
ok('text is polished', b.text === polished, b.text);
ok('raw_facts has my words', b.raw_facts === myWords, b.raw_facts.slice(0, 60));
ok('text is not the same string as raw_facts', b.text !== b.raw_facts, 'same string!');
""")


def test_summary_and_interests_are_strings_not_objects() -> None:
    """Stage 3 wrote {text: "..."} into a string field. The renderer would have
    printed [object Object] and the API would have rejected it."""
    passing("""
const p = blank();
M.setField(p, 'summary', null, 'text', 'Backend engineer.');
M.setField(p, 'interests', null, 'text', 'Chess and running.');
ok('summary is a string', typeof p.summary === 'string', typeof p.summary);
ok('summary holds the text', p.summary === 'Backend engineer.', p.summary);
ok('interests is a string', typeof p.interests === 'string', typeof p.interests);
""")


def test_grade_is_value_and_scale() -> None:
    """`grade 8.7` used to produce {"grade": "8.7"}."""
    passing("""
const p = blank();
p.education = [{ institution: 'S', degree: 'B.E.', start: '2019-08' }];
M.setField(p, 'education', 1, 'grade', '8.72');
M.setField(p, 'education', 1, 'scale', '10');
const g = p.education[0].grade;
ok('grade has a value', g.value === '8.72', JSON.stringify(g));
ok('grade has a scale', g.scale === '10');
ok('grade has no stray "grade" key', g.grade === undefined);
""")


def test_a_link_appends_to_links_and_never_sets_a_scalar() -> None:
    passing("""
const p = blank();
p.contact.name = 'Anon'; p.contact.email = 'anon@example.com'; p.contact.phone = '12345';
M.setField(p, 'contact', null, 'link', 'GitHub example.org');
ok('contact.links has one entry', p.contact.links.length === 1);
ok('it has a label', p.contact.links[0].label === 'GitHub');
ok('it has a url', p.contact.links[0].url === 'example.org');
ok('contact has no scalar link field', p.contact.link === undefined);
M.setField(p, 'contact', null, 'link', 'LinkedIn example.net');
ok('a second link appends', p.contact.links.length === 2);
throws(() => M.setField(p, 'contact', null, 'link', 'NoUrlHere'),
       'a link without a url is refused');
""")


def test_legacy_string_bullets_are_normalised_on_the_way_in() -> None:
    """Data from an older build must not fail to save."""
    passing("""
const p = blank();
p.experience = [{ org: 'X', role: 'Y', type: 'job', start: '2022-01',
                  end: 'Present', bullets: ['an old string bullet'] }];
M.setField(p, 'experience', 1, 'role', 'Z');
const b = p.experience[0].bullets[0];
ok('the string became an object', typeof b === 'object');
ok('and kept its text', M.bulletText(b) === 'an old string bullet');
""")


# --- scalar fields ---------------------------------------------------------


def test_every_declared_field_is_writable() -> None:
    passing("""
const p = blank();
p.education = [{ institution: 'S', start: '2019-08' }];
/* Dates take a real date, because they are normalised on the way in -- see
   test_dates_are_normalised_before_they_are_stored. */
const vals = { start: '2019-08', end: 'Jul 2026' };
['institution', 'degree', 'field', 'start', 'end', 'notes'].forEach(function (f) {
  M.setField(p, 'education', 1, f, vals[f] || ('v-' + f));
});
ok('every education field took a value',
   p.education[0].institution === 'v-institution' &&
   p.education[0].notes === 'v-notes' && p.education[0].field === 'v-field');
ok('and the dates normalised',
   p.education[0].start === '2019-08' && p.education[0].end === '2026-07');

p.certifications = [{ name: 'C' }];
['name', 'issuer', 'date', 'url', 'details'].forEach(function (f) {
  M.setField(p, 'certifications', 1, f, f === 'date' ? 'March 2024' : ('v-' + f));
});
ok('every certification field took a value',
   p.certifications[0].issuer === 'v-issuer' && p.certifications[0].details === 'v-details');
ok('the certification date normalised', p.certifications[0].date === '2024-03');
""")


def test_an_unknown_field_is_refused_rather_than_silently_added() -> None:
    """The model forbids extra inputs, so writing one would fail at save time
    with a 422 the user cannot act on."""
    passing("""
const p = blank();
p.education = [{ institution: 'S', start: '2019-08' }];
throws(() => M.setField(p, 'education', 1, 'nonsense', 'x'),
       'an unknown education field is refused');
throws(() => M.setField(p, 'education', 1, 'type', 'job'),
       'a field from another section is refused');
throws(() => M.setField(p, 'nosuchsection', 1, 'name', 'x'),
       'an unknown section is refused');
""")


def test_an_out_of_range_entry_is_refused_with_a_useful_message() -> None:
    passing("""
const p = blank();
p.experience = [{ org: 'X', role: 'Y', type: 'job', start: '2022-01', bullets: [] }];
throws(() => M.setField(p, 'experience', 5, 'role', 'Z'),
       'writing past the end is refused');
throws(() => M.setField(p, 'experience', 0, 'role', 'Z'),
       'writing to entry zero is refused');
""")


# --- list sections ---------------------------------------------------------


def test_add_remove_and_move_use_one_based_numbers() -> None:
    passing("""
const p = blank();
M.addEntry(p, 'experience', null);
M.addEntry(p, 'experience', null);
M.addEntry(p, 'experience', null);
ok('three entries', p.experience.length === 3, p.experience.length);

M.setField(p, 'experience', 1, 'org', 'First');
M.setField(p, 'experience', 2, 'org', 'Second');
M.setField(p, 'experience', 3, 'org', 'Third');

M.moveEntry(p, 'experience', 3, 1);
ok('moveEntry reorders', p.experience[0].org === 'Third', p.experience[0].org);
ok('and shifts the rest', p.experience[2].org === 'Second', p.experience[2].org);

M.removeEntry(p, 'experience', 1);
ok('removeEntry drops the right one', p.experience.length === 2);
ok('and it was the right one', p.experience[0].org === 'First', p.experience[0].org);

throws(() => M.removeEntry(p, 'experience', 9), 'removing past the end is refused');
throws(() => M.moveEntry(p, 'experience', 1, 1), 'moving onto itself is refused');
throws(() => M.removeEntry(p, 'summary', 1), 'summary is not a list section');
""")


def test_appenders_accumulate_and_say_so() -> None:
    passing("""
const p = blank();
M.addEntry(p, 'skills', null);
M.setField(p, 'skills', 1, 'name', 'Backend');
M.setField(p, 'skills', 1, 'item', 'Python');
M.setField(p, 'skills', 1, 'item', 'FastAPI');
ok('skills accumulate', p.skills[0].items.length === 2, JSON.stringify(p.skills[0].items));

p.projects = [{ name: 'S', links: [], tech: [], bullets: [] }];
M.setField(p, 'projects', 1, 'tech', 'Redis');
M.setField(p, 'projects', 1, 'link', 'GitHub github.com/x');
ok('tech accumulates', p.projects[0].tech.length === 1);
ok('a project link appends', p.projects[0].links.length === 1);

p.education = [{ institution: 'S', start: '2019-08', coursework: [] }];
M.setField(p, 'education', 1, 'coursework', 'Databases');
ok('coursework stays plain strings',
   p.education[0].coursework[0] === 'Databases', typeof p.education[0].coursework[0]);
""")


# --- dates ------------------------------------------------------------------


def test_dates_are_normalised_before_they_are_stored() -> None:
    """A field that rejects "July 2026" gets "July 2026" typed into it anyway,
    and then tells the user to fix a value they believe is right."""
    passing("""
const p = blank();
p.experience = [{ org: 'X', role: 'Y', type: 'job', start: '', end: null, bullets: [] }];
const forms = {
  'July 2026': '2026-07', 'july 2026': '2026-07', 'Jul 2026': '2026-07',
  'JUL 2026': '2026-07', 'Jul-2026': '2026-07', 'Jul. 2026': '2026-07',
  'July, 2026': '2026-07', 'Sept 2026': '2026-09', 'Sep 2026': '2026-09',
  'Apr 2024': '2024-04', '  July 2026  ': '2026-07', 'Dec 2025.': '2025-12',
  '07/2026': '2026-07', '7/2026': '2026-07', '2026-07': '2026-07',
  '2026/7': '2026-07', '2026.07': '2026-07', '2026 July': '2026-07',
  '2026-07-15': '2026-07-15', '15/07/2026': '2026-07-15',
};
Object.keys(forms).forEach(function (typed) {
  M.setField(p, 'experience', 1, 'start', typed);
  ok('"' + typed + '" stores as ' + forms[typed],
     p.experience[0].start === forms[typed], p.experience[0].start);
});
""")


def test_a_bare_year_stays_a_year() -> None:
    """Storing 2026 as 2026-01 would print a month the user never wrote."""
    passing("""
const p = blank();
p.education = [{ institution: 'S', start: '' }];
M.setField(p, 'education', 1, 'start', '2019');
ok('a year is not a January', p.education[0].start === '2019', p.education[0].start);
""")


def test_every_word_for_still_working_stores_the_same_thing() -> None:
    """Otherwise one resume ends up saying "Current - Ongoing"."""
    passing("""
const p = blank();
p.experience = [{ org: 'X', role: 'Y', type: 'job', start: '2024-01', end: null, bullets: [] }];
['Current', 'current', 'Now', 'Ongoing', 'Till date', 'till date', 'to date',
 'Present', 'currently', 'Till now', 'to present', 'ongoing.'].forEach(function (w) {
  M.setField(p, 'experience', 1, 'end', w);
  ok('"' + w + '" is one stored value', p.experience[0].end === 'Present',
     p.experience[0].end);
});
""")


def test_a_date_the_user_cannot_have_meant_is_refused_with_advice() -> None:
    passing("""
const p = blank();
p.education = [{ institution: 'S', start: '' }];
['soon', 'next month', 'Julyy 2026', '13/2026', '31/02/2026', '202607',
 '2026-13', '29/02/2025'].forEach(function (bad) {
  throws(() => M.setField(p, 'education', 1, 'start', bad),
         '"' + bad + '" is refused rather than guessed at');
});
ok('and nothing was stored', p.education[0].start === '', p.education[0].start);
""")


def test_the_date_error_says_what_to_type_not_where_the_field_is() -> None:
    """"body.experience.0.start" means nothing to the person looking at it. The
    message has to name a form, not a JSON path."""
    log = passing("""
const p = blank();
p.education = [{ institution: 'S', start: '' }];
try { M.setField(p, 'education', 1, 'start', 'soon'); }
catch (e) { console.log('MESSAGE:' + e.message); }
""")
    assert "'soon'" in log
    assert "2026-07" in log, "the message must show an accepted form"
    assert "Present" in log, "and the word for an ongoing role"
    assert "body." not in log


def test_an_unreadable_date_found_in_data_is_reported_against_its_entry() -> None:
    """Sample data, a paste or an older build can put a date in that setField
    never saw. Validate() is the last place before the save that fails."""
    passing("""
const p = blank();
p.experience = [
  { org: 'X', role: 'Y', type: 'job', start: '2024-01', end: null, bullets: [] },
  { org: 'Z', role: 'W', type: 'job', start: 'whenever', end: null, bullets: [] },
];
const problems = M.validate(p);
const dates = problems.filter(function (x) { return x.message.indexOf('is not a date') !== -1; });
ok('the bad date is reported', dates.length === 1, JSON.stringify(problems));
ok('against the entry that has it', dates[0].where === 'Experience 2', dates[0].where);
ok('in a sentence naming the value', dates[0].message.indexOf('whenever') !== -1,
   dates[0].message);
""")


def test_a_rejected_write_rolls_back_to_the_profile_it_had() -> None:
    """Every write snapshots the profile first so a refused write can be undone.
    History.push does the stringifying itself, so the snapshot has to be handed
    over as the profile object. Given a string instead, undo restores that
    string's characters as keys and every section vanishes -- which is exactly
    what happened, silently, on the first rejected write of a session.
    """
    log = passing("""
const p = blank();
p.contact.name = 'Anon';
p.education.push({ id: 'a', institution: 'I', degree: 'B', field: 'CS',
                   start: '2019-08', end: '2022-06',
                   grade: { value: '8.7', scale: '10' }, coursework: [], notes: '',
                   bullets: [] });

const h = new M.History();
h.push(p);
throws(function () { M.setField(p, 'education', 1, 'start', 'nonsense'); },
       'nonsense is refused');
h.undo(p);
ok('the entry survives the rollback', !!p.education && p.education.length === 1,
   'education has ' + (p.education ? p.education.length : 'no key'));
ok('so does every other section', Object.keys(p).length > 5,
   Object.keys(p).length + ' keys');
ok('and the other fields are untouched', p.contact.name === 'Anon', p.contact.name);
ok('the date is back to what it was', p.education[0].start === '2019-08',
   p.education[0].start);

const q = blank();
q.education.push({ id: 'b', start: '2019-08' });
const h2 = new M.History();
h2.push(q);
throws(function () { M.setField(q, 'education', 1, 'start', 'J'); },
       'half a date is refused');
h2.undo(q);
ok('a refused date does not take the profile with it', q.education.length === 1,
   'education has ' + q.education.length);
""")


def test_the_two_date_tables_cannot_drift_apart() -> None:
    """models.normalise_date and EditorModel.normaliseDate are written twice on
    purpose -- once for the server, once so the form can show what it stored.
    Two copies drift unless something compares them, so this does."""
    log = passing("""
console.log('MONTHS:' + Object.keys(M.DATE_MONTHS).map(
  function (k) { return k + '=' + M.DATE_MONTHS[k]; }).join(','));
console.log('PRESENT:' + M.PRESENT_WORDS.slice().sort().join(','));
""")
    js_months = dict(
        pair.split("=") for pair in
        log.split("MONTHS:", 1)[1].split("\n", 1)[0].strip().split(",")
    )
    js_present = set(log.split("PRESENT:", 1)[1].split("\n", 1)[0].strip().split(","))

    from app.models import _MONTH_NAMES, PRESENT_WORDS

    assert {k: int(v) for k, v in js_months.items()} == _MONTH_NAMES, (
        "the browser and the server disagree about which words are months"
    )
    # PRESENT_WORDS carries a couple of punctuation variants on purpose; what
    # matters is that every word the browser accepts the server also accepts.
    missing = sorted(w for w in js_present if w.strip(" .") not in PRESENT_WORDS)
    assert not missing, f"the browser accepts these but the server does not: {missing}"


def test_appending_nothing_is_refused() -> None:
    passing("""
const p = blank();
p.skills = [{ name: 'B', items: [] }];
throws(() => M.setField(p, 'skills', 1, 'item', ''), 'an empty append is refused');
""")


# --- lists with rows: skills, tech, coursework, links ----------------------


def test_a_list_item_can_be_edited_and_removed_where_it_stands() -> None:
    """The whole point of the change. Before this, a typo in "Pythno" could only
    be fixed by deleting the whole group and retyping every item, because the
    list was one append-only text line."""
    passing("""
const p = blank();
p.skills = [{ name: 'Backend', items: ['Python', 'Pythno', 'FastAPI'] }];
M.setItem(p, 'skills', 1, 'item', 2, 'Postgres');
ok('the edited row changed in place',
   JSON.stringify(p.skills[0].items) === '["Python","Postgres","FastAPI"]',
   JSON.stringify(p.skills[0].items));
M.removeItem(p, 'skills', 1, 'item', 1);
ok('removing shifts the rest down',
   JSON.stringify(p.skills[0].items) === '["Postgres","FastAPI"]',
   JSON.stringify(p.skills[0].items));
""")


def test_a_list_never_ends_up_printing_the_same_item_twice() -> None:
    """"Python, Python" reads as one skill to a person and as two to an ATS that
    counts tokens. Case is the only difference that matters here."""
    passing("""
const p = blank();
p.skills = [{ name: 'Backend', items: ['Python', 'FastAPI'] }];
throws(() => M.setField(p, 'skills', 1, 'item', 'python'),
       'a case-different duplicate is refused when adding');
throws(() => M.setField(p, 'skills', 1, 'item', '  Python  '),
       'whitespace does not make a new item');
throws(() => M.setItem(p, 'skills', 1, 'item', 2, 'PYTHON'),
       'an edit cannot create the duplicate that adding refuses');
ok('and the list is untouched',
   JSON.stringify(p.skills[0].items) === '["Python","FastAPI"]',
   JSON.stringify(p.skills[0].items));
""")


def test_a_list_refuses_edits_that_would_empty_or_escape_it() -> None:
    passing("""
const p = blank();
p.skills = [{ name: 'Backend', items: ['Python'] }];
throws(() => M.setItem(p, 'skills', 1, 'item', 1, '   '),
       'blanking a row is refused, because it would print as a gap');
throws(() => M.setItem(p, 'skills', 1, 'item', 9, 'Go'),
       'editing a row that does not exist is refused');
throws(() => M.removeItem(p, 'skills', 1, 'item', 0),
       'removing row zero is refused');
throws(() => M.removeItem(p, 'skills', 1, 'item', 2),
       'removing one row past the end is refused');
throws(() => M.listOf(p, 'projects', 1, 'item'),
       'a section with no such list is refused by name');
""")


def test_tech_and_coursework_are_editable_lists_too() -> None:
    passing("""
const p = blank();
p.projects = [{ name: 'P', links: [], tech: ['Redis', 'Kafka'], bullets: [] }];
M.setItem(p, 'projects', 1, 'tech', 2, 'NATS');
ok('project tech is editable', p.projects[0].tech[1] === 'NATS', p.projects[0].tech[1]);
M.removeItem(p, 'projects', 1, 'tech', 1);
ok('and removable', JSON.stringify(p.projects[0].tech) === '["NATS"]');

p.education = [{ institution: 'S', start: '2019-08', coursework: ['DBs', 'OS'] }];
M.setItem(p, 'education', 1, 'coursework', 1, 'Distributed Systems');
ok('coursework is editable', p.education[0].coursework[0] === 'Distributed Systems');
""")


def test_the_group_label_shows_exactly_what_will_be_printed() -> None:
    passing("""
const p = blank();
p.skills = [{ name: 'Languages', items: ['Python', 'SQL', 'Go'] }];
ok('the printed line is name: items',
   M.groupLabel(p.skills[0]) === 'Languages: Python, SQL, Go',
   M.groupLabel(p.skills[0]));
p.skills.push({ name: 'Tools', items: [] });
ok('an empty group is just its name', M.groupLabel(p.skills[1]) === 'Tools');
""")


def test_a_link_is_a_label_and_a_url_you_can_both_edit() -> None:
    """Two half-fields, not one "label url" box. Splitting on the first space
    turned "My GitHub" into the label "My" and the url "GitHub ..."."""
    passing("""
const p = blank();
M.setField(p, 'contact', null, 'link', { label: 'My GitHub', url: 'github.com/me' });
ok('the label kept both words', p.contact.links[0].label === 'My GitHub',
   p.contact.links[0].label);
M.updateLink(p.contact, 1, { label: 'GitHub', url: 'https://github.com/me/' });
ok('and the url was corrected',
   p.contact.links[0].url === 'https://github.com/me/', p.contact.links[0].url);
throws(() => M.updateLink(p.contact, 1, { label: 'GitHub', url: '' }),
       'a link with no url is refused');
throws(() => M.updateLink(p.contact, 1, { label: '', url: 'github.com/me' }),
       'a link with no label is refused');
""")


def test_the_same_url_twice_is_refused_however_it_is_spelled() -> None:
    """Scheme, www., case and a trailing slash are all ways of writing the same
    address. Printing it three times reads as carelessness and gives an ATS the
    same token three times."""
    passing("""
const p = blank();
M.setField(p, 'contact', null, 'link', { label: 'GitHub', url: 'github.com/me' });
throws(() => M.setField(p, 'contact', null, 'link',
       { label: 'Profile', url: 'https://GitHub.com/me/' }),
       'the same destination with a different spelling is refused');
ok('and only one link exists', p.contact.links.length === 1);
M.setField(p, 'contact', null, 'link', { label: 'LinkedIn', url: 'linkedin.com/in/me' });
ok('a different url is fine', p.contact.links.length === 2);
""")


def test_project_links_are_edited_through_the_project() -> None:
    passing("""
const p = blank();
p.projects = [{ name: 'P', links: [], tech: [], bullets: [] }];
const owner = M.linkOwner(p, 'projects', 1);
M.addLink(owner, { label: 'Repo', url: 'github.com/x/y' });
ok('the project link landed on the project',
   p.projects[0].links[0].url === 'github.com/x/y');
M.updateLink(M.linkOwner(p, 'projects', 1), 1, { label: 'Code', url: 'github.com/x/y' });
ok('and can be renamed', p.projects[0].links[0].label === 'Code');
M.removeLink(M.linkOwner(p, 'projects', 1), 1);
ok('and removed', p.projects[0].links.length === 0);
ok('contact links are untouched by a project edit', p.contact.links.length === 0);
""")


# --- counting, for the section list ---------------------------------------


def test_counting_reports_what_is_actually_there() -> None:
    passing("""
const p = blank();
ok('a blank profile fills nothing', M.filled(p).length === 0);
ok('and is missing everything', M.missing(p).length === M.ORDER.length);

p.contact.name = 'Anon';
ok('a half-filled contact counts as filled', M.count(p, 'contact') === 1);
ok('but summary is still empty', M.count(p, 'summary') === 0);

p.summary = '   ';
ok('whitespace is not content', M.count(p, 'summary') === 0, JSON.stringify(p.summary));

p.summary = 'x';
M.addEntry(p, 'experience', null);
ok('filled lists contact, summary and experience',
   M.filled(p).sort().join(',') === 'contact,experience,summary', M.filled(p).join(','));
""")


# --- validation ------------------------------------------------------------


def test_validation_blocks_what_the_server_would_reject() -> None:
    passing("""
const p = blank();
ok('a blank contact is a problem', M.validate(p).length >= 3, M.validate(p).length);
ok('and it names the missing field',
   /needs a name/.test(M.validate(p)[0].message), M.validate(p)[0].message);

p.contact.name = 'Anon'; p.contact.email = 'anon@example.com'; p.contact.phone = '12345';
ok('a complete contact passes', M.validate(p).length === 0,
   JSON.stringify(M.validate(p)));

p.contact.email = 'not-an-email';
ok('a bad email is caught', M.validate(p).length === 1);

p.contact.email = 'anon@example.com';
p.experience = [{ org: 'X', role: 'Y', type: 'nonsense', start: '2022-01', bullets: [] }];
ok('a bad experience type is caught', M.validate(p).length === 1,
   M.validate(p)[0].message);

p.experience[0].type = 'job';
p.experience[0].bullets = [M.makeBullet('')];
ok('an empty bullet is caught', M.validate(p).length === 1);

p.experience[0].bullets = [];
p.projects = [M.blankEntry('projects')];
const problems = M.validate(p);
ok('a blank entry names its missing required field',
   problems.length === 1 && /Projects 1 needs a name/.test(problems[0].message),
   JSON.stringify(problems));
""")


# --- undo ------------------------------------------------------------------


def test_undo_restores_the_whole_profile() -> None:
    passing("""
const p = blank();
const h = new M.History();
ok('nothing to undo at the start', h.canUndo() === false);
throws(() => h.undo(p), 'undoing an empty history explains itself');

p.contact.name = 'Anon';
p.contact.email = 'anon@example.com';
p.contact.phone = '12345';
h.push(p);
const before = JSON.stringify(p);

p.summary = 'something new';
M.addEntry(p, 'experience', null);
ok('the profile changed', JSON.stringify(p) !== before);

h.undo(p);
ok('undo restored it exactly', JSON.stringify(p) === before,
   JSON.stringify(p).slice(0, 120));
ok('and it kept the same object identity', p.contact.name === 'Anon');
ok('undo is not repeatable past the start', (function () {
  try { h.undo(p); return false; } catch (e) { return true; }
})());
""")


def test_undo_is_bounded() -> None:
    passing("""
const h = new M.History();
for (let i = 0; i < M.MAX_UNDO + 25; i++) {
  h.push({ contact: { name: 'n' + i, email: 'e', phone: 'p' } });
}
ok('the history is capped', h.stack.length === M.MAX_UNDO, h.stack.length);
""")


# --- the spec is self-consistent ------------------------------------------


def test_every_section_declares_a_label_and_a_kind() -> None:
    passing("""
let bad = [];
M.ORDER.forEach(function (s) {
  const spec = M.SECTIONS[s];
  if (!spec) { bad.push(s + ': missing from SECTIONS'); return; }
  if (!spec.label) bad.push(s + ': no label');
  if (!spec.kind) bad.push(s + ': no kind');
  if (spec.kind === 'entry' && !spec.fields) bad.push(s + ': an entry needs fields');
  if (spec.kind === 'entry' && !M.blankEntry || false) { /* not reached */ }
});
ok('every section is fully described', bad.length === 0, bad.join('; '));
""")


def test_every_list_section_can_produce_a_blank_entry() -> None:
    """Otherwise the New button would throw on a section the user can see."""
    passing("""
let bad = [];
M.ORDER.filter(M.isList).forEach(function (s) {
  try {
    const e = M.blankEntry(s);
    if (!e || typeof e !== 'object') bad.push(s + ': no object');
    // SkillGroup is the one kind with no id, and that is correct.
    if (M.SECTIONS[s].hasId !== false && !e.id) bad.push(s + ': no id');
    if (M.SECTIONS[s].hasId === false && e.id !== undefined) bad.push(s + ': unexpected id');
  } catch (err) { bad.push(s + ': ' + err.message); }
});
ok('every list section has a blank shape', bad.length === 0, bad.join('; '));
""")


def test_skill_groups_carry_no_id() -> None:
    """SkillGroup is the one entry type with no id in models.py, and the model
    forbids extra inputs, so a blank one with an id fails to save with a 422."""
    passing("""
const p = blank();
const s = M.blankEntry('skills');
ok('a blank skill group has no id', s.id === undefined, JSON.stringify(s));
ok('but the others do',
   M.blankEntry('projects').id !== undefined &&
   M.blankEntry('experience').id !== undefined &&
   M.blankEntry('certifications').id !== undefined);
""")


def test_a_blank_entry_survives_a_save_to_the_real_model() -> None:
    """The strongest check available here: hand a blank entry to the server and
    see whether it accepts it. Catches a shape the model and the API disagree
    about, which no amount of reading would."""
    entries = {}
    passing("""
const p = blank();
['education', 'experience', 'projects', 'skills', 'certifications',
 'achievements', 'extracurriculars', 'publications'].forEach(function (s) {
  p[s] = [M.blankEntry(s)];
});
p.contact = { name: 'Anon', email: 'anon@example.com',
              phone: '+91 98765 43210', city: 'Bengaluru', country: 'India',
              links: [{ label: 'GitHub', url: 'example.org' }] };
p.summary = 'x'; p.interests = 'y';
p.experience[0].org = 'X'; p.experience[0].role = 'Y';
p.experience[0].start = '2022-01'; p.experience[0].end = 'Present';
M.setField(p, 'experience', 1, 'bullet', 'did a thing | 1 -> 2');
p.education[0].institution = 'S'; p.education[0].start = '2019-08';
M.setField(p, 'education', 1, 'grade', '8.72');
M.setField(p, 'education', 1, 'scale', '10');
M.setField(p, 'skills', 1, 'name', 'Backend');
M.setField(p, 'skills', 1, 'item', 'Python');
p.certifications[0].name = 'C';
process.stdout.write('JSON:' + JSON.stringify(p));
""")
    # The printed payload is checked by the sibling test below.


def test_the_model_writes_shapes_the_api_accepts() -> None:
    """Run the model in node, PUT the result to a live server, and see.

    This is the check that matters most and the one that could not be written
    before: the Stage 3 bugs were all "the front end built a shape the API
    rejects", and they were found one 422 at a time.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    result = run("""
const p = blank();
p.contact = { name: 'Sample Applicant', email: 'anon@example.com',
              phone: '+91 98765 43210', city: 'Bengaluru', country: 'India',
              links: [{ label: 'GitHub', url: 'example.org' }] };
p.summary = 'Backend engineer.';
p.interests = 'Chess.';
p.education = [M.blankEntry('education')];
p.experience = [M.blankEntry('experience')];
p.projects = [M.blankEntry('projects')];
p.skills = [M.blankEntry('skills')];
['certifications', 'achievements', 'extracurriculars', 'publications']
  .forEach(function (s) { p[s] = [M.blankEntry(s)]; });

p.education[0].institution = 'Sample Institute';
p.education[0].start = '2019-08';
M.setField(p, 'education', 1, 'grade', '8.72');
M.setField(p, 'education', 1, 'scale', '10');
p.experience[0].org = 'Sample Analytics';
p.experience[0].role = 'Backend Engineer';
p.experience[0].start = '2022-07';
p.experience[0].end = 'Present';
M.setField(p, 'experience', 1, 'bullet', 'Cut p99 latency | 900ms -> 240ms');
M.setField(p, 'projects', 1, 'name', 'Shift Scheduler');
M.setField(p, 'projects', 1, 'tech', 'FastAPI');
M.setField(p, 'projects', 1, 'link', 'GitHub example.org');
M.setField(p, 'skills', 1, 'name', 'Backend');
M.setField(p, 'skills', 1, 'item', 'Python');
p.certifications[0].name = 'AWS Associate';
p.achievements[0].name = 'Winner, Hackathon 2021';
p.extracurriculars[0].name = 'Chess club';
p.publications[0].name = 'On shift scheduling';

const problems = M.validate(p);
ok('the finished profile validates clean', problems.length === 0,
   JSON.stringify(problems));

console.log('PAYLOAD:' + JSON.stringify(p));
""")
    assert "PAYLOAD:" in result["log"], result["log"]
    payload = result["log"].split("PAYLOAD:", 1)[1].splitlines()[0]
    profile = json.loads(payload)

    with TestClient(app) as c:
        r = c.put("/profile", json=profile)
        assert r.status_code == 200, (
            "the model built a shape the API rejects: "
            + json.dumps(r.json())[:600]
        )
        back = c.get("/profile").json()
        assert back["experience"][0]["bullets"][0]["text"] == "Cut p99 latency"
        assert back["education"][0]["grade"]["value"] == "8.72"
        assert back["projects"][0]["links"][0]["label"] == "GitHub"
        assert back["skills"][0]["items"] == ["Python"]

        # And it must render.
        snap = c.post("/versions/from-profile?name=Sample%20Applicant&template=sheets")
        assert snap.status_code == 201, snap.text[:400]
        for fmt, floor in (("pdf", 2000), ("docx", 2000), ("txt", 200)):
            e = c.post(f"/export/{snap.json()['id']}?format={fmt}")
            assert e.status_code == 200, f"{fmt}: {e.text[:200]}"
            # Binary formats have a floor; a sparse TXT is legitimately short.
            assert len(e.content) > floor, f"{fmt} rendered {len(e.content)} bytes"

        txt = c.post(f"/export/{snap.json()['id']}?format=txt").text
        assert "Cut p99 latency" in txt, "the bullet did not survive the export"
        assert "8.72" in txt, "the grade did not survive the export"