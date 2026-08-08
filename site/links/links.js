/* Link-in-bio feed.

   The GitHub Action only rebuilds twice a day, so links.json ships with future
   posts already in it and this script holds them back until their send time.
   That way a story appears on the page the moment it goes live on the channel,
   not up to twelve hours later. */

(() => {
  'use strict';

  const FEED = document.getElementById('feed');
  const STAMP = document.getElementById('stamp');
  const NEW_FOR_HOURS = 48;      // how long a card wears the "new" flag
  const TICK_MS = 30_000;        // safety net if a timer is throttled

  let items = [];
  let data = {};
  let timers = [];

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const ms = (iso) => new Date(iso).getTime();

  function relative(iso) {
    const diff = Date.now() - ms(iso);
    const mins = Math.round(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.round(hrs / 24);
    if (days < 7) return `${days}d ago`;
    return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' })
      .format(new Date(iso));
  }

  function cardHTML(item) {
    const fresh = Date.now() - ms(item.publishAt) < NEW_FOR_HOURS * 3600_000;
    const thumb = item.thumb
      ? `<img class="shot" src="../data/${esc(item.thumb.src)}" alt="" loading="lazy" decoding="async">`
      : '';

    return `<a class="card ${item.thumb ? '' : 'no-thumb'}"
        href="${esc(item.url)}" target="_blank" rel="noopener">
      ${thumb}
      <span class="body">
        <span class="headline">${esc(item.headline)}</span>
        ${item.blurb ? `<span class="blurb">${esc(item.blurb)}</span>` : ''}
        <span class="meta">
          ${fresh ? '<span class="isnew">New</span>' : ''}
          <span class="host">${esc(item.host)}</span>
          <span class="sep">·</span>
          <span>${esc(relative(item.publishAt))}</span>
        </span>
      </span>
    </a>`;
  }

  function render() {
    const now = Date.now();
    const live = items
      .filter((i) => ms(i.publishAt) <= now)
      .sort((a, b) => ms(b.publishAt) - ms(a.publishAt));

    FEED.innerHTML = live.length
      ? live.map(cardHTML).join('')
      : '<p class="empty">Nothing here just yet — check back shortly.</p>';

    scheduleReveals();
  }

  function scheduleReveals() {
    timers.forEach(clearTimeout);
    timers = [];
    const now = Date.now();

    for (const item of items) {
      const due = ms(item.publishAt) - now;
      // setTimeout saturates past ~24.8 days; anything beyond that will have
      // been picked up by a rebuild long before it matters.
      if (due > 0 && due < 2_000_000_000) {
        timers.push(setTimeout(render, due + 1500));
      }
    }
  }

  async function boot() {
    try {
      const resp = await fetch(`../data/links.json?v=${Date.now()}`, { cache: 'no-store' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      data = await resp.json();
      items = (data.items || []).filter((i) => i.url && i.publishAt);
    } catch (err) {
      FEED.innerHTML = '<p class="empty">Could not load the latest posts.</p>';
      console.error(err);
      return;
    }

    render();

    // Deliberately does not advertise how many posts are queued. This page is
    // public, so there is no reason to draw attention to unpublished work.
    if (STAMP && data.generatedAt) {
      STAMP.textContent = 'Updated ' + new Intl.DateTimeFormat(undefined, {
        month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
      }).format(new Date(data.generatedAt));
    }

    // Backstop for phones that suspend timers in a background tab.
    setInterval(render, TICK_MS);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) render();
    });
  }

  boot();
})();
