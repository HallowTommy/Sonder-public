// static/js/cart-mini.js
(function () {
    const panel = document.getElementById('Cart-Window');
    if (!panel) return;

    const SUMMARY_URL = panel.dataset.cartSummaryUrl;
    const UPDATE_URL = panel.dataset.cartUpdateUrl;
    const ICON_ADD = panel.dataset.iconCartAdd || '';
    const ICON_MINUS = panel.dataset.iconMinus || '';
    const ICON_PLUS = panel.dataset.iconPlus || '';
    const ICON_CLOSE = panel.dataset.iconClose || '';
    const PLACEHOLDER = panel.dataset.placeholderImg || '';

    const linesWrap = panel.querySelector('#cart-lines-mini');
    const totalEl = panel.querySelector('#cart-total-mini');

    function getCookie(name) {
        const v = `; ${document.cookie}`.split(`; ${name}=`);
        if (v.length === 2) return decodeURIComponent(v.pop().split(';').shift());
    }

    const CSRF = getCookie('csrftoken') || '';

    const cartIconImages = Array.from(document.querySelectorAll('.cart img, .cart-2 img'))
        .map(img => ({img, initial: img.getAttribute('src')}));

    function setCartIconActive(active) {
        cartIconImages.forEach(({img, initial}) => {
            if (active && ICON_ADD) {
                if (img.getAttribute('src') !== ICON_ADD) img.setAttribute('src', ICON_ADD);
            } else {
                if (img.getAttribute('src') !== initial) img.setAttribute('src', initial);
            }
        });
    }

    function openCart() {
        // явно ставим block, т.к. в разметке стоит display:none
        panel.style.display = 'block';
        document.documentElement.style.overflow = 'hidden';
    }

    function closeCart() {
        panel.style.display = 'none';
        document.documentElement.style.overflow = '';
    }

    // открыть по иконке
    document.addEventListener('click', (e) => {
        const trigger = e.target.closest('.cart, .cart-2');
        if (!trigger) return;
        e.preventDefault();
        openCart();
        refreshMiniCart();
    });

    // закрыть ТОЛЬКО по крестику
    document.addEventListener('click', (e) => {
        const closeBtn = e.target.closest('a[data-close="cart"].close-cross-wrap-cart');
        if (!closeBtn) return;
        e.preventDefault();
        closeCart();
    }, true);

    function renderItems(items) {
        if (!items || !items.length) {
            linesWrap.innerHTML = `
      <div class="product-line" style="opacity:.7;display:block;padding:24px 0;">
        Корзина пуста
      </div>`;
            setCartIconActive(false);
            if (totalEl) totalEl.textContent = '0';
            return;
        }

        linesWrap.innerHTML = items.map(it => `
    <div class="product-line" data-product-id="${it.id}">
      <div class="pl-img-wrap">
        ${it.url
            ? `<a href="${it.url}" class="pl-img-link" title="${it.name}">
               <img src="${it.image || PLACEHOLDER}" loading="lazy" alt="${it.name}">
             </a>`
            : `<img src="${it.image || PLACEHOLDER}" loading="lazy" alt="${it.name}">`
        }
      </div>
      <div class="pl-about-info">
        ${it.name}${it.size ? `,<br>${it.size}` : ''}
      </div>
      <div class="pl-price">${it.line_total} BYN</div>
      <div class="pl-quantity-grid-wrap">
        <a href="#" class="plq-minus-quantity w-inline-block" data-action="minus">
          <img src="${ICON_MINUS}" loading="lazy" alt="-">
        </a>
        <div class="plqg-quantity-info" data-role="qty">${it.qty}</div>
        <a href="#" class="plq-plus-quantity w-inline-block" data-action="plus">
          <img src="${ICON_PLUS}" loading="lazy" alt="+">
        </a>
      </div>
      <a href="#" class="pl-close-button w-inline-block" data-action="remove" aria-label="Удалить">
        <img src="${ICON_CLOSE}" loading="lazy" alt="Удалить">
      </a>
    </div>
  `).join('');
    }


    async function refreshMiniCart() {
        try {
            const resp = await fetch(SUMMARY_URL, {credentials: 'same-origin'});
            if (!resp.ok) throw new Error('network');
            const data = await resp.json();
            if (!data.ok) throw new Error('bad');

            renderItems(data.items || []);
            if (totalEl) totalEl.textContent = data.total || '0';
            setCartIconActive((data.count || 0) > 0);
        } catch (e) {
            console.error(e);
        }
    }

    linesWrap.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        e.preventDefault();

        const row = btn.closest('[data-product-id]');
        const pid = row?.getAttribute('data-product-id');
        const action = btn.getAttribute('data-action');
        if (!pid || !action) return;

        try {
            const body = new URLSearchParams({product_id: String(pid), action});
            const resp = await fetch(UPDATE_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                    'X-CSRFToken': CSRF,
                },
                credentials: 'same-origin',
                body
            });
            if (!resp.ok) throw new Error('network');
            const data = await resp.json();
            if (!data.ok) return;

            if (totalEl) totalEl.textContent = data.total;
            setCartIconActive((data.count || 0) > 0);

            if (data.removed) {
                row.remove();
                if (!linesWrap.querySelector('[data-product-id]')) {
                    renderItems([]); // покажем «Корзина пуста», но окно НЕ закрываем
                }
                return;
            }

            row.querySelector('[data-role="qty"]').textContent = data.qty;
            row.querySelector('.pl-price').textContent = `${data.line_total} BYN`;
        } catch (err) {
            console.error(err);
        }
    });

    // после добавления в корзину из каталога/карточки
    document.addEventListener('click', function (e) {
        const addBtn = e.target.closest('.add-product-link-wrap-1[data-product-id]');
        if (!addBtn) return;
        setTimeout(() => {
            refreshMiniCart();
            setCartIconActive(true);
            // openCart(); // если нужно автооткрывать после добавления — раскомментируй
        }, 200);
    });

    document.addEventListener('DOMContentLoaded', refreshMiniCart);
})();
