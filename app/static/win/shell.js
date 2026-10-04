/* ============================================================================
   shell.js -- the window manager.

   Free-floating, overlapping windows, exactly as asked. A taskbar is included
   because without one, overlapping windows are a trap: you end up with four
   of them and no way to tell which is on top or how to reach the one you
   want. Win95 had a taskbar for that reason and so does this.

   Responsibilities, in order of how much they matter:
     1. focus and z-order  -- the thing the whole interaction model rests on
     2. drag and resize
     3. minimise / maximise / close, and the taskbar that mirrors them
     4. menu bars, the Start menu, dialogs
     5. motion, and the sound engine

   Rules this file obeys, matching the rest of the project:
     - all text enters the DOM through textContent, never innerHTML
     - no dependencies
     - every visual is inline SVG or a CSS border, so nothing can fail to load
   ========================================================================= */

(function () {
'use strict';

/* ------------------------------------------------------------------ icons */
/* Drawn rather than downloaded: no licences, no requests, no 404s. Each is
   small on purpose -- 1995 icons were 32x32 and chunky.

   Each entry below is the INNER content of an <svg>. They are turned into real
   nodes with DOMParser rather than by assigning innerHTML, because innerHTML
   is banned in this project and, more to the point, an assigned string is
   parsed by the HTML parser inside the live document. DOMParser parses
   image/svg+xml, which has no script execution and no HTML fallback, so there
   is no path from these strings to anything executable even if an entry were
   later built from data rather than from source. */

const svg = (body) => body;

const ICONS = {
  app: '<rect x="4" y="3" width="24" height="26" fill="#fff" stroke="#000"/>' +
       '<path d="M4 9h24" stroke="#000"/><path d="M8 13h16M8 17h16M8 21h11" stroke="#808080"/>' +
       '<rect x="9" y="2" width="12" height="3" fill="#c0c0c0" stroke="#000"/>',
  folder: '<path d="M3 8h9l3 3h14v17H3z" fill="#ffd76e" stroke="#000"/>' +
          '<path d="M3 13h26v15H3z" fill="#ffe9a8" stroke="#000"/>',
  folderOpen: '<path d="M3 8h9l3 3h14v17H3z" fill="#ffd76e" stroke="#000"/>' +
          '<path d="M6 15l4-5h20l-4 5z" fill="#fff3c4" stroke="#000"/>' +
          '<path d="M6 15h20l-4 12H2z" fill="#ffe9a8" stroke="#000"/>',
  notepad: '<rect x="5" y="3" width="22" height="26" fill="#fff" stroke="#000"/>' +
          '<path d="M9 8h14M9 12h14M9 16h14M9 20h9" stroke="#000080"/>',
  printer: '<rect x="8" y="3" width="16" height="8" fill="#fff" stroke="#000"/>' +
          '<rect x="4" y="11" width="24" height="12" fill="#c0c0c0" stroke="#000"/>' +
          '<rect x="8" y="19" width="16" height="10" fill="#fff" stroke="#000"/>' +
          '<circle cx="24" cy="15" r="1.5" fill="#008000"/>',
  display: '<rect x="3" y="5" width="26" height="18" fill="#c0c0c0" stroke="#000"/>' +
          '<rect x="6" y="8" width="20" height="12" fill="#000080"/>' +
          '<path d="M12 23v4M20 23v4M8 27h16" stroke="#000"/>',
  // The ? and the i are drawn as strokes rather than as <text>. An SVG text node
  // becomes part of its ancestors' textContent, so the Read Me desktop icon
  // announced itself as "?Read Me" and any lookup by label matched "?Read Me".
  // An icon must contribute no characters at all.
  help: '<circle cx="16" cy="16" r="13" fill="#000080" stroke="#fff" stroke-width="2"/>' +
        '<path d="M12.5 12.5a3.6 3.6 0 1 1 4.4 4.3c-.9.3-1.4 1.1-1.4 2v1" ' +
        'fill="none" stroke="#fff" stroke-width="2.4"/>' +
        '<rect x="14.6" y="22.4" width="2.9" height="2.9" fill="#fff"/>',
  info: '<circle cx="16" cy="16" r="13" fill="#ff0000" stroke="#fff" stroke-width="2"/>' +
        '<rect x="14.6" y="13.4" width="2.9" height="10.6" fill="#fff"/>' +
        '<rect x="14.6" y="7.4" width="2.9" height="2.9" fill="#fff"/>',
  warning: '<path d="M16 2 31 29H1z" fill="#ffd700" stroke="#000"/>' +
           '<rect x="15" y="11" width="3" height="11" fill="#000"/>' +
           '<rect x="15" y="24" width="3" height="3" fill="#000"/>',
  error: '<circle cx="16" cy="16" r="13" fill="#ff0000" stroke="#fff" stroke-width="2"/>' +
         '<path d="M10 10l12 12M22 10L10 22" stroke="#fff" stroke-width="4"/>',
  computer: '<rect x="3" y="6" width="26" height="16" fill="#c0c0c0" stroke="#000"/>' +
            '<rect x="6" y="9" width="20" height="10" fill="#000080"/>' +
            '<rect x="12" y="22" width="8" height="4" fill="#c0c0c0" stroke="#000"/>',
  save: '<rect x="4" y="4" width="24" height="24" fill="#000080" stroke="#000"/>' +
        '<rect x="9" y="4" width="14" height="10" fill="#c0c0c0" stroke="#000"/>' +
        '<rect x="9" y="18" width="14" height="10" fill="#fff" stroke="#000"/>',
  find: '<circle cx="13" cy="13" r="8" fill="#fff" stroke="#000" stroke-width="2"/>' +
        '<path d="M19 19l9 9" stroke="#000" stroke-width="4"/>',
  delete: '<path d="M6 8h20l-2 21H8z" fill="#c0c0c0" stroke="#000"/>' +
          '<path d="M4 5h24v3H4z" fill="#fff" stroke="#000"/>' +
          '<path d="M13 5v-2h6v2" fill="#fff" stroke="#000"/>',
  key: '<circle cx="10" cy="16" r="6" fill="#ffd700" stroke="#000" stroke-width="2"/>' +
       '<path d="M16 16h13M23 16v5M27 16v4" stroke="#000" stroke-width="3"/>',
  program: '<rect x="3" y="4" width="26" height="24" fill="#c0c0c0" stroke="#000"/>' +
           '<rect x="6" y="7" width="20" height="4" fill="#000080"/>' +
           '<rect x="6" y="14" width="9" height="5" fill="#fff" stroke="#000"/>' +
           '<rect x="17" y="14" width="9" height="5" fill="#fff" stroke="#000"/>' +
           '<rect x="6" y="22" width="9" height="4" fill="#fff" stroke="#000"/>',
  resume: '<rect x="7" y="2" width="18" height="28" fill="#fff" stroke="#000"/>' +
          '<path d="M10 7h12M10 11h12M10 15h12M10 19h8" stroke="#808080"/>' +
          '<rect x="5" y="8" width="22" height="16" fill="none" stroke="#000080" stroke-width="2"/>',
};

/* Build an icon node. Falls back to an empty <svg> rather than throwing if
   DOMParser is unavailable, so a missing API costs a picture and not a window. */
function icon(name) {
  const markup = ICONS[name] || ICONS.app;
  const wrap = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" ' +
               'aria-hidden="true" focusable="false">' + markup + '</svg>';
  if (typeof DOMParser !== 'function') {
    return document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  }
  const doc = new DOMParser().parseFromString(wrap, 'image/svg+xml');
  if (doc.querySelector('parsererror')) {
    return document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  }
  return document.importNode(doc.documentElement, true);
}

/* ------------------------------------------------------------ sound engine */
/* WebAudio oscillators only: no files, so nothing to load and nothing to
   fail. OFF until the user turns it on in the Sound menu -- a chime that
   ambushes you on page load is not nostalgia, it is a nuisance. */

const sfx = (function () {
  let ctx = null;
  let enabled = false;

  function ensure() {
    if (ctx) return ctx;
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null;
    try { ctx = new Ctor(); } catch (_) { ctx = null; }
    return ctx;
  }

  function tone(freq, start, dur, gainTo, type) {
    const c = ensure();
    if (!c) return;
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = type || 'square';
    osc.frequency.setValueAtTime(freq, c.currentTime + start);
    const g = gainTo === undefined ? 0.06 : gainTo;
    gain.gain.setValueAtTime(g, c.currentTime + start);
    gain.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + start + dur);
    osc.connect(gain);
    gain.connect(c.destination);
    osc.start(c.currentTime + start);
    osc.stop(c.currentTime + start + dur + 0.02);
  }

  return {
    get on() { return enabled; },
    setEnabled(v) {
      enabled = !!v;
      if (enabled) { ensure(); sfx.startup(); }
    },
    click()    { if (enabled) tone(1400, 0, 0.035, 0.035); },
    open()     { if (enabled) { tone(520, 0, 0.05, 0.05); tone(880, 0.05, 0.07, 0.045); } },
    close()    { if (enabled) { tone(700, 0, 0.05, 0.045); tone(380, 0.05, 0.08, 0.04); } },
    error()    { if (enabled) { tone(190, 0, 0.16, 0.07, 'sawtooth'); tone(140, 0.16, 0.2, 0.06, 'sawtooth'); } },
    // Four rising notes, roughly the shape of the 1995 startup sting.
    startup()  { if (!enabled) return;
      [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.11, 0.16, 0.05)); },
  };
})();

