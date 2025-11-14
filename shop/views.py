from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Q
from .models import Product, Category, NewTabSettings, HomePageSettings, AboutPageSettings, ContactPageSettings, \
    DeliveryPageSettings
from decimal import Decimal, InvalidOperation
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django_countries import countries
from django.conf import settings
from django.urls import reverse
from django.views.generic import TemplateView
from django.db import transaction
from .models import Customer, Order, OrderItem, Payment
from .services import upsert_customer_from_checkout
from django.db.models import Prefetch


class HomeView(TemplateView):
    template_name = "index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        home = HomePageSettings.get_solo()
        ctx["home"] = home
        ctx["home_new_products"] = (
            Product.objects.filter(is_active=True, is_new=True)
            .only("id", "name", "slug", "price_byn", "image")
            .order_by("-id")[:4]
        )
        ctx["featured_blocks"] = home.featured_blocks()
        ctx["menu_sections"] = _menu_sections()  # <-- новое
        return ctx


def catalog(request):
    section_slug  = (request.GET.get("section") or "new").strip()
    category_slug = (request.GET.get("category") or "").strip()
    sort          = (request.GET.get("sort") or "newest").strip()

    # корневые вкладки — по position
    sections = (
        Category.objects
        .filter(parent__isnull=True)
        .order_by("position", "name")
    )

    current_section  = None
    current_category = None
    current_tab      = None
    new_settings     = None
    categories       = Category.objects.none()   # пока пусто

    qs = Product.objects.filter(is_active=True).select_related("category", "category__parent")

    if section_slug == "new":
        current_tab  = "new"
        new_settings = NewTabSettings.get_solo()
        qs = qs.filter(is_new=True)
    else:
        current_section = get_object_or_404(Category, slug=section_slug, parent__isnull=True)

        # подкатегории — тоже по position (БЕЗ is_active)
        categories = (
            Category.objects
            .filter(parent=current_section)
            .order_by("position", "name")
        )

        qs = qs.filter(Q(category=current_section) | Q(category__parent=current_section))

        if category_slug:
            current_category = get_object_or_404(Category, slug=category_slug, parent=current_section)
            qs = qs.filter(category=current_category)

    order_map = {"newest": "-id", "oldest": "id", "price_desc": "-price_byn", "price_asc": "price_byn"}
    qs = qs.order_by(order_map.get(sort, "-id"))

    products = Paginator(qs, 8).get_page(request.GET.get("page"))

    return render(request, "catalog.html", {
        "sections": sections,
        "current_section": current_section,
        "current_category": current_category,
        "current_tab": current_tab,
        "categories": categories,
        "products": products,
        "sort": sort,
        "new_settings": new_settings,
        "menu_sections": _menu_sections(),
    })


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.filter(is_active=True)
        .select_related("category", "category__parent")  # ← добавили parent
        .prefetch_related("photos"),
        slug=slug,
    )

    photos_qs = product.photos.filter(is_active=True).order_by("position", "id")

    # Собираем галерею без дублей (по URL)
    gallery, seen = [], set()

    def push(url, alt, cover=False):
        if not url or url in seen:
            return
        gallery.append({"url": url, "alt": alt, "cover": cover})
        seen.add(url)

    # 1) обложка (если есть и ещё не встречалась среди фото)
    if getattr(product, "image", None):
        push(product.image.url, product.name, cover=True)

    # 2) остальные фото
    for ph in photos_qs:
        push(ph.image.url, ph.alt or product.name, cover=False)

    # Похожие товары: сначала из той же категории (кроме текущего), всего 4
    limit = 4
    base_qs = Product.objects.filter(is_active=True).exclude(pk=product.pk)

    same_cat = list(
        base_qs.filter(category=product.category)
        .select_related("category")
        .only("id", "name", "slug", "price_byn", "image", "category")
        .order_by("-is_new", "-id")[:limit]
    )

    related = same_cat
    if len(related) < limit:
        need = limit - len(related)
        exclude_ids = [p.id for p in related] + [product.id]
        fallback = list(
            Product.objects.filter(is_active=True)
            .exclude(id__in=exclude_ids)
            .only("id", "name", "slug", "price_byn", "image")
            .order_by("-is_new", "-id")[:need]
        )
        related += fallback

    return render(request, "product.html", {
        "product": product,
        "gallery": gallery,
        "related_products": related,
        "menu_sections": _menu_sections(),
    })


