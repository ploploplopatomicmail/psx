(() => {
  const $ = s => document.querySelector(s);
  const root = document.body.dataset.root, fuseSrc = document.body.dataset.fuse;
  const grid = $('#grid'), more = $('#more'), pager = $('#pager'), status = $('#status'), input = $('#q');
  const BATCH = 36, original = grid.innerHTML;
  let fuse, loading, hits = [], shown = 0, seq = 0, timer, active = false;

  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const card = v => `<a class="card" href="${root}${esc(v.u)}"><span class="thumb"><img src="${esc(v.i)}" alt="${esc(v.t)}" loading="lazy" decoding="async"><b class="dur">${esc(v.l)}</b></span><span class="t">${esc(v.t)}</span><span class="m">${(v.v || 0).toLocaleString()} views</span></a>`;

  const loadFuse = () => new Promise((ok, fail) => {
    if (window.Fuse) return ok();
    const s = document.createElement('script');
    s.src = fuseSrc; s.onload = ok; s.onerror = fail; document.head.appendChild(s);
  });

  async function readIndex() {
    try {   // gzipped index, decompressed in the browser
      const buf = await (await fetch(root + 'search-index.json.gz')).arrayBuffer();
      const b = new Uint8Array(buf);
      if (b[0] === 0x1f && b[1] === 0x8b) {  // server did not already decode it
        const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'));
        return JSON.parse(await new Response(stream).text());
      }
      return JSON.parse(new TextDecoder().decode(b));
    } catch (e) {   // old browser without DecompressionStream
      return (await fetch(root + 'search-index.json')).json();
    }
  }

  const init = () => loading || (loading = Promise.all([loadFuse(), readIndex()]).then(([, data]) => {
    fuse = new Fuse(data, {
      keys: [{name: 't', weight: .5}, {name: 'g', weight: .3}, {name: 'd', weight: .2}],
      threshold: .3, ignoreLocation: true, minMatchCharLength: 2
    });
  }));

  function renderMore() {
    const slice = hits.slice(shown, shown + BATCH);
    grid.insertAdjacentHTML('beforeend', slice.map(card).join(''));
    shown += slice.length;
    more.hidden = shown >= hits.length;
  }

  async function run(term, push) {
    const my = ++seq;
    term = term.trim();
    if (push) history.replaceState(null, '', term ? `?q=${encodeURIComponent(term)}` : location.pathname);
    if (!term) {
      active = false; grid.innerHTML = original; more.hidden = true; status.hidden = true;
      if (pager) pager.hidden = false;
      return;
    }
    status.hidden = false; status.textContent = 'Searching…';
    await init();
    if (my !== seq) return;               // a newer query superseded this one
    hits = fuse.search(term).map(r => r.item); active = true;
    shown = 0; grid.innerHTML = '';
    if (pager) pager.hidden = true;
    status.textContent = hits.length ? `${hits.length.toLocaleString()} results for “${term}”` : `No results for “${term}”`;
    renderMore();
  }

  input.addEventListener('focus', init, {once: true});   // warm up while the user types
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => run(input.value, true), 180); });
  input.closest('form').addEventListener('submit', e => { e.preventDefault(); clearTimeout(timer); run(input.value, true); });
  more.addEventListener('click', renderMore);

  // remember which list a video was opened from, so next / previous follow that list
  const remember = ev => {
    if (!ev.target.closest('a.card')) return;
    try {
      if (active) sessionStorage.setItem('ctx', JSON.stringify(hits.map(h => h.u)));  // search results
      else sessionStorage.removeItem('ctx');                                          // home = default order
    } catch (err) {}
  };
  grid.addEventListener('click', remember);
  grid.addEventListener('auxclick', remember);

  const initial = new URLSearchParams(location.search).get('q');
  if (initial) { input.value = initial; run(initial, false); }
})();
