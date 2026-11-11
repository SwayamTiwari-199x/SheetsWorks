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
  /* `done` is false on every keystroke and true on blur. A date box needs the
     difference: half a date ("Jul", "July 2") is unreadable, so the keystroke
     pass must not complain, but the blur pass must -- otherwise the field would
     accept anything. Blur is also when the section redraws, so the stored form
     replaces what was typed. Every other box ignores `done`. */
  input.addEventListener('input', () => onInput(input.value, false));
  if (o.onCommit) {
    input.addEventListener('change', () => onInput(input.value, true));
  }
  if (o.placeholder) input.placeholder = o.placeholder;
  label.htmlFor = '';
  if (!o.hideLabel) wrap.appendChild(label);
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
    renderLinks(host, 'Links', () => M.linkOwner(state.profile, 'contact'), null);
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
      history.push(state.profile);
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
        history.push(state.profile);
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
    host.appendChild(field(f, entry[f], (v, done) => write(key, picked, f, v, done),
      M.isDateField(key, f) ? { onCommit: true } : undefined));
  });

  if (spec.grade) {
    const g = entry.grade || { value: '', scale: '' };
    const row = el('div', 'row');
    row.appendChild(field('grade', g.value, (v) => write(key, picked, 'grade', v)));
    row.appendChild(field('scale', g.scale, (v) => write(key, picked, 'scale', v)));
    host.appendChild(row);
  }

  if (entry.links) {
    renderLinks(host, 'Links', () => entry, picked);
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
        history.push(state.profile);
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
        'the claim, optionally: claim | the numbers behind it', (v) =>
          applyFn(() => M.setField(state.profile, key, picked, 'bullet', v), true));
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
    renderItemList(host, spec, f, key, picked, entry);
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
function lineButton(label, onClick, opts) {
  const b = button(label, onClick, opts);
  b.classList.add('ed-wide');
  return b;
}

/* ------------------------------------------------------- list rendering */
/* One item per row, with its own Edit and Remove. This replaces a single line of
   comma-joined text that could only ever be appended to: a typo was permanent
   (the only fix was deleting the group and retyping it), and a duplicate such as
   "Python, Python" was invisible. Rows also mean the group is spelled out once
   per item instead of being parsed out of a sentence. */

function renderItemList(host, spec, f, key, index, entry) {
  const items = M.listOf(state.profile, key, index, f) || [];
  const legend = f === 'item' ? 'Items' : f.charAt(0).toUpperCase() + f.slice(1);

  const box = el('div', 'groupbox');
  box.appendChild(el('span', 'groupbox-legend', legend));
  if (!items.length) {
    box.appendChild(el('div', 'ed-sub dim', 'Nothing here yet.'));
  }
  items.forEach((text, i) => {
    box.appendChild(itemRow(text, i + 1, () => {
      askText('Edit item ' + (i + 1), 'the item as it should read, on its own',
        (v) => applyFn(() => M.setItem(state.profile, key, index, f, i + 1, v), true));
    }, () => applyFn(() => {
      M.removeItem(state.profile, key, index, f, i + 1);
    }, true)));
  });
  host.appendChild(box);

  /* For skills, the rendered line is the group name and its items, so it is
     shown verbatim: "Languages: Python, SQL, Go". Anything less would leave the
     user guessing how the group will appear on the page. */
  if (f === 'item') {
    const line = M.groupLabel(entry);
    if (line) host.appendChild(el('div', 'ed-sub', 'Printed as: ' + line));
  }

  host.appendChild(lineButton('Add ' + f, () => {
    askText('Add ' + f, 'one at a time', (v) =>
      applyFn(() => M.setField(state.profile, key, index, f, v), true));
  }));
}

function itemRow(text, n, onEdit, onRemove) {
  const row = el('div', 'ed-item');
  row.appendChild(el('span', 'ed-item-t', String(text)));
  const edit = el('button', 'btn btn-icon', 'edit');
  edit.type = 'button';
  edit.title = 'Edit this item';
  edit.addEventListener('click', onEdit);
  row.appendChild(edit);
  const del = el('button', 'btn btn-icon', 'x');
  del.type = 'button';
  del.title = 'Remove this item';
  del.addEventListener('click', onRemove);
  row.appendChild(del);
  return row;
}

/* Links are a list too, in Contact and in Projects. They were two things at
   once before: a read-only field that looked editable, and an "Add a link"
   dialog that took "label url" in one box, so a two-word label like "My GitHub"
   became the label "My". Both halves now get their own box and their own row. */
