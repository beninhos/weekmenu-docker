/* Receptenplanner page — views (grid/coverflow/list), detail panel, plan popup.
 * Depends on utils.js (esc) and DOMPurify (from CDN, loaded before this script).
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
let activeRecipe    = null;

function formatAmt(amount) {
  if (amount === null || amount === undefined || amount === 0) return '';
  const r = Math.round(amount * 100) / 100;
  return Number.isInteger(r) ? String(r) : String(parseFloat(r.toFixed(2)));
}

function cardImage(r, w, h) {
  if (r.image_path) {
    return `<img src="/${esc(r.image_path)}" alt="${esc(r.name)}" loading="lazy"
                 style="width:${w};height:${h};object-fit:cover;display:block;">`;
  }
  return `<div style="width:${w};height:${h};display:flex;align-items:center;justify-content:center;">
    <span style="font-size:2.5rem;font-weight:800;color:#D4CEC4;">${esc((r.name?.[0] ?? '?').toUpperCase())}</span>
  </div>`;
}

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
    <div class="recipe-card-grid" onclick="openDetail(${r.id})">
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
      if (offset === 0) openDetail(r.id);
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
         onclick="openDetail(${r.id})">
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

function openDetail(recipeId) {
  if (!recipeId) return;
  const r = RECIPES.find(x => x.id === recipeId);
  if (!r) return;
  activeRecipe = r;

  const img = document.getElementById('dp-img');
  const ph  = document.getElementById('dp-placeholder');
  if (r.image_path) {
    img.src = '/' + r.image_path;
    img.style.display = 'block';
    ph.style.display  = 'none';
  } else {
    img.style.display = 'none';
    ph.style.display  = 'flex';
    document.getElementById('dp-initial').textContent = (r.name?.[0] ?? '?').toUpperCase();
  }

  document.getElementById('dp-name').textContent     = r.name;
  document.getElementById('dp-cookbook').textContent = r.cookbook || '';
  document.getElementById('dp-page').textContent     = r.page ? 'p. ' + r.page : '';
  document.getElementById('dp-serves').textContent   = r.serves + ' personen';

  const urlEl = document.getElementById('dp-url');
  if (r.url) {
    urlEl.href          = r.url;
    urlEl.style.display = 'inline';
  } else {
    urlEl.style.display = 'none';
  }

  const instrWrap = document.getElementById('dp-instr-wrap');
  if (r.instructions) {
    document.getElementById('dp-instr').innerHTML = DOMPurify.sanitize(r.instructions);
    instrWrap.style.display = 'block';
  } else {
    instrWrap.style.display = 'none';
  }

  document.getElementById('dp-ingredients').innerHTML = r.ingredients.map(ing => `
    <div class="ing-item flex items-center gap-2 py-0.5">
      <input type="checkbox" id="ing-${ing.id}" value="${ing.id}" checked
             style="width:1rem;height:1rem;border-radius:0.25rem;accent-color:#8B4513;flex-shrink:0;cursor:pointer;">
      <label for="ing-${ing.id}" class="text-sm text-[#2C2C2C] cursor-pointer select-none">
        ${formatAmt(ing.amount) ? formatAmt(ing.amount) + ' ' : ''}${esc(ing.unit)} ${esc(ing.name)}${ing.preparation ? ' <span class="text-[#6B6B6B] italic">(' + esc(ing.preparation) + ')</span>' : ''}
      </label>
    </div>
  `).join('') || '<p class="text-sm text-[#6B6B6B]">Geen ingrediënten.</p>';

  const favBtn = document.getElementById('dp-fav-btn');
  favBtn.textContent = r.is_favorite ? '\u2B50' : '\u2606';
  document.getElementById('dp-edit-btn').href = '/recipe/' + r.id + '/edit';

  document.getElementById('popup-persons').value = DEFAULT_SERVES || r.serves;

  document.getElementById('detail-overlay').style.display = 'block';
  document.getElementById('detail-panel').classList.add('open');
}

async function toggleDetailFavorite() {
  if (!activeRecipe) return;
  try {
    const resp = await fetch('/recipe/' + activeRecipe.id + '/toggle_favorite', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }
    });
    const data = await resp.json();
    if (data.status === 'success') {
      activeRecipe.is_favorite = data.is_favorite;
      const master = RECIPES.find(x => x.id === activeRecipe.id);
      if (master) master.is_favorite = data.is_favorite;
      document.getElementById('dp-fav-btn').textContent = data.is_favorite ? '\u2B50' : '\u2606';
      if (currentView === 'grid') renderGrid();
      else if (currentView === 'list') renderList();
      else if (currentView === 'coverflow') updateCoverflowCaption();
    }
  } catch(e) {
    console.error('Fout bij favoriet toggle:', e);
  }
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
      if (activeRecipe && activeRecipe.id === recipeId) {
        activeRecipe.is_favorite = data.is_favorite;
        document.getElementById('dp-fav-btn').textContent = data.is_favorite ? '\u2B50' : '\u2606';
      }
    }
  } catch(e) {
    console.error('Fout bij favoriet toggle:', e);
  }
}

async function deleteFromDetail() {
  if (!activeRecipe) return;
  if (!confirm('Weet je zeker dat je "' + activeRecipe.name + '" wilt verwijderen?')) return;
  try {
    const resp = await fetch('/recipe/' + activeRecipe.id, { method: 'DELETE' });
    if (resp.ok) {
      const idx = RECIPES.findIndex(x => x.id === activeRecipe.id);
      if (idx !== -1) RECIPES.splice(idx, 1);
      closeDetail();
      applyFilters();
      showToast('Recept verwijderd');
    }
  } catch(e) {
    console.error('Fout bij verwijderen:', e);
  }
}

function closeDetail() {
  document.getElementById('detail-panel').classList.remove('open');
  document.getElementById('detail-overlay').style.display = 'none';
  activeRecipe = null;
}

function toggleAll(checked) {
  document.querySelectorAll('#dp-ingredients input[type=checkbox]')
    .forEach(cb => { cb.checked = checked; });
}

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
  if (!activeRecipe) return;
  document.getElementById('popup-recipe-name').textContent = activeRecipe.name;
  document.getElementById('popup-week').value = CURRENT_WEEK;
  document.getElementById('popup-error').style.display = 'none';
  updateWeekRange();
  document.getElementById('plan-popup').classList.add('open');
}

function closePlanPopup() {
  document.getElementById('plan-popup').classList.remove('open');
}

async function confirmPlanning() {
  if (!activeRecipe) return;

  const btn = document.getElementById('popup-confirm-btn');
  btn.disabled = true;
  btn.textContent = 'Bezig...';

  const checkedIds = Array.from(
    document.querySelectorAll('#dp-ingredients input[type=checkbox]:checked')
  ).map(cb => parseInt(cb.value));

  const payload = {
    recipe_id:      activeRecipe.id,
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
  if (e.key === 'Escape') {
    if (document.getElementById('plan-popup').classList.contains('open')) { closePlanPopup(); return; }
    if (activeRecipe) { closeDetail(); return; }
  }
  if (currentView !== 'coverflow' || activeRecipe) return;
  if (e.key === 'ArrowRight') coverflowNext();
  if (e.key === 'ArrowLeft')  coverflowPrev();
  if (e.key === 'Enter' && filteredRecipes[cfIndex]) openDetail(filteredRecipes[cfIndex].id);
});

document.addEventListener('DOMContentLoaded', () => {
  initCookbookFilter();
  let saved = 'grid';
  try { saved = localStorage.getItem('plannerView') || 'grid'; } catch(e) {}
  switchView(saved);
});
