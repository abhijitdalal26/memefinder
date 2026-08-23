import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageFilter, ImageStat

BASE_DIR = Path(__file__).resolve().parent.parent

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F02F"
    "\U00002B00-\U00002BFF\uFE0F\u2700-\u27BF]"
)

HUMOR_PATTERNS = [
    ("me_when", r"\bme when\b|\bme after\b|\bme during\b|\bnot me\b|\bme IRL\b"),
    ("pov", r"\bpov[:\s]|\bpov\b"),
    ("nobody", r"\bnobody:\b|\bno one:\b|\bliterally nobody\b"),
    ("be_like", r"\bbe like\b|\bb like\b|\bbe me\b|\bam i right\b"),
    ("when_you", r"\bwhen (you|u|ur|your|she|he|they|the)\b|\bthat moment\b|\bthat one (friend|guy|person)\b"),
    ("how_it_feels", r"\bhow it feels\b|\bhow i feel\b|\bthe way i\b|\bwhat it feels like\b"),
    ("tell_me", r"tell me you .{1,60} without telling me"),
    ("starter_pack", r"\bstarter pack\b"),
    ("expectation_vs_reality", r"\bexpectation\b|\breality\b|\bthen vs now\b"),
    ("caption_macro", r"^(when|me|nobody|pov|they don'?t know|my brain)\b.*\b(at|in|on|during|be like)\b", ),
    ("self_deprecating", r"\bi'm (so )?(dumb|stupid|trash|bad|broken)\b|\bcan'?t even\b|\bsame tbh\b|\bit me\b"),
    ("absurdist", r"\bforbidden\b|\bcursed\b|\bblursed\b|\bunhinged\b|\bgremlin\b"),
]


def analyze_title(title: str) -> Dict:
    title = (title or "").strip()
    letters = [c for c in title if c.isalpha()]
    caps_ratio = (sum(1 for c in letters if c.isupper()) / len(letters)) if len(letters) >= 6 else 0.0

    humor_signal = "none"
    for name, pattern in HUMOR_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            humor_signal = name
            break

    if humor_signal == "none" and caps_ratio >= 0.7:
        humor_signal = "shouting"

    if humor_signal != "none":
        style = humor_signal
    elif title.endswith("?"):
        style = "question"
    elif caps_ratio >= 0.7:
        style = "shouting"
    elif len(title) <= 25:
        style = "short_punchy"
    else:
        style = "statement"

    return {
        "text_length": len(title),
        "word_count": len(title.split()),
        "title_style": style,
        "humor_signal": humor_signal,
        "title_has_question": "?" in title,
        "title_has_caps_shout": caps_ratio >= 0.7,
        "title_has_emoji": bool(EMOJI_RE.search(title)),
    }


def analyze_timing(
    posted_at_iso: str,
    upvotes: int = 0,
    comments: int = 0,
    collected_at_iso: str = "",
) -> Dict:
    out = {
        "posted_day_of_week": "",
        "posted_hour_utc": None,
        "age_days_at_collection": None,
        "virality_score": None,
        "engagement_ratio": None,
    }
    try:
        posted = datetime.fromisoformat(posted_at_iso.replace("Z", "+00:00"))
    except Exception:
        return out

    out["posted_day_of_week"] = posted.strftime("%A")
    out["posted_hour_utc"] = posted.hour

    try:
        collected = (
            datetime.fromisoformat(collected_at_iso.replace("Z", "+00:00"))
            if collected_at_iso
            else datetime.now(timezone.utc)
        )
        age_hours = max((collected - posted).total_seconds() / 3600.0, 6.0)
        out["age_days_at_collection"] = round((collected - posted).total_seconds() / 86400.0, 2)
        out["virality_score"] = round(upvotes / age_hours, 2)
        out["engagement_ratio"] = round(comments / max(upvotes, 1), 3)
    except Exception:
        pass
    return out


def _hex(rgb: tuple) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb[:3])


def _band_edge_density(gray: Image.Image, box: tuple) -> float:
    band = gray.crop(box).filter(ImageFilter.FIND_EDGES)
    return ImageStat.Stat(band).mean[0] / 255.0


ANALYSIS_MAX_DIM = 512


