/* ============================================================================
   app.js -- the Sheetsworks desktop: which windows exist and what they do.

   This is the only file that knows about your resume. The window manager in
   shell.js knows nothing about resumes; it just moves rectangles around. That
   split is deliberate: the chrome is reusable and the app is replaceable.

   Stage 5a is the shell only -- it opens the windows and proves drag, focus,
   minimise, maximise, menus, dialogs, the taskbar and the loading states work.
   The editor itself lands in 5b.
   ========================================================================= */

(function () {
'use strict';

const W = window.Win95;

/* --------------------------------------------------------------- storage -- */

const store = {
  get(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (_) { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* private mode */ }
  },
};

/* ------------------------------------------------------------- app state -- */

const state = {
  profile: null,
  template: 'sheets',
  tips: [],
  sound: store.get('rb.sound', false) === true,
};

/* ------------------------------------------------------------ small DOM --- */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function button(label, onClick, opts) {
  const o = opts || {};
  const b = el('button', 'btn' + (o.default ? ' default' : ''), label);
  b.type = 'button';
  if (o.title) b.title = o.title;
  b.addEventListener('click', () => { W.sfx.click(); onClick(); });
  return b;
}

/* The advice on screen is the research in RULES.md, served by the server into
   an inert <template>. A parse failure must not take the desktop down, so the
   Read Me window simply says it has nothing. */
function loadTips() {
  const holder = document.getElementById('tipsData');
  let text = '';
  try {
    if (holder.content && holder.content.textContent) text = holder.content.textContent;
    else if (typeof holder.textContent === 'string') text = holder.textContent;
    const parsed = JSON.parse(text || '{"tips":[]}');
    return Array.isArray(parsed.tips) ? parsed.tips : [];
  } catch (_) { return []; }
}

/* ------------------------------------------------------------- API calls -- */

async function api(path, opts) {
  const o = opts || {};
  const res = await fetch(path, {
    method: o.method || 'GET',
    headers: o.body ? { 'Content-Type': 'application/json' } : undefined,
    body: o.body ? JSON.stringify(o.body) : undefined,
  });
  if (!res.ok) {
    /* explainFailure, not JSON.stringify. A rejected save used to print
       [{"type":"...","loc":["body","experience",0,"start"],"msg":"Value error, ..."}]
       into a message box, which tells the person nothing about which box they
       got wrong. It is declared further down this file, so the same reader that
       un-breaks "[object Object]" now handles this too. */
    const err = new Error(await explainFailure(res));
    err.status = res.status;
    throw err;
  }
  return res;
}

/* Anything that talks to the server is wrapped in this, so every one of them
   gets the hourglass, the ellipsis title and the status bar for free -- and
   cannot forget to turn them off again. */
async function working(winId, label, fn) {
  W.setBusy(winId, true, label);
  try {
    return await fn();
  } catch (err) {
    W.sfx.error();
    await W.messageBox({
      title: 'Error', icon: 'error', heading: 'The operation failed',
      message: err.message || String(err), buttons: ['OK'],
    });
    throw err;
  } finally {
    W.setBusy(winId, false);
  }
}

/* ============================================================ desktop ==== */

const DESKTOP_ICONS = [
  { label: 'My Resume',  icon: 'resume',  run: () => openEditor() },
  { label: 'Sample Resume', icon: 'notepad', run: () => loadSample() },
  { label: 'File Manager', icon: 'folder', run: () => openFileManager() },
  { label: 'Read Me',     icon: 'help',    run: () => openReadMe() },
  { label: 'Preview',     icon: 'find',    run: () => openPreview() },
  { label: 'Export As',   icon: 'printer', run: () => openExport() },
  { label: 'Display',     icon: 'display', run: () => openDisplay() },
  { label: 'Sheetsworks', icon: 'computer', run: () => openAbout() },
];

function buildDesktop() {
  const host = document.getElementById('desktopIcons');
  host.textContent = '';
  // A column down the left, as on a real desktop.
  host.style.position = 'absolute';
  host.style.top = '8px';
  host.style.left = '8px';
  host.style.display = 'flex';
  host.style.flexDirection = 'column';
  host.style.gap = '6px';

  DESKTOP_ICONS.forEach((item) => {
    const b = el('div', 'desk-icon');
    b.setAttribute('role', 'button');
    b.setAttribute('tabindex', '0');
    b.setAttribute('aria-selected', 'false');
    const ic = W.icon(item.icon);
    ic.setAttribute('width', '32'); ic.setAttribute('height', '32');
    b.appendChild(ic);
    const label = el('span', null, item.label);
    b.appendChild(label);

    // One click selects, a second opens -- the Win95 idiom, and it means a
    // stray click never launches something.
    let armed = false;
    const armTimer = setTimeout(() => { armed = false; }, 1500);
    const activate = () => {
      W.sfx.click();
      if (armed) { clearTimeout(armTimer); armed = false; item.run(); }
      else {
        armed = true;
        host.querySelectorAll('.desk-icon').forEach((n) => n.setAttribute('aria-selected', 'false'));
        b.setAttribute('aria-selected', 'true');
      }
    };
    b.addEventListener('click', activate);
    b.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); item.run(); }
    });
    host.appendChild(b);
  });
}

/* ============================================================ windows ==== */

/* One window per app, reused. Opening "My Resume" twice should raise the
   window you already have, not stack two copies of the same form. */
const open = new Map();

function once(id, factory) {
  const existing = open.get(id);
  const rec = W.windows.get(id);
  if (rec && !rec.closing) { W.restore(id); return rec; }
  const created = factory();
  open.set(id, created);
  return created;
}

/* ---- About ------------------------------------------------------------- */