/* ------------------------------------------------------------------ state */

const wins = new Map();     // id -> record
let zTop = 20;

/* Stacking, bottom to top: ordinary windows, then the veil that dims them for a
   modal, then the modal itself, then popup menus, then the taskbar.

   A modal has to sit ABOVE its own veil. Windows stack from 20 and the veil is
   at 900, so without this every dialog rendered underneath the thing meant to
   dim it: faintly visible through 18% black, and completely unclickable,
   because a full-screen div was swallowing every click aimed at it. The taskbar
   and Start menu sit above the veil, which is why the Start menu still opened
   while no window responded at all.

   Found by clicking, not by reading. The synthetic Escape the harness
   dispatched went straight to a document keydown listener and never touched the
   veil, so every automated check passed while the app was unusable. */
const Z_VEIL = 900;
const Z_MODAL = 950;
const Z_POPUP = 1050;
const Z_TASKBAR = 1100;
let activeId = null;
let cascade = 0;

const els = {
  desktop: document.getElementById('desktop'),
  taskbar: document.getElementById('taskbar'),
  taskButtons: document.getElementById('taskButtons'),
  tray: document.getElementById('tray'),
  startBtn: document.getElementById('startBtn'),
  startMenu: document.getElementById('startMenu'),
  veil: document.getElementById('veil'),
};

