// ─────────────────────────────────────────────────────────────────
//  SCANNER — full-screen camera-first add flow
// ─────────────────────────────────────────────────────────────────

// ── API key dialog ───────────────────────────────────────────
function _showApiKeyDialog() {
  // Avoid duplicates
  if (document.getElementById('apikey-dialog')) return;
  const overlay = document.createElement('div');
  overlay.id = 'apikey-dialog';
  overlay.style.cssText = `
    position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;
    background:rgba(0,0,0,.6);backdrop-filter:blur(4px);
  `;
  overlay.innerHTML = `
    <div style="background:var(--surface,#1c1c1e);border:1px solid var(--outline-v,#333);
                border-radius:16px;padding:28px 24px;max-width:360px;width:90%;text-align:center">
      <div style="font-size:2rem;margin-bottom:8px">🔑</div>
      <h3 style="margin:0 0 8px;color:var(--on-surface,#fff);font-size:1.1rem">${t('scanner.apiKey.title')}</h3>
      <p style="margin:0 0 16px;color:var(--muted,#aaa);font-size:.88rem;line-height:1.5">
        ${t('scanner.apiKey.description')}<br>
        ${t('scanner.apiKey.instruction').replace('.env', '<code style="background:var(--surface-top,#2a2a2c);padding:2px 6px;border-radius:4px;font-size:.82rem">.env</code>')}
      </p>
      <a href="https://console.anthropic.com/" target="_blank" rel="noopener"
         style="display:inline-block;margin-bottom:12px;color:var(--accent,#d4a574);font-size:.85rem;text-decoration:underline">
        ${t('scanner.apiKey.getKey')}
      </a><br>
      <button onclick="document.getElementById('apikey-dialog').remove()"
              style="margin-top:4px;padding:10px 28px;border-radius:10px;border:none;
                     background:var(--accent,#d4a574);color:#000;font-weight:600;font-size:.9rem;cursor:pointer">
        ${t('scanner.apiKey.ok')}
      </button>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}

// ── Open / Close ─────────────────────────────────────────────
// Back button support
window.addEventListener('popstate', () => {
  if (scannerOpen) {
    const sheet = document.getElementById('scanner-sheet');
    if (sheet.classList.contains('sheet-open')) {
      if (_sheetView === 'confirm' && window._searchResults && window._searchResults.length) {
        // Go back to results list instead of closing sheet
        showResultsInSheet(window._searchResults, !!window._detectedBarcode);
      } else {
        closeSheet();
      }
      // Re-push history so next back closes the scanner
      history.pushState({ scanner: true }, '', location.hash);
    } else {
      closeScanner();
    }
  }
});


// ── Mode Switching ───────────────────────────────────────────

// ── Photo capture from scanner ───────────────────────────────

// ── Search (scanner mode) ────────────────────────────────────

// ── Bottom Sheet ─────────────────────────────────────────────
function openSheet() {
  const sheet    = document.getElementById('scanner-sheet');
  const backdrop = document.getElementById('scanner-sheet-backdrop');

  backdrop.classList.remove('hidden');
  sheet.style.transform = 'translateY(0)';
  sheet.classList.add('sheet-open');
}

function closeSheet() {
  const sheet    = document.getElementById('scanner-sheet');
  const backdrop = document.getElementById('scanner-sheet-backdrop');

  _sheetView = null;
  sheet.style.transform = 'translateY(100%)';
  sheet.classList.remove('sheet-open');
  backdrop.classList.add('hidden');

  setTimeout(() => {
    document.getElementById('scanner-sheet-header').innerHTML = '';
    document.getElementById('scanner-sheet-body').innerHTML = '';
    document.getElementById('scanner-sheet-footer').innerHTML = '';
  }, 400);

  // Restart barcode scanning if still in barcode mode
  if (scannerMode === 'barcode' && cameraStream) {
    startQuaggaPolling();
  }
}

let _sheetView = null; // 'results' | 'confirm' — tracks current sheet content


// ── Results in Sheet ─────────────────────────────────────────
function _buildFormatString(r) {
  if (Array.isArray(r.formats) && r.formats.length) {
    const parts = [];
    for (const f of r.formats) {
      parts.push(f.name);
      if (Array.isArray(f.descriptions)) parts.push(...f.descriptions);
      if (f.text) parts.push(f.text);
    }
    return parts.join(', ');
  }
  return Array.isArray(r.format) ? r.format.join(', ') : (r.format || '');
}

function showResultsInSheet(results, isBarcode) {
  _sheetView = 'results';
  openSheet();

  const header = document.getElementById('scanner-sheet-header');
  const body   = document.getElementById('scanner-sheet-body');
  const footer = document.getElementById('scanner-sheet-footer');

  header.innerHTML = `
    <div>
      <h2 class="font-headline text-2xl font-bold text-on-surface">${t('scanner.results.title')}</h2>
      <p class="font-label text-[10px] uppercase tracking-widest text-primary font-bold">
        ${t('scanner.results.count', { count: results.length })}
      </p>
    </div>
    <button onclick="closeSheet()" class="w-10 h-10 flex items-center justify-center bg-surface-high rounded-full text-on-surface-v hover:text-on-surface transition-colors shrink-0">
      <i class="bi bi-x-lg"></i>
    </button>`;

  body.innerHTML = `
    <div class="space-y-3">
      ${results.map((r, i) => {
        const thumb = r.cover_image || r.thumb || '';
        const year  = r.year || '';
        const label = Array.isArray(r.label) ? r.label[0] : (r.label || '');
        const fmt   = _buildFormatString(r);
        return `
          <div class="group flex items-center gap-4 p-4 bg-surface-low rounded-2xl cursor-pointer transition-all hover:bg-surface active:bg-surface-high" onclick="scannerSelectRelease(${i})">
            ${thumb
              ? `<img class="w-20 h-20 object-cover rounded-lg flex-shrink-0 shadow-md" src="${esc(thumb)}" alt=""
                      onerror="this.outerHTML='<div class=\\'w-20 h-20 bg-surface-high rounded-lg flex items-center justify-center text-outline-v flex-shrink-0\\'><i class=\\'bi bi-vinyl text-2xl\\'></i></div>'">`
              : `<div class="w-20 h-20 bg-surface-high rounded-lg flex items-center justify-center text-outline-v flex-shrink-0"><i class="bi bi-vinyl text-2xl"></i></div>`}
            <div class="flex-1 min-w-0">
              <h3 class="font-headline text-lg font-bold text-on-surface truncate">${esc(r.title)}</h3>
              <p class="font-body text-sm text-on-surface-v">${esc(r.artist || '')}</p>
              <p class="font-label text-[10px] text-outline mt-1 uppercase tracking-tight">
                ${[year, label].filter(Boolean).join(' \u2022 ')}
              </p>
              ${fmt ? `<p class="font-label text-[10px] text-outline uppercase tracking-tight">${esc(fmt)}</p>` : ''}
            </div>
            <div class="w-10 h-10 rounded-full bg-surface-high text-outline flex items-center justify-center flex-shrink-0 group-hover:bg-primary group-hover:text-on-primary transition-all">
              <i class="bi bi-plus"></i>
            </div>
          </div>`;
      }).join('')}
    </div>`;

  footer.innerHTML = `
    <button class="w-full py-4 bg-outline-v/20 text-on-surface-v rounded-full font-label text-xs uppercase tracking-widest font-bold active:scale-[0.98] transition-all" onclick="closeSheet(); switchScannerMode('search')">
      ${t('scanner.results.noneMatch')}
    </button>`;
}

async function scannerSelectRelease(idx) {
  const stub = window._searchResults[idx];
  const body = document.getElementById('scanner-sheet-body');

  body.innerHTML = `
    <div class="text-center py-8 text-on-surface-v">
      <div class="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin inline-block"></div>
      <p class="mt-3 text-sm">${t('scanner.results.loadingDetails')}</p>
    </div>`;

  try {
    const release = await getReleaseFull(stub.id);
    if (release.error) throw new Error(release.error);

    if (window._detectedBarcode) release.barcode = window._detectedBarcode;
    if (!release.cover_image_url) {
      release.cover_image_url = stub.cover_image || stub.thumb || '';
    }

    selectedRelease = release;
    showConfirmInSheet();
  } catch (e) {
    body.innerHTML = `
      <div class="text-center py-6 text-danger">
        ${t('scanner.results.loadError', { error: esc(e.message) })}
        <br><button class="text-primary hover:underline mt-2" onclick="closeSheet()">${t('scanner.results.goBack')}</button>
      </div>`;
  }
}


// ── Confirm in Sheet ─────────────────────────────────────────
function showConfirmInSheet() {
  const r = selectedRelease;
  if (!r) return;

  _sheetView = 'confirm';

  const header = document.getElementById('scanner-sheet-header');
  const body   = document.getElementById('scanner-sheet-body');
  const footer = document.getElementById('scanner-sheet-footer');

  // Build a pseudo-record compatible with _renderPanelHtml (from detail.js)
  const pseudo = { ...r, local_cover: null };

  header.innerHTML = `
    <div>
      <h2 class="font-headline text-xl font-bold text-on-surface">${t('scanner.confirm.title')}</h2>
    </div>
    <button onclick="closeSheet()" class="w-10 h-10 flex items-center justify-center bg-surface-high rounded-full text-on-surface-v hover:text-on-surface transition-colors shrink-0">
      <i class="bi bi-x-lg"></i>
    </button>`;

  body.innerHTML = `
    <div class="space-y-4">
      ${r.already_in_discogs ? `
        <div class="bg-primary/10 border border-primary/30 rounded-lg px-3 py-2 text-sm text-primary mx-4">
          <i class="bi bi-exclamation-triangle mr-1"></i>
          ${t('scanner.confirm.alreadyInDiscogs')}
        </div>` : ''}

      ${_renderPanelHtml(pseudo, true)}

      <div id="scanner-capture-section" class="flex gap-2 px-4">
        <button onclick="_scannerCaptureCover()"
                class="flex-1 border-2 border-dashed border-outline-v/40 rounded-lg p-3 text-center cursor-pointer transition-colors hover:border-primary">
          <i class="bi bi-camera text-xl text-primary"></i>
          <div class="text-xs text-on-surface-v mt-1">${t('scanner.confirm.snapCover')}</div>
        </button>
        <button onclick="document.getElementById('scanner-cover-input').click()"
                class="flex-1 border-2 border-dashed border-outline-v/40 rounded-lg p-3 text-center cursor-pointer transition-colors hover:border-primary">
          <i class="bi bi-upload text-xl text-primary"></i>
          <div class="text-xs text-on-surface-v mt-1">${t('scanner.confirm.upload')}</div>
        </button>
        <input type="file" id="scanner-cover-input" accept="image/*,.heic,.heif" class="hidden" onchange="_scannerHandleCoverUpload(event)">
      </div>

      <div class="px-4">
        <label class="text-xs text-on-surface-v block mb-1">${t('scanner.confirm.notesLabel')}</label>
        <textarea id="notes-input" rows="2"
                  class="w-full bg-transparent border-b border-outline-v/40 py-2 px-0 text-sm text-on-surface focus:outline-none focus:border-primary transition-colors placeholder:text-outline resize-y"
                  placeholder="${t('scanner.confirm.notesPlaceholder')}"></textarea>
      </div>
    </div>`;

  footer.innerHTML = `
    <div class="space-y-2">
      <button id="save-btn" class="btn-primary-new w-full py-4 text-base font-bold" onclick="saveRecord()">
        <i class="bi bi-plus-circle mr-1"></i>${t('scanner.confirm.addBtn')}
      </button>
      <button class="btn-ghost-new w-full" onclick="showResultsInSheet(window._searchResults || [], !!window._detectedBarcode)">
        <i class="bi bi-arrow-left mr-1"></i>${t('scanner.confirm.backToResults')}
      </button>
    </div>`;
}

function _scannerCaptureCover() {
  const dataUrl = captureFromScanner();
  if (!dataUrl) {
    toast(t('scanner.camera.notAvailableUpload'), 'error');
    return;
  }
  capturedPhoto = dataUrl;
  const wrap = document.getElementById('scanner-cover-wrap');
  const panelImg = document.querySelector('#scanner-sheet-body .detail-panel > img');
  if (wrap) {
    wrap.innerHTML = `<img src="${dataUrl}" class="w-full aspect-square rounded-xl object-cover shadow-lg">`;
  } else if (panelImg) {
    panelImg.src = dataUrl;
  }
  document.getElementById('scanner-capture-section').style.display = 'none';
  toast(t('scanner.save.coverCaptured'), 'success');
}

async function _scannerHandleCoverUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const isHeic = file.type === 'image/heic' || file.type === 'image/heif'
              || /\.hei[cf]$/i.test(file.name);
  if (!isHeic && !file.type.startsWith('image/')) {
    toast(t('scanner.barcode.selectImage'), 'error');
    return;
  }
  try {
    capturedPhoto = await imageFileToDataUrl(file);
    const wrap = document.getElementById('scanner-cover-wrap');
    const panelImg = document.querySelector('#scanner-sheet-body .detail-panel > img');
    if (wrap) {
      wrap.innerHTML = `<img src="${capturedPhoto}" class="w-full aspect-square rounded-xl object-cover shadow-lg">`;
    } else if (panelImg) {
      panelImg.src = capturedPhoto;
    }
    document.getElementById('scanner-capture-section').style.display = 'none';
    toast(t('scanner.save.photoUploaded'), 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}


// ── Duplicate Warning ────────────────────────────────────────
function _showDuplicateWarning(existing) {
  const body   = document.getElementById('scanner-sheet-body');
  const footer = document.getElementById('scanner-sheet-footer');

  const cover = existing.local_cover || existing.cover_image_url || '';
  body.innerHTML = `
    <div class="text-center py-6">
      ${cover
        ? `<img src="${esc(cover)}" class="w-24 h-24 object-cover rounded-lg mx-auto mb-4">`
        : `<div class="w-24 h-24 bg-surface-high rounded-lg mx-auto mb-4 flex items-center justify-center text-3xl text-outline-v">
             <i class="bi bi-vinyl"></i>
           </div>`}
      <div class="text-danger font-bold mb-2">
        <i class="bi bi-exclamation-circle mr-1"></i>${t('scanner.duplicate.title')}
      </div>
      <div class="font-semibold text-on-surface">${esc(existing.title)}</div>
      <div class="text-sm text-on-surface-v mt-1">
        ${esc(existing.artist)}${existing.year ? ' · ' + esc(existing.year) : ''}
      </div>
    </div>`;

  footer.innerHTML = `
    <div class="flex gap-3">
      <button class="btn-ghost-new flex-1" onclick="closeScanner()">${t('scanner.duplicate.close')}</button>
      <button class="btn-primary-new flex-1" onclick="closeSheet(); switchScannerMode('barcode')">
        <i class="bi bi-arrow-left mr-1"></i>${t('scanner.duplicate.startOver')}
      </button>
    </div>`;
}


// ── Save Record ──────────────────────────────────────────────
async function saveRecord() {
  const notes   = document.getElementById('notes-input')?.value?.trim() || '';
  const saveBtn = document.getElementById('save-btn');
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<div class="w-4 h-4 border-2 border-on-primary/30 border-t-on-primary rounded-full animate-spin inline-block mr-2"></div>' + t('scanner.save.saving');
  }

  try {
    const sourceMap = { barcode: 'barcode', photo: 'photo', search: 'search' };
    const payload = { ...selectedRelease, notes, add_source: sourceMap[scannerMode] || 'search' };
    const res     = await fetch('/api/collection', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload)
    });

    if (res.status === 409) {
      const json = await res.json();
      const dup  = json.existing || {};
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.innerHTML = '<i class="bi bi-plus-circle mr-1"></i>' + t('scanner.confirm.addBtn');
      }
      _showDuplicateWarning(dup);
      return;
    }

    if (!res.ok) throw new Error('Backend error ' + res.status);
    const result = await res.json();

    if (capturedPhoto && result.id) {
      await apiPost('/api/upload-cover', {
        image: capturedPhoto, record_id: result.id
      });
    }

    let discogsMsg = '';
    if (selectedRelease.already_in_discogs) {
      discogsMsg = t('scanner.save.alreadyInDiscogs');
    } else if (selectedRelease.discogs_id) {
      const ok = await addToDiscogsCollection(selectedRelease.discogs_id);
      discogsMsg = ok ? t('scanner.save.addedToDiscogs') : t('scanner.save.discogsSyncFailed');
    }

    await loadCollection();
    closeScanner();
    toast(t('scanner.save.addedTitle', { title: selectedRelease.title, discogsMsg }), 'success');
  } catch (e) {
    toast(t('scanner.save.error', { error: e.message }), 'error');
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.innerHTML = '<i class="bi bi-plus-circle mr-1"></i>' + t('scanner.confirm.addBtn');
    }
  }
}
