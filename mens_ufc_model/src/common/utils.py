from __future__ import annotations

import hashlib
import re
from typing import Any

import pandas as pd


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def slugify_url(url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    safe = re.sub(r"[^A-Za-z0-9]+", "_", url).strip("_")[:80]
    return f"{safe}_{digest}.html"


def parse_int(value: Any) -> int | None:
    text = clean_text(value)
    if text in {"", "--", "---"}:
        return None
    match = re.search(r"-?\d+", text)
    return int(match.group()) if match else None


def parse_float(value: Any) -> float | None:
    text = clean_text(value)
    if text in {"", "--", "---"}:
        return None
    text = text.replace("%", "")
    try:
        return float(text)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(match.group()) if match else None


def parse_percent(value: Any) -> float | None:
    value_float = parse_float(value)
    if value_float is None:
        return None
    if value_float > 1:
        return value_float / 100.0
    return value_float


def parse_landed_attempted(value: Any) -> tuple[int | None, int | None]:
    text = clean_text(value)
    if text in {"", "--", "---"}:
        return None, None
    nums = re.findall(r"\d+", text)
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    if len(nums) == 1:
        return int(nums[0]), None
    return None, None


def parse_time_to_seconds(value: Any) -> int | None:
    text = clean_text(value)
    if text in {"", "--", "---"}:
        return None
    if ":" not in text:
        return parse_int(text)
    parts = text.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return None
    return None


def fight_elapsed_seconds(
    round_value: Any,
    round_time: Any,
    default_round_seconds: int = 300,
) -> int | None:
    round_number = parse_int(round_value)
    seconds = parse_time_to_seconds(round_time)
    if round_number is None or seconds is None:
        return None
    return max(0, (round_number - 1) * default_round_seconds + seconds)


def normalize_division(bout_type: Any) -> str:
    text = clean_text(bout_type)
    text = re.sub(r"\s+Bout$", "", text, flags=re.I)
    text = text.replace("Women's Catch Weight", "Women's Catchweight")
    text = text.replace("Womenâ€™s", "Women's")
    return text


def is_womens_bout(bout_type: Any) -> bool:
    text = clean_text(bout_type).lower()
    return "women" in text or "women's" in text or "womenâ€™s" in text


def ensure_http(url: str) -> str:
    if url.startswith("https://ufcstats.com"):
        return url.replace("https://", "http://", 1)
    if url.startswith("https://www.ufcstats.com"):
        return url.replace("https://www.", "http://", 1)
    return url


def id_from_url(url: str) -> str:
    return clean_text(url).rstrip("/").split("/")[-1]


def safe_div(
    numerator: float | int | None,
    denominator: float | int | None,
    default: float | None = None,
) -> float | None:
    if numerator is None or denominator is None:
        return default
    try:
        if float(denominator) == 0:
            return default
        return float(numerator) / float(denominator)
    except Exception:
        return default


def parse_date_safe(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    return timestamp