def _cart_context(request):
    cart_raw = request.session.get("cart", {})
    if not cart_raw:
        return {"items": [], "total": Decimal(0), "count": 0}

    ids = [int(pid) for pid in cart_raw.keys()]
    products = (
        Product.objects.filter(id__in=ids, is_active=True)
        .only("id", "name", "slug", "price_byn", "image")
    )

    items, total, count = [], Decimal(0), 0
    by_id = {p.id: p for p in products}
    for pid_str, row in cart_raw.items():
        pid = int(pid_str)
        p = by_id.get(pid)
        if not p:
            continue
        qty = max(1, int(row.get("qty", 1)))
        line_total = p.price_byn * qty
        items.append({
            "id": p.id,
            "name": p.name,
            "slug": p.slug,
            "image": (p.image.url if p.image else None),
            "price": p.price_byn,
            "qty": qty,
            "line_total": line_total,
        })
        total += line_total
        count += qty

    return {"items": items, "total": total, "count": count}


def _cart_totals(cart_dict):
    """Подсчитать итоговую сумму и общее кол-во по cart_dict вида {"12":{"qty":2}}."""
    if not cart_dict:
        return Decimal(0), 0
    ids = [int(pid) for pid in cart_dict.keys()]
    by_id = {p.id: p for p in Product.objects.filter(id__in=ids, is_active=True).only("id", "price_byn")}
    total = Decimal(0)
    count = 0
    for pid_str, row in cart_dict.items():
        p = by_id.get(int(pid_str))
        if not p:
            continue
        qty = max(1, int(row.get("qty", 1)))
        total += p.price_byn * qty
        count += qty
    return total, count


@require_POST
def cart_add(request):
    pid = request.POST.get("product_id")
    qty = request.POST.get("qty", "1")

    # Валидация
    try:
        pid = int(pid)
        qty = int(qty)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("bad params")

    qty = min(max(qty, 1), 99)  # 1..99
    # Проверяем, что товар активен
    get_object_or_404(Product, pk=pid, is_active=True)

    cart = request.session.get("cart", {})
    current = cart.get(str(pid), {}).get("qty", 0)
    cart[str(pid)] = {"qty": min(current + qty, 99)}  # накапливаем
    request.session["cart"] = cart
    request.session.modified = True

    total, count = _cart_totals(cart)
    return JsonResponse({"ok": True, "count": count, "total": int(total)})


@require_POST
def cart_update(request):
    pid = request.POST.get("product_id")
    action = request.POST.get("action")  # 'plus' | 'minus' | 'remove' | 'set'
    qty_raw = request.POST.get("qty")

    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("bad pid")

    # убеждаемся, что товар существует и активен (заодно для цены)
    product = get_object_or_404(Product, pk=pid, is_active=True)

    cart = request.session.get("cart", {})
    key = str(pid)
    cur = int(cart.get(key, {}).get("qty", 0))

    if action == "remove":
        cart.pop(key, None)
    elif action == "plus":
        cart[key] = {"qty": min(99, cur + 1)}
    elif action == "minus":
        new_qty = cur - 1
        if new_qty <= 0:
            cart.pop(key, None)
        else:
            cart[key] = {"qty": new_qty}
    elif action == "set":
        try:
            q = int(qty_raw)
        except (TypeError, ValueError):
            return HttpResponseBadRequest("bad qty")
        q = max(0, min(99, q))
        if q <= 0:
            cart.pop(key, None)
        else:
            cart[key] = {"qty": q}
    else:
        return HttpResponseBadRequest("bad action")

    request.session["cart"] = cart
    request.session.modified = True

    # Итоги по корзине
    total, count = _cart_totals(cart)

    # Текущая строка (если не удалили)
    qty = int(cart.get(key, {}).get("qty", 0))
    removed = qty == 0
    line_total = (product.price_byn * qty) if not removed else Decimal(0)

    return JsonResponse({
        "ok": True,
        "removed": removed,
        "qty": qty,
        "line_total": int(line_total),
        "total": int(total),
        "count": count,
    })


def checkout(request):
    cart = _cart_context(request)

    allowed = getattr(settings, "CHECKOUT_ALLOWED_COUNTRIES", [])
    if allowed:
        limited_countries = [(code, name) for code, name in countries if code in allowed]
    else:
        limited_countries = list(countries)

    selected_country = (
            request.GET.get("country")
            or request.session.get("checkout_country")
            or (allowed[0] if allowed else "BY")
    )

    context = {
        "cart": cart,
        "countries": limited_countries,  # ← отдаём урезанный список
        "selected_country": selected_country,
    }
    return render(request, "checkout.html", {**context, "menu_sections": _menu_sections()})


