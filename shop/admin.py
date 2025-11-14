# admin.py
from decimal import Decimal

from django import forms
from django.contrib import admin
from django.db import models
from django.db.models import F, Sum, Value, DecimalField
from django.db.models.expressions import ExpressionWrapper
from django.db.models.functions import Coalesce, Cast
from django.forms import Textarea
from django.http import JsonResponse
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse, path
from django.utils.html import format_html

from ckeditor_uploader.widgets import CKEditorUploadingWidget
from image_cropping import ImageCroppingMixin

from .models import (
    Category, Product, ProductPhoto, NewTabSettings, HomePageSettings,
    AboutPageSettings, ContactPageSettings, DeliveryPageSettings,
    Customer, Order, OrderItem, Payment, Shipment
)

# ---------------------------------------------------------------------
# КОНСТАНТЫ СТИЛЕЙ (единые)
# ---------------------------------------------------------------------
COMMON = "width:25rem !important; min-width:25rem !important; max-width:none !important;"
NARROW = "width:8rem !important; min-width:8rem !important; max-width:8rem !important; text-align:right;"
TEXTINPUT_MAX = 50
TEXTAREA_MAX = 300

# =====================================================================
# ============================ КАТАЛОГ ================================
# =====================================================================

# --- Категории
@admin.register(Category)
class CategoryAdmin(ImageCroppingMixin, admin.ModelAdmin):
    list_display = ("name", "position", "parent", "banner_preview")
    list_editable = ("position",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    change_list_template = "admin/shop/category/change_list.html"

    formfield_overrides = {
        models.TextField: {"widget": Textarea(attrs={"rows": 3, "style": "width:100%;"})},
    }

    fieldsets = (
        (None, {"fields": ("name", "slug", "parent", "position")}),
        ("Баннер", {
            "fields": ("banner_image", "banner_crop", "banner_text"),
            "description": (
                "Баннер показывается у родительских категорий вверху каталога. "
                "Кадрирование — через «Обрезка баннера»."
            ),
        }),
    )

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        obj = NewTabSettings.get_solo()
        opts = NewTabSettings._meta
        extra_context["newtab_url"] = reverse(
            f"admin:{opts.app_label}_{opts.model_name}_change",
            args=[obj.pk],
        )
        return super().changelist_view(request, extra_context=extra_context)

    def get_fieldsets(self, request, obj=None):
        if obj and obj.parent_id:
            return ((None, {"fields": ("name", "slug", "parent")}),)
        return super().get_fieldsets(request, obj)

    def banner_preview(self, obj):
        if obj.banner_image:
            return format_html(
                '<img src="{}" style="height:60px;border-radius:4px;object-fit:cover;object-position:center;">',
                obj.banner_image.url,
            )
        return "—"

    banner_preview.short_description = "Баннер"


# --- Фото товара (inline)
class ProductPhotoInline(ImageCroppingMixin, admin.TabularInline):
    model = ProductPhoto
    fields = ("preview", "image", "image_crop", "alt", "position", "is_active")
    readonly_fields = ("preview",)
    ordering = ("position", "id")
    min_num, max_num, validate_min, extra = 3, 3, True, 0
    verbose_name_plural = "Галерея товара (первое фото — обложка, всего 3)"

    def get_extra(self, request, obj=None, **kwargs):
        if obj:
            have = obj.photos.count()
            return max(0, self.max_num - have)
        return self.max_num

    def preview(self, obj):
        if obj and getattr(obj, "image", None):
            return format_html('<img src="{}" style="height:60px;"/>', obj.image.url)
        return "—"

    preview.short_description = "Превью"


class ProductAdminForm(forms.ModelForm):
    # === TextInput-поля с лимитом 50 ===
    name        = forms.CharField(
        max_length=TEXTINPUT_MAX,
        widget=forms.TextInput(attrs={"style": COMMON, "maxlength": TEXTINPUT_MAX}),
        label="Название",
    )
    size_title  = forms.CharField(
        required=False, max_length=TEXTINPUT_MAX,
        widget=forms.TextInput(attrs={"style": COMMON, "maxlength": TEXTINPUT_MAX}),
        label="Заголовок размера",
    )
    size_value  = forms.CharField(
        required=False, max_length=TEXTINPUT_MAX,
        widget=forms.TextInput(attrs={"style": COMMON, "maxlength": TEXTINPUT_MAX}),
        label="Размер",
    )
    slug        = forms.SlugField(
        max_length=TEXTINPUT_MAX,
        widget=forms.TextInput(attrs={"style": COMMON, "maxlength": TEXTINPUT_MAX}),
    )
    short_desc = forms.CharField(
        required=False, max_length=TEXTAREA_MAX,
        widget=forms.TextInput(attrs={"style": COMMON, "maxlength": TEXTAREA_MAX}),
        label="Короткое описание",
    )
    extra_text = forms.CharField(
        required=False, max_length=TEXTAREA_MAX,
        widget=forms.Textarea(attrs={"style": COMMON + "height:10rem;", "maxlength": TEXTAREA_MAX}),
        label="Текст «Дополнительно»",
    )

    class Meta:
        model = Product
        fields = "__all__"
        widgets = {
            "price_byn":  forms.NumberInput(attrs={"style": COMMON}),
            "category":   forms.Select(attrs={"style": COMMON}),
        }


# --- Товары (с lookup JSON + автоподстановкой главного фото)
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ("name", "category", "price_byn", "is_new", "is_active")
    list_filter = ("is_active", "is_new", "category")
    search_fields = ("name", "slug", "id", "category__name")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductPhotoInline]
    exclude = ("image",)

    fieldsets = (
        ("Описание", {
            "classes": ("wide",),
            "description": "Поля расположены в том же порядке, как на странице товара.",
            "fields": (
                "name", "short_desc",
                "size_title", "size_value",
                "price_byn",
                "extra_text",
                "category", "slug",
                "is_new", "is_active",
            ),
        }),
    )

    # Показываем только активные товары в автокомплите
    def get_search_results(self, request, queryset, search_term):
        qs, use_distinct = super().get_search_results(request, queryset, search_term)
        rm = getattr(request, "resolver_match", None)
        is_autocomplete = bool(rm and rm.url_name and rm.url_name.endswith("_autocomplete"))
        if is_autocomplete:
            qs = qs.filter(is_active=True)
        return qs, use_distinct

    # JSON lookup: отдаём цену и название по pk (для JS в инлайне позиций заказа)
    def get_urls(self):
        return [
            path("lookup/<int:pk>/", self.admin_site.admin_view(self.lookup_view),
                 name="shop_product_lookup"),
        ] + super().get_urls()

    def lookup_view(self, request, pk: int):
        obj = get_object_or_404(Product, pk=pk)
        return JsonResponse({"id": obj.pk, "name": obj.name, "price_byn": str(obj.price_byn)})

    # После сохранения инлайнов берём первое активное фото и ставим в product.image
    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        product = form.instance
        first = product.photos.filter(is_active=True).order_by("position", "id").first()
        if first and (not product.image or product.image.name != first.image.name):
            product.image = first.image  # тот же файл, без копирования
            product.save(update_fields=["image"])


