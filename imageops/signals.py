from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.db import models
from django.conf import settings
from .utils import compress_image


def _should_process(file_obj, only_on_change=True):
    if not file_obj:
        return False
    if getattr(file_obj, "_imageops_processed", False):
        return False
    if only_on_change and getattr(file_obj, "_committed", True):
        return False
    return True


@receiver(pre_save)
def imageops_on_any_model(sender, instance, **kwargs):
    if not getattr(settings, "IMAGEOPS_ENABLE", True):
        return
    for field in instance._meta.fields:
        if not isinstance(field, models.ImageField):
            continue
        if "imageops:skip" in (field.help_text or ""):
            continue
        file_obj = getattr(instance, field.name, None)
        if not _should_process(file_obj, getattr(settings, "IMAGEOPS_ONLY_ON_CHANGE", True)):
            continue
        try:
            new_file = compress_image(
                file_obj.file if hasattr(file_obj, "file") else file_obj,
                max_dims=getattr(settings, "IMAGEOPS_MAX_DIMS", (1600, 1600)),
                quality=getattr(settings, "IMAGEOPS_QUALITY", 82),
                force_webp=getattr(settings, "IMAGEOPS_FORCE_WEBP", False),
                strip_exif=getattr(settings, "IMAGEOPS_STRIP_EXIF", True),
            )
            setattr(instance, field.name, new_file)
        except Exception:
            continue