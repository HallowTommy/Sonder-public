from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.text import slugify
from image_cropping import ImageRatioField
from decimal import Decimal
from django.core.validators import RegexValidator

username_validator = RegexValidator(
    regex=r'^[A-Za-z0-9._]{2,30}$',
    message="Только латинские буквы/цифры/._, 2–30 символов."
)


class BannerFieldsMixin(models.Model):
    banner_image = models.ImageField(
        "Баннер (реком. 1920×820)",
        upload_to="banners/",
        null=True,
        blank=True,
    )
    banner_crop = ImageRatioField(
        "banner_image",
        "1920x820",
        verbose_name="Обрезка баннера",
    )
    banner_text = models.TextField("Текст на баннере", blank=True)

    class Meta:
        abstract = True


class Category(BannerFieldsMixin, models.Model):
    name = models.CharField("Название", max_length=200)
    slug = models.SlugField("Слаг", unique=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, related_name="children",
        on_delete=models.CASCADE, verbose_name="Родительская категория",
    )

    position = models.PositiveSmallIntegerField(
        "Порядок", default=100, db_index=True,
        help_text="Чем меньше число, тем выше категория в меню"
    )

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"
        ordering = ["position", "name"]

    def __str__(self):
        return f"{self.parent.name} — {self.name}" if self.parent else self.name

    # запретить коллизию со вкладкой «Новинки»
    def clean(self):
        super().clean()
        if (self.slug or "").lower() == "new":
            raise ValidationError(
                {"slug": "Слаг 'new' зарезервирован для вкладки «Новинки'."}
            )


class NewTabSettings(BannerFieldsMixin, models.Model):
    """
    Единственные настройки для вкладки «Новинки»
    (баннер как у родительских категорий).
    """

    class Meta:
        verbose_name = "Вкладка «Новинки»"
        verbose_name_plural = "Вкладка «Новинки»"

    def __str__(self):
        return "Настройки вкладки «Новинки»"

    @classmethod
    def get_solo(cls):
        """Гарантированно вернуть одну запись (создаст при первом доступе)."""
        obj = cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj

    # Страховка от второй записи, если кто-то создаст через shell/скрипт
    def save(self, *args, **kwargs):
        if not self.pk and NewTabSettings.objects.exists():
            raise ValidationError(
                "Разрешена только одна запись настроек вкладки «Новинки»."
            )
        return super().save(*args, **kwargs)


