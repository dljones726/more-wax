// ─────────────────────────────────────────────────────────────────
//  DETAIL MODAL — pure render helpers (HTML-string builders)
//  Split out of detail.js; loaded before it in index.html. All globals.
// ─────────────────────────────────────────────────────────────────

function _renderPanelHtml(r, peek = false) {
  if (!r) return '<div class="detail-panel"></div>';

  const cover = r.local_cover || r.cover_image_url;
  const coverHtml = cover
    ? `<img src="${esc(cover)}" class="w-full max-h-[50vh] object-contain bg-black sm:max-h-[340px]" onerror="this.style.display='none'">`
    : `<div class="w-full h-44 bg-surface-high flex items-center justify-center text-outline-v">
         <i class="bi bi-vinyl text-5xl"></i>
       </div>`;

  const genres = parseList(r.genres);
  const styles = parseList(r.styles);
  const tags = [...new Set([...genres, ...styles])];
  const hasPrices = r.price_median || r.price_high || r.price_low;

  return `<div class="detail-panel">
    ${coverHtml}
    <div class="p-4 pb-2 space-y-4">
      <!-- Title & Artist -->
      <div class="overflow-hidden">
        <h3 class="font-headline font-bold text-2xl sm:text-3xl text-on-surface tracking-tight leading-tight line-clamp-2 break-words">${esc(r.title)}</h3>
        <p class="font-headline italic text-lg text-on-surface-v mt-1 truncate">${esc(r.artist)}</p>
      </div>

      <!-- Tags & actions -->
      <div class="flex items-start gap-2">
        <div class="flex flex-wrap gap-1.5 flex-1 min-w-0">
          ${r.year ? `<span class="bg-surface-high/60 px-2.5 py-0.5 text-xs font-label rounded-full text-on-surface-v">${esc(r.year)}</span>` : ''}
          ${r.label ? [...new Set(r.label.split(', '))].map(l => `<span class="bg-surface-high/60 px-2.5 py-0.5 text-xs font-label rounded-full text-on-surface-v">${esc(l.trim())}</span>`).join('') : ''}
          ${r.country ? `<span class="bg-surface-high/60 px-2.5 py-0.5 text-xs font-label rounded-full text-on-surface-v">${esc(r.country)}</span>` : ''}
          ${tags.map(t => `<span class="border border-outline-v/30 px-2.5 py-0.5 text-xs font-label rounded-full text-outline">${esc(t)}</span>`).join('')}
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          ${r.id ? `<button class="w-8 h-8 rounded-full bg-surface-high/50 flex items-center justify-center text-outline hover:text-primary transition-colors" onclick="_copyDetailInfo(this, ${r.id})" title="${esc(t('detail.copy.title'))}">
            <i class="bi bi-clipboard text-xs"></i>
          </button>` : ''}
          ${r.id ? `<button id="share-btn" class="w-8 h-8 rounded-full bg-surface-high/50 flex items-center justify-center text-outline hover:text-primary transition-colors" onclick="_shareRecord(this, ${r.id})" title="${esc(t('detail.share.title'))}">
            <i class="bi bi-share text-xs"></i>
          </button>` : ''}
          ${r.discogs_id ? `<a href="https://www.discogs.com/release/${r.discogs_id}" target="_blank" class="w-8 h-8 rounded-full bg-surface-high/50 flex items-center justify-center text-outline hover:text-primary transition-colors" title="${esc(t('detail.viewOnDiscogs'))}"><i class="bi bi-box-arrow-up-right text-xs"></i></a>` : ''}
          ${r.discogs_id && !peek ? _renderDiscogsToggleBtn(r.discogs_id) : ''}
        </div>
      </div>

      <!-- Discogs Value Card -->
      ${hasPrices || r.discogs_id ? `
      <div class="bg-surface rounded-xl p-5 relative overflow-hidden">
        <div class="relative z-10">
          <div ${peek ? '' : 'id="detail-price-area"'}>${hasPrices ? _editorialPriceCard(r) : ''}</div>
        </div>
        <div class="absolute -right-4 -bottom-4 w-32 h-32 bg-primary/5 rounded-full blur-3xl"></div>
      </div>` : ''}

      <!-- Rating -->
      <div ${peek ? '' : 'id="detail-rating-area"'}>${ratingStars(r.rating_average, r.rating_count)}</div>

      <!-- Notes -->
      ${r.notes ? `
      <div class="bg-surface-top/30 rounded-xl p-5">
        <h4 class="font-headline italic text-lg text-on-surface mb-2">${esc(t('detail.notes.title'))}</h4>
        <p class="font-body text-on-surface-v text-sm leading-relaxed">${esc(r.notes)}</p>
      </div>` : ''}

      <!-- Discogs Extra (lazy loaded) -->
      <div ${peek ? '' : `id="detail-extra-${r.id}"`} class="space-y-4">
        ${r.discogs_extra ? _renderDiscogsExtra(r.discogs_extra, r) : ''}
      </div>

      <!-- Listens (loaded after render) -->
      ${peek || !r.id ? '' : `<div id="detail-listens-${r.id}"></div>`}

      <!-- Delete — always last -->
      ${peek || !r.id ? '' : _deleteButton(r.id)}
    </div>
  </div>`;
}