/* ------------------------------------------------- window creation ------- */

function place(w, h) {
  const desk = els.desktop.getBoundingClientRect();
  const width = Math.min(w || 460, Math.max(200, desk.width - 20));
  const height = Math.min(h || 320, Math.max(140, desk.height - 20));
  // The cascade: each new window steps down-right by 18px, wrapping. Exactly
  // what Win95 did, and it keeps a pile of windows from landing on one spot.
  //
  // The origin is offset clear of the desktop icon column. Cascading from the
  // very corner buried the icons under the first window, which reads as a bug
  // even though it is what Windows actually did.
  const step = 18;
  const maxSteps = 7;
  const off = (cascade % maxSteps) * step;
  cascade += 1;
  const originX = 104;
  const originY = 10;
  return {
    w: width,
    h: height,
    x: Math.min(originX + off, Math.max(0, desk.width - width - 4)),
    y: Math.min(originY + off, Math.max(0, desk.height - height - 4)),
  };
}

function createWindow(opts) {
  const o = opts || {};
  const id = o.id || ('win' + Math.random().toString(36).slice(2, 9));
  /* `h: 'auto'` means "size to the content". It has to be latched here, before
     place() is called: the old line passed `o.h === 'auto' ? 200 : o.h` into
     place() and then tested `geom.h === 'auto'`, which could never be true. So
     every auto-height dialog was silently locked to 200px.
     Nothing showed it for a long time because message boxes are short, and a
     clipped short dialog just looks like a dialog. The Export dialog's content
     finally exceeded 200px and its OK and Cancel buttons were pushed outside the
     window -- a dialog you could neither confirm nor cancel. */
  const autoH = o.h === 'auto';
  const geom = o.rect || place(o.w, autoH ? 200 : o.h);

  const win = document.createElement('div');
  win.className = 'win' + (o.dialog ? ' dialog' : '');
  win.setAttribute('data-window', id);
  win.setAttribute('role', o.dialog ? 'dialog' : 'region');
  win.setAttribute('aria-label', o.title || 'Window');
  if (o.minWidth)  win.style.minWidth  = o.minWidth + 'px';
  if (o.minHeight) win.style.minHeight = o.minHeight + 'px';

  win.style.left = geom.x + 'px';
  win.style.top = geom.y + 'px';
  win.style.width = geom.w + 'px';
  // A dialog sizes to its content. Sizing it to a default 320px left a message
  // box with a button at the top and a third of a screen of empty grey under it,
  // which no dialog in the reference does.
  if (autoH) win.style.height = 'auto';
  else win.style.height = geom.h + 'px';

  // ---- title bar
  const title = document.createElement('div');
  title.className = 'win-title';
  const ic = icon(o.icon || 'app');
  ic.setAttribute('class', 'win-title-icon');
  title.appendChild(ic);
  const text = document.createElement('span');
  text.className = 'win-title-text';
  text.textContent = o.title || 'Window';
  title.appendChild(text);

  if (!o.dialog) {
    const cap = document.createElement('span');
    cap.className = 'win-caption';
    if (o.minimisable !== false) cap.appendChild(captionBtn('min', 'Minimize', () => minimise(id)));
    if (o.resizable !== false)   cap.appendChild(captionBtn('max', 'Maximize', () => toggleMax(id)));
    cap.appendChild(captionBtn('close', 'Close', () => close(id)));
    title.appendChild(cap);
  }
  win.appendChild(title);

  // ---- menu bar
  if (o.menus && o.menus.length) {
    const bar = document.createElement('div');
    bar.className = 'win-menubar';
    o.menus.forEach((m) => {
      const item = document.createElement('div');
      item.className = 'win-menu';
      item.setAttribute('role', 'menuitem');
      item.setAttribute('tabindex', '0');
      // Alt+F, Alt+E ... as in the original. Underlining the first letter is
      // how the user learns that.
      const u = document.createElement('u');
      u.textContent = (m.label || '').charAt(0);
      item.appendChild(u);
      item.appendChild(document.createTextNode((m.label || '').slice(1)));
      item.addEventListener('click', () => openMenu(id, item, m.items || []));
      item.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); openMenu(id, item, m.items || []); }
      });
      bar.appendChild(item);
    });
    win.appendChild(bar);
  }

  // ---- toolbar
  if (o.toolbar && o.toolbar.length) {
    const bar = document.createElement('div');
    bar.className = 'win-toolbar';
    o.toolbar.forEach((t) => {
      if (t.sep) { const s = document.createElement('span'); s.className = 'sep'; bar.appendChild(s); return; }
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn btn-icon';
      b.title = t.label || '';
      b.setAttribute('aria-label', t.label || '');
      const ic2 = icon(t.icon || 'app');
      ic2.setAttribute('width', '16'); ic2.setAttribute('height', '16');
      b.appendChild(ic2);
      b.addEventListener('click', () => { sfx.click(); t.action && t.action(); });
      bar.appendChild(b);
    });
    win.appendChild(bar);
  }

  // ---- body
  const body = document.createElement('div');
  body.className = 'win-body' + (o.sunken === false ? '' : '');
  win.appendChild(body);

  // ---- status bar
  if (o.status !== false) {
    const st = document.createElement('div');
    st.className = 'win-statusbar';
    const left = document.createElement('span');
    left.className = 'win-status-cell grow';
    left.setAttribute('data-role', 'status-left');
    left.textContent = o.statusText || 'Ready';
    const right = document.createElement('span');
    right.className = 'win-status-cell';
    right.setAttribute('data-role', 'status-right');
    right.textContent = '';
    const grip = document.createElement('span');
    grip.className = 'win-status-grip';
    st.appendChild(left); st.appendChild(right); st.appendChild(grip);
    win.appendChild(st);
  }

  if (o.resizable !== false && !o.dialog) {
    const grip = document.createElement('div');
    grip.className = 'win-resizer';
    win.appendChild(grip);
    startResize(id, win, grip);
  }

  startDrag(id, win, title);
  els.desktop.appendChild(win);

  const rec = {
    id, el: win, title: text, body,
    minimised: false, maximised: false,
    restore: null, onClose: o.onClose, modal: !!o.modal,
    // Stored, not merely used to build the class name. Both toggleMax() and the
    // Escape handler read rec.dialog, and it was never assigned -- so Escape
    // could never dismiss a modal dialog, and a dialog would have been
    // maximisable. Undefined is falsy, so nothing threw and nothing looked
    // broken: the feature was simply absent. Found by dispatching a real key
    // event, not by reading the source.
    dialog: !!o.dialog,
    resizable: o.resizable !== false && !o.dialog,
    iconName: o.icon || 'app',
  };
  win.setAttribute('data-icon', rec.iconName);
  wins.set(id, rec);

  // The opening animation, with a guaranteed cleanup. animationend does not
  // fire when an animation is cancelled, when the tab is backgrounded, or when
  // prefers-reduced-motion sets `animation: none` -- and a stuck `opening`
  // class means opacity 0, i.e. a window that is present, focusable and
  // completely invisible. Correctness must not depend on an animation running.
  // Same reasoning as close()'s fallback below.
  win.classList.add('opening');
  const opened = () => win.classList.remove('opening');
  win.addEventListener('animationend', opened, { once: true });
  setTimeout(opened, 250);

  focusWindow(id);
  raiseOnPointerDown(id, win);
  buildTaskButtons();
  sfx.open();
  return rec;
}

