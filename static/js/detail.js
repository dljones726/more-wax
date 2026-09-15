// ─────────────────────────────────────────────────────────────────
//  DETAIL MODAL
// ─────────────────────────────────────────────────────────────────

// ── Navigation state ──────────────────────────────────────
let _detailList = [];
let _detailIndex = 0;
let _detailSwipe = null;
let _detailAnimating = false;
let _detailListenersAttached = false;

async function showDetail(id) {
  const r = collection.find(x => x.id === id);
  if (!r) return;

  // Snapshot current sorted/filtered list for pager
  _detailList = sortedFiltered();
  _detailIndex = _detailList.findIndex(x => x.id === id);
  if (_detailIndex < 0) _detailIndex = 0;

  // Pre-fetch full record (includes cached discogs_extra) before rendering
  await _preloadExtra(r);

  _renderDetailBody(r);
  _updateDetailNav();

  AppModal.show('detail-modal');
  const modalEl = document.getElementById('detail-modal');
  _attachDetailListeners(modalEl);

  _lazyLoadDetailData(r);
}

/** Fetch prices, extra details, and collection status if needed. */
function _lazyLoadDetailData(r) {
  if (r.discogs_id && (!r.price_median || !r.price_high || !r.rating_average)) {
    _refreshDetailPrices(r);
  }
  if (r.discogs_id && !r.discogs_extra) {
    _loadDiscogsExtra(r);
  }
  if (r.discogs_id) {
    _checkDiscogsCollection(r.discogs_id);
  }
}

// ── Listens section ──────────────────────────────────────────────

async function _loadListensForDetail(r) {
  if (!r || !r.id) return;
  const el = document.getElementById(`detail-listens-${r.id}`);
  if (!el) return;
  try {
    const listens = await apiGet(`/api/listens?record_id=${r.id}`);
    el.innerHTML = _renderListensSection(r, listens);
  } catch (e) {
    el.innerHTML = `<p class="text-sm text-outline">${esc(t('detail.listens.loadError', { error: e.message }))}</p>`;
  }
}

async function _logListenForDetail(recordId) {
  const r = _detailList[_detailIndex];
  try {
    await apiPost('/api/listens', { record_id: recordId });
    await _loadListensForDetail(r);
    if (typeof toast === 'function' && r) {
      toast(t('detail.listens.logged', { title: r.title || '' }), 'success');
    }
  } catch (e) {
    if (typeof toast === 'function') {
      toast(t('detail.listens.logError', { error: e.message }), 'error');
    }
  }
}

async function _deleteListenForDetail(listenId) {
  const r = _detailList[_detailIndex];
  if (!r) return;
  try {
    await apiDelete(`/api/listens/${listenId}`);
    await _loadListensForDetail(r);
  } catch (e) {
    if (typeof toast === 'function') {
      toast(t('detail.listens.deleteError', { error: e.message }), 'error');
    }
  }
}

function _updateDetailNav() {
  const prev = document.getElementById('detail-prev');
  const next = document.getElementById('detail-next');
  if (prev) prev.disabled = _detailIndex <= 0;
  if (next) next.disabled = _detailIndex >= _detailList.length - 1;
}

function _navigateDetail(dir) {
  const newIdx = _detailIndex + dir;
  if (newIdx < 0 || newIdx >= _detailList.length || _detailAnimating) return;
  _detailAnimating = true;

  // Start prefetch during animation (localhost is ~instant, finishes before 280ms transition)
  const nextR = _detailList[newIdx];
  const prefetch = _preloadExtra(nextR);

  const track = document.querySelector('.detail-track');
  if (!track) { _detailAnimating = false; return; }

  const target = dir > 0 ? '-100%' : '100%';
  track.classList.add('animating');
  track.style.transform = `translateX(${target})`;

  track.addEventListener('transitionend', async function once() {
    track.removeEventListener('transitionend', once);
    track.classList.remove('animating');

    _detailIndex = newIdx;
    await prefetch.catch(() => {});
    const r = _detailList[_detailIndex];

    const body = document.getElementById('detail-body');
    if (body) {
      body.style.visibility = 'hidden';
      body.scrollTop = 0;
    }

    _renderDetailBody(r);
    _updateDetailNav();

    requestAnimationFrame(() => {
      if (body) body.style.visibility = '';
      _detailAnimating = false;
    });

    _lazyLoadDetailData(r);
  });
}

