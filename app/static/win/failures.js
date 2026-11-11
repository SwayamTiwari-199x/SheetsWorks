/* ============================================================================
   failures.js -- turning a failed response into something a person can act on.

   One copy, on purpose. There used to be two: one in app.js for the API helper
   and one in editor.js for the AI dialog. They agreed on the happy path and
   differed everywhere else, so the same 422 read as

       "Value error, 'Jul' is not a date I can read."      (from the editor)

   in one window and as

       "experience entry 1: 'Jul' is not a date I can read."   (from the app)

   in another. Two sentences for one mistake, one of them a JSON path with a
   zero-based index, which is the worst possible thing to hand someone who is
   looking at a form.

   This module is DOM-free so node can drive it: a Response here is any object
   with `status` and `json()`, which is all that is read.
   ========================================================================= */

(function (global) {
'use strict';

/* Pydantic's loc is ["body", "experience", 0, "start"]. Printed as it stands it
   is a JSON path, and a JSON path is not something a person filling in a form
   can act on. Numbers become entry numbers, counted from one, and the tail is
   dropped because the message itself names the field. */
function whereInPlainEnglish(loc) {
  if (!Array.isArray(loc) || loc.length < 2) return '';
  const parts = loc.slice(1).filter(function (p) {
    return typeof p === 'string' && p !== 'body';
  });
  const numbered = loc.slice(1).filter(function (p) { return typeof p === 'number'; });
  const bits = parts.slice(0, -1);
  let where = bits.join(' ');
  for (const n of numbered.slice(0, 1)) {
    where = (where ? where + ' ' : '') + 'entry ' + (n + 1);
  }
  return where ? where + ': ' : '';
}

/* "Value error, 'Jul 2026' is not a date I can read." The prefix adds nothing
   and makes the sentence start lower-case in the middle of a list. */
function say(d) {
  const msg = (d && d.msg) || JSON.stringify(d);
  return String(msg).replace(/^Value error,\s*/, '');
}

/* Every shape the API has answered with, plus the ones it might. The order is
   the order of how much the reader learns: a written message first, the status
   code only as a last resort. It must not throw: this runs in a catch block,
   and a throw here would replace a real explanation with a confusing one. */
async function explainFailure(res) {
  let body = null;
  try {
    body = await res.json();
  } catch (_) {
    /* not json: a proxy page or a gateway timeout. The status is the fact. */
  }
  if (!body || typeof body !== 'object') return 'HTTP ' + res.status;

  const detail = body.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map(function (d) {
      return whereInPlainEnglish(d && d.loc) + say(d);
    }).join('\n');
  }
  if (typeof body.msg === 'string' && body.msg) return body.msg;
  if (detail && typeof detail !== 'object') return String(detail);
  if (Object.keys(body).length) return JSON.stringify(body);
  return 'HTTP ' + res.status;
}

global.Failures = {
  explainFailure: explainFailure,
  whereInPlainEnglish: whereInPlainEnglish,
  say: say,
};

})(typeof window !== 'undefined' ? window : globalThis);