function captionBtn(kind, label, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'btn btn-icon glyph-' + kind;
  b.title = label;
  b.setAttribute('aria-label', label);
  b.addEventListener('click', (ev) => { ev.stopPropagation(); sfx.click(); onClick(); });
  return b;
}

/* ------------------------------------------------------------ focus / z */

function focusWindow(id) {
  const rec = wins.get(id);
  if (!rec) return;
  if (activeId === id && rec.el.style.zIndex) return;
  activeId = id;
  // A modal must clear the veil it raises. See the stacking note above.
  if (rec.modal) zTop = Math.max(zTop + 1, Z_MODAL);
  else zTop += 1;
  rec.el.style.zIndex = String(zTop);
  wins.forEach((r) => r.el.setAttribute('data-active', String(r.id === id)));
  buildTaskButtons();
  syncVeil();
}

function syncVeil() {
  const anyModal = Array.from(wins.values()).some(
    (r) => r.modal && !r.minimised && !r.el.hidden);
  if (els.veil) els.veil.classList.toggle('on', anyModal);
}

/* Any click inside a window brings it to the front.
 *
 * Without this the only way to raise an overlapped window was to drag its title
 * bar, because focusWindow() was reachable from exactly three places: creation,
 * a drag, and restore. That is not how a desktop behaves -- and it was invisible
 * to every test, because each test either opened a window (which focuses it) or
 * clicked a control in a window that was already on top.
 *
 * pointerdown rather than click, because focus must move before the control's own
 * handler runs, or the first click on a background window's button would act on a
 * window the user had not yet raised. */
