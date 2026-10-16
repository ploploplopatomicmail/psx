(() => {
  const p = document.querySelector('.player'), v = p.querySelector('video');
  let { next, prev } = p.dataset;
  const mute = document.getElementById('mute'), bar = document.getElementById('bar');
  const back = document.getElementById('back');
  let leaving = false;

  // remember whether we arrived from a list / search page of this site
  try {
    let same = false, fromVideo = false;
    if (document.referrer) {
      const u = new URL(document.referrer);
      same = u.origin === location.origin;
      fromVideo = /\/videos\/[^/]+\/?$/.test(u.pathname);
    }
    if (!same) { sessionStorage.setItem('fromList', '0'); sessionStorage.removeItem('ctx'); }
    else if (!fromVideo) sessionStorage.setItem('fromList', '1');
  } catch (e) {}

  // next / previous follow the list the user came from (search results); otherwise newest-first order
  try {
    const list = JSON.parse(sessionStorage.getItem('ctx') || 'null');
    const m = location.pathname.match(/videos\/([^/]+)\/?$/);
    const i = Array.isArray(list) && m ? list.indexOf('videos/' + m[1] + '/') : -1;
    if (i >= 0) {
      const root = document.body.dataset.root || '/';
      next = i + 1 < list.length ? root + list[i + 1] : '';
      prev = i > 0 ? root + list[i - 1] : '';
      document.querySelectorAll('link[rel=prefetch]').forEach(l => l.remove());
      [next, prev].forEach(u => {
        if (!u) return;
        const l = document.createElement('link'); l.rel = 'prefetch'; l.href = u; document.head.appendChild(l);
      });
    }
  } catch (e) {}

  // back to the page we came from (keeps page number / ?q= search / scroll); otherwise home
  function goBack() {
    let ok = false;
    try { ok = sessionStorage.getItem('fromList') === '1' && history.length > 1; } catch (e) {}
    if (ok) history.back(); else location.href = back ? back.href : '/';
  }
  if (back) back.addEventListener('click', e => { e.preventDefault(); goBack(); });

  function go(url, dir) {
    if (!url || leaving) return;
    leaving = true;
    p.classList.add(dir > 0 ? 'out-up' : 'out-down');
    setTimeout(() => { location.replace(url); }, 160);   // replace: swiping through videos does not pile up history
  }
  const goNext = () => go(next, 1), goPrev = () => go(prev, -1);
  addEventListener('pageshow', e => {
    leaving = false; p.classList.remove('out-up', 'out-down');
    if (e.persisted && v.paused) autoplay();     // back button restored the page from cache
  });

  // touch: swipe up -> next video, swipe down -> previous video
  let sx, sy, st, track = false;
  p.addEventListener('touchstart', e => {
    track = e.touches.length === 1 && !e.target.closest('.no-swipe');
    if (track) { sx = e.touches[0].clientX; sy = e.touches[0].clientY; st = Date.now(); }
  }, { passive: true });
  p.addEventListener('touchend', e => {
    if (!track) return; track = false;
    const t = e.changedTouches[0], dx = t.clientX - sx, dy = t.clientY - sy;
    if (Math.abs(dy) > 60 && Math.abs(dy) > Math.abs(dx) * 1.5 && Date.now() - st < 900) {
      dy < 0 ? goNext() : goPrev();
    }
  }, { passive: true });

  // desktop: mouse wheel and keyboard
  let wl = 0;
  addEventListener('wheel', e => {
    if (Math.abs(e.deltaY) < 30 || Date.now() - wl < 800) return;
    wl = Date.now(); e.deltaY > 0 ? goNext() : goPrev();
  }, { passive: true });
  addEventListener('keydown', e => {
    if (e.target.matches('input')) return;
    if (e.key === 'ArrowDown' || e.key === 'j') goNext();
    else if (e.key === 'ArrowUp' || e.key === 'k') goPrev();
    else if (e.key === ' ') { e.preventDefault(); toggle(); }
    else if (e.key === 'm') setMuted(!v.muted);
    else if (e.key === 'Escape') goBack();
  });
  document.getElementById('down').onclick = goNext;
  document.getElementById('up').onclick = goPrev;

  // playback
  const toggle = () => (v.paused ? v.play() : v.pause());
  let skipClick = false;
  p.addEventListener('click', e => { if (!skipClick && !e.target.closest('.no-swipe')) toggle(); });
  v.addEventListener('pause', () => p.classList.add('paused'));
  v.addEventListener('play', () => p.classList.remove('paused'));
  v.addEventListener('timeupdate', () => { bar.firstChild.style.width = (v.currentTime / (v.duration || 1) * 100) + '%'; });
  bar.addEventListener('click', e => { const r = bar.getBoundingClientRect(); v.currentTime = (e.clientX - r.left) / r.width * v.duration; });

  function setMuted(m) {
    v.muted = m; mute.textContent = m ? '🔇' : '🔊';
    try { sessionStorage.setItem('muted', m ? '1' : '0'); } catch (e) {}
  }
  mute.onclick = () => setMuted(!v.muted);
  let wantSound = false;
  try { wantSound = sessionStorage.getItem('muted') === '0'; } catch (e) {}

  // autoplay: try with sound if the viewer unmuted earlier, then muted; if the browser still
  // blocks it, show the play icon and start on the first tap / key press
  async function autoplay() {
    if (wantSound) {                      // viewer unmuted earlier: try with sound first
      try { v.muted = false; await v.play(); setMuted(false); return; } catch (e) {}
    }
    try { v.muted = true; mute.textContent = '🔇'; await v.play(); return; } catch (e) {}
    p.classList.add('paused');            // blocked: show the play icon, start on first interaction
    const kick = () => {
      skipClick = true; setTimeout(() => { skipClick = false; }, 400);
      v.play().catch(() => {});
    };
    ['pointerdown', 'touchstart', 'keydown'].forEach(t => addEventListener(t, kick, { once: true, passive: true }));
  }
  autoplay();
})();
