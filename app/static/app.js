/* resume-builder: a single-page terminal UI.
 *
 * Rules this file obeys, and why:
 *  - NEVER innerHTML. Every character reaches the DOM through textContent or
 *    createTextNode. A terminal echoes whatever the user typed and whatever the
 *    server returned, which is exactly how terminal UIs get turned into an XSS
 *    vector. `tests/test_frontend.py` greps for innerHTML to keep it that way.
 *  - No eval, no Function constructor, no external scripts.
 *  - No mouse handlers. The navbar items have no click listener: they type a
 *    command into the terminal and run it, so the terminal stays the only
 *    interface and the navbar is purely a shortcut surface.
 *  - Every command runs inside a try/catch boundary. A thrown error prints a
 *    line and the app keeps running.
 */
'use strict';

(function () {

// ---------------------------------------------------------------- constants

const THEMES = ['amber', 'green', 'matrix', 'paper'];
const FORMATS = ['pdf', 'docx', 'txt'];

// Menu order for the navbar. This is navigation order only; the order sections
// appear on the rendered resume comes from rules.json section_order, server-side.
const SECTION_ORDER = [
  'contact', 'summary', 'experience', 'projects',
  'skills', 'education', 'certifications', 'achievements',
  'extracurriculars', 'publications',
];

// list:false sections hold exactly one object; list:true hold an array.
const SECTIONS = {
  contact:         { list: false, fields: ['name', 'email', 'phone', 'city', 'country', 'link'] },
  summary:         { list: false, fields: ['text'] },
  education:       { list: true,  fields: ['institution', 'degree', 'field', 'start', 'end', 'grade', 'scale', 'course'] },
  experience:      { list: true,  fields: ['org', 'role', 'type', 'location', 'start', 'end', 'bullet'] },
  projects:        { list: true,  fields: ['name', 'role', 'start', 'end', 'tech', 'bullet', 'link'] },
  skills:          { list: true,  fields: ['group', 'item'] },
  certifications:  { list: true,  fields: ['name', 'issuer', 'date'] },
  achievements:    { list: true,  fields: ['name', 'date'] },
  extracurriculars:{ list: true,  fields: ['name'] },
  publications:    { list: true,  fields: ['name', 'url'] },
};

// What each section is FOR, and the exact next command to type.
//
// This exists because of a real usability failure: clicking "contact" in the
// navbar dropped you into a directory and told you nothing. Navigating must
// always say what the place is for and hand you the next command.
const SECTION_INFO = {
  contact: {
    what: 'How employers reach you. This sits at the very top of the resume.',
    do: 'draft contact',
    then: 'then type name / email / phone / city, one per line, then done',
  },
  summary: {
    what: 'Two or three lines saying who you are and your strongest evidence.',
    do: 'draft summary',
    then: 'then type: text <your summary>, then done',
  },
  experience: {
    what: 'Jobs you were paid for. One entry per role, most recent first.',
    do: 'draft experience',
    then: 'then type org / role / start / end, then one bullet per line',
    tip: 'bullets should carry the numbers — impact, scale, speed, cost',
  },
  projects: {
    what: 'Things you built. Strong for students and for roles with little experience.',
    do: 'draft projects',
    then: 'then type name / tech / start / end, then one bullet per line',
    tip: 'say what problem it solved and what changed, not just what you used',
  },
  skills: {
    what: 'Your toolkit, grouped. Recruiters and ATS both scan this.',
    do: 'draft skills',
    then: 'then type group <name>, then item <skill> for each one, then done',
  },
  education: {
    what: 'Degree, grades and coursework. Leads the resume for students.',
    do: 'draft education',
    then: 'then type institution / degree / start / end / grade / scale, then done',
    tip: 'always give the scale — "8.7/10", never a bare 8.7',
  },
  certifications: {
    what: 'Certificates and courses, with who issued them and when.',
    do: 'draft certifications',
    then: 'then type name / issuer / date, then done',
  },
  achievements: {
    what: 'Awards, competitions, scholarships. A strong one-line proof.',
    do: 'draft achievements',
    then: 'then type name, then done',
  },
  extracurriculars: {
    what: 'Clubs, volunteering, sports. Only if it says something about you.',
    do: 'draft extracurriculars',
    then: 'then type name, then done',
  },
  publications: {
    what: 'Papers and talks, if you have any.',
    do: 'draft publications',
    then: 'then type name / url, then done',
  },
};

// Fields that append to an array instead of replacing a scalar.
//
// `bullet` is the odd one out: the API models a bullet as an object with
// raw_facts and text, not a string. Appending a bare string produced a payload
// the server rejected with a 422, and printing one showed "[object Object]".
const APPENDERS = { bullet: 'bullets', course: 'coursework', tech: 'tech', item: 'items' };
const APPENDER_KIND = { bullet: 'bullet', course: 'string', tech: 'string', item: 'string' };

const bulletText = (b) => (b && typeof b === 'object' ? (b.text || '') : String(b || ''));

const EXperience_TYPES = ['job', 'internship', 'freelance'];

const BANNER = [
  '  ___  ___  _  _  ___  ___  ___  ___  ___  ___ ',
  ' |   \\|   || \\| |/ __|/ __|/ _ \\| _ \\/ __|/ _ \\',
  ' | |) | | || .  | (__| (__|   /|   / (__|   /',
  ' |___/|___||_|\\_|\\___|\\___|_|_|\\_|\\___|_|\\_\\',
].join('\n');

const MAX_UNDO = 60;
const SAVE_DEBOUNCE_MS = 800;

const EMPTY_PROFILE = () => ({
  contact: { name: '', email: '', phone: '', links: [] },
  summary: '', education: [], experience: [], projects: [], skills: [],
  certifications: [], achievements: [], extracurriculars: [], publications: [],
});

// A deliberately complete, clearly fictional resume for `demo`, so a newcomer
// can see the shape of a finished one before filling their own.
const SAMPLE_PROFILE = {
  contact: {
    name: 'Dusht', email: 'dusht@example.com', phone: '+91 98765 43210',
    city: 'Bengaluru', country: 'India',
    links: [
      { label: 'GitHub', url: 'github.com/dusht' },
      { label: 'LinkedIn', url: 'linkedin.com/in/dusht' },
    ],
  },
  summary:
    'Backend engineer with 3 years in Python and Postgres, most recently owning '
    + 'the payment path for a staffing product used by 12 retail stores.',
  education: [{
    institution: 'Sample Institute of Technology', degree: 'B.E. Computer Science',
    field: 'Computer Science', start: '2019-08', end: '2022-06',
    grade: { value: '8.72', scale: '10' },
    coursework: ['Databases', 'Distributed Systems'],
  }],
  experience: [{
    org: 'Sample Analytics', role: 'Backend Engineer', type: 'job',
    location: 'Bengaluru', start: '2022-07', end: 'Present',
    bullets: [
      { raw_facts: '900ms -> 240ms', text:
        'Cut p99 checkout latency from 900ms to 240ms by adding Redis read-through caching on the payment-intent path.' },
      { raw_facts: '11 -> 15, 4 services, no downtime', text:
        'Migrated Postgres 11 to 15 across 4 services using logical replication, with zero customer-visible downtime.' },
      { raw_facts: '5 -> 12 engineers', text:
        'Mentored 5 engineers into owning the settlement service, growing that team to 12 without extra headcount.' },
    ],
  }],
  projects: [{
    name: 'Shift Scheduler', role: 'Solo build',
    links: [{ label: 'GitHub', url: 'github.com/dusht/scheduler' }],
    start: '2021-01', end: '2021-06',
    tech: ['FastAPI', 'PostgreSQL', 'Celery', 'Redis'],
    bullets: [
      { raw_facts: '12 stores, 4h -> 30s', text:
        'Built a shift scheduler now used by 12 stores to publish weekly rosters in under 30 seconds, down from 4 hours.' },
    ],
  }],
  skills: [
    { name: 'Languages', items: ['Python', 'SQL', 'Go'] },
    { name: 'Backend', items: ['FastAPI', 'Django', 'Celery', 'Redis'] },
    { name: 'Data', items: ['PostgreSQL', 'Kafka', 'MongoDB'] },
  ],
  certifications: [{
    name: 'AWS Certified Solutions Architect - Associate',
    issuer: 'Amazon Web Services', date: '2024-03',
  }],
  achievements: [{ name: 'Winner, Hackathon 2021 - 1st of 240 teams' }],
  extracurriculars: [], publications: [],
  personal_details: {},
};

// ---------------------------------------------------------------- state

const state = {
  profile: null,
  section: null,      // what `cd` selected
  draft: null,        // { section, entry, index }
  history: [],
  histIndex: -1,
  undo: [],
  previewOn: false,
  previewSeq: 0,
  dirty: false,
  lastSnapshot: null,
};

const el = {
  navbar: document.getElementById('navbar'),
  nbItems: document.getElementById('nbItems'),
  nbStatus: document.getElementById('nbStatus'),
  scrollback: document.getElementById('scrollback'),
  form: document.getElementById('promptForm'),
  input: document.getElementById('cmd'),
  promptPath: document.getElementById('promptPath'),
  pane: document.getElementById('previewPane'),
  frame: document.getElementById('previewFrame'),
  meta: document.getElementById('previewMeta'),
};

// ---------------------------------------------------------------- output

function out(text, cls) {
  const div = document.createElement('div');
  div.className = 'line ' + (cls || 'out');
  div.textContent = text;           // the only way text enters the DOM
  el.scrollback.appendChild(div);
  el.scrollback.scrollTop = el.scrollback.scrollHeight;
  return div;
}
// Guarded: passing a bare string here once threw "forEach is not a function"
// in the middle of a command. Treat anything non-array as a single line.
const outLines = (arr, cls) =>
  (Array.isArray(arr) ? arr : [String(arr)]).forEach((l) => out(l, cls));

function errorOut(text) { out(text, 'err'); }
function dim(text)     { out(text, 'dim'); }
function ok(text)      { out(text, 'ok'); }

function table(rows, cols) {
  const width = cols.map((c) => Math.max(...rows.map((r) => String(r[c] ?? '').length), c.length));
  const line = (vals) => vals.map((v, i) => String(v ?? '').padEnd(width[i])).join('  ');
  out(line(cols), 'dim');
  rows.forEach((r) => out(line(cols.map((c) => r[c])), 'out'));
}

// ---------------------------------------------------------------- storage
// localStorage throws in some private-browsing modes. Never let that kill boot.

const store = {
  get(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (_) { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; }
    catch (_) { return false; }
  },
  del(key) {
    try { localStorage.removeItem(key); } catch (_) { /* ignore */ }
  },
};

// ---------------------------------------------------------------- network

async function api(path, options) {
  let resp;
  try {
    resp = await fetch(path, options);
  } catch (err) {
    throw new Error('cannot reach the server — is uvicorn still running? (' + err.message + ')');
  }
  const ctype = resp.headers.get('content-type') || '';
  if (!resp.ok) {
    let detail = 'HTTP ' + resp.status;
    if (ctype.includes('application/json')) {
      try {
        const body = await resp.json();
        if (body && body.detail) {
          if (typeof body.detail === 'string') detail = body.detail;
          else if (Array.isArray(body.detail)) {
            detail = body.detail.map((d) => (d.loc ? d.loc.join('.') + ': ' : '') + d.msg).join('; ');
          }
        }
      } catch (_) { /* keep the status line */ }
    }
    const e = new Error(detail);
    e.status = resp.status;
    throw e;
  }
  return resp;
}

const saveProfile = (p) =>
  api('/profile', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(p),
  });

// ---------------------------------------------------------------- helpers

const clone = (v) =>
  (typeof structuredClone === 'function')
    ? structuredClone(v)
    : JSON.parse(JSON.stringify(v));

function tokenize(line) {
  const out_ = [];
  let cur = '';
  let quote = null;
  for (const ch of line) {
    if (quote) {
      if (ch === quote) quote = null; else cur += ch;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
    } else if (/\s/.test(ch)) {
      if (cur) { out_.push(cur); cur = ''; }
    } else cur += ch;
  }
  if (cur) out_.push(cur);
  return out_;
}

function levenshtein(a, b) {
  const m = a.length, n = b.length;
  if (!m) return n;
  if (!n) return m;
  let prev = Array.from({ length: n + 1 }, (_, i) => i);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) {
      cur[j] = Math.min(
        prev[j] + 1,
        cur[j - 1] + 1,
        prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
    }
    prev = cur;
  }
  return prev[n];
}

