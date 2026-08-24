/* Shared recipe form helpers — used by new_recipe.html and edit_recipe.html.
 * Depends on utils.js (esc) and ingredient-autocomplete.js (initAutocomplete).
 */

const CATEGORIES = JSON.parse(
  document.getElementById('recipe-form-categories').textContent
);

/** Initialize a Quill editor with the app's standard toolbar. */
function setupQuill(selector, placeholder, initialHtml) {
  const q = new Quill(selector, {
    modules: {
      toolbar: [
        [{ 'header': [1, 2, false] }],
        ['bold', 'italic'],
        [{ 'list': 'ordered' }, { 'list': 'bullet' }],
        [{ 'color': [] }],
        ['clean']
      ]
    },
    theme: 'snow',
    placeholder: placeholder || 'Beschrijf de bereidingsstappen...'
  });
  if (initialHtml) q.root.innerHTML = initialHtml;
  return q;
}

/** Toggle the "new cookbook" input field when the cookbook select changes. */
function toggleNewCookbook(select) {
  const input = document.getElementById('newCookbookInput');
  if (select.value === '__new__') {
    input.classList.remove('hidden');
    input.focus();
  } else {
    input.classList.add('hidden');
    input.value = '';
  }
  // Suggestion banner is optional (only present in new_recipe.html)
  const banner = document.getElementById('cookbookSuggestion');
  if (banner) banner.classList.add('hidden');
}

/** Append an ingredient row.
 * `opts` heeft dezelfde vorm als een geïmporteerde regel uit /recipe/scrape,
 * /recipe/from-photo of /dump/draft, zodat die er rechtstreeks in past:
 *   {name, amount, unit, category, id, preparation, in_pantry, pantry_hint, variant_of}
 */
function addIngredientRow(opts) {
  const o = opts || {};
  const container = document.getElementById('ingredients');
  const row = document.createElement('div');
  row.className = 'grid grid-cols-12 gap-x-2 gap-y-1 ingredient-row';
  const optionsHtml = CATEGORIES.map(cat => `<option value="${esc(cat)}">${esc(cat)}</option>`).join('');

  row.innerHTML = `
        <div class="col-span-10 md:col-span-4 order-1 md:order-1 relative">
            <input type="text" name="ingredient[]" placeholder="Ingrediënt" value="${esc(o.name ?? '')}" autocomplete="off"
                   class="ingredient-ac block w-full rounded-md border-[#D4CEC4] shadow-sm">
            <input type="hidden" name="ingredient_id[]" value="${esc(o.id ?? '')}">
            <input type="hidden" name="preparation[]" value="${esc(o.preparation ?? '')}">
            <input type="hidden" name="pantry_flag[]" value="0">
            <div class="ac-dropdown hidden absolute z-50 w-full bg-white border border-[#E8E4DC] rounded-md shadow-lg mt-1 max-h-48 overflow-y-auto"></div>
        </div>
        <div class="col-span-1 order-2 md:order-5 flex items-center justify-center">
            <button type="button" onclick="this.closest('.ingredient-row').remove()"
                    class="w-8 h-8 flex items-center justify-center rounded text-red-400 hover:text-red-600 text-xl font-bold"
                    aria-label="Ingrediënt verwijderen">×</button>
        </div>
        <div class="col-span-5 md:col-span-1 order-3 md:order-2">
            <input type="number" step="0.1" inputmode="decimal" name="amount[]" placeholder="Aantal" value="${esc(o.amount ?? '')}"
                   class="block w-full rounded-md border-[#D4CEC4] shadow-sm">
        </div>
        <div class="col-span-6 md:col-span-1 order-4 md:order-3">
            <input type="text" name="unit[]" placeholder="Eenheid" value="${esc(o.unit ?? '')}" list="unit-list"
                   class="block w-full rounded-md border-[#D4CEC4] shadow-sm">
        </div>
        <div class="col-span-12 md:col-span-3 order-5 md:order-4">
            <select name="category[]" class="block w-full rounded-md border-[#D4CEC4] shadow-sm">
                ${optionsHtml}
            </select>
        </div>
        <div class="col-span-12 md:col-span-2 order-6 md:order-6">
            <label class="pantry-label inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-[#E8E4DC] cursor-pointer text-xs text-[#6B6B6B]">
                <input type="checkbox" class="pantry-cb sr-only">
                <span class="pantry-icon" aria-hidden="true"></span>
                <span class="pantry-text">op de lijst</span>
            </label>
        </div>
        <div class="col-span-12 order-7 md:order-7 pantry-variant hidden"></div>
    `;

  setCategoryValue(row.querySelector('select[name="category[]"]'), o.category);
  container.appendChild(row);
  initAutocomplete(row.querySelector('.ingredient-ac'));
  initPantryToggle(row, o.in_pantry, o.pantry_hint);
  if (o.pantry_hint === 'variant' && o.variant_of) showVariantHint(row, o.variant_of);
}