# --- Вспомогательный ProductPhotoAdmin (скрыт в меню, но доступен по URL)
@admin.register(ProductPhoto)
class ProductPhotoAdmin(ImageCroppingMixin, admin.ModelAdmin):
    list_display = ("product", "position", "is_active")
    list_filter = ("is_active",)
    ordering = ("product", "position")
    fields = ("product", "image", "image_crop", "alt", "position", "is_active")

    # полностью скрыть из всех списков приложений
    def has_module_permission(self, request):
        return False

    # не давать открывать список по прямому URL
    def has_view_permission(self, request, obj=None):
        return False

    # на всякий случай — не публиковать модель в app_list
    def get_model_perms(self, request):
        return {}


# --- Вкладка «Новинки» (скрытый singleton)
@admin.register(NewTabSettings)
class NewTabSettingsAdmin(ImageCroppingMixin, admin.ModelAdmin):
    list_display = ("banner_preview",)

    formfield_overrides = {
        models.TextField: {"widget": Textarea(attrs={"rows": 3, "style": "width:100%;"})},
    }

    fieldsets = (
        ("Баннер вкладки «Новинки»", {
            "fields": ("banner_image", "banner_crop", "banner_text"),
            "description": (
                "Баннер показывается вверху вкладки «Новинки». "
                "Кадрирование — через «Обрезка баннера»."
            ),
        }),
    )

    def has_module_permission(self, request): return False
    def has_add_permission(self, request): return not NewTabSettings.objects.exists()
    def has_delete_permission(self, request, obj=None): return False

    def changelist_view(self, request, extra_context=None):
        obj = NewTabSettings.get_solo()
        return redirect(f"{obj.pk}/change/")

    def banner_preview(self, obj):
        if obj.banner_image:
            return format_html(
                '<img src="{}" style="height:60px;border-radius:4px;object-fit:cover;object-position:center;">',
                obj.banner_image.url,
            )
        return "—"

    banner_preview.short_description = "Баннер"


