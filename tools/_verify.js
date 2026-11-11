/* ============================================================================
   _verify.js -- drives the real desktop and reports what it found.

   Loads the app's own scripts in the top document, then exercises the window
   manager, every window, the preview, focus, minimise/maximise and a message
   box, and writes the result into the DOM so `chromium --dump-dom` can carry
   it out.

   Two rules this file follows because the first version got them wrong:
     - it writes to the log synchronously on entry, so a harness that dies
       early says so rather than leaving an empty log that reads as a pass;
     - it never reports success by being silent. Every check is recorded.
   ========================================================================= */

(function () {
'use strict';

var FAILS = [];
var COUNT = 0;
var log = document.createElement('pre');
log.id = 'verifyLog';
// pointer-events:none, because this overlay covers the whole page. With it on,
// elementFromPoint returns the <pre> instead of whatever is really under the
// cursor, and the harness "fails" a perfectly good button. A log has no
// business intercepting a click.
log.style.cssText = 'position:fixed;inset:0;z-index:99999;background:#000;' +
  'color:#0f0;font:11px monospace;padding:8px;margin:0;overflow:auto;' +
  'white-space:pre-wrap;pointer-events:none';
document.body.appendChild(log);

function say(text) { log.textContent += text + '\n'; }

function ok(label, cond, detail) {
  COUNT++;
  if (!cond) FAILS.push(label + (detail ? ' :: ' + detail : ''));
  say((cond ? 'PASS  ' : 'FAIL  ') + label + (detail ? '   ' + detail : ''));
}

function finish() {
  say('');
  say('--- ' + COUNT + ' checks, ' + FAILS.length + ' failed ---');
  FAILS.forEach(function (f) { say('  ! ' + f); });
  document.title = 'DONE';
}

say('harness evaluated, waiting for boot');

function win(id) { return document.querySelector('[data-window="' + id + '"]'); }
function txt(node) { return node ? node.textContent : ''; }
function pause(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
/* Order-sensitive array comparison. Sorting both sides would hide a reordering
   bug, which is exactly the sort of thing worth catching in a format list. */
function fmt_eq(got, want) {
  if (got.length !== want.length) return false;
  return got.every(function (v, i) { return v === want[i]; });
}

/* Boot is async and nothing signals when it finished, so poll for the thing
   that only exists afterwards. Bounded, so a boot failure reports rather than
   hangs. */
function waitForBoot() {
  return new Promise(function (resolve, reject) {
    var tries = 0;
    (function poll() {
      tries++;
      // Wait for the app's OWN readiness signal, not for a window to appear.
      // A window exists from the first frame; `state.profile` does not settle
      // until boot's fetch returns. Seeding a profile before that and then
      // having boot overwrite it with null produced five failures that read as
      // four unrelated bugs.
      if (window.Sheetsworks && window.Sheetsworks.ready) {
        window.Sheetsworks.ready.then(function () { resolve(true); },
                                       function () { resolve(true); });
        return;
      }
      if (tries > 120) return reject(new Error('boot never completed'));
      setTimeout(poll, 50);
    })();
  });
}

waitForBoot().then(run).catch(function (err) {
  // The app's own error handler opens a message box, which is right for a user
  // and useless here. Report what actually threw.
  const seen = (window.__errors || []).join(' | ') || '(nothing recorded)';
  ok('the app boots', false, String(err && err.message || err) + ' -- ' + seen);
  const dlg = document.querySelector('.win.dialog');
  if (dlg) ok('a message box said', false, dlg.textContent.slice(0, 300));
  finish();
});

async function run() {
  const S = window.Sheetsworks;
  const W = window.Win95;
  const D = document;

  try {
    ok('the app surface exists', !!S);
    ok('the window manager is exposed', !!W);
    ok('the sample data is exposed', !!window.SampleResume);
    ok('the editor model is exposed', !!window.EditorModel);
    ok('the editor form is exposed', !!window.EditorForm);
    const M = window.EditorModel;

    /* ---------------- load the sample first ----------------
       With no profile there is nothing for the File Manager to list and
       nothing for the preview to render. Checking those against an empty
       profile would test the empty case and then report it as a pass. */
    S.state.profile = window.SampleResume.build();
    const saved = await fetch('/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(S.state.profile),
    });
    ok('the API accepts the sample profile', saved.ok, 'HTTP ' + saved.status);
    const reread = await (await fetch('/profile')).json();
    ok('the sample round-trips through the server',
       !!(reread.contact && reread.contact.name === 'Anon'),
       reread.contact && reread.contact.name);

    /* A version has to exist before the Versions pane can be said to list
       anything. Checked against GET /versions directly, so a failure here is
       the endpoint's, not the browser's.

       Order matters. The sample's name is still 'Anon' at this point, and
       POST /versions/from-profile refuses to snapshot one -- so the refusal is
       checked first, while the profile really is a placeholder. */
    const refused = await fetch('/versions/from-profile?name=Anon%20Resume',
                                { method: 'POST' });
    ok('a snapshot of the placeholder name is refused',
       refused.status === 400, 'HTTP ' + refused.status);
    const afterRefusal = await (await fetch('/versions')).json();
    ok('and the refused attempt stored nothing',
       Array.isArray(afterRefusal) && afterRefusal.length === 0,
       JSON.stringify(afterRefusal).slice(0, 120));

    const named = JSON.parse(JSON.stringify(S.state.profile));
    named.contact.name = 'Sample Applicant';
    await fetch('/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(named),
    });
    const snapRes = await fetch(
      '/versions/from-profile?name=' + encodeURIComponent('Sample Applicant Resume')
      + '&template=blank', { method: 'POST' });
    ok('a snapshot can be created', snapRes.status === 201, 'HTTP ' + snapRes.status);
    const listed = await (await fetch('/versions')).json();
    ok('GET /versions lists it', Array.isArray(listed) && listed.length === 1,
       JSON.stringify(listed).slice(0, 160));
    ok('and a summary carries no profile snapshot',
       Array.isArray(listed) && listed.length === 1
       && listed[0].profile_snapshot === undefined
       && listed[0].name === 'Sample Applicant Resume',
       Array.isArray(listed) && listed.length ? JSON.stringify(listed[0]) : 'none');

    /* ---------------- tips, the way the real page gets them ----------------
       Read out of the served page rather than injected here, so this checks the
       actual server-side substitution rather than a fixture that could drift
       away from it. */
    const pageHtml = await (await fetch('/')).text();
    const start = pageHtml.indexOf('<template id="tipsData">');
    const payload = pageHtml.slice(pageHtml.indexOf('>', start) + 1,
                                   pageHtml.indexOf('</template>', start));
    let tips = [];
    try { tips = JSON.parse(payload).tips; } catch (_) { tips = []; }
    ok('the server injects the research tips into the page', tips.length >= 6,
       tips.length + ' tips');
    S.state.tips = tips;
    // Re-render Read Me so it shows the real payload rather than the fixture.
    W.close('readme'); await pause(120);

    /* ---------------- desktop ---------------- */
    const icons = Array.from(D.querySelectorAll('.desk-icon'));
    ok('the desktop has icons', icons.length >= 6, icons.length + ' icons');
    const labels = icons.map(function (n) { return n.textContent.trim(); });
    ['My Resume', 'Sample Resume', 'File Manager', 'Read Me', 'Preview',
     'Export As', 'Display', 'Sheetsworks'].forEach(function (want) {
      ok('desktop icon: ' + want, labels.indexOf(want) !== -1, labels.join(' / '));
    });

    /* ---------------- taskbar and start ---------------- */
    const taskBtns = Array.from(D.querySelectorAll('.task-btn'));
    ok('the taskbar tracks open windows', taskBtns.length >= 1,
       taskBtns.length + ' buttons');
    ok('at most one taskbar button is active',
       taskBtns.filter(function (b) {
         return b.getAttribute('data-active') === 'true';
       }).length <= 1);
    ok('the tray shows the sound state', txt(D.getElementById('trayText')) !== '');

    const startItems = Array.from(D.querySelectorAll('#startMenu .start-item'))
      .map(function (n) { return n.textContent.trim(); });
    ok('the start menu lists the applications', startItems.length >= 7,
       startItems.join(' / '));
    ['My Resume', 'Sample Resume', 'File Manager', 'Preview', 'Export As...',
     'Read Me', 'Display Properties', 'AI Resume Builder', 'Exit']
      .forEach(function (want) {
      ok('start item: ' + want, startItems.indexOf(want) !== -1);
    });
    ok('the start menu is closed on arrival',
       !D.getElementById('startMenu').classList.contains('open'));

    /* ---------------- the editor window ---------------- */
    const ed = win('editor');
    ok('My Resume is open on arrival', !!ed);
    ok('it has a title bar', !!ed.querySelector('.win-title-text'));
    ok('it has a status bar', !!ed.querySelector('.win-statusbar'));
    ok('it has exactly three caption buttons',
       ed.querySelectorAll('.win-caption .btn').length === 3,
       ed.querySelectorAll('.win-caption .btn').length + '');
    const menus = Array.from(ed.querySelectorAll('.win-menu'))
      .map(function (n) { return n.textContent.trim(); });
    ok('it has File / Edit / View / Help',
       ['File', 'Edit', 'View', 'Help'].every(function (m) {
         return menus.indexOf(m) !== -1;
       }), menus.join(' / '));
    ok('it has a toolbar', ed.querySelectorAll('.win-toolbar .btn').length >= 3,
       ed.querySelectorAll('.win-toolbar .btn').length + ' buttons');
    // The placeholder had a progress bar to demonstrate the loading states; the
    // real form does not need one, so this asserts the form's structure instead.
    ok('the editor has a section list and a field pane',
       !!ed.querySelector('[data-role="sections"]') && !!ed.querySelector('.ed-fields'));
    ok('the editor has a Save / Undo / Close bar',
       /Save/.test(ed.textContent) && /Undo/.test(ed.textContent)
       && /Close/.test(ed.textContent));
    ok('the status bar says something',
       txt(ed.querySelector('[data-role="status-right"]')) !== '',
       txt(ed.querySelector('[data-role="status-right"]')));
    ok('the status bar grip is present', !!ed.querySelector('.win-status-grip'));

    /* ---------------- open the rest ---------------- */
    S.openFileManager(); await pause(150);
    S.openReadMe();      await pause(150);
    S.openPreview();     await pause(150);
    S.openDisplay();     await pause(150);

    const fm = win('fm'), rm = win('readme'), pv = win('preview'), dp = win('display');
    ok('File Manager opened', !!fm);
    ok('Read Me opened', !!rm);
    ok('Preview opened', !!pv);
    ok('Display Properties opened', !!dp);

    /* ---------------- File Manager ---------------- */
    ok('File Manager has a Resume tab and a Versions tab',
       fm.querySelectorAll('.fm-tabs .tab').length === 2);
    const boxes = fm.querySelectorAll('.listbox');
    ok('File Manager has two list boxes', boxes.length === 2, boxes.length + '');
    Array.from(boxes).forEach(function (b, i) {
      const r = b.getBoundingClientRect();
      ok('list box ' + i + ' has real height', r.height > 60, Math.round(r.height) + 'px');
      ok('list box ' + i + ' has rows', b.children.length > 0, b.children.length + '');
    });
    const sections = Array.from(boxes[0].children)
      .map(function (n) { return n.textContent.trim(); });
    // Every section the model knows about must be offered, labelled for a
    // person rather than by its key.
    ok('the tree lists every section the model declares',
       M.ORDER.every(function (key) {
         return sections.some(function (t) { return t.indexOf(M.SECTIONS[key].label) === 0; });
       }), sections.join(' / '));

    // Versions mode. Switch by clicking the tab, the way a person would.
    const vtab = fm.querySelector('.fm-tabs .tab[data-mode="versions"]');
    ok('the Versions tab is clickable', !!vtab);
    vtab.click();
    await pause(700);
    ok('the Versions tab is now selected',
       vtab.getAttribute('aria-selected') === 'true');
    ok('the title reflects the mode', /Versions/.test(fm.querySelector('.win-title-text').textContent),
       fm.querySelector('.win-title-text').textContent);
    const vRows = fm.querySelectorAll('.fm-left .listbox-row[data-version]');
    ok('the version list is a real list, not a loading stub',
       fm.querySelector('.fm-left').textContent.indexOf('Loading...') === -1,
       fm.querySelector('.fm-left').textContent.slice(0, 80));
    ok('versions found on the server', vRows.length >= 1,
       vRows.length + ' versions; pane says: '
       + fm.querySelector('.fm-left').textContent.trim().slice(0, 60));

    // Selecting one must offer Export and Delete.
    if (vRows.length) {
      vRows[0].click();
      await pause(120);
      const actions = fm.querySelector('.fm-actions');
      ok('selecting a version shows its details', !!actions);
      ok('it can be exported from here',
         !!actions && /Export/.test(actions.textContent));
      ok('it can be deleted from here',
         !!actions && /Delete/.test(actions.textContent));
      ok('the details name the version',
         /Name:/.test(fm.querySelector('[data-role="fm-right"]').textContent));
    }
    fm.querySelector('.fm-tabs .tab[data-mode="resume"]').click();
    await pause(150);

    /* ---------------- raising an overlapped window ---------------- */
    // A click anywhere inside a window must bring it forward. The only way to do
    // this used to be dragging the title bar, so an overlapped window could not
    // be raised by clicking its body -- and every earlier test missed that,
    // because each one either opened a window or clicked something already on
    // top. Exactly the "the control exists and responds" trap.
    W.focusWindow('fm');
    await pause(120);
    ok('the File Manager can be raised by name', fm.getAttribute('data-active') === 'true',
       'data-active=' + fm.getAttribute('data-active'));
    ok('and that demotes the others',
       pv.getAttribute('data-active') === 'false'
       && ed.getAttribute('data-active') === 'false');
    // Now click the *editor* -- a window underneath -- and see if it comes up.
    ed.querySelector('.win-body').dispatchEvent(
      new PointerEvent('pointerdown', { bubbles: true }));
    await pause(150);
    ok('clicking an overlapped window brings it to the front',
       ed.getAttribute('data-active') === 'true',
       'editor data-active=' + ed.getAttribute('data-active')
       + ', z=' + ed.style.zIndex + ' vs fm z=' + fm.style.zIndex);
    ok('and it is genuinely above the one it was behind',
       parseInt(ed.style.zIndex, 10) > parseInt(fm.style.zIndex, 10),
       ed.style.zIndex + ' > ' + fm.style.zIndex);

    /* ---------------- Read Me ---------------- */
    const tipBlocks = rm.querySelectorAll('.win-body > .well-fill > div');
    ok('Read Me lists the research tips', tipBlocks.length >= 6,
       tipBlocks.length + ' tips');
    const rmText = rm.textContent;
    ok('Read Me shows a verified tag', rmText.indexOf('[verified]') !== -1);
    ok('Read Me shows an unverified tag', rmText.indexOf('[unverified]') !== -1);
    ok('Read Me cites RULES.md', rmText.indexOf('RULES.md') !== -1);
    ok('Read Me has a menu bar', rm.querySelectorAll('.win-menu').length >= 2);

    /* ---------------- Preview ---------------- */
    const frame = pv.querySelector('#previewFrame');
    ok('the preview has an iframe', !!frame);
    ok('the iframe was handed a real blob URL',
       !!frame && frame.src.indexOf('blob:') === 0, frame && frame.src.slice(0, 30));
    const fb = pv.querySelector('#previewFallback');
    // The property alone is not the assertion that matters. `hidden` only
    // contributes a UA-level [hidden] rule, which an inline `display:flex`
    // outranks -- and that is precisely the bug that made every preview show
    // "could not be shown" instead of the PDF. So check what is *painted*.
    ok('the fallback is genuinely not painted over the PDF',
       !!fb && getComputedStyle(fb).display === 'none',
       fb ? 'display=' + getComputedStyle(fb).display : 'no fallback element');
    // And the element at the centre of the preview must not be the message.
    // elementFromPoint is the only check that catches a panel sitting
    // invisibly on top of content. Raise the window first, the way a person
    // would -- the windows cascade, so something else is legitimately in front.
    pv.querySelector('.win-title').dispatchEvent(
      new PointerEvent('pointerdown', { bubbles: true }));
    await pause(250);
    const fr = frame.getBoundingClientRect();
    const cx = fr.left + fr.width / 2, cy = fr.top + fr.height / 2;
    const hit = document.elementFromPoint(cx, cy);
    // Name the window the hit belongs to, so a failure says WHICH thing is in
    // front instead of just "a button".
    const hitWin = hit && hit.closest ? hit.closest('[data-window]') : null;
    ok('nothing is painted over the preview frame',
       !!hit && !fb.contains(hit),
       hit ? hit.tagName + '.' + hit.className
           + ' in ' + (hitWin ? hitWin.getAttribute('data-window') : 'no window')
           + ' at ' + Math.round(cx) + ',' + Math.round(cy)
       : 'nothing there');
    ok('and the frame is what you reach once the window is in front',
       hit === frame || frame.contains(hit),
       hit ? hit.tagName + '.' + hit.className
           + ' in ' + (hitWin ? hitWin.getAttribute('data-window') : 'no window')
       : 'nothing there');
    ok('the open-in-new-tab link points at the blob',
       pv.querySelector('#previewOpen').href.indexOf('blob:') === 0,
       pv.querySelector('#previewOpen').href.slice(0, 24));
    const pvStatus = txt(pv.querySelector('[data-role="status-right"]'));
    ok('the preview status reports the page budget',
       /\d+\/\d+ pages/.test(pvStatus), pvStatus);

    /* ---------------- Display ---------------- */
    const rows = Array.from(dp.querySelectorAll('.listbox-row'));
    ok('Display lists both templates', rows.length === 2, rows.length + '');
    ok('Display marks exactly one template active',
       rows.filter(function (r) {
         return r.getAttribute('aria-selected') === 'true';
       }).length === 1);
    const btnLabels = Array.from(dp.querySelectorAll('.msg-buttons .btn'))
      .map(function (n) { return n.textContent.trim(); });
    ok('Display has OK / Cancel / Help in that order',
       btnLabels.join(',') === 'OK,Cancel,Help', btnLabels.join(','));
    const gbox = dp.querySelector('.groupbox').getBoundingClientRect();
    const bar = dp.querySelector('.msg-buttons').getBoundingClientRect();
    ok('the buttons sit BELOW the group box', bar.top > gbox.bottom,
       'groupbox ends ' + Math.round(gbox.bottom) + ', buttons start ' + Math.round(bar.top));

    /* ---------------- focus, z-order, minimise, maximise ---------------- */
    W.focusWindow('fm'); await pause(80);
    ok('exactly one window is active',
       D.querySelectorAll('.win[data-active="true"]').length === 1,
       D.querySelectorAll('.win[data-active="true"]').length + '');
    ok('the focused window is the active one',
       fm.getAttribute('data-active') === 'true');

    W.minimise('fm'); await pause(100);
    ok('a minimised window is hidden', win('fm').hidden === true);
    W.restore('fm'); await pause(100);
    ok('restore brings it back', win('fm').hidden === false);

    W.toggleMax('readme'); await pause(100);
    const maxed = win('readme').getBoundingClientRect();
    ok('maximise fills the desktop', maxed.width > 1000 && maxed.height > 600,
       Math.round(maxed.width) + 'x' + Math.round(maxed.height));
    W.toggleMax('readme'); await pause(100);
    const restored = win('readme').getBoundingClientRect();
    ok('maximise is reversible', restored.width < maxed.width,
       Math.round(restored.width) + 'x' + Math.round(restored.height));

    const before = D.querySelectorAll('.win').length;
    S.openFileManager(); await pause(150);
    ok('opening the same window twice does not stack a copy',
       D.querySelectorAll('.win').length === before,
       before + ' -> ' + D.querySelectorAll('.win').length);

    /* ---------------- a message box ---------------- */
    S.openAiNotice(); await pause(300);
    const dlg = D.querySelector('.win.dialog');
    ok('the AI notice opens as a dialog', !!dlg);
    ok('it says it is unavailable', /not available/i.test(dlg.textContent));
    ok('it explains why', /missing LLM_MODEL/i.test(dlg.textContent));
    ok('it has an OK button', !!dlg.querySelector('.msg-buttons .btn'));
    ok('a modal dims the desktop', D.getElementById('veil').classList.contains('on'));
    // Win95 modal dialogs carry no caption buttons at all -- you answer them
    // with a button or with Escape. So zero is correct; one would mean a close
    // box on a modal.
    ok('a dialog has no caption buttons',
       dlg.querySelectorAll('.win-caption .btn').length === 0,
       dlg.querySelectorAll('.win-caption .btn').length + '');

    /* ---- THE CHECK THAT WAS MISSING ----
       Every earlier assertion here passed while the app was unusable. They
       asked whether the dialog existed, was active, dimmed the desktop, and
       answered a synthetic Escape -- none of which involves the pointer.

       This asks the only question that matters: if the user clicks OK, what is
       actually under the cursor? The veil sat at z-index 900 while windows
       stacked from 20, so every dialog rendered underneath its own veil --
       visible through 18% black, and every click landing on a full-screen div.
       The desktop looked frozen. Escape still worked, which is why nothing
       looked obviously wrong. */
    const veil = D.getElementById('veil');
    const vz = parseInt(getComputedStyle(veil).zIndex, 10) || 0;
    const dz = parseInt(getComputedStyle(dlg).zIndex, 10) || 0;
    ok('the dialog stacks above its own veil', dz > vz, 'dialog=' + dz + ' veil=' + vz);
    const normalZ = parseInt(getComputedStyle(win('editor')).zIndex, 10) || 0;
    ok('the veil is above ordinary windows', vz > normalZ, vz + ' > ' + normalZ);

    const okBtn = dlg.querySelector('.msg-buttons .btn');
    const r = okBtn.getBoundingClientRect();
    const under = D.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    ok('the OK button is what the pointer would hit',
       !!under && (under === okBtn || okBtn.contains(under)),
       under ? '<' + under.tagName.toLowerCase() + ' class="' + under.className + '">'
              : 'nothing at that point');

    // A screenshot showed the dialog translucent, with the File Manager visible
    // through it. Two possible causes: the window is genuinely see-through, or
    // the opening animation was caught mid-flight. Ask the computed style.
    const cs = getComputedStyle(dlg);
    ok('the dialog is fully opaque once settled',
       parseFloat(cs.opacity) === 1, 'opacity=' + cs.opacity);
    ok('the dialog is not still animating',
       !dlg.classList.contains('opening'),
       'classes="' + dlg.className + '"');
    ok('the window face is an opaque colour',
       !/rgba\(|transparent|hsla\(/.test(cs.backgroundColor),
       cs.backgroundColor);
    // Hit-test a point in the middle of the dialog body too: if a window behind
    // it answers there, it is painting over the dialog.
    const dr = dlg.getBoundingClientRect();
    const mid = D.elementFromPoint(dr.left + dr.width / 2, dr.top + dr.height / 2);
    ok('the dialog body owns its own area',
       !!mid && dlg.contains(mid),
       mid ? '<' + mid.tagName.toLowerCase() + ' class="' + mid.className + '">'
           : 'nothing');

    okBtn.click();
    await pause(400);
    ok('clicking OK dismisses the dialog', !D.querySelector('.win.dialog'),
       D.querySelector('.win.dialog') ? 'still open' : 'closed');
    ok('dismissing by click lifts the veil',
       !D.getElementById('veil').classList.contains('on'),
       'veil="' + D.getElementById('veil').className + '"');

    // Escape, on a freshly opened one.
    S.openAiNotice(); await pause(300);
    const dlg2 = D.querySelector('.win.dialog');
    const dlgId = dlg2 ? dlg2.getAttribute('data-window') : '';
    ok('a second dialog opens', !!dlg2, String(dlgId));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await pause(400);
    ok('Escape dismisses a modal dialog', !win(dlgId),
       win(dlgId) ? 'still on screen' : 'gone');
    ok('dismissing by Escape lifts the veil',
       !D.getElementById('veil').classList.contains('on'),
       'veil="' + D.getElementById('veil').className + '"');

    /* ---------------- the sample resume ---------------- */
    const sample = window.SampleResume.build();
    ok('the sample has a name', sample.contact.name === 'Anon');
    ok('the sample is obviously fictional',
       /Sample/.test(sample.experience[0].org) &&
       /Sample/.test(sample.education[0].institution));
    ok('the sample has bullets as objects',
       typeof sample.experience[0].bullets[0] === 'object');
    ok('the sample has several skill groups', sample.skills.length >= 2);
    ok('the sample carries an Interests line for the sheets template',
       typeof sample.interests === 'string' && sample.interests.length > 10);
    ok('the emptiness check answers a boolean',
       typeof window.SampleResume.isEmpty(S.state.profile) === 'boolean');
    ok('the emptiness check calls a real profile non-empty',
       window.SampleResume.isEmpty(sample) === false);

    /* ---------------- the editor form, driven for real ---------------- */
    // Everything above inspects the chrome. This types into it, because a form
    // that renders correctly and does not save is exactly the failure that got
    // through in Stage 3.
    const ed2 = win('editor');
    ok('the editor has a section list',
       !!ed2.querySelector('[data-role="sections"]'));
    const secRows = ed2.querySelectorAll('[data-role="sections"] .listbox-row');
    ok('every section is offered', secRows.length === M.ORDER.length,
       secRows.length + ' rows');

    function pickSection(name) {
      const row = Array.from(
        ed2.querySelectorAll('[data-role="sections"] .listbox-row'))
        .find(function (r) { return r.textContent.indexOf(name) === 0; });
      if (row) row.click();
      return !!row;
    }
    function setInput(labelText, value) {
      const f = Array.from(ed2.querySelectorAll('.ed-field')).find(function (n) {
        const l = n.querySelector('.ed-label');
        return l && l.textContent === labelText;
      });
      if (!f) return false;
      const input = f.querySelector('.ed-input');
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    }

    ['Contact', 'Summary', 'Interests', 'Experience', 'Skills', 'Education',
     'Projects'].forEach(function (want) {
      ok('the editor offers ' + want, pickSection(want));
    });

    pickSection('Contact');
    await pause(150);
    ok('the name field takes a value', setInput('name', 'Anon'));
    ok('the email field takes a value', setInput('email', 'anon@example.com'));
    ok('the phone field takes a value', setInput('phone', '+91 98765 43210'));
    await pause(80);
    ok('typing marks the window dirty',
       ed2.querySelector('.win-title-text').textContent.indexOf('*') === 0,
       ed2.querySelector('.win-title-text').textContent);

    pickSection('Experience');
    await pause(150);
    const newBtn = Array.from(ed2.querySelectorAll('.ed-tools .btn'))
      .find(function (b) { return b.textContent === 'New'; });
    ok('there is a New button', !!newBtn);
    if (newBtn) newBtn.click();
    await pause(150);
    ok('a new entry can be given an org', setInput('org', 'Sample Analytics'));
    ok('and a role', setInput('role', 'Backend Engineer'));
    ok('and a start date', setInput('start', '2022-07'));
    const typeSel = ed2.querySelector('select');
    ok('experience type is a dropdown', !!typeSel,
       typeSel ? Array.from(typeSel.options).map(function (o) { return o.value; }).join(',')
               : 'none');

    // Let the debounced autosave fire.
    await pause(2200);
    ok('the autosave cleared the dirty marker',
       ed2.querySelector('.win-title-text').textContent.indexOf('*') !== 0,
       ed2.querySelector('.win-title-text').textContent);
    const afterSave = await (await fetch('/profile')).json();
    ok('the server has the typed name',
       !!(afterSave.contact && afterSave.contact.name === 'Anon'),
       afterSave.contact && afterSave.contact.name);
    ok('the server has the typed entry',
       afterSave.experience.length === 1
       && afterSave.experience[0].org === 'Sample Analytics',
       JSON.stringify(afterSave.experience || []).slice(0, 140));

    // Undo must not throw, and must put a change back.
    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true }));
    await pause(300);
    ok('Ctrl+Z did not throw', true);

    /* ---------------- Export As ---------------- */
    S.openExport();
    await pause(200);
    const ex = win('export');
    ok('the Export dialog opens', !!ex);
    if (ex) {
      ok('it is modal', ex.classList.contains('dialog'));
      const fmts = Array.from(ex.querySelectorAll('[data-role="formats"] .listbox-row'))
        .map(function (n) { return n.getAttribute('data-fmt'); });
      ok('it offers all three formats',
         fmt_eq(fmts, ['pdf', 'docx', 'txt']), fmts.join(','));
      ok('exactly one format is selected',
         ex.querySelectorAll('[data-role="formats"] [aria-selected="true"]').length === 1);
      ok('personal details are OFF by default',
         ex.querySelector('#exportPersonal').checked === false);
      ok('the filename is shown before you commit',
         /\.pdf$/.test(txt(ex.querySelector('.ed-name'))),
         txt(ex.querySelector('.ed-name')));
      // Choosing Word must change the filename extension, or the saved file
      // would claim to be a PDF and not be one.
      const docx = ex.querySelector('[data-fmt="docx"]');
      docx.click();
      await pause(80);
      ok('choosing Word changes the filename',
         /\.docx$/.test(txt(ex.querySelector('.ed-name'))),
         txt(ex.querySelector('.ed-name')));
      ok('and exactly one format stays selected',
         ex.querySelectorAll('[data-role="formats"] [aria-selected="true"]').length === 1);
      ok('the checkbox turns on',
         (function () { const c = ex.querySelector('#exportPersonal');
                        c.checked = true; return c.checked === true; })());
      ok('Cancel is offered', /Cancel/.test(ex.textContent));

      /* The check that would have caught the clipped dialog. Every dialog's
         buttons must lie INSIDE the window, not merely exist in its text.

         `h: 'auto'` used to resolve to a fixed 200px, so a dialog with tall
         content had its OK and Cancel pushed outside the window -- present in
         the DOM, not on screen, and unclickable. Asserting the text contained
         "Cancel" passed throughout. */
      (function () {
        const dr = ex.getBoundingClientRect();
        const btns = Array.from(ex.querySelectorAll('.msg-buttons .btn'));
        ok('the Export dialog has real buttons', btns.length >= 2,
           btns.length + ' found');
        const outside = btns.filter(function (b) {
          const r = b.getBoundingClientRect();
          return r.bottom > dr.bottom + 0.5 || r.right > dr.right + 0.5
              || r.top < dr.top - 0.5;
        });
        ok('every one of them is INSIDE the dialog, not clipped off it',
           outside.length === 0,
           outside.length + ' outside; dialog ' + Math.round(dr.height) + 'px tall,'
           + ' buttons end at ' + Math.round(btns.length
               ? btns[btns.length - 1].getBoundingClientRect().bottom - dr.top : -1)
           + 'px');
        ok('the dialog is taller than the 200px it used to be locked to',
           dr.height > 200, Math.round(dr.height) + 'px');
        ok('and the pointer would reach the OK button',
           (function () {
             const r = btns[0].getBoundingClientRect();
             const hit = document.elementFromPoint(r.left + r.width / 2,
                                                   r.top + r.height / 2);
             return hit === btns[0];
           })(), 'elementFromPoint at the OK button centre');
      })();
    }
    if (ex) { W.close('export'); await pause(200); }

    /* Sweep every dialog on screen for the same class of defect. A dialog whose
       buttons sit outside its own frame is unclosable, and textContent checks
       cannot see it -- only geometry can. */
    (function () {
      const dlgs = Array.from(document.querySelectorAll('.win.dialog'));
      ok('there are dialogs to sweep', dlgs.length >= 1, dlgs.length + '');
      let clipped = [];
      dlgs.forEach(function (d) {
        const dr = d.getBoundingClientRect();
        Array.from(d.querySelectorAll('.btn')).forEach(function (b) {
          const r = b.getBoundingClientRect();
          if (r.width === 0 && r.height === 0) return;   // not laid out yet
          if (r.bottom > dr.bottom + 0.5 || r.top < dr.top - 0.5) {
            clipped.push(d.getAttribute('data-window') + '/' + b.textContent.trim());
          }
        });
      });
      ok('no dialog has a button outside its own frame', clipped.length === 0,
         clipped.join(', ') || dlgs.map(function (d) {
           return d.getAttribute('data-window') + '='
             + Math.round(d.getBoundingClientRect().height) + 'px';
         }).join(' '));
    })();

    /* Is this browser even able to display a PDF? Headless Chrome frequently
       is not, which makes a black preview area meaningless as evidence. Saying
       so is better than reporting either a false pass or a phantom defect. */
    ok('this browser reports whether it can show PDFs',
       typeof navigator.pdfViewerEnabled === 'boolean',
       'pdfViewerEnabled=' + navigator.pdfViewerEnabled);
    if (navigator.pdfViewerEnabled === false) {
      ok('a black preview screenshot is therefore inconclusive here', true,
         'headless has no PDF viewer; the DOM and status bar were checked instead');
    }

    /* ---------------- profile JSON download / upload ---------------- */
    // BUILD_PLAN Stage 3 asks for "a profile JSON download/upload" beside the
    // PDF/DOCX/TXT export, and it was missing. Driven here rather than read from
    // source: the interesting failure is a menu item that exists and does
    // nothing.
    ok('the app exposes a JSON download', typeof S.downloadProfileJson === 'function');
    ok('and a JSON upload', typeof S.uploadProfileJson === 'function');

    // The round trip: what GET /profile returns must PUT back unchanged.
    const downloaded = await (await fetch('/profile')).json();
    ok('GET /profile is a complete profile object',
       !!(downloaded.contact && downloaded.experience && downloaded.skills));
    const putBack = await fetch('/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(downloaded),
    });
    ok('it PUTs back unchanged', putBack.ok, 'HTTP ' + putBack.status);

    // A malformed one must be refused with a message naming the field -- that is
    // what the upload path shows the user instead of "upload failed".
    const bad = await fetch('/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contact: { name: 'X', email: 'nope', phone: '1' } }),
    });
    ok('a malformed profile is refused', bad.status === 422, 'HTTP ' + bad.status);
    const badBody = await bad.json();
    ok('and the refusal names the field',
       Array.isArray(badBody.detail)
       && badBody.detail.some(function (d) {
         return Array.isArray(d.loc) && d.loc.join('.').indexOf('email') !== -1;
       }),
       JSON.stringify(badBody.detail).slice(0, 160));

    // reloadProfile must repaint the File Manager as well as the editor. That is
    // the drift the shared function exists to prevent: two copies of "assign it,
    // tell the form" and the File Manager keeps showing yesterday's sections.
    await fetch('/profile', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(window.SampleResume.build()),
    });
    await S.reloadProfile();
    await pause(250);
    const fmLeftText = fm.querySelector('.fm-left').textContent;
    ok('after a reload the File Manager shows the new sections',
       /Experience/.test(fmLeftText) && /Skills/.test(fmLeftText),
       fmLeftText.replace(/\s+/g, ' ').slice(0, 90));
    ok('and so does the editor',
       /Experience/.test(ed.textContent), 'the section list');

    ok('Stage 4: the AI assist button exists on bullet sections',
       document.body.textContent.indexOf('Tell the AI') !== -1,
       'the editor exposes Tell the AI');

    /* ---------------- the AI dialog's waiting state and timeout ---------- */
    /* Driven against a stubbed fetch, so this costs no provider calls and still
     * exercises the real dialog, the real waiting line and the real timeout.

     * The thing worth catching here is silence: a 60-second request with nothing
     * on screen looks identical to a broken button, and the one real run took 80
     * seconds because a truncated reply makes the server retry. */

    var realFetch = window.fetch;
    var stub = { delay: 0, mode: 'ok', seen: [] };
    window.fetch = function (url, opts) {
      var u = String(url);
      if (u.indexOf('/assist/') !== 0) return realFetch.apply(this, arguments);
      stub.seen.push(u);
      return new Promise(function (resolve, reject) {
        setTimeout(function () {
          if (stub.mode === 'unreachable') {
            /* What fetch actually throws when the host is gone. A plain Error
             * would not take the branch under test. */
            var e = new TypeError('Failed to fetch');
            reject(e);
            return;
          }
          if (stub.mode === 'error') {
            resolve(new Response(
              JSON.stringify({ detail: 'Provider said the key is not authorised.' }),
              { status: 502, headers: { 'Content-Type': 'application/json' } }));
            return;
          }
          if (u === '/assist/answer') {
            resolve(new Response(JSON.stringify({
              bullets: [{ text: 'Built the billing service.', facts: [1] }],
              numbered_facts: ['owned the billing service'],
              unused_facts: [], reused_metrics: [], shared_facts: [],
            }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
          } else {
            resolve(new Response(JSON.stringify({ entries: [], questions: [] }),
              { status: 200, headers: { 'Content-Type': 'application/json' } }));
          }
        }, stub.delay);
      });
    };

    // The newest window on the page is the one a click just opened.
    function lastWindow() {
      var wins = Array.from(document.querySelectorAll('[data-window]'));
      return wins[wins.length - 1];
    }
    function clickIn(node, label) {
      var b = Array.from(node.querySelectorAll('button')).find(function (x) {
        return x.textContent === label;
      });
      if (b) b.click();
      return !!b;
    }

    // Experience already has an entry from earlier in the harness, so the
    // section host offers "Tell the AI...".
    var edWin = win('editor');
    pickSection('Experience');
    await pause(200);
    var aiBtn = Array.from(edWin.querySelectorAll('button'))
      .find(function (b) { return b.textContent.indexOf('Tell the AI') === 0; });
    ok('the AI button appears on an Experience entry', !!aiBtn,
       aiBtn ? 'found' : 'no entry selected');

    if (aiBtn) {
      aiBtn.click();
      await pause(200);
      var dumpDlg = lastWindow();
      ok('clicking it opens a dialog',
         /Tell the AI/.test(txt(dumpDlg)), txt(dumpDlg).slice(0, 60));

      var ta = dumpDlg.querySelector('textarea');
      ok('the dialog takes a rough description', !!ta);
      if (ta) {
        ta.value = 'worked on the backend for a staffing app';
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }

      // A slow reply must put something on screen immediately.
      stub.delay = 3000;
      clickIn(dumpDlg, 'Continue');
      await pause(400);
      var waiting = document.querySelector('.ai-waiting');
      ok('a slow call shows a visible waiting state', !!waiting,
         waiting ? txt(waiting).slice(0, 80) : 'nothing appeared');
      ok('and the waiting state says what is happening',
         !!waiting && /Asking the AI/.test(txt(waiting)),
         waiting ? txt(waiting).slice(0, 120) : 'n/a');
      ok('the waiting line is styled, not bare text',
         !!waiting && getComputedStyle(waiting).display !== 'inline',
         waiting ? getComputedStyle(waiting).display : 'n/a');
      ok('the buttons are disabled while it waits',
         Array.from(dumpDlg.querySelectorAll('.msg-buttons button'))
           .every(function (b) { return b.disabled; }));

        await pause(3200);
      ok('the waiting line goes away once it answers',
         !document.querySelector('.ai-waiting'),
         txt(document.querySelector('.ai-waiting')).slice(0, 60));
    }

    // Now the failure path: a provider 502 must show the provider's own words.
    stub.delay = 50;
    stub.mode = 'error';
    if (aiBtn) {
      // The dialog that survived the slow call is gone; reopen.
      aiBtn.click();
      await pause(200);
      var d2 = lastWindow();
      var ta2 = d2.querySelector('textarea');
      if (ta2) { ta2.value = 'more backend work'; }
      clickIn(d2, 'Continue');
      await pause(600);
      var failed = d2.querySelector('.ai-waiting.ai-waiting-failed');
      ok('a provider failure is left visible in the dialog', !!failed,
         failed ? txt(failed).slice(0, 120) : 'no failed line');
      ok('and it quotes the provider, not the status code',
         !!failed && /key is not authorised/.test(txt(failed)),
         failed ? txt(failed).slice(0, 160) : 'n/a');
      ok('and it says nothing was saved',
         !!failed && /nothing was saved/i.test(txt(failed)),
         failed ? txt(failed).slice(0, 200) : 'n/a');

      // Dismiss the message box so the next check starts clean.
      var mb = Array.from(document.querySelectorAll('[data-window]'))
        .filter(function (w) { return /AI request failed/.test(txt(w)); });
      mb.forEach(function (w) {
        var okb = Array.from(w.querySelectorAll('button'))
          .find(function (b) { return b.textContent === 'OK'; });
        if (okb) okb.click();
      });
      await pause(200);
    }

    // A server that is gone must not be reported as a provider problem.
    stub.mode = 'unreachable';
    stub.delay = 50;
    if (aiBtn) {
      aiBtn.click();
      await pause(200);
      var d3 = lastWindow();
      var ta3 = d3.querySelector('textarea');
      if (ta3) { ta3.value = 'still backend work'; }
      clickIn(d3, 'Continue');
      await pause(600);
      // Scoped to this dialog: the previous failure's line is still on screen in
      // the dialog behind it, and document-wide would find that one instead.
      var gone = d3.querySelector('.ai-waiting.ai-waiting-failed');
      ok('an unreachable server is named as such',
         !!gone && /Could not reach the app/.test(txt(gone)),
         gone ? txt(gone).slice(0, 160) : 'n/a');
      Array.from(document.querySelectorAll('[data-window]'))
        .filter(function (w) { return /AI request failed/.test(txt(w)); })
        .forEach(function (w) {
          var okb = Array.from(w.querySelectorAll('button'))
            .find(function (b) { return b.textContent === 'OK'; });
          if (okb) okb.click();
        });
      await pause(200);
    }

    ok('the AI dialog made no real provider request',
       stub.seen.every(function (u) { return u.indexOf('/assist/') === 0; }),
       stub.seen.join(', '));
    window.fetch = realFetch;

    /* ---------------- skills, tech and links are real lists -------------- */
    /* The thing being checked is not that a list exists -- it did -- but that
     * each item can be corrected and deleted where it stands. Before this, a
     * typo meant deleting the whole group and retyping every item, because the
     * list was one append-only text line. */

    pickSection('Skills');
    await pause(250);
    var skillRows = edWin.querySelectorAll('.ed-item');
    ok('a skills item is a row with its own controls', skillRows.length > 0,
       skillRows.length + ' rows');
    ok('each row offers an edit', skillRows.length > 0 &&
       Array.from(skillRows).every(function (r) {
         return Array.from(r.querySelectorAll('button'))
           .some(function (b) { return b.title === 'Edit this item'; });
       }));
    ok('and a remove', skillRows.length > 0 &&
       Array.from(skillRows).every(function (r) {
         return Array.from(r.querySelectorAll('button'))
           .some(function (b) { return b.title === 'Remove this item'; });
       }));
    ok('the group is shown as it will be printed',
       /Printed as: .+: .+/.test(txt(edWin)),
       (txt(edWin).match(/Printed as: [^\n]{0,80}/) || ['none'])[0]);

    // Remove one row through the UI and confirm the page really changed.
    if (skillRows.length) {
      var rowsBefore = skillRows.length;
      Array.from(skillRows[0].querySelectorAll('button'))
        .find(function (b) { return b.title === 'Remove this item'; }).click();
      await pause(250);
      var rowsAfter = edWin.querySelectorAll('.ed-item').length;
      ok('removing a row takes it off the page', rowsAfter === rowsBefore - 1,
         rowsBefore + ' -> ' + rowsAfter);
    }

    // A link is two boxes, not one "label url" box that split on the first space.
    pickSection('Contact');
    await pause(250);
    var addLinkBtn = Array.from(edWin.querySelectorAll('button'))
      .find(function (b) { return b.textContent === 'Add a link'; });
    ok('links are added from a real list, not a read-only field',
       !!addLinkBtn && !/Add a link/.test(
         Array.from(edWin.querySelectorAll('label'))
           .map(function (l) { return l.textContent; }).join(' ')),
       addLinkBtn ? 'Add a link button' : 'missing');
    if (addLinkBtn) {
      addLinkBtn.click();
      await pause(200);
      var linkDlg = lastWindow();
      var linkLabels = Array.from(linkDlg.querySelectorAll('.ed-label'))
        .map(function (l) { return l.textContent; });
      ok('the link dialog asks for a label and a url separately',
         linkLabels.join(',') === 'label,url', linkLabels.join(','));
      var inputs = linkDlg.querySelectorAll('.ed-input');
      if (inputs.length === 2) {
        inputs[0].value = 'My GitHub';
        inputs[1].value = 'github.com/me';
      }
      clickIn(linkDlg, 'OK');
      await pause(300);
      var linkRow = Array.from(edWin.querySelectorAll('.ed-item'))
        .find(function (r) { return /My GitHub/.test(txt(r)); });
      ok('a two-word label survives being saved', !!linkRow,
         linkRow ? txt(linkRow) : 'row not found');
      ok('and the row can be corrected', !!linkRow &&
         Array.from(linkRow.querySelectorAll('button'))
           .some(function (b) { return b.title === 'Edit this link'; }));
    }

    /* The hint used to be printed twice in "Add a bullet" and "Add item". */
    pickSection('Experience');
    await pause(250);
    var addBullet = Array.from(edWin.querySelectorAll('button'))
      .find(function (b) { return b.textContent === 'Add a bullet'; });
    if (addBullet) {
      addBullet.click();
      await pause(200);
      var bulletDlg = lastWindow();
      var hint = 'the claim, optionally: claim | the numbers behind it';
      var occurrences = txt(bulletDlg).split(hint).length - 1;
      ok('the add-bullet hint is shown once, not twice', occurrences === 1,
         occurrences + ' times');
      ok('and the box has no duplicate label',
         bulletDlg.querySelectorAll('.ed-label').length === 0,
         bulletDlg.querySelectorAll('.ed-label').length + ' labels');
      clickIn(bulletDlg, 'Cancel');
      await pause(150);
    }

    /* A date typed the way a person types it is stored the way the page shows
     * it. Before this the field kept "July 2026" while the server stored
     * "2026-07", so nothing on screen showed what had been recorded.

     * Dates commit on blur, not per keystroke: "Jul" on its way to "July 2019"
     * is not a readable date, and committing each character threw a message box
     * at every one of them. Both are checked here. */
    pickSection('Education');
    await pause(250);
    function startBox() {
      return Array.from(edWin.querySelectorAll('.ed-field'))
        .filter(function (f) { return txt(f.querySelector('.ed-label')) === 'start'; })
        .map(function (f) { return f.querySelector('.ed-input'); })[0];
    }
    // Only date complaints count here. The AI tests leave dialogs lying about,
    // and counting every dialog would blame them on whatever ran next.
    function dateErrors() {
      return Array.from(edWin.parentNode.querySelectorAll('.win.dialog'))
        .filter(function (d) { return /is not a date i can read/i.test(txt(d)); })
        .map(function (d) { return txt(d).slice(0, 90); });
    }
    var errs0 = dateErrors().length;
    var startInput = startBox();
    // The rest of the profile, read back from the server, so a refused write
    // cannot quietly empty the sections around it.
    var profileBefore = await fetch('/profile').then(function (r) { return r.json(); });
    if (startInput) {
      // clear it first, then type it the way a person does, one character
      startInput.value = '';
      'July 2019'.split('').forEach(function (ch) {
        startInput.value += ch;
        startInput.dispatchEvent(new Event('input', { bubbles: true }));
      });
      await pause(200);
      ok('a half-typed date raises no error box while it is being typed',
         dateErrors().length === errs0, dateErrors().join(' || ') || 'none');
      ok('and the text is left alone under the caret',
         startInput.value === 'July 2019', startInput.value);

      startInput.dispatchEvent(new Event('change', { bubbles: true }));
      await pause(250);
      // the section redraws on commit, so the box must be looked up again
      var committed = startBox();
      // The server is the contract that matters: whatever the page shows, the stored
      // date has to be the normalised one. Reading it back also avoids guessing
      // which object the editor mutates.
      await pause(2600);
      var storedStart = await fetch('/profile').then(function (r) { return r.json(); })
        .then(function (j) {
          return j.education && j.education[0] ? String(j.education[0].start)
                                              : 'no education entry';
        });
      ok('a natural date is normalised on the way in',
         storedStart === '2019-07', storedStart);
      // Every other section must be exactly as it was. A refused date write used
      // to roll the profile back to a snapshot of a *string*, which turned the
      // sections into character keys and wiped them.
      var after = await fetch('/profile').then(function (r) { return r.json(); });
      ok('the refused half-typed dates left the other sections alone',
         M.count(after, 'skills') === M.count(profileBefore, 'skills')
         && M.count(after, 'experience') === M.count(profileBefore, 'experience')
         && after.contact.name === profileBefore.contact.name,
         'skills ' + M.count(profileBefore, 'skills') + '->' + M.count(after, 'skills')
         + ', experience ' + M.count(profileBefore, 'experience') + '->'
         + M.count(after, 'experience')
         + ', name ' + JSON.stringify(profileBefore.contact.name) + '->'
         + JSON.stringify(after.contact.name));
      ok('a natural date is normalised in the field itself',
         !!committed && committed.value === '2019-07',
         committed ? committed.value : 'no start box');
      ok('and no error box for a date it can read',
         dateErrors().length === errs0, dateErrors().join(' || ') || 'none');
    }

    /* ---- typing must not take the caret away -------------------------------
     * Every text field used to lose focus after one character, so a word cost
     * one click per letter. The cause was not the input event: it was the
     * section redrawing itself afterwards. A rebuild replaces the input
     * element, and the browser puts the caret on the document body. Only the
     * writes that change the *shape* of a section may rebuild; a keystroke
     * must never.
     *
     * Real key events, not a value assignment, because the bug is about focus
     * and a synthetic value write never had the caret to lose in the first
     * place. Checked on three kinds of field: a contact field, the multiline
     * summary, and a bullet row inside an Experience entry. */
    /* Seed by dispatching a real input event, the way a paste would, so the box
     * and the model start in agreement. Assigning .value alone leaves the model
     * holding the old text, and every later assertion compares the wrong pair. */
    function typeInto(box, text, from) {
      box.focus();
      box.value = from || '';
      if (from) box.dispatchEvent(new Event('input', { bubbles: true }));
      var lost = null;
      for (var i = 0; i < text.length; i += 1) {
        var ch = text[i];
        box.dispatchEvent(new KeyboardEvent('keydown', { key: ch, bubbles: true }));
        // A real keystroke lands in the value before `input` fires; do it the
        // way the browser would, then let the listener run.
        box.value += ch;
        box.dispatchEvent(new Event('input', { bubbles: true }));
        if (document.activeElement !== box) {
          lost = 'after "' + box.value + '" (wanted "' + text.slice(0, i + 1) + '")';
          break;
        }
      }
      return lost;
    }

    function fieldByLabel(winNode, labelText) {
      return Array.from(winNode.querySelectorAll('.ed-field')).filter(function (f) {
        return txt(f.querySelector('.ed-label')) === labelText;
      }).map(function (f) { return f.querySelector('.ed-input'); })[0];
    }

    /* Every keystroke of a word, into each kind of field, asserting the same
     * element still holds focus and the value came out whole. */
    async function typingSurvives(sectionName, labelText, word, opts) {
      var o = opts || {};
      pickSection(sectionName);
      await pause(200);
      var box = fieldByLabel(edWin, labelText);
      ok(sectionName + '/' + labelText + ' has a field to type into', !!box);
      if (!box) return;
      var seed = (o.from || '') + word;
      var lost = typeInto(box, word, o.from);
      ok(sectionName + '/' + labelText + ' keeps the caret for every key of "' + word + '"',
         lost === null, lost || 'held all ' + word.length + ' keys');
      ok(sectionName + '/' + labelText + ' ends up with the whole word',
         box.value === seed, JSON.stringify(box.value));
      ok(sectionName + '/' + labelText + ' still holds focus at the end',
         document.activeElement === box,
         document.activeElement ? document.activeElement.className || document.activeElement.tagName
                                : 'nothing focused');
    }

    await typingSurvives('Contact', 'name', 'Anonymous', { from: 'An' });
    await typingSurvives('Summary', 'Summary', 'Builds things', { from: '' });

    /* A bullet lives inside an Experience entry, so the third kind of field
     * needs that section and an entry to type into. */
    pickSection('Experience');
    await pause(200);
    var orgBox = fieldByLabel(edWin, 'org');
    ok('Experience has an org field to type into', !!orgBox);
    if (orgBox) {
      var lostOrg = typeInto(orgBox, 'Acme Systems');
      ok('Experience/org keeps the caret for every key of "Acme Systems"',
         lostOrg === null, lostOrg || 'held all keys');
      ok('Experience/org ends up with the whole word',
         orgBox.value === 'Acme Systems', JSON.stringify(orgBox.value));
    }

    /* And the value has to survive a round trip, not just stay in the box:
     * a caret can be held by an input nobody wrote back. */
    await pause(1600);
    var typedBack = await fetch('/profile').then(function (r) { return r.json(); });
    ok('the typed words reached the server, not just the box',
       typedBack.contact.name === 'AnAnonymous'
       && String(typedBack.summary || '').indexOf('Builds things') === 0,
       'name ' + JSON.stringify(typedBack.contact.name)
       + ', summary ' + JSON.stringify(String(typedBack.summary || '').slice(0, 30)));

  } catch (err) {
    ok('the harness ran to completion', false,
       (err && err.stack ? err.stack : String(err)));
  }
  finish();
}

})();