async function deleteRecipe(id) {
    if (confirm('Weet je zeker dat je dit recept wilt verwijderen?')) {
        const response = await fetch(`/recipe/${id}`, {
            method: 'DELETE',
        });
        if (response.ok) {
            location.reload();
        }
    }
}

async function toggleFavorite(recipeId, button) {
    try {
        const response = await fetch(`/recipe/${recipeId}/toggle_favorite`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (data.status === 'success') {
            button.textContent = data.is_favorite ? '\u2B50' : '\u2606';
            button.dataset.isFavorite = data.is_favorite;
        }
    } catch (error) {
        console.error('Error toggling favorite:', error);
    }
}
