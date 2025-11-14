import io
from PIL import Image, ImageOps
from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile


def compress_image(file,
                   max_dims=None,
                   quality=None,
                   force_webp=None,
                   strip_exif=True):
    max_w, max_h = max_dims or getattr(settings, "IMAGEOPS_MAX_DIMS", (1600, 1600))
    quality = quality or getattr(settings, "IMAGEOPS_QUALITY", 82)
    force_webp = (getattr(settings, "IMAGEOPS_FORCE_WEBP", False)
                  if force_webp is None else force_webp)

    img = Image.open(file)
    img = ImageOps.exif_transpose(img)
    img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

    fmt = (getattr(img, "format", "JPEG") or "JPEG").upper()
    if fmt == "JPG": fmt = "JPEG"
    if fmt not in {"JPEG", "PNG", "WEBP"}: fmt = "JPEG"
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if fmt == "JPEG" and has_alpha:
        fmt = "WEBP"
    if fmt == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif fmt in ("WEBP", "PNG") and img.mode == "P":
        img = img.convert("RGBA")

    buf = io.BytesIO()
    params = {"quality": quality, "optimize": True}
    if fmt == "WEBP":
        params["method"] = 6
    img.save(buf, format=fmt, **params)
    data = buf.getvalue()

    ext = "jpg" if fmt == "JPEG" else fmt.lower()
    content_type = f"image/{'jpeg' if ext == 'jpg' else ext}"
    out = InMemoryUploadedFile(io.BytesIO(data), None,
                               (file.name.rsplit(".", 1)[0] + f".{ext}"),
                               content_type, len(data), None)
    setattr(out, "_imageops_processed", True)
    return out