function raiseOnPointerDown(id, win) {
  win.addEventListener('pointerdown', () => focusWindow(id), true);
}

/* --------------------------------------------------------------- drag ---- */

function startDrag(id, win, handle) {
  handle.addEventListener('mousedown', (ev) => {
    // Buttons and the menu bar are not drag handles.
    if (ev.target.closest('.win-caption') || ev.target.closest('.win-menu')) return;
    if (ev.button !== 0) return;
    focusWindow(id);

    const rec = wins.get(id);
    if (rec.maximised) return;          // a maximised window does not drag

    const startX = ev.clientX;
    const startY = ev.clientY;
    const left = parseInt(win.style.left, 10) || 0;
    const top = parseInt(win.style.top, 10) || 0;
    let moved = false;

    document.body.classList.add('dragging');

    const onMove = (e) => {
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 3) return;
      moved = true;
      const desk = els.desktop.getBoundingClientRect();
      const w = win.offsetWidth;
      const h = win.offsetHeight;
      // Let the title bar go under the taskbar, but never above the desktop,
      // and never so far right that the window is unreachable.
      const maxX = desk.width - 60;
      const maxY = desk.height - 8;
      win.style.left = Math.max(-w + 60, Math.min(maxX, left + dx)) + 'px';
      win.style.top  = Math.max(0, Math.min(maxY, top + dy)) + 'px';
    };

    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.classList.remove('dragging');
    };

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    ev.preventDefault();
  });

  // Double-click the title bar maximises, as everywhere in Windows.
  handle.addEventListener('dblclick', (ev) => {
    if (ev.target.closest('.win-caption')) return;
    toggleMax(id);
  });
}

/* ------------------------------------------------------------- resize ---- */