function openAbout() {
  return once('about', () => {
    const rec = W.createWindow({
      id: 'about', title: 'About Sheetsworks', icon: 'computer',
      w: 380, h: 250, status: false,
    });
    const row = el('div', 'msg-row');
    const ic = W.icon('computer');
    ic.setAttribute('class', 'msg-icon');
    row.appendChild(ic);
    const text = el('div', 'msg-text');
    const h = el('span', 'title', 'Sheetsworks');
    text.appendChild(h);
    text.appendChild(el('div', null,
      'A resume builder with a Windows 95 desktop, a profile editor, and a File Manager' +
      'with Resume and Versions tabs. Export produces valid PDF, DOCX, or TXT. A profile'));
    text.appendChild(el('div', null, 'Two formats: blank and sheets. See Read Me for why.'));
    row.appendChild(text);
    rec.body.appendChild(row);

    const bar = el('div', 'msg-buttons');
    bar.appendChild(button('OK', () => W.close('about'), { default: true }));
    rec.body.appendChild(bar);
    return rec;
  });
}

/* ---- Read Me: the research -------------------------------------------- */

function openReadMe() {
  return once('readme', () => {
    const rec = W.createWindow({
      id: 'readme', title: 'Read Me - Sheetsworks', icon: 'notepad',
      w: 520, h: 420,
      menus: [
        { label: 'File', items: [{ label: 'Close', accel: 'Alt+F4', action: () => W.close('readme') }] },
        { label: 'Help', items: [{ label: 'About Sheetsworks', action: openAbout }] },
      ],
      statusText: state.tips.length + ' notes',
    });
    const fill = el('div', 'well-fill');
    fill.style.overflowY = 'auto';
    fill.style.flex = '1 1 auto';

    if (!state.tips.length) {
      fill.appendChild(el('div', null, 'No research notes were loaded.'));
    } else {
      state.tips.forEach((tip) => {
        const block = el('div');
        block.style.paddingBottom = '10px';
        block.style.marginBottom = '10px';
        block.style.borderBottom = '1px solid #808080';

        const head = el('div');
        head.style.fontWeight = 'bold';
        head.textContent = tip.title || '';
        const tag = el('span', null, ' [' + (tip.tag || 'unverified') + ']');
        // Colour the tag rather than hiding it: half this advice rests on a
        // single source and the reader is entitled to know which half.
        tag.style.color = tip.tag === 'verified' ? '#006000' : '#a00000';
        tag.style.fontWeight = 'normal';
        head.appendChild(tag);
        block.appendChild(head);

        block.appendChild(el('div', null, tip.body || ''));
        const src = el('div', 'dim', tip.source || '');
        src.style.fontSize = '10px';
        block.appendChild(src);
        fill.appendChild(block);
      });
    }
    rec.body.appendChild(fill);
    return rec;
  });
}

/* ---- Display: the theme picker ---------------------------------------- */

function openDisplay() {
  return once('display', () => {
    const rec = W.createWindow({
      id: 'display', title: 'Display Properties', icon: 'display',
      w: 340, h: 240, status: false, minimisable: false,
    });
    const fill = el('div', 'well-fill');

    const box = el('div', 'groupbox');
    box.appendChild(el('span', 'groupbox-legend', 'Resume format'));
    const list = el('div', 'listbox');
    list.style.height = '92px';
    [['blank', 'blank  -  every section, including a summary'],
     ['sheets', 'sheets  -  no summary, one Interests line at the end']]
      .forEach(([key, label]) => {
        const row = el('div', 'listbox-row', label);
        row.setAttribute('data-template', key);
        row.setAttribute('role', 'option');
        row.setAttribute('aria-selected', String(state.template === key));
        row.addEventListener('click', () => {
          state.template = key;
          store.set('rb.template', state.template);
          W.setStatus('display', 'Format set to ' + state.template, 'right');
          list.querySelectorAll('.listbox-row').forEach((r) => {
            r.setAttribute('aria-selected', String(r === row));
          });
          if (window.EditorForm) window.EditorForm.setTemplate(state.template);
          renderTemplateHint();
        });
        list.appendChild(row);
      });
    box.appendChild(list);

    const hint = el('div', 'dim', '');
    hint.style.marginTop = '8px';
    hint.style.fontSize = '10px';
    box.appendChild(hint);
    fill.appendChild(box);

    function renderTemplateHint() {
      hint.textContent = state.template === 'sheets'
        ? 'One page. Files are named "First Last Resume".'
        : 'Two pages for an experienced candidate.';
    }
    renderTemplateHint();

    // Content first, then the buttons. Appending the button bar before the group
    // box put OK/Cancel/Help above the thing they act on, which is not how a
    // dialog is arranged anywhere, Windows included.
    rec.body.appendChild(fill);

    const bar = el('div', 'msg-buttons');
    bar.appendChild(button('OK', () => W.close('display'), { default: true }));
    bar.appendChild(button('Cancel', () => W.close('display')));
    bar.appendChild(button('Help', () => openAbout()));
    rec.body.appendChild(bar);
    return rec;
  });
}

/* ---- File Manager: your resume, and its saved snapshots ----------------- */
/* It has two modes, chosen by a tab bar rather than a menu, because both are
   things you look at and the switch should cost no clicks:
     Resume   -- the live profile: sections on the left, entries on the right.
     Versions -- saved snapshots from GET /versions, with export and delete.
   The Versions mode is why that endpoint exists. Without it snapshots were
   write-only: you could make one and never see it again. */

const FM_TABS = [['resume', 'Resume'], ['versions', 'Versions']];
let fmMode = 'resume';
let fmVersions = null;

/* --- profile JSON download / upload ------------------------------------ */
/* The minimum Stage 3 asked for and never got. Both directions are thin on
   purpose: GET /profile already returns exactly the file, and PUT /profile
   already validates it, so the server needs nothing new and there is no way for
   the two sides to disagree about the format. */

/* Shared by the JSON download and the PDF/DOCX/TXT export, so there is one place
   that hands a blob to the browser and one revoke policy. */
function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  // Revoke late: Safari and Firefox have been known to cancel the download if the
  // URL disappears in the same tick as the click.
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

function profileJsonFilename() {
  const n = state.profile && state.profile.contact && state.profile.contact.name;
  return (n ? n : 'profile').trim() + '.json';
}

async function downloadProfileJson() {
  try {
    const res = await api('/profile');
    if (res.status === 404) {
      await W.messageBox({
        title: 'Download Profile', icon: 'warning',
        heading: 'Nothing to download',
        message: 'There is no saved profile yet. Fill in My Resume and save it first.',
        buttons: ['OK'],
      });
      return;
    }
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const blob = await res.blob();
    const filename = profileJsonFilename();
    triggerDownload(blob, filename);
    W.setStatus('fm', 'Saved ' + filename + ' (' + blob.size + ' bytes)', 'right');
  } catch (err) {
    W.sfx.error();
    W.setStatus('fm', 'Download failed: ' + err.message, 'right');
  }
}

