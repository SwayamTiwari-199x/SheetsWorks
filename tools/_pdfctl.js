/* Builds a minimal, known-good PDF and hands it to an iframe as a data: URL.
 *
 * No application code, no server, no blob: deliberately the simplest thing that
 * could possibly display a PDF. If this screenshots black too, then black
 * screenshots say nothing about the app's preview.
 */
(function () {
  'use strict';
  var parts = [];
  function obj(n, body) { parts.push(n + ' 0 obj\n' + body + '\nendobj\n'); }

  var text = 'BT /F1 24 Tf 30 120 Td (HELLO PDF) Tj ET\n';
  obj(1, '<< /Type /Catalog /Pages 2 0 R >>');
  obj(2, '<< /Type /Pages /Kids [3 0 R] /Count 1 >>');
  obj(3, '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] '
       + '/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>');
  obj(4, '<< /Length ' + text.length + ' >>\nstream\n' + text + 'endstream');
  obj(5, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');

  var pdf = '%PDF-1.4\n' + parts.join('') + 'trailer\n<< /Root 1 0 R >>\n';
  // The xref table is optional for a viewer this simple; most tolerate its
  // absence, and if one does not, that is itself a useful finding.
  var b64 = btoa(unescape(encodeURIComponent(pdf)));

  document.getElementById('v').textContent = String(navigator.pdfViewerEnabled);
  document.getElementById('f').src = 'data:application/pdf;base64,' + b64;
})();