function renderLinks(host, legend, owner, index) {
  const c = owner();
  const links = c.links || [];

  const box = el('div', 'groupbox');
  box.appendChild(el('span', 'groupbox-legend', legend));
  if (!links.length) box.appendChild(el('div', 'ed-sub dim', 'None yet.'));
  links.forEach((l, i) => {
    const row = el('div', 'ed-item');
    row.appendChild(el('span', 'ed-item-t', l.label + ' — ' + l.url));
    const edit = el('button', 'btn btn-icon', 'edit');
    edit.type = 'button';
    edit.title = 'Edit this link';
    edit.addEventListener('click', () => askLink('Edit link ' + (i + 1), l,
      (pair) => applyFn(() => M.updateLink(owner(), i + 1, pair), true)));
    row.appendChild(edit);
    const del = el('button', 'btn btn-icon', 'x');
    del.type = 'button';
    del.title = 'Remove this link';
    del.addEventListener('click', () => applyFn(() => M.removeLink(owner(), i + 1), true));
    row.appendChild(del);
    box.appendChild(row);
  });
  host.appendChild(box);

  host.appendChild(lineButton('Add a link', () => askLink('Add a link', null,
    (pair) => applyFn(() => M.addLink(owner(), pair), true))));
}

function askLink(title, existing, onOk) {
  const dlg = W.createWindow({
    dialog: true, modal: true, title: title, icon: 'app',
    w: 400, h: 'auto', status: false, minimisable: false, resizable: false,
  });
  const lf = field('label', existing ? existing.label : '',
    () => {}, { placeholder: 'GitHub' });
  const uf = field('url', existing ? existing.url : '',
    () => {}, { placeholder: 'github.com/me' });
  lf.style.marginBottom = '6px';
  uf.style.marginBottom = '10px';
  dlg.body.appendChild(lf);
  dlg.body.appendChild(uf);
  const bar = el('div', 'msg-buttons');
  bar.appendChild(button('OK', () => {
    const label = lf._input.value.trim();
    const url = uf._input.value.trim();
    if (!label || !url) {
      complain([{ message: 'a link needs both a label and a url' }]);
      return;
    }
    W.close(dlg.id);
    onOk({ label: label, url: url });
  }, { default: true }));
  bar.appendChild(button('Cancel', () => W.close(dlg.id)));
  dlg.body.appendChild(bar);
  setTimeout(() => lf._input.focus(), 0);
  return dlg;
}

/* The Win95 answer to "type a value": a tiny one-field dialog. Reused for every
   append, so there is exactly one place a value is typed into a dialog. */
