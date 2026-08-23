from PIL import Image
from pathlib import Path
from typing import Tuple, Optional
import math


def get_image_info_from_img(img: Image.Image, image_path: str) -> Optional[dict]:
    try:
        width, height = img.size
        file_size = Path(image_path).stat().st_size
        return {
            "width": width,
            "height": height,
            "resolution": (width, height),
            "format": img.format,
            "mode": img.mode,
            "file_size_bytes": file_size,
            "file_size_kb": round(file_size / 1024, 2),
            "megapixels": round((width * height) / 1_000_000, 2),
        }
    except Exception:
        return None


def get_image_info(image_path: str) -> Optional[dict]:
    try:
        with Image.open(image_path) as img:
            return get_image_info_from_img(img, image_path)
    except Exception:
        return None


def passes_quality_check_img(
    img: Image.Image,
    image_path: str,
    min_resolution: Tuple[int, int] = (300, 300),
    max_file_size_mb: float = 10,
) -> Tuple[bool, str]:
    info = get_image_info_from_img(img, image_path)
    if info is None:
        return False, "cannot_open"

    width, height = info["resolution"]
    if width < min_resolution[0] or height < min_resolution[1]:
        return False, f"too_small_{width}x{height}"

    file_size_mb = info["file_size_bytes"] / (1024 * 1024)
    if file_size_mb > max_file_size_mb:
        return False, f"too_large_{file_size_mb:.1f}mb"

    return True, "ok"


def passes_quality_check(
    image_path: str,
    min_resolution: Tuple[int, int] = (300, 300),
    max_file_size_mb: float = 10,
) -> Tuple[bool, str]:
    try:
        with Image.open(image_path) as img:
            return passes_quality_check_img(img, image_path, min_resolution, max_file_size_mb)
    except Exception:
        return False, "cannot_open"


def compute_quality_score(
    upvotes: int = 0,
    comments: int = 0,
    resolution: Tuple[int, int] = (0, 0),
    views: int = 0,
) -> float:
    upvote_score = min(upvotes / 50000, 1.0) * 0.4
    comment_score = min(comments / 5000, 1.0) * 0.2

    width, height = resolution
    pixels = width * height
    resolution_score = min(pixels / (1920 * 1080), 1.0) * 0.2

    view_score = min(views / 100000, 1.0) * 0.2 if views > 0 else 0.1

    raw_score = upvote_score + comment_score + resolution_score + view_score
    return round(min(max(raw_score, 0.0), 1.0), 3)


def classify_image_type_from_info(info: Optional[dict]) -> str:
    if not info:
        return "unknown"

    if info.get("format") == "GIF":
        return "gif"

    width, height = info["resolution"]
    aspect_ratio = width / height if height > 0 else 1

    if 0.9 <= aspect_ratio <= 1.1:
        return "square"
    elif aspect_ratio > 1.5:
        return "landscape_wide"
    elif aspect_ratio > 1.1:
        return "landscape"
    elif aspect_ratio < 0.67:
        return "portrait_tall"
    elif aspect_ratio < 0.9:
        return "portrait"
    else:
        return "standard"


def is_template_record(record: dict) -> bool:
    from config.settings import TEMPLATE_SOURCES, TEMPLATE_SUBREDDITS
    if record.get("source") in TEMPLATE_SOURCES:
        return True
    sub = (record.get("source_sub") or "").lower().replace("r/", "")
    if sub in TEMPLATE_SUBREDDITS:
        return True
    tags = record.get("tags") or []
    return any("template" in str(t).lower() or "blank" in str(t).lower() for t in tags)


def passes_curation_gates(
    record: dict,
    min_resolution: Tuple[int, int] = (400, 400),
    min_file_size_kb: float = 20,
    min_score: float = 0.12,
) -> Tuple[bool, str]:
    """Quality gates for the curated training set.

    Templates (blank/format sources) are exempt from the engagement score gate
    because they legitimately carry 0 upvotes.
    """
    w, h = record.get("resolution", [0, 0])
    if w < min_resolution[0] or h < min_resolution[1]:
        return False, "too_small"
    if record.get("file_size_kb", 0) < min_file_size_kb:
        return False, "too_small_file"
    if not is_template_record(record) and record.get("quality_score", 0) < min_score:
        return False, "low_score"
    return True, "ok"


def classify_image_type(image_path: str) -> str:
    return classify_image_type_from_info(get_image_info(image_path))