# =====================================================================
# ======================= КОНТЕНТ И СТРАНИЦЫ ==========================
# =====================================================================

@admin.register(HomePageSettings)
class HomePageSettingsAdmin(ImageCroppingMixin, admin.ModelAdmin):
    list_display = ("hero_preview",)
    # базовый скелет — чтобы был заголовок и описание
    fieldsets = (
        ("Герой", {"fields": ("hero_image", "hero_crop")}),
        ("Блоки каталога на главной", {
            "fields": (),  # заполним динамически
            "description": "Выбери раздел, подпись и откадрируй картинку под плитку.",
        }),
    )

    def get_fieldsets(self, request, obj=None):
        fs = list(super().get_fieldsets(request, obj))

        rows = []
        for i in (1, 2, 3):
            row = [f"featured_{i}", f"featured_{i}_title", f"featured_{i}_image"]
            # crop добавляем только если картинка уже есть на объекте
            if obj and getattr(obj, f"featured_{i}_image"):
                row.append(f"featured_{i}_crop")
            rows.append(tuple(row))

        # подменяем поля второго филдсета
        fs[1][1]["fields"] = tuple(rows)
        return fs

    def has_add_permission(self, request):
        return not HomePageSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = HomePageSettings.get_solo()
        return redirect(f"{obj.pk}/change/")

    def hero_preview(self, obj):
        if obj.hero_image:
            return format_html('<img src="{}" style="height:60px;border-radius:6px;object-fit:cover;">', obj.hero_image.url)
        return "—"
    hero_preview.short_description = "Превью"


@admin.register(AboutPageSettings)
class AboutPageSettingsAdmin(ImageCroppingMixin, admin.ModelAdmin):
    list_display = ("title", "b1_preview", "b2_preview", "b3_preview")
    fieldsets = (
        ("Хедер", {"fields": ("title", "intro_text"), "description": "Верхняя часть страницы."}),
        ("Блок 1", {"fields": ("block1_image", "block1_crop", "block1_text")}),
        ("Блок 2", {"fields": ("block2_image", "block2_crop", "block2_text")}),
        ("Блок 3", {"fields": ("block3_image", "block3_crop", "block3_text")}),
    )

    def has_add_permission(self, request): return not AboutPageSettings.objects.exists()
    def has_delete_permission(self, request, obj=None): return False

    def changelist_view(self, request, extra_context=None):
        obj = AboutPageSettings.get_solo()
        return redirect(f"{obj.pk}/change/")

    def _preview(self, img):
        if img:
            return format_html('<img src="{}" style="height:60px;border-radius:4px;object-fit:cover;">', img.url)
        return "—"

    def b1_preview(self, obj): return self._preview(obj.block1_image)
    def b2_preview(self, obj): return self._preview(obj.block2_image)
    def b3_preview(self, obj): return self._preview(obj.block3_image)

    b1_preview.short_description = "Блок 1"
    b2_preview.short_description = "Блок 2"
    b3_preview.short_description = "Блок 3"


@admin.register(ContactPageSettings)
class ContactPageSettingsAdmin(admin.ModelAdmin):
    list_display = ("title", "instagram_username", "email")
    fieldsets = (
        ("Верхняя часть", {"fields": ("title", "address_text")}),
        ("Контакты", {"fields": ("instagram_username", "instagram_url", "email")}),
        ("Карта (на будущее)", {
            "fields": ("map_lat", "map_lng", "map_zoom"),
            "description": "Координаты для карты. Подключим рендер позже.",
        }),
    )

    def has_add_permission(self, request): return not ContactPageSettings.objects.exists()
    def has_delete_permission(self, request, obj=None): return False

    def changelist_view(self, request, extra_context=None):
        obj = ContactPageSettings.get_solo()
        return redirect(f"{obj.pk}/change/")