function didYouMean(input, candidates) {
  let best = null, bestScore = Infinity;
  for (const c of candidates) {
    const d = levenshtein(input.toLowerCase(), c.toLowerCase());
    if (d < bestScore) { bestScore = d; best = c; }
  }
  const tolerance = Math.max(2, Math.floor(input.length / 3));
  return bestScore <= tolerance ? best : null;
}

const sectionsOf = (profile) => SECTION_ORDER.filter((s) => s in SECTIONS);
const entriesFor = (section) => {
  if (!state.profile) return [];
  const value = state.profile[section];
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value : [value];
};
const isList = (section) => !!(SECTIONS[section] && SECTIONS[section].list);

// Does this section hold anything a reader would see? An empty contact object
// still counts as one "entry", which made a blank profile look non-empty and
// stopped `demo` from loading.
function hasContent(section) {
  const entries = entriesFor(section);
  if (!entries.length) return false;
  return entries.some((e) => {
    if (!e || typeof e !== 'object') return Boolean(String(e).trim());
    return Object.keys(e).some((k) => {
      const v = e[k];
      if (v === null || v === undefined) return false;
      if (Array.isArray(v)) return v.length > 0;
      if (typeof v === 'object') return Object.values(v).some(
        (x) => (Array.isArray(x) ? x.length > 0 : Boolean(String(x || '').trim())));
      return String(v).trim() !== '';
    });
  });
}

// Entries a reader would actually see. A singleton section holding only empty
// strings is zero, not one.
function visibleCount(section) {
  return hasContent(section) ? entriesFor(section).length : 0;
}

const profileIsEmpty = () =>
  !state.profile || sectionsOf(state.profile).every((s) => !hasContent(s));

// Printed every time you arrive somewhere. Answers the three questions a new
// user actually has: what is this, what goes in it, and what do I type now.
function guide(section) {
  const info = SECTION_INFO[section];
  if (!info) return;
  const count = entriesFor(section).length;
  const filled = hasContent(section);

  out('  ' + info.what, 'hint');

  if (!filled) {
    out('  next: ' + info.do, 'hint');
    out('  ' + info.then, 'dim');
  } else {
    out('  ' + count + ' entr' + (count > 1 ? 'ies' : 'y') + ' here.', 'dim');
    out('  view: `cat ' + section + '`    add another: `' + info.do + '`', 'hint');
  }
  if (info.tip) out('  tip: ' + info.tip, 'dim');
  if (!isList(section)) {
    out('  change it any time: `edit ' + section + ' <field> <value>`', 'dim');
  } else {
    out('  reorder: `mv 1 down`    delete: `rm 1`', 'dim');
  }
}

function describeEntry(section, entry) {
  if (section === 'contact') return [entry.name || '(no name)'];
  if (section === 'summary') {
    const t = String(entry.text || '').trim();
    return [t.length > 58 ? t.slice(0, 58) + '…' : t || '(empty)'];
  }
  if (section === 'education') return [entry.institution || '(no institution)', entry.degree || ''];
  if (section === 'experience') return [entry.role || '(no role)', entry.org || ''];
  if (section === 'projects') return [entry.name || '(no name)', entry.role || ''];
  if (section === 'skills') return [(entry.name || '') + ':', (entry.items || []).join(', ')];
  return [entry.name || '(no name)', entry.issuer || entry.date || ''];
}

