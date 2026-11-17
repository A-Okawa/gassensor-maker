"""Portable figure appearance, separate from the measurement data and run labels."""
from __future__ import annotations

import json
import math

from figure_style import STYLE_KEYS, validate_style_settings

NUMBER_KEYS = {"fig_width": (25 / 25.4, 20.0), "fig_height": (25 / 25.4, 20.0), "font_size": (4.0, 28.0),
               "tick_font_size": (4.0, 28.0), "legend_font_size": (4.0, 28.0), "smooth_s": (0.0, 600.0),
               "raw_alpha": (0.05, 1.0), "marker_size": (1.0, 12.0), "lead": (0.0, 600.0)}
BOOL_KEYS = {"show_raw", "shade", "conc_labels", "response_labels", "show_legend", "align"}
CHOICE_KEYS = {"dpi_export": (300, 600), "time_unit": ("min", "s", "h"), "figure_language": ("en", "ja"),
               "palette": None, "palette_reverse": (True, False)}
TEMPLATE_KEYS = frozenset(STYLE_KEYS) | set(NUMBER_KEYS) | BOOL_KEYS | set(CHOICE_KEYS)
MAX_TEMPLATE_BYTES = 64 * 1024
FORMAT = "gassensor-maker-style"


class StyleError(ValueError):
    pass


def clean_settings(settings: dict) -> dict:
    cleaned = dict(validate_style_settings({k: v for k, v in settings.items() if k in STYLE_KEYS}))
    for key, value in settings.items():
        if key in NUMBER_KEYS:
            low, high = NUMBER_KEYS[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                raise StyleError(f"{key} must be between {low:g} and {high:g}.")
            cleaned[key] = float(value)
        elif key in BOOL_KEYS:
            if not isinstance(value, bool):
                raise StyleError(f"{key} must be true or false.")
            cleaned[key] = value
        elif key in CHOICE_KEYS:
            choices = CHOICE_KEYS[key]
            if choices is None:
                from palettes import PALETTES
                choices = tuple(PALETTES)
            if value not in choices:
                raise StyleError(f"Unknown value for {key}.")
            cleaned[key] = value
    return cleaned


def encode_style_template(settings: dict, name: str = "Figure style") -> bytes:
    cleaned = clean_settings({k: v for k, v in settings.items() if k in TEMPLATE_KEYS})
    return json.dumps({"format": FORMAT, "version": 1, "name": name, "settings": cleaned},
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def decode_style_template(raw: bytes) -> dict:
    if len(raw) > MAX_TEMPLATE_BYTES:
        raise StyleError("Style template exceeds the 64 KB limit.")
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise StyleError("This is not a valid figure style JSON file.") from exc
    if (not isinstance(document, dict) or document.get("format") != FORMAT or document.get("version") != 1
            or not isinstance(document.get("settings"), dict)):
        raise StyleError("Unsupported figure style template.")
    if any(k not in TEMPLATE_KEYS for k in document["settings"]):
        raise StyleError("Style template contains settings unrelated to figure appearance.")
    return clean_settings(document["settings"])
