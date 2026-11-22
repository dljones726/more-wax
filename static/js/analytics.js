// ─────────────────────────────────────────────────────────────────
//  ANALYTICS VIEW
// ─────────────────────────────────────────────────────────────────
async function renderAnalytics() {
  const el = document.getElementById('view-analytics');
  if (!el) return;
  el.innerHTML = '<div class="p-6 text-outline">Loading analytics…</div>';
  try {
    el.innerHTML = _analyticsHtml(await apiGet('/api/analytics'));
  } catch (e) {
    el.innerHTML = `<div class="p-6 text-danger">Could not load analytics: ${esc(e.message)}</div>`;
  }
}

function _analyticsHtml(d) {
  const sym = currSym(d.value.currency);
  const money = n => `${sym}${Number(n).toFixed(0)}`;
  const barMax = list => Math.max(1, ...list.map(r => r.value));

  const bar = (row, max) => `
    <div class="flex items-center gap-3 text-sm">
      <span class="w-28 truncate text-on-surface-v">${esc(row.name)}</span>
      <div class="flex-1 h-2 rounded-full bg-surface-high overflow-hidden">
        <div class="h-full bg-primary" style="width:${(row.value / max * 100).toFixed(1)}%"></div>
      </div>
      <span class="w-16 text-end font-headline text-on-surface">${money(row.value)}</span>
    </div>`;

  const rows = (list, metric) => list.length
    ? list.map(r => `
      <div class="flex items-center text-sm py-1 border-b border-outline-v/10">
        <span class="truncate text-on-surface">${esc(r.artist)} <span class="text-outline">— ${esc(r.title)}</span></span>
        <span class="ml-auto pl-2 font-headline text-on-surface whitespace-nowrap">${metric(r)}</span>
      </div>`).join('')
    : '<div class="text-outline text-sm">—</div>';

  return `
  <div class="max-w-3xl mx-auto p-4 sm:p-6 space-y-6">
    <div class="grid grid-cols-3 gap-4">
      <div class="bg-surface-low rounded-xl p-5 text-center">
        <div class="font-label text-xs uppercase tracking-widest text-outline mb-1">Records</div>
        <div class="font-headline text-2xl text-on-surface">${d.count}</div>
      </div>
      <div class="bg-surface-low rounded-xl p-5 text-center">
        <div class="font-label text-xs uppercase tracking-widest text-outline mb-1">Est. value</div>
        <div class="font-headline text-2xl text-on-surface">${money(d.value.median)}</div>
      </div>
      <div class="bg-surface-low rounded-xl p-5 text-center">
        <div class="font-label text-xs uppercase tracking-widest text-outline mb-1">Range</div>
        <div class="font-headline text-sm text-on-surface-v mt-2">${money(d.value.low)}–${money(d.value.high)}</div>
      </div>
    </div>

    <div class="bg-surface-low rounded-xl p-6 space-y-2">
      <h4 class="font-label text-xs uppercase tracking-widest text-outline mb-3">Value by genre</h4>
      ${d.by_genre.length ? d.by_genre.slice(0, 8).map(g => bar(g, barMax(d.by_genre))).join('') : '<div class="text-outline text-sm">—</div>'}
    </div>

    <div class="bg-surface-low rounded-xl p-6 space-y-2">
      <h4 class="font-label text-xs uppercase tracking-widest text-outline mb-3">Value by decade</h4>
      ${d.by_decade.length ? d.by_decade.map(g => bar(g, barMax(d.by_decade))).join('') : '<div class="text-outline text-sm">—</div>'}
    </div>

    <div class="grid gap-4 md:grid-cols-3">
      <div class="bg-surface-low rounded-xl p-6">
        <h4 class="font-label text-xs uppercase tracking-widest text-outline mb-3">Most valuable</h4>
        ${rows(d.top_value, r => money(r.price_median))}
      </div>
      <div class="bg-surface-low rounded-xl p-6">
        <h4 class="font-label text-xs uppercase tracking-widest text-outline mb-3">Rarest</h4>
        ${rows(d.rarest, r => `${r.num_for_sale} for sale`)}
      </div>
      <div class="bg-surface-low rounded-xl p-6">
        <h4 class="font-label text-xs uppercase tracking-widest text-outline mb-3">Highest rated</h4>
        ${rows(d.highest_rated, r => `${Number(r.rating_average).toFixed(1)}★`)}
      </div>
    </div>
  </div>`;
}