function startResize(id, win, grip) {
  grip.addEventListener('mousedown', (ev) => {
    if (ev.button !== 0) return;
    ev.stopPropagation();
    focusWindow(id);
    const startX = ev.clientX;
    const startY = ev.clientY;
    const w = win.offsetWidth;
    const h = win.offsetHeight;
    const minW = parseInt(getComputedStyle(win).minWidth, 10) || 180;
    const minH = parseInt(getComputedStyle(win).minHeight, 10) || 90;

    document.body.classList.add('resizing');

    const onMove = (e) => {
      const desk = els.desktop.getBoundingClientRect();
      win.style.width = Math.max(minW, Math.min(desk.width - win.offsetLeft,
        w + (e.clientX - startX))) + 'px';
      win.style.height = Math.max(minH, Math.min(desk.height - win.offsetTop,
        h + (e.clientY - startY))) + 'px';
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.classList.remove('resizing');
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    ev.preventDefault();
  });
}

/* ------------------------------------------------- minimise / maximise --- */

function minimise(id) {
  const rec = wins.get(id);
  if (!rec || rec.minimised) return;
  rec.minimised = true;
  rec.el.hidden = true;
  sfx.click();
  // Hand focus to whatever is now on top that is actually visible.
  const next = topmostVisible();
  if (next) focusWindow(next); else activeId = null;
  buildTaskButtons();
  syncVeil();
}

function restore(id) {
  const rec = wins.get(id);
  if (!rec) return;
  if (rec.minimised) { rec.minimised = false; rec.el.hidden = false; sfx.open(); }
  focusWindow(id);
  buildTaskButtons();
  syncVeil();
}

function toggleMax(id) {
  const rec = wins.get(id);
  if (!rec || rec.dialog) return;
  sfx.click();
  if (rec.maximised) {
    if (rec.restore) {
      rec.el.style.left = rec.restore.x; rec.el.style.top = rec.restore.y;
      rec.el.style.width = rec.restore.w; rec.el.style.height = rec.restore.h;
    }
    rec.maximised = false;
  } else {
    rec.restore = {
      x: rec.el.style.left, y: rec.el.style.top,
      w: rec.el.style.width, h: rec.el.style.height,
    };
    const desk = els.desktop.getBoundingClientRect();
    rec.el.style.left = '0px';
    rec.el.style.top = '0px';
    rec.el.style.width = desk.width + 'px';
    rec.el.style.height = desk.height + 'px';
    rec.maximised = true;
  }
  buildTaskButtons();
}

function close(id) {
  const rec = wins.get(id);
  if (!rec) return;
  if (rec.onClose && rec.onClose() === false) return;   // a veto
  rec.el.classList.add('closing');
  sfx.close();
  const done = () => {
    rec.el.remove();
    wins.delete(id);
    const next = topmostVisible();
    if (next) focusWindow(next); else { activeId = null; }
    buildTaskButtons();
    syncVeil();
  };
  rec.el.addEventListener('animationend', done, { once: true });
  // If motion is off, animationend never fires, so remove it directly.
  setTimeout(() => { if (rec.el.parentNode) done(); }, 220);
}

function topmostVisible() {
  let best = null;
  let bestZ = -1;
  wins.forEach((r) => {
    if (r.minimised) return;
    const z = parseInt(r.el.style.zIndex, 10) || 0;
    if (z > bestZ) { bestZ = z; best = r.id; }
  });
  return best;
}

/* ------------------------------------------------------- taskbar / start - */

function buildTaskButtons() {
  if (!els.taskButtons) return;
  els.taskButtons.textContent = '';
  wins.forEach((rec) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'task-btn';
    b.setAttribute('data-active', String(rec.id === activeId && !rec.minimised));
    const ic = icon(rec.el.getAttribute('data-icon') || 'app');
    ic.setAttribute('width', '14'); ic.setAttribute('height', '14');
    b.appendChild(ic);
    const label = document.createElement('span');
    label.textContent = rec.title.textContent;
    b.appendChild(label);
    b.addEventListener('click', () => {
      sfx.click();
      if (rec.id === activeId && !rec.minimised) minimise(rec.id);
      else restore(rec.id);
    });
    els.taskButtons.appendChild(b);
  });
}

function setStartOpen(open) {
  if (!els.startMenu) return;
  els.startMenu.classList.toggle('open', !!open);
  els.startBtn.setAttribute('aria-expanded', String(!!open));
}

function startItem(label, iconName, action, disabled) {
  const item = document.createElement('div');
  item.className = 'start-item';
  item.setAttribute('role', 'menuitem');
  item.setAttribute('tabindex', '0');
  if (disabled) item.setAttribute('aria-disabled', 'true');
  const ic = icon(iconName);
  ic.setAttribute('width', '22'); ic.setAttribute('height', '22');
  item.appendChild(ic);
  const t = document.createElement('span');
  t.textContent = label;
  item.appendChild(t);
  const run = () => { if (disabled) { sfx.error(); return; } setStartOpen(false); sfx.click(); action(); };
  item.addEventListener('click', run);
  item.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); run(); }
  });
  return item;
}

/* --------------------------------------------------------- popup menus --- */

let openPopup = null;

function closePopup() {
  if (!openPopup) return;
  openPopup.el.remove();
  if (openPopup.owner) openPopup.owner.setAttribute('aria-expanded', 'false');
  openPopup = null;
}

