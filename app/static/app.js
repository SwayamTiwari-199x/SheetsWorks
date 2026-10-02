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

// Fields that append to an array instead of replacing a scalar.
const APPENDERS = { bullet: 'bullets', course: 'coursework', tech: 'tech', item: 'items' };

const EXperience_TYPES = ['job', 'internship', 'freelance'];

const BANNER = [
  '  ___  ___  _  _  ___  ___  ___  ___  ___  ___ ',
  ' |   \\|   || \\| |/ __|/ __|/ _ \\| _ \\/ __|/ _ \\',
  ' | |) | | || .  | (__| (__|   /|   / (__|   /',
  ' |___/|___||_|\\_|\\___|\\___|_|_|\\_|\\___|_|\\_\\',
].join('\n');

const MAX_UNDO = 60;
const SAVE_DEBOUNCE_MS = 800;

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
const outLines = (arr, cls) => arr.forEach((l) => out(l, cls));

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
  for (const section of sectionsOf(state.profile)) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'nb-btn';
    btn.setAttribute('data-cmd', 'cd ' + section);
    btn.setAttribute('aria-current', String(state.section === section));

    const label = document.createElement('span');
    label.textContent = section;
    const count = document.createElement('span');
    count.className = 'nb-count';
    count.textContent = String(entriesFor(section).length);
    btn.append(label, count);

    // No click listener anywhere: activating the button (mouse, Enter or Space,
    // all of which browsers synthesise) dispatches an activation event, which
    // we translate into typing the command. Same single interface.
    btn.addEventListener('click', () => runTyped('cd ' + section));
    el.nbItems.appendChild(btn);
  }
}

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
    (entry[target] = entry[target] || []).push(value.join(' '));
    return field + ' added (' + entry[target].length + ' total)';
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

function requireSection() {
  if (state.section) return state.section;
  errorOut('cd into a section first — e.g. cd experience');
  dim('or `ls` to see them all');
  return null;
}

function resolveIndex(token) {
  const arr = entriesFor(requireSection() || '');
  const n = Number(token);
  if (!Number.isInteger(n) || n < 1 || n > arr.length) {
    errorOut('no entry ' + token + ' (this section has ' + arr.length + ')');
    return -1;
  }
  return n - 1;
}

// ---------------------------------------------------------------- commands

