/* Shared recipe detail modal — fetch-based, accessibility-aware.
 *
 * Required partials/scripts on the page:
 *   - {% include '_recipe_detail_modal.html' %}
 *   - static/js/utils.js (for esc)
 *   - DOMPurify (for sanitizing instructions HTML)
 *
 * Optional page-level integration:
 *   - window.openPlanPopup      → if undefined, "Plan dit recept" button is hidden
 *   - window.onRecipeFavoriteToggled(id, isFavorite) → called after a successful toggle
 *   - window.onRecipeDeleted(id)                    → called after a successful delete
 *   - window.showToast(msg)                         → optional, used for delete-confirm feedback
 */

(function () {
  let activeRecipe = null;

  function fmtAmt(amount) {
    if (amount === null || amount === undefined || amount === 0) return '';
    const r = Math.round(amount * 100) / 100;
    return Number.isInteger(r) ? String(r) : String(parseFloat(r.toFixed(2)));
  }

  function hidePlanBtnIfNoHandler() {
    const btn = document.getElementById('dp-plan-btn');
    if (btn && typeof window.openPlanPopup !== 'function') {
      btn.style.display = 'none';
    }
  }

  function populate(r) {
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

    document.getElementById('dp-ingredients').innerHTML = (r.ingredients || []).map(ing => `
      <div class="ing-item flex items-center gap-2 py-0.5">
        <input type="checkbox" id="ing-${ing.id}" value="${ing.id}" checked
               style="width:1rem;height:1rem;border-radius:0.25rem;accent-color:#8B4513;flex-shrink:0;cursor:pointer;">
        <label for="ing-${ing.id}" class="text-sm text-[#2C2C2C] cursor-pointer select-none">
          ${fmtAmt(ing.amount) ? fmtAmt(ing.amount) + ' ' : ''}${esc(ing.unit)} ${esc(ing.name)}${ing.preparation ? ' <span class="text-[#6B6B6B] italic">(' + esc(ing.preparation) + ')</span>' : ''}
        </label>
      </div>
    `).join('') || '<p class="text-sm text-[#6B6B6B]">Geen ingrediënten.</p>';

    document.getElementById('dp-fav-btn').textContent = r.is_favorite ? '\u2B50' : '\u2606';
    document.getElementById('dp-edit-btn').href       = '/recipe/' + r.id + '/edit';

    hidePlanBtnIfNoHandler();

    document.getElementById('detail-overlay').style.display = 'block';
    document.getElementById('detail-panel').classList.add('open');
  }

  async function openDetailById(id) {
    try {
      const resp = await fetch('/api/recipe/' + id);
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const r = await resp.json();
      populate(r);
    } catch (e) {
      console.error('Fout bij laden recept:', e);
    }
  }

  // Public: handles <a href="/recipe/{id}/edit" onclick="return openDetail(event, id)"> — keeps
  // Ctrl/Cmd/middle-click as a native "open edit in new tab" fallback, overrides plain left-click
  // to open the modal.
  window.openDetail = function (event, id) {
    if (event && (event.ctrlKey || event.metaKey || event.shiftKey || event.button === 1)) {
      return true;
    }
    event?.preventDefault?.();
    if (typeof id === 'number' || typeof id === 'string') {
      openDetailById(id);
    }
    return false;
  };

  window.closeDetail = function () {
    document.getElementById('detail-panel').classList.remove('open');
    document.getElementById('detail-overlay').style.display = 'none';
    activeRecipe = null;
  };

  window.toggleAll = function (checked) {
    document.querySelectorAll('#dp-ingredients input[type=checkbox]')
      .forEach(cb => { cb.checked = checked; });
  };

  window.toggleDetailFavorite = async function () {
    if (!activeRecipe) return;
    try {
      const resp = await fetch('/recipe/' + activeRecipe.id + '/toggle_favorite', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }
      });
      const data = await resp.json();
      if (data.status === 'success') {
        activeRecipe.is_favorite = data.is_favorite;
        document.getElementById('dp-fav-btn').textContent = data.is_favorite ? '\u2B50' : '\u2606';
        if (typeof window.onRecipeFavoriteToggled === 'function') {
          window.onRecipeFavoriteToggled(activeRecipe.id, data.is_favorite);
        }
      }
    } catch (e) {
      console.error('Fout bij favoriet toggle:', e);
    }
  };

  window.deleteFromDetail = async function () {
    if (!activeRecipe) return;
    if (!confirm('Weet je zeker dat je "' + activeRecipe.name + '" wilt verwijderen?')) return;
    const id = activeRecipe.id;
    try {
      const resp = await fetch('/recipe/' + id, { method: 'DELETE' });
      if (resp.ok) {
        window.closeDetail();
        if (typeof window.onRecipeDeleted === 'function') {
          window.onRecipeDeleted(id);
        }
        if (typeof window.showToast === 'function') {
          window.showToast('Recept verwijderd');
        }
      }
    } catch (e) {
      console.error('Fout bij verwijderen:', e);
    }
  };

  window.getActiveDetailRecipe = function () { return activeRecipe; };

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && activeRecipe) {
      // Let page-level popups (plan-popup) handle Escape first if they're open.
      const planPopup = document.getElementById('plan-popup');
      if (planPopup && planPopup.classList.contains('open')) return;
      window.closeDetail();
    }
  });
})();
