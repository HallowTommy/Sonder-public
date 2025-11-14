// static/js/search-mini.js
(function () {
  const panel = document.getElementById('Search-Window');
  if (!panel) return;

  const SEARCH_URL  = panel.dataset.searchUrl;
  const PLACEHOLDER = panel.dataset.placeholderImg || "";

  const inputEl   = panel.querySelector('#search-input');
  const resultsEl = panel.querySelector('#search-results');

  function openSearch() {
    panel.style.display = 'block';
    document.documentElement.style.overflow = 'hidden';
    setTimeout(() => inputEl && inputEl.focus(), 0);
  }
  function closeSearch() {
    panel.style.display = 'none';
    document.documentElement.style.overflow = '';
    if (inputEl) inputEl.value = '';
    if (resultsEl) resultsEl.innerHTML = '';
  }

  // открыть по иконке лупы
  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('.search, .search-2');
    if (!trigger) return;
    e.preventDefault();
    openSearch();
  });

  // закрыть ТОЛЬКО по крестику (в capture, чтобы обойти stopPropagation на контейнере)
  panel.addEventListener('click', (e) => {
    const closeBtn = e.target.closest('a.cross-link-wrap[data-close="search"]');
    if (!closeBtn) return;
    e.preventDefault();
    closeSearch();
  }, true); // <<< важное

  // дебаунс
  function debounce(fn, wait){ let t; return (...a)=>{clearTimeout(t); t=setTimeout(()=>fn(...a), wait);} }

  function renderItems(items) {
    if (!items.length) {
      resultsEl.innerHTML = `<div class="text-block-24" style="opacity:.6">Ничего не найдено</div>`;
    } else {
      resultsEl.innerHTML = items.map(it => `
        <a class="search-item" href="${it.url}">
          <span class="si-thumb"><img src="${it.image || PLACEHOLDER}" alt=""></span>
          <span class="si-meta">
            <span class="si-title">${it.name}</span>
            <span class="si-price">${it.price} BYN</span>
          </span>
        </a>
      `).join('');
    }
  }

  async function doSearch(q) {
    if (!q || q.length < 2) { resultsEl.innerHTML = ''; return; }
    try {
      const resp = await fetch(`${SEARCH_URL}?q=${encodeURIComponent(q)}`, { credentials: 'same-origin' });
      if (!resp.ok) throw new Error('network');
      const data = await resp.json();
      if (!data.ok) throw new Error('bad');
      renderItems(data.items || []);
    } catch (e) {
      console.error(e);
      resultsEl.innerHTML = `<div class="text-block-24" style="opacity:.6">Ошибка поиска</div>`;
    }
  }

  inputEl.addEventListener('input', debounce(e => doSearch(e.target.value.trim()), 250));

  // Enter — перейти к первому результату
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const first = resultsEl.querySelector('.search-item');
      if (first) window.location.href = first.getAttribute('href');
    }
  });
})();