/** Zet de categorie, ook als het een waarde is die niet (meer) in de lijst staat. */
function setCategoryValue(select, category) {
  if (!select || !category) return;
  select.value = category;
  if (select.selectedIndex === -1) {
    // Anders stuurt de select niets mee en schuiven alle volgende rijen op.
    const opt = document.createElement('option');
    opt.value = category;
    opt.textContent = category + ' (verouderd)';
    select.insertBefore(opt, select.firstChild);
    select.value = category;
  }
}

/** Koppel het vinkje aan de verborgen vlag die wél altijd meegestuurd wordt.
 * `hint` stuurt de drie standen: bevestigd (in voorraad), vraag (kandidaat), neutraal.
 */
function initPantryToggle(row, checked, hint) {
  const cb = row.querySelector('.pantry-cb');
  const flag = row.querySelector('input[name="pantry_flag[]"]');
  const label = row.querySelector('.pantry-label');
  const text = row.querySelector('.pantry-text');
  if (!cb || !flag) return;

  // Op de rij, niet in de closure: de autocomplete kan de hint later nog wijzigen.
  if (hint !== undefined) row.dataset.hint = hint || '';

  const icon = row.querySelector('.pantry-icon');
  const paint = () => {
    flag.value = cb.checked ? '1' : '0';
    if (!label) return;
    const suggest = !cb.checked && row.dataset.hint === 'suggest';
    label.className = 'pantry-label inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full cursor-pointer text-xs '
      + (cb.checked ? 'border border-[#97C459] bg-[#EAF3DE] text-[#3B6D11]'
        : suggest ? 'border border-dashed border-[#BA7517] bg-[#FAEEDA] text-[#854F0B]'
          : 'border border-[#E8E4DC] text-[#B4B2A9] hover:border-[#8B4513] hover:text-[#8B4513]');
    if (icon) icon.textContent = cb.checked ? '\u2302' : (suggest ? '+' : '');
    if (text) text.textContent = cb.checked ? 'in huis' : (suggest ? 'altijd in huis?' : 'op de lijst');
  };

  cb.checked = !!checked;
  paint();
  cb.addEventListener('change', paint);
  row._paintPantry = paint;
}

/** Waarschuw als de naam samenvalt met een ingredient dat al op voorraad staat. */
function showVariantHint(row, twin) {
  const box = row.querySelector('.pantry-variant');
  if (!box) return;
  // classList, geen className: de haak-klasse pantry-variant moet blijven staan,
  // anders is het blok daarna nergens meer terug te vinden.
  box.classList.remove('hidden');
  box.classList.add('mt-1', 'rounded', 'bg-[#E6F1FB]', 'px-3', 'py-2',
                    'flex', 'items-center', 'gap-2', 'flex-wrap');
  box.innerHTML = `
        <span class="text-xs text-[#0C447C] flex-1 min-w-[200px]">Lijkt op <strong class="font-medium">${esc(twin.name)}</strong>, die in je voorraad staat</span>
        <button type="button" class="variant-accept text-xs px-2.5 py-1 rounded border border-[#378ADD] text-[#0C447C] hover:bg-[#B5D4F4]">Zelfde product</button>
        <button type="button" class="variant-dismiss text-xs px-2 py-1 text-[#185FA5] hover:underline">Toch apart</button>`;

  box.querySelector('.variant-accept').addEventListener('click', () => {
    row.querySelector('input[name="ingredient[]"]').value = twin.name;
    row.querySelector('input[name="ingredient_id[]"]').value = twin.id;
    const cb = row.querySelector('.pantry-cb');
    if (cb) { cb.checked = true; cb.dispatchEvent(new Event('change')); }
    clearVariantHint(row);
  });
  box.querySelector('.variant-dismiss').addEventListener('click', () => clearVariantHint(row));
}

/** Haal de variantwaarschuwing weg, bijvoorbeeld als de rij een ander
 *  ingredient krijgt. */
function clearVariantHint(row) {
  const box = row.querySelector('.pantry-variant');
  if (!box) return;
  box.innerHTML = '';
  box.className = 'col-span-12 order-7 md:order-7 pantry-variant hidden';
}

document.querySelectorAll('.ingredient-row').forEach(row => {
  initPantryToggle(row, row.dataset.pantry === '1', row.dataset.hint || '');
  if (row.dataset.hint === 'variant' && row.dataset.variantId) {
    showVariantHint(row, { id: row.dataset.variantId, name: row.dataset.variantName || '' });
  }
});
