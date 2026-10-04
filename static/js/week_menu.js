// Weekmenu-pagina: recept-picker (drag/drop, autocomplete),
// menu opslaan, week wissen. Data via <script id="page-data">.

const _pageData = JSON.parse(document.getElementById("page-data").textContent);

const recipesData = _pageData.recipes;
const recipes = recipesData.map(r => ({
    id: r.id,
    name: r.name,
    serves: r.serves || 4,
    cookbook: r.cookbook,
    cookbookAbbr: r.cookbookAbbr,
    page: r.page,
    displayName: r.name + (r.cookbook ? ` (${r.cookbookAbbr}${r.page ? ' p.' + r.page : ''})` : ''),
}));
const recipesById = {};
recipesData.forEach(r => { recipesById[r.id] = r; });

const defaultServes = _pageData.defaultServes;

let selectedRecipeForModal = null;

// ── Helpers ────────────────────────────────────────────────────────────────

const debounce = (func, wait) => {
    let timeout;
    return function executedFunction(...args) {
        const later = () => { clearTimeout(timeout); func(...args); };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
};

const showSaveStatus = () => {
    const status = document.getElementById('saveStatus');
    status.classList.remove('hidden');
    setTimeout(() => status.classList.add('hidden'), 2000);
};

// ── Dag-datums & week-bereik ────────────────────────────────────────────────

const NL_MONTHS_SHORT = ['jan','feb','mrt','apr','mei','jun','jul','aug','sep','okt','nov','dec'];

function getWeekMonday(week, year) {
    const jan4 = new Date(year, 0, 4);
    const dow  = jan4.getDay() || 7;
    const mon  = new Date(jan4);
    mon.setDate(jan4.getDate() - (dow - 1) + (week - 1) * 7);
    return mon;
}

function fillDayDates(week, year) {
    const mon   = getWeekMonday(week, year);
    const today = new Date();
    today.setHours(0,0,0,0);

    document.querySelectorAll('[data-day-date]').forEach(el => {
        const d = new Date(mon);
        d.setDate(mon.getDate() + parseInt(el.dataset.dayDate));
        el.textContent = d.getDate() + ' ' + NL_MONTHS_SHORT[d.getMonth()];

        // Vandaag markeren
        if (d.getTime() === today.getTime()) {
            const card = document.getElementById('day-card-' + el.dataset.dayDate);
            if (card) card.classList.add('day-today');
        }
    });

    const sun = new Date(mon);
    sun.setDate(mon.getDate() + 6);
}

// ── Menu opslaan ────────────────────────────────────────────────────────────

// Losse recepten die bij het opslaan opgaan in het weekmenu ('zelfde maaltijd').
const teOvernemen = new Set();

// Een vak kreeg een recept: staat het deze week al als los recept op de
// boodschappenlijst, vraag dan of het dezelfde maaltijd is. Het recept staat
// al in het vak, dus wegklikken laat het erbij komen.
async function vraagBijLosRecept(recipeId, naam) {
    const nogTeVragen = _pageData.losseRecepten.filter(q => !teOvernemen.has(q.id));
    const { keuze, los } = await kiesBijLosRecept(nogTeVragen, recipeId,
                                                  _pageData.year, _pageData.week, naam);
    if (keuze === 'zelfde') teOvernemen.add(los.id);
}

const updateMenu = async () => {
    const menu = [];
    for (let day = 0; day < 7; day++) {
        const meals = {};
        ['ontbijt', 'lunch', 'diner'].forEach(mealType => {
            const recipeInput = document.querySelector(`[data-day="${day}"][data-meal="${mealType}"].meal-input`);
            const peopleCountInput = document.querySelector(`[data-day="${day}"][data-meal="${mealType}"].people-count-input`);
            if (recipeInput.value) {
                const pcVal = peopleCountInput ? peopleCountInput.value.trim() : '';
                const peopleCount = pcVal ? (parseInt(pcVal) || null) : null;
                meals[mealType] = { recipe_id: recipeInput.value, people_count: peopleCount };
            }
        });
        menu.push({ day, meals });
    }
    try {
        const response = await fetch('/update_menu', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ week: _pageData.week, year: _pageData.year, menu: menu,
                                   neem_los_recept_over: [...teOvernemen] })
        });
        if (response.ok) {
            _pageData.losseRecepten = _pageData.losseRecepten.filter(q => !teOvernemen.has(q.id));
            teOvernemen.clear();
            showSaveStatus();
        }
        else console.error('Error saving menu');
    } catch (error) {
        console.error('Error:', error);
    }
};

const debouncedUpdate = debounce(updateMenu, 500);

// ── Zoeken ──────────────────────────────────────────────────────────────────

function filterRecipes(query) {
    if (!query) return recipes;
    const lowerQuery = query.toLowerCase();
    return recipes.filter(recipe => {
        const searchString = [recipe.name, recipe.cookbook, recipe.cookbookAbbr, recipe.page, `p${recipe.page}`]
            .filter(Boolean).join(' ').toLowerCase();
        if (lowerQuery.includes(' ')) {
            return lowerQuery.split(' ').every(part => searchString.includes(part));
        }
        return searchString.includes(lowerQuery);
    });
}