class Product(models.Model):
    name = models.CharField("Название", max_length=200)
    slug = models.SlugField("Слаг", max_length=220, unique=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="Категория",
    )
    price_byn = models.DecimalField(
        "Цена, BYN",
        max_digits=10,
        decimal_places=0,
    )
    is_active = models.BooleanField("Показывать на сайте", default=True, db_index=True)
    is_new = models.BooleanField("Новинка", default=False, db_index=True)
    short_desc = models.TextField(
        "Короткое описание",
        max_length=240,
        blank=True,
    )
    image = models.ImageField("Обложка", upload_to="products/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    size_title = models.CharField(
        "Заголовок блока размера",
        max_length=50,
        default="Размер",
    )
    size_value = models.CharField(
        "Размер / объём",
        max_length=100,
        blank=True,
        default="",
    )
    extra_text = models.TextField("Текст «Дополнительно»", blank=True, default="")

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["is_active", "is_new"]),
            models.Index(fields=["category", "is_active"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("shop:product-detail", kwargs={"slug": self.slug})


class ProductPhoto(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="photos", verbose_name="Товар")
    image = models.ImageField("Фото", upload_to="products/photos/")
    image_crop = ImageRatioField("image", "1000x1000", verbose_name="Обрезка")
    alt = models.CharField("Alt-текст", max_length=200, blank=True)
    position = models.PositiveIntegerField("Порядок", default=0)
    is_active = models.BooleanField("Показывать", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Фото товара"
        verbose_name_plural = "Фото товара"
        ordering = ["position", "id"]
        indexes = [
            models.Index(fields=["product", "is_active", "position"]),
        ]

    def __str__(self):
        return f"{self.product.name} — фото #{self.pk}"


class HomePageSettings(models.Model):
    hero_image = models.ImageField(
        "Фоновое фото (герой)",
        upload_to="homepage/",
        blank=True,
        null=True,
    )
    hero_crop = ImageRatioField(
        "hero_image",
        "1920x820",
        verbose_name="Обрезка героя",
    )

    # --- блоки каталога
    featured_1 = models.ForeignKey(
        Category,
        verbose_name="Блок 1 — раздел",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        limit_choices_to={"parent__isnull": True},
    )
    featured_1_title = models.CharField(
        "Блок 1 — подпись",
        max_length=100,
        blank=True,
        default="",
    )
    featured_1_image = models.ImageField(
        "Блок 1 — фон",
        upload_to="homepage/featured/",
        null=True,
        blank=True,
    )
    featured_1_crop = ImageRatioField(
        "featured_1_image",
        "1000x1000",
        verbose_name="Обрезка блока 1",
    )

    featured_2 = models.ForeignKey(
        Category,
        verbose_name="Блок 2 — раздел",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        limit_choices_to={"parent__isnull": True},
    )
    featured_2_title = models.CharField(
        "Блок 2 — подпись",
        max_length=100,
        blank=True,
        default="",
    )
    featured_2_image = models.ImageField(
        "Блок 2 — фон",
        upload_to="homepage/featured/",
        null=True,
        blank=True,
    )
    featured_2_crop = ImageRatioField(
        "featured_2_image",
        "1000x1000",
        verbose_name="Обрезка блока 2",
    )

    featured_3 = models.ForeignKey(
        Category,
        verbose_name="Блок 3 — раздел",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        limit_choices_to={"parent__isnull": True},
    )
    featured_3_title = models.CharField(
        "Блок 3 — подпись",
        max_length=100,
        blank=True,
        default="",
    )
    featured_3_image = models.ImageField(
        "Блок 3 — фон",
        upload_to="homepage/featured/",
        null=True,
        blank=True,
    )
    featured_3_crop = ImageRatioField(
        "featured_3_image",
        "1000x1000",
        verbose_name="Обрезка блока 3",
    )

    def featured_blocks(self):
        rows = []
        triples = (
            (self.featured_1, self.featured_1_title, self.featured_1_image),
            (self.featured_2, self.featured_2_title, self.featured_2_image),
            (self.featured_3, self.featured_3_title, self.featured_3_image),
        )

        for idx, (cat, title, img) in enumerate(triples, start=1):
            if not cat:
                continue

            crop_name = f"featured_{idx}_crop" if img else None
            rows.append(
                {
                    "slug": cat.slug,
                    "title": title or cat.name,
                    "image": (
                        img.url
                        if img
                        else (cat.banner_image.url if cat.banner_image else "")
                    ),
                    "crop": crop_name,  # ← важно
                }
            )
        return rows

    class Meta:
        verbose_name = "Страница «Главная»"
        verbose_name_plural = "Страница «Главная»"

    def __str__(self):
        return "Настройки главной"

    @classmethod
    def get_solo(cls):
        return cls.objects.first() or cls.objects.create()


class AboutPageSettings(models.Model):
    # Хедер
    title = models.CharField("Заголовок", max_length=120, default="О НАС")
    intro_text = models.TextField("Интро-текст", blank=True, default="")

    # Блок 1
    block1_image = models.ImageField(
        "Блок 1 — фото",
        upload_to="about/",
        blank=True,
        null=True,
    )
    block1_crop = ImageRatioField(
        "block1_image",
        "1000x1000",
        verbose_name="Обрезка блока 1",
    )
    block1_text = models.TextField("Блок 1 — текст", blank=True, default="")

    # Блок 2
    block2_image = models.ImageField(
        "Блок 2 — фото",
        upload_to="about/",
        blank=True,
        null=True,
    )
    block2_crop = ImageRatioField(
        "block2_image",
        "1000x1000",
        verbose_name="Обрезка блока 2",
    )
    block2_text = models.TextField("Блок 2 — текст", blank=True, default="")

    # Блок 3
    block3_image = models.ImageField(
        "Блок 3 — фото",
        upload_to="about/",
        blank=True,
        null=True,
    )
    block3_crop = ImageRatioField(
        "block3_image",
        "1000x1000",
        verbose_name="Обрезка блока 3",
    )
    block3_text = models.TextField("Блок 3 — текст", blank=True, default="")

    class Meta:
        verbose_name = "Страница «О нас»"
        verbose_name_plural = "Страница «О нас»"

    def __str__(self):
        return "Настройки «О нас»"

    @classmethod
    def get_solo(cls):
        return cls.objects.first() or cls.objects.create()

    # страховка от дубликатов при прямом создании
    def save(self, *args, **kwargs):
        if not self.pk and AboutPageSettings.objects.exists():
            raise ValidationError(
                "Разрешена только одна запись настроек «О нас»."
            )
        return super().save(*args, **kwargs)


class ContactPageSettings(models.Model):
    title = models.CharField("Заголовок", max_length=120, default="КОНТАКТЫ")
    address_text = models.TextField(
        "Адрес / описание",
        blank=True,
        default=(
            "Адрес мастерской:\n"
            "ул. Тимирязева 65б, пом.903, 9 этаж\n"
            "(посещение по предварительной договоренности)"
        ),
    )
    instagram_username = models.CharField(
        "Instagram (username)",
        max_length=120,
        blank=True,
        default="sonder.homefeeling",
    )
    instagram_url = models.URLField(
        "Instagram (URL)",
        blank=True,
        default="https://www.instagram.com/sonder.homefeeling/",
    )
    email = models.EmailField(
        "E-mail",
        blank=True,
        default="sonder.homefeeling@gmail.com",
    )
    map_lat = models.DecimalField(
        "Широта",
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
    )
    map_lng = models.DecimalField(
        "Долгота",
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
    )
    map_zoom = models.PositiveSmallIntegerField("Зум карты", default=16)

    class Meta:
        verbose_name = "Страница «Контакты»"
        verbose_name_plural = "Страница «Контакты»"

    def __str__(self):
        return "Настройки «Контакты»"

    @classmethod
    def get_solo(cls):
        return cls.objects.first() or cls.objects.create()

    def save(self, *args, **kwargs):
        if not self.pk and ContactPageSettings.objects.exists():
            raise ValidationError(
                "Разрешена только одна запись настроек «Контакты»."
            )
        return super().save(*args, **kwargs)


class DeliveryPageSettings(models.Model):
    title = models.CharField(
        "Заголовок",
        max_length=120,
        default="ДОСТАВКА И ОПЛАТА",
    )
    body_text = models.TextField("Текст страницы", blank=True, default="")
    image_left = models.ImageField(
        "Фото слева",
        upload_to="delivery/",
        blank=True,
        null=True,
    )
    image_left_crop = ImageRatioField(
        "image_left",
        "1000x1000",
        verbose_name="Обрезка слева",
    )
    image_right = models.ImageField(
        "Фото справа",
        upload_to="delivery/",
        blank=True,
        null=True,
    )
    image_right_crop = ImageRatioField(
        "image_right",
        "1000x1000",
        verbose_name="Обрезка справа",
    )

    class Meta:
        verbose_name = "Страница «Доставка и оплата»"
        verbose_name_plural = "Страница «Доставка и оплата»"

    def __str__(self):
        return "Настройки «Доставка и оплата»"

    @classmethod
    def get_solo(cls):
        return cls.objects.first() or cls.objects.create()

    # страховка от дублей
    def save(self, *args, **kwargs):
        if not self.pk and DeliveryPageSettings.objects.exists():
            raise ValidationError(
                "Разрешена только одна запись настроек «Доставка и оплата»."
            )
        return super().save(*args, **kwargs)


# === Заказы ===

class Customer(models.Model):
    email = models.EmailField("E-mail", db_index=True, unique=True)
    name = models.CharField("Имя", max_length=255, blank=True)
    phone = models.CharField("Телефон", max_length=64, blank=True)
    tg_username = models.CharField("Telegram", max_length=64, blank=True, validators=[username_validator])
    instagram_username = models.CharField("Instagram", max_length=64, blank=True, validators=[username_validator])

    class ContactPref(models.TextChoices):
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Телефон"
        TG = "tg", "Telegram"
        IG = "ig", "Instagram"

    preferred_contact = models.CharField(
        "Предпочтительный способ связи",
        max_length=10,
        choices=ContactPref.choices,
        default=ContactPref.EMAIL,
        db_index=True,
    )

    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    def save(self, *args, **kwargs):
        def _norm_username(s: str) -> str:
            s = (s or "").strip()
            if s.startswith("@"):
                s = s[1:]
            return s.lower()

        self.tg_username = _norm_username(self.tg_username)
        self.instagram_username = _norm_username(self.instagram_username)
        # ↓ полезно тоже нормализовать email
        self.email = (self.email or "").strip().lower()

        super().save(*args, **kwargs)

    @property
    def preferred_contact_value(self) -> str:
        m = self.preferred_contact
        return (
            self.email if m == self.ContactPref.EMAIL else
            self.phone if m == self.ContactPref.PHONE else
            self.tg_username if m == self.ContactPref.TG else
            self.instagram_username
        ) or ""

    class Meta:
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["phone"]),
            models.Index(fields=["preferred_contact"]),
        ]

    def __str__(self):
        return self.name or self.email or f"Клиент #{self.pk}"


class Order(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Новый"
        PAID = "paid", "Оплачен"
        FULFILLING = "fulfilling", "Готовим"
        SHIPPED = "shipped", "Отправлен"
        DONE = "done", "Завершён"
        CANCELED = "canceled", "Отменён"

    class ContactMethod(models.TextChoices):
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Телефон"
        TG = "tg", "Telegram"
        IG = "ig", "Instagram"

    number = models.CharField(
        "Номер заказа",
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name="orders", verbose_name="Клиент"
    )
    email = models.EmailField("E-mail")
    phone = models.CharField("Телефон", max_length=64, blank=True)

    # --- Срез контакта в рамках конкретного заказа
    contact_method = models.CharField(
        "Способ связи (срез)",
        max_length=10,
        choices=ContactMethod.choices,
        blank=True,
        help_text="Как попросили связаться именно по этому заказу",
        db_index=True,
    )
    contact_value = models.CharField("Контакт (срез)", max_length=255, blank=True)

    status = models.CharField(
        "Статус",
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )

    # --- Доставка
    delivery_provider = models.CharField(
        "Провайдер доставки", max_length=50, blank=True
    )  # 'cdek', 'evropochta', 'pickup'
    delivery_method = models.CharField(
        "Метод доставки", max_length=50, blank=True
    )  # 'pickup', 'courier', ...
    pickup_address = models.CharField("Адрес ПВЗ", max_length=255, blank=True)
    delivery_address = models.CharField("Адрес доставки", max_length=255, blank=True)

    # --- Деньги (по умолчанию BYN)
    currency = models.CharField("Валюта", max_length=10, default="BYN")
    subtotal = models.DecimalField("Сумма товаров", max_digits=10, decimal_places=0, default=0)
    shipping_cost = models.DecimalField("Доставка", max_digits=10, decimal_places=0, default=0)
    discount = models.DecimalField("Скидка", max_digits=10, decimal_places=0, default=0)
    total = models.DecimalField("Итого", max_digits=10, decimal_places=0, default=0)

    comment = models.TextField("Комментарий покупателя", blank=True)
    utm = models.JSONField("UTM-данные", blank=True, null=True)

    created_at = models.DateTimeField("Создан", auto_now_add=True)
    paid_at = models.DateTimeField("Оплачен в", blank=True, null=True)

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["email"]),
            models.Index(fields=["number"]),
            # contact_method уже проиндексирован через db_index=True
        ]

    def __str__(self):
        return f"{self.number or 'ORDER-????'} — {self.get_status_display()}"

    def save(self, *args, **kwargs):
        if not self.pk:
            super().save(*args, **kwargs)  # получить pk
            self.number = f"№-{self.pk:04d}"
            super().save(update_fields=["number"])
            return
        super().save(*args, **kwargs)

    def recalc_totals(self, commit=True):
        subtotal = Decimal("0")
        for it in self.items.all():
            subtotal += it.line_total
        self.subtotal = subtotal
        self.total = subtotal + (self.shipping_cost or 0) - (self.discount or 0)
        if commit:
            self.save(update_fields=["subtotal", "total"])


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items", verbose_name="Заказ")

    product = models.ForeignKey("shop.Product", on_delete=models.PROTECT, verbose_name="Товар")
    product_name = models.CharField("Название на момент покупки", max_length=255)
    sku = models.CharField("SKU", max_length=64, blank=True)

    qty = models.PositiveIntegerField("Кол-во", default=1)
    price_byn = models.DecimalField("Цена (BYN)", max_digits=10, decimal_places=0)  # цена за единицу в момент покупки
    line_total = models.DecimalField("Сумма строки", max_digits=10, decimal_places=0)

    class Meta:
        verbose_name = "Позиция заказа"
        verbose_name_plural = "Позиции заказа"
        ordering = ["id"]

    def __str__(self):
        return f"{self.product_name} ×{self.qty}"

    def save(self, *args, **kwargs):
        # пересчитываем сумму строки
        self.line_total = (self.price_byn or Decimal("0")) * self.qty
        # если не задан срез имени — подтянем из продукта
        if not self.product_name:
            self.product_name = self.product.name
        super().save(*args, **kwargs)


