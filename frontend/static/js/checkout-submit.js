// static/js/checkout-submit.js
(function () {
    // ----- helpers
    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return decodeURIComponent(parts.pop().split(';').shift());
    }

    function $(sel, root) {
        return (root || document).querySelector(sel);
    }

    const form = $('#checkout-form');
    if (!form) return;

    const modal = $('.successfully-window');
    const overlay = modal ? modal.querySelector('.shadow-on-sw') : null;
    const totalEl = $('#cart-total');
    const textEl = modal ? modal.querySelector('.text-block-112') : null;

    const CSRF = getCookie('csrftoken') || window.CSRF || '';
    const SUBMIT_URL = window.CHECKOUT_SUBMIT_URL || form.getAttribute('action') || location.href;

    let modalAnchor = null;

    function portalModalToBody() {
        if (!modal || modal.__ported) return;
        modalAnchor = document.createComment('modal-anchor');
        modal.parentNode.insertBefore(modalAnchor, modal);
        document.body.appendChild(modal);
        modal.__ported = true;
    }

    // Утилита: FormData -> URLSearchParams
    function formToUrlEncoded(formEl) {
        const fd = new FormData(formEl);
        const params = new URLSearchParams();
        for (const [k, v] of fd.entries()) params.append(k, v);
        return params;
    }

    // Показ модалки
    function showSuccess(message, total, currency) {
        try {
            portalModalToBody(); // <— добавили
            if (textEl) {
                textEl.textContent = message || `Ваш заказ принят. Мы свяжемся с вами в ближайшее время.`;
            }
            if (overlay) overlay.style.display = 'block';
            if (modal) modal.style.display = 'block';
            document.body.classList.add('no-scroll');
        } catch (e) {
            console.warn('Cannot show success modal:', e);
            alert(message || 'Заказ оформлен!');
        }
    }

    // Основной перехватчик submit
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // если cart пуст — не уходим
        const cartIsEmpty = !document.querySelector('#cart-lines .product-line-placing');
        if (cartIsEmpty) {
            alert('Корзина пуста');
            return;
        }

        const methodDelivery = form.querySelector('input[name="contact_method"]:checked')?.value || '';
        const methodPickup = form.querySelector('input[name="contact_method_pickup"]:checked')?.value || '';
        const method = (methodDelivery || methodPickup || '').toLowerCase(); // 'tg' | 'ig' | ''

// активное поле с ником — берём то, которое не disabled
        const handleEl = document.querySelector('.contact-method .cm-input:not([disabled])');
        const handle = (handleEl?.value || '').trim();

        const body = formToUrlEncoded(form);
// продублируем выбранный метод (на случай, если это радио было в disabled-блоке)
        if (method) body.set('contact_method', method);
// и пробросим ник в нужное поле, которого нет в форме
        if (handle) {
            if (method === 'tg') body.append('tg_username', handle);
            if (method === 'ig') body.append('instagram_username', handle);
        }
        // Можно явно пробросить сумму из DOM (необязательно, бэкенд считает сам)
        const domTotal = totalEl ? (totalEl.textContent || '').trim() : '';
        if (domTotal) body.append('client_total_hint', domTotal);

        let resp, data;
        try {
            resp = await fetch(SUBMIT_URL, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': CSRF,
                    'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body
            });
        } catch (err) {
            console.error('Network error, fallback to native submit', err);
            // ФОЛБЭК: обычная отправка формы
            form.removeEventListener('submit', arguments.callee);
            form.submit();
            return;
        }

        if (!resp.ok) {
            // 400/500 — попробуем прочитать текст ошибки
            const txt = await resp.text().catch(() => '');
            console.error('Checkout error:', txt || resp.status);
            alert('Не удалось оформить заказ. Проверьте поля и попробуйте ещё раз.');
            return;
        }

        try {
            data = await resp.json();
        } catch {
            // Если вернулся не JSON — тоже фолбэк на нативный POST
            form.removeEventListener('submit', arguments.callee);
            form.submit();
            return;
        }

        if (!data || !data.ok) {
            alert((data && data.message) || 'Не удалось оформить заказ.');
            return;
        }

        // Успех
        const total = data.total || domTotal || '';
        const currency = data.currency || 'BYN';
        const msg = data.message || `Ваш заказ принят. Сумма: ${total} ${currency}. успешно оформлен!`;

        // подчистим мини-корзину в UI
        const linesWrap = document.getElementById('cart-lines');
        if (linesWrap) {
            linesWrap.innerHTML = '<div class="product-line-placing" style="opacity:.7;display:block;padding:24px 0;">Корзина пуста</div>';
        }
        if (totalEl) totalEl.textContent = '0.00';

        showSuccess(msg, total, currency);

        // Если когда-нибудь будет payment_url — редиректим:
        if (data.payment_url) {
            window.location.assign(data.payment_url);
        }
    });
})();
