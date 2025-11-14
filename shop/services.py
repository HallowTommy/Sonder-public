from django.db import transaction
from .models import Customer


def _normalize_username(s: str) -> str:
    """Снять @, обрезать пробелы, привести к lower для унификации."""
    s = (s or "").strip()
    if s.startswith("@"):
        s = s[1:]
    return s.lower()


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _coerce_contact_pref(value: str | None) -> str | None:
    """Вернёт валидное значение из Customer.ContactPref или None."""
    if not value:
        return None
    value = str(value).lower().strip()
    allowed = {
        Customer.ContactPref.EMAIL: Customer.ContactPref.EMAIL,
        Customer.ContactPref.PHONE: Customer.ContactPref.PHONE,
        Customer.ContactPref.TG: Customer.ContactPref.TG,
        Customer.ContactPref.IG: Customer.ContactPref.IG,
        # на всякий случай мапим сырой ввод
        "email": Customer.ContactPref.EMAIL,
        "phone": Customer.ContactPref.PHONE,
        "tg": Customer.ContactPref.TG,
        "ig": Customer.ContactPref.IG,
    }
    return allowed.get(value)


@transaction.atomic
def upsert_customer_from_checkout(
    email: str,
    name: str = "",
    phone: str = "",
    tg_username: str = "",
    instagram_username: str = "",
    preferred_contact: str | None = None,
) -> Customer:
    """
    Находит/создаёт клиента по email и частично обновляет профиль
    непустыми значениями. Никнеймы нормализуются, email приводится к lower.
    """
    email_norm = _normalize_email(email)
    tg = _normalize_username(tg_username)
    ig = _normalize_username(instagram_username)
    pref = _coerce_contact_pref(preferred_contact) or Customer.ContactPref.EMAIL

    cust, created = Customer.objects.get_or_create(
        email=email_norm,
        defaults={
            "name": (name or "").strip(),
            "phone": (phone or "").strip(),
            "tg_username": tg,
            "instagram_username": ig,
            "preferred_contact": pref,
        },
    )

    # Если клиент уже был — обновляем только непустыми новыми значениями
    changed = False

    def set_if_new(field: str, new_val: str):
        nonlocal changed
        new_val = (new_val or "").strip()
        if field in ("tg_username", "instagram_username"):
            new_val = _normalize_username(new_val)
        if new_val and getattr(cust, field) != new_val:
            setattr(cust, field, new_val)
            changed = True

    set_if_new("name", name)
    set_if_new("phone", phone)
    set_if_new("tg_username", tg)
    set_if_new("instagram_username", ig)

    coerced_pref = _coerce_contact_pref(preferred_contact)
    if coerced_pref and cust.preferred_contact != coerced_pref:
        cust.preferred_contact = coerced_pref
        changed = True

    if changed:
        cust.save(update_fields=[
            "name", "phone", "tg_username", "instagram_username",
            "preferred_contact", "updated_at"
        ])

    return cust
