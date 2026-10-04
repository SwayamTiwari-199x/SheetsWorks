/* ============================================================================
   editor.js -- the My Resume form.

   Builds itself from EditorModel.SECTIONS, so a field cannot exist in the form
   and be missing from the model, or the other way round. All the rules live in
   the model; this file only draws them and moves values in and out.

   Shape: a section list on the left, the selected section's fields on the
   right, and a button bar underneath. Every save goes through the model, then
   PUT /profile, then the preview re-renders -- so what you see is always what
   will be exported.

   Undo is per-window and holds the whole profile before each change, which is
   the same bargain the terminal made and is adequate at this size.
   ========================================================================= */

(function (global) {
'use strict';

const W = global.Win95;
const M = global.EditorModel;

let history = null;
let current = null;          // the section being edited
let rec = null;              // the window record

/* ------------------------------------------------------------- utilities */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function field(labelText, value, onInput, opts) {
  const o = opts || {};
  const wrap = el('div', 'ed-field');
  const label = el('label', 'ed-label', labelText);
  const input = o.multiline
    ? document.createElement('textarea')
    : document.createElement('input');
  input.className = 'field ed-input';
  if (!o.multiline) input.type = 'text';
  input.value = value === undefined || value === null ? '' : String(value);
  input.spellcheck = false;
  input.addEventListener('input', () => onInput(input.value));
  if (o.placeholder) input.placeholder = o.placeholder;
  label.htmlFor = '';
  wrap.appendChild(label);
  wrap.appendChild(input);
  wrap._input = input;
  return wrap;
}

function button(label, onClick, opts) {
  const o = opts || {};
  const b = el('button', 'btn' + (o.default ? ' default' : ''), label);
  b.type = 'button';
  if (o.title) b.title = o.title;
  b.addEventListener('click', () => { W.sfx.click(); onClick(); });
  return b;
}

/* Report a problem the same way Win95 would: a message box, not a red string
   nobody reads. Validation messages are already sentences. */
async function complain(problems) {
  const lines = problems.slice(0, 8).map((p) => '• ' + p.message);
  if (problems.length > 8) lines.push('…and ' + (problems.length - 8) + ' more.');
  await W.messageBox({
    title: 'Sheetsworks', icon: 'warning',
    heading: problems.length === 1 ? 'One thing to fix' : problems.length + ' things to fix',
    message: lines.join('\n'),
    buttons: ['OK'],
  });
}

function status(text, where) {
  W.setStatus('editor', text, where || 'left');
}

/* -------------------------------------------------------------- rendering */

function sectionLabel(key) {
  const n = M.count(state.profile, key);
  const s = M.spec(key);
  return s.label + (n ? '  (' + n + ')' : '  —');
}

let state = { profile: null, onChanged: null, template: 'sheets' };

function renderSections(host) {
  host.textContent = '';
  M.ORDER.forEach((key) => {
    const row = el('div', 'listbox-row', sectionLabel(key));
    row.setAttribute('data-section', key);
    row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', String(current === key));
    // A section the active template will not print is marked, not hidden:
    // hiding it would look like data loss.
    if (key === 'summary' && state.template !== 'blank') row.setAttribute('data-hidden', 'true');
    if (key === 'interests' && state.template !== 'sheets') row.setAttribute('data-hidden', 'true');
    row.addEventListener('click', () => select(key));
    host.appendChild(row);
  });
}

/* The fields for the selected section. */
function renderFields(host) {
  host.textContent = '';
  const key = current;
  const spec = M.spec(key);
  if (!spec) { host.appendChild(el('p', 'ed-blurb', 'Pick a section on the left.')); return; }

  host.appendChild(el('p', 'ed-blurb', spec.blurb));

  if (spec.kind === 'text') {
    const value = state.profile[key] || '';
    host.appendChild(field(key === 'summary' ? 'Summary' : 'Interests', value,
      (v) => write(key, null, 'text', v),
      { multiline: key === 'summary' }));
    return;
  }

  if (spec.kind === 'contact') {
    const c = state.profile.contact || (state.profile.contact = {});
    ['name', 'email', 'phone', 'city', 'country'].forEach((f) => {
      host.appendChild(field(f, c[f], (v) => write(key, null, f, v)));
    });
    /* Read-only on purpose. It looks like a field, so it used to accept typing and
     then silently throw it away, which is the worst of both. Links are added
     with the button below, which is honest about what it does. */
    const linksField = field('links', (c.links || [])
      .map((l) => l.label + ' ' + l.url).join(', '), () => {},
      { placeholder: 'none yet' });
    linksField.querySelector('.ed-input').readOnly = true;
    host.appendChild(linksField);
    host.appendChild(lineButton('Add a link', () => {
      askText('Add a link', 'label and url', (v) => {
        try { apply(key, null, 'link', v); } catch (e) { complain([{ message: e.message }]); }
      });
    }));
    return;
  }

  /* A list section: an entry picker, then that entry's fields. */
  const entries = M.entries(state.profile, key);
  const bar = el('div', 'ed-entries');
  const picker = el('div', 'listbox ed-picker');
  picker.setAttribute('data-role', 'entries');
  if (!entries.length) {
    picker.appendChild(el('div', 'listbox-row dim', 'Nothing here yet.'));
  }
  entries.forEach((e, i) => {
    const row = el('div', 'listbox-row', describe(key, e, i + 1));
    row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', String(picked === i + 1));
    row.addEventListener('click', () => { picked = i + 1; renderFields(host); });
    picker.appendChild(row);
  });
  bar.appendChild(picker);

  const tools = el('div', 'ed-tools');
  tools.appendChild(button('New', () => {
    try {
      history.push(JSON.stringify(state.profile));
      const n = M.addEntry(state.profile, key, null);
      picked = n;
      changed();
      renderFields(host);
    } catch (e) { complain([{ message: e.message }]); }
  }, { title: 'Add an entry to ' + spec.label }));
  if (entries.length) {
    tools.appendChild(button('Delete', async () => {
      const ok = await W.messageBox({
        title: spec.label, icon: 'warning',
        heading: 'Delete entry ' + picked + '?',
        message: 'This cannot be undone from here, but Ctrl+Z reverts the last change.',
        buttons: ['Delete', 'Cancel'],
      });
      if (ok !== 'Delete') return;
      try {
        history.push(JSON.stringify(state.profile));
        M.removeEntry(state.profile, key, picked);
        picked = Math.min(picked, M.entries(state.profile, key).length) || 1;
        changed();
        renderFields(host);
      } catch (e) { complain([{ message: e.message }]); }
    }, { title: 'Remove the selected entry' }));
    tools.appendChild(button('Up', () => reorder(key, picked, picked - 1, host),
      { title: 'Move it earlier' }));
    tools.appendChild(button('Down', () => reorder(key, picked, picked + 1, host),
      { title: 'Move it later' }));
  }
  bar.appendChild(tools);
  host.appendChild(bar);

  const entry = entries[picked - 1];
  if (!entry) return;

  (spec.fields || []).forEach((f) => {
    if (f === 'type') {
      host.appendChild(selectField('type', entry.type || 'job', (v) =>
        write(key, picked, 'type', v), M.EXPERIENCE_TYPES));
      return;
    }
    host.appendChild(field(f, entry[f], (v) => write(key, picked, f, v)));
  });

  if (spec.grade) {
    const g = entry.grade || { value: '', scale: '' };
    const row = el('div', 'row');
    row.appendChild(field('grade', g.value, (v) => write(key, picked, 'grade', v)));
    row.appendChild(field('scale', g.scale, (v) => write(key, picked, 'scale', v)));
    host.appendChild(row);
  }

  if (entry.links && entry.links.length) {
    host.appendChild(el('div', 'ed-sub', 'Links: ' +
      entry.links.map((l) => l.label + ' → ' + l.url).join(', ')));
  }

  /* Bullets deserve their own block: they are the evidence, and a bullet is an
     object with a text field, not a bare line. */
  if (Array.isArray(entry.bullets)) {
    const box = el('div', 'groupbox');
    box.appendChild(el('span', 'groupbox-legend', 'Bullets'));
    (entry.bullets || []).forEach((b, i) => {
      const line = el('div', 'ed-bullet');
      const txt = M.bulletText(b);
      line.appendChild(el('span', 'ed-bullet-n', String(i + 1) + '.'));
      line.appendChild(el('span', 'ed-bullet-t', txt));
      const del = el('button', 'btn btn-icon', 'x');
      del.type = 'button';
      del.title = 'Delete this bullet';
      del.addEventListener('click', () => {
        history.push(JSON.stringify(state.profile));
        entry.bullets.splice(i, 1);
        changed();
        renderFields(host);
      });
      line.appendChild(del);
      box.appendChild(line);
    });
    host.appendChild(box);
    host.appendChild(lineButton('Add a bullet', () => {
      askText('Add a bullet',
        'the claim, optionally: claim | the numbers behind it', (v) => {
          try { apply(key, picked, 'bullet', v); } catch (e) { complain([{ message: e.message }]); }
        });
    }));
    /* Tell the AI: per-section assistant for bullet writing. Only for
       sections that support it — Experience, Projects, Achievements. */
    const aiSections = ['experience', 'projects', 'achievements_awards'];
    if (aiSections.includes(key)) {
      host.appendChild(lineButton('Tell the AI...', () => openAiAssist(key, picked, host),
        { title: 'Ask the AI to write or polish bullets for this entry' }));
    }
  }

  (Object.keys(spec.appenders || {})).forEach((f) => {
    if (f === 'bullet') return;                 // handled above
    const target = { coursework: 'coursework', tech: 'tech', item: 'items' }[f];
    const list = entry[target] || [];
    if (list.length) {
      host.appendChild(el('div', 'ed-sub', (spec.label === 'Skills' ? '' : f) +
        ': ' + list.join(', ')));
    }
    host.appendChild(lineButton('Add ' + f, () => {
      askText('Add ' + f, 'one at a time', (v) => {
        try { apply(key, picked, f, v); } catch (e) { complain([{ message: e.message }]); }
      });
    }));
  });
}

let picked = 1;

function select(key) {
  current = key;
  picked = 1;
  renderSections(sectionHost);
  renderFields(fieldHost);
}

function describe(key, entry, n) {
  if (key === 'skills') return n + '. ' + (entry.name || '(no name)');
  const bits = [];
  if (entry.org) bits.push(entry.role ? entry.role + ', ' + entry.org : entry.org);
  if (entry.institution) bits.push(entry.institution);
  if (entry.name) bits.push(entry.name);
  if (!bits.length && entry.text) bits.push(String(entry.text).slice(0, 40));
  return n + '. ' + (bits.join('  |  ') || '(no details)');
}

/* A full-width field with a button, for the append-only pseudo-fields. */
function lineButton(label, onClick) {
  const b = button(label, onClick);
  b.classList.add('ed-wide');
  return b;
}

/* The Win95 answer to "type a value": a tiny one-field dialog. Reused for every
   append, so there is exactly one place a value is typed into a dialog. */
function askText(title, hint, onOk) {
  const dlg = W.createWindow({
    dialog: true, modal: true, title: title, icon: 'app',
    w: 380, h: 'auto', status: false, minimisable: false, resizable: false,
  });
  const f = field(hint, '', () => {}, { multiline: true });
  f.style.marginBottom = '10px';
  dlg.body.appendChild(el('p', 'ed-blurb', hint));
  dlg.body.appendChild(f);
  const bar = el('div', 'msg-buttons');
  const okBtn = button('OK', () => {
    const v = f._input.value.trim();
    W.close(dlg.id);
    if (v) onOk(v);
  }, { default: true });
  const cancelBtn = button('Cancel', () => W.close(dlg.id));
  bar.appendChild(okBtn);
  bar.appendChild(cancelBtn);
  dlg.body.appendChild(bar);
  setTimeout(() => f._input.focus(), 0);
  return dlg;
}

/* Tell the AI: a per-section dialog for bullet writing. */
async function openAiAssist(sectionKey, entryIndex, host) {
  const spec = M.spec(sectionKey);
  const entries = M.entries(state.profile, sectionKey);
  const entry = entries[entryIndex - 1];
  if (!entry) return;

  /* Step 1: free-text dump. */
  const dumpDlg = W.createWindow({
    dialog: true, modal: true, title: 'Tell the AI — ' + spec.label, icon: 'app',
    w: 460, h: 340, status: false, minimisable: false, resizable: false,
  });
  dumpDlg.body.appendChild(el('p', 'ed-blurb',
    'Paste or type a rough description of what you did. The AI will ask clarifying questions, then write bullets.'));
  const textarea = el('textarea', 'field', '');
  textarea.className = 'field';
  textarea.style.width = '100%';
  textarea.style.height = '140px';
  textarea.style.resize = 'vertical';
  dumpDlg.body.appendChild(textarea);
  const bar1 = el('div', 'msg-buttons');
  const cancel1 = button('Cancel', () => W.close(dumpDlg.id));
  const next1 = button('Continue', async () => {
    const text = textarea.value.trim();
    if (!text) { textarea.focus(); return; }
    bar1.querySelectorAll('button').forEach(b => b.disabled = true);
    try {
      const res = await fetch('/assist/' + encodeURIComponent(sectionKey), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ free_text: text }),
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      W.close(dumpDlg.id);
      if (data.questions && data.questions.length) {
        showQuestions(sectionKey, entryIndex, text, data, host);
      } else {
        showSuggestions(sectionKey, entryIndex, text, '', data, host);
      }
    } catch (err) {
      bar1.querySelectorAll('button').forEach(b => b.disabled = false);
      await W.messageBox({ title: 'Error', icon: 'error', heading: 'AI request failed', message: err.message, buttons: ['OK'] });
    }
  }, { default: true });
  bar1.appendChild(cancel1);
  bar1.appendChild(next1);
  dumpDlg.body.appendChild(bar1);
  setTimeout(() => textarea.focus(), 0);
}

/* Step 2: show clarifying questions, collect answers. */
async function showQuestions(sectionKey, entryIndex, freeText, data, host) {
  const spec = M.spec(sectionKey);
  const qDlg = W.createWindow({
    dialog: true, modal: true, title: 'Questions — ' + spec.label, icon: 'app',
    w: 460, h: 380, status: false, minimisable: false, resizable: false,
  });
  qDlg.body.appendChild(el('p', 'ed-blurb', 'The AI needs a few details before it can write strong bullets:'));
  const inputs = [];
  data.questions.forEach((q, i) => {
    qDlg.body.appendChild(el('label', 'ed-label', (i + 1) + '. ' + q));
    const inp = el('input', 'field');
    inp.className = 'field';
    inp.style.width = '100%';
    qDlg.body.appendChild(inp);
    inputs.push(inp);
  });
  const bar2 = el('div', 'msg-buttons');
  const cancel2 = button('Cancel', () => W.close(qDlg.id));
  const done2 = button('Done', async () => {
    const answers = inputs.map((inp, i) => (i + 1) + '. ' + (inp.value || '(no answer)')).join('\n');
    bar2.querySelectorAll('button').forEach(b => b.disabled = true);
    try {
      const res = await fetch('/assist/answer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ section: sectionKey, facts: freeText, answers: answers }),
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const result = await res.json();
      W.close(qDlg.id);
      showSuggestions(sectionKey, entryIndex, freeText, answers, result, host);
    } catch (err) {
      bar2.querySelectorAll('button').forEach(b => b.disabled = false);
      await W.messageBox({ title: 'Error', icon: 'error', heading: 'AI request failed', message: err.message, buttons: ['OK'] });
    }
  }, { default: true });
  bar2.appendChild(cancel2);
  bar2.appendChild(done2);
  qDlg.body.appendChild(bar2);
  setTimeout(() => inputs[0] && inputs[0].focus(), 0);
}

/* Step 3: show polished bullets, accept/edit/reject. */
async function showSuggestions(sectionKey, entryIndex, freeText, answers, data, host) {
  const spec = M.spec(sectionKey);
  const entry = M.entries(state.profile, sectionKey)[entryIndex - 1];
  if (!entry) return;

  const sDlg = W.createWindow({
    dialog: true, modal: true, title: 'AI Bullet Suggestions — ' + spec.label, icon: 'app',
    w: 520, h: 400, status: false, minimisable: false, resizable: false,
  });
  sDlg.body.appendChild(el('p', 'ed-blurb', 'Accept, edit, or reject each suggestion. Accepted bullets are added to this entry.'));
  const bullets = data.bullets || [];
  if (!bullets.length) {
    sDlg.body.appendChild(el('p', 'ed-blurb', 'The AI did not produce any bullets. Try adding more detail above.'));
  }
  const list = el('div', 'ed-bullet-list');
  bullets.forEach((b, i) => {
    const row = el('div', 'ed-bullet-suggestion');
    const ta = el('textarea', 'field', b);
    ta.className = 'field';
    ta.style.width = '100%';
    ta.style.height = '44px';
    ta.style.resize = 'vertical';
    row.appendChild(ta);
    const actions = el('div', 'ed-bullet-actions');
    const accept = button('Accept', async () => {
      const text = ta.value.trim();
      if (!text) return;
      history.push(JSON.stringify(state.profile));
      const facts = freeText + (answers ? '\n' + answers : '');
      entry.bullets.push(M.makeBullet(text, facts));
      changed();
      renderFields(host);
      W.close(sDlg.id);
    });
    const reject = button('Reject', () => row.remove());
    actions.appendChild(accept);
    actions.appendChild(reject);
    row.appendChild(actions);
    list.appendChild(row);
  });
  sDlg.body.appendChild(list);

  const bar3 = el('div', 'msg-buttons');
  const close = button('Close', () => W.close(sDlg.id));
  bar3.appendChild(close);
  sDlg.body.appendChild(bar3);
}

function selectField(labelText, value, onChange, options) {
  const wrap = el('div', 'ed-field');
  wrap.appendChild(el('label', 'ed-label', labelText));
  const sel = document.createElement('select');
  sel.className = 'field';
  options.forEach((o) => {
    const opt = document.createElement('option');
    opt.value = o;
    opt.textContent = o;
    if (o === value) opt.selected = true;
    sel.appendChild(opt);
  });
  sel.addEventListener('change', () => onChange(sel.value));
  wrap.appendChild(sel);
  return wrap;
}

/* ------------------------------------------------------------------ writes */

function write(section, index, name, value) {
  apply(section, index, name, value);
}

function apply(section, index, name, value) {
  history.push(JSON.stringify(state.profile));
  try {
    const said = M.setField(state.profile, section, index, name, value);
    changed(said);
  } catch (err) {
    // Roll back: a rejected write must not leave an undo frame that undoes
    // nothing and a profile the user did not intend.
    try { history.undo(state.profile); } catch (_) { /* nothing to undo */ }
    complain([{ message: err.message }]);
  }
}

function reorder(section, from, to, host) {
  if (to < 1 || to > M.entries(state.profile, section).length) return;
  history.push(JSON.stringify(state.profile));
  try {
    M.moveEntry(state.profile, section, from, to);
    picked = to;
    changed();
    renderFields(host);
  } catch (err) { complain([{ message: err.message }]); }
}

let changedTimer = null;

function changed(said) {
  status(said ? said + ' — not saved yet' : 'Changed — not saved yet');
  markDirty(true);
  clearChangedTimer();
}

/* Autosave, debounced. The terminal did the same; without it every field would
   need its own Save press, which is not how a form is used. */
function clearChangedTimer() {
  if (changedTimer) clearTimeout(changedTimer);
  changedTimer = setTimeout(() => { changedTimer = null; save(false); }, 1200);
}

let dirty = false;

function markDirty(v) {
  dirty = v;
  const t = rec && rec.title;
  if (t) t.textContent = (v ? '* ' : '') + titleBase();
}

function titleBase() {
  const n = state.profile && state.profile.contact && state.profile.contact.name;
  return 'My Resume' + (n ? ' - ' + n : '');
}

async function save(explicit) {
  if (!dirty && !explicit) return;
  const problems = M.validate(state.profile);
  if (problems.length) {
    if (explicit) await complain(problems);
    status(problems.length + ' thing(s) to fix before this can be saved');
    markDirty(true);
    return;
  }
  clearChangedTimer();
  dirty = false;
  markDirty(false);
  await global.Sheetsworks.saveProfile(explicit ? 'Saved' : 'Autosaved');
  if (state.onChanged) state.onChanged();
}

function undo() {
  if (!history || !history.canUndo()) {
    status('nothing to undo');
    return;
  }
  try {
    history.undo(state.profile);
    changed('undone');
    renderSections(sectionHost);
    renderFields(fieldHost);
  } catch (err) { status(err.message); }
}

/* -------------------------------------------------------------------- open */

let sectionHost = null;
let fieldHost = null;

function open(profile, opts) {
  const o = opts || {};
  state = {
    profile: profile,
    onChanged: o.onChanged || null,
    template: o.template || 'sheets',
  };
  history = new M.History();
  dirty = false;
  current = M.filled(profile)[0] || 'contact';
  picked = 1;

  rec = W.createWindow({
    id: 'editor', title: titleBase(), icon: 'resume',
    w: 700, h: 480, minWidth: 520, minHeight: 340,
    menus: [
      { label: 'File', items: [
        { label: 'Save', accel: 'Ctrl+S', action: () => save(true) },
        { sep: true },
        { label: 'Close', accel: 'Alt+F4', action: () => close() },
      ] },
      { label: 'Edit', items: [
        { label: 'Undo', accel: 'Ctrl+Z', action: undo },
      ] },
      { label: 'View', items: [
        { label: 'Preview', action: () => global.Sheetsworks.openPreview() },
        { label: 'File Manager', action: () => global.Sheetsworks.openFileManager() },
      ] },
      { label: 'Help', items: [
        { label: 'Read Me', action: () => global.Sheetsworks.openReadMe() },
      ] },
    ],
    toolbar: [
      { icon: 'save', label: 'Save', action: () => save(true) },
      { icon: 'find', label: 'Preview', action: () => global.Sheetsworks.openPreview() },
      { sep: true },
      { icon: 'delete', label: 'Undo', action: undo },
    ],
    statusText: 'Ready',
    onClose: () => {
      // Unsaved work must not vanish silently. Ask, and save if they say yes.
      if (!dirty) return true;
      W.messageBox({
        title: 'My Resume', icon: 'warning',
        heading: 'Save before closing?',
        message: 'You have changes that are not saved yet.',
        buttons: ['Save', 'Discard', 'Cancel'],
      }).then((answer) => {
        if (answer === 'Save') { save(true).then(() => W.close('editor')); }
        else if (answer === 'Discard') { dirty = false; W.close('editor'); }
      });
      return false;                       // handled above, once they answer
    },
  });

  const fill = el('div', 'well-fill');
  const split = el('div', 'split ed-split');
  sectionHost = el('div', 'listbox ed-sections');
  sectionHost.setAttribute('data-role', 'sections');
  fieldHost = el('div', 'ed-fields');
  split.appendChild(sectionHost);
  split.appendChild(fieldHost);
  fill.appendChild(split);

  const bar = el('div', 'ed-bar');
  bar.appendChild(button('Save', () => save(true), { default: true }));
  bar.appendChild(button('Undo', undo));
  bar.appendChild(button('Close', () => close()));
  bar.appendChild(el('span', 'ed-count grow'));
  fill.appendChild(bar);

  rec.body.appendChild(fill);
  renderSections(sectionHost);
  renderFields(fieldHost);

  /* Ctrl+S saves, Ctrl+Z undoes -- the two everyone tries first. */
  rec.el.addEventListener('keydown', (ev) => {
    if (!ev.ctrlKey) return;
    if (ev.key === 's') { ev.preventDefault(); save(true); }
    else if (ev.key === 'z') { ev.preventDefault(); undo(); }
  });

  return rec;
}

function close() { W.close('editor'); }

function refresh(newProfile) {
  if (!rec || !W.windows.get('editor')) return;
  /* app.js and editor.js each hold a reference to the profile, and the app
     reloads it from the server on every boot. The form must adopt the new
     object or it keeps showing the empty one it was opened with -- which is
     exactly what happened: the title bar read "Dusht Verma" while every
     section showed as empty. */
  if (newProfile) state.profile = newProfile;
  rec.title.textContent = (dirty ? '* ' : '') + titleBase();
  renderSections(sectionHost);
  renderFields(fieldHost);
}

function setTemplate(name) {
  state.template = name;
  refresh();
}

global.EditorForm = { open, refresh, setTemplate, save, undo,
  get isDirty() { return dirty; } };

})(window);