function askText(title, hint, onOk) {
  const dlg = W.createWindow({
    dialog: true, modal: true, title: title, icon: 'app',
    w: 380, h: 'auto', status: false, minimisable: false, resizable: false,
  });
  /* The hint is shown once, as the blurb above the box. It used to be passed to
   * field() as the label AND appended as a blurb, so "Add a bullet" printed its
   * instructions twice, which read as a mistake in the dialog rather than as
   * emphasis. The label is dropped instead of the blurb: the blurb carries the
   * whole sentence, and a truncated one-line label would cut it. */
  const f = field('', '', () => {}, { multiline: true, hideLabel: true });
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

/* The provider can take a minute, and on a truncated reply the server retries
   with a bigger token allowance before it gives up -- the last real run took
   80 seconds and spent three calls. The client timeout is deliberately larger
   than the server's own LLM_TIMEOUT_SECONDS (60) so that a slow-but-alive
   request is not aborted while the server is still legitimately working on it.
   Past this point something is actually wrong, and saying so beats a dialog
   that spins forever. */
const AI_TIMEOUT_MS = 150000;

/* One place for both AI calls, so the waiting state and the timeout cannot
 * drift apart between the two branches -- which is how a UI ends up with one
 * step that reports a timeout and another that hangs. */
async function callAssist(url, payload, dialogBody, bar) {
  const waiting = el('div', 'ai-waiting');
  waiting.appendChild(el('span', 'ai-waiting-icon', '\u25F3'));
  const note = el('span', 'ai-waiting-text',
    'Asking the AI. This can take a minute -- it is thinking, and a second '
    + 'pass happens if the reply runs out of room.');
  waiting.appendChild(note);
  dialogBody.appendChild(waiting);
  bar.querySelectorAll('button').forEach(b => { b.disabled = true; });

  const started = performance.now();
  const elapsed = () => Math.round((performance.now() - started) / 1000);
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, AI_TIMEOUT_MS);

  let message;
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!res.ok) {
      /* The server refused or the provider failed. Either way no bullet was
       * written, so say so rather than leaving the user to guess whether their
       * text survived. */
      const detail = await explainFailure(res);
      const err = new Error(
        (detail || ('The server answered ' + res.status + '.'))
        + ' Nothing was saved.');
      err.status = res.status;
      throw err;
    }
    return await res.json();
  } catch (err) {
    if (timedOut) {
      message = 'No answer after ' + Math.round(AI_TIMEOUT_MS / 1000)
        + ' seconds. The request was sent and may still be running on the '
        + 'server; nothing was saved. Check logs/llm.log for what the provider '
        + 'did, then try again.';
    } else if (err.name === 'AbortError') {
      message = 'The request was cancelled before it finished. Nothing was saved.';
    } else if (err instanceof TypeError) {
      message = 'Could not reach the app at ' + url + '. The server may have '
        + 'stopped (' + err.message + '). Nothing was saved.';
    } else {
      message = err.message;
    }
    throw new Error(message);
  } finally {
    clearTimeout(timer);
    bar.querySelectorAll('button').forEach(b => { b.disabled = false; });
    if (message) {
      /* Leave the line up, turned into the reason, instead of removing it. The
       * message box sits on top of it, so the user has the failure in the dialog
       * itself once they dismiss the box. */
      waiting.classList.add('ai-waiting-failed');
      waiting.querySelector('.ai-waiting-icon').textContent = '\u26A0';
      note.textContent = message + ' (' + elapsed() + 's)';
    } else {
      waiting.remove();
    }
  }
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
    try {
      const data = await callAssist(
        '/assist/' + encodeURIComponent(sectionKey), { free_text: text },
        dumpDlg.body, bar1);
      W.close(dumpDlg.id);
      if (data.questions && data.questions.length) {
        showQuestions(sectionKey, entryIndex, text, data, host);
      } else {
        showSuggestions(sectionKey, entryIndex, text, '', data, host);
      }
    } catch (err) {
      await W.messageBox({ title: 'Error', icon: 'error', heading: 'AI request failed', message: err.message, buttons: ['OK'] });
    }
  }, { default: true });
  bar1.appendChild(cancel1);
  bar1.appendChild(next1);
  dumpDlg.body.appendChild(bar1);
  setTimeout(() => textarea.focus(), 0);
}

/* Step 2: show clarifying questions, collect answers. */
/* The server's own words, not "HTTP 400". A provider 502 carries the message
   the provider sent back, which is the sentence that says what it disliked.
   explainFailure is defined in app.js; this file already depends on it existing
   for the export path, so the AI dialogs use the same one. */
/* Turning a failed response into words lives in failures.js, shared with app.js.
   The copy that used to be here dropped the entry number and left "Value error,"
   at the front of the sentence, so the same refusal read two different ways
   depending on which window ran it. */
