"""
EPUB image compressor — adaptive compression targeting 10% of original size.

Strategy:
1. Extract images from EPUB (ZIP archive)
2. Resize if exceeding max dimensions
3. Binary-search JPEG quality to hit target_size_ratio
4. Optionally convert PNG → JPEG (flatten transparency on white)
5. Rebuild EPUB preserving structure (mimetype stored first, uncompressed)
6. Update content references if any PNG→JPEG renames occurred
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from pathlib import Path

from PIL import Image

from nerv.config import Config
from nerv.logger import NervLogger
from nerv.stats import Stats

# ── Constants ───────────────────────────────────────────────────────

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
CONTENT_EXTENSIONS = {".xhtml", ".html", ".htm", ".opf", ".ncx", ".css"}


def _is_image(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS


def _is_content_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in CONTENT_EXTENSIONS


# ── Single Image Compression ───────────────────────────────────────


def _compress_image(
    image_data: bytes,
    filename: str,
    config: Config,
) -> tuple[bytes, str, dict]:
    """
    Compress a single image to reach ~target_size_ratio of its original size.

    Returns:
        (compressed_bytes, new_filename, info_dict)

    info_dict keys:
        skipped (bool), reason (str), original_size, compressed_size,
        format (str), renamed (bool)
    """
    original_size = len(image_data)
    target_size = int(original_size * config.compression.target_size_ratio)
    ext = Path(filename).suffix.lower()

    # Try to open the image
    try:
        img = Image.open(io.BytesIO(image_data))
    except Exception:
        return image_data, filename, {"skipped": True, "reason": "Cannot open image"}

    # Skip animated images (GIF, WEBP with multiple frames)
    if getattr(img, "n_frames", 1) > 1:
        return image_data, filename, {"skipped": True, "reason": "Animated image"}

    has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info

    # ── Resize if exceeding max dimensions ──
    w, h = img.size
    max_w = config.compression.max_width
    max_h = config.compression.max_height
    if w > max_w or h > max_h:
        ratio = min(max_w / w, max_h / h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    # ── Decide output format ──
    new_filename = filename
    output_format = "JPEG"

    if ext == ".png" and has_alpha and not config.compression.convert_png_to_jpeg:
        # Keep PNG with transparency
        output_format = "PNG"
    elif ext == ".png" and has_alpha and config.compression.convert_png_to_jpeg:
        # Flatten transparency on white background, convert to JPEG
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "RGBA":
            background.paste(img, mask=img.split()[3])
        else:
            img_rgba = img.convert("RGBA")
            background.paste(img_rgba, mask=img_rgba.split()[3])
        img = background
        new_filename = str(Path(filename).with_suffix(".jpeg"))
    elif ext == ".png" and config.compression.convert_png_to_jpeg:
        # No transparency, simple conversion
        if img.mode != "RGB":
            img = img.convert("RGB")
        new_filename = str(Path(filename).with_suffix(".jpeg"))
    elif ext == ".png":
        output_format = "PNG"
    else:
        # Already JPEG/WEBP/BMP → output as JPEG
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

    # ── Compress ──
    if output_format == "JPEG":
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        compressed = _binary_search_jpeg_quality(
            img,
            target_size,
            config.compression.jpeg_quality_min,
            config.compression.jpeg_quality_max,
        )
    else:
        # PNG optimization — quantize + optimize
        buf = io.BytesIO()
        try:
            quantized = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
            quantized.save(buf, format="PNG", optimize=True)
        except Exception:
            img.save(buf, format="PNG", optimize=True)
        compressed = buf.getvalue()

    return compressed, new_filename, {
        "skipped": False,
        "original_size": original_size,
        "compressed_size": len(compressed),
        "format": output_format,
        "renamed": new_filename != filename,
    }


def _binary_search_jpeg_quality(
    img: Image.Image,
    target_size: int,
    quality_min: int,
    quality_max: int,
) -> bytes:
    """
    Find optimal JPEG quality to get as close to target_size as possible.

    Uses binary search over quality parameter (max 10 iterations).
    Returns the best compressed bytes found.
    """
    lo, hi = quality_min, quality_max

    # Quick check: is minimum quality already too large?
    min_data = _encode_jpeg(img, lo)
    if len(min_data) >= target_size:
        return min_data  # Can't do better

    # Quick check: is maximum quality already small enough?
    max_data = _encode_jpeg(img, hi)
    if len(max_data) <= target_size:
        return max_data  # No need to reduce quality

    # Binary search for the highest quality that stays under target
    best_data = min_data
    for _ in range(10):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        data = _encode_jpeg(img, mid)

        if len(data) <= target_size:
            best_data = data
            lo = mid + 1
        else:
            hi = mid - 1

    return best_data


def _encode_jpeg(img: Image.Image, quality: int) -> bytes:
    """Encode image as JPEG with given quality, return bytes."""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


# ── Single EPUB Compression ────────────────────────────────────────


def compress_epub(
    epub_path: str,
    config: Config,
    logger: NervLogger,
) -> dict:
    """
    Compress all images inside a single EPUB file (in-place).

    Two-pass approach:
      Pass 1 — Read all entries, compress images, build rename map.
      Pass 2 — Write new EPUB, updating content references if needed.

    Returns dict with success status and size metrics.
    """
    epub = Path(epub_path)
    original_size = epub.stat().st_size

    rename_map: dict[str, str] = {}  # old_name → new_name (for PNG→JPEG)
    entries: list[tuple[str, bytes, str, bool]] = []
    # Each entry: (original_name, data, output_name, was_image_processed)

    total_img_original = 0
    total_img_compressed = 0
    images_processed = 0

    # ── Pass 1: Read & compress images ──
    try:
        with zipfile.ZipFile(epub_path, "r") as zin:
            for item in zin.infolist():
                data = zin.read(item.filename)

                if _is_image(item.filename):
                    comp_data, new_name, info = _compress_image(
                        data, item.filename, config
                    )
                    if not info.get("skipped"):
                        total_img_original += info["original_size"]
                        total_img_compressed += info["compressed_size"]
                        images_processed += 1

                        if info.get("renamed"):
                            rename_map[item.filename] = new_name

                        entries.append((item.filename, comp_data, new_name, True))
                        logger.debug(
                            f"  ├─ {item.filename} : "
                            f"{info['original_size']:,} → {info['compressed_size']:,} o "
                            f"({(1 - info['compressed_size'] / max(info['original_size'], 1)) * 100:.0f}%)"
                        )
                    else:
                        entries.append((item.filename, data, item.filename, False))
                        logger.debug(
                            f"  ├─ {item.filename} : ignoré ({info.get('reason', '?')})"
                        )
                else:
                    entries.append((item.filename, data, item.filename, False))

    except zipfile.BadZipFile:
        logger.error(f"Fichier ZIP invalide : {epub}")
        return {"success": False, "error": "Bad ZIP file"}
    except Exception as e:
        logger.error(f"Erreur lecture {epub} : {e}")
        return {"success": False, "error": str(e)}

    # ── Pass 2: Write new EPUB ──
    temp_path = epub.with_suffix(".epub.tmp")
    try:
        with zipfile.ZipFile(str(temp_path), "w") as zout:
            for original_name, data, output_name, _ in entries:
                # mimetype must be stored first and uncompressed (EPUB spec)
                if output_name == "mimetype":
                    info = zipfile.ZipInfo("mimetype")
                    info.compress_type = zipfile.ZIP_STORED
                    zout.writestr(info, data)
                    continue

                # Update references in content files if we renamed any images
                if _is_content_file(original_name) and rename_map:
                    text = data.decode("utf-8", errors="replace")
                    for old_name, new_name in rename_map.items():
                        old_base = Path(old_name).name
                        new_base = Path(new_name).name
                        text = text.replace(old_base, new_base)

                    # Update media-type in OPF manifest for renamed items
                    if original_name.endswith(".opf"):
                        for old_name, new_name in rename_map.items():
                            new_base = re.escape(Path(new_name).name)
                            text = re.sub(
                                r'(<item[^>]*href="[^"]*'
                                + new_base
                                + r'"[^>]*media-type=")image/png(")',
                                r"\1image/jpeg\2",
                                text,
                            )
                            # Handle reversed attribute order
                            text = re.sub(
                                r'(<item[^>]*media-type=")image/png("[^>]*href="[^"]*'
                                + new_base
                                + r'")',
                                r"\1image/jpeg\2",
                                text,
                            )

                    info = zipfile.ZipInfo(original_name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    zout.writestr(info, text.encode("utf-8"))
                else:
                    info = zipfile.ZipInfo(output_name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    zout.writestr(info, data)

        # Replace original with compressed version
        os.replace(str(temp_path), epub_path)
        compressed_size = Path(epub_path).stat().st_size

        return {
            "success": True,
            "original_size": original_size,
            "compressed_size": compressed_size,
            "images_processed": images_processed,
            "image_original_total": total_img_original,
            "image_compressed_total": total_img_compressed,
        }

    except Exception as e:
        # Clean up temp file on failure
        if temp_path.exists():
            temp_path.unlink()
        logger.error(f"Erreur écriture {epub} : {e}")
        return {"success": False, "error": str(e)}


# ── Batch Compression ──────────────────────────────────────────────


def compress_epubs(
    files: list[str],
    config: Config,
    logger: NervLogger,
    stats: Stats,
    dry_run: bool = False,
    progress_callback: callable | None = None,
):
    """
    Compress all EPUB files in the given list.

    In dry-run mode, estimates compression without writing.
    Calls progress_callback() after each file for progress bar updates.
    """
    for epub_path in files:
        filename = Path(epub_path).name

        if dry_run:
            try:
                original_size = Path(epub_path).stat().st_size
            except OSError:
                original_size = 0
            estimated = int(original_size * config.compression.target_size_ratio)
            logger.debug(
                f"[DRY-RUN] Compresserait : {filename} "
                f"({original_size:,} → ~{estimated:,} o)"
            )
            stats.add_compressed(filename, original_size, estimated)
        else:
            logger.info(f"Compression : {filename}")
            result = compress_epub(epub_path, config, logger)

            if result["success"]:
                stats.add_compressed(
                    filename,
                    result["original_size"],
                    result["compressed_size"],
                )
                gain = (
                    (1 - result["compressed_size"] / result["original_size"]) * 100
                    if result["original_size"] > 0
                    else 0
                )
                logger.info(
                    f"  └─ ✓ {result['original_size']:,} → "
                    f"{result['compressed_size']:,} o "
                    f"({gain:.1f}% gain, {result['images_processed']} images)"
                )
            else:
                stats.add_error(filename, result.get("error", "Unknown error"))

        if progress_callback:
            progress_callback()