/* Upload. Read and parsed in the browser, confirmed with the user, and only then
   sent -- asking permission after the write would be theatre.

   A malformed profile comes back as a 422 from the same validator that guards
   every other write, and the server's own text is shown: "name: field required"
   is the difference between a message the user can act on and "upload failed". */
function uploadProfileJson() {
  const picker = document.createElement('input');
  picker.type = 'file';
  picker.accept = 'application/json,.json';
  picker.addEventListener('change', async () => {
    const file = picker.files && picker.files[0];
    if (!file) return;
    let parsed;
    try {
      parsed = JSON.parse(await file.text());
    } catch (err) {
      W.sfx.error();
      await W.messageBox({
        title: 'Upload Profile', icon: 'error',
        heading: 'That file is not valid JSON',
        message: String(err.message),
        buttons: ['OK'],
      });
      return;
    }
    const answer = await W.messageBox({
      title: 'Upload Profile', icon: 'warning',
      heading: 'Replace the saved profile?',
      message: 'File: ' + file.name + '\n\nThis overwrites the profile in full. '
        + 'Nothing is merged, and nothing is kept.',
      buttons: ['Replace', 'Cancel'],
    });
    if (answer !== 'Replace') {
      W.setStatus('fm', 'Upload cancelled', 'right');
      return;
    }
    try {
      const res = await api('/profile', { method: 'PUT', body: parsed });
      if (!res.ok) throw new Error(await explainFailure(res));
      await reloadProfile();
      W.setStatus('fm', 'Uploaded ' + file.name, 'right');
    } catch (err) {
      W.sfx.error();
      await W.messageBox({
        title: 'Upload Profile', icon: 'error',
        heading: 'The server rejected that profile',
        message: String(err.message),
        buttons: ['OK'],
      });
      W.setStatus('fm', 'Upload failed', 'right');
    }
  });
  // A file input is only clickable while it is in the document.
  document.body.appendChild(picker);
  picker.click();
  document.body.removeChild(picker);
}

/* Pull the profile back from the server and hand it to whoever is showing it. One
   function because there are two callers -- boot and this upload -- and they must
   not drift. */
async function reloadProfile() {
  const res = await api('/profile');
  state.profile = await res.json();
  window.EditorForm.refresh(state.profile);
  W.setStatus('editor', 'Ready', 'right');
  const fm = W.windows.get('fm');
  if (fm) paintFm(fm);
  refreshPreviewSoon();
}

function openFileManager() {
  return once('fm', () => {
    const rec = W.createWindow({
      id: 'fm', title: 'File Manager', icon: 'folderOpen',
      w: 600, h: 400, minWidth: 460, minHeight: 300,
      menus: [
        { label: 'File', items: [
          { label: 'Open', accel: 'Enter', action: () => openEditor() },
          { label: 'Export As...', accel: 'Ctrl+E', action: () => openExport() },
          { sep: true },
          // BUILD_PLAN Stage 3 asks for "a profile JSON download/upload" beside
          // the PDF/DOCX/TXT export buttons. It was missing. No new route: the
          // file is GET /profile as it stands, and the upload is PUT /profile,
          // so this is the browser half of two endpoints that already exist.
          { label: 'Download Profile JSON', action: () => downloadProfileJson() },
          { label: 'Upload Profile JSON...', action: () => uploadProfileJson() },
          { sep: true },
          { label: 'Close', accel: 'Alt+F4', action: () => W.close('fm') },
        ] },
        { label: 'View', items: [
          { label: 'Resume', action: () => setFmMode('resume') },
          { label: 'Versions', action: () => setFmMode('versions') },
          { sep: true },
          { label: 'Read Me', action: openReadMe },
          { label: 'Preview', action: openPreview },
        ] },
        { label: 'Help', items: [{ label: 'About', action: openAbout }] },
      ],
      toolbar: [
        { icon: 'folderOpen', label: 'Open', action: () => openEditor() },
        { icon: 'save',       label: 'Snapshot', action: () => fmSnapshot() },
        { icon: 'printer',    label: 'Export', action: () => openExport() },
        { sep: true },
        { icon: 'notepad',    label: 'Read Me', action: openReadMe },
      ],
      statusText: 'Ready',
    });

    const wrap = el('div', 'well-fill');

    const tabs = el('div', 'fm-tabs');
    tabs.setAttribute('role', 'tablist');
    FM_TABS.forEach(([key, label]) => {
      const b = el('button', 'tab', label);
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.setAttribute('data-mode', key);
      b.addEventListener('click', () => setFmMode(key));
      tabs.appendChild(b);
    });
    wrap.appendChild(tabs);

    const row = el('div', 'split fm-split');

    const left = el('div', 'listbox fm-left');
    left.setAttribute('data-role', 'fm-left');
    const right = el('div', 'listbox grow');
    right.setAttribute('data-role', 'fm-right');
    row.appendChild(left);
    row.appendChild(right);
    wrap.appendChild(row);

    rec.body.appendChild(wrap);
    rec.el.addEventListener('keydown', (ev) => {
      if (ev.ctrlKey && ev.key === 'e') { ev.preventDefault(); openExport(); }
    });

    paintFm(rec);
    loadVersions(rec);
    return rec;
  });
}

function setFmMode(mode) {
  fmMode = mode;
  const rec = W.windows.get('fm');
  if (rec) {
    paintFm(rec);
    if (mode === 'versions' && fmVersions === null) loadVersions(rec);
  }
}

/* Paint the tab strip and the currently-selected pane. */
function paintFm(rec) {
  rec.el.querySelectorAll('.fm-tabs .tab').forEach((t) => {
    const on = t.getAttribute('data-mode') === fmMode;
    t.setAttribute('aria-selected', String(on));
    if (on) t.classList.add('active');
    else t.classList.remove('active');
  });
  const left = rec.el.querySelector('[data-role="fm-left"]');
  const right = rec.el.querySelector('[data-role="fm-right"]');
  left.textContent = '';
  right.textContent = '';
  if (fmMode === 'resume') paintFmResume(left, right);
  else paintFmVersions(left, right);
  rec.title.textContent = fmMode === 'resume'
    ? 'File Manager - My Resume'
    : 'File Manager - Versions';
}

