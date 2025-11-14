from django.apps import AppConfig


class ImageOpsConfig(AppConfig):
    name = "imageops"

    def ready(self):
        from . import signals