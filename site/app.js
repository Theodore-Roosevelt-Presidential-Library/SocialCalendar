/* Social Calendar - Theodore Roosevelt Presidential Library
   Reads site/data/calendar.json (written twice daily by the GitHub Action)
   and renders it as a month grid or an agenda, with per-network post previews. */

(() => {
  'use strict';

  // ---------------------------------------------------------------- config

  // Everything is stored UTC; we render in the viewer's own zone and say so,
  // rather than guessing between Medora (Mountain) and Bismarck (Central).
  const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone;

  const NETWORKS = {
    TWITTER:           { label: 'X',          color: '#0f1419', handle: '@', layout: 'feed' },
    X:                 { label: 'X',          color: '#0f1419', handle: '@', layout: 'feed' },
    FACEBOOK:          { label: 'Facebook',   color: '#1877f2', handle: '',  layout: 'feed' },
    FACEBOOKPAGE:      { label: 'Facebook',   color: '#1877f2', handle: '',  layout: 'feed' },
    FACEBOOKGROUP:     { label: 'Facebook',   color: '#1877f2', handle: '',  layout: 'feed' },
    INSTAGRAM:         { label: 'Instagram',  color: '#c13584', handle: '@', layout: 'ig' },
    INSTAGRAMBUSINESS: { label: 'Instagram',  color: '#c13584', handle: '@', layout: 'ig' },
    LINKEDIN:          { label: 'LinkedIn',   color: '#0a66c2', handle: '',  layout: 'feed' },
    LINKEDINCOMPANY:   { label: 'LinkedIn',   color: '#0a66c2', handle: '',  layout: 'feed' },
    YOUTUBE:           { label: 'YouTube',    color: '#ff0000', handle: '',  layout: 'tall' },
    YOUTUBECHANNEL:    { label: 'YouTube',    color: '#ff0000', handle: '',  layout: 'tall' },
    TIKTOK:            { label: 'TikTok',     color: '#010101', handle: '@', layout: 'tall' },
    TIKTOKBUSINESS:    { label: 'TikTok',     color: '#010101', handle: '@', layout: 'tall' },
    PINTEREST:         { label: 'Pinterest',  color: '#bd081c', handle: '',  layout: 'tall' },
    THREADS:           { label: 'Threads',    color: '#101010', handle: '@', layout: 'feed' },
    BLUESKY:           { label: 'Bluesky',    color: '#0085ff', handle: '@', layout: 'feed' },
    OTHER:             { label: 'Social',     color: '#877b6c', handle: '',  layout: 'feed' }
  };

  const ICONS = {
    X: '<path d="M13.7 10.6 20.4 3h-1.6l-5.8 6.6L8.3 3H3l7 10-7 8h1.6l6.1-7 4.9 7H21l-7.3-10.4Zm-2.2 2.5-.7-1L5.2 4.2h2.4l4.5 6.5.7 1 5.9 8.4h-2.4l-4.8-6.9Z"/>',
    Facebook: '<path d="M22 12a10 10 0 1 0-11.6 9.9v-7H7.9V12h2.5V9.8c0-2.5 1.5-3.9 3.7-3.9 1.1 0 2.2.2 2.2.2v2.4h-1.2c-1.2 0-1.6.8-1.6 1.6V12h2.7l-.4 2.9h-2.3v7A10 10 0 0 0 22 12Z"/>',
    Instagram: '<path d="M12 2.2c3.2 0 3.6 0 4.9.1 1.2.1 1.8.3 2.2.4.6.2 1 .5 1.4.9.4.4.7.8.9 1.4.2.4.4 1 .4 2.2.1 1.3.1 1.7.1 4.9s0 3.6-.1 4.9c-.1 1.2-.3 1.8-.4 2.2-.2.6-.5 1-.9 1.4-.4.4-.8.7-1.4.9-.4.2-1 .4-2.2.4-1.3.1-1.7.1-4.9.1s-3.6 0-4.9-.1c-1.2-.1-1.8-.3-2.2-.4-.6-.2-1-.5-1.4-.9-.4-.4-.7-.8-.9-1.4-.2-.4-.4-1-.4-2.2C2.2 15.6 2.2 15.2 2.2 12s0-3.6.1-4.9c.1-1.2.3-1.8.4-2.2.2-.6.5-1 .9-1.4.4-.4.8-.7 1.4-.9.4-.2 1-.4 2.2-.4C8.4 2.2 8.8 2.2 12 2.2Zm0 5.1a4.7 4.7 0 1 0 0 9.4 4.7 4.7 0 0 0 0-9.4Zm0 7.7a3 3 0 1 1 0-6 3 3 0 0 1 0 6Zm6-7.9a1.1 1.1 0 1 1-2.2 0 1.1 1.1 0 0 1 2.2 0Z"/>',
    LinkedIn: '<path d="M20.4 3H3.6C3.3 3 3 3.3 3 3.6v16.8c0 .3.3.6.6.6h16.8c.3 0 .6-.3.6-.6V3.6c0-.3-.3-.6-.6-.6ZM8.3 18.3H5.6V9.7h2.7v8.6ZM7 8.5A1.6 1.6 0 1 1 7 5.3a1.6 1.6 0 0 1 0 3.2Zm11.4 9.8h-2.7v-4.2c0-1 0-2.3-1.4-2.3s-1.6 1.1-1.6 2.2v4.3H9.9V9.7h2.6v1.2h.1c.4-.7 1.3-1.4 2.6-1.4 2.7 0 3.2 1.8 3.2 4.1v4.7Z"/>',
    YouTube: '<path d="M21.6 7.2s-.2-1.4-.8-2c-.7-.8-1.5-.8-1.9-.8C16.1 4.2 12 4.2 12 4.2s-4.1 0-6.9.2c-.4 0-1.2 0-1.9.8-.6.6-.8 2-.8 2S2.2 8.8 2.2 10.5v1.6c0 1.6.2 3.3.2 3.3s.2 1.4.8 2c.7.8 1.7.7 2.1.8 1.6.1 6.7.2 6.7.2s4.1 0 6.9-.2c.4-.1 1.2-.1 1.9-.8.6-.6.8-2 .8-2s.2-1.6.2-3.3v-1.6c0-1.6-.2-3.3-.2-3.3ZM9.9 14V8.6l5.3 2.7-5.3 2.7Z"/>',
    TikTok: '<path d="M16.6 2h-3v13.1a2.6 2.6 0 1 1-2.6-2.6c.2 0 .5 0 .7.1V9.5a5.7 5.7 0 1 0 4.9 5.6V8.5a6.4 6.4 0 0 0 3.9 1.3V6.7a3.5 3.5 0 0 1-3.9-3.4V2Z"/>',
    Pinterest: '<path d="M12 2a10 10 0 0 0-3.6 19.3c-.1-.8-.2-2 0-2.9l1.2-5.1s-.3-.6-.3-1.5c0-1.4.8-2.5 1.8-2.5.9 0 1.3.6 1.3 1.4 0 .9-.6 2.2-.9 3.4-.2 1 .5 1.9 1.6 1.9 1.9 0 3.3-2 3.3-4.9 0-2.6-1.8-4.4-4.4-4.4-3 0-4.8 2.2-4.8 4.6 0 .9.3 1.9.8 2.4.1.1.1.2.1.3l-.3 1.1c0 .2-.2.2-.3.1-1.3-.6-2.1-2.5-2.1-4 0-3.3 2.4-6.3 6.9-6.3 3.6 0 6.4 2.6 6.4 6 0 3.6-2.2 6.5-5.4 6.5-1 0-2-.5-2.4-1.2l-.6 2.5c-.2.9-.8 2-1.2 2.7A10 10 0 1 0 12 2Z"/>',
    Threads: '<path d="M16.5 11.2a7 7 0 0 0-.3-.1c-.2-3.3-2-5.2-5-5.2-1.9 0-3.4.8-4.4 2.2l1.7 1.2c.7-1.1 1.8-1.3 2.7-1.3 1 0 1.8.3 2.3.9.4.4.6 1 .7 1.7a12 12 0 0 0-2.7-.1c-2.7.2-4.5 1.7-4.4 3.9 0 1.1.6 2 1.5 2.7.8.5 1.9.8 3 .7 1.5-.1 2.6-.6 3.4-1.7.6-.8 1-1.8 1.2-3 .7.4 1.2.9 1.5 1.6.5 1.1.5 3-1 4.5-1.3 1.3-2.9 1.9-5.3 1.9-2.7 0-4.7-.9-6-2.6C4.2 17 3.6 15 3.6 12.4c0-2.6.6-4.6 1.8-6.1 1.3-1.7 3.3-2.6 6-2.6 2.7 0 4.8.9 6.1 2.6.6.9 1.1 1.9 1.4 3.2l2-.5c-.4-1.6-1-3-1.8-4-1.7-2.2-4.3-3.4-7.6-3.4S5.5 2.8 3.8 5C2.3 7 1.5 9.4 1.5 12.4s.8 5.5 2.3 7.4c1.7 2.2 4.2 3.3 7.5 3.3 2.9 0 5-.8 6.8-2.5 2.3-2.3 2.2-5.2 1.4-7-.5-1.2-1.6-2.1-3-2.7Zm-4.8 4.9c-1.2.1-2.5-.5-2.6-1.6-.1-.9.6-1.8 2.6-1.9h.6c.7 0 1.3.1 1.9.2-.2 2.6-1.5 3.2-2.5 3.3Z"/>',
    Bluesky: '<path d="M6 4.3C8.6 6.3 11.4 10.2 12 12.4c.6-2.2 3.4-6.1 6-8.1 1.9-1.4 5-2.5 5 1.1 0 .7-.4 6-.7 6.8-.8 3-3.9 3.8-6.6 3.3 4.7.8 5.9 3.5 3.3 6.1-5 5-7.2-1.2-7.7-2.8l-.3-.9-.3.9c-.6 1.6-2.7 7.8-7.7 2.8-2.6-2.6-1.4-5.3 3.3-6.1-2.7.5-5.8-.3-6.6-3.3C1.4 11.4 1 6.1 1 5.4c0-3.6 3.1-2.5 5-1.1Z"/>',
    Social: '<path d="M18 8a3 3 0 1 0-2.8-4H15L8.9 9.6A3 3 0 1 0 9 14.5l6.2 3.6a3 3 0 1 0 1-1.7l-6.1-3.6a3 3 0 0 0 0-1.5l6.2-3.7c.5.3 1.1.4 1.7.4Z"/>'
  };

  const STATUS_LABELS = {
    SCHEDULED: 'Scheduled',
    SENT: 'Published',
    PENDING_APPROVAL: 'Needs approval',
    SUBMITTED: 'Submitted',
    REJECTED: 'Rejected',
    SEND_FAILED_PERMANENTLY: 'Failed',
    DRAFT: 'Draft'
  };

  const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  // ----------------------------------------------------------------- state

  const state = {
    data: null,
    view: 'month',
    cursor: startOfMonth(new Date()),
    channels: new Set(),      // profile ids that are ON
    tags: new Set(),          // empty means "no tag filter"
    statuses: new Set(),      // empty means "all statuses"
    query: '',
    expandedDays: new Set()
  };

  const el = (id) => document.getElementById(id);

  // ------------------------------------------------------------- utilities

  function startOfMonth(d) { return new Date(d.getFullYear(), d.getMonth(), 1); }
  function addMonths(d, n) { return new Date(d.getFullYear(), d.getMonth() + n, 1); }
  function addDays(d, n) { const c = new Date(d); c.setDate(c.getDate() + n); return c; }
  function dayKey(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }
  function sameDay(a, b) { return dayKey(a) === dayKey(b); }

  const fmtTime = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' });
  const fmtDateLong = new Intl.DateTimeFormat(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
  const fmtDateTimeFull = new Intl.DateTimeFormat(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short'
  });
  const fmtMonth = new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' });

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function linkify(text) {
    // Highlight hashtags and @mentions the way the networks do. Everything is
    // escaped first so post copy can never inject markup.
    return esc(text).replace(/(^|\s)([#@][\w.\-]+)/g,
      (_m, pre, tok) => `${pre}<span class="tagtok">${tok}</span>`);
  }

  function netInfo(network) {
    return NETWORKS[(network || 'OTHER').toUpperCase()] || NETWORKS.OTHER;
  }

  function profileOf(post) {
    return state.data.profiles.find((p) => p.id === post.profileId) || {
      id: post.profileId, name: 'Unknown profile', network: 'OTHER'
    };
  }

  function durationLabel(sec) {
    if (!sec) return null;
    const s = Math.round(sec);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  // -------------------------------------------------------------- filtering

  function visiblePosts() {
    const q = state.query.trim().toLowerCase();
    return state.data.posts.filter((p) => {
      if (state.channels.size && !state.channels.has(p.profileId)) return false;
      if (state.statuses.size && !state.statuses.has(p.state)) return false;
      if (state.tags.size && !(p.tags || []).some((t) => state.tags.has(t))) return false;
      if (q && !(p.text || '').toLowerCase().includes(q)) return false;
      return true;
    });
  }

  function groupByDay(posts) {
    const map = new Map();
    for (const p of posts) {
      if (!p.scheduledAt) continue;
      const k = dayKey(new Date(p.scheduledAt));
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(p);
    }
    for (const list of map.values()) {
      list.sort((a, b) => new Date(a.scheduledAt) - new Date(b.scheduledAt));
    }
    return map;
  }

  function activeFilterCount() {
    let n = 0;
    if (state.channels.size && state.channels.size !== state.data.profiles.length) n++;
    if (state.tags.size) n++;
    if (state.statuses.size) n++;
    if (state.query.trim()) n++;
    return n;
  }

  // -------------------------------------------------------- post rendering

  function mediaBlock(post, layout, full) {
    const all = post.media || [];
    if (!all.length) return '';

    // Cards get at most four tiles so a 20-image carousel cannot swamp the
    // grid; the modal shows every attachment, in order.
    const media = full ? all : all.slice(0, 4);
    const hidden = all.length - media.length;

    const figs = media.map((m, i) => {
      const src = m.remote ? m.src : `data/${m.src}`;
      const dur = durationLabel(m.durationSec);
      const overlay = (!full && hidden && i === media.length - 1)
        ? `<div class="play more-media"><span>+${hidden}</span></div>` : '';
      return `<figure>
        <img src="${esc(src)}" alt="${esc(m.altText || '')}" loading="lazy" decoding="async">
        ${m.kind === 'video' ? '<div class="play"><span>▶</span></div>' : ''}
        ${dur ? `<span class="dur">${esc(dur)}</span>` : ''}
        ${full && all.length > 1 ? `<span class="idx">${i + 1} / ${all.length}</span>` : ''}
        ${overlay}
      </figure>`;
    }).join('');

    const cls = full ? 'net-media is-full' : `net-media n${media.length}`;
    return `<div class="${cls}" data-layout="${layout}">${figs}</div>`;
  }

  function previewHTML(post, { full = false } = {}) {
    const prof = profileOf(post);
    const info = netInfo(prof.network);
    const icon = ICONS[info.label] || ICONS.Social;
    const initials = (prof.name || '?').replace(/[^A-Za-z0-9 ]/g, '').trim()
      .split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?';

    const when = post.scheduledAt ? new Date(post.scheduledAt) : null;
    const media = mediaBlock(post, info.layout, full);
    const text = post.text
      ? `<div class="net-text">${linkify(full ? post.text : truncate(post.text, 260))}</div>`
      : '';

    const tags = (post.tags || []).length
      ? `<div class="net-tags">${post.tags.map((t) => `<span class="tagchip">${esc(t)}</span>`).join('')}</div>`
      : '';

    const head = `<div class="net-head">
      <div class="net-av" style="background:${info.color}">${esc(initials)}</div>
      <div>
        <div class="net-name">${esc(prof.name)}</div>
        <div class="net-handle">${esc(info.handle)}${esc(handleOf(prof))} · ${esc(info.label)}</div>
      </div>
      <span class="net-icon" style="color:${info.color}" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="currentColor">${icon}</svg>
      </span>
    </div>`;

    // Instagram leads with the image and puts the caption underneath.
    const body = info.layout === 'ig'
      ? head + media + text + tags
      : head + text + media + tags;

    const layoutClass = info.layout === 'ig' ? 'ig' : (info.layout === 'tall' ? 'tall' : '');

    return `
      <div class="post-meta">
        <span class="when">${when ? esc(fmtTime.format(when)) : 'Unscheduled'}</span>
        <span>${when ? esc(fmtDateLong.format(when)) : ''}</span>
        <span class="status">
          <span class="status-tag s-${esc(post.state)}">${esc(STATUS_LABELS[post.state] || post.state)}</span>
        </span>
      </div>
      <div class="net ${layoutClass}">${body}</div>`;
  }

  function handleOf(prof) {
    if (!prof.url) return prof.name;
    try {
      const path = new URL(prof.url).pathname.replace(/^\/+|\/+$/g, '');
      return path.split('/').pop() || prof.name;
    } catch { return prof.name; }
  }

  function truncate(s, n) {
    return s.length > n ? s.slice(0, n).replace(/\s+\S*$/, '') + '…' : s;
  }

  // -------------------------------------------------------------- rendering

  function render() {
    const posts = visiblePosts();
    el('resultCount').textContent =
      `${posts.length} post${posts.length === 1 ? '' : 's'} match${posts.length === 1 ? 'es' : ''} your filters`;

    const count = activeFilterCount();
    const badge = el('filterCount');
    badge.hidden = count === 0;
    badge.textContent = count;

    if (state.view === 'month') renderMonth(posts);
    else renderAgenda(posts);

    syncChips();
  }

  function renderMonth(posts) {
    const byDay = groupByDay(posts);
    const first = state.cursor;
    const gridStart = addDays(first, -first.getDay());
    const today = new Date();

    el('periodLabel').textContent = fmtMonth.format(first);

    let html = '<div class="monthgrid">';
    for (const d of DOW) html += `<div class="dow">${d}</div>`;

    // Whole weeks only - 35 cells when the month fits in five rows, 42 when it
    // does not. Breaking out mid-week would leave a ragged final row.
    const daysInMonth = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
    const cells = Math.ceil((first.getDay() + daysInMonth) / 7) * 7;

    for (let i = 0; i < cells; i++) {
      const day = addDays(gridStart, i);
      const k = dayKey(day);
      const list = byDay.get(k) || [];
      const outside = day.getMonth() !== first.getMonth();
      const weekend = day.getDay() === 0 || day.getDay() === 6;
      const expanded = state.expandedDays.has(k);
      const shown = expanded ? list : list.slice(0, 3);

      const cls = ['day'];
      if (outside) cls.push('is-outside');
      if (weekend) cls.push('is-weekend');
      if (sameDay(day, today)) cls.push('is-today');

      html += `<div class="${cls.join(' ')}"><span class="daynum">${day.getDate()}</span>`;
      for (const p of shown) {
        const prof = profileOf(p);
        const info = netInfo(prof.network);
        const thumb = (p.media || [])[0];
        const src = thumb ? (thumb.remote ? thumb.src : `data/${thumb.src}`) : null;
        html += `<button class="evt ${p.state === 'SENT' ? 'is-sent' : ''}"
            style="border-left-color:${info.color}" data-post="${esc(p.id)}"
            title="${esc(truncate(p.text || '', 140))}">
          ${src ? `<img class="thumb" src="${esc(src)}" alt="" loading="lazy">` : ''}
          <span class="t">${esc(fmtTime.format(new Date(p.scheduledAt)).replace(':00', ''))}</span>
          <span class="x">${esc(truncate(p.text || info.label, 60))}</span>
        </button>`;
      }
      if (list.length > shown.length) {
        html += `<button class="more" data-expand="${k}">+${list.length - shown.length} more</button>`;
      } else if (expanded && list.length > 3) {
        html += `<button class="more" data-expand="${k}">Show less</button>`;
      }
      html += '</div>';
    }
    html += '</div>';

    el('main').innerHTML = html;
  }

  function renderAgenda(posts) {
    const today = new Date();
    // The agenda ignores the month cursor: it is a forward-running list from
    // today, which is how people actually use it.
    const upcoming = posts
      .filter((p) => p.scheduledAt && new Date(p.scheduledAt) >= addDays(today, -1))
      .sort((a, b) => new Date(a.scheduledAt) - new Date(b.scheduledAt));

    el('periodLabel').textContent = 'Upcoming';

    if (!upcoming.length) {
      el('main').innerHTML = emptyState('Nothing upcoming matches these filters.');
      return;
    }

    const byDay = groupByDay(upcoming);
    let html = '<div class="agenda">';
    for (const [k, list] of byDay) {
      const d = new Date(list[0].scheduledAt);
      const isToday = sameDay(d, today);
      const isTomorrow = sameDay(d, addDays(today, 1));
      html += `<section class="agenda-day">
        <div class="agenda-date ${isToday ? 'is-today' : ''}">
          <div class="dnum">${d.getDate()}</div>
          <div class="dname">${esc(new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short' }).format(d))}</div>
          ${isToday ? '<div class="badge">Today</div>' : isTomorrow ? '<div class="badge">Tomorrow</div>' : ''}
        </div>
        <div class="agenda-posts">
          ${list.map((p) => `<button class="post" data-post="${esc(p.id)}">${previewHTML(p)}</button>`).join('')}
        </div>
      </section>`;
      void k;
    }
    html += '</div>';
    el('main').innerHTML = html;
  }

  function emptyState(msg) {
    return `<div class="state"><h3>${esc(msg)}</h3>
      <p>Try clearing filters, or check a different month.</p></div>`;
  }

  // ------------------------------------------------------------------ modal

  function openModal(postId) {
    const post = state.data.posts.find((p) => p.id === postId);
    if (!post) return;
    const prof = profileOf(post);
    const when = post.scheduledAt ? new Date(post.scheduledAt) : null;

    const rows = [
      ['Channel', `${esc(prof.name)} · ${esc(netInfo(prof.network).label)}`],
      ['When', when ? esc(fmtDateTimeFull.format(when)) : 'Unscheduled'],
      ['Status', esc(STATUS_LABELS[post.state] || post.state)]
    ];
    if ((post.media || []).length) {
      const vids = post.media.filter((m) => m.kind === 'video').length;
      rows.push(['Attachments', `${post.media.length}` +
        (vids ? ` (${vids} video${vids === 1 ? '' : 's'})` : '')]);
    }
    if ((post.tags || []).length) rows.push(['Tags', esc(post.tags.join(', '))]);
    if (post.postUrl) rows.push(['Live post', `<a href="${esc(post.postUrl)}" target="_blank" rel="noopener">Open ↗</a>`]);
    if (post.text) rows.push(['Characters', String(post.text.length)]);

    el('modalBody').innerHTML =
      `<div class="post" id="modalTitle">${previewHTML(post, { full: true })}</div>
       <dl class="modal-extra">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>`;

    el('modal').hidden = false;
    document.body.style.overflow = 'hidden';
    el('modal').querySelector('.modal-close').focus();
  }

  function closeModal() {
    el('modal').hidden = true;
    document.body.style.overflow = '';
  }

  // ----------------------------------------------------------------- chips

  function buildChips() {
    const posts = state.data.posts;

    el('channelList').innerHTML = state.data.profiles.map((p) => {
      const info = netInfo(p.network);
      const n = posts.filter((x) => x.profileId === p.id).length;
      return `<button class="chip" data-channel="${esc(p.id)}">
        <span class="swatch" style="background:${info.color}"></span>
        ${esc(p.name)} <span class="n">${n}</span>
      </button>`;
    }).join('');

    const tags = state.data.tags || [];
    el('tagBlock').hidden = tags.length === 0;
    el('tagList').innerHTML = tags.map((t) => {
      const n = posts.filter((x) => (x.tags || []).includes(t)).length;
      return `<button class="chip" data-tag="${esc(t)}">${esc(t)} <span class="n">${n}</span></button>`;
    }).join('');

    const statuses = [...new Set(posts.map((p) => p.state))].sort();
    el('statusList').innerHTML = statuses.map((s) => {
      const n = posts.filter((x) => x.state === s).length;
      return `<button class="chip" data-status="${esc(s)}">
        ${esc(STATUS_LABELS[s] || s)} <span class="n">${n}</span>
      </button>`;
    }).join('');
  }

  function syncChips() {
    document.querySelectorAll('[data-channel]').forEach((b) =>
      b.classList.toggle('on', state.channels.has(b.dataset.channel)));
    document.querySelectorAll('[data-tag]').forEach((b) =>
      b.classList.toggle('on', state.tags.has(b.dataset.tag)));
    document.querySelectorAll('[data-status]').forEach((b) =>
      b.classList.toggle('on', state.statuses.has(b.dataset.status)));
  }

  // ----------------------------------------------------------------- events

  function wire() {
    document.querySelectorAll('.viewswitch button').forEach((b) => {
      b.addEventListener('click', () => {
        state.view = b.dataset.view;
        document.querySelectorAll('.viewswitch button').forEach((x) => {
          const on = x === b;
          x.classList.toggle('is-active', on);
          x.setAttribute('aria-selected', String(on));
        });
        render();
      });
    });

    el('filterToggle').addEventListener('click', () => {
      const f = el('filters');
      f.hidden = !f.hidden;
      el('filterToggle').setAttribute('aria-expanded', String(!f.hidden));
    });

    el('prev').addEventListener('click', () => { state.cursor = addMonths(state.cursor, -1); render(); });
    el('next').addEventListener('click', () => { state.cursor = addMonths(state.cursor, 1); render(); });
    el('today').addEventListener('click', () => { state.cursor = startOfMonth(new Date()); render(); });

    let t;
    el('search').addEventListener('input', (e) => {
      clearTimeout(t);
      t = setTimeout(() => { state.query = e.target.value; render(); }, 160);
    });

    document.addEventListener('click', (e) => {
      const ch = e.target.closest('[data-channel]');
      if (ch) { toggle(state.channels, ch.dataset.channel); return render(); }

      const tg = e.target.closest('[data-tag]');
      if (tg) { toggle(state.tags, tg.dataset.tag); return render(); }

      const st = e.target.closest('[data-status]');
      if (st) { toggle(state.statuses, st.dataset.status); return render(); }

      const bulk = e.target.closest('[data-channels]');
      if (bulk) {
        state.channels.clear();
        if (bulk.dataset.channels === 'all') {
          state.data.profiles.forEach((p) => state.channels.add(p.id));
        }
        return render();
      }

      const exp = e.target.closest('[data-expand]');
      if (exp) {
        toggle(state.expandedDays, exp.dataset.expand);
        return render();
      }

      const post = e.target.closest('[data-post]');
      if (post) return openModal(post.dataset.post);

      if (e.target.closest('[data-close]')) return closeModal();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !el('modal').hidden) closeModal();
      if (el('modal').hidden && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) {
        if (e.key === 'ArrowLeft') el('prev').click();
        if (e.key === 'ArrowRight') el('next').click();
      }
    });
  }

  function toggle(set, v) { set.has(v) ? set.delete(v) : set.add(v); }

  // ------------------------------------------------------------------- boot

  async function boot() {
    wire();
    try {
      const resp = await fetch(`data/calendar.json?v=${Date.now()}`, { cache: 'no-store' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      state.data = await resp.json();
    } catch (err) {
      el('main').innerHTML = `<div class="state">
        <h3>No schedule data yet</h3>
        <p>The build has not produced <code>data/calendar.json</code>.<br>
        Run the <strong>Refresh social calendar</strong> workflow in GitHub Actions,
        or see <code>SETUP.md</code> for the one-time Hootsuite credentials.</p>
        <p style="opacity:.6">(${esc(err.message)})</p></div>`;
      el('freshness').textContent = 'No data';
      return;
    }

    state.data.posts = state.data.posts || [];
    state.data.profiles = state.data.profiles || [];

    buildChips();

    const gen = state.data.generatedAt ? new Date(state.data.generatedAt) : null;
    el('freshness').textContent = gen
      ? `Updated ${fmtDateTimeFull.format(gen)} · times shown in ${TZ}`
      : `Times shown in ${TZ}`;

    // Land on the month with the nearest upcoming post, so an empty current
    // month does not look like a broken page.
    const now = new Date();
    const next = state.data.posts
      .filter((p) => p.scheduledAt && new Date(p.scheduledAt) >= now)
      .sort((a, b) => new Date(a.scheduledAt) - new Date(b.scheduledAt))[0];
    state.cursor = startOfMonth(next ? new Date(next.scheduledAt) : now);

    render();
  }

  boot();
})();
