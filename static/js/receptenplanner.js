/* Receptenplanner page — views (grid/coverflow/list) + plan popup.
 *
 * Detail-modal (openDetail/closeDetail/toggleDetailFavorite/…) komt uit
 * static/js/recipe-detail-modal.js, dat vóór dit script geladen wordt.
 * Wij gebruiken:
 *   - window.openDetail(event, id)        om de modal te openen
 *   - window.getActiveDetailRecipe()      om de plan-popup aan de actieve recipe te koppelen
 *   - window.onRecipeFavoriteToggled/Deleted callbacks om onze lokale RECIPES-cache
 *     synchroon te houden met modal-acties.
 */

const RECIPES = JSON.parse(document.getElementById('planner-recipes').textContent);
const _plannerCfg = JSON.parse(document.getElementById('planner-config').textContent);
const CURRENT_WEEK   = _plannerCfg.current_week;
const CURRENT_YEAR   = _plannerCfg.current_year;
const DEFAULT_SERVES = _plannerCfg.default_serves;

let currentView     = 'grid';
let currentCookbook = null;
let filteredRecipes = [...RECIPES];
let cfIndex         = 0;

function switchView(view) {
  ['grid','coverflow','list'].forEach(v => {
    const el = document.getElementById('view-' + v);
    el.style.display = 'none';
    document.getElementById('btn-' + v).classList.remove('active');
  });

  currentView = view;
  const container = document.getElementById('view-' + view);
  document.getElementById('btn-' + view).classList.add('active');

  if (view === 'grid') {
    container.style.display = 'grid';
    renderGrid();
  } else if (view === 'coverflow') {
    container.style.display = 'block';
    renderCoverflow();
  } else {
    container.style.display = 'block';
    renderList();
  }

  try { localStorage.setItem('plannerView', view); } catch(e) {}
}

function applyFilters() {
  const q     = (document.getElementById('recipe-search').value || '').trim().toLowerCase();
  const words = q ? q.split(/\s+/) : [];
  filteredRecipes = RECIPES.filter(r => {
    const textMatch = !words.length || words.every(w =>
      [r.name, r.cookbook || '', r.cookbook_abbr || ''].join(' ').toLowerCase().includes(w)
    );
    const bookMatch = !currentCookbook || r.cookbook === currentCookbook;
    return textMatch && bookMatch;
  });
  cfIndex = 0;
  if (currentView === 'grid')            renderGrid();
  else if (currentView === 'coverflow')  renderCoverflow();
  else                                   renderList();
}

function filterByCookbook(val) {
  currentCookbook = val || null;
  applyFilters();
}

function initCookbookFilter() {
  const books = [...new Set(RECIPES.map(r => r.cookbook).filter(Boolean))].sort();
  const sel   = document.getElementById('cookbook-filter');
  books.forEach(b => {
    const opt = document.createElement('option');
    opt.value = b; opt.textContent = b;
    sel.appendChild(opt);
  });
  if (books.length <= 1) sel.style.display = 'none';
}

function renderGrid() {
  const container = document.getElementById('view-grid');
  if (!filteredRecipes.length) {
    container.innerHTML = '<p class="text-[#6B6B6B] text-sm col-span-full">Geen recepten gevonden.</p>';
    return;
  }
  container.innerHTML = filteredRecipes.map(r => `
    <div class="recipe-card-grid" role="button" tabindex="0"
         onclick="openDetail(event, ${r.id})"
         onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openDetail(null, ${r.id});}">
      ${r.image_path
        ? `<img src="/${esc(r.image_path)}" alt="${esc(r.name)}" loading="lazy">`
        : `<div class="card-placeholder"><span style="font-size:3rem;font-weight:800;color:#D4CEC4;">${esc((r.name?.[0] ?? '?').toUpperCase())}</span></div>`
      }
      <div class="card-overlay">
        <span style="color:white;font-weight:600;font-size:0.8rem;line-height:1.25;
                     overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;">
          ${esc(r.name)}
        </span>
        <span style="display:inline-block;margin-top:0.3rem;font-size:0.7rem;color:white;
                     background:rgba(139,69,19,0.85);border-radius:9999px;padding:0.1rem 0.5rem;width:max-content;">
          ${r.serves} pers.
        </span>
      </div>
      <button onclick="event.stopPropagation();toggleCardFavorite(${r.id},this)"
              style="position:absolute;top:0.4rem;right:0.5rem;font-size:1.1rem;background:none;border:none;cursor:pointer;padding:0;line-height:1;"
              title="Favoriet">${r.is_favorite ? '\u2B50' : '\u2606'}</button>
    </div>
  `).join('');
}

const CF_POS = ['cf-pos-m2','cf-pos-m1','cf-pos-0','cf-pos-1','cf-pos-2'];