function _editorialPriceCard(r) {
  const cur = r.price_currency || 'USD';
  const sym = currSym(cur);
  const med = parseFloat(r.price_median);
  const low = parseFloat(r.price_low);
  const high = parseFloat(r.price_high);
  if (isNaN(med) && isNaN(low)) return '';
  return `
    <div class="flex items-baseline justify-between gap-3">
      <div class="flex items-baseline gap-2">
        ${!isNaN(med) ? `<span class="text-2xl font-headline font-bold text-primary">${sym}${med.toFixed(2)}</span>` : ''}
        <span class="text-[10px] font-label text-outline uppercase tracking-wider">${t('detail.price.median')}</span>
      </div>
      <div class="flex items-baseline gap-3 text-sm font-headline text-on-surface-v">
        ${!isNaN(low) ? `<span>${sym}${low.toFixed(0)} <span class="text-[10px] font-label text-outline uppercase">${t('detail.price.low')}</span></span>` : ''}
        ${!isNaN(high) ? `<span>${sym}${high.toFixed(0)} <span class="text-[10px] font-label text-outline uppercase">${t('detail.price.high')}</span></span>` : ''}
        ${r.num_for_sale ? `<span>${r.num_for_sale} <span class="text-[10px] font-label text-outline uppercase">${t('detail.price.listed')}</span></span>` : ''}
      </div>
    </div>`;
}

function _specRow(label, value) {
  if (!value) return '';
  return `<div class="flex justify-between items-end pb-2 border-b border-outline-v/10">
    <span class="font-body text-sm text-on-surface-v">${esc(label)}</span>
    <span class="font-headline text-sm text-on-surface">${esc(String(value))}</span>
  </div>`;
}

function _renderDetailBody(r) {
  const body = document.getElementById('detail-body');
  const prev = _detailList[_detailIndex - 1] || null;
  const next = _detailList[_detailIndex + 1] || null;

  body.innerHTML = `
    <div class="sticky top-0 z-10 flex justify-between items-center px-3 py-2 pointer-events-none" style="margin-bottom:-48px">
      <div class="detail-nav flex items-center gap-1.5 mr-auto pointer-events-auto">
        <button class="hidden sm:flex detail-overlay-btn" id="detail-prev" onclick="_navigateDetail(-1)" title="${esc(t('detail.nav.previous'))}">
          <i class="bi bi-chevron-left text-sm"></i>
        </button>
        <button class="hidden sm:flex detail-overlay-btn" id="detail-next" onclick="_navigateDetail(1)" title="${esc(t('detail.nav.next'))}">
          <i class="bi bi-chevron-right text-sm"></i>
        </button>
      </div>
      <button data-dismiss="modal" class="detail-overlay-btn pointer-events-auto" aria-label="Close">
        <i class="bi bi-x-lg text-sm"></i>
      </button>
    </div>
    <div class="detail-track relative">
      <div class="absolute top-0 right-full w-full overflow-hidden max-h-[90vh]">${prev ? _renderPanelHtml(prev, true) : ''}</div>
      ${_renderPanelHtml(r)}
      <div class="absolute top-0 left-full w-full overflow-hidden max-h-[90vh]">${next ? _renderPanelHtml(next, true) : ''}</div>
    </div>`;
  _loadListensForDetail(r);
}