// ---------------------------------------------------------------- undo

function snapshotForUndo() {
  if (!state.profile) return;
  state.undo.push({ profile: clone(state.profile), section: state.section });
  if (state.undo.length > MAX_UNDO) state.undo.shift();
}

async function undo() {
  if (!state.undo.length) { dim('nothing to undo'); return; }
  const prev = state.undo.pop();
  state.profile = prev.profile;
  state.section = prev.section;
  state.draft = null;
  await pushSave('undo');
  ok('undone');
}

// ---------------------------------------------------------------- saving

let saveTimer = null;

function setStatus(text, kind) {
  el.nbStatus.textContent = text;
  el.nbStatus.setAttribute('data-state', kind || '');
}

async function pushSave(reason) {
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
  if (!state.profile) return;
  setStatus('saving…', 'saving');
  try {
    await saveProfile(state.profile);
    state.dirty = false;
    setStatus('saved', 'saved');
  } catch (err) {
    state.dirty = true;
    setStatus('save failed', 'error');
    errorOut('could not save: ' + err.message);
    errorOut('your edits are still in this tab — run `save` to retry');
  }
  refreshPreviewSoon();
}

function scheduleSave() {
  state.dirty = true;
  setStatus('unsaved changes', 'dirty');
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { saveTimer = null; pushSave('debounce'); }, SAVE_DEBOUNCE_MS);
}

// ---------------------------------------------------------------- navbar

function refreshNavbar() {
  el.nbItems.textContent = '';

  const add = (label, command, count, isCurrent) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'nb-btn';
    btn.setAttribute('data-cmd', command);
    btn.title = command;                 // hover text, without a hover handler
    btn.setAttribute('aria-current', String(!!isCurrent));

    const text = document.createElement('span');
    text.textContent = label;
    btn.appendChild(text);
    if (count !== null && count !== undefined) {
      const c = document.createElement('span');
      c.className = 'nb-count';
      c.textContent = String(count);
      btn.appendChild(c);
    }

    // No click listener that acts directly: it types the command and runs it,
    // so the terminal stays the only interface and the echo is visible.
    btn.addEventListener('click', () => runTyped(command));
    el.nbItems.appendChild(btn);
  };

  // "home" stands in for the desktop: every section in one place.
  add('home', 'home', null, !state.section);
  if (state.profile) {
    for (const section of sectionsOf(state.profile)) {
      add(section, 'cd ' + section, visibleCount(section), state.section === section);
    }
  }
  add('notes', 'notes', notesCount(), false);
  add('hint', 'hint', null, false);
  add('help', 'help', null, false);
  add('preview', 'preview', null, state.previewOn);
}

const notesCount = () => (store.get('rb.notes', []) || []).length;

function runTyped(command) {
  el.input.value = command;
  el.input.focus();
  runLine(command);
}

// ---------------------------------------------------------------- preview

let previewTimer = null;

function refreshPreviewSoon() {
  if (!state.previewOn) return;
  if (previewTimer) clearTimeout(previewTimer);
  previewTimer = setTimeout(() => { previewTimer = null; doPreview(); }, 700);
}

async function doPreview() {
  if (!state.profile) return;
  const seq = ++state.previewSeq;
  try {
    const resp = await fetch('/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(state.profile),
    });
    if (!resp.ok) {
      el.meta.textContent = 'preview failed (HTTP ' + resp.status + ')';
      el.meta.setAttribute('data-budget', 'over');
      return;
    }
    const pages = resp.headers.get('X-Pages') || '?';
    const limit = resp.headers.get('X-Page-Limit') || '?';
    const budget = resp.headers.get('X-Page-Budget') || 'ok';
    const density = resp.headers.get('X-Density') || '';
    el.meta.textContent =
      pages + '/' + limit + ' pages' +
      (budget === 'over' ? '  OVER BUDGET — trim content' : '  ok') +
      (density && density !== 'normal' ? '  [' + density + ']' : '');
    el.meta.setAttribute('data-budget', budget);

    if (seq !== state.previewSeq) return;   // a newer render already won
    const blob = await resp.blob();
    if (seq !== state.previewSeq) return;
    if (el.frame.src.startsWith('blob:')) URL.revokeObjectURL(el.frame.src);
    el.frame.src = URL.createObjectURL(blob);
  } catch (err) {
    el.meta.textContent = 'preview failed';
    el.meta.setAttribute('data-budget', 'over');
  }
}

function togglePreview(on) {
  state.previewOn = on === undefined ? !state.previewOn : !!on;
  el.pane.hidden = !state.previewOn;
  if (state.previewOn) { doPreview(); dim('preview on — refreshes as you type'); }
  else dim('preview off');
}

// ---------------------------------------------------------------- drafts

function startDraft(section) {
  if (!SECTIONS[section]) {
    errorOut('no such section: ' + section);
    out('valid: ' + Object.keys(SECTIONS).join(', '), 'dim');
    return;
  }
  const editing = isList(section) && state.section === section;
  if (isList(section) && !state.section) {
    dim('cd ' + section + ' first, or just start drafting straight away');
  }
  state.draft = {
    section: section,
    entry: editing ? {} : (isList(section) ? {} : clone(entriesFor(section)[0] || {})),
    listMode: isList(section),
  };
  ok('drafting ' + section + ' — one field per line, then `done`');
  dim('fields: ' + SECTIONS[section].fields.join(', '));
}

function applyField(section, field, value) {
  const draft = state.draft;
  const entry = draft.entry;

  if (field === 'link') {
    if (!value.length) throw new Error('link needs a label and a url: link GitHub github.com/me');
    const label = value[0];
    const url = value.slice(1).join(' ');
    if (!url) throw new Error('link needs a url: link GitHub github.com/me');
    (entry.links = entry.links || []).push({ label: label, url: url });
    return 'link added: ' + label;
  }

  if (field === 'grade' || field === 'scale') {
    // `grade` is the user-facing word for the grade object's *value*.
    // Writing entry.grade.grade used to produce {"grade": "8.7"} instead of
    // {"value": "8.7", "scale": "10"}.
    entry.grade = entry.grade || { value: '', scale: '' };
    const key = field === 'grade' ? 'value' : 'scale';
    entry.grade[key] = value.join(' ');
    return field + ' set';
  }

  const target = APPENDERS[field];
  if (target) {
    const list = (entry[target] = entry[target] || []);
    const text = value.join(' ');
    // Match the shape already in the array; fall back to what the model wants.
    const wantsObject = APPENDER_KIND[field] === 'bullet'
      || (list.length && list[0] && typeof list[0] === 'object');
    if (wantsObject) {
      // raw_facts is the user's own words; text is the same until the AI
      // polishes it in a later stage. Nothing is invented.
      list.push({ id: 'b' + Math.random().toString(36).slice(2, 10),
                  raw_facts: text, text: text, metrics: [], tags: [], tools: [] });
    } else {
      list.push(text);
    }
    return field + ' added (' + list.length + ' total)';
  }

  entry[field] = value.join(' ');
  return field + ' set';
}