function renderCoverflow() {
  const track = document.getElementById('coverflow-track');
  track.innerHTML = '';
  filteredRecipes.forEach((r, i) => {
    const div = document.createElement('div');
    div.className = 'coverflow-card';
    div.dataset.idx = i;
    div.innerHTML = r.image_path
      ? `<img src="/${esc(r.image_path)}" alt="${esc(r.name)}" loading="lazy">`
      : `<div class="cf-placeholder" style="background:#F5F2ED;">
           <span style="font-size:4rem;font-weight:800;color:#D4CEC4;">${esc((r.name?.[0] ?? '?').toUpperCase())}</span>
         </div>`;
    div.innerHTML += `<div class="cf-label">${esc(r.name)}</div>`;
    div.addEventListener('click', () => {
      const offset = i - cfIndex;
      if (offset === 0) openDetail(null, r.id);
      else coverflowGoTo(i);
    });
    track.appendChild(div);
  });
  updateCoverflowPositions();
  updateCoverflowCaption();
}

function updateCoverflowPositions() {
  const cards = document.querySelectorAll('.coverflow-card');
  cards.forEach(card => {
    const i      = parseInt(card.dataset.idx);
    const offset = i - cfIndex;
    card.classList.remove('cf-pos-0','cf-pos-1','cf-pos-m1','cf-pos-2','cf-pos-m2',
                          'cf-pos-hidden','cf-pos-hidden-left');
    if      (offset ===  0) card.classList.add('cf-pos-0');
    else if (offset ===  1) card.classList.add('cf-pos-1');
    else if (offset === -1) card.classList.add('cf-pos-m1');
    else if (offset ===  2) card.classList.add('cf-pos-2');
    else if (offset === -2) card.classList.add('cf-pos-m2');
    else if (offset  >   2) card.classList.add('cf-pos-hidden');
    else                    card.classList.add('cf-pos-hidden-left');
  });
}

function updateCoverflowCaption() {
  const r = filteredRecipes[cfIndex];
  if (!r) {
    document.getElementById('cf-title').textContent = '';
    document.getElementById('cf-sub').textContent = '';
    return;
  }
  document.getElementById('cf-title').textContent = r.name;
  let sub = '';
  if (r.cookbook) sub += r.cookbook;
  if (r.page)     sub += (sub ? ' · ' : '') + 'p. ' + r.page;
  sub += (sub ? ' · ' : '') + r.serves + ' pers.';
  document.getElementById('cf-sub').textContent = sub;
}

function coverflowGoTo(index) {
  cfIndex = Math.max(0, Math.min(index, filteredRecipes.length - 1));
  updateCoverflowPositions();
  updateCoverflowCaption();
}
function coverflowNext() { coverflowGoTo(cfIndex + 1); }
function coverflowPrev() { coverflowGoTo(cfIndex - 1); }

function renderList() {
  const container = document.getElementById('view-list');
  if (!filteredRecipes.length) {
    container.innerHTML = '<p class="text-[#6B6B6B] text-sm">Geen recepten gevonden.</p>';
    return;
  }
  container.innerHTML = filteredRecipes.map(r => `
    <div class="flex items-center gap-3 p-3 bg-[#F5F2ED] rounded-lg border border-[#E8E4DC] cursor-pointer hover:border-[#C9A882]"
         role="button" tabindex="0"
         onclick="openDetail(event, ${r.id})"
         onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openDetail(null, ${r.id});}">
      <div class="flex-shrink-0 rounded-lg overflow-hidden" style="width:56px;height:56px;background:#F5F2ED;">
        ${r.image_path
          ? `<img src="/${esc(r.image_path)}" alt="${esc(r.name)}" loading="lazy" style="width:56px;height:56px;object-fit:cover;">`
          : `<div style="width:56px;height:56px;display:flex;align-items:center;justify-content:center;">
               <span style="font-size:1.4rem;font-weight:800;color:#D4CEC4;">${esc((r.name?.[0] ?? '?').toUpperCase())}</span>
             </div>`
        }
      </div>
      <div class="flex-1 min-w-0">
        <p class="font-semibold text-[#2C2C2C] truncate text-sm">${esc(r.name)}</p>
        <p class="text-xs text-[#6B6B6B] truncate">
          ${r.cookbook ? esc(r.cookbook) : ''}${r.page ? ' p. ' + r.page : ''}${(r.cookbook || r.page) ? ' · ' : ''}${r.serves} pers.
        </p>
      </div>
      <button onclick="event.stopPropagation();toggleCardFavorite(${r.id},this)"
              class="text-base ml-1 flex-shrink-0" style="background:none;border:none;cursor:pointer;padding:0;line-height:1;"
              title="Favoriet">${r.is_favorite ? '\u2B50' : '\u2606'}</button>
    </div>
  `).join('');
}

