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

/** Append an ingredient row. `withPantry` toggles the "always in stock" checkbox. */
function addIngredientRow(name, amount, unit, category, ingId, preparation, withPantry) {
  const container = document.getElementById('ingredients');
  const row = document.createElement('div');
  row.className = 'grid grid-cols-12 gap-x-2 gap-y-1 ingredient-row';
  const optionsHtml = CATEGORIES.map(cat => `<option value="${esc(cat)}">${esc(cat)}</option>`).join('');

  const ingColSpan = withPantry ? 'col-span-10' : 'col-span-11';
  const pantryCell = withPantry ? `
        <div class="col-span-1 order-2 md:order-5 flex items-center justify-center"
             title="Altijd in huis — wijzigt de voorraadkast voor de hele app">
            <input type="checkbox" name="pantry[]" value=""
                   class="pantry-cb w-4 h-4 cursor-pointer rounded border-[#D4CEC4]">
        </div>` : '';
  const removeMobile = withPantry ? 'order-3' : 'order-2';
  const removeMd = withPantry ? 'md:order-6' : 'md:order-5';
  const amountOrder = withPantry ? 'order-4' : 'order-3';
  const unitOrder = withPantry ? 'order-5' : 'order-4';
  const categoryOrder = withPantry ? 'order-6' : 'order-5';

  row.innerHTML = `
        <div class="${ingColSpan} md:col-span-4 order-1 md:order-1 relative">
            <input type="text" name="ingredient[]" placeholder="Ingrediënt" value="${esc(name ?? '')}" autocomplete="off"
                   class="ingredient-ac block w-full rounded-md border-[#D4CEC4] shadow-sm">
            <input type="hidden" name="ingredient_id[]" value="${esc(ingId ?? '')}">
            <div class="ac-dropdown hidden absolute z-50 w-full bg-white border border-[#E8E4DC] rounded-md shadow-lg mt-1 max-h-48 overflow-y-auto"></div>
        </div>
        ${pantryCell}
        <div class="col-span-1 ${removeMobile} ${removeMd} flex items-center justify-center">
            <button type="button" onclick="this.closest('.ingredient-row').remove()"
                    class="w-8 h-8 flex items-center justify-center rounded text-red-400 hover:text-red-600 text-xl font-bold">×</button>
        </div>
        <div class="col-span-6 md:col-span-2 ${amountOrder} md:order-2">
            <input type="number" step="0.1" inputmode="decimal" name="amount[]" placeholder="Aantal" value="${esc(amount ?? '')}"
                   class="block w-full rounded-md border-[#D4CEC4] shadow-sm">
        </div>
        <div class="col-span-6 md:col-span-2 ${unitOrder} md:order-3">
            <input type="text" name="unit[]" placeholder="Eenheid" value="${esc(unit ?? '')}" list="unit-list"
                   class="block w-full rounded-md border-[#D4CEC4] shadow-sm">
        </div>
        <div class="col-span-12 md:col-span-3 ${categoryOrder} md:order-4">
            <select name="category[]" class="block w-full rounded-md border-[#D4CEC4] shadow-sm">
                ${optionsHtml}
            </select>
        </div>
    `;
  if (category) {
    row.querySelector('select[name="category[]"]').value = category;
  }
  container.appendChild(row);
  const ac = row.querySelector('.ingredient-ac');
  initAutocomplete(ac);
  if (withPantry) {
    ac.addEventListener('change', () => {
      const hiddenId = row.querySelector('input[name="ingredient_id[]"]');
      const cb = row.querySelector('.pantry-cb');
      if (hiddenId && cb) cb.value = hiddenId.value;
    });
  }
}
