/* Records anything that throws while the app boots.
 *
 * The app has its own error handler, which does the right thing for a user and
 * the wrong thing for a test: it opens a message box. So when boot fails, all
 * this harness can see is "the editor never appeared". Loaded before app.js so
 * it hears the error first. */
(function () {
  'use strict';
  window.__errors = [];
  window.addEventListener('error', function (ev) {
    window.__errors.push((ev.message || 'error')
      + ' @ ' + (ev.filename || '?') + ':' + (ev.lineno || 0));
  });
  window.addEventListener('unhandledrejection', function (ev) {
    const r = ev.reason;
    window.__errors.push('unhandled rejection: '
      + ((r && r.stack) || (r && r.message) || String(r)));
  });
})();