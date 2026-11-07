// Service-worker registration, kept out of line so a Content-Security-Policy with
// `script-src 'self'` cannot block it (FLEET.md, PWA standard). An inline registration is
// blocked by such a policy and, because registration swallows its errors, the PWA stops
// with no visible error: artbypriti #26 found exactly that.
//
// Behaviour is unchanged from the inline version it replaces: it never registers on
// localhost, so `hugo server` is not shadowed by a stale worker (e2e asserts this).
(function () {
  if (!('serviceWorker' in navigator)) return;
  var h = location.hostname;
  if (h === 'localhost' || h === '127.0.0.1' || h === '[::1]') return;
  var tag = document.currentScript || document.querySelector('script[data-sw-url]');
  var url = tag && tag.dataset.swUrl;
  if (!url) return;
  window.addEventListener('load', function () {
    navigator.serviceWorker.register(url, { scope: '/' })
      .catch(function (err) { console.warn('[sw] registration failed', err); });
  });
})();