function setPeopleCount(searchInput, recipeId) {
    const input = searchInput.parentNode.querySelector('.people-count-input');
    if (!input) return;
    const recipeData = recipesById[parseInt(recipeId)];
    if (defaultServes) {
        input.value = defaultServes;
    } else if (recipeData && recipeData.serves) {
        input.value = recipeData.serves;
    } else {
        input.value = '';
    }
}

function clearPeopleCount(searchInput) {
    const input = searchInput.parentNode.querySelector('.people-count-input');
    if (input) input.value = '';
}

function showDropdown(searchInput, filteredRecipes) {
    const dropdown = searchInput.parentNode.querySelector('.recipe-dropdown');
    if (filteredRecipes.length === 0) { dropdown.classList.add('hidden'); return; }

    dropdown.innerHTML = filteredRecipes.map(recipe =>
        `<div class="recipe-option px-3 py-2 cursor-pointer text-sm mx-1 rounded-lg transition-colors"
              style="color: var(--color-ink);"
              onmouseover="this.style.background='var(--color-sepia-bg)'"
              onmouseout="this.style.background=''"
              data-recipe-id="${recipe.id}" data-recipe-name="${recipe.name}"
              data-cookbook-abbr="${recipe.cookbookAbbr}" data-page="${recipe.page}" data-serves="${recipe.serves}">
            <div class="font-medium">${recipe.name}</div>
            ${recipe.cookbook
                ? `<div class="text-xs" style="color:var(--color-pencil)">${recipe.cookbook}${recipe.page ? `, p.${recipe.page}` : ''} · ${recipe.serves} pers.</div>`
                : `<div class="text-xs" style="color:var(--color-pencil)">${recipe.serves} pers.</div>`}
        </div>`
    ).join('');

    dropdown.classList.remove('hidden');

    dropdown.querySelectorAll('.recipe-option').forEach(option => {
        option.addEventListener('click', async () => {
            const recipeId     = option.dataset.recipeId;
            const recipeName   = option.dataset.recipeName;
            const cookbookAbbr = option.dataset.cookbookAbbr;
            const page         = option.dataset.page;

            searchInput.value = recipeName;
            searchInput.classList.add('has-recipe');
            searchInput.parentNode.querySelector('.meal-input').value = recipeId;

            setPeopleCount(searchInput, recipeId);
            updateRecipeInfo(searchInput, cookbookAbbr, page);

            dropdown.classList.add('hidden');
            await vraagBijLosRecept(recipeId, recipeName);
            debouncedUpdate();
        });
    });
}

function updateRecipeInfo(searchInput, cookbookAbbr, page) {
    const existing = searchInput.parentNode.querySelector('.recipe-info');
    if (existing) existing.remove();

    if (cookbookAbbr && cookbookAbbr !== 'null') {
        const infoDiv = document.createElement('div');
        infoDiv.className = 'recipe-info mt-1.5';
        infoDiv.innerHTML = `<span class="inline-block rounded px-1.5 py-0.5 text-xs font-medium"
            style="background: var(--color-sepia-bg); color: var(--color-sepia);">${cookbookAbbr}${page && page !== 'null' ? ` p.${page}` : ''}</span>`;
        const peopleContainer = searchInput.parentNode.querySelector('.people-count-container');
        if (peopleContainer) {
            searchInput.parentNode.insertBefore(infoDiv, peopleContainer.nextSibling);
        } else {
            searchInput.parentNode.insertBefore(infoDiv, searchInput.nextSibling);
        }
    }
}

function hideDropdown(searchInput) {
    setTimeout(() => {
        searchInput.parentNode.querySelector('.recipe-dropdown').classList.add('hidden');
    }, 200);
}

document.querySelectorAll('.recipe-search').forEach(searchInput => {
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value;
        if (query.length > 0) {
            showDropdown(searchInput, filterRecipes(query));
        } else {
            searchInput.classList.remove('has-recipe');
            searchInput.parentNode.querySelector('.meal-input').value = '';
            clearPeopleCount(searchInput);
            const existingInfo = searchInput.parentNode.querySelector('.recipe-info');
            if (existingInfo) existingInfo.remove();
            hideDropdown(searchInput);
            debouncedUpdate();
        }
    });

    searchInput.addEventListener('blur', () => hideDropdown(searchInput));

    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' || e.key === 'Delete') {
            setTimeout(() => {
                if (searchInput.value === '') {
                    searchInput.classList.remove('has-recipe');
                    searchInput.parentNode.querySelector('.meal-input').value = '';
                    clearPeopleCount(searchInput);
                    const existingInfo = searchInput.parentNode.querySelector('.recipe-info');
                    if (existingInfo) existingInfo.remove();
                    debouncedUpdate();
                }
            }, 10);
        }
    });
});