const COMMANDS = {

  help(args) {
    const topic = args[0];
    if (topic) {
      const key = topic.replace(/^\//, '').toLowerCase();
      const detail = HELP_TOPICS[key];
      if (!detail) {
        const guess = didYouMean(key, Object.keys(HELP_TOPICS));
        errorOut('no help topic: ' + topic);
        if (guess) out('did you mean `help ' + guess + '`?', 'hint');
        return;
      }
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
    if (!section) {
      const rows = sectionsOf(state.profile).map((s) => ({
        section: s,
        entries: entriesFor(s).length,
        kind: isList(s) ? 'list' : 'single',
      }));
      table(rows, ['section', 'entries', 'kind']);
      dim('cd <section> to open one');
      return;
    }
    if (!SECTIONS[section]) {
      errorOut('no such section: ' + section);
      const guess = didYouMean(section, Object.keys(SECTIONS));
      if (guess) out('did you mean `' + guess + '`?', 'hint');
      return;
    }
    const arr = entriesFor(section);
    if (!arr.length) { dim(section + ' is empty — try `draft ' + section + '`'); return; }
    arr.forEach((entry, i) => out((i + 1) + '. ' + describeEntry(section, entry, i).join('  —  ')));
  },

  cd(args) {
    const target = (args[0] || '~').replace(/^\//, '');
    if (target === '~' || target === '') { state.section = null; dim('~'); refreshNavbar(); return; }
    if (!SECTIONS[target]) {
      errorOut('no such section: ' + target);
      const guess = didYouMean(target, Object.keys(SECTIONS));
      if (guess) out('did you mean `cd ' + guess + '`?', 'hint');
      dim('`ls` lists them all');
      return;
    }
    state.section = target;
    ok('~/' + target);
    refreshNavbar();
  },

  pwd() { dim('~/' + (state.section || '')); },

  cat(args) {
    const section = args[0] ? args[0].replace(/^\//, '') : state.section;
    if (!section) { errorOut('which section? cat <section>'); return; }
    if (!SECTIONS[section]) { errorOut('no such section: ' + section); return; }
    const arr = entriesFor(section);
    if (!arr.length) { dim(section + ' is empty'); return; }
    arr.forEach((entry, i) => {
      const [head, sub] = describeEntry(section, entry, i);
      out((i + 1) + '. ' + head + (sub ? '  —  ' + sub : ''));
      (entry.bullets || []).forEach((b) => out('     - ' + b));
      (entry.coursework || []).forEach((c) => out('     course: ' + c));
      (entry.tech || []).forEach((t) => out('     tech: ' + t));
    });
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
    const idx = resolveIndex(args[0]);
    if (idx < 0) return;
    snapshotForUndo();
    const [removed] = state.profile[section].splice(idx, 1);
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
    // Two shapes: `edit <n> <field> <value>` for a list section,
    // `edit <field> <value>` for a single-value one.
    const listMode = isList(section);
    const field = ((listMode ? args[1] : args[0]) || '').toLowerCase();
    const value = listMode ? args.slice(2) : args.slice(1);
    const valid = SECTIONS[section].fields;

    if (!field) {
      errorOut(listMode
        ? 'edit <n> <field> <value> — fields: ' + valid.join(', ')
        : 'edit <field> <value> — fields: ' + valid.join(', '));
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

// Aliases: short forms people will actually try.
COMMANDS.u = COMMANDS.undo;
COMMANDS.q = COMMANDS.exit;
COMMANDS.w = COMMANDS.save;
COMMANDS['?'] = COMMANDS.help;

const COMMAND_NAMES = Object.keys(COMMANDS).sort();

const HELP_TEXT = [
  'resume-builder — every command, grouped by what you are trying to do.',
  '',
  '  FINDING YOUR WAY',
  '    help [topic]        this list, or `help draft` for one command',
  '    hint                what to do next, based on your profile',
  '    ls [section]        list sections, or the entries in one',
  '    cd <section>        open a section        pwd    where am I',
  '    cat <section>       show one section in full',
  '    grep <text>         search everything for a word',
  '    clear               clear the screen',
  '',
  '  WRITING',
  '    draft <section>     start writing         add <field> <value>   add a line',
  '    done                save the draft        cancel     throw it away',
  '    rm <n>              delete entry n        mv <n> up|down   reorder',
  '    edit <n> <field> <value>   change one field',
  '    undo / u            step back (Ctrl+Z also works)',
  '    save / w            save immediately (it also autosaves)',
  '',
  '  OUTPUT',
  '    profile             summary of the whole resume',
  '    preview [on|off]    live rendered PDF (Ctrl+P)',
  '    export <fmt> [name] download pdf, docx or txt',
  '    snapshot [name]     store a version you can return to',
  '',
  '  LOOK',
  '    theme [name]        amber, green, matrix, paper',
  '',
  'Tips: Tab completes anything. Up/Down recalls history. Ctrl+L clears.',
  'Both `help` and `/help` work — the slash is optional.',
];

const HELP_TOPICS = {
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
  ],
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
  mv: ['mv <n> up | down | <position>   move entry n.', '',
       '    mv 2 up        move the 2nd entry up one place',
       '    mv 1 down      move the 1st entry down one place',
       '    mv 4 2         move entry 4 into position 2'],
  theme: ['theme [amber|green|matrix|paper]', '',
          '  No argument lists them. Your choice is remembered.'],
  undo: ['undo   (or `u`, or Ctrl+Z)', '',
         '  Steps back through edits made in this browser tab.'],
  preview: ['preview [on|off]   (or Ctrl+P)', '',
            '  Renders the real exported PDF — the same renderer the exporter',
            '  uses, not an approximation. Refreshes shortly after each change.'],
  grep: ['grep <text>   search every field in your profile', '',
         '    grep redis'],
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
  if (head === 'export') return FORMATS.filter((f) => f.startsWith(prefix));
  if (head === 'theme') return THEMES.filter((t) => t.startsWith(prefix));
  if (head === 'preview') return ['on', 'off'].filter((t) => t.startsWith(prefix));
  if (head === 'mv') return ['up', 'down'].filter((t) => t.startsWith(prefix));
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
  dim('resume-builder — type `help` to begin, `hint` if you want a nudge.');
  outLines(['', 'Tab completes commands, sections and fields. Up/Down is history.', ''], 'dim');

  try {
    const resp = await api('/profile');
    state.profile = await resp.json();
    setStatus('ready', '');
    refreshNavbar();
    ok('loaded your profile — ' + (state.profile.contact && state.profile.contact.name || '(no name yet)'));
  } catch (err) {
    if (err.status === 404) {
      state.profile = {
        contact: { name: '', email: '', phone: '', links: [] },
        summary: '', education: [], experience: [], projects: [], skills: [],
        certifications: [], achievements: [], extracurriculars: [], publications: [],
      };
      setStatus('new profile', '');
      ok('no profile yet — start with `draft contact`');
    } else {
      setStatus('offline', 'error');
      errorOut(err.message);
      outLines(['', 'The terminal still works; only save/export need the server.', ''], 'dim');
    }
    refreshNavbar();
  }

  el.input.focus();
}

boot();

})();
