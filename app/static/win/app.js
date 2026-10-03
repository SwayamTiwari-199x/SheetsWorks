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
  template: 'blank',
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
    let detail = 'HTTP ' + res.status;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* not json */ }
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
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
      'A resume builder that shows you the real exported PDF while you write, ' +
      'and tells you where you are breaking the rules.'));
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
        list.appendChild(row);
      });
    list.addEventListener('click', () => {
      const picked = list.querySelector('[aria-selected="true"]');
      if (!picked) return;
      state.template = picked.getAttribute('data-template');
      store.set('rb.template', state.template);
      W.setStatus('display', 'Format set to ' + state.template, 'right');
      list.querySelectorAll('.listbox-row').forEach((r) => {
        r.setAttribute('aria-selected', String(r === picked));
      });
      renderTemplateHint();
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

/* ---- File Manager: sections and entries -------------------------------- */

function openFileManager() {
  return once('fm', () => {
    const rec = W.createWindow({
      id: 'fm', title: 'File Manager - My Resume', icon: 'folderOpen',
      w: 560, h: 380,
      menus: [
        { label: 'File', items: [
          { label: 'Open', accel: 'Enter', action: () => openEditor() },
          { sep: true },
          { label: 'Close', accel: 'Alt+F4', action: () => W.close('fm') },
        ] },
        { label: 'View', items: [
          { label: 'Read Me', action: openReadMe },
          { label: 'Preview', action: openPreview },
        ] },
        { label: 'Help', items: [{ label: 'About', action: openAbout }] },
      ],
      toolbar: [
        { icon: 'folderOpen', label: 'Open', action: () => openEditor() },
        { icon: 'notepad',   label: 'Read Me', action: openReadMe },
        { sep: true },
        { icon: 'printer',   label: 'Export', action: () => openEditor() },
      ],
      statusText: 'Ready',
    });

    const row = el('div', 'split');
    row.style.height = '100%';

    // The "C:\" drive dropdown, repurposed as the section list.
    const left = el('div', 'listbox');
    left.style.width = '150px';
    left.style.flex = '0 0 150px';
    (state.profile ? ['contact', 'summary', 'interests', 'experience', 'projects',
                      'skills', 'education', 'achievements'] : ['(no profile yet)'])
      .forEach((s) => {
        const item = el('div', 'listbox-row', s);
        item.setAttribute('data-section', s);
        left.appendChild(item);
      });

    // The file list.
    const right = el('div', 'listbox grow');
    right.setAttribute('data-role', 'entries');
    right.appendChild(el('div', 'listbox-row dim', 'Select a section on the left.'));

    row.appendChild(left);
    row.appendChild(right);
    rec.body.appendChild(row);

    left.addEventListener('click', () => {
      const picked = left.querySelector('[aria-selected="true"]');
      if (!picked) return;
      left.querySelectorAll('.listbox-row').forEach((r) => {
        r.setAttribute('aria-selected', String(r === picked));
      });
      const section = picked.getAttribute('data-section');
      right.textContent = '';
      const value = state.profile ? state.profile[section] : null;
      const items = value === undefined || value === null ? []
        : (Array.isArray(value) ? value : [value]);
      if (!items.length) {
        right.appendChild(el('div', 'listbox-row dim', 'Empty. Use My Resume to add something.'));
      } else {
        items.forEach((item, i) => {
          const r = el('div', 'listbox-row',
            describeEntry(section, item, i));
          right.appendChild(r);
        });
      }
      W.setStatus('fm', section + ': ' + items.length + ' item(s)', 'right');
    });

    // A friendly empty state instead of a blank list.
    if (!state.profile) {
      W.setStatus('fm', 'No profile loaded', 'right');
    } else {
      W.setStatus('fm', state.profile.contact
        && state.profile.contact.name || '(no name)', 'right');
    }
    return rec;
  });
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
    fallback.hidden = true;
    fallback.style.cssText = 'position:absolute;inset:0;display:flex;' +
      'flex-direction:column;gap:8px;align-items:center;justify-content:center;' +
      'background:#c0c0c0;text-align:center;padding:16px;';
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
    if (fallback) fallback.hidden = true;
  } catch (err) {
    W.sfx.error();
    W.setStatus(winId, 'Preview failed', 'right');
    if (fallback) fallback.hidden = false;
  } finally {
    W.setBusy(winId, false);
    W.progress(winId, 'main', 1);
  }
}

/* ---- Resume Editor: the stub the real form lands in -------------------- */

function openEditor() {
  return once('editor', () => {
    const rec = W.createWindow({
      id: 'editor', title: 'My Resume', icon: 'resume',
      w: 640, h: 460,
      menus: [
        { label: 'File', items: [
          { label: 'Save', accel: 'Ctrl+S', action: () => saveProfile() },
          { sep: true },
          { label: 'Close', accel: 'Alt+F4', action: () => W.close('editor') },
        ] },
        { label: 'Edit', items: [
          { label: 'Undo', accel: 'Ctrl+Z', disabled: true },
        ] },
        { label: 'View', items: [
          { label: 'Preview', action: openPreview },
          { label: 'File Manager', action: openFileManager },
        ] },
        { label: 'Help', items: [{ label: 'Read Me', action: openReadMe }] },
      ],
      toolbar: [
        { icon: 'save',   label: 'Save',   action: () => saveProfile() },
        { icon: 'find',   label: 'Preview', action: openPreview },
        { sep: true },
        { icon: 'folderOpen', label: 'Sections', action: openFileManager },
      ],
      statusText: 'Ready',
    });

    const fill = el('div', 'well-fill');
    const note = el('div');
    note.appendChild(el('div', null,
      'This is where the editor form goes.'));
    const sub = el('div', 'dim',
      'Stage 5b replaces this panel with the real section editor. The window ' +
      'manager, menus, toolbar, status bar and loading states around it are ' +
      'already the finished article, which is why they are being demonstrated ' +
      'on a placeholder: nothing around this panel will need to move.');
    sub.style.fontSize = '10px';
    sub.style.marginTop = '6px';
    note.appendChild(sub);

    // Live progress, so the indeterminate bar and the percentage bar can both
    // be seen working against something real.
    const bar = el('div', 'bar');
    bar.setAttribute('data-progress', 'main');
    const fillBar = el('div', 'bar-fill');
    bar.appendChild(fillBar);
    bar.style.marginTop = '10px';
    note.appendChild(bar);

    const barLabel = el('div', 'dim', 'Not started');
    barLabel.style.fontSize = '10px';
    barLabel.setAttribute('data-role', 'progress-label');
    note.appendChild(barLabel);

    fill.appendChild(note);
    rec.body.appendChild(fill);
    return rec;
  });
}

async function saveProfile(label) {
  if (!state.profile) {
    await W.messageBox({
      title: 'Sheetsworks', icon: 'warning', heading: 'Nothing to save',
      message: 'There is no profile yet. The editor form arrives in the next stage.',
      buttons: ['OK'],
    });
    return;
  }
  await working('editor', 'Saving...', () => api('/profile', {
    method: 'PUT', body: state.profile,
  }));
  W.setStatus('editor', (label || 'Profile') + ' - saved', 'right');
}

/* ---- AI notice ---------------------------------------------------------- */

async function openAiNotice() {
  await W.messageBox({
    title: 'Sheetsworks', icon: 'error', heading: 'The AI Resume Builder is not available',
    message: 'The provider this project is configured against currently ' +
             'rejects every available model for this account, so anything built ' +
             'now would fail silently or lie about what it did.\n\n' +
             'An assistant that guesses is worse than no assistant on a ' +
             'document you are about to send.',
    buttons: ['OK'],
  });
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

async function boot() {
  state.tips = loadTips();
  state.template = store.get('rb.template', 'blank');
  if (state.template !== 'sheets') state.template = 'blank';
  state.sound = store.get('rb.sound', false) === true;

  buildDesktop();
  buildTaskbar();

  const rec = openEditor();
  W.progress('editor', 'main', 0.35);
  W.setStatus('editor', 'Loading profile...', 'right');
  const label = rec.el.querySelector('[data-role="progress-label"]');
  if (label) label.textContent = 'Contacting server...';

  try {
    const res = await api('/profile');
    state.profile = await res.json();
    W.setStatus('editor', 'Ready', 'right');
    if (label) {
      label.textContent = 'Loaded — ' +
        (state.profile.contact && state.profile.contact.name || 'no name yet');
    }
    W.progress('editor', 'main', 1);
  } catch (err) {
    state.profile = null;
    W.setStatus('editor', 'No profile saved yet', 'right');
    if (label) label.textContent = 'No profile saved yet — this is a fresh start.';
    W.progress('editor', 'main', 1);
  }

  rec.title.textContent = 'My Resume'
    + (state.profile && state.profile.contact && state.profile.contact.name
      ? ' - ' + state.profile.contact.name : '');

  if (state.sound) W.sfx.setEnabled(true);

  // ?open=fm,readme,preview opens those windows on arrival. Same reasoning as a
  // deep link: it makes a particular set of windows shareable, and it is the
  // only way to review a multi-window desktop without a mouse.
  const asked = requestedWindows();
  if (asked.length) {
    const map = {
      editor: openEditor, fm: openFileManager, readme: openReadMe,
      preview: openPreview, display: openDisplay, about: openAbout,
      ai: openAiNotice, exit: confirmExit,
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
                  'ai', 'exit'];
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
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

})();