function finishDraft() {
  const draft = state.draft;
  if (!draft) { dim('no draft open'); return; }
  const { section, entry, listMode } = draft;

  if (section === 'contact') {
    for (const required of ['name', 'email', 'phone']) {
      if (!entry[required]) {
        errorOut('contact needs at least name, email and phone — missing: ' + required);
        dim('keep going, then run `done` again');
        return;
      }
    }
  }
  if (listMode && section === 'experience' && entry.type &&
      !EXperience_TYPES.includes(entry.type)) {
    errorOut('type must be one of: ' + EXperience_TYPES.join(', '));
    return;
  }
  if (!listMode && section === 'summary' && !entry.text) {
    errorOut('summary is empty — add `text …` first');
    return;
  }
  if (listMode && !Object.keys(entry).length) {
    errorOut('draft is empty — nothing to save');
    return;
  }

  snapshotForUndo();
  if (listMode) {
    const arr = (state.profile[section] = state.profile[section] || []);
    arr.push(entry);
    ok('added to ' + section + ' (' + arr.length + ' entries)');
  } else {
    state.profile[section] = entry;
    ok(section + ' updated');
  }
  state.draft = null;
  scheduleSave();
  refreshNavbar();
}

function cancelDraft() {
  if (!state.draft) { dim('no draft open'); return; }
  dim('draft discarded');
  state.draft = null;
}

// ---------------------------------------------------------------- helpers for edit/rm/mv

// "2" is entry 2; "2.3" is the 3rd bullet of entry 2. Dot notation is the only
// way to address a single bullet, which is what you need to fix a typo without
// deleting the whole entry.
function parseRef(token) {
  const m = /^(\d+)(?:\.(\d+))?$/.exec(String(token || '').trim());
  if (!m) return null;
  return { index: Number(m[1]), bullet: m[2] ? Number(m[2]) : null };
}

function requireSection() {
  if (state.section) return state.section;
  errorOut('cd into a section first — e.g. cd experience');
  dim('or `home` to see them all');
  return null;
}

function resolveIndex(token) {
  const section = requireSection() || '';
  const arr = entriesFor(section);
  const ref = parseRef(token);
  if (!ref || ref.index < 1 || ref.index > arr.length) {
    errorOut('no entry ' + (token || '') + ' (this section has ' + arr.length + ')');
    return -1;
  }
  if (ref.bullet !== null) {
    const bullets = arr[ref.index - 1].bullets || [];
    if (ref.bullet < 1 || ref.bullet > bullets.length) {
      errorOut('entry ' + ref.index + ' has ' + bullets.length
        + ' bullet' + (bullets.length === 1 ? '' : 's') + ', not ' + ref.bullet);
      return -1;
    }
  }
  return ref.index - 1;
}

// ---------------------------------------------------------------- commands