def _work_copy(img: Image.Image) -> Image.Image:
    """Downscaled RGB copy for pixel statistics (ratios are resolution-independent)."""
    rgb = img.convert("RGB")
    max_dim = max(rgb.size)
    if max_dim > ANALYSIS_MAX_DIM:
        scale = ANALYSIS_MAX_DIM / max_dim
        new_size = (max(1, round(rgb.size[0] * scale)), max(1, round(rgb.size[1] * scale)))
        return rgb.resize(new_size)
    return rgb


def analyze_image(image_path: str = "", img: Image.Image = None) -> Dict:
    out = {
        "aspect_ratio": None,
        "orientation": "unknown",
        "platform_fit": [],
        "visual_complexity": None,
        "text_overlay_likelihood": "unknown",
        "dominant_colors": [],
        "brightness": None,
        "is_grayscale": False,
    }
    if img is None:
        try:
            img = Image.open(image_path)
            img.load()
        except Exception:
            return out

    w, h = img.size
    ratio = round(w / h, 3) if h else 1.0
    out["aspect_ratio"] = ratio

    if 0.95 <= ratio <= 1.05:
        out["orientation"] = "square"
        out["platform_fit"] = ["instagram_feed", "discord", "whatsapp", "reddit"]
    elif 0.75 <= ratio < 0.95:
        out["orientation"] = "portrait"
        out["platform_fit"] = ["instagram_feed", "facebook", "pinterest"]
    elif ratio < 0.75:
        out["orientation"] = "tall"
        out["platform_fit"] = ["tiktok", "stories", "shorts", "pinterest"]
    elif ratio <= 1.2:
        out["orientation"] = "landscape"
        out["platform_fit"] = ["twitter", "reddit", "discord"]
    elif ratio <= 1.9:
        out["orientation"] = "wide"
        out["platform_fit"] = ["twitter", "reddit", "youtube_thumbnail", "discord"]
    else:
        out["orientation"] = "ultrawide"
        out["platform_fit"] = ["twitter", "reddit"]

    try:
        work = _work_copy(img)
        small = work.resize((64, 64))
        hsv = small.convert("HSV")
        sat_mean = ImageStat.Stat(hsv.split()[1]).mean[0] / 255.0
        gray = work.convert("L")
        brightness = ImageStat.Stat(gray).mean[0] / 255.0

        q = small.quantize(colors=4)
        palette = q.getpalette()
        counts = sorted(q.getcolors(), reverse=True)[:3]
        dom = []
        for _, idx in counts:
            dom.append(_hex(tuple(palette[idx * 3: idx * 3 + 3])))

        h_px = gray.size[1]
        w_px = gray.size[0]
        top_e = _band_edge_density(gray, (0, 0, w_px, max(h_px // 4, 1)))
        bot_e = _band_edge_density(gray, (0, 3 * h_px // 4, w_px, h_px))
        mid_e = _band_edge_density(gray, (0, h_px // 3, w_px, 2 * h_px // 3))

        complexity = round(ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0] / 255.0, 3)

        top_white = sum(1 for p in gray.crop((0, 0, w_px, max(h_px // 4, 1))).getdata() if p > 235) / max(w_px * (h_px // 4), 1)
        bot_white = sum(1 for p in gray.crop((0, 3 * h_px // 4, w_px, h_px)).getdata() if p > 235) / max(w_px * (h_px - 3 * h_px // 4), 1)

        band_ratio = max(top_e, bot_e) / max(mid_e, 0.01)
        if (band_ratio >= 1.8 and max(top_e, bot_e) >= 0.05) or max(top_white, bot_white) >= 0.55:
            overlay = "high"
        elif band_ratio >= 1.3:
            overlay = "medium"
        else:
            overlay = "low"

        out["visual_complexity"] = complexity
        out["text_overlay_likelihood"] = overlay
        out["dominant_colors"] = dom
        out["brightness"] = round(brightness, 3)
        out["is_grayscale"] = sat_mean < 0.06
    except Exception:
        pass
    return out


def enrich(record: Dict, img: Image.Image = None) -> Dict:
    title_fields = analyze_title(record.get("title", ""))
    timing_fields = analyze_timing(
        record.get("posted_at", ""),
        upvotes=record.get("upvotes", 0) or 0,
        comments=record.get("comments", 0) or 0,
        collected_at_iso=record.get("collected_at", ""),
    )
    p = Path(record.get("image_path", ""))
    if not p.is_absolute():
        p = BASE_DIR / p
    image_fields = analyze_image(str(p), img=img)
    record.update(title_fields)
    record.update(timing_fields)
    record.update(image_fields)
    return record