def cart_summary(request):
    """
    JSON для мини-корзины (окно справа):
    { ok, items:[{id,name,slug,image,qty,price,line_total,url,size}], total, count }
    """
    ctx = _cart_context(request)  # <-- используем твою существующую сборку из сессии

    items = []
    for it in ctx["items"]:
        slug = it.get("slug")
        items.append({
            "id": it["id"],
            "name": it["name"],
            "slug": slug or "",
            "image": it.get("image") or "",  # абсолютный урл картинки
            "qty": it["qty"],
            "price": int(it["price"]),
            "line_total": int(it["line_total"]),
            "size": it.get("size", "") or "",
            "url": reverse("shop:product-detail", args=[slug]) if slug else "",
        })

    return JsonResponse({
        "ok": True,
        "items": items,
        "total": int(ctx["total"]),
        "count": ctx["count"],
    })


def search_products(request):
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"ok": True, "items": []})

    qs = (
        Product.objects.filter(is_active=True)
        .filter(
            Q(name__icontains=q) |
            Q(short_desc__icontains=q) |  # <<< у тебя поле short_desc, не description
            Q(category__name__icontains=q)
        )
        .only("id", "name", "slug", "price_byn", "image")
        .order_by("-is_new", "-id")[:10]
    )

    items = [{
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "price": int(p.price_byn),
        "image": (p.image.url if p.image else ""),
        "url": reverse("shop:product-detail", args=[p.slug]),
    } for p in qs]

    return JsonResponse({"ok": True, "items": items})