function openMenu(winId, ownerEl, items) {
  const wasSame = openPopup && openPopup.owner === ownerEl;
  closePopup();
  if (wasSame) return;                     // click again to dismiss

  const pop = document.createElement('div');
  pop.className = 'menu-popup';
  pop.setAttribute('role', 'menu');
  items.forEach((it) => {
    if (it.sep) { const s = document.createElement('div'); s.className = 'menu-sep'; pop.appendChild(s); return; }
    const row = document.createElement('div');
    row.className = 'menu-item';
    row.setAttribute('role', 'menuitem');
    row.setAttribute('tabindex', '0');
    if (it.disabled) row.setAttribute('aria-disabled', 'true');
    if (it.checked) {
      const m = document.createElement('span');
      m.className = 'check-mark';
      m.textContent = '✓';
      row.appendChild(m);
    }
    const label = document.createElement('span');
    label.textContent = it.label;
    row.appendChild(label);
    if (it.accel) {
      const a = document.createElement('span');
      a.className = 'accel';
      a.textContent = it.accel;
      row.appendChild(a);
    }
    const run = () => {
      if (it.disabled) { sfx.error(); return; }
      closePopup();
      sfx.click();
      it.action && it.action();
    };
    row.addEventListener('click', run);
    row.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); run(); }
    });
    pop.appendChild(row);
  });

  document.body.appendChild(pop);
  const r = ownerEl.getBoundingClientRect();
  const top = r.bottom;
  // Flip above the menu bar if it would fall off the bottom of the screen.
  const h = pop.offsetHeight;
  const below = els.desktop.getBoundingClientRect().height + els.desktop.offsetTop;
  pop.style.left = Math.max(2, Math.min(r.left, window.innerWidth - pop.offsetWidth - 4)) + 'px';
  pop.style.top = (top + h > below ? Math.max(2, top - h - (r.height - 2)) : top) + 'px';
  ownerEl.setAttribute('aria-expanded', 'true');
  openPopup = { el: pop, owner: ownerEl };
}

/* ------------------------------------------------------------- dialogs --- */

/* A message box: the workhorse of this whole UI. One function covers the
   information, warning, error and question icons because they differ only in
   the glyph and the buttons. */
function messageBox(opts) {
  const o = opts || {};
  const buttons = o.buttons || ['OK'];
  return new Promise((resolve) => {
    let settled = false;
    const id = o.id || ('dlg' + Math.random().toString(36).slice(2, 9));

    /* One exit point, used by the buttons, by Escape and by the window manager
       alike. Previously the buttons removed the window themselves and onClose
       returned false, which meant Escape resolved the promise but left the
       dialog on screen with the modal veil still up: a dialog with no close box
       and no working Escape, which is a trap. */
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
      close(id);
    };

    const rec = createWindow({
      id: id,
      dialog: true,
      modal: o.modal !== false,
      title: o.title || 'Sheetsworks',
      icon: 'app',
      w: o.w || 380,
      h: 'auto',
      resizable: false,
      minimisable: false,
      status: false,
      onClose: () => {
        // Escape, or a stray click while modal: treated as Cancel.
        finish(o.cancelValue !== undefined ? o.cancelValue : null);
        return true;                   // and let the window actually go away
      },
    });

    const row = document.createElement('div');
    row.className = 'msg-row';
    const ic = icon(o.icon || 'info');
    ic.setAttribute('class', 'msg-icon');
    row.appendChild(ic);
    const text = document.createElement('div');
    text.className = 'msg-text';
    if (o.heading) {
      const h = document.createElement('span');
      h.className = 'title';
      h.textContent = o.heading;
      text.appendChild(h);
    }
    text.appendChild(document.createTextNode(o.message || ''));
    row.appendChild(text);
    rec.body.appendChild(row);

    const bar = document.createElement('div');
    bar.className = 'msg-buttons';
    buttons.forEach((label, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn' + (i === 0 ? ' default' : '');
      b.textContent = label;
      b.addEventListener('click', () => { sfx.click(); finish(label); });
      bar.appendChild(b);
    });
    rec.body.appendChild(bar);
    setTimeout(() => {
      const first = rec.el.querySelector('.btn.default') || rec.el.querySelector('.btn');
      if (first) first.focus();
    }, 0);
  });
}

/* --------------------------------------------------------------- status --- */

function setStatus(winId, text, slot) {
  const rec = wins.get(winId);
  if (!rec) return;
  const cell = rec.el.querySelector('[data-role="status-' + (slot || 'left') + '"]');
  if (cell) cell.textContent = text;
}