/* Resume mode: sections, then their entries. Counts come from the model so the
   list cannot disagree with what the editor would show. */
function paintFmResume(left, right) {
  right.appendChild(el('div', 'listbox-row dim', 'Select a section on the left.'));
  if (!state.profile) {
    left.appendChild(el('div', 'listbox-row dim', '(no profile yet)'));
    W.setStatus('fm', 'No profile loaded', 'right');
    return;
  }
  const M = window.EditorModel;
  M.ORDER.forEach((section) => {
    const spec = M.spec(section);
    const n = M.count(state.profile, section);
    const item = el('div', 'listbox-row',
      spec.label + (n ? '  (' + n + ')' : ''));
    item.setAttribute('data-section', section);
    if (!n) item.classList.add('dim');
    left.appendChild(item);
  });
  left.addEventListener('click', onFmSectionClick);
  W.setStatus('fm',
    (state.profile.contact && state.profile.contact.name) || '(no name)', 'right');
}

function onFmSectionClick(ev) {
  const picked = ev.target.closest('.listbox-row[data-section]');
  if (!picked) return;
  const left = ev.currentTarget;
  left.querySelectorAll('.listbox-row').forEach((r) => {
    r.setAttribute('aria-selected', String(r === picked));
  });
  const right = left.parentElement.querySelector('[data-role="fm-right"]');
  const section = picked.getAttribute('data-section');
  right.textContent = '';
  const value = state.profile ? state.profile[section] : null;
  const items = value === undefined || value === null ? []
    : (Array.isArray(value) ? value : [value]);
  if (!items.length) {
    right.appendChild(el('div', 'listbox-row dim',
      'Empty. Use My Resume to add something.'));
  } else {
    items.forEach((item, i) => right.appendChild(
      el('div', 'listbox-row', describeEntry(section, item, i))));
  }
  W.setStatus('fm', section + ': ' + items.length + ' item(s)', 'right');
}

/* Versions mode. */
function paintFmVersions(left, right) {
  if (fmVersions === null) {
    left.appendChild(el('div', 'listbox-row dim', 'Loading...'));
    return;
  }
  if (!fmVersions.length) {
    left.appendChild(el('div', 'listbox-row dim', '(no snapshots yet)'));
    right.appendChild(el('div', 'listbox-row dim',
      'Use Snapshot in the toolbar to save the current resume as a version.'));
    W.setStatus('fm', 'No saved versions', 'right');
    return;
  }
  fmVersions.forEach((v, i) => {
    const item = el('div', 'listbox-row', v.name + '   ' + v.created_at);
    item.setAttribute('data-version', v.id);
    item.setAttribute('data-index', String(i));
    left.appendChild(item);
  });
  left.addEventListener('click', onFmVersionClick);
  right.appendChild(el('div', 'listbox-row dim',
    'Select a version to export or delete it.'));
  W.setStatus('fm', fmVersions.length + ' version(s)', 'right');
}

function onFmVersionClick(ev) {
  const picked = ev.target.closest('.listbox-row[data-version]');
  if (!picked) return;
  const left = ev.currentTarget;
  left.querySelectorAll('.listbox-row').forEach((r) => {
    r.setAttribute('aria-selected', String(r === picked));
  });
  const right = left.parentElement.querySelector('[data-role="fm-right"]');
  const v = fmVersions[Number(picked.getAttribute('data-index'))];
  right.textContent = '';
  [['Name', v.name], ['Saved', v.created_at], ['Template', v.template],
   ['Job description', v.jd_id || '(none linked)'], ['Version id', v.id]]
    .forEach(([k, val]) => {
      const row = el('div', 'listbox-row');
      row.appendChild(el('span', 'fm-key', k + ':'));
      row.appendChild(el('span', 'fm-val', String(val)));
      right.appendChild(row);
    });
  const bar = el('div', 'fm-actions');
  const exp = el('button', 'btn default', 'Export As...');
  exp.type = 'button';
  exp.addEventListener('click', () => openExport(v.id, v.name));
  const del = el('button', 'btn', 'Delete');
  del.type = 'button';
  del.addEventListener('click', async () => {
    const answer = await W.messageBox({
      title: 'Delete Version', icon: 'warning',
      heading: 'Delete "' + v.name + '"?',
      message: 'A saved version cannot be brought back once it is gone.',
      buttons: ['Delete', 'Cancel'],
    });
    if (answer !== 'Delete') return;
    await W.working('fm', 'Deleting...', async () => {
      const res = await api('/versions/' + encodeURIComponent(v.id), { method: 'DELETE' });
      if (!res.ok) throw new Error('delete failed: HTTP ' + res.status);
    });
    fmVersions = null;
    const rec = W.windows.get('fm');
    if (rec) { await loadVersions(rec); paintFm(rec); }
    W.setStatus('fm', 'Deleted ' + v.name, 'right');
  });
  bar.appendChild(exp);
  bar.appendChild(del);
  right.appendChild(bar);
  W.setStatus('fm', v.name, 'right');
}

/* Fetch the list. A failure is reported in the pane rather than swallowed --
   an empty list that is really a failed request is indistinguishable from an
   empty database, and only one of those is true. */
async function loadVersions(rec) {
  fmVersions = null;
  try {
    const res = await api('/versions');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    fmVersions = await res.json();
  } catch (err) {
    fmVersions = [];
    W.setStatus('fm', 'Could not load versions: ' + err.message, 'right');
  }
  if (W.windows.get('fm') === rec) paintFm(rec);
}

/* Snapshot the live profile. Naming it after the person is what the sheets
   convention expects, so that is the default rather than "current". */