const COMMANDS = {

  // The "desktop". Going home shows every section with its purpose and the one
  // command that starts writing it, so nobody lands in a directory with no idea
  // what to do next.
  home(args) {
    state.section = null;
    refreshNavbar();
    out('home  —  your resume, as a set of sections', 'hint');
    outLines('', 'out');
    table(
      sectionsOf(state.profile).map((s) => ({
        section: s,
        entries: visibleCount(s),
        status: hasContent(s) ? 'filled' : 'empty',
      })),
      ['section', 'entries', 'status'],
    );
    outLines('', 'out');

    const missing = sectionsOf(state.profile).filter((s) => !hasContent(s));
    if (missing.length) {
      out('nothing started yet in ' + missing.length + ' section' + (missing.length > 1 ? 's' : '') + '.', 'dim');
      const first = missing[0];
      out('start here: ' + SECTION_INFO[first].do, 'hint');
      dim('  ' + SECTION_INFO[first].what);
      outLines(['', '  `help` lists every command   `hint` suggests a next step', ''], 'dim');
    } else {
      ok('every section has something in it.');
      out('see it rendered: `preview`    download it: `export pdf`', 'hint');
    }
  },

  setup(args) {
    const section = args[0] ? args[0].replace(/^\//, '') : null;
    if (!section) {
      out('setup walks you through one section at a time, asking for each field.', 'hint');
      const order = ['contact', 'summary', 'experience', 'projects', 'skills',
                     'education', 'certifications', 'achievements'];
      for (const s of order) {
        if (SECTIONS[s]) out('  setup ' + s.padEnd(16) + SECTION_INFO[s].what, 'dim');
      }
      dim('  `setup contact` to start');
      return;
    }
    if (!SECTIONS[section]) {
      errorOut('no such section: ' + section);
      const guess = didYouMean(section, Object.keys(SECTIONS));
      if (guess) out('did you mean `setup ' + guess + '`?', 'hint');
      return;
    }
    COMMANDS.cd([section]);
    COMMANDS.draft([section]);
    out('  add fields one per line, then `done`. `cancel` throws it away.', 'hint');
    out('  e.g. ' + SECTIONS[section].fields.slice(0, 3).join(' / ') + ' ...', 'dim');
  },

  help(args) {
    const topic = args[0];
    if (topic) {
      const raw = topic.replace(/^\//, '').toLowerCase();
      // Resolve aliases so `help note` and `help dir` work, not just `help notes`.
      const key = HELP_TOPICS[raw] ? raw : (ALIAS_TARGET[raw] || raw);
      const detail = HELP_TOPICS[key];
      if (!detail) {
        const guess = didYouMean(raw, Object.keys(HELP_TOPICS));
        errorOut('no help topic: ' + topic);
        if (guess) out('did you mean `help ' + guess + '`?', 'hint');
        return;
      }
      if (key !== raw) dim('(`' + raw + '` is short for `' + key + '`)');
      outLines(detail, 'out');
      return;
    }
    outLines(HELP_TEXT, 'out');
  },

  hint() {
    if (state.draft) {
      out('you are drafting ' + state.draft.section + '.', 'hint');
      out('  fields: ' + SECTIONS[state.draft.section].fields.join(', '), 'hint');
      out('  `done` saves it, `cancel` throws it away', 'hint');
      return;
    }
    if (!state.profile) { out('loading…', 'hint'); return; }
    const missing = [];
    if (!entriesFor('contact').length) missing.push('cd contact');
    if (!String((state.profile.summary || {}).text || '').trim()) missing.push('draft summary');
    const exp = entriesFor('experience');
    const noBullets = exp.filter((e) => !(e.bullets || []).length).length;
    if (noBullets) missing.push(noBullets + ' experience entr' + (noBullets > 1 ? 'ies have' : 'y has') + ' no bullets');
    if (!entriesFor('skills').length) missing.push('draft skills');
    if (missing.length) {
      out('next up:', 'hint');
      missing.forEach((m) => out('  ' + m, 'hint'));
    } else {
      out('profile looks complete. try `preview` to see it, then `export pdf`.', 'hint');
    }
  },

  ls(args) {
    const section = args[0] ? args[0].replace(/^\//, '') : state.section;
    if (!section) { COMMANDS.home([]); return; }
    if (!SECTIONS[section]) {
      errorOut('no such section: ' + section);
      const guess = didYouMean(section, Object.keys(SECTIONS));
      if (guess) out('did you mean `ls ' + guess + '`?', 'hint');
      dim('`home` lists them all');
      return;
    }
    const arr = entriesFor(section);
    if (!arr.length) {
      dim(section + ' is empty');
      if (SECTION_INFO[section]) {
        out('  next: ' + SECTION_INFO[section].do, 'hint');
        out('  ' + SECTION_INFO[section].then, 'dim');
      }
      return;
    }
    arr.forEach((entry, i) => {
      out((i + 1) + '. ' + describeEntry(section, entry).join('  —  '), 'out');
    });
    dim('  edit 1 <field> <value>   ·   mv 1 down   ·   rm 1');
  },

  cd(args) {
    const target = (args[0] || '~').replace(/^\//, '');
    if (target === '~' || target === '') { COMMANDS.home([]); return; }
    if (!SECTIONS[target]) {
      errorOut('no such section: ' + target);
      const guess = didYouMean(target, Object.keys(SECTIONS));
      if (guess) out('did you mean `cd ' + guess + '`?', 'hint');
      dim('`home` lists them all, with what to type in each');
      return;
    }
    state.section = target;
    ok('~/' + target);
    guide(target);
    refreshNavbar();
  },

  pwd() { dim('~/' + (state.section || '')); },

  cat(args) {
    const section = args[0] ? args[0].replace(/^\//, '') : state.section;
    if (!section) {
      errorOut('which section? cat <section>');
      out('e.g. `cat experience` — see `home` for the list.', 'hint');
      return;
    }
    if (!SECTIONS[section]) {
      errorOut('no such section: ' + section);
      const guess = didYouMean(section, Object.keys(SECTIONS));
      if (guess) out('did you mean `cat ' + guess + '`?', 'hint');
      return;
    }
    const arr = entriesFor(section);
    out(section + '  —  ' + (SECTION_INFO[section] ? SECTION_INFO[section].what : ''), 'hint');
    outLines('', 'out');
    if (!arr.length) {
      dim('nothing here yet.');
      if (SECTION_INFO[section]) {
        out('  next: ' + SECTION_INFO[section].do, 'hint');
        out('  ' + SECTION_INFO[section].then, 'dim');
      }
      return;
    }
    arr.forEach((entry, i) => {
      const [head, sub] = describeEntry(section, entry);
      out((i + 1) + '. ' + head + (sub ? '  —  ' + sub : ''));
      (entry.bullets || []).forEach((b) => out('     - ' + bulletText(b)));
      (entry.coursework || []).forEach((c) => out('     course: ' + c));
      (entry.tech || []).forEach((t) => out('     tech: ' + t));
    });
    outLines('', 'out');
    dim(arr.length + ' entr' + (arr.length > 1 ? 'ies' : 'y')
      + '  ·  edit: `edit 1 <field> <value>`  ·  move: `mv 1 down`  ·  delete: `rm 1`');
  },

  profile() {
    const p = state.profile;
    if (!p) return;
    const c = p.contact || {};
    out(c.name || '(no name)', 'out');
    dim([c.email, c.phone, c.city, c.country].filter(Boolean).join(' | '));
    const rows = SECTION_ORDER.map((s) => ({ section: s, entries: entriesFor(s).length }));
    out('', 'out');
    table(rows, ['section', 'entries']);
    const bullets = countBullets();
    out('', 'out');
    dim(bullets + ' bullets across ' + rows.filter((r) => r.entries).length + ' sections');
  },

  grep(args) {
    const needle = args.join(' ').toLowerCase();
    if (!needle) { errorOut('grep what? e.g. grep redis'); return; }
    let hits = 0;
    const walk = (value, trail) => {
      if (typeof value === 'string') {
        if (value.toLowerCase().includes(needle)) { out(trail + ': ' + value, 'out'); hits++; }
      } else if (Array.isArray(value)) {
        value.forEach((v, i) => walk(v, trail + '[' + (i + 1) + ']'));
      } else if (value && typeof value === 'object') {
        for (const k of Object.keys(value)) walk(value[k], trail ? trail + '.' + k : k);
      }
    };
    walk(state.profile, '');
    if (!hits) dim('no matches for "' + needle + '"');
    else out(hits + ' match' + (hits > 1 ? 'es' : ''), 'dim');
  },

  theme(args) {
    const want = args[0];
    if (!want) { out('themes: ' + THEMES.join(', '), 'out'); dim('theme <name>'); return; }
    if (!THEMES.includes(want)) {
      errorOut('no such theme: ' + want);
      const guess = didYouMean(want, THEMES);
      if (guess) out('did you mean `' + guess + '`?', 'hint');
      return;
    }
    document.documentElement.setAttribute('data-theme', want);
    store.set('rb.theme', want);
    ok('theme: ' + want);
  },

  clear() { el.scrollback.textContent = ''; },

  draft(args) {
    if (!args[0]) {
      if (state.draft) out('drafting ' + state.draft.section, 'hint');
      else { errorOut('draft what? e.g. draft experience'); dim('sections: ' + Object.keys(SECTIONS).join(', ')); }
      return;
    }
    startDraft(args[0].replace(/^\//, ''));
  },

  add(args) {
    if (!state.draft) { errorOut('no draft open — run `draft <section>` first'); return; }
    const field = (args[0] || '').toLowerCase();
    const valid = SECTIONS[state.draft.section].fields;
    if (!field) { errorOut('which field? one of: ' + valid.join(', ')); return; }
    if (!valid.includes(field)) {
      errorOut('unknown field "' + field + '" for ' + state.draft.section);
      out('valid: ' + valid.join(', '), 'dim');
      const guess = didYouMean(field, valid);
      if (guess) out('did you mean `' + guess + '`?', 'hint');
      return;
    }
    if (!args.slice(1).length && !APPENDERS[field] && field !== 'link' && field !== 'grade' && field !== 'scale') {
      errorOut(field + ' needs a value, e.g. ' + field + ' some value');
      return;
    }
    try {
      dim(applyField(state.draft.section, field, args.slice(1)));
    } catch (err) { errorOut(err.message); }
  },

  done() { finishDraft(); },
  cancel() { cancelDraft(); },
  exit() { if (state.draft) cancelDraft(); else COMMANDS.cd([]); },

  rm(args) {
    const section = requireSection();
    if (!section) return;
    if (!isList(section)) { errorOut(section + ' holds a single value — use `edit` instead'); return; }
    const ref = parseRef(args[0]);
    const idx = resolveIndex(args[0]);
    if (idx < 0) return;
    const arr = state.profile[section];

    if (ref && ref.bullet !== null) {
      snapshotForUndo();
      const entry = arr[idx];
      const [gone] = entry.bullets.splice(ref.bullet - 1, 1);
      ok('removed bullet: ' + bulletText(gone));
      scheduleSave();
      return;
    }

    snapshotForUndo();
    const [removed] = arr.splice(idx, 1);
    ok('removed ' + (removed.role || removed.name || removed.org || 'entry ' + (idx + 1)));
    scheduleSave();
    refreshNavbar();
  },

  mv(args) {
    const section = requireSection();
    if (!section) return;
    if (!isList(section)) { errorOut(section + ' holds a single value'); return; }
    const idx = resolveIndex(args[0]);
    if (idx < 0) return;
    const arr = state.profile[section];
    const where = (args[1] || '').toLowerCase();
    let to;
    if (where === 'up') to = idx - 1;
    else if (where === 'down') to = idx + 1;
    else if (/^\d+$/.test(where)) to = Number(where) - 1;
    else { errorOut('mv <n> up | down | <position>'); return; }
    if (to < 0 || to >= arr.length) { dim('already at the ' + (to < 0 ? 'top' : 'bottom')); return; }
    snapshotForUndo();
    const [moved] = arr.splice(idx, 1);
    arr.splice(to, 0, moved);
    ok('moved to position ' + (to + 1));
    scheduleSave();
    refreshNavbar();
  },

  edit(args) {
    const section = requireSection();
    if (!section) return;
    const listMode = isList(section);

    // `edit 1.2 <text>` rewrites one bullet. Detected before field validation,
    // because here the second token is the new text, not a field name.
    const ref = parseRef(listMode ? args[0] : null);
    if (listMode && ref && ref.bullet !== null) {
      const idx = resolveIndex(args[0]);
      if (idx < 0) return;
      const entry = state.profile[section][idx];
      const text = args.slice(1).join(' ');
      if (!text) {
        errorOut('edit ' + args[0] + ' <new text>');
        dim('  e.g. edit 1.2 Cut p99 latency from 900ms to 240ms with Redis.');
        return;
      }
      snapshotForUndo();
      const b = entry.bullets[ref.bullet - 1];
      if (b && typeof b === 'object') b.text = text;
      else entry.bullets[ref.bullet - 1] = text;
      ok('bullet ' + ref.bullet + ' of entry ' + ref.index + ' rewritten');
      scheduleSave();
      return;
    }

    // Two shapes: `edit <n> <field> <value>` for a list section,
    // `edit <field> <value>` for a single-value one.
    const field = ((listMode ? args[1] : args[0]) || '').toLowerCase();
    const value = listMode ? args.slice(2) : args.slice(1);
    const valid = SECTIONS[section].fields;

    if (!field) {
      errorOut(listMode
        ? 'edit <n> <field> <value>  ·  or edit <n>.<m> <text> for one bullet'
        : 'edit <field> <value> — fields: ' + valid.join(', '));
      dim('  `help edit` has examples');
      return;
    }
    if (!valid.includes(field)) {
      errorOut('unknown field "' + field + '" for ' + section);
      out('valid: ' + valid.join(', '), 'dim');
      const guess = didYouMean(field, valid);
      if (guess) out('did you mean `' + guess + '`?', 'hint');
      return;
    }

    if (listMode) {
      const idx = resolveIndex(args[0]);
      if (idx < 0) return;
      snapshotForUndo();
      const scratch = { section: section, entry: state.profile[section][idx], listMode: true };
      state.draft = scratch;
      try { dim(applyField(section, field, value)); } catch (err) { errorOut(err.message); }
      state.draft = null;
    } else {
      snapshotForUndo();
      // Mutate in place, then write the same object back. Reading state.draft
      // after clearing it used to discard the edit entirely.
      const scratch = { section: section, entry: state.profile[section] || {}, listMode: false };
      state.draft = scratch;
      try { dim(applyField(section, field, value)); } catch (err) { errorOut(err.message); }
      state.draft = null;
      state.profile[section] = scratch.entry;
    }
    scheduleSave();
  },

  save() { pushSave('manual'); },

  // A scratchpad for half-remembered facts. Deliberately NOT part of the
  // profile: these are the raw thoughts that Stage 4's AI will later turn into
  // bullets, so they must not pollute the resume itself.
  notes(args) {
    const all = store.get('rb.notes', []);
    const verb = (args[0] || '').toLowerCase();

    if (!args.length) {
      if (!all.length) {
        dim('no notes yet.');
        outLines(['', '  jot down anything you remember, with numbers:', ''], 'dim');
        out('  note cut p99 latency from 900ms to 240ms with redis', 'hint');
        out('  note led a team of 5 engineers on the billing service', 'hint');
        return;
      }
      out('notes  (' + all.length + ')', 'hint');
      all.forEach((n, i) => out((i + 1) + '. ' + n, 'out'));
      outLines(['', '  `note <text>` add    `note rm <n>` delete    `note clear` wipe', ''], 'dim');
      return;
    }

    if (verb === 'clear') {
      if (!all.length) { dim('no notes to clear'); return; }
      store.set('rb.notes', []);
      ok('notes cleared (' + all.length + ' removed, undo cannot bring these back)');
      return;
    }
    if (verb === 'rm' || verb === 'del') {
      const n = Number(args[1]);
      if (!Number.isInteger(n) || n < 1 || n > all.length) {
        errorOut('no note ' + (args[1] || '') + ' (you have ' + all.length + ')');
        return;
      }
      const [gone] = all.splice(n - 1, 1);
      store.set('rb.notes', all);
      ok('deleted: ' + gone);
      return;
    }
    const text = args.join(' ').trim();
    if (!text) { errorOut('note what? e.g. note cut latency by 40%'); return; }
    if (text.length > 500) { errorOut('keep notes under 500 characters'); return; }
    all.push(text);
    store.set('rb.notes', all);
    ok('noted (' + all.length + ' total)');
  },

  // A finished resume to look at. Refuses to overwrite real data unless forced,
  // because this is the command a nervous newcomer is most likely to run twice.
  demo(args) {
    const forced = args.includes('--force') || args.includes('-f');
    const empty = profileIsEmpty();

    if (!empty && !forced) {
      errorOut('this would replace the profile you have already written.');
      out('look at it first with `preview`, or run `demo --force` to replace it.', 'hint');
      dim('`undo` also restores it if you go ahead by accident');
      return;
    }

    snapshotForUndo();
    state.profile = clone(SAMPLE_PROFILE);
    state.section = null;
    state.draft = null;
    ok('loaded a sample resume so you can see what a finished one looks like');
    dim('every word is made up — replace it with your own');
    // Saved immediately, not on the autosave debounce: replacing the whole
    // profile should never be lost to a closed tab.
    const saving = pushSave('demo');
    refreshNavbar();
    outLines(['', '  `cat experience`    read a section', '  `preview`          see it rendered', ''], 'hint');
    return saving;
  },

  reset(args) {
    const empty = profileIsEmpty();
    if (empty) { dim('already empty'); return; }
    if (!args.includes('--force') && !args.includes('-f')) {
      errorOut('this empties your profile.');
      out('run `reset --force` if you are sure. `undo` also restores it.', 'hint');
      return;
    }
    snapshotForUndo();
    state.profile = clone(EMPTY_PROFILE());
    state.section = null;
    state.draft = null;
    ok('profile cleared — `undo` brings it back');
    const saving = pushSave('reset');   // immediate, not debounced
    refreshNavbar();
    return saving;
  },


  undo() { undo(); },

  preview(args) {
    if (args[0] === 'off') return togglePreview(false);
    if (args[0] === 'on') return togglePreview(true);
    togglePreview();
  },

  snapshot(args) {
    const name = args.join(' ') || 'snapshot';
    return withBusy('saving snapshot…', async () => {
      const resp = await api('/versions/from-profile?name=' + encodeURIComponent(name), { method: 'POST' });
      const body = await resp.json();
      state.lastSnapshot = body;
      ok('snapshot "' + body.name + '" saved as ' + body.id.slice(0, 8));
    });
  },

  export(args) {
    const fmt = (args[0] || 'pdf').toLowerCase();
    if (!FORMATS.includes(fmt)) {
      errorOut('format must be one of: ' + FORMATS.join(', '));
      return;
    }
    return withBusy('rendering ' + fmt + '…', async () => {
      const name = args.slice(1).join(' ') || 'resume';
      const snap = await api('/versions/from-profile?name=' + encodeURIComponent(name), { method: 'POST' });
      const version = await snap.json();
      const resp = await api('/export/' + version.id + '?format=' + fmt, { method: 'POST' });
      const pages = resp.headers.get('X-Pages');
      const limit = resp.headers.get('X-Page-Limit');
      const budget = resp.headers.get('X-Page-Budget');
      if (pages) {
        if (budget === 'over') errorOut(pages + '/' + limit + ' pages — OVER BUDGET');
        else ok(pages + '/' + limit + ' pages');
      }
      const blob = await resp.blob();
      downloadBlob(blob, name + '.' + fmt);
      ok('downloaded ' + name + '.' + fmt);
    });
  },
};

const countBullets = () =>
  ['experience', 'projects'].reduce((n, s) => {
    return n + entriesFor(s).reduce((m, e) => m + ((e.bullets || []).length), 0);
  }, 0);

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();          // programmatic download, not a mouse-driven control
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

async function withBusy(message, fn) {
  out(message, 'dim');
  try {
    await fn();
  } catch (err) {
    errorOut(err.message);
  }
}

// Aliases: short forms and friendly synonyms people will actually try.
COMMANDS.u = COMMANDS.undo;
COMMANDS.q = COMMANDS.exit;
COMMANDS.w = COMMANDS.save;
COMMANDS['?'] = COMMANDS.help;
COMMANDS.dir = COMMANDS.ls;
COMMANDS.ll = COMMANDS.ls;
COMMANDS.note = COMMANDS.notes;
COMMANDS['clear-screen'] = COMMANDS.clear;

const COMMAND_NAMES = Object.keys(COMMANDS).sort();

// Alias -> the command it points at, so `help note` finds `help notes`.
const ALIAS_TARGET = {
  note: 'notes', dir: 'ls', ll: 'ls', '?': 'help', 'clear-screen': 'clear',
};

const HELP_TEXT = [
  'resume-builder — a resume, written as a set of files.',
  '',
  '  START HERE',
  '    home               your resume as folders — start with the ones marked empty',
  '    cd <section>       go to a section; it tells you what to type next',
  '    setup [section]    walk yourself through writing one',
  '    demo               load a finished sample resume to look at',
  '    hint               what to do next, based on where you are',
  '    help [topic]       this list, or `help cat` for one command',
  '',
  '  WRITING',
  '    draft <section>     open a draft      add <field> <value>   add one line',
  '    done                save the draft    cancel      throw it away',
  '    cat <section>       read a section back in full',
  '    edit <n> <field> <value>   change one field',
  '    rm <n>              delete entry n    mv <n> up|down   reorder',
  '    undo / u            step back (Ctrl+Z)',
  '    save / w            save now (it autosaves anyway)',
  '',
  '  FINDING THINGS',
  '    ls                  every section and how full it is',
  '    ls <section>        the entries in one section',
  '    grep <text>         search every field for a word',
  '    profile             summary of the whole resume',
  '    notes               your scratchpad — raw facts not yet on the resume',
  '',
  '  OUTPUT',
  '    preview [on|off]    live rendered PDF (Ctrl+P)',
  '    export <fmt> [name] download pdf, docx or txt',
  '    snapshot [name]     store a version you can return to',
  '    reset --force       empty the profile',
  '',
  '  LOOK',
  '    theme [name]        amber, green, matrix, paper',
  '    clear               clear the screen',
  '',
  'Not sure what something means? `help <command>`, e.g. `help cat`.',
  'Tab completes anything. Up/Down is history. Both `help` and `/help` work.',
];

const HELP_TOPICS = {
  home: [
    'home',
    '',
    '  Your resume as a set of folders, each with how many entries it holds.',
    '  This is the "desktop". The ones marked empty are where the work is left.',
    '  If you have not started, home tells you what to type first.',
  ],
  setup: [
    'setup [section]',
    '',
    '  Opens the section and starts a draft in one go, then lists its fields.',
    '',
    '    setup              every section, with what belongs in each',
    '    setup experience   jump straight into writing an experience entry',
  ],
  cd: [
    'cd <section>          go to a section',
    'cd ~                  back to home',
    '',
    '  Arriving somewhere always explains what it is for and what to type next,',
    '  so you never land in a directory with nothing to do. `cd` on its own is',
    '  the same as `home`.',
  ],
  ls: [
    'ls                    every section, with entry counts and filled/empty',
    'ls <section>          the entries in one section',
    '',
    '  Like listing files in a folder.',
  ],
  cat: [
    'cat <section>         read a section back in full',
    '',
    '  Prints the section heading, a one-line explanation of what belongs',
    '  there, then each entry numbered with its bullets, courses and tech.',
    '  If the section is empty it tells you the command that starts one.',
    '',
    '    cat experience',
    '    cat contact',
  ],
  pwd: ['pwd   which section you are currently in'],
  notes: [
    'notes                show your scratchpad',
    'note <text>          remember something (kept out of the resume)',
    'note rm <n>          delete note n',
    'note clear           delete them all',
    '',
    '  A place to jot down half-remembered facts — "cut latency 900 to 240ms",',
    '  "led a team of 5". These are deliberately NOT part of your resume; they',
    '  are the raw material the AI will later turn into bullets.',
  ],
  demo: [
    'demo                 load a finished sample resume',
    'demo --force         replace a profile you have already written',
    '',
    '  Every word in the sample is made up. It refuses to overwrite a profile',
    '  you have already filled in unless you pass --force, and `undo` restores',
    '  it either way.',
  ],
  reset: [
    'reset --force        empty the whole profile',
    '',
    '  Without --force it just explains. `undo` brings everything back.',
  ],
  draft: [
    'draft <section> — open a writing session for that section.',
    '',
    'Then type one field per line, for example:',
    '    draft experience',
    '    org PayFlow',
    '    role Backend Engineer',
    '    start 2022-07',
    '    end Present',
    '    bullet Cut p99 latency from 900ms to 240ms with Redis caching.',
    '    done',
    '',
    'Fields differ per section. Run `draft <section>` to see them, or:',
    '    contact          name email phone city country link',
    '    summary          text',
    '    education        institution degree field start end grade scale course',
    '    experience       org role type location start end bullet',
    '    projects         name role start end tech bullet link',
    '    skills           group item',
    '    certifications   name issuer date',
    '    achievements     name date',
  ],
  edit: [
    'edit <n> <field> <value>    change one field of entry n in a list section',
    'edit <field> <value>        change a field of a single-value section',
    'edit <n>.<m> <value>        rewrite bullet m of entry n',
    '',
    '    cd experience',
    '    edit 1 org Renamed',
    '    edit 1.2 Cut p99 latency from 900ms to 240ms with Redis.',
    '',
    '    cd contact',
    '    edit city Pune',
    '',
    '  Note: `bullet`, `course`, `tech` and `item` ADD a new line when you draft.',
    '  To change one that already exists, use the dotted form: `edit 1.2 <value>`.',
  ],
  rm: ['rm <n>        delete entry n from the current section',
       'rm <n>.<m>     delete just bullet m of entry n',
       '',
       '  `cd` into the section first. `undo` puts it back.',
       '  Use a dot to target one bullet, e.g. `rm 1.2` removes the second bullet',
       '  of the first entry — handy for fixing one line without losing the rest.'],
  mv: ['mv <n> up | down | <position>   move entry n.', '',
       '    mv 2 up        move the 2nd entry up one place',
       '    mv 1 down      move the 1st entry down one place',
       '    mv 4 2         move entry 4 into position 2'],
  export: [
    'export <pdf|docx|txt> [name]',
    '',
    '  Saves a snapshot of your current profile, renders it, and downloads it.',
    '  PDF reports its page count; if it is over the rules.json budget you get',
    '  a warning because the layout has squeezed as far as it is allowed to.',
    '',
    '    export pdf',
    '    export pdf my-cv-v2',
  ],
  theme: ['theme [amber|green|matrix|paper]', '',
          '  No argument lists them. Your choice is remembered.'],
  undo: ['undo   (or `u`, or Ctrl+Z)', '',
         '  Steps back through edits made in this browser tab.'],
  preview: ['preview [on|off]   (or Ctrl+P)', '',
            '  Renders the real exported PDF — the same renderer the exporter',
            '  uses, not an approximation. Refreshes shortly after each change.'],
  grep: ['grep <text>   search every field in your profile', '',
         '    grep redis'],
  hint: ['hint   what to do next, based on what you have and where you are', ''],
  profile: ['profile   a summary of the whole resume, with entry counts', ''],
  clear: ['clear   wipe the screen', ''],
};

// Assigned after the literal: referencing HELP_TOPICS inside its own
// initialiser is a temporal dead zone ReferenceError, which killed the whole
// script at load time.
HELP_TOPICS.help = ['help [topic]', '',
                    '  Topics: ' + Object.keys(HELP_TOPICS).join(', ')];

// ---------------------------------------------------------------- dispatch

function runLine(raw) {
  const line = raw.trim();
  out('$ ' + raw, 'cmd');

  if (!line) return;
  state.history.push(line);
  state.histIndex = state.history.length;
  state.history = state.history.slice(-200);

  // Inside a draft, a bare `field value` line is the natural thing to type.
  // Anything that is a real command still dispatches; anything else is treated
  // as an attempted field, so a typo gets "unknown field" with the valid list
  // rather than a baffling "command not found".
  if (state.draft && !line.startsWith('/')) {
    const parts = tokenize(line);
    const head = (parts[0] || '').toLowerCase();
    if (!COMMAND_NAMES.includes(head)) {
      COMMANDS.add(parts);
      return;
    }
  }

  const parts = tokenize(line);
  let name = (parts[0] || '').replace(/^\//, '').toLowerCase();
  const args = parts.slice(1);

  if (name === 'sudo') { errorOut('no.'); return; }

  const fn = COMMANDS[name];
  if (!fn) {
    errorOut(name + ': command not found');
    const guess = didYouMean(name, COMMAND_NAMES);
    if (guess) out('did you mean `' + guess + '`?', 'hint');
    outLines(['', '  `help` lists every command', '  Tab completes what you start typing'], 'dim');
    return;
  }
  try {
    const result = fn(args);
    if (result && typeof result.catch === 'function') result.catch((e) => errorOut(e.message));
  } catch (err) {
    errorOut((err && err.message) || String(err));
  }
}

function runLineSafely(raw) {
  try {
    runLine(raw);
  } catch (err) {
    // The boundary the whole UI depends on: a bad command must never kill it.
    errorOut('internal error: ' + ((err && err.message) || String(err)));
    dim('the app is still running — try `hint`');
  }
}

// ---------------------------------------------------------------- completion

function candidatesFor(text) {
  const trailingSpace = /\s$/.test(text);
  const parts = text.trim().split(/\s+/);

  if (state.draft && parts.length === 1 && !trailingSpace) {
    return SECTIONS[state.draft.section].fields.slice();
  }

  if (parts.length === 1) {
    return trailingSpace ? [] : COMMAND_NAMES.slice();
  }

  const head = parts[0].replace(/^\//, '').toLowerCase();
  const prefix = trailingSpace ? '' : parts[parts.length - 1];

  if (['cd', 'ls', 'cat', 'draft'].includes(head)) {
    return Object.keys(SECTIONS).filter((s) => s.startsWith(prefix));
  }
  if (head === 'setup') {
    return Object.keys(SECTIONS).filter((s) => s.startsWith(prefix));
  }
  if (head === 'export') return FORMATS.filter((f) => f.startsWith(prefix));
  if (head === 'theme') return THEMES.filter((t) => t.startsWith(prefix));
  if (head === 'preview') return ['on', 'off'].filter((t) => t.startsWith(prefix));
  if (head === 'mv') return ['up', 'down'].filter((t) => t.startsWith(prefix));
  if (head === 'reset' || head === 'demo') return ['--force'].filter((t) => t.startsWith(prefix));
  if (['rm', 'edit', 'mv'].includes(head)) {
    const n = Number(parts[1]);
    if (Number.isInteger(n) && state.section && isList(state.section)) {
      return SECTIONS[state.section].fields.filter((f) => f.startsWith(prefix));
    }
    const max = state.section ? entriesFor(state.section).length : 0;
    return Array.from({ length: max }, (_, i) => String(i + 1)).filter((s) => s.startsWith(prefix));
  }
  if (head === 'help') return Object.keys(HELP_TOPICS).filter((t) => t.startsWith(prefix));
  return [];
}

function applyCompletion() {
  const text = el.input.value;
  const cands = candidatesFor(text);
  if (!cands.length) return;

  if (cands.length === 1) {
    const trailing = /\s$/.test(text);
    const parts = text.trim().split(/\s+/);
    parts[parts.length - 1] = cands[0];
    el.input.value = parts.join(' ') + (trailing ? ' ' : ' ');
    return;
  }

  const prefix = text.trim().split(/\s+/).pop();
  let shared = cands[0];
  for (const c of cands) {
    let i = 0;
    while (i < shared.length && i < c.length && shared[i] === c[i]) i++;
    shared = shared.slice(0, i);
  }
  if (shared.length > prefix.length) {
    const trailing = /\s$/.test(text);
    const parts = text.trim().split(/\s+/);
    parts[parts.length - 1] = shared;
    el.input.value = parts.join(' ') + ' ';
    return;
  }
  out(cands.join('  '), 'dim');
}

// ---------------------------------------------------------------- wiring

el.form.addEventListener('submit', (ev) => {
  ev.preventDefault();
  const value = el.input.value;
  el.input.value = '';
  runLineSafely(value);
  el.input.focus();
});

el.input.addEventListener('keydown', (ev) => {
  if (ev.key === 'Tab') { ev.preventDefault(); applyCompletion(); return; }
  if (ev.key === 'ArrowUp') {
    ev.preventDefault();
    if (state.histIndex > 0) { state.histIndex--; el.input.value = state.history[state.histIndex]; }
    return;
  }
  if (ev.key === 'ArrowDown') {
    ev.preventDefault();
    if (state.histIndex < state.history.length - 1) {
      state.histIndex++;
      el.input.value = state.history[state.histIndex];
    } else {
      state.histIndex = state.history.length;
      el.input.value = '';
    }
    return;
  }
  if (ev.key === 'l' && ev.ctrlKey) { ev.preventDefault(); COMMANDS.clear(); return; }
  if (ev.key === 'p' && ev.ctrlKey) { ev.preventDefault(); togglePreview(); return; }
  if (ev.key === 'z' && ev.ctrlKey) { ev.preventDefault(); undo(); return; }
  if (ev.key === 'c' && ev.ctrlKey) {
    ev.preventDefault();
    out('^C', 'cmd');
    state.draft = null;
    return;
  }
});

document.getElementById('previewClose').addEventListener('click', () => {
  togglePreview(false);
  el.input.focus();
});
document.getElementById('previewRefresh').addEventListener('click', () => {
  doPreview();
  el.input.focus();
});

// Nothing on the page uses the mouse, but if a stray click ever lands, put
// focus back so the keyboard never appears dead.
document.addEventListener('mouseup', () => el.input.focus());

window.addEventListener('error', (ev) => {
  errorOut('unexpected error: ' + (ev.message || 'unknown'));
});
window.addEventListener('unhandledrejection', (ev) => {
  const r = ev.reason;
  errorOut('unexpected failure: ' + ((r && r.message) || r));
});

// ---------------------------------------------------------------- boot

async function boot() {
  const saved = store.get('rb.theme', null);
  if (THEMES.includes(saved)) document.documentElement.setAttribute('data-theme', saved);
  state.history = store.get('rb.history', []);

  const ascii = document.createElement('div');
  ascii.className = 'ascii';
  ascii.textContent = BANNER;
  el.scrollback.appendChild(ascii);

  try {
    const resp = await api('/profile');
    state.profile = await resp.json();
    setStatus('ready', '');
    refreshNavbar();
    ok('loaded your profile — ' + (state.profile.contact && state.profile.contact.name || '(no name yet)'));
    const empty = profileIsEmpty();
    if (empty) welcome();
  } catch (err) {
    if (err.status === 404) {
      state.profile = EMPTY_PROFILE();
      setStatus('new profile', '');
      ok('no profile saved yet — let us build one');
      welcome();
    } else {
      setStatus('offline', 'error');
      errorOut(err.message);
      outLines(['', 'The terminal still works; only save/export need the server.', ''], 'dim');
    }
    refreshNavbar();
  }

  el.input.focus();
}

// The first thing a new user sees. Answers "what is this and what do I type"
// without requiring them to know anything about terminals.
function welcome() {
  outLines([
    '',
    '  Welcome. Your resume is a set of folders — contact, summary, experience,',
    '  skills and so on. Three ways to start, pick whichever suits you:',
    '',
    '    home              see every folder and what is still empty',
    '    setup contact     be walked through writing your contact details',
    '    demo              load a finished sample resume to look at',
    '',
    '  Stuck anywhere? `hint` always tells you the next useful thing.',
    '  Unsure what a command means? `help cat`, for example.',
    '',
  ], 'hint');
}

boot();

})();
