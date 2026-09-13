// Gedeelde helper voor de twee AH-zoek-flows:
//
//   * ah_search.js (op de boodschappenlijst per item, met chips voor
//     taxonomie en verpakkingsmaat)
//   * ah_products.html (op /ah-producten, koppelt zoekresultaten aan een
//     specifiek ingredient — geen chips, wél sortering en prijsadvies)
//
// De UI-flows verschillen te veel om écht samen te vallen, maar de request
// naar /api/ah/product-search hoort op één plek te wonen. Zo landt een
// URL-verandering (bijv. een nieuwe filter, een andere endpoint-versie) op
// één regel in plaats van twee plekken.
async function ahFetchProducts(q, opts) {
    q = (q || '').trim();
    if (!q) return null;
    opts = opts || {};
    const params = new URLSearchParams({ q, size: String(opts.size || 12) });
    if (opts.taxonomyId) params.set('taxonomy_id', opts.taxonomyId);
    if (opts.pkg)        params.set('pkg', opts.pkg);
    const resp = await fetch('/api/ah/product-search?' + params.toString());
    return resp.json();
}