async function toggleCardFavorite(recipeId, btn) {
  try {
    const resp = await fetch('/recipe/' + recipeId + '/toggle_favorite', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }
    });
    const data = await resp.json();
    if (data.status === 'success') {
      const master = RECIPES.find(x => x.id === recipeId);
      if (master) master.is_favorite = data.is_favorite;
      btn.textContent = data.is_favorite ? '\u2B50' : '\u2606';
      const active = window.getActiveDetailRecipe?.();
      if (active && active.id === recipeId) {
        active.is_favorite = data.is_favorite;
        document.getElementById('dp-fav-btn').textContent = data.is_favorite ? '\u2B50' : '\u2606';
      }
    }
  } catch(e) {
    console.error('Fout bij favoriet toggle:', e);
  }
}

// Callbacks van de gedeelde modal-module — houden de lokale RECIPES-cache synchroon.
window.onRecipeFavoriteToggled = function (id, isFav) {
  const master = RECIPES.find(x => x.id === id);
  if (master) master.is_favorite = isFav;
  if (currentView === 'grid') renderGrid();
  else if (currentView === 'list') renderList();
  else if (currentView === 'coverflow') updateCoverflowCaption();
};

window.onRecipeDeleted = function (id) {
  const idx = RECIPES.findIndex(x => x.id === id);
  if (idx !== -1) RECIPES.splice(idx, 1);
  applyFilters();
};

const NL_MONTHS = ['jan','feb','mrt','apr','mei','jun','jul','aug','sep','okt','nov','dec'];

function getISOWeekMonday(week, year) {
  const jan4 = new Date(year, 0, 4);
  const day  = jan4.getDay() || 7;
  const mon  = new Date(jan4);
  mon.setDate(jan4.getDate() - (day - 1) + (week - 1) * 7);
  return mon;
}

function weekDateRange(week, year) {
  const mon = getISOWeekMonday(week, year);
  const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
  const fmt = d => d.getDate() + ' ' + NL_MONTHS[d.getMonth()];
  return fmt(mon) + ' – ' + fmt(sun);
}

function updateWeekRange() {
  const week = parseInt(document.getElementById('popup-week').value);
  const el   = document.getElementById('popup-week-range');
  if (week >= 1 && week <= 53) {
    el.textContent = weekDateRange(week, CURRENT_YEAR);
  } else {
    el.textContent = '';
  }
}

function openPlanPopup() {
  const active = window.getActiveDetailRecipe?.();
  if (!active) return;
  document.getElementById('popup-recipe-name').textContent = active.name;
  document.getElementById('popup-week').value = CURRENT_WEEK;
  document.getElementById('popup-persons').value = DEFAULT_SERVES || active.serves;
  document.getElementById('popup-error').style.display = 'none';
  updateWeekRange();
  document.getElementById('plan-popup').classList.add('open');
}

function closePlanPopup() {
  document.getElementById('plan-popup').classList.remove('open');
}

async function confirmPlanning() {
  const active = window.getActiveDetailRecipe?.();
  if (!active) return;

  const btn = document.getElementById('popup-confirm-btn');
  btn.disabled = true;
  btn.textContent = 'Bezig...';

  const checkedIds = Array.from(
    document.querySelectorAll('#dp-ingredients input[type=checkbox]:checked')
  ).map(cb => parseInt(cb.value));

  const payload = {
    recipe_id:      active.id,
    day:            parseInt(document.getElementById('popup-day').value),
    meal_type:      document.getElementById('popup-meal').value,
    week:           parseInt(document.getElementById('popup-week').value),
    year:           CURRENT_YEAR,
    people_count:   parseInt(document.getElementById('popup-persons').value) || 4,
    ingredient_ids: checkedIds
  };

  try {
    const resp = await fetch('/api/planner/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await resp.json();

    if (data.status === 'success') {
      closePlanPopup();
      showToast('Ingepland voor week ' + payload.week + '!');
      setTimeout(closeDetail, 350);
    } else {
      const errEl = document.getElementById('popup-error');
      errEl.textContent   = data.message || 'Er ging iets mis.';
      errEl.style.display = 'block';
    }
  } catch(e) {
    const errEl = document.getElementById('popup-error');
    errEl.textContent   = 'Netwerkfout, probeer opnieuw.';
    errEl.style.display = 'block';
  } finally {
    btn.disabled    = false;
    btn.textContent = 'Bevestigen';
  }
}

function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 3000);
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && document.getElementById('plan-popup').classList.contains('open')) {
    closePlanPopup();
    return;
  }
  // Modal-Escape wordt afgehandeld in recipe-detail-modal.js.
  const modalOpen = !!window.getActiveDetailRecipe?.();
  if (currentView !== 'coverflow' || modalOpen) return;
  if (e.key === 'ArrowRight') coverflowNext();
  if (e.key === 'ArrowLeft')  coverflowPrev();
  if (e.key === 'Enter' && filteredRecipes[cfIndex]) openDetail(null, filteredRecipes[cfIndex].id);
});

document.addEventListener('DOMContentLoaded', () => {
  initCookbookFilter();
  let saved = 'grid';
  try { saved = localStorage.getItem('plannerView') || 'grid'; } catch(e) {}
  switchView(saved);
});