class Payment(models.Model):
    class Provider(models.TextChoices):
        CARD = "CARD", "Карта"
        CASH = "CASH", "Наличные"

    class PStatus(models.TextChoices):
        PENDING = "pending", "Ожидает"
        SUCCEEDED = "succeeded", "Успех"
        FAILED = "failed", "Ошибка"
        REFUNDED = "refunded", "Возврат"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments", verbose_name="Заказ")
    provider = models.CharField("Провайдер", max_length=20, choices=Provider.choices, default=Provider.CARD)
    provider_payment_id = models.CharField("ID платежа у провайдера", max_length=128, blank=True)
    amount = models.DecimalField("Сумма", max_digits=10, decimal_places=0)
    currency = models.CharField("Валюта", max_length=10, default="BYN")
    status = models.CharField("Статус платежа", max_length=20, choices=PStatus.choices, default=PStatus.PENDING)
    raw = models.JSONField("Сырой ответ/событие", blank=True, null=True)
    comment = models.TextField("Комментарий по платежу", blank=True, default="")
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Платёж"
        verbose_name_plural = "Платежи"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["provider", "status", "created_at"])]

    def __str__(self):
        return f"{self.get_provider_display()} [{self.get_status_display()}] {self.amount} {self.currency}"


class Shipment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="shipments", verbose_name="Заказ")
    provider = models.CharField("Служба", max_length=50, blank=True)
    tracking_number = models.CharField("Трек-номер", max_length=64, blank=True)
    status = models.CharField("Статус отгрузки", max_length=30)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Отгрузка"
        verbose_name_plural = "Отгрузки"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider or 'Отгрузка'} {self.tracking_number or ''}".strip()