async function fmSnapshot() {
  if (!state.profile || !state.profile.contact || !state.profile.contact.name) {
    await W.messageBox({
      title: 'Snapshot', icon: 'warning', heading: 'Nothing to snapshot',
      message: 'Fill in your name in My Resume first -- it names the file.',
      buttons: ['OK'],
    });
    return;
  }
  const name = state.profile.contact.name + ' Resume';
  await W.working('fm', 'Saving a version...', () =>
    api('/versions/from-profile?name=' + encodeURIComponent(name)
        + '&template=' + encodeURIComponent(state.template),
        { method: 'POST' }));
  fmVersions = null;
  const rec = W.windows.get('fm');
  if (rec) {
    await loadVersions(rec);
    setFmMode('versions');
  }
  W.setStatus('fm', 'Saved "' + name + '"', 'right');
}

function describeEntry(section, item, i) {
  if (typeof item === 'string') return item;
  if (!item || typeof item !== 'object') return String(item);
  const bits = [];
  if (item.name) bits.push(item.name);
  if (item.org) bits.push(item.role ? item.role + ', ' + item.org : item.org);
  if (item.institution) bits.push(item.institution + (item.degree ? ', ' + item.degree : ''));
  if (item.title) bits.push(item.title);
  if (item.text) bits.push(String(item.text).slice(0, 60));
  if (item.items) bits.push('[' + item.items.join(', ') + ']');
  return (i + 1) + '.  ' + (bits.join('  |  ') || '(no details)');
}

/* ---- Export As ---------------------------------------------------------- */
/* The reference image's Open dialog, with the dummy text swapped for something
   that matters: whether your date of birth and address go on the page. That is
   a real decision per export, not a per-application setting, so it lives here. */

const EXPORT_FORMATS = [
  ['pdf', 'PDF Document (*.pdf)'],
  ['docx', 'Word Document (*.docx)'],
  ['txt', 'Plain Text (*.txt)'],
];

function openExport(versionId, versionName) {
  let fmt = 'pdf';
  let personal = false;

  const dlg = W.createWindow({
    id: 'export', dialog: true, modal: true,
    title: 'Export As', icon: 'printer',
    w: 420, h: 'auto', status: false, minimisable: false, resizable: false,
    onClose: () => true,
  });

  const label = el('p', 'ed-blurb',
    versionId
      ? 'Export the saved version "' + versionName + '".'
      : 'Save the current resume as a new version, then export it.');
  dlg.body.appendChild(label);

  const box = el('div', 'groupbox');
  box.appendChild(el('span', 'groupbox-legend', 'Save as type'));
  const list = el('div', 'listbox ed-formats');
  list.setAttribute('role', 'listbox');
  list.setAttribute('data-role', 'formats');
  EXPORT_FORMATS.forEach(([key, text]) => {
    const row = el('div', 'listbox-row', text);
    row.setAttribute('role', 'option');
    row.setAttribute('data-fmt', key);
    row.setAttribute('aria-selected', String(key === fmt));
    row.addEventListener('click', () => {
      fmt = key;
      list.querySelectorAll('.listbox-row').forEach((r) => {
        r.setAttribute('aria-selected', String(r.getAttribute('data-fmt') === fmt));
      });
      showName();
    });
    list.appendChild(row);
  });
  box.appendChild(list);

  const check = el('label', 'ed-check');
  const cb = el('input');
  cb.type = 'checkbox';
  cb.id = 'exportPersonal';
  check.appendChild(cb);
  check.appendChild(el('span', null,
    'Include personal details (address, date of birth)'));
  check.appendChild(el('span', 'ed-hint',
    'Off by default. Turning it on is right for a job application and wrong for anything you post publicly.'));
  box.appendChild(check);
  dlg.body.appendChild(box);

  const nameRow = el('div', 'ed-name');
  dlg.body.appendChild(nameRow);

  function showName() {
    nameRow.textContent = '';
    nameRow.appendChild(el('span', 'fm-key', 'File name:'));
    nameRow.appendChild(el('span', 'fm-val',
      (versionName || suggestedName()) + EXPORT_FORMATS
        .find(([k]) => k === fmt)[1].match(/\(([^)]+)\)$/)[1].replace('*', '')));
  }
  showName();

  const bar = el('div', 'msg-buttons');
  const okBtn = el('button', 'btn default', 'OK');
  okBtn.type = 'button';
  const cancelBtn = el('button', 'btn', 'Cancel');
  cancelBtn.type = 'button';
  bar.appendChild(okBtn);
  bar.appendChild(cancelBtn);
  dlg.body.appendChild(bar);

  cancelBtn.addEventListener('click', () => { W.sfx.click(); W.close('export'); });
  okBtn.addEventListener('click', async () => {
    W.sfx.click();
    okBtn.disabled = true;
    try {
      await doExport({ versionId, versionName, fmt, personal });
      W.close('export');
    } catch (err) {
      okBtn.disabled = false;
      W.setStatus('fm', 'Export failed: ' + err.message, 'right');
    }
  });

  return dlg;
}

function suggestedName() {
  const n = state.profile && state.profile.contact && state.profile.contact.name;
  return (n ? n : 'resume').trim() + ' Resume';
}

/* Read the filename the server chose. The sheets convention lives server-side --
   "Name Resume" for documents, bare "Name" for PDFs -- so guessing it here
   would produce two different answers for the same file. */
function filenameFromResponse(res, fallback) {
  const cd = res.headers.get('Content-Disposition') || '';
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) { try { return decodeURIComponent(star[1]); } catch (_) { /* fall through */ } }
  const plain = cd.match(/filename="?([^";]+)"?/i);
  return plain ? plain[1] : fallback;
}

/* Turn a failed response into something worth reading. FastAPI's `detail` is a
   list of per-field objects for validation failures, which rendered as
   "[object Object]" before this existed -- so the one message that would have
   told the user which field is wrong was the one message nobody could read. */
/* Turning a failed response into words lives in failures.js, shared with
   editor.js. One copy: the other one dropped the entry number and left
   "Value error," at the front of the sentence, so the same 422 read two
   different ways depending on which window ran it. */
const explainFailure = window.Failures.explainFailure;
const whereInPlainEnglish = window.Failures.whereInPlainEnglish;
const say = window.Failures.say;