class DeliveryPageSettingsForm(forms.ModelForm):
    body_text = forms.CharField(label="Текст страницы", required=False, widget=CKEditorUploadingWidget())
    class Meta:
        model = DeliveryPageSettings
        fields = "__all__"


@admin.register(DeliveryPageSettings)
class DeliveryPageSettingsAdmin(ImageCroppingMixin, admin.ModelAdmin):
    form = DeliveryPageSettingsForm
    list_display = ("title", "left_preview", "right_preview")
    fieldsets = (
        ("Верхняя часть", {"fields": ("title", "body_text")}),
        ("Фотографии", {"fields": ("image_left", "image_left_crop", "image_right", "image_right_crop")}),
    )

    def has_add_permission(self, request): return not DeliveryPageSettings.objects.exists()
    def has_delete_permission(self, request, obj=None): return False

    def changelist_view(self, request, extra_context=None):
        obj = DeliveryPageSettings.get_solo()
        return redirect(f"{obj.pk}/change/")

    def _preview(self, img):
        if img:
            return format_html('<img src="{}" style="height:60px;border-radius:4px;object-fit:cover;">', img.url)
        return "—"

    def left_preview(self, obj): return self._preview(obj.image_left)
    def right_preview(self, obj): return self._preview(obj.image_right)

    left_preview.short_description = "Фото слева"
    right_preview.short_description = "Фото справа"


# =====================================================================
# =========================== ОПЕРАЦИИ ================================
# =====================================================================

# --- Клиенты + история заказов (inline)
class CustomerOrderInline(admin.TabularInline):
    model = Order
    fk_name = "customer"
    extra = 0
    can_delete = False
    show_change_link = True
    ordering = ("-created_at",)
    verbose_name = "Заказ"
    verbose_name_plural = "История заказов"

    fields = ("number", "status_badge_inline", "email", "total_price_inline", "created_at")
    readonly_fields = ("number", "status_badge_inline", "email", "total_price_inline", "created_at")

    @admin.display(description="Статус")
    def status_badge_inline(self, obj):
        colors = {
            "new": "#2563eb", "paid": "#16a34a", "fulfilling": "#a16207",
            "shipped": "#0891b2", "done": "#065f46", "canceled": "#dc2626",
        }
        c = colors.get(obj.status, "#374151")
        return format_html('<span style="padding:2px 8px;border-radius:12px;background:{};color:#fff;">{}</span>',
                           c, obj.get_status_display())

    @admin.display(description="Цена", ordering="total")
    def total_price_inline(self, obj): return obj.total

    def has_add_permission(self, request, obj=None):  # историю руками не добавляем
        return False


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "phone", "created_at", "orders_count")
    search_fields = ("email", "name", "phone")
    readonly_fields = ("created_at",)
    inlines = [CustomerOrderInline]

    def orders_count(self, obj): return obj.orders.count()
    orders_count.short_description = "Заказов"