// ── Keyboard navigation ──────────────────────────────────
function _detailKeyHandler(e) {
  if (e.key === 'ArrowLeft')  { e.preventDefault(); _navigateDetail(-1); }
  if (e.key === 'ArrowRight') { e.preventDefault(); _navigateDetail(1); }
}

// ── Touch / swipe navigation ─────────────────────────────
function _detailTouchStart(e) {
  if (e.touches.length !== 1) return;
  const body = document.getElementById('detail-body');
  _detailSwipe = {
    startX: e.touches[0].clientX,
    startY: e.touches[0].clientY,
    locked: false,
    canPull: body && body.scrollTop <= 0
  };
}

function _detailTouchMove(e) {
  if (!_detailSwipe || e.touches.length !== 1) return;
  const dx = e.touches[0].clientX - _detailSwipe.startX;
  const dy = e.touches[0].clientY - _detailSwipe.startY;

  if (!_detailSwipe.locked && (Math.abs(dx) > 10 || Math.abs(dy) > 10)) {
    if (Math.abs(dx) > Math.abs(dy)) {
      _detailSwipe.locked = 'h';
    } else if (dy > 0 && _detailSwipe.canPull) {
      _detailSwipe.locked = 'pull';
    } else {
      _detailSwipe.locked = 'v';
    }
  }

  if (_detailSwipe.locked === 'h') {
    e.preventDefault();
    const track = document.querySelector('.detail-track');
    if (!track) return;
    let translate = dx;
    if ((dx > 0 && _detailIndex <= 0) || (dx < 0 && _detailIndex >= _detailList.length - 1)) {
      translate = dx * 0.2;
    }
    const pct = (translate / track.parentElement.clientWidth) * 100;
    track.style.transform = `translateX(${pct}%)`;
  } else if (_detailSwipe.locked === 'pull') {
    e.preventDefault();
    const content = document.querySelector('#detail-modal .app-modal-content');
    if (!content) return;
    const pullDist = Math.max(0, dy) * 0.5;
    content.style.transform = `translateY(${pullDist}px)`;
    content.style.opacity = Math.max(0.3, 1 - pullDist / 400);
    content.style.transition = 'none';
  }
}

function _detailTouchEnd(e) {
  if (!_detailSwipe) return;
  const dx = (e.changedTouches[0]?.clientX || 0) - _detailSwipe.startX;
  const dy = (e.changedTouches[0]?.clientY || 0) - _detailSwipe.startY;
  const mode = _detailSwipe.locked;
  _detailSwipe = null;

  if (mode === 'h') {
    const track = document.querySelector('.detail-track');
    if (track) {
      if (Math.abs(dx) > 60) {
        _navigateDetail(dx < 0 ? 1 : -1);
      } else {
        track.classList.add('animating');
        track.style.transform = 'translateX(0)';
        track.addEventListener('transitionend', function once() {
          track.removeEventListener('transitionend', once);
          track.classList.remove('animating');
        });
      }
    }
  } else if (mode === 'pull') {
    const content = document.querySelector('#detail-modal .app-modal-content');
    if (!content) return;
    if (dy > 100) {
      content.style.transition = 'transform 250ms ease-out, opacity 200ms ease-out';
      content.style.transform = `translateY(${window.innerHeight}px)`;
      content.style.opacity = '0';
      setTimeout(() => {
        content.style.transform = '';
        content.style.opacity = '';
        content.style.transition = '';
        AppModal.hide('detail-modal');
      }, 260);
    } else {
      content.style.transition = 'transform 200ms ease-out, opacity 200ms ease-out';
      content.style.transform = '';
      content.style.opacity = '';
      setTimeout(() => { content.style.transition = ''; }, 200);
    }
  }
}

// ── Listener management ──────────────────────────────────
function _attachDetailListeners(modalEl) {
  if (_detailListenersAttached) return;
  _detailListenersAttached = true;

  document.addEventListener('keydown', _detailKeyHandler);

  const body = document.getElementById('detail-body');
  body.addEventListener('touchstart', _detailTouchStart, { passive: true });
  body.addEventListener('touchmove', _detailTouchMove, { passive: false });
  body.addEventListener('touchend', _detailTouchEnd, { passive: true });

  modalEl.addEventListener('modal:hidden', function cleanup() {
    modalEl.removeEventListener('modal:hidden', cleanup);
    document.removeEventListener('keydown', _detailKeyHandler);
    body.removeEventListener('touchstart', _detailTouchStart);
    body.removeEventListener('touchmove', _detailTouchMove);
    body.removeEventListener('touchend', _detailTouchEnd);
    _detailListenersAttached = false;
    _detailList = [];
    _detailIndex = 0;
  });
}