async function doExport({ versionId, versionName, fmt, personal }) {
  let id = versionId;
  if (!id) {
    if (!state.profile) throw new Error('there is nothing to export yet');
    const res = await api('/versions/from-profile?name='
      + encodeURIComponent(versionName || suggestedName())
      + '&include_personal_details=' + (personal ? 'true' : 'false')
      + '&template=' + encodeURIComponent(state.template),
      { method: 'POST' });
    if (!res.ok) throw new Error('could not save a version (HTTP ' + res.status + ')');
    const version = await res.json();
    id = version.id;
  }
  const res = await api('/export/' + encodeURIComponent(id) + '?format='
    + encodeURIComponent(fmt), { method: 'POST' });
  if (!res.ok) {
    // The server's own error text, which says which rule was broken.
    throw new Error(await explainFailure(res));
  }
  const blob = await res.blob();
  const filename = filenameFromResponse(res, suggestedName() + '.' + fmt);
  triggerDownload(blob, filename);
  W.setStatus('fm', 'Exported ' + filename + ' (' + blob.size + ' bytes)', 'right');
  fmVersions = null;                    // a fresh version now exists
  const rec = W.windows.get('fm');
  if (rec) { await loadVersions(rec); paintFm(rec); }
}

/* ---- Preview: the real PDF -------------------------------------------- */

function openPreview() {
  return once('preview', () => {
    const rec = W.createWindow({
      id: 'preview', title: 'Preview - My Resume', icon: 'find',
      w: 560, h: 500,
      menus: [
        { label: 'File', items: [
          { label: 'Refresh', accel: 'F5', action: () => refreshPreview('preview') },
          { sep: true },
          { label: 'Close', accel: 'Alt+F4', action: () => W.close('preview') },
        ] },
        { label: 'Help', items: [{ label: 'About', action: openAbout }] },
      ],
      statusText: 'Ready',
    });
    const frame = document.createElement('iframe');
    frame.id = 'previewFrame';
    frame.title = 'Rendered resume PDF';
    frame.style.width = '100%';
    frame.style.height = '100%';
    frame.style.border = 'none';
    frame.style.background = '#fff';
    rec.body.appendChild(frame);

    // The escape hatch, and it is not optional. This exact omission is what
    // made the live preview a silent white rectangle once already: the iframe
    // is fed a blob: URL, and a browser that refuses it reports nothing at all.
    // A visible link plus an explicit message means a blocked preview can never
    // again be mistaken for a blank page.
    const fallback = document.createElement('div');
    fallback.id = 'previewFallback';
    fallback.style.cssText = 'position:absolute;inset:0;display:flex;' +
      'flex-direction:column;gap:8px;align-items:center;justify-content:center;' +
      'background:#c0c0c0;text-align:center;padding:16px;';
    // `hidden` on its own is NOT enough here. It only contributes a UA-level
    // `[hidden] { display: none }`, and the inline `display:flex` above outranks
    // it -- so the fallback sat on top of the PDF permanently and every preview
    // showed "could not be shown" instead of the resume. showFallback() moves
    // `display` explicitly, so what the property says is what is painted.
    showFallback(fallback, false);
    const note = el('div', null,
      'The preview could not be shown in place. Your resume is fine -- this ' +
      'browser is refusing to display the PDF frame.');
    const openLink = el('a', null, 'Open it in a new tab instead');
    openLink.id = 'previewOpen';
    openLink.href = '#';
    openLink.target = '_blank';
    openLink.rel = 'noopener';
    openLink.style.color = '#000080';
    fallback.appendChild(note);
    fallback.appendChild(openLink);
    rec.body.appendChild(fallback);

    refreshPreview('preview');
    return rec;
  });
}

/* Show or hide the preview's escape-hatch panel.
 *
 * Deliberately does not rely on `hidden`. The UA stylesheet's
 * `[hidden] { display: none }` loses to any inline `display`, and this panel
 * needs an inline `display:flex` to centre its message. Relying on `hidden`
 * therefore left it permanently painted over the PDF -- which is exactly what
 * happened, and why the preview looked broken. Both the property and the
 * computed style are set, and a test asserts the computed value.
 */
function showFallback(node, show) {
  if (!node) return;
  node.hidden = show;
  node.style.display = show ? 'flex' : 'none';
}

async function refreshPreview(winId) {
  if (!state.profile) return;
  const rec = W.windows.get(winId);
  const frame = rec && rec.el.querySelector('#previewFrame');
  if (!frame) return;
  const fallback = rec.el.querySelector('#previewFallback');
  const openLink = rec.el.querySelector('#previewOpen');
  W.setBusy(winId, true, 'Rendering...');
  // An indeterminate bar, because a PDF render has no meaningful percentage.
  W.progress(winId, 'main', null);
  try {
    const res = await api('/preview?template=' + encodeURIComponent(state.template), {
      method: 'POST', body: state.profile,
    });
    const pages = res.headers.get('X-Pages') || '?';
    const limit = res.headers.get('X-Page-Limit') || '?';
    const budget = res.headers.get('X-Page-Budget') || 'ok';
    const density = res.headers.get('X-Density') || '';
    W.setStatus(winId, pages + '/' + limit + ' pages'
      + (budget === 'over' ? '  OVER BUDGET' : '  ok')
      + (density && density !== 'normal' ? '  [' + density + ']' : ''), 'right');
    const blob = await res.blob();
    if (frame.src && frame.src.startsWith('blob:')) URL.revokeObjectURL(frame.src);
    const url = URL.createObjectURL(blob);
    frame.src = url;
    // setAttribute, not a property write. Assigning a#href reads it back
    // resolved against the document, so the handler stored the page URL instead
    // of the blob and the fallback link pointed at the app.
    if (openLink) openLink.setAttribute('href', url);
    showFallback(fallback, false);
  } catch (err) {
    W.sfx.error();
    W.setStatus(winId, 'Preview failed', 'right');
    showFallback(fallback, true);
  } finally {
    W.setBusy(winId, false);
    W.progress(winId, 'main', 1);
  }
}

/* ---- Resume Editor ------------------------------------------------------ */
/* The form itself lives in editor.js and builds from editor-model.js. This is
   only the door: open it if it is not already open, and refresh it if it is. */