def _parse_decimal(val, default="0"):
    try:
        return Decimal(str(val).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _get_cart_rows(session):
    """
    Вернёт список (product, qty, price_byn) только по актуальным активным товарам из сессии.
    """
    cart_raw = session.get("cart", {}) or {}
    if not cart_raw:
        return []

    ids = [int(pid) for pid in cart_raw.keys() if str(pid).isdigit()]
    if not ids:
        return []

    by_id = {p.id: p for p in Product.objects.filter(id__in=ids, is_active=True)
    .only("id", "name", "price_byn")}
    rows = []
    for pid_str, row in cart_raw.items():
        try:
            pid = int(pid_str)
        except (TypeError, ValueError):
            continue
        p = by_id.get(pid)
        if not p:
            continue
        qty = max(1, int(row.get("qty", 1)))
        rows.append((p, qty, p.price_byn))
    return rows


def _extract_utm_from_request(request):
    # Можно расширить: вытаскивать _ga, fbclid, реферер, куки и т.д.
    return {
        "utm_source": request.POST.get("utm_source") or request.GET.get("utm_source"),
        "utm_medium": request.POST.get("utm_medium") or request.GET.get("utm_medium"),
        "utm_campaign": request.POST.get("utm_campaign") or request.GET.get("utm_campaign"),
        "utm_content": request.POST.get("utm_content") or request.GET.get("utm_content"),
        "utm_term": request.POST.get("utm_term") or request.GET.get("utm_term"),
        "referrer": request.META.get("HTTP_REFERER"),
    }


def _post(request, key, fallback_keys=()):
    """Удобный геттер POST-полей с тримом и фолбэками."""
    val = (request.POST.get(key) or "").strip()
    if val:
        return val
    for k in fallback_keys:
        v = (request.POST.get(k) or "").strip()
        if v:
            return v
    return ""


@transaction.atomic
@require_POST
def checkout_submit(request):
    """
    Принимает форму из checkout.html и создаёт заказ.
    Возвращает JSON:
      { ok, order_id, order_number, total, currency, message }
    """

    # 1) Корзина
    cart_rows = _get_cart_rows(request.session)
    if not cart_rows:
        return HttpResponseBadRequest("empty cart")

    # 2) Доставка vs Самовывоз
    delivery_provider = _post(request, "delivery_provider")
    country = _post(request, "country")
    city = _post(request, "city")
    pickup_address = _post(request, "pickup_address")
    is_delivery = bool(delivery_provider or country or city)

    # 3) Контакты (берём поля с фолбэками на *_pickup)
    full_name = _post(request, "full_name", ("full_name_pickup",))
    email = _post(request, "email", ("email_pickup",)).lower()
    phone = _post(request, "phone", ("phone_pickup",))

    if not email:
        return HttpResponseBadRequest("email required")

    # Способ связи и хэндлы
    contact_method = _post(request, "contact_method", ("contact_method_pickup",))  # 'email'|'phone'|'tg'|'ig'

    # общий универсальный хэндл (если на форме одно поле для ника)
    contact_handle = _post(
        request, "contact_handle",
        ("contact_handle_pickup", "handle", "contact", "username")
    )

    # целевые поля (если отдельные инпуты тоже есть)
    tg_username = _post(request, "tg_username", ("tg", "telegram"))
    instagram_username = _post(request, "instagram_username", ("ig_username", "instagram", "insta_username"))

    # если выбранный метод есть и заполнен общий хэндл — разложим по нужному полю
    if contact_method == "tg" and contact_handle and not tg_username:
        tg_username = contact_handle
    elif contact_method == "ig" and contact_handle and not instagram_username:
        instagram_username = contact_handle

    # если метод пуст, но заполнен только один ник — определим метод автоматически
    if not contact_method:
        if instagram_username and not tg_username:
            contact_method = "ig"
        elif tg_username and not instagram_username:
            contact_method = "tg"

    # 4) Суммы
    shipping_cost = _parse_decimal(request.POST.get("shipping_cost"), "0")
    discount = _parse_decimal(request.POST.get("discount"), "0")

    # 5) Апсерт профиля клиента по email (авто-нормализация в save())
    pref_map = {
        "email": Customer.ContactPref.EMAIL,
        "phone": Customer.ContactPref.PHONE,
        "tg": Customer.ContactPref.TG,
        "ig": Customer.ContactPref.IG,
    }
    customer = upsert_customer_from_checkout(
        email=email,
        name=full_name,
        phone=phone,
        tg_username=tg_username,
        instagram_username=instagram_username,
        preferred_contact=pref_map.get(contact_method),
    )

    # 6) Хелпер: «срез» контакта для конкретного заказа
    def resolve_contact_value() -> str:
        if contact_method == "email" and email:
            return email
        if contact_method == "phone" and phone:
            return phone
        if contact_method == "tg" and tg_username:
            return tg_username
        if contact_method == "ig" and instagram_username:
            return instagram_username
        # запасной вариант — чтобы заказ точно не остался без контакта
        return customer.preferred_contact_value or email or phone or tg_username or instagram_username

    # 7) Создаём заказ (пока без позиций)
    order = Order.objects.create(
        customer=customer,
        email=email,
        phone=phone,
        contact_method=(contact_method or customer.preferred_contact),
        contact_value=resolve_contact_value(),

        status=Order.Status.NEW,

        # Доставка / самовывоз
        delivery_provider=(delivery_provider if is_delivery else "pickup"),
        delivery_method=("courier" if is_delivery else "pickup"),
        pickup_address=(pickup_address if not is_delivery else ""),
        delivery_address=(f"{country}, {city}, {pickup_address}".strip(", ") if is_delivery else ""),

        # Деньги
        shipping_cost=shipping_cost,
        discount=discount,

        # Прочее
        comment=_post(request, "order_comment"),
        utm=_extract_utm_from_request(request),
        currency="BYN",
    )

    # 8) Позиции + пересчёт
    subtotal = Decimal("0")
    for product, qty, price in cart_rows:
        line_total = price * qty
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,  # срез имени
            sku="",  # если появится product.sku — подставь
            qty=qty,
            price_byn=price,  # срез цены
            line_total=line_total,
        )
        subtotal += line_total

    order.subtotal = subtotal
    order.total = subtotal + shipping_cost - discount
    order.save(update_fields=["subtotal", "total"])

    # 9) (опц.) предварительный платёж PENDING
    Payment.objects.create(
        order=order,
        provider=Payment.Provider.CARD,  # замените при интеграции провайдера
        amount=order.total,
        currency=order.currency,
        status=Payment.PStatus.PENDING,
    )

    # 10) Очистка корзины
    request.session["cart"] = {}
    request.session.modified = True

    # 11) Ответ фронту
    msg = (
        f"Ваш заказ {order.number} на сумму {int(order.total)} {order.currency} оформлен. "
        f"Мы свяжемся с вами для уточнения оплаты."
    )
    return JsonResponse({
        "ok": True,
        "order_id": order.id,
        "order_number": order.number,
        "total": int(order.total),
        "currency": order.currency,
        "message": msg,
        # "payment_url": null  # появится при подключении платёжной сессии
    })


def about(request):
    settings_obj = AboutPageSettings.get_solo()
    return render(request, "about.html", {"about": settings_obj, "menu_sections": _menu_sections()})


def contact(request):
    c = ContactPageSettings.get_solo()
    return render(request, "contact.html", {"contact": c, "ymaps_key": settings.YANDEX_MAPS_API_KEY, "menu_sections": _menu_sections()})


def delivery(request):
    d = DeliveryPageSettings.get_solo()
    return render(request, "delivery.html", {"delivery": d, "menu_sections": _menu_sections()})


def _menu_sections():
    """
    Возвращает дерево категорий для меню:
    """
    parents = Category.objects.filter(parent__isnull=True).order_by("position", "name")
    children_qs = Category.objects.filter(parent__isnull=False).order_by("position", "name")
    sections = list(
        parents.prefetch_related(Prefetch("children", queryset=children_qs, to_attr="subcats"))
    )
    return [
        {
            "slug": s.slug,
            "name": s.name,
            "children": [{"slug": c.slug, "name": c.name} for c in getattr(s, "subcats", [])],
        }
        for s in sections
    ]