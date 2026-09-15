// ─────────────────────────────────────────────────────────────────
//  SCANNER / CAMERA — barcode + photo capture and search.
//  Split out of add-modal.js; loaded before it in index.html. All globals.
//  The sheet/results/confirm/save flow stays in add-modal.js.
// ─────────────────────────────────────────────────────────────────

async function openScanner() {
  selectedRelease       = null;
  capturedPhoto         = null;
  window._searchResults = [];
  window._detectedBarcode = null;
  scannerOpen = true;

  const el = document.getElementById('view-scanner');
  el.style.display = 'flex';
  el.classList.add('open');

  // Hide header & bottom nav
  document.querySelector('header').style.display = 'none';
  document.getElementById('bottom-nav').style.display = 'none';

  // Push history so back button closes scanner
  history.pushState({ scanner: true }, '', location.hash);

  // Start camera, wait for it to be ready, then start barcode mode
  await startScannerCamera();
  switchScannerMode('barcode');

  // Escape key handler
  document.addEventListener('keydown', _scannerEscHandler);
}

function closeScanner() {
  scannerOpen = false;
  stopScannerCamera();
  closeSheet();

  const el = document.getElementById('view-scanner');
  el.style.display = 'none';
  el.classList.remove('open');

  // Restore header & bottom nav
  document.querySelector('header').style.display = '';
  document.getElementById('bottom-nav').style.display = '';

  // Hide search panel
  document.getElementById('scanner-search-panel').classList.add('hidden');
  document.getElementById('scanner-dim').classList.add('hidden');

  document.removeEventListener('keydown', _scannerEscHandler);

  // Re-render current view
  if (currentView === 'dashboard') renderDashboard();
  if (currentView === 'collection') renderCollection();
}

function _scannerEscHandler(e) {
  if (e.key === 'Escape') {
    const sheet = document.getElementById('scanner-sheet');
    if (!sheet.classList.contains('sheet-open')) {
      closeScanner();
    } else {
      closeSheet();
    }
  }
}

function switchScannerMode(mode) {
  scannerMode = mode;

  // Update toggle buttons
  document.querySelectorAll('.scanner-mode-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });

  const frame     = document.getElementById('scanner-frame');
  const scanLine  = document.getElementById('scanner-scan-line');
  const shutter   = document.getElementById('scanner-shutter');
  const uploadBtn = document.getElementById('scanner-upload-btn');
  const guidance  = document.getElementById('scanner-guidance');
  const frameWrap = document.getElementById('scanner-frame-wrap');
  const dim       = document.getElementById('scanner-dim');
  const searchP   = document.getElementById('scanner-search-panel');
  const bottomA   = document.getElementById('scanner-bottom-area');

  if (mode === 'barcode') {
    frame.classList.remove('photo-mode');
    frameWrap.classList.remove('hidden');
    scanLine.style.display = '';
    shutter.classList.add('hidden');
    uploadBtn.classList.add('hidden');
    guidance.textContent = t('scanner.guidance.barcode');
    dim.classList.add('hidden');
    searchP.classList.add('hidden');
    bottomA.classList.remove('hidden');
    startQuaggaPolling();
  } else if (mode === 'photo') {
    if (_serverStatus && !_serverStatus.anthropic_key_set) {
      _showApiKeyDialog(); return;
    }
    frame.classList.add('photo-mode');
    frameWrap.classList.remove('hidden');
    scanLine.style.display = 'none';
    shutter.classList.remove('hidden');
    uploadBtn.classList.remove('hidden');
    guidance.textContent = t('scanner.guidance.photo');
    dim.classList.add('hidden');
    searchP.classList.add('hidden');
    bottomA.classList.remove('hidden');
    stopQuaggaPolling();
  } else if (mode === 'search') {
    frameWrap.classList.add('hidden');
    shutter.classList.add('hidden');
    uploadBtn.classList.add('hidden');
    dim.classList.remove('hidden');
    searchP.classList.remove('hidden');
    bottomA.classList.add('hidden');
    stopQuaggaPolling();
    setTimeout(() => document.getElementById('scanner-search-input')?.focus(), 200);
  }
}

function scannerSnapPhoto() {
  const dataUrl = captureFromScanner();
  if (!dataUrl) {
    toast(t('scanner.camera.notAvailable'), 'error');
    return;
  }
  processSearchPhotoForScanner(dataUrl, 'snapshot.jpg');
}

function handleScannerPhotoUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  const isHeic = file.type === 'image/heic' || file.type === 'image/heif'
              || /\.hei[cf]$/i.test(file.name);

  if (!isHeic && !file.type.startsWith('image/')) {
    toast(t('scanner.barcode.selectImage'), 'error');
    return;
  }

  openSheet();
  const body = document.getElementById('scanner-sheet-body');
  body.innerHTML = `
    <div class="flex flex-col items-center py-8">
      <div class="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
      <p class="mt-3 text-sm text-on-surface-v">${isHeic ? t('scanner.photo.converting') : t('scanner.photo.processing')}</p>
    </div>`;

  (async () => {
    try {
      const dataUrl = await imageFileToDataUrl(file);
      processSearchPhotoForScanner(dataUrl, file.name);
    } catch (e) {
      closeSheet();
      toast(e.message, 'error');
    }
  })();

  event.target.value = '';
}

function scannerDoSearch() {
  const q = document.getElementById('scanner-search-input')?.value?.trim();
  if (!q) return;
  scannerFetchAndShowResults(q, false);
}

async function scannerFetchAndShowResults(query, isBarcode) {
  openSheet();
  const body = document.getElementById('scanner-sheet-body');

  body.innerHTML = `
    <div class="text-center py-8 text-on-surface-v">
      <div class="w-6 h-6 border-2 border-primary/30 border-t-primary rounded-full animate-spin inline-block"></div>
      <p class="mt-3 text-sm">${t('scanner.search.searching')}</p>
    </div>`;

  try {
    const data    = isBarcode ? await searchByBarcode(query) : await searchDiscogs(query);
    const results = data.results || [];

    window._searchResults   = results;
    window._detectedBarcode = isBarcode ? query : null;

    if (results.length === 0) {
      body.innerHTML = `
        <div class="text-center py-8 text-on-surface-v">
          <i class="bi bi-emoji-frown text-4xl"></i>
          <p class="mt-3">${isBarcode ? t('scanner.search.noResultsBarcode') : t('scanner.search.noResults')}.</p>
        </div>`;
      document.getElementById('scanner-sheet-footer').innerHTML = `
        <button class="btn-ghost-new w-full" onclick="closeSheet(); switchScannerMode('search')">
          ${t('scanner.search.tryManual')}
        </button>`;
      return;
    }

    showResultsInSheet(results, isBarcode);
  } catch (e) {
    body.innerHTML = `
      <div class="text-center py-6 text-danger">
        <i class="bi bi-exclamation-triangle text-3xl"></i>
        <p class="mt-2">${t('scanner.search.discogsError', { error: esc(e.message) })}</p>
      </div>`;
  }
}