const explainFailure = global.Failures.explainFailure;

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
    try {
      const result = await callAssist(
        '/assist/answer',
        { section: sectionKey, facts: freeText, answers: answers },
        qDlg.body, bar2);
      W.close(qDlg.id);
      showSuggestions(sectionKey, entryIndex, freeText, answers, result, host);
    } catch (err) {
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
  sDlg.body.appendChild(el('p', 'ed-blurb', 'Accept, edit, or reject each suggestion. Each one shows which of your facts it uses. Accepted bullets are added to this entry.'));
  const bullets = data.bullets || [];
  const factText = data.numbered_facts || [];
  const factLabel = (i) => {
    const text = factText[i - 1];
    return text ? 'Fact ' + i + ' — ' + text : 'Fact ' + i;
  };
  if (!bullets.length) {
    sDlg.body.appendChild(el('p', 'ed-blurb', 'The AI did not produce any bullets. Try adding more detail above.'));
  }
  const list = el('div', 'ed-bullet-list');
  bullets.forEach((b, i) => {
    const text = typeof b === 'string' ? b : (b.text || '');
    const ids = (typeof b === 'string' ? [] : (b.facts || []));
    const row = el('div', 'ed-bullet-suggestion');
    const ta = el('textarea', 'field', text);
    ta.className = 'field';
    ta.style.width = '100%';
    ta.style.height = '44px';
    ta.style.resize = 'vertical';
    row.appendChild(ta);
    const uses = el('div', 'ai-factline', 'Uses: ' + (ids.length ? ids.map(factLabel).join('  |  ') : 'no fact identified'));
    row.appendChild(uses);
    const actions = el('div', 'ed-bullet-actions');
    const accept = button('Accept', async () => {
      const typed = ta.value.trim();
      if (!typed) return;
      history.push(state.profile);
      const facts = freeText + (answers ? '\n' + answers : '');
      entry.bullets.push(M.makeBullet(typed, facts));
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

  /* Facts the bullets did not use, and figures spent twice. Both are computed
   * server-side; the model is not trusted to report either. */
  const unused = data.unused_facts || [];
  if (unused.length && factText.length) {
    const w = el('div', 'ai-warn');
    w.appendChild(el('div', 'ai-warn-head', 'Not used by any bullet:'));
    unused.forEach((id) => w.appendChild(el('div', 'ai-warn-line', '• ' + factLabel(id))));
    sDlg.body.appendChild(w);
  }
  const reused = data.reused_metrics || [];
  if (reused.length) {
    const w = el('div', 'ai-warn');
    w.appendChild(el('div', 'ai-warn-head', 'Same metric in more than one bullet: ' + reused.join(', ')));
    w.appendChild(el('div', 'ai-warn-line', 'Each figure should be spent by only one bullet. Edit or reject one of them.'));
    sDlg.body.appendChild(w);
  }
  const shared = data.shared_facts || [];
  if (shared.length && factText.length) {
    const w = el('div', 'ai-warn');
    w.appendChild(el('div', 'ai-warn-head', 'More than one bullet rests on the same fact:'));
    shared.forEach((id) => w.appendChild(el('div', 'ai-warn-line', '• ' + factLabel(id))));
    w.appendChild(el('div', 'ai-warn-line', 'Two bullets on one claim are the same achievement twice. Keep the stronger one.'));
    sDlg.body.appendChild(w);
  }

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

/* `done` is true when the box is finished (a date box on blur) rather than
   mid-keystroke. Only then does the section redraw, because a normalised date
   is meant to be shown in its stored form and the fields have to be rebuilt to
   show it. Per keystroke, a redraw would destroy the input being typed into.

   A half-typed date is unreadable, so the keystroke pass stays quiet rather
   than throwing a message box at every character. It still writes whatever it
   can read, so the autosave is not held back by a field nobody finished. */
function write(section, index, name, value, done) {
  apply(section, index, name, value, done);
}

function apply(section, index, name, value, done) {
  /* `done` is the only thing that may rebuild: a date box replaces what was
     typed with the stored form when it commits, and every other box ignores it.
     Coerced here rather than at the call sites so that no text field can be
     given a redraw by forgetting an argument. */
  applyFn(() => M.setField(state.profile, section, index, name, value),
          done === true, done !== true);
}

/* Every write goes through here: snapshot, mutate, mark changed, or roll the
   snapshot back and say why. A rejected write must not leave an undo frame that
   undoes nothing and a profile the user did not intend.

   `redrawOk` is for the writes that change the shape of the section -- adding
   or removing a list row -- where the fields have to be rebuilt to show the
   change. Text edits never are.

   The test is `=== true`, deliberately. A rebuild replaces the input element,
   so the browser drops the caret onto the body and the next keystroke lands
   nowhere: typing a word then cost one click per letter. Defaulting a missing
   flag to "rebuild" made that the case for every field whose callback did not
   bother to pass one, which was every field except the list entries. A flag
   that is forgotten must be safe, so nothing redraws unless a caller has
   positively asked for it.

   `quiet` is for a write that is expected to fail while the user is still
   typing, so the rejection is rolled back silently instead of opening a message
   box per keystroke. The blur pass of a date field is the one that reports. */
function applyFn(fn, redrawOk, quiet) {
  history.push(state.profile);
  try {
    const said = fn();
    changed(said);
    if (redrawOk === true) renderFields(fieldHost);
  } catch (err) {
    try { history.undo(state.profile); } catch (_) { /* nothing to undo */ }
    if (!quiet) complain([{ message: err.message }]);
  }
}

function reorder(section, from, to, host) {
  if (to < 1 || to > M.entries(state.profile, section).length) return;
  history.push(state.profile);
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
     exactly what happened: the title bar read the placeholder name
     while every section showed as empty. */
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