// ── Price refresh ────────────────────────────────────────
async function _refreshDetailPrices(r) {
  try {
    const prices = await getReleasePrices(r.discogs_id);
    if (prices.error) throw new Error(prices.error);

    let changed = false;
    for (const k of ['price_low', 'price_median', 'price_high', 'price_currency', 'num_for_sale', 'rating_average', 'rating_count']) {
      if (prices[k]) { r[k] = prices[k]; changed = true; }
    }

    if (changed) {
      await apiPut(`/api/collection/${r.id}`, {
        price_low: r.price_low || '', price_median: r.price_median || '',
        price_high: r.price_high || '', price_currency: r.price_currency || 'USD',
        num_for_sale: r.num_for_sale || '',
        rating_average: r.rating_average || '', rating_count: r.rating_count || ''
      });

      const priceArea = document.getElementById('detail-price-area');
      if (priceArea) priceArea.innerHTML = _editorialPriceCard(r);
      const ratingArea = document.getElementById('detail-rating-area');
      if (ratingArea) ratingArea.innerHTML = ratingStars(r.rating_average, r.rating_count);

      _updateCardBadge(r);
    }
  } catch (e) {
    console.warn('Could not refresh prices:', e.message);
    const priceArea = document.getElementById('detail-price-area');
    if (priceArea && !priceArea.querySelector('.text-primary')) {
      priceArea.innerHTML = '';
    }
    if (e.message?.includes('429')) throw e;
  }
}

function _updateCardBadge(r) {
  const card = document.querySelector(`[data-record-id="${r.id}"]`);
  if (!card) return;
  const metaRowEl = card.querySelector('.record-meta-row');
  if (!metaRowEl) return;

  const cur = r.price_currency || 'USD';
  const sym = currSym(cur);
  const priceBadge = card.querySelector('.record-price-badge');
  const newPriceBadge = r.price_median && !isNaN(parseFloat(r.price_median))
    ? `<span class="record-price-badge">${sym}${parseFloat(r.price_median).toFixed(0)} <span class="text-[0.7em] opacity-70 font-normal">med</span></span>`
    : r.price_low && !isNaN(parseFloat(r.price_low))
      ? `<span class="record-price-badge opacity-75">${sym}${parseFloat(r.price_low).toFixed(0)} <span class="text-[0.7em] opacity-70 font-normal">low</span></span>`
      : '';
  if (priceBadge) priceBadge.outerHTML = newPriceBadge;
  else if (newPriceBadge) metaRowEl.insertAdjacentHTML('beforeend', newPriceBadge);

  const rBadge = card.querySelector('.record-rating-badge');
  const newRatingBadge = ratingBadge(r);
  if (rBadge) rBadge.outerHTML = newRatingBadge;
  else if (newRatingBadge) {
    const yearEl = card.querySelector('.record-year');
    if (yearEl) yearEl.insertAdjacentHTML('afterend', newRatingBadge);
  }
}

// ── Discogs collection toggle ────────────────────────────────────
let _discogsCollectionState = {};  // discogs_id → bool

function _renderDiscogsToggleBtn(discogsId) {
  const cached = _discogsCollectionState[discogsId];
  const icon = cached === true ? 'bi-dash-circle' : 'bi-plus-circle';
  const color = cached === true ? 'text-primary' : 'text-outline';
  const title = cached === true ? t('detail.inDiscogsRemove')
    : cached === false ? t('detail.notInDiscogsAdd') : t('detail.checkingDiscogs');
  return `<button id="detail-discogs-toggle" data-discogs-id="${esc(discogsId)}" class="w-8 h-8 rounded-full bg-surface-high/50 flex items-center justify-center ${color} hover:text-primary transition-colors" onclick="_toggleDiscogsCollection('${esc(discogsId)}')" title="${esc(title)}">
    <i class="bi ${icon} text-xs"></i>
  </button>`;
}

async function _checkDiscogsCollection(discogsId) {
  const did = String(discogsId);
  try {
    const res = await apiGet(`/api/discogs/in-collection/${did}`);
    _discogsCollectionState[did] = res.in_collection;
    const btn = document.getElementById('detail-discogs-toggle');
    if (btn) _updateDiscogsToggle(btn, res.in_collection);
  } catch {
    // ignore — button stays in initial state
  }
}