function openEditor() {
  const existing = W.windows.get('editor');
  if (existing) {
    W.restore('editor');
    window.EditorForm.refresh(state.profile);
    return existing;
  }
  if (!state.profile) {
    // Nothing to edit yet. An empty profile is still editable -- contact first.
    state.profile = emptyProfile();
  }
  return window.EditorForm.open(state.profile, {
    template: state.template,
    onChanged: () => { refreshPreviewSoon(); },
  });
}

/* The name starts as 'Anon' rather than blank so that the export guard has
   something to match on a genuinely fresh install. With a blank name the
   'still Anon' refusal never fired, and the first export of a new install went
   straight out under an empty filename. The field stays editable and the window
   title shows whatever is in it, so this is a visible starting point rather
   than a hidden default. */
function emptyProfile() {
  return {
    contact: { name: 'Anon', email: '', phone: '', city: '', country: '', links: [] },
    summary: '', interests: '',
    education: [], experience: [], projects: [], skills: [],
    certifications: [], achievements: [], extracurriculars: [], publications: [],
  };
}

async function saveProfile(label) {
  if (!state.profile) {
    await W.messageBox({
      title: 'Sheetsworks', icon: 'warning', heading: 'Nothing to save',
      message: 'There is no profile yet. Open My Resume and fill in your contact details.',
      buttons: ['OK'],
    });
    return;
  }
  await working('editor', 'Saving...', () => api('/profile', {
    method: 'PUT', body: state.profile,
  }));
  W.setStatus('editor', (label || 'Profile') + ' - saved', 'right');
  if (state.profile.contact && state.profile.contact.name) {
    const rec = W.windows.get('editor');
    if (rec) rec.title.textContent = 'My Resume - ' + state.profile.contact.name;
  }
}

/* Refresh the preview after an edit, but not on every keystroke. */
let previewSoonTimer = null;
function refreshPreviewSoon() {
  if (previewSoonTimer) clearTimeout(previewSoonTimer);
  previewSoonTimer = setTimeout(() => {
    previewSoonTimer = null;
    if (W.windows.get('preview')) refreshPreview('preview');
  }, 900);
}

/* ---- AI notice ---------------------------------------------------------- */

async function openAiNotice() {
  // Read the injected LLM info from the page template
  const tmpl = document.getElementById('tipsData');
  let llm = { provider: null, model: null };
  if (tmpl) {
    try { llm = JSON.parse(tmpl.textContent).llm || llm; } catch (_) {}
  }
  const provider = llm.provider;
  const model = llm.model;
  if (provider === 'openrouter' && model) {
    await W.messageBox({
      title: 'AI Resume Builder', icon: 'info',
      heading: 'The AI Resume Builder is ready',
      message: 'OpenRouter is configured with model: ' + model + '.\n\n' +
               'Open a section in My Resume and click "Tell the AI" to start.',
      buttons: ['OK'],
    });
  } else {
    await W.messageBox({
      title: 'Sheetsworks', icon: 'error', heading: 'The AI Resume Builder is not available',
      message: 'No LLM provider configured, or OpenRouter is missing LLM_MODEL.\n\n' +
               'Set LLM_PROVIDER=openrouter and LLM_MODEL to a valid model ID, ' +
               'then restart the application.',
      buttons: ['OK'],
    });
  }
}

/* ======================================================== taskbar / start = */

function buildTaskbar() {
  const startIcon = document.getElementById('startIcon');
  const si = W.icon('computer');
  si.setAttribute('width', '16'); si.setAttribute('height', '16');
  startIcon.textContent = '';
  startIcon.appendChild(si);

  const trayIcon = document.getElementById('trayIcon');
  const ti = W.icon('key');
  ti.setAttribute('width', '14'); ti.setAttribute('height', '14');
  trayIcon.textContent = '';
  trayIcon.appendChild(ti);
  document.getElementById('trayText').textContent = state.sound ? 'Sound on' : 'Sound off';

  document.getElementById('tray').addEventListener('click', async () => {
    const on = await W.messageBox({
      title: 'Sound', icon: 'key',
      heading: 'Sound effects',
      message: 'Windows 95 played a sting on startup and a beep on error. ' +
               'Those are generated here with WebAudio, so there is nothing to ' +
               'download. Off by default, because a chime that ambushes you on ' +
               'page load is not nostalgia.',
      buttons: ['Sound On', 'Sound Off', 'Cancel'],
    });
    if (on === 'Sound On') { state.sound = true; store.set('rb.sound', true); }
    else if (on === 'Sound Off') { state.sound = false; store.set('rb.sound', false); }
    else return;
    W.sfx.setEnabled(state.sound);
    document.getElementById('trayText').textContent = state.sound ? 'Sound on' : 'Sound off';
  });

  document.getElementById('startBtn').addEventListener('click', () => {
    W.sfx.click();
    W.setStartOpen(!document.getElementById('startMenu').classList.contains('open'));
  });

  const menu = document.getElementById('startMenu');
  menu.textContent = '';
  menu.appendChild(W.startItem('My Resume', 'resume', openEditor));
  menu.appendChild(W.startItem('Sample Resume', 'notepad', loadSample));
  menu.appendChild(W.startItem('File Manager', 'folder', openFileManager));
  menu.appendChild(W.startItem('Preview', 'find', openPreview));
  menu.appendChild(W.startItem('Export As...', 'printer', openExport));
  menu.appendChild(W.startSeparator());
  menu.appendChild(W.startItem('Read Me', 'notepad', openReadMe));
  menu.appendChild(W.startItem('Display Properties', 'display', openDisplay));
  menu.appendChild(W.startSeparator());
  menu.appendChild(W.startItem('AI Resume Builder', 'program', openAiNotice));
  menu.appendChild(W.startItem('About Sheetsworks', 'computer', openAbout));
  menu.appendChild(W.startSeparator());
  menu.appendChild(W.startItem('Exit', 'error', confirmExit));
}

/* --------------------------------------------------------- sample resume */
/* Load a finished, entirely fictional resume so there is something to look at
   before you have written anything. It refuses to overwrite a profile that
   already has content in it, and says plainly that the data is made up --
   a demo that looks like a real CV is a demo someone will send by accident. */