# --- Платёж (standalone admin)
class PaymentAdminForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = "__all__"
        widgets = {
            "provider":            forms.Select(attrs={"style": COMMON}),
            "status":              forms.Select(attrs={"style": COMMON}),
            "amount":              forms.NumberInput(attrs={"style": COMMON}),
            "currency":            forms.TextInput(attrs={"style": COMMON}),
            "provider_payment_id": forms.TextInput(attrs={"style": COMMON}),
            "comment":             forms.Textarea(attrs={"style": COMMON + "height:10rem;"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"].label = "Способ оплаты"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    form = PaymentAdminForm
    exclude = ("raw",)  # JSON-поле не показываем
    list_display = ("id", "order", "provider", "status", "amount", "currency", "created_at")
    list_filter = ("provider", "status", ("created_at", admin.DateFieldListFilter))
    search_fields = ("provider_payment_id", "order__number")
    autocomplete_fields = ("order",)
    readonly_fields = ("created_at",)


# --- Отгрузка (standalone admin)
class ShipmentAdminForm(forms.ModelForm):
    class Meta:
        model = Shipment
        fields = ("order", "provider", "tracking_number", "status")
        widgets = {
            "order":           forms.Select(attrs={"style": COMMON}),
            "provider":        forms.TextInput(attrs={"style": COMMON, "placeholder": "СДЭК / Яндекс / ..."}),
            "tracking_number": forms.TextInput(attrs={"style": COMMON, "placeholder": "Трек-номер"}),
            "status":          forms.TextInput(attrs={"style": COMMON, "placeholder": "Создан"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"].label = "Служба"
        self.fields["tracking_number"].label = "Трек-номер"
        self.fields["status"].label = "Статус отгрузки"


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    form = ShipmentAdminForm
    readonly_fields = ("created_at",)
    fields = ("order", "provider", "tracking_number", "status", "created_at")


# ========================== ЗАКАЗЫ ===========================

# --- Форма заказа
class OrderAdminForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = "__all__"

    PROVIDER_RU = {
        "yandex": "Яндекс",
        "cdek": "СДЭК",
        "evropochta": "Европочта",
        "autolight": "Автолайт",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        WIDTH = "25rem"
        TEXT_STYLE = f"width:{WIDTH};min-width:{WIDTH};"
        SELECT_STYLE = f"width:{WIDTH};min-width:{WIDTH};"

        for name in ("email", "phone"):
            if name in self.fields:
                self.fields[name].widget.attrs.update(style=TEXT_STYLE)
        if "customer" in self.fields:
            self.fields["customer"].widget.attrs.update(style=SELECT_STYLE)

        if "delivery_provider" in self.fields:
            f = self.fields["delivery_provider"]
            f.label = "Способ доставки"
            f.help_text = None
            choices = list(getattr(f, "choices", []) or [])
            if choices:
                norm = []
                for key, label in choices:
                    key_l = (key or "").lower()
                    norm.append((key, self.PROVIDER_RU.get(key_l, label or key)))
                choices = norm
            else:
                choices = [("cdek", "СДЭК"), ("yandex", "Яндекс"),
                           ("evropochta", "Европочта"), ("autolight", "Автолайт")]
            f.widget = forms.Select(choices=choices, attrs={"style": SELECT_STYLE})

        if "delivery_address" in self.fields:
            self.fields["delivery_address"].label = "Адрес доставки"
            self.fields["delivery_address"].help_text = None
            self.fields["delivery_address"].widget.attrs.update(style=TEXT_STYLE)

        if "comment" in self.fields:
            self.fields["comment"].label = "Комментарий покупателя"
            self.fields["comment"].widget.attrs.update(style=f"{TEXT_STYLE}height:10rem;")

    def clean_delivery_provider(self):
        val = (self.cleaned_data.get("delivery_provider") or "").strip()
        return val.lower()


# --- Инлайны к заказу
class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = ("product", "qty", "price_byn")  # только редактируемые поля

    def clean(self):
        cleaned = super().clean()
        p = cleaned.get("product")
        if p and not cleaned.get("price_byn"):
            cleaned["price_byn"] = p.price_byn
        if not cleaned.get("qty"):
            cleaned["qty"] = 1
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.line_total = (obj.qty or 0) * (obj.price_byn or 0)  # серверный пересчёт
        if commit:
            obj.save()
        return obj


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    form = OrderItemForm
    fields = ("product", "qty", "price_byn", "line_total")
    readonly_fields = ("line_total",)
    autocomplete_fields = ("product",)
    extra = 0
    can_delete = True
    verbose_name = "товар"
    verbose_name_plural = "Позиции заказа"

    # как правило, jquery.init уже есть; оставим чисто queryset
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "product":
            kwargs["queryset"] = Product.objects.filter(is_active=True).only("id", "name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("product")


# --- Заказы (основная форма)
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    form = OrderAdminForm

    exclude = ("utm",)
    date_hierarchy = "created_at"
    list_display = ("number", "status_badge", "email", "total_price", "created_at")
    # если у Order нет currency — не добавляй его сюда
    list_filter = ("status", "delivery_provider", "delivery_method",
                   ("created_at", admin.DateFieldListFilter))
    search_fields = ("number", "email", "phone")
    autocomplete_fields = ("customer",)

    readonly_fields = (
        "number", "created_at", "paid_at", "subtotal", "total",
        "number_plain", "created_at_plain", "paid_at_plain",
        "customer_email_plain", "customer_name_plain", "customer_phone_plain",
        "customer_tg_plain", "customer_ig_plain", "customer_pref_plain",
        "pickup_info",
    )

    fieldsets = (
        ("Основное", {
            "classes": ("wide",),
            "fields": (
                ("number_plain", "status"),
                ("created_at_plain", "paid_at_plain"),
                ("customer",),
                "customer_email_plain", "customer_name_plain", "customer_phone_plain",
                "customer_tg_plain", "customer_ig_plain", "customer_pref_plain",
            ),
        }),
        ("Доставка", {"classes": ("wide",), "fields": ("pickup_info",)}),
        ("Комментарий", {"classes": ("wide",), "fields": ("comment",)}),
    )

    inlines = [OrderItemInline]

    # утилита для read-only «plain»-полей
    @staticmethod
    def _box(val: str):
        return format_html('<div style="width:25rem;min-width:25rem;">{}</div>', val or "—")

    @admin.display(description="Самовывоз")
    def pickup_info(self, obj):
        return self._box("Самовывоз — Тимирязева 65Б, пом. 903")

    # динамический набор полей раздела «Доставка»
    def _is_pickup(self, obj):
        if not obj:
            return False
        prov = (obj.delivery_provider or "").lower()
        meth = (obj.delivery_method or "").lower()
        return prov == "pickup" or meth == "pickup"

    def get_fieldsets(self, request, obj=None):
        base = list(super().get_fieldsets(request, obj))
        out = []
        for title, opts in base:
            if title != "Доставка":
                out.append((title, opts))
                continue
            if self._is_pickup(obj):
                out.append(("Доставка", {"classes": ("wide",), "fields": ("pickup_info",)}))
            else:
                out.append(("Доставка", {"classes": ("wide",), "fields": ("delivery_provider", "delivery_address")}))
        return out

    # пересчёт тоталов после сохранения инлайнов
    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        order = form.instance

        dec12_2 = DecimalField(max_digits=12, decimal_places=2)
        line_total_expr = ExpressionWrapper(
            Cast(F("qty"), dec12_2) * Cast(F("price_byn"), dec12_2),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
        subtotal = OrderItem.objects.filter(order=order).aggregate(
            s=Coalesce(Sum(line_total_expr), Value(Decimal("0.00")),
                       output_field=DecimalField(max_digits=18, decimal_places=2))
        )["s"]

        order.subtotal = subtotal
        order.total = order.subtotal  # + (order.shipping_cost or 0) - (order.discount or 0)
        order.save(update_fields=["subtotal", "total"])

        if hasattr(order, "_prefetched_objects_cache"):
            order._prefetched_objects_cache.pop("items", None)

    # read-only поля
    @admin.display(description="Цена", ordering="total")
    def total_price(self, obj):
        return obj.total

    @admin.display(description="E-mail")
    def customer_email_plain(self, obj):
        return self._box(getattr(obj.customer, "email", None))

    @admin.display(description="Имя")
    def customer_name_plain(self, obj):
        return self._box(getattr(obj.customer, "name", None))

    @admin.display(description="Телефон")
    def customer_phone_plain(self, obj):
        return self._box(getattr(obj.customer, "phone", None))

    @admin.display(description="Telegram")
    def customer_tg_plain(self, obj):
        u = getattr(obj.customer, "tg_username", None)
        return self._box(f"@{u}" if u else None)

    @admin.display(description="Instagram")
    def customer_ig_plain(self, obj):
        u = getattr(obj.customer, "instagram_username", None)
        return self._box(f"@{u}" if u else None)

    @admin.display(description="Предпочтительный способ связи")
    def customer_pref_plain(self, obj):
        cust = getattr(obj, "customer", None)
        return self._box(cust.get_preferred_contact_display() if cust and cust.preferred_contact else None)

    @admin.display(description="Номер заказа")
    def number_plain(self, obj):
        return self._box(obj.number)

    @admin.display(description="Создан")
    def created_at_plain(self, obj):
        val = obj.created_at.strftime("%d %B %Y г. %H:%M") if obj.created_at else "—"
        return self._box(val)

    @admin.display(description="Оплачен в")
    def paid_at_plain(self, obj):
        val = obj.paid_at.strftime("%d %B %Y г. %H:%M") if obj.paid_at else "—"
        return self._box(val)

    @admin.display(description="Статус")
    def status_badge(self, obj):
        colors = {
            "new": "#2563eb", "paid": "#16a34a", "fulfilling": "#a16207",
            "shipped": "#0891b2", "done": "#065f46", "canceled": "#dc2626",
        }
        c = colors.get(obj.status, "#374151")
        return format_html(
            '<span style="padding:2px 8px;border-radius:12px;background:{};color:#fff;">{}</span>',
            c, obj.get_status_display()
        )