function _updateDiscogsToggle(btn, inCollection) {
  const icon = btn.querySelector('i');
  if (inCollection) {
    icon.className = 'bi bi-dash-circle text-xs';
    btn.classList.remove('text-outline');
    btn.classList.add('text-primary');
    btn.title = t('detail.inDiscogsRemove');
  } else {
    icon.className = 'bi bi-plus-circle text-xs';
    btn.classList.remove('text-primary');
    btn.classList.add('text-outline');
    btn.title = t('detail.notInDiscogsAdd');
  }
}

async function _toggleDiscogsCollection(discogsId) {
  const did = String(discogsId);
  const btn = document.getElementById('detail-discogs-toggle');
  if (!btn) return;
  const inCollection = _discogsCollectionState[did];
  const icon = btn.querySelector('i');

  // Show spinner
  icon.className = 'bi bi-arrow-repeat animate-spin text-xs';

  try {
    if (inCollection) {
      // Restore icon while waiting for confirmation
      _updateDiscogsToggle(btn, true);
      if (!confirm(t('detail.discogs.removeConfirm'))) return;
      icon.className = 'bi bi-arrow-repeat animate-spin text-xs';
      const res = await apiDelete(`/api/discogs/collection/${did}`);
      if (res && res.success) {
        _discogsCollectionState[did] = false;
        toast(t('detail.discogs.removed'));
      } else {
        toast(t('detail.discogs.removeError'), 'error');
      }
    } else {
      const res = await apiPost(`/api/discogs/add-to-collection/${did}`, {});
      if (res && res.success) {
        _discogsCollectionState[did] = true;
        toast(t('detail.discogs.added'));
      } else {
        toast(t('detail.discogs.addError'), 'error');
      }
    }
    const currentBtn = document.getElementById('detail-discogs-toggle');
    if (currentBtn) _updateDiscogsToggle(currentBtn, _discogsCollectionState[did]);
  } catch (e) {
    toast(t('detail.discogs.failed', { error: e.message }), 'error');
    const currentBtn = document.getElementById('detail-discogs-toggle');
    if (currentBtn) _updateDiscogsToggle(currentBtn, !!inCollection);
  }
}

function _copyDetailInfo(btn, id) {
  const r = collection.find(x => x.id === id);
  if (!r) return;
  const text = `${r.artist} - ${r.title}`;

  function onSuccess() {
    const icon = btn.querySelector('i');
    icon.className = 'bi bi-clipboard-check';
    btn.classList.add('text-green');
    setTimeout(() => { icon.className = 'bi bi-clipboard'; btn.classList.remove('text-green'); }, 1500);
  }

  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(onSuccess).catch(() => _fallbackCopy(text, onSuccess));
  } else {
    _fallbackCopy(text, onSuccess);
  }
}

function _fallbackCopy(text, cb) {
  const modalEl = document.getElementById('detail-modal');
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.cssText = 'position:absolute;left:-9999px;top:-9999px';
  modalEl.appendChild(ta);
  ta.focus();
  ta.select();
  const ok = document.execCommand('copy');
  modalEl.removeChild(ta);
  if (ok) cb();
}

function _deleteButton(id) {
  return `<div class="flex justify-end pt-2 pb-2">
    <button class="text-danger/70 hover:text-danger text-sm font-medium flex items-center gap-1.5 transition-colors" onclick="confirmDelete(${id})">
      <i class="bi bi-trash"></i> ${esc(t('detail.delete.btn'))}
    </button>
  </div>`;
}

// ── Pre-fetch cached extra from local DB ────────────────
async function _preloadExtra(r) {
  if (r.discogs_extra || !r.discogs_id) return;
  try {
    const full = await apiGet(`/api/collection/${r.id}`);
    if (full && full.discogs_extra) {
      r.discogs_extra = full.discogs_extra;
    }
  } catch (e) { /* ignore — will fall back to lazy load */ }
}

// ── Discogs extra details (lazy loaded) ─────────────────
async function _loadDiscogsExtra(r) {
  const spinTimer = setTimeout(() => {
    const el = document.getElementById(`detail-extra-${r.id}`);
    if (el && !el.innerHTML.trim()) {
      el.innerHTML = `<div class="text-outline text-sm flex items-center gap-2 justify-center py-4"><i class="bi bi-arrow-repeat animate-spin"></i> ${esc(t('detail.loadingDetails'))}</div>`;
    }
  }, 3000);
  try {
    const extra = await getCollectionDetails(r.id);
    clearTimeout(spinTimer);
    if (extra.error) throw new Error(extra.error);
    r.discogs_extra = extra;
    const el = document.getElementById(`detail-extra-${r.id}`);
    if (el) el.innerHTML = _renderDiscogsExtra(extra, r);
  } catch (e) {
    clearTimeout(spinTimer);
    console.warn('Could not load release details:', e.message);
    if (e.message && e.message.includes('429')) {
      toast('Discogs rate limit — try again in a minute', 'error');
    }
    const el = document.getElementById(`detail-extra-${r.id}`);
    if (el) el.innerHTML = '';
  }
}

// ── Track likes ──────────────────────────────────────────────
async function _toggleTrackLike(btn, rid, trackId) {
  const r = collection.find(x => x.id === rid);
  if (!r) return;
  const prev = r.liked_tracks ? [...r.liked_tracks] : [];
  const wasLiked = prev.includes(trackId);
  const next = wasLiked ? prev.filter(t => t !== trackId) : [...prev, trackId];
  r.liked_tracks = next;
  const icon = btn.querySelector('i');
  icon.className = wasLiked ? 'bi bi-heart' : 'bi bi-heart-fill';
  btn.style.color = wasLiked ? '#4e453c' : '#f87171';
  btn.title = wasLiked ? t('detail.tracklist.like') : t('detail.tracklist.unlike');
  // Bounce: big → small → normal
  btn.style.transition = 'none';
  btn.style.transform = 'scale(1.8)';
  requestAnimationFrame(() => {
    btn.style.transition = 'transform 0.6s cubic-bezier(0.34, 1.56, 0.64, 1)';
    btn.style.transform = '';
  });
  try {
    await apiPut(`/api/collection/${rid}`, { liked_tracks: next });
  } catch (e) {
    r.liked_tracks = prev;
    icon.className = wasLiked ? 'bi bi-heart-fill' : 'bi bi-heart';
    btn.style.color = wasLiked ? '#f87171' : '#4e453c';
    btn.title = wasLiked ? t('detail.tracklist.unlike') : t('detail.tracklist.like');
    toast(t('detail.tracklist.likeError'), 'error');
  }
}

async function confirmDelete(id) {
  if (!confirm(t('detail.delete.confirm'))) return;
  await apiDelete(`/api/collection/${id}`);
  AppModal.hide('detail-modal');
  await loadCollection();
  toast(t('detail.delete.success'), 'success');
}

// ── Share record card ────────────────────────────────────────
async function _shareRecord(btn, id) {
  const r = collection.find(x => x.id === id);
  if (!r) return;
  const icon = btn.querySelector('i');
  icon.className = 'bi bi-arrow-repeat animate-spin text-xs';

  try {
    const canvas = document.createElement('canvas');
    const [coverImg, qrImg] = await Promise.all([
      _loadShareCover(r),
      _loadQrCode(),
    ]);
    _drawShareCard(canvas, r, coverImg, qrImg);

    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    const filename = `${r.artist || 'Record'} - ${r.title || 'Untitled'}.png`;

    // Try Web Share API (mobile)
    if (navigator.share && navigator.canShare) {
      const file = new File([blob], filename, { type: 'image/png' });
      const shareData = { files: [file] };
      if (navigator.canShare(shareData)) {
        await navigator.share(shareData);
        icon.className = 'bi bi-share text-xs';
        return;
      }
    }

    // Fallback: download
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    toast(t('detail.share.cardSaved'), 'success');
  } catch (e) {
    if (e.name !== 'AbortError') toast(t('detail.share.cardError'), 'error');
  }
  icon.className = 'bi bi-share text-xs';
}

let _cachedQrImg = undefined; // undefined = not fetched, null = failed, Image = loaded
function _loadQrCode() {
  if (_cachedQrImg !== undefined) return Promise.resolve(_cachedQrImg);
  return new Promise(resolve => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => { _cachedQrImg = img; resolve(img); };
    img.onerror = () => { _cachedQrImg = null; resolve(null); };
    img.src = 'https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=https%3A%2F%2Fgithub.com%2Feboudrant%2Fmore-wax&bgcolor=131313&color=9a8f83';
  });
}

function _loadShareCover(r) {
  return new Promise(resolve => {
    let src = r.local_cover ? `/covers/${r.local_cover}` : r.cover_image_url;
    if (!src) { resolve(null); return; }
    // Proxy Discogs images through our server to avoid CORS
    if (src.startsWith('https://i.discogs.com/')) {
      src = `/api/cover-proxy?url=${encodeURIComponent(src)}`;
    }
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}
