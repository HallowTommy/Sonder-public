# core/admin_site.py
from django.contrib.admin import AdminSite
from django.contrib.admin.apps import AdminConfig
from django.urls import reverse


class SonderAdminSite(AdminSite):
    site_header = "Администрирование Django"
    site_title = "Sonder Admin"
    index_title = "Админка"

    # --- модели, которые НЕ должны появляться в боковом меню
    HIDE_MODELS = {
        ("shop", "NewTabSettings"),  # Вкладка «Новинки»
    }

    # --- секции (группа -> порядок)
    MODEL_GROUP = {
        # Каталог
        ("shop", "Category"): ("Каталог", 10),
        ("shop", "Product"): ("Каталог", 10),

        # Контент и страницы (по умолчанию всё сюда)

        # Администрирование
        ("auth", "User"): ("Администрирование", 200),
        ("auth", "Group"): ("Администрирование", 200),

        # Операции (последним)
        ("shop", "Order"): ("Операции", 900),
        ("shop", "Customer"): ("Операции", 900),
        ("shop", "Shipment"): ("Операции", 900),
        ("shop", "Payment"): ("Операции", 900),
    }

    MODEL_ORDER = {
        # Контент и страницы (твой нужный порядок)
        ("shop", "HomePageSettings"): 10,  # Главная
        ("shop", "AboutPageSettings"): 20,  # О нас
        ("shop", "ContactPageSettings"): 30,  # Контакты
        ("shop", "DeliveryPageSettings"): 40,  # Доставка и оплата

        # Каталог
        ("shop", "Category"): 10,
        ("shop", "Product"): 20,

        # Администрирование
        ("auth", "User"): 10,
        ("auth", "Group"): 20,

        # Операции
        ("shop", "Customer"): 20,
        ("shop", "Order"): 30,
        ("shop", "Payment"): 40,
        ("shop", "Shipment"): 50,
    }

    def get_app_list(self, request):
        groups = {}

        for model, model_admin in self._registry.items():
            # права
            perms = model_admin.get_model_perms(request)
            if not any(perms.values()):
                continue

            opts = model._meta
            key = (opts.app_label, opts.object_name)

            # жёстко скрываем нежелательные модели
            if key in self.HIDE_MODELS:
                continue

            section_title, section_order = self.MODEL_GROUP.get(
                key, ("Контент и страницы", 100)
            )

            if section_title not in groups:
                groups[section_title] = {
                    "name": section_title,
                    "app_label": section_title.lower().replace(" ", "_"),
                    "app_url": "",
                    "has_module_perms": True,
                    "models": [],
                    "_order": section_order,
                }

            groups[section_title]["models"].append({
                "name": opts.verbose_name_plural.capitalize(),
                "object_name": opts.object_name,
                "app_label": opts.app_label,
                "perms": perms,
                "admin_url": reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist"),
                "add_url": reverse(f"admin:{opts.app_label}_{opts.model_name}_add") if perms.get("add") else None,
                "view_only": perms.get("view") and not perms.get("change"),
            })

        # сортировка моделей в секциях
        for section in groups.values():
            section["models"].sort(
                key=lambda m: (
                    self.MODEL_ORDER.get((m["app_label"], m["object_name"]), 500),
                    m["name"],
                )
            )

        app_list = sorted(groups.values(), key=lambda a: (a["_order"], a["name"]))
        for a in app_list:
            a.pop("_order", None)
        return app_list


class SonderAdminConfig(AdminConfig):
    default_site = "core.admin_site.SonderAdminSite"