async function loadSample(force) {
  const sample = window.SampleResume.build();
  if (!force && !window.SampleResume.isEmpty(state.profile)) {
    const answer = await W.messageBox({
      title: 'Sample Resume', icon: 'warning',
      heading: 'Replace what is already here?',
      message: 'You already have a profile saved. Loading the sample will '
             + 'overwrite it.\n\nThere is no undo for this yet, so cancel if '
             + 'you want to keep your own words.',
      buttons: ['Replace', 'Cancel'],
    });
    if (answer !== 'Replace') return;
  }

  state.profile = sample;
  const rec = openEditor();
  rec.title.textContent = 'My Resume - ' + sample.contact.name;
  W.setStatus('editor', 'Sample loaded - not saved yet', 'right');
  await saveProfile('Sample Resume loaded');

  await W.messageBox({
    title: 'Sample Resume', icon: 'info',
    heading: 'This is not a real person',
    message: 'Every employer, institution, date and number in it is invented. '
           + '"Sample Analytics" does not exist.\n\n'
           + 'It has been saved over your profile, so use Display Properties '
           + 'or clear it before you start writing your own.',
    buttons: ['OK'],
  });
  refreshPreview('preview');
}

async function confirmExit() {
  const answer = await W.messageBox({
    title: 'Exit', icon: 'warning', heading: 'Close Sheetsworks?',
    message: 'Your profile is saved on the server as you go, so nothing is lost.',
    buttons: ['OK', 'Cancel'],
  });
  if (answer === 'OK') {
    // There is no server-side session to end; the honest exit is to say so.
    await W.messageBox({
      title: 'Exit', icon: 'info', heading: 'Nothing to close',
      message: 'There is no running program to quit -- the server keeps your ' +
               'profile whether or not this page is open. Close the tab when ' +
               'you are done.',
      buttons: ['OK'],
    });
  }
}

/* ================================================================= boot === */

/* Readiness, as a promise created before anything can ask for it.
 *
 * The desktop is visibly "up" the moment openEditor() puts a window on screen,
 * but `state.profile` is not settled until the fetch in bootPromise() returns.
 * Anything acting on the profile in that gap is working against a half-booted
 * app and cannot tell -- the screenshot harness seeded a profile and then had
 * boot overwrite it with null, which produced five failures that looked like
 * four unrelated bugs.
 *
 * So the app publishes an honest signal: `Sheetsworks.ready`. Created here,
 * exposed in the surface literal, resolved when the profile is loaded or known
 * to be absent. The presence of a window is not that signal. */
let markReady;
const ready = new Promise(function (res) { markReady = res; });

async function boot() {
  try {
    await bootPromise();
  } catch (_) { /* failures are already reported through the status bar */ }
}

async function bootPromise() {
  try {
    await bootInner();
  } finally {
    // Must run on BOTH paths. The ?open= branch below returns early, and it is
    // precisely the URL the screenshot harness uses -- so resolving only at the
    // end of the function would hang every deep-linked page forever.
    markReady();
  }
}

async function bootInner() {
  state.tips = loadTips();
  state.template = store.get('rb.template', 'sheets');
  state.sound = store.get('rb.sound', false) === true;

  buildDesktop();
  buildTaskbar();

  const rec = openEditor();
  W.setStatus('editor', 'Loading profile...', 'right');

  // reloadProfile, not a second copy of it: the JSON upload path loads the
  // profile the same way, and two copies of "assign it, tell the form, tell the
  // File Manager" is how the File Manager ends up showing yesterday's sections
  // after an upload.
  try {
    await reloadProfile();
  } catch (err) {
    state.profile = null;
    W.setStatus('editor', 'No profile saved yet - this is a fresh start', 'right');
  }

  if (state.profile && state.profile.contact && state.profile.contact.name) {
    rec.title.textContent = 'My Resume - ' + state.profile.contact.name;
  }

  if (state.sound) W.sfx.setEnabled(true);

  // ?open=fm,readme,preview opens those windows on arrival. Same reasoning as a
  // deep link: it makes a particular set of windows shareable, and it is the
  // only way to review a multi-window desktop without a mouse.
  const asked = requestedWindows();
  if (asked.length) {
    const map = {
      editor: openEditor, fm: openFileManager, readme: openReadMe,
      preview: openPreview, display: openDisplay, about: openAbout,
      ai: openAiNotice, exit: confirmExit, sample: loadSample,
      export: openExport,
    };
    let i = 0;
    const step = () => {
      if (i >= asked.length) return;
      const name = asked[i++];
      if (map[name]) map[name]();
      // A beat apart, so the cascade actually cascades instead of stacking.
      setTimeout(step, 240);
    };
    setTimeout(step, 500);
    return;                 // an explicit request replaces the first-run flow
  }

  // Open the Read Me only for a genuinely new visitor. Otherwise the desktop
  // greets them with three overlapping dialogs, which is not a welcome.
  if (!state.profile) setTimeout(openReadMe, 350);
}

/* Which windows the URL asked for. Feature-detected, because this file is also
   executed under node by the flow tests, where there is no `location`. */
function requestedWindows() {
  if (typeof location === 'undefined' || !location || !location.search) return [];
  const KNOWN = ['editor', 'fm', 'readme', 'preview', 'display', 'about',
                  'ai', 'exit', 'sample', 'export'];
  try {
    const raw = new URLSearchParams(location.search).get('open') || '';
    return raw.split(',').map((s) => s.trim()).filter((s) => KNOWN.indexOf(s) !== -1);
  } catch (_) { return []; }
}

/* The app's own surface, the way Win95 exposed its windows to the shell.
   Exposed so a window can be opened by name -- which is what makes the desktop
   linkable and reviewable, and what lets the screenshot harness drive it
   without a mouse. Nothing here is a test hook: these are the real openers. */
window.Sheetsworks = {
  state,
  openEditor, openFileManager, openReadMe, openPreview, openDisplay,
  openAbout, openAiNotice, confirmExit, loadSample,
  openExport, setFmMode, loadVersions,
  downloadProfileJson, uploadProfileJson, reloadProfile,
  saveProfile,
  ready,
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

})();
