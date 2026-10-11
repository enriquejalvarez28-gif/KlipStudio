/* ============================================================
   KLIP — content loader.

   Every word, image and booking id on this site lives in
   /data/content.json and /data/pages.json. Those two files are
   what the admin panel at /admin writes to, which is why nobody
   needs to open a .js file to change the site.

   This loader reads them, hands them to the renderers as
   window.KLIP and window.KLIP_PAGES, then fires 'klip:data'.
   Each page waits for that event before it draws anything.

   NOTE FOR LOCAL PREVIEW: browsers block fetch() on files opened
   with a double-click (file://). To preview the site on your own
   machine, run  npx serve  in this folder and open the address it
   prints. On Cloudflare Pages — and anywhere else it is actually
   hosted — this is a non-issue.
   ============================================================ */
(function () {
  /* Scripts that draw the page register here instead of running on
     sight. They run in the order they registered — the same order
     the <script> tags appear in — once the content has arrived. */
  var queue = [], ready = false;
  window.KLIPREADY = function (fn) {
    if (ready) { fn(); return; }
    queue.push(fn);
  };
  function run() {
    ready = true;
    while (queue.length) {
      try { queue.shift()(); } catch (e) { try { console.error(e); } catch (x) {} }
    }
  }

  var BASE = (function () {
    // works from / and from any sub-path the site is served under
    var s = document.currentScript;
    if (!s) return '';
    var m = s.src.match(/^(.*\/)js\/klip-data\.js/);
    return m ? m[1] : '';
  })();

  /* One file per screen in the editor, so saving one screen can never
     disturb another. They are merged back into a single object here. */
  var PARTS = ['brand', 'navigation', 'hero', 'sections', 'studio',
               'photography', 'photographers', 'podcasts', 'clients',
               'location', 'visibility', 'booking', 'consultation'];

  function get(name) {
    return fetch(BASE + 'data/' + name + '.json', { cache: 'no-cache' })
      .then(function (r) {
        if (!r.ok) throw new Error(name + ' ' + r.status);
        return r.json();
      });
  }

  function fail(err) {
    try { console.error('KLIP content failed to load:', err); } catch (e) {}
    var m = document.querySelector('main');
    if (!m) return;
    m.innerHTML =
      '<section class="sec sec--paper"><div class="wrap" style="padding:120px 0;max-width:46ch">' +
      '<h2>Content Could Not Load<span class="dot">.</span></h2>' +
      '<p class="lede" style="margin-top:18px">The page is fine — the content files did not answer. ' +
      'If you opened this file directly from a folder, run <code>npx serve</code> in that folder ' +
      'and open the address it prints instead.</p></div></section>';
  }

  Promise.all(PARTS.map(get).concat([get('pages'), get('webp').catch(function(){ return null; })]))
    .then(function (r) {
      var webp = r.pop(), pages = r.pop(), content = {};
      window.KLIP_WEBP = webp;
      r.forEach(function (part) {
        for (var k in part) { if (Object.prototype.hasOwnProperty.call(part, k)) content[k] = part[k]; }
      });
      window.KLIP = content;
      window.KLIP_PAGES = pages;
      run();
      document.dispatchEvent(new CustomEvent('klip:data'));
    })
    .catch(fail);
})();
