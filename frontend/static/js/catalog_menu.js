(function () {
    if (window.__MNAV_BOUND__) return;
    window.__MNAV_BOUND__ = true;

    const mnav = document.getElementById('mnav');
    if (!mnav) return;

    // ---- helpers ---------------------------------------------------------
    const isMobile = () => window.matchMedia('(max-width: 767px)').matches;
    let sy = 0;

    function lockBody() {
        sy = window.scrollY || document.documentElement.scrollTop;
        document.body.classList.add('body-lock');
        document.body.style.top = `-${sy}px`;
    }

    function unlockBody() {
        document.body.classList.remove('body-lock');
        document.body.style.top = '';
        window.scrollTo(0, sy);
    }

    function openMenu() {
        mnav.hidden = false;
        mnav.setAttribute('aria-hidden', 'false');
        mnav.classList.add('is-open');
        lockBody();
    }

    function closeMenu() {
        mnav.setAttribute('aria-hidden', 'true');
        mnav.classList.remove('is-open');
        setTimeout(() => {
            mnav.hidden = true;
        }, 180);
        unlockBody();
    }

    // показать/скрыть divider, стоящий СРАЗУ ПОСЛЕ секции
    function syncDivider(section, expanded) {
        const divider = section && section.nextElementSibling;
        if (!divider || !divider.classList || !divider.classList.contains('mnav-divider')) return;
        divider.style.display = expanded ? 'none' : ''; // скрыть когда раскрыто
    }

    // ---- header triggers (Каталог/бургер) -------------------------------
    document.addEventListener('click', function (e) {
        const el = e.target.closest('a,button');
        if (!el || !isMobile()) return;
        if (el.closest('#mnav')) return; // клики внутри меню игнорируем

        const href = (el.getAttribute && el.getAttribute('href')) || '';
        const inHeader = el.closest('.w-layout-grid.header, .w-layout-grid.header-4, header, .menu, .menu-2');
        const hitsKnown = el.closest('.menu .text-block-catalog, .menu-2 .text-block-27, .menu-toggle, .burger, .hamburger');
        const hitsClass = el.closest('.js-catalog-trigger');
        const hitsHref = inHeader && typeof href === 'string' && /\/catalog\/?$/.test(href);

        if (hitsHref || hitsKnown || hitsClass) {
            e.preventDefault();
            openMenu();
        }
    }, true);

    // ---- closing ---------------------------------------------------------
    mnav.addEventListener('click', (e) => {
        if (e.target.closest('.js-mnav-close')) closeMenu();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !mnav.hidden) closeMenu();
    });

    // ---- accordion -------------------------------------------------------
    mnav.addEventListener('click', (e) => {
        const btn = e.target.closest('.js-mnav-acc');
        if (!btn) return;

        const panel = btn.nextElementSibling;         // <ul class="mnav-sub">
        const section = btn.closest('.mnav-section'); // <li class="mnav-section">
        const wasExpanded = btn.getAttribute('aria-expanded') === 'true';
        const nowExpanded = !wasExpanded;

        btn.setAttribute('aria-expanded', String(nowExpanded));
        if (panel) panel.hidden = !nowExpanded;
        if (section) {
            section.classList.toggle('is-open', nowExpanded);
            syncDivider(section, nowExpanded);
        }
    });

    // ---- init: sync all sections, panels, dividers ----------------------
    mnav.querySelectorAll('.mnav-section').forEach(section => {
        const btn = section.querySelector('.js-mnav-acc');
        const panel = btn && btn.nextElementSibling;
        const expanded = !!(btn && btn.getAttribute('aria-expanded') === 'true');

        if (panel) panel.hidden = !expanded;
        section.classList.toggle('is-open', expanded);
        syncDivider(section, expanded);
    });

    // debug helpers
    window.MNAV_OPEN = openMenu;
    window.MNAV_CLOSE = closeMenu;
})();
(function () {
    const src = document.querySelector('.text-block-19') || document.body;
    const ff = getComputedStyle(src).fontFamily;
    document.documentElement.style.setProperty('--app-font', ff);
})();