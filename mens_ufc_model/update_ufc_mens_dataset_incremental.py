#!/usr/bin/env python3
"""Safe incremental UFCStats updater for the migrated men's UFC dataset.

The lower-level men scripts are full-output builders. This wrapper provides the
operational safety contract around them:
- dry-run by default;
- project CSV writes require --apply;
- staged rows are audited before apply;
- derived rebuilds are explicit and logged.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.utils import clean_text, ensure_http, id_from_url, is_womens_bout  # noqa: E402
from src.data.ingest_ufcstats import (  # noqa: E402
    EVENT_COLUMNS,
    FIGHT_COLUMNS,
    FIGHT_STATS_COLUMNS,
    FIGHTER_COLUMNS,
    is_mens_weight_class,
    normalize_profile,
    parse_fight_detail,
)
from src.data.ufcstats_scraper import BASE_URL, UFCStatsScraper  # noqa: E402


UFCSTATS_COMPLETED_EVENTS_URL = "http://ufcstats.com/statistics/events/completed?page=all"
RAW_DIR = Path("data/raw/ufcstats_men")
PROCESSED_TRAINING = Path("data/processed/mens_training_rows.csv")
ELO_TRAINING = Path("data/processed/mens_training_rows_with_elo.csv")
ADVANCED_TRAINING = Path("data/processed/mens_training_rows_v2_advanced.csv")

UNSAFE_SKIP_STATUSES = {
    "skipped_future_event",
    "skipped_unresolved_result",
    "skipped_no_winner_loser",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely stage and optionally apply incremental men's UFCStats dataset updates."
    )
    parser.add_argument("--events-url", default=UFCSTATS_COMPLETED_EVENTS_URL)
    parser.add_argument(
        "--from-date",
        default=None,
        help="Inspect events on/after this date, YYYY-MM-DD. Defaults to latest raw fight date + 1 day.",
    )
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--max-fights", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.6)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--rebuild-derived",
        action="store_true",
        help="After a successful --apply with new raw fights, rebuild training, Elo, v2 advanced, and validation outputs.",
    )
    parser.add_argument("--backup-dir", default=None)
    parser.add_argument("--manifest-dir", default="_update_manifests")
    parser.add_argument(
        "--user-agent",
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Refresh cached UFCStats event/fight/profile pages during this run.",
    )
    parser.add_argument(
        "--allow-future-events",
        action="store_true",
        help="Allow completed-result rows dated after today. Default blocks them.",
    )
    parser.add_argument(
        "--allow-unsafe-apply",
        action="store_true",
        help="Allow --apply even if staged rows fail the safety audit. Intended only for manual repair.",
    )
    return parser.parse_args()


class SkippedFight(Exception):
    def __init__(self, status: str, reason: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.details = details or {}


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def one_line(value: Any) -> str:
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d") if pd.notna(value) else None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def project_path(path_text: str | None, default: Path) -> Path:
    path = Path(path_text) if path_text else default
    if not path.is_absolute():
        path = ROOT / path
    return path


def validate_events_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host == "ufc.com" or host.endswith(".ufc.com"):
        raise ValueError("--events-url must not point at UFC.com.")
    if host not in {"ufcstats.com", "www.ufcstats.com"}:
        raise ValueError("--events-url must point at UFCStats.")


def make_scraper(args: argparse.Namespace) -> UFCStatsScraper:
    scraper = UFCStatsScraper(
        cache_dir=ROOT / "cache",
        sleep_seconds=float(args.sleep),
        refresh_cache=bool(args.refresh_cache),
        timeout=int(max(float(args.timeout), 1.0)),
    )
    scraper.session.headers.update({"User-Agent": args.user_agent})
    return scraper


def original_marker_value(value: Any) -> str:
    return clean_text(value)


def marker_value(value: Any) -> str:
    marker_text = clean_text(value)
    marker_upper = marker_text.upper()
    marker_words = marker_upper.replace("_", " ").replace("-", " ")
    marker_words = " ".join(marker_words.split())
    marker_compact = marker_words.replace(" ", "")

    if marker_upper in {"", "--", "---", "NAN", "NONE", "NULL"}:
        return ""
    if marker_words in {"W", "WIN", "WINNER"}:
        return "W"
    if marker_words in {"L", "LOSS", "LOSER", "LOSE", "LOST"}:
        return "L"
    if marker_words in {"D", "DRAW"}:
        return "D"
    if marker_words in {"NC", "N/C", "N C", "NO CONTEST"} or marker_compact in {"NC", "NOCONTEST"}:
        return "NC"
    return marker_upper


def is_blank_marker(value: Any) -> bool:
    return marker_value(value) == ""


def result_marker_manifest_fields(fight_meta: dict[str, Any]) -> dict[str, Any]:
    original_1 = fight_meta.get("original_result_marker_1")
    original_2 = fight_meta.get("original_result_marker_2")
    if original_1 is None:
        original_1 = original_marker_value(fight_meta.get("fighter_1_result_marker"))
    if original_2 is None:
        original_2 = original_marker_value(fight_meta.get("fighter_2_result_marker"))

    normalized_1 = fight_meta.get("normalized_result_marker_1")
    normalized_2 = fight_meta.get("normalized_result_marker_2")
    if normalized_1 is None:
        normalized_1 = marker_value(fight_meta.get("fighter_1_result_marker"))
    if normalized_2 is None:
        normalized_2 = marker_value(fight_meta.get("fighter_2_result_marker"))

    return {
        "result_marker_inference_used": bool(fight_meta.get("result_marker_inference_used", False)),
        "result_marker_inference_reason": fight_meta.get("result_marker_inference_reason", "not_evaluated"),
        "original_result_marker_1": original_1,
        "original_result_marker_2": original_2,
        "normalized_result_marker_1": normalized_1,
        "normalized_result_marker_2": normalized_2,
    }


def normalize_fight_meta_result_markers(
    fight_meta: dict[str, Any],
    event: dict[str, Any],
    today: pd.Timestamp,
    allow_future_events: bool,
    existing_fight_ids: set[str] | None = None,
) -> None:
    original_markers = [
        original_marker_value(fight_meta.get("fighter_1_result_marker")),
        original_marker_value(fight_meta.get("fighter_2_result_marker")),
    ]
    normalized_markers = [marker_value(original_markers[0]), marker_value(original_markers[1])]
    final_markers = list(normalized_markers)
    fighters = [clean_text(fight_meta.get("fighter_1")), clean_text(fight_meta.get("fighter_2"))]
    event_date = pd.to_datetime(event.get("event_date"), errors="coerce")
    event_date = pd.Timestamp(event_date).normalize() if pd.notna(event_date) else pd.NaT
    fight_id = clean_text(fight_meta.get("fight_id") or id_from_url(str(fight_meta.get("fight_url") or "")))
    existing_fight_ids = existing_fight_ids or set()

    inference_used = False
    inference_reason = "not_needed"
    if normalized_markers.count("W") == 1 and normalized_markers.count("") == 1:
        blank_index = normalized_markers.index("")
        if not all(fighters):
            inference_reason = "not_inferred_missing_fighter_name"
        elif pd.isna(event_date):
            inference_reason = "not_inferred_unknown_event_date"
        elif event_date > today:
            inference_reason = "not_inferred_future_event"
        elif fight_id and fight_id in existing_fight_ids:
            inference_reason = "not_inferred_existing_fight_id"
        else:
            final_markers[blank_index] = "L"
            inference_used = True
            inference_reason = f"one_winner_marker_blank_opponent_inferred_fighter_{blank_index + 1}_loss"
    elif normalized_markers.count("W") == 1 and normalized_markers.count("L") == 1:
        inference_reason = "not_needed_complete_w_l_pair"
    elif normalized_markers.count("") == 2:
        inference_reason = "not_inferred_both_markers_blank"
    elif any(marker in {"D", "NC"} for marker in normalized_markers):
        inference_reason = "not_inferred_draw_or_no_contest_marker"
    else:
        inference_reason = "not_inferred_ambiguous_markers"

    fight_meta["original_result_marker_1"] = original_markers[0]
    fight_meta["original_result_marker_2"] = original_markers[1]
    fight_meta["normalized_result_marker_1"] = final_markers[0]
    fight_meta["normalized_result_marker_2"] = final_markers[1]
    fight_meta["result_marker_inference_used"] = inference_used
    fight_meta["result_marker_inference_reason"] = inference_reason
    fight_meta["fighter_1_result_marker"] = final_markers[0]
    fight_meta["fighter_2_result_marker"] = final_markers[1]


def blankish_series(series: pd.Series) -> pd.Series:
    text = series.astype(str).map(clean_text).str.lower()
    return series.isna() | text.isin({"", "nan", "none", "null", "--", "---"})


def select_completed_events(events, cutoff, today, max_events=None):
    """Exclude future listings before imposing the bounded inspection limit."""
    selected = [event for event in events if cutoff <= pd.Timestamp(event["event_date"]).normalize() <= today]
    return selected[:max_events] if max_events is not None else selected


def parse_event_list(soup: BeautifulSoup) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    date_re = re.compile(
        r"\b("
        r"January|February|March|April|May|June|July|August|September|October|November|December"
        r")\s+\d{1,2},\s+\d{4}\b",
        flags=re.I,
    )

    for row in soup.select("tr"):
        link = row.select_one('a[href*="/event-details/"]')
        if not link or not link.get("href"):
            continue

        event_url = ensure_http(urljoin(BASE_URL, link.get("href")))
        event_name = clean_text(link.get_text(" "))
        row_text = clean_text(row.get_text(" "))
        cells = [clean_text(td.get_text(" ")) for td in row.select("td")]

        event_date = None
        for cell in cells:
            dt = pd.to_datetime(cell, errors="coerce")
            if pd.notna(dt):
                event_date = pd.Timestamp(dt).normalize()
                break
        if event_date is None:
            match = date_re.search(row_text)
            if match:
                dt = pd.to_datetime(match.group(0), errors="coerce")
                if pd.notna(dt):
                    event_date = pd.Timestamp(dt).normalize()

        location = cells[-1] if cells else ""
        if not location and event_date is not None:
            cleaned = row_text.replace(event_name, "", 1).strip() if event_name else row_text
            match = date_re.search(cleaned)
            if match:
                cleaned = cleaned.replace(match.group(0), "", 1).strip()
            location = clean_text(cleaned)

        if event_name and event_url and event_date is not None:
            events.append(
                {
                    "event_id": id_from_url(event_url),
                    "event_name": event_name,
                    "event_date": event_date,
                    "location": location,
                    "event_url": event_url,
                    "source_url": event_url,
                }
            )

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        if event["event_url"] in seen:
            continue
        seen.add(event["event_url"])
        unique.append(event)
    return sorted(unique, key=lambda item: item["event_date"])


def event_row(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event.get("event_id", ""),
        "event_name": event.get("event_name", ""),
        "event_date": iso_date(event.get("event_date")),
        "location": event.get("location", ""),
        "source_url": event.get("source_url") or event.get("event_url", ""),
    }


def iso_date(value: Any) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(ts) else pd.Timestamp(ts).strftime("%Y-%m-%d")


def load_csv(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns or [])
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def save_csv(df: pd.DataFrame, path: Path, columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    if columns:
        for column in columns:
            if column not in out.columns:
                out[column] = ""
        out = out[columns]
    out.to_csv(path, index=False, encoding="utf-8-sig")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=json_default),
        encoding="utf-8",
    )


def backup_file(path: Path, backup_dir: Path) -> Path | None:
    if not path.exists():
        return None
    resolved_root = ROOT.resolve()
    resolved_path = path.resolve()
    try:
        rel = resolved_path.relative_to(resolved_root)
    except ValueError:
        rel = Path(path.name)
    dest = backup_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(resolved_path, dest)
    return dest


def backup_files(paths: Iterable[Path], backup_dir: Path) -> list[str]:
    backed_up: list[str] = []
    for path in paths:
        dest = backup_file(ROOT / path if not path.is_absolute() else path, backup_dir)
        if dest is not None:
            backed_up.append(str(dest))
    return backed_up


def align_to_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for column in columns:
        if column not in out.columns:
            out[column] = ""
    return out[columns]


def append_rows(existing: pd.DataFrame, new_rows: pd.DataFrame, columns: list[str], sort_cols: list[str]) -> pd.DataFrame:
    existing = align_to_columns(existing, columns)
    new_rows = align_to_columns(new_rows, columns)
    if new_rows.empty:
        return existing.copy()
    out = pd.concat([existing, new_rows], ignore_index=True)
    available_sort_cols = [column for column in sort_cols if column in out.columns]
    if available_sort_cols:
        out = out.sort_values(available_sort_cols, kind="mergesort").reset_index(drop=True)
    return out


def latest_date_string(df: pd.DataFrame | None) -> str:
    if df is None or df.empty or "event_date" not in df.columns:
        return ""
    dates = pd.to_datetime(df["event_date"], errors="coerce")
    if dates.notna().sum() == 0:
        return ""
    return dates.max().date().isoformat()


def unique_fight_count(df: pd.DataFrame | None) -> int:
    if df is None or df.empty or "fight_id" not in df.columns:
        return 0
    return int(df["fight_id"].dropna().astype(str).map(clean_text).replace("", np.nan).dropna().nunique())


def count_future_rows(df: pd.DataFrame | None, today: pd.Timestamp) -> int:
    if df is None or df.empty or "event_date" not in df.columns:
        return 0
    dates = pd.to_datetime(df["event_date"], errors="coerce")
    return int((dates > today).sum())


def count_overfull_fight_ids(df: pd.DataFrame | None) -> int:
    if df is None or df.empty or "fight_id" not in df.columns:
        return 0
    counts = df["fight_id"].dropna().astype(str).map(clean_text).replace("", np.nan).dropna().value_counts()
    return int((counts > 2).sum())


def count_one_sided_fight_ids(df: pd.DataFrame | None) -> int:
    if df is None or df.empty or "fight_id" not in df.columns:
        return 0
    counts = df["fight_id"].dropna().astype(str).map(clean_text).replace("", np.nan).dropna().value_counts()
    return int((counts != 2).sum())


def count_duplicate_fight_rows(df: pd.DataFrame | None) -> int:
    if df is None or df.empty or "fight_id" not in df.columns:
        return 0
    fight_ids = df["fight_id"].dropna().astype(str).map(clean_text)
    return int(fight_ids[fight_ids != ""].duplicated().sum())


def count_unresolved_result_rows(df: pd.DataFrame | None) -> int:
    if df is None or df.empty:
        return 0
    mask = pd.Series(False, index=df.index)
    for column in ["result", "fighter_a_result", "fighter_b_result"]:
        if column in df.columns:
            mask = mask | blankish_series(df[column])
    if "winner_id" in df.columns and "result" in df.columns:
        result = df["result"].astype(str).map(clean_text).str.lower()
        winner_blank = blankish_series(df["winner_id"])
        loser_blank = blankish_series(df["loser_id"]) if "loser_id" in df.columns else pd.Series(False, index=df.index)
        mask = mask | ((result == "win_loss") & (winner_blank | loser_blank))
    return int(mask.sum())


def count_nan_target_rows(df: pd.DataFrame | None) -> int:
    if df is None or df.empty:
        return 0
    mask = pd.Series(False, index=df.index)
    for column in ["won", "fighter_a_won"]:
        if column in df.columns:
            values = pd.to_numeric(df[column], errors="coerce")
            mask = mask | values.isna()
    return int(mask.sum())


def dataset_metrics(prefix: str, df: pd.DataFrame | None, before: pd.DataFrame | None, today: pd.Timestamp) -> dict[str, Any]:
    rows = int(len(df)) if df is not None else 0
    metrics: dict[str, Any] = {
        f"{prefix}_rows": rows,
        f"{prefix}_unique_fights": unique_fight_count(df),
        f"{prefix}_latest_event_date": latest_date_string(df),
        f"{prefix}_future_rows_count": count_future_rows(df, today),
        f"{prefix}_unresolved_nan_result_rows_count": count_unresolved_result_rows(df),
        f"{prefix}_nan_target_rows_count": count_nan_target_rows(df),
        f"{prefix}_duplicate_fight_id_count": count_duplicate_fight_rows(df)
        if prefix == "raw_fights"
        else count_overfull_fight_ids(df),
        f"{prefix}_one_sided_fight_id_count": count_one_sided_fight_ids(df)
        if prefix in {"raw_fight_stats", "processed", "advanced"}
        else 0,
    }
    if before is not None:
        metrics[f"{prefix}_rows_before"] = int(len(before))
        metrics[f"{prefix}_rows_after"] = rows
        metrics[f"{prefix}_unique_fights_before"] = unique_fight_count(before)
        metrics[f"{prefix}_unique_fights_after"] = unique_fight_count(df)
        metrics[f"{prefix}_latest_event_date_before"] = latest_date_string(before)
        metrics[f"{prefix}_latest_event_date_after"] = latest_date_string(df)
    return metrics


def read_project_datasets() -> dict[str, pd.DataFrame]:
    return {
        "raw_events": load_csv(ROOT / RAW_DIR / "events.csv", EVENT_COLUMNS),
        "raw_fights": load_csv(ROOT / RAW_DIR / "fights.csv", FIGHT_COLUMNS),
        "raw_fight_stats": load_csv(ROOT / RAW_DIR / "fight_stats.csv", FIGHT_STATS_COLUMNS),
        "raw_fighters": load_csv(ROOT / RAW_DIR / "fighters.csv", FIGHTER_COLUMNS),
        "processed": load_csv(ROOT / PROCESSED_TRAINING),
        "training_elo": load_csv(ROOT / ELO_TRAINING),
        "advanced": load_csv(ROOT / ADVANCED_TRAINING),
    }


def is_mens_fight_meta(fight_meta: dict[str, Any]) -> bool:
    bout_type = fight_meta.get("bout_type") or fight_meta.get("division") or ""
    division = fight_meta.get("division") or bout_type
    return not is_womens_bout(bout_type) and is_mens_weight_class(division)


def validate_completed_fight_meta(
    fight_meta: dict[str, Any],
    event: dict[str, Any],
    today: pd.Timestamp,
    allow_future_events: bool,
    existing_fight_ids: set[str] | None = None,
) -> None:
    normalize_fight_meta_result_markers(
        fight_meta,
        event,
        today=today,
        allow_future_events=allow_future_events,
        existing_fight_ids=existing_fight_ids,
    )
    event_date = pd.to_datetime(event.get("event_date"), errors="coerce")
    event_date = pd.Timestamp(event_date).normalize() if pd.notna(event_date) else pd.NaT
    fighters = [clean_text(fight_meta.get("fighter_1")), clean_text(fight_meta.get("fighter_2"))]
    markers = [
        fight_meta.get("normalized_result_marker_1", marker_value(fight_meta.get("fighter_1_result_marker"))),
        fight_meta.get("normalized_result_marker_2", marker_value(fight_meta.get("fighter_2_result_marker"))),
    ]
    details = {
        "event_name": event.get("event_name", ""),
        "event_date": event_date.date().isoformat() if pd.notna(event_date) else "",
        "fighter_1": fighters[0],
        "fighter_2": fighters[1],
        "result_marker_1": markers[0],
        "result_marker_2": markers[1],
        **result_marker_manifest_fields(fight_meta),
    }
    if pd.notna(event_date) and event_date > today and not allow_future_events:
        raise SkippedFight("skipped_future_event", "event date is after today", details)
    if not fighters[0] or not fighters[1]:
        raise SkippedFight("skipped_unresolved_result", "could not parse both fighters", details)
    if any(is_blank_marker(marker) for marker in markers):
        raise SkippedFight("skipped_unresolved_result", "blank result marker", details)
    allowed = {"W", "L", "D", "NC"}
    if any(marker not in allowed for marker in markers):
        raise SkippedFight("skipped_unresolved_result", f"unsupported result markers: {markers}", details)
    if markers.count("W") != 1 or markers.count("L") != 1:
        raise SkippedFight("skipped_no_winner_loser", f"no single W/L result pair: {markers}", details)


def fight_manifest_base(fight_meta: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    marker_fields = result_marker_manifest_fields(fight_meta)
    return {
        "event_id": event.get("event_id", ""),
        "event_name": event.get("event_name", ""),
        "event_date": iso_date(event.get("event_date")),
        "fight_id": fight_meta.get("fight_id") or id_from_url(str(fight_meta.get("fight_url") or "")),
        "fight_url": fight_meta.get("fight_url", ""),
        "division": fight_meta.get("division", ""),
        "fighter_1": fight_meta.get("fighter_1", ""),
        "fighter_2": fight_meta.get("fighter_2", ""),
        "result_marker_1": marker_fields["normalized_result_marker_1"],
        "result_marker_2": marker_fields["normalized_result_marker_2"],
        **marker_fields,
    }


def audit_new_rows_for_apply(
    new_fights: pd.DataFrame,
    new_stats: pd.DataFrame,
    existing_fight_ids: set[str],
    today: pd.Timestamp,
    allow_future_events: bool,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    unsafe_indices: set[Any] = set()

    def add_issue(code: str, description: str, indices: Iterable[Any]) -> None:
        idx = list(indices)
        if not idx:
            return
        unsafe_indices.update(idx)
        fight_count = 0
        if "fight_id" in new_stats.columns:
            fight_count = int(new_stats.loc[idx, "fight_id"].dropna().astype(str).nunique())
        issues.append(
            {
                "code": code,
                "description": description,
                "row_count": int(len(idx)),
                "fight_count": fight_count,
            }
        )

    if new_stats.empty and new_fights.empty:
        return {"unsafe_rows_count": 0, "unsafe_fight_count": 0, "issues": []}

    if "event_date" not in new_stats.columns:
        add_issue("missing_event_date", "new rows have no event_date column", new_stats.index)
    else:
        dates = pd.to_datetime(new_stats["event_date"], errors="coerce")
        add_issue("blank_event_date", "new rows have blank or invalid event_date", dates[dates.isna()].index)
        if not allow_future_events:
            add_issue("future_event_date", "new rows have event_date after today", dates[dates > today].index)

    if "result" not in new_stats.columns:
        add_issue("missing_result", "new rows have no result column", new_stats.index)
    else:
        add_issue("blank_result", "new rows have blank result", new_stats[blankish_series(new_stats["result"])].index)
        result = new_stats["result"].astype(str).map(clean_text).str.lower()
        add_issue(
            "unsupported_result",
            "new rows contain result values outside win/loss",
            new_stats[~result.isin({"win", "loss"})].index,
        )

    if "won" not in new_stats.columns:
        add_issue("missing_won", "new rows have no won column", new_stats.index)
    else:
        won = pd.to_numeric(new_stats["won"], errors="coerce")
        add_issue("nan_winner_target", "new rows have NaN won target", won[won.isna()].index)
        add_issue("unsupported_winner_target", "new rows have won values outside 0/1", won[~won.isin([0, 1])].dropna().index)

    if "fight_id" not in new_stats.columns:
        add_issue("missing_fight_id", "new rows have no fight_id column", new_stats.index)
    else:
        fight_ids = new_stats["fight_id"].astype(str).map(clean_text)
        add_issue(
            "duplicate_existing_fight_id",
            "new rows contain fight_id values already present in the project dataset",
            new_stats[fight_ids.isin(existing_fight_ids)].index,
        )
        for fight_id, group in new_stats.groupby(fight_ids, dropna=False):
            if not fight_id:
                add_issue("missing_fight_id", "new rows contain blank fight_id", group.index)
                continue
            bad_shape = len(group) != 2
            if "fighter_id" in group.columns:
                fighter_ids = group["fighter_id"].astype(str).map(clean_text)
                bad_shape = bad_shape or fighter_ids.eq("").any() or fighter_ids.nunique() != 2
            if "fighter_name" in group.columns:
                fighter_names = group["fighter_name"].astype(str).map(clean_text)
                bad_shape = bad_shape or fighter_names.eq("").any() or fighter_names.nunique() != 2
            if bad_shape:
                add_issue("one_sided_fighter_rows", f"fight_id {fight_id} does not have exactly two fighter rows", group.index)
            if "won" in group.columns:
                won_values = pd.to_numeric(group["won"], errors="coerce").dropna().tolist()
                if sorted(won_values) != [0.0, 1.0]:
                    add_issue("missing_winner_loser", f"fight_id {fight_id} does not have one winner and one loser", group.index)

    if not new_fights.empty:
        fight_result = new_fights.get("result", pd.Series(dtype=str)).astype(str).map(clean_text).str.lower()
        bad_fight_rows = new_fights[~fight_result.isin({"win_loss"})]
        if not bad_fight_rows.empty and "fight_id" in new_stats.columns:
            bad_ids = set(bad_fight_rows["fight_id"].astype(str))
            add_issue(
                "unsupported_fight_result",
                "new fight rows contain non-win_loss results",
                new_stats[new_stats["fight_id"].astype(str).isin(bad_ids)].index,
            )
        if "fight_id" in new_fights.columns:
            duplicate_new_fights = new_fights[new_fights["fight_id"].astype(str).duplicated(keep=False)]
            if not duplicate_new_fights.empty and "fight_id" in new_stats.columns:
                dup_ids = set(duplicate_new_fights["fight_id"].astype(str))
                add_issue(
                    "duplicate_new_fight_id",
                    "new fight rows contain duplicate fight_id values",
                    new_stats[new_stats["fight_id"].astype(str).isin(dup_ids)].index,
                )

    unsafe_fights = 0
    if unsafe_indices and "fight_id" in new_stats.columns:
        unsafe_fights = int(new_stats.loc[list(unsafe_indices), "fight_id"].dropna().astype(str).nunique())
    return {
        "unsafe_rows_count": int(len(unsafe_indices)),
        "unsafe_fight_count": int(unsafe_fights),
        "issues": issues,
    }


def count_rejected_unsafe_rows(fight_manifest: list[dict[str, Any]]) -> int:
    rows = 0
    for rec in fight_manifest:
        if rec.get("status") not in UNSAFE_SKIP_STATUSES:
            continue
        if rec.get("fighter_1") and rec.get("fighter_2"):
            rows += 2
    return rows


def collect_profile_rows(
    scraper: UFCStatsScraper,
    profile_urls: dict[str, str],
    names_by_id: dict[str, str],
    existing_fighter_ids: set[str],
    manifest_dir: Path,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    for fighter_id, profile_url in sorted(profile_urls.items()):
        if not fighter_id or fighter_id in existing_fighter_ids:
            continue
        try:
            profile = scraper.get_fighter_profile(profile_url)
            row = normalize_profile(profile, profile_url)
            if not row.get("fighter_name"):
                row["fighter_name"] = names_by_id.get(fighter_id, "")
            rows.append(row)
            manifest.append({"fighter_id": fighter_id, "fighter_name": row.get("fighter_name", ""), "status": "scraped", "source_url": profile_url})
        except Exception as exc:
            rows.append(
                {
                    "fighter_id": fighter_id,
                    "fighter_name": names_by_id.get(fighter_id, ""),
                    "source_url": ensure_http(profile_url),
                }
            )
            manifest.append(
                {
                    "fighter_id": fighter_id,
                    "fighter_name": names_by_id.get(fighter_id, ""),
                    "status": "profile_fetch_error",
                    "source_url": profile_url,
                    "error": one_line(exc),
                }
            )
    profile_manifest = pd.DataFrame(manifest)
    save_csv(profile_manifest, manifest_dir / "fighter_profiles_inspected.csv")
    return pd.DataFrame(rows)


def write_post_update_audit(
    manifest_dir: Path,
    stamp: str,
    mode: str,
    apply_status: str,
    today: pd.Timestamp,
    before: dict[str, pd.DataFrame],
    after: dict[str, pd.DataFrame],
    new_fights: pd.DataFrame,
    new_stats: pd.DataFrame,
    new_fighters: pd.DataFrame,
    safety_audit: dict[str, Any],
    scrape_counts: dict[str, Any],
    rebuild_derived_status: str,
) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "generated_at": stamp,
        "mode": mode,
        "apply_status": apply_status,
        "today": today.date().isoformat(),
        "raw_event_links_found": int(scrape_counts.get("raw_event_links_found", 0)),
        "completed_events_found": int(scrape_counts.get("completed_events_found", 0)),
        "events_inspected": int(scrape_counts.get("events_inspected", 0)),
        "men_fights_scraped": unique_fight_count(new_fights),
        "new_raw_fight_rows": int(len(new_fights)),
        "new_fight_stat_rows": int(len(new_stats)),
        "new_fighter_profile_rows": int(len(new_fighters)),
        "new_unsafe_rows_count": int(safety_audit.get("unsafe_rows_count", 0)),
        "new_unsafe_fight_count": int(safety_audit.get("unsafe_fight_count", 0)),
        "new_unsafe_issue_count": int(len(safety_audit.get("issues", []))),
        "new_unsafe_issues_json": json.dumps(safety_audit.get("issues", []), sort_keys=True),
        "rebuild_derived_status": rebuild_derived_status,
    }
    for key in ["raw_events", "raw_fights", "raw_fight_stats", "raw_fighters", "processed", "training_elo", "advanced"]:
        audit.update(dataset_metrics(key, after.get(key), before.get(key), today))

    audit["raw_rows_before"] = audit.get("raw_fight_stats_rows_before", 0)
    audit["raw_rows_after"] = audit.get("raw_fight_stats_rows_after", 0)
    audit["processed_rows_before"] = audit.get("processed_rows_before", 0)
    audit["processed_rows_after"] = audit.get("processed_rows_after", 0)
    audit["advanced_rows_before"] = audit.get("advanced_rows_before", 0)
    audit["advanced_rows_after"] = audit.get("advanced_rows_after", 0)
    audit["unique_fights_before"] = audit.get("raw_fights_unique_fights_before", 0)
    audit["unique_fights_after"] = audit.get("raw_fights_unique_fights_after", 0)
    audit["latest_event_date_before"] = audit.get("raw_fights_latest_event_date_before", "")
    audit["latest_event_date_after"] = audit.get("raw_fights_latest_event_date_after", "")
    audit["future_rows_count"] = int(
        audit.get("raw_fights_future_rows_count", 0)
        + audit.get("raw_fight_stats_future_rows_count", 0)
        + audit.get("processed_future_rows_count", 0)
        + audit.get("advanced_future_rows_count", 0)
    )
    audit["unresolved_nan_result_rows_count"] = int(
        audit.get("raw_fights_unresolved_nan_result_rows_count", 0)
        + audit.get("raw_fight_stats_unresolved_nan_result_rows_count", 0)
        + audit.get("processed_unresolved_nan_result_rows_count", 0)
        + audit.get("processed_nan_target_rows_count", 0)
        + audit.get("advanced_unresolved_nan_result_rows_count", 0)
        + audit.get("advanced_nan_target_rows_count", 0)
    )
    audit["duplicate_fight_id_count"] = int(
        audit.get("raw_fights_duplicate_fight_id_count", 0)
        + audit.get("raw_fight_stats_duplicate_fight_id_count", 0)
        + audit.get("processed_duplicate_fight_id_count", 0)
        + audit.get("advanced_duplicate_fight_id_count", 0)
    )

    save_csv(pd.DataFrame([audit]), manifest_dir / "post_update_audit.csv")
    write_json(manifest_dir / "post_update_audit.json", audit)
    return audit


def summary_text(summary: dict[str, Any]) -> str:
    lines = [
        "SAFE MEN DATASET UPDATE SUMMARY",
        "=" * 80,
        f"- completed events found: {summary.get('completed_events_found', '')}",
        f"- events inspected: {summary.get('events_inspected', '')}",
        f"- men fights scraped: {summary.get('men_fights_scraped', '')}",
        f"- rows to add: {summary.get('rows_to_add', '')}",
        f"- unsafe rows blocked: {summary.get('unsafe_rows_blocked', '')}",
        f"- raw rows before/after: {summary.get('raw_rows_before_after', '')}",
        f"- processed rows before/after: {summary.get('processed_rows_before_after', '')}",
        f"- advanced rows before/after: {summary.get('advanced_rows_before_after', '')}",
        f"- derived rebuild status: {summary.get('rebuild_derived_status', '')}",
        f"- final latest date: {summary.get('final_latest_date', '')}",
        f"- apply status: {summary.get('apply_status', '')}",
        f"- manifest folder: {summary.get('manifest_dir', '')}",
    ]
    return "\n".join(lines) + "\n"


def print_and_write_summary(manifest_dir: Path, summary: dict[str, Any]) -> None:
    text = summary_text(summary)
    (manifest_dir / "safe_update_summary.txt").write_text(text, encoding="utf-8")
    print()
    print(text.rstrip())


def build_summary(
    manifest_dir: Path,
    before: dict[str, pd.DataFrame],
    after: dict[str, pd.DataFrame],
    new_stats: pd.DataFrame,
    new_fights: pd.DataFrame,
    unsafe_rows_blocked: int,
    scrape_counts: dict[str, Any],
    apply_status: str,
    rebuild_derived_status: str,
) -> dict[str, Any]:
    return {
        "completed_events_found": scrape_counts.get("completed_events_found", 0),
        "events_inspected": scrape_counts.get("events_inspected", 0),
        "men_fights_scraped": unique_fight_count(new_fights),
        "rows_to_add": int(len(new_stats)),
        "unsafe_rows_blocked": int(unsafe_rows_blocked),
        "raw_rows_before_after": f"{len(before['raw_fight_stats'])} / {len(after['raw_fight_stats'])}",
        "processed_rows_before_after": f"{len(before['processed'])} / {len(after['processed'])}",
        "advanced_rows_before_after": f"{len(before['advanced'])} / {len(after['advanced'])}",
        "rebuild_derived_status": rebuild_derived_status,
        "final_latest_date": latest_date_string(after["raw_fights"]),
        "apply_status": apply_status,
        "manifest_dir": str(manifest_dir),
    }


def run_logged_command(cmd: list[str], cwd: Path, stdout_path: Path, stderr_path: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(part) for part in cmd],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    stdout_path.write_text(result.stdout or "", encoding="utf-8", errors="replace")
    stderr_path.write_text(result.stderr or "", encoding="utf-8", errors="replace")
    return result


def run_derived_rebuild(manifest_dir: Path, backup_dir: Path) -> str:
    derived_paths = [
        Path("data/interim/mens_prefight_snapshots.csv"),
        Path("data/interim/mens_model_ready_matchups.csv"),
        PROCESSED_TRAINING,
        Path("data/processed/mens_training_rows.manifest.json"),
        ELO_TRAINING,
        Path("data/processed/mens_elo_feature_audit.json"),
        ADVANCED_TRAINING,
        Path("data/processed/mens_v2_feature_audit.json"),
        Path("data/processed/mens_v2_feature_completeness.csv"),
        Path("data/processed/mens_training_rows_v3_bayes_smoothing_candidate.csv"),
        Path("data/processed/mens_v3_bayes_smoothing_candidate_audit.json"),
        Path("data/processed/mens_validation_summary.json"),
        Path("data/processed/mens_feature_completeness.csv"),
    ]
    backed_up = backup_files(derived_paths, backup_dir)
    rebuild_manifest: dict[str, Any] = {
        "status": "running",
        "backup_dir": str(backup_dir),
        "backed_up_files": backed_up,
        "steps": [],
    }
    write_json(manifest_dir / "derived_rebuild_status.json", rebuild_manifest)

    steps = [
        (
            "build_training_dataset",
            [sys.executable, "src/data/build_mens_training_dataset.py"],
        ),
        (
            "add_elo_features",
            [sys.executable, "src/features/add_mens_elo_features.py"],
        ),
        (
            "build_advanced_v2_features",
            [sys.executable, "src/features/build_mens_advanced_features.py"],
        ),
        (
            "build_v3_bayes_smoothing_features",
            [sys.executable, "src/features/build_mens_bayes_smoothing_candidate.py"],
        ),
        (
            "validate_mens_dataset",
            [sys.executable, "src/validation/validate_mens_dataset.py", "--allow-mirrored"],
        ),
    ]

    for idx, (name, cmd) in enumerate(steps, start=1):
        stdout_path = manifest_dir / f"derived_rebuild_{idx:02d}_{name}_stdout.txt"
        stderr_path = manifest_dir / f"derived_rebuild_{idx:02d}_{name}_stderr.txt"
        print(f"Running derived rebuild step {idx}/{len(steps)}: {name}")
        result = run_logged_command(cmd, ROOT, stdout_path, stderr_path)
        step_record = {
            "name": name,
            "command": subprocess.list2cmdline([str(part) for part in cmd]),
            "return_code": result.returncode,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
        rebuild_manifest["steps"].append(step_record)
        if result.returncode != 0:
            rebuild_manifest["status"] = "failed"
            rebuild_manifest["failed_step"] = name
            write_json(manifest_dir / "derived_rebuild_status.json", rebuild_manifest)
            raise RuntimeError(f"Derived rebuild step failed: {name} (exit {result.returncode})")
        write_json(manifest_dir / "derived_rebuild_status.json", rebuild_manifest)

    rebuild_manifest["status"] = "completed"
    write_json(manifest_dir / "derived_rebuild_status.json", rebuild_manifest)
    return "completed"


def write_raw_outputs(
    events: pd.DataFrame,
    fights: pd.DataFrame,
    fight_stats: pd.DataFrame,
    fighters: pd.DataFrame,
) -> None:
    save_csv(events, ROOT / RAW_DIR / "events.csv", EVENT_COLUMNS)
    save_csv(fights, ROOT / RAW_DIR / "fights.csv", FIGHT_COLUMNS)
    save_csv(fight_stats, ROOT / RAW_DIR / "fight_stats.csv", FIGHT_STATS_COLUMNS)
    save_csv(fighters, ROOT / RAW_DIR / "fighters.csv", FIGHTER_COLUMNS)


def main() -> int:
    args = parse_args()
    validate_events_url(args.events_url)
    stamp = now_stamp()
    today = pd.Timestamp(datetime.now().date())
    manifest_dir = project_path(args.manifest_dir, Path("_update_manifests")) / stamp
    manifest_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = project_path(args.backup_dir, Path(f"_backup_before_update_{stamp}"))

    before = read_project_datasets()
    existing_fight_ids = set(before["raw_fights"].get("fight_id", pd.Series(dtype=str)).dropna().astype(str).map(clean_text))
    existing_event_ids = set(before["raw_events"].get("event_id", pd.Series(dtype=str)).dropna().astype(str).map(clean_text))
    existing_fighter_ids = set(before["raw_fighters"].get("fighter_id", pd.Series(dtype=str)).dropna().astype(str).map(clean_text))

    if args.from_date:
        cutoff = pd.to_datetime(args.from_date, errors="coerce")
    else:
        latest = pd.to_datetime(before["raw_fights"].get("event_date", pd.Series(dtype=str)), errors="coerce").max()
        cutoff = latest + pd.Timedelta(days=1)
    if pd.isna(cutoff):
        raise ValueError("Could not determine cutoff date. Use --from-date YYYY-MM-DD.")
    cutoff = pd.Timestamp(cutoff).normalize()

    print("\nINCREMENTAL UFC MEN'S DATASET UPDATE")
    print("=" * 100)
    print(f"Raw dir:          {RAW_DIR}")
    print(f"Existing fights:  {len(existing_fight_ids):,}")
    print(f"Latest date:      {latest_date_string(before['raw_fights'])}")
    print(f"Scrape cutoff:    event_date >= {cutoff.date()}")
    print(f"Today:            {today.date()}")
    print(f"Mode:             {'APPLY' if args.apply else 'DRY RUN'}")

    scraper = make_scraper(args)
    original_refresh_cache = scraper.refresh_cache
    scraper.refresh_cache = True
    events_html = scraper.fetch_html(args.events_url)
    scraper.refresh_cache = original_refresh_cache
    events_soup = BeautifulSoup(events_html, "lxml")
    raw_event_links = events_soup.select('a[href*="/event-details/"]')
    events = parse_event_list(events_soup)
    if not events:
        raise ValueError("UFCStats returned no parseable completed events; refusing an apparent empty update.")
    new_events = select_completed_events(events, cutoff, today, args.max_events)

    print(f"Raw event links found:           {len(raw_event_links)}")
    print(f"Completed UFCStats events found: {len(events)}")
    print(f"Events to inspect:               {len(new_events)}")

    event_manifest: list[dict[str, Any]] = []
    fight_manifest: list[dict[str, Any]] = []
    event_rows_by_id: dict[str, dict[str, Any]] = {}
    staged_fights: list[dict[str, Any]] = []
    staged_stats: list[dict[str, Any]] = []
    staged_profile_urls: dict[str, str] = {}
    names_by_id: dict[str, str] = {}

    events_inspected = 0
    fights_scraped = 0
    max_fights_reached = False

    # Always re-fetch event pages and fight detail pages for new events.
    # Event pages are sometimes cached before UFCStats enters results, causing
    # blank W/L markers on every subsequent run until the stale cache is cleared.
    scraper.refresh_cache = True

    for event in new_events:
        print(f"\nEvent: {iso_date(event['event_date'])} | {event['event_name']}")
        try:
            fight_metas = scraper.get_event_fights(event["event_url"])
            events_inspected += 1
            event_manifest.append(
                {
                    **event_row(event),
                    "status": "ok",
                    "fight_links_found": len(fight_metas),
                }
            )
            print(f"  fight links found: {len(fight_metas)}")
        except Exception as exc:
            event_manifest.append({**event_row(event), "status": "event_fetch_error", "error": one_line(exc)})
            print(f"  ERROR fetching event: {exc}")
            continue

        for fight_meta in fight_metas:
            fight_id = clean_text(fight_meta.get("fight_id") or id_from_url(str(fight_meta.get("fight_url") or "")))
            base = fight_manifest_base(fight_meta, event)

            if not is_mens_fight_meta(fight_meta):
                fight_manifest.append({**base, "status": "not_mens_bout"})
                continue
            if fight_id in existing_fight_ids:
                fight_manifest.append({**base, "status": "already_exists"})
                continue
            if args.max_fights is not None and fights_scraped >= args.max_fights:
                max_fights_reached = True
                break

            try:
                validate_completed_fight_meta(
                    fight_meta,
                    event,
                    today=today,
                    allow_future_events=bool(args.allow_future_events),
                    existing_fight_ids=existing_fight_ids,
                )
                base = fight_manifest_base(fight_meta, event)
                event_series = pd.Series(
                    {
                        "event_id": event["event_id"],
                        "event_name": event["event_name"],
                        "event_date": event["event_date"],
                        "location": event.get("location", ""),
                        "event_url": event["event_url"],
                    }
                )
                fight_row, stat_rows, profile_urls = parse_fight_detail(scraper, event_series, fight_meta)
                if not fight_row.get("is_mens_bout"):
                    fight_manifest.append({**base, "status": "not_mens_bout"})
                    continue
                if fight_row.get("result") != "win_loss" or not fight_row.get("winner_id") or not fight_row.get("loser_id"):
                    raise SkippedFight("skipped_no_winner_loser", "parsed fight did not produce one winner and one loser", base)
                if len(stat_rows) != 2:
                    raise SkippedFight("skipped_unresolved_result", "parsed fight did not produce two fighter stat rows", base)

                staged_fights.append(fight_row)
                staged_stats.extend(stat_rows)
                staged_profile_urls.update({k: v for k, v in profile_urls.items() if k and v})
                for row in stat_rows:
                    if row.get("fighter_id"):
                        names_by_id[str(row["fighter_id"])] = row.get("fighter_name") or ""
                event_rows_by_id[event["event_id"]] = event_row(event)
                fights_scraped += 1
                fight_manifest.append(
                    {
                        **base,
                        "status": "scraped",
                        "winner_id": fight_row.get("winner_id", ""),
                        "loser_id": fight_row.get("loser_id", ""),
                        "method": fight_row.get("method", ""),
                    }
                )
                print(f"  + men's fight: {base.get('fighter_1')} vs {base.get('fighter_2')} | {base.get('division')}")
            except SkippedFight as exc:
                rec = {**base, "status": exc.status, "reason": exc.reason}
                rec.update(exc.details)
                fight_manifest.append(rec)
                print(f"  - {exc.status}: {base.get('fighter_1', '')} vs {base.get('fighter_2', '')} ({exc.reason})")
            except Exception as exc:
                fight_manifest.append({**base, "status": "fight_fetch_error", "error": one_line(exc)})
                print(f"  ERROR fight {fight_id}: {exc}")

        if max_fights_reached:
            break

    scraper.refresh_cache = bool(args.refresh_cache)

    new_fights = pd.DataFrame(staged_fights)
    new_stats = pd.DataFrame(staged_stats)
    new_event_ids = set(new_fights.get("event_id", pd.Series(dtype=str)).astype(str)) if not new_fights.empty else set()
    new_events_df = pd.DataFrame(
        [
            row
            for event_id, row in event_rows_by_id.items()
            if event_id in new_event_ids and event_id not in existing_event_ids
        ]
    )
    new_fighters = collect_profile_rows(
        scraper=scraper,
        profile_urls=staged_profile_urls,
        names_by_id=names_by_id,
        existing_fighter_ids=existing_fighter_ids,
        manifest_dir=manifest_dir,
    )

    new_events_df = align_to_columns(new_events_df, EVENT_COLUMNS)
    new_fights = align_to_columns(new_fights, FIGHT_COLUMNS)
    new_stats = align_to_columns(new_stats, FIGHT_STATS_COLUMNS)
    new_fighters = align_to_columns(new_fighters, FIGHTER_COLUMNS)

    save_csv(pd.DataFrame(event_manifest), manifest_dir / "events_inspected.csv")
    save_csv(pd.DataFrame(fight_manifest), manifest_dir / "fights_inspected.csv")
    save_csv(new_fights, manifest_dir / "new_fight_rows_preview.csv", FIGHT_COLUMNS)
    save_csv(new_stats, manifest_dir / "new_fight_stats_rows_preview.csv", FIGHT_STATS_COLUMNS)
    save_csv(new_fighters, manifest_dir / "new_fighter_rows_preview.csv", FIGHTER_COLUMNS)
    save_csv(new_events_df, manifest_dir / "new_event_rows_preview.csv", EVENT_COLUMNS)

    safety_audit = audit_new_rows_for_apply(
        new_fights=new_fights,
        new_stats=new_stats,
        existing_fight_ids=existing_fight_ids,
        today=today,
        allow_future_events=bool(args.allow_future_events),
    )
    write_json(manifest_dir / "new_rows_safety_audit.json", safety_audit)

    updated = dict(before)
    updated["raw_events"] = append_rows(before["raw_events"], new_events_df, EVENT_COLUMNS, ["event_date", "event_id"])
    updated["raw_fights"] = append_rows(before["raw_fights"], new_fights, FIGHT_COLUMNS, ["event_date", "event_id", "fight_id"])
    updated["raw_fight_stats"] = append_rows(
        before["raw_fight_stats"],
        new_stats,
        FIGHT_STATS_COLUMNS,
        ["event_date", "event_id", "fight_id", "fighter_id"],
    )
    updated["raw_fighters"] = append_rows(before["raw_fighters"], new_fighters, FIGHTER_COLUMNS, ["fighter_name", "fighter_id"])

    rejected_unsafe_rows = count_rejected_unsafe_rows(fight_manifest)
    unsafe_rows_blocked = int(safety_audit["unsafe_rows_count"]) + rejected_unsafe_rows
    scrape_counts = {
        "raw_event_links_found": len(raw_event_links),
        "completed_events_found": len(events),
        "events_inspected": events_inspected,
    }

    print("\nSCRAPE SUMMARY")
    print("=" * 100)
    print(f"New men's fights scraped: {unique_fight_count(new_fights)}")
    print(f"New fight-stat rows:      {len(new_stats)}")
    print(f"Unsafe staged rows:       {safety_audit['unsafe_rows_count']}")
    print(f"Rejected unsafe rows:     {rejected_unsafe_rows}")
    print(f"Manifest folder:          {manifest_dir}")

    apply_status = "dry_run"
    rebuild_derived_status = "not_requested"

    if not args.apply:
        if args.rebuild_derived:
            rebuild_derived_status = "skipped_dry_run"
        if args.audit:
            write_post_update_audit(
                manifest_dir,
                stamp,
                "dry_run",
                apply_status,
                today,
                before,
                updated,
                new_fights,
                new_stats,
                new_fighters,
                safety_audit,
                scrape_counts,
                rebuild_derived_status,
            )
        summary = build_summary(
            manifest_dir,
            before,
            updated,
            new_stats,
            new_fights,
            unsafe_rows_blocked,
            scrape_counts,
            apply_status,
            rebuild_derived_status,
        )
        print("\nDRY RUN COMPLETE - no project files were changed.")
        print("Review preview files in the manifest folder. Re-run with --apply only if the manifest is safe.")
        print_and_write_summary(manifest_dir, summary)
        return 0

    if int(safety_audit["unsafe_rows_count"]) > 0 and not args.allow_unsafe_apply:
        apply_status = "blocked_unsafe"
        if args.audit:
            write_post_update_audit(
                manifest_dir,
                stamp,
                "apply_blocked",
                apply_status,
                today,
                before,
                before,
                new_fights,
                new_stats,
                new_fighters,
                safety_audit,
                scrape_counts,
                rebuild_derived_status,
            )
        summary = build_summary(
            manifest_dir,
            before,
            before,
            new_stats,
            new_fights,
            unsafe_rows_blocked,
            scrape_counts,
            apply_status,
            rebuild_derived_status,
        )
        print("\nUnsafe update blocked. Review manifest.")
        print_and_write_summary(manifest_dir, summary)
        return 2

    if new_fights.empty and new_stats.empty:
        apply_status = "no_changes"
        if args.rebuild_derived:
            rebuild_derived_status = "skipped_no_changes"
        if args.audit:
            write_post_update_audit(
                manifest_dir,
                stamp,
                "apply_no_changes",
                apply_status,
                today,
                before,
                before,
                new_fights,
                new_stats,
                new_fighters,
                safety_audit,
                scrape_counts,
                rebuild_derived_status,
            )
        summary = build_summary(
            manifest_dir,
            before,
            before,
            new_stats,
            new_fights,
            unsafe_rows_blocked,
            scrape_counts,
            apply_status,
            rebuild_derived_status,
        )
        print("\nNo new men's fights found. Nothing to update.")
        print_and_write_summary(manifest_dir, summary)
        return 0

    print("\nWRITING RAW DATA UPDATES")
    print("=" * 100)
    backup_files(
        [
            RAW_DIR / "events.csv",
            RAW_DIR / "fights.csv",
            RAW_DIR / "fight_stats.csv",
            RAW_DIR / "fighters.csv",
            RAW_DIR / "ingest_manifest.json",
        ],
        backup_dir,
    )
    write_raw_outputs(
        updated["raw_events"],
        updated["raw_fights"],
        updated["raw_fight_stats"],
        updated["raw_fighters"],
    )
    ingest_manifest = {
        "source": "Safe incremental UFCStats men updater",
        "generated_at": stamp,
        "events_inspected": events_inspected,
        "mens_fights_added": unique_fight_count(new_fights),
        "fight_stats_rows_added": int(len(new_stats)),
        "fighter_profiles_added": int(len(new_fighters)),
        "manifest_dir": str(manifest_dir),
    }
    write_json(ROOT / RAW_DIR / "ingest_manifest.json", ingest_manifest)
    apply_status = "applied"

    try:
        if args.rebuild_derived:
            rebuild_derived_status = run_derived_rebuild(manifest_dir, backup_dir)
    except Exception as exc:
        rebuild_derived_status = f"failed: {one_line(exc)}"
        after_failure = read_project_datasets()
        if args.audit:
            write_post_update_audit(
                manifest_dir,
                stamp,
                "apply_rebuild_failed",
                apply_status,
                today,
                before,
                after_failure,
                new_fights,
                new_stats,
                new_fighters,
                safety_audit,
                scrape_counts,
                rebuild_derived_status,
            )
        summary = build_summary(
            manifest_dir,
            before,
            after_failure,
            new_stats,
            new_fights,
            unsafe_rows_blocked,
            scrape_counts,
            apply_status,
            rebuild_derived_status,
        )
        print_and_write_summary(manifest_dir, summary)
        print(f"ERROR: {rebuild_derived_status}", file=sys.stderr)
        return 1

    after = read_project_datasets()
    if args.audit:
        write_post_update_audit(
            manifest_dir,
            stamp,
            "apply",
            apply_status,
            today,
            before,
            after,
            new_fights,
            new_stats,
            new_fighters,
            safety_audit,
            scrape_counts,
            rebuild_derived_status,
        )
    summary = build_summary(
        manifest_dir,
        before,
        after,
        new_stats,
        new_fights,
        unsafe_rows_blocked,
        scrape_counts,
        apply_status,
        rebuild_derived_status,
    )
    print_and_write_summary(manifest_dir, summary)
    print(f"Backup folder: {backup_dir}")
    print("Update complete.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