/* A busy indicator that looks like 1995: the title bar text cycles ellipsis,
   the pointer becomes an hourglass, and the status bar shows an indeterminate
   block. Called around anything that talks to the server. */
function setBusy(winId, on, label) {
  const rec = wins.get(winId);
  if (!rec) return;
  const base = rec.title.textContent.replace(/[.…]+$/, '');
  if (on) {
    rec.title.textContent = base + '...';
    rec.el.setAttribute('aria-busy', 'true');
    document.body.classList.add('is-busy');
    setStatus(winId, label || 'Working...');
  } else {
    rec.title.textContent = base;
    rec.el.removeAttribute('aria-busy');
    document.body.classList.remove('is-busy');
    setStatus(winId, 'Ready');
  }
}

function progress(winId, slot, fraction) {
  const rec = wins.get(winId);
  if (!rec) return;
  let bar = rec.el.querySelector('[data-progress="' + (slot || 'main') + '"]');
  if (!bar) {
    bar = document.createElement('div');
    bar.className = 'bar';
    bar.setAttribute('data-progress', slot || 'main');
    const fill = document.createElement('div');
    fill.className = 'bar-fill';
    bar.appendChild(fill);
    (rec.body.querySelector('.well-fill') || rec.body).appendChild(bar);
  }
  const fill = bar.querySelector('.bar-fill');
  if (fraction === null || fraction === undefined) {
    bar.classList.add('indeterminate');
  } else {
    bar.classList.remove('indeterminate');
    fill.style.width = Math.max(0, Math.min(1, fraction)) * 100 + '%';
  }
}

/* ------------------------------------------------------------- keyboard -- */

document.addEventListener('mousedown', (ev) => {
  if (!openPopup) return;
  if (openPopup.el.contains(ev.target) || openPopup.owner.contains(ev.target)) return;
  closePopup();
}, true);

document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape') {
    if (openPopup) { closePopup(); return; }
    if (els.startMenu && els.startMenu.classList.contains('open')) { setStartOpen(false); return; }
    const rec = wins.get(activeId);
    if (rec && rec.dialog) close(rec.id);
    return;
  }
  // Ctrl+Esc, or the Windows key, opens Start -- as it always did.
  if ((ev.ctrlKey && ev.key === 'Escape') || ev.key === 'Meta') {
    ev.preventDefault();
    setStartOpen(!els.startMenu.classList.contains('open'));
    return;
  }
  // Alt+letter activates a menu bar item of the active window.
  if (ev.altKey && ev.key.length === 1 && activeId) {
    const rec = wins.get(activeId);
    if (!rec) return;
    const key = ev.key.toLowerCase();
    const items = rec.el.querySelectorAll('.win-menu');
    for (let i = 0; i < items.length; i++) {
      const letter = items[i].textContent.trim().charAt(0).toLowerCase();
      if (letter === key) { ev.preventDefault(); items[i].click(); return; }
    }
  }
});

/* Clicking the desktop drops focus, so the active window is never a lie. */
if (els.desktop) {
  els.desktop.addEventListener('mousedown', (ev) => {
    if (ev.target !== els.desktop) return;
    closePopup();
    setStartOpen(false);
    activeId = null;
    wins.forEach((r) => r.el.setAttribute('data-active', 'false'));
    buildTaskButtons();
  });
}

/* The last line of defence. A throw inside a window must not take the whole
   desktop with it -- and it must say so, rather than leaving a dead window
   with no explanation. Carried over from the terminal UI, where the same test
   caught a temporal-dead-zone ReferenceError that blanked the entire page. */
window.addEventListener('error', function (ev) {
  report(ev.message || 'unknown error');
});
window.addEventListener('unhandledrejection', function (ev) {
  const r = ev.reason;
  report((r && r.message) || String(r));
});

let reported = 0;
function report(message) {
  // Do not let an error inside the reporter start an error inside the reporter.
  if (reported > 4) return;
  reported += 1;
  sfx.error();
  messageBox({
    title: 'Sheetsworks',
    icon: 'error',
    heading: 'Something went wrong',
    message: String(message),
    buttons: ['OK'],
  });
}

/* Expose the shell. Everything the windows need and nothing more. */
window.Win95 = {
  ICONS, svg, icon, sfx,
  createWindow, close, minimise, restore, toggleMax, focusWindow,
  setStatus, setBusy, progress,
  messageBox, openMenu, closePopup,
  setStartOpen, startItem,
  startSeparator: function () {
    const s = document.createElement('div');
    s.className = 'start-sep';
    return s;
  },
  windows: wins,
  get activeId() { return activeId; },
  els,
};

})();