document.querySelectorAll('.people-count-input').forEach(input => {
    input.addEventListener('change', debouncedUpdate);
    input.addEventListener('input', debouncedUpdate);
});

document.addEventListener('click', (e) => {
    if (!e.target.closest('.relative')) {
        document.querySelectorAll('.recipe-dropdown').forEach(d => d.classList.add('hidden'));
    }
});

// ── Quick Access ────────────────────────────────────────────────────────────

async function loadQuickAccessRecipes() {
    try {
        const response = await fetch('/api/quick_access_recipes');
        const data = await response.json();
        displayRecipeList('favorites-list', data.favorites);
        displayRecipeList('recent-list', data.recent);
        displayRecipeList('popular-list', data.popular, true);
    } catch (error) {
        console.error('Error loading quick access recipes:', error);
    }
}

function displayRecipeList(containerId, recipeList, showCount) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (recipeList.length === 0) {
        container.innerHTML = '<p class="text-xs py-1" style="color:var(--color-pencil)">Nog geen recepten</p>';
        return;
    }

    container.innerHTML = recipeList.map(recipe => {
        const meta = [
            recipe.cookbook_abbr ? (recipe.cookbook_abbr + (recipe.page ? ` p.${recipe.page}` : '')) : null,
            recipe.serves + ' pers.',
            showCount && recipe.usage_count ? recipe.usage_count + '×' : null
        ].filter(Boolean).join(' · ');

        return `<div class="recipe-quick-item px-2 py-1.5 rounded-lg cursor-pointer transition-colors"
                     style="color: var(--color-ink);"
                     onmouseover="this.style.background='var(--color-sepia-bg)'"
                     onmouseout="this.style.background=''"
                     data-recipe='${JSON.stringify(recipe)}'>
                    <div class="text-sm font-medium leading-snug">${recipe.name}</div>
                    <div class="text-xs" style="color:var(--color-pencil)">${meta}</div>
                </div>`;
    }).join('');

    container.querySelectorAll('.recipe-quick-item').forEach(item => {
        item.addEventListener('click', () => openRecipeModal(JSON.parse(item.dataset.recipe)));
    });
}

function openRecipeModal(recipe) {
    selectedRecipeForModal = recipe;
    document.getElementById('selectedRecipe').textContent = recipe.name;
    document.getElementById('recipeModal').classList.remove('hidden');
}

// ── Modal ───────────────────────────────────────────────────────────────────

document.getElementById('cancelModal').addEventListener('click', () => {
    document.getElementById('recipeModal').classList.add('hidden');
    selectedRecipeForModal = null;
});

document.querySelectorAll('.meal-select-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const gekozen = selectedRecipeForModal;
        if (!gekozen) return;
        selectedRecipeForModal = null;
        document.getElementById('recipeModal').classList.add('hidden');
        const day  = parseInt(btn.dataset.day);
        const meal = btn.dataset.meal;
        const searchInput = document.querySelector(`[data-day="${day}"][data-meal="${meal}"].recipe-search`);
        const hiddenInput = document.querySelector(`[data-day="${day}"][data-meal="${meal}"].meal-input`);
        if (!searchInput || !hiddenInput) return;
        searchInput.value = gekozen.name;
        hiddenInput.value = gekozen.id;
        searchInput.classList.add('has-recipe');
        setPeopleCount(searchInput, gekozen.id);
        updateRecipeInfo(searchInput, gekozen.cookbook_abbr, gekozen.page);
        await vraagBijLosRecept(gekozen.id, gekozen.name);
        debouncedUpdate();
    });
});

// ── Week wissen ────────────────────────────────────────────────────────────

async function clearWeek() {
    if (!confirm('Weet je zeker dat je het complete weekmenu wilt wissen? Dit verwijdert ook de boodschappenlijst.')) return;
    try {
        const response = await fetch('/clear_week_menu', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ week: _pageData.week, year: _pageData.year })
        });
        const data = await response.json();
        if (data.status === 'success') location.reload();
        else alert('Fout: ' + (data.message || 'Onbekende fout'));
    } catch (error) {
        alert('Fout bij wissen: ' + error.message);
    }
}

// ── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    fillDayDates(_pageData.week, _pageData.year);
    loadQuickAccessRecipes();

    document.querySelectorAll('.meal-input').forEach(mealInput => {
        if (mealInput.value) {
            const day  = mealInput.dataset.day;
            const meal = mealInput.dataset.meal;
            const searchInput   = document.querySelector(`[data-day="${day}"][data-meal="${meal}"].recipe-search`);
            const peopleHidden  = document.querySelector(`[data-day="${day}"][data-meal="${meal}"].people-input`);
            const peopleVisible = document.querySelector(`[data-day="${day}"][data-meal="${meal}"].people-count-input`);
            if (searchInput && searchInput.value) searchInput.classList.add('has-recipe');
            if (peopleHidden && peopleVisible && peopleHidden.value) peopleVisible.value = peopleHidden.value;
        }
    });
});
