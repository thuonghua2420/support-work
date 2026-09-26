"""Exact comparison of user-supplied still images, independent of the web UI."""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
from datetime import datetime, timezone
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageOps, UnidentifiedImageError

MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
MAX_CANVAS_PIXELS = 16_000_000
SUPPORTED_FORMATS = {"PNG", "JPEG", "WEBP", "BMP"}


def _load(value: Any, label: str) -> tuple[Image.Image, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError(f"Vui lòng chọn {label}.")
    data_url = value.get("data_url", "")
    if not isinstance(data_url, str) or len(data_url) > MAX_FILE_BYTES * 4 // 3 + 200:
        raise ValueError(f"{label}: tối đa 12 MB mỗi ảnh.")
    try:
        header, encoded = data_url.split(",", 1)
        if not header.startswith("data:image/") or not header.endswith(";base64"):
            raise ValueError()
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"{label}: dữ liệu ảnh không hợp lệ.") from exc
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"{label}: ảnh trống hoặc lớn hơn 12 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in SUPPORTED_FORMATS:
                raise ValueError(f"{label}: chỉ hỗ trợ PNG, JPEG, WebP và BMP.")
            if getattr(source, "n_frames", 1) != 1:
                raise ValueError(f"{label}: vui lòng dùng ảnh tĩnh, không dùng ảnh động.")
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError(f"{label}: tối đa 12 triệu pixel mỗi ảnh.")
            # Pillow reduces 16-bit RGB PNGs to 8 bits on decode. Reject explicitly
            # rather than falsely reporting equality after losing low-order bits.
            if source.mode in {"I", "F", "I;16", "I;16B", "I;16L"} or (
                source.format == "PNG" and len(raw) > 24 and raw[24] == 16
            ):
                raise ValueError(f"{label}: ảnh 16/32-bit chưa được hỗ trợ; hãy dùng ảnh 8-bit.")
            profile = source.info.get("icc_profile", b"") or b""
            metadata = {
                "name": str(value.get("name", label))[:240],
                "format": source.format,
                "bytes": len(raw),
                "file_sha256": hashlib.sha256(raw).hexdigest(),
                "icc_sha256": hashlib.sha256(profile).hexdigest(),
                "png_gamma": source.info.get("gamma"),
                "png_srgb": source.info.get("srgb"),
                "png_chromaticity": source.info.get("chromaticity"),
            }
            image = ImageOps.exif_transpose(source).convert("RGBA")
            metadata.update(width=image.width, height=image.height,
                            pixel_sha256=hashlib.sha256(image.tobytes()).hexdigest())
            return image, metadata
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"{label}: file ảnh hỏng hoặc không đọc được.") from exc


def _png(image: Image.Image) -> str:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def _regions(mask: Image.Image, tile: int = 32) -> list[list[int]]:
    bounds = mask.getbbox()
    if not bounds:
        return []
    active = set()
    for y in range(bounds[1] // tile, (bounds[3] + tile - 1) // tile):
        for x in range(bounds[0] // tile, (bounds[2] + tile - 1) // tile):
            if mask.crop((x * tile, y * tile, min((x + 1) * tile, mask.width), min((y + 1) * tile, mask.height))).getbbox():
                active.add((x, y))
    regions = []
    while active:
        start = active.pop()
        pending = [start]
        min_x = max_x = start[0]
        min_y = max_y = start[1]
        while pending:
            x, y = pending.pop()
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
            for neighbor in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                if neighbor in active:
                    active.remove(neighbor)
                    pending.append(neighbor)
        box = (min_x * tile, min_y * tile, min((max_x+1)*tile, mask.width), min((max_y+1)*tile, mask.height))
        tight = mask.crop(box).getbbox()
        regions.append([box[0]+tight[0], box[1]+tight[1], box[0]+tight[2], box[1]+tight[3]])
    return sorted(regions, key=lambda box: (box[1], box[0]))


def compare_images(old: Any, new: Any) -> dict[str, Any]:
    old_image, old_info = _load(old, "ảnh Old")
    new_image, new_info = _load(new, "ảnh New")
    width, height = max(old_image.width, new_image.width), max(old_image.height, new_image.height)
    if width * height > MAX_CANVAS_PIXELS:
        raise ValueError("Khung so sánh quá lớn (tối đa 16 triệu pixel).")
    canvases = []
    presence = []
    for image in (old_image, new_image):
        canvas = Image.new("RGBA", (width, height))
        canvas.paste(image, (0, 0))
        canvases.append(canvas)
        area = Image.new("L", (width, height))
        area.paste(255, (0, 0, image.width, image.height))
        presence.append(area)
    channels = ImageChops.difference(*canvases).split()
    delta = channels[0]
    for channel in channels[1:]:
        delta = ImageChops.lighter(delta, channel)
    mask = ImageChops.lighter(delta, ImageChops.difference(*presence)).point(lambda p: 255 if p else 0)
    changed = mask.histogram()[255]
    total = old_image.width * old_image.height + new_image.width * new_image.height - min(old_image.width, new_image.width) * min(old_image.height, new_image.height)
    dimensions_equal = old_image.size == new_image.size
    pixels_equal = dimensions_equal and changed == 0
    profile_equal = all(old_info[key] == new_info[key] for key in ("icc_sha256", "png_gamma", "png_srgb", "png_chromaticity"))
    identical = pixels_equal and profile_equal
    binary_equal = old_info["file_sha256"] == new_info["file_sha256"]
    regions = _regions(mask)
    background = Image.new("RGBA", (width, height), "white")
    rendered = [Image.alpha_composite(background, canvas).convert("RGB") for canvas in canvases]
    base = Image.blend(*rendered, 0.5)
    highlight = Image.composite(Image.new("RGB", base.size, "#ef4444"), base, mask)
    draw = ImageDraw.Draw(highlight)
    for x0, y0, x1, y1 in regions:
        draw.rectangle((x0, y0, x1-1, y1-1), outline="#b91c1c", width=1)
    return {
        "schema": "autocompare.image-comparison.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "BINARY IDENTICAL" if binary_equal else "PIXEL IDENTICAL" if identical else "DIFFERENT",
        "identical": identical, "binary_identical": binary_equal,
        "pixels_identical": pixels_equal, "dimensions_identical": dimensions_equal,
        "color_metadata_identical": profile_equal,
        "old": old_info, "new": new_info,
        "width": width, "height": height,
        "changed_pixels": changed, "total_pixels": total,
        "difference_percent": changed / total * 100,
        "regions": regions,
        "method": "Exact RGBA 8-bit after EXIF orientation; includes transparent pixels and missing area; no resize, tolerance, or alignment. Color metadata checked separately. Coordinates: zero-based, [x0,y0,x1,y1), 32px tile-connected regions.",
        "previews": {"old": _png(canvases[0]), "new": _png(canvases[1]), "diff": _png(highlight)},
    }