function _formatListenTime(iso) {
  try {
    return new Intl.DateTimeFormat(getLocale(), {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function _renderListensSection(r, listens) {
  const count = listens.length;
  const countLabel = count === 0
    ? esc(t('detail.listens.empty'))
    : esc(t('detail.listens.count', { count }));
  const rows = listens.slice(0, 5).map(l => `
    <li class="flex items-center justify-between gap-3 py-1.5 border-b border-outline-v/10 last:border-b-0">
      <span class="font-body text-sm text-on-surface-v">${esc(_formatListenTime(l.listened_at))}</span>
      <button onclick="_deleteListenForDetail(${l.id})" class="text-outline hover:text-danger transition-colors shrink-0" title="${esc(t('detail.listens.delete'))}" aria-label="${esc(t('detail.listens.delete'))}">
        <i class="bi bi-x text-base"></i>
      </button>
    </li>`).join('');
  return `
    <div class="bg-surface-top/30 rounded-xl p-5">
      <div class="flex items-center justify-between mb-3">
        <h4 class="font-headline italic text-lg text-on-surface">${esc(t('detail.listens.title'))}</h4>
        <span class="text-xs font-label text-outline">${countLabel}</span>
      </div>
      ${rows ? `<ul class="mb-4">${rows}</ul>` : ''}
      <button onclick="_logListenForDetail(${r.id})" class="w-full inline-flex items-center justify-center gap-2 py-2 rounded-full border border-primary/40 text-primary hover:bg-primary/10 transition-colors text-sm font-label">
        <i class="bi bi-music-note-beamed"></i>
        ${esc(t('detail.listens.logBtn'))}
      </button>
    </div>`;
}

function _renderDiscogsExtra(extra, r) {
  return [
    _renderTracklist(extra.tracklist, r),
    _renderFormats(extra.formats),
    _renderCredits(extra.extraartists),
    _renderReleaseNotes(extra.notes),
    _renderIdentifiers(extra.identifiers),
    _renderCompanies(extra.companies, extra.series),
  ].filter(Boolean).join('');
}

function _renderTracklist(tracklist, r) {
  if (!tracklist || !tracklist.length) return '';
  const liked = r && r.liked_tracks ? r.liked_tracks : [];
  const rid = r ? r.id : 0;
  let html = '<div class="bg-surface-low rounded-xl p-5">';
  html += `<h4 class="font-label text-xs uppercase tracking-widest text-outline mb-4">${esc(t('detail.tracklist.title'))}</h4>`;
  html += '<div class="space-y-0">';
  for (const trk of tracklist) {
    if (trk.type_ === 'heading') {
      html += `<div class="font-label text-xs uppercase tracking-widest text-primary-dim pt-3 pb-1">${esc(trk.title)}</div>`;
      continue;
    }
    const trackId = trk.position || trk.title;
    const isLiked = liked.includes(trackId);
    const pos = trk.position ? `<span class="text-outline font-label text-xs shrink-0 whitespace-nowrap">${esc(trk.position)}</span>` : '';
    const safeTrackId = trackId.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;');
    const heart = rid ? `<button class="shrink-0 text-sm transition-all duration-200"
      style="color:${isLiked ? '#f87171' : '#4e453c'}"
      onclick="_toggleTrackLike(this, ${rid}, '${safeTrackId}')" title="${isLiked ? t('detail.tracklist.unlike') : t('detail.tracklist.like')}">
      <i class="bi ${isLiked ? 'bi-heart-fill' : 'bi-heart'}" style="transition:transform 0.2s"></i>
    </button>` : '';
    html += `<div class="flex items-center gap-2 py-1.5 border-b border-outline-v/10">
      ${pos}
      <span class="font-body text-sm text-on-surface truncate flex-1">${esc(trk.title)}</span>
      ${heart}
      <span class="text-outline text-xs shrink-0 w-10 text-right tabular-nums">${trk.duration ? esc(trk.duration) : ''}</span>
    </div>`;
  }
  html += '</div></div>';
  return html;
}

function _renderFormats(formats) {
  if (!formats || !formats.length) return '';
  const desc = formats.map(f => {
    const parts = [];
    if (f.qty && f.qty !== '1') parts.push(f.qty + '×');
    parts.push(f.name);
    if (f.descriptions && f.descriptions.length) parts.push(...f.descriptions);
    return parts.join(', ');
  }).join(' + ');
  return `<div class="bg-surface-low rounded-xl p-5">
    <h4 class="font-label text-xs uppercase tracking-widest text-outline mb-3">${esc(t('detail.format.title'))}</h4>
    <p class="font-body text-sm text-on-surface-v">${esc(desc)}</p>
  </div>`;
}

function _renderCredits(extraartists) {
  if (!extraartists || !extraartists.length) return '';
  const grouped = {};
  for (const a of extraartists) {
    const role = a.role || 'Other';
    if (!grouped[role]) grouped[role] = [];
    grouped[role].push(a.name);
  }
  let html = '<div class="bg-surface-low rounded-xl p-5">';
  html += `<h4 class="font-label text-xs uppercase tracking-widest text-outline mb-4">${esc(t('detail.credits.title'))}</h4>`;
  html += '<div class="space-y-2">';
  for (const [role, names] of Object.entries(grouped)) {
    html += `<div class="pb-2 border-b border-outline-v/10">
      <span class="font-label text-[11px] uppercase tracking-wider text-outline">${esc(role)}</span>
      <div class="font-headline text-sm text-on-surface mt-0.5">${names.map(n => esc(n)).join(', ')}</div>
    </div>`;
  }
  html += '</div></div>';
  return html;
}

function _renderReleaseNotes(notes) {
  if (!notes) return '';
  return `<div class="bg-surface-top/30 rounded-xl p-5">
    <h4 class="font-label text-xs uppercase tracking-widest text-outline mb-3">${esc(t('detail.releaseNotes.title'))}</h4>
    <p class="font-body text-on-surface-v text-sm leading-relaxed whitespace-pre-line">${esc(notes)}</p>
  </div>`;
}

function _renderIdentifiers(identifiers) {
  if (!identifiers || !identifiers.length) return '';
  let html = '<div class="bg-surface-low rounded-xl p-5">';
  html += `<h4 class="font-label text-xs uppercase tracking-widest text-outline mb-4">${esc(t('detail.identifiers.title'))}</h4>`;
  html += '<div class="space-y-2">';
  for (const id of identifiers) {
    const desc = id.description ? ` (${esc(id.description)})` : '';
    html += `<div class="pb-2 border-b border-outline-v/10">
      <span class="font-label text-[11px] uppercase tracking-wider text-outline">${esc(id.type)}${desc}</span>
      <div class="font-headline text-sm text-on-surface mt-0.5 font-mono break-all">${esc(id.value)}</div>
    </div>`;
  }
  html += '</div></div>';
  return html;
}

function _renderCompanies(companies, series) {
  const items = [];
  if (companies && companies.length) {
    for (const c of companies) {
      items.push({ label: c.entity_type_name || 'Company', value: c.name + (c.catno ? ` [${c.catno}]` : '') });
    }
  }
  if (series && series.length) {
    for (const s of series) {
      items.push({ label: t('detail.companies.series'), value: s.name + (s.catno ? ` #${s.catno}` : '') });
    }
  }
  if (!items.length) return '';
  let html = '<div class="bg-surface-low rounded-xl p-5">';
  html += `<h4 class="font-label text-xs uppercase tracking-widest text-outline mb-4">${esc(t('detail.companies.title'))}</h4>`;
  html += '<div class="space-y-2">';
  for (const item of items) {
    html += `<div class="pb-2 border-b border-outline-v/10">
      <span class="font-label text-[11px] uppercase tracking-wider text-outline">${esc(item.label)}</span>
      <div class="font-headline text-sm text-on-surface mt-0.5">${esc(item.value)}</div>
    </div>`;
  }
  html += '</div></div>';
  return html;
}

