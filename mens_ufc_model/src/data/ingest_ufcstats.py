from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.ufcstats_scraper import BASE_URL, UFCStatsScraper
from src.common.utils import (
    clean_text,
    ensure_http,
    fight_elapsed_seconds,
    id_from_url,
    is_womens_bout,
    normalize_division,
    parse_int,
    parse_landed_attempted,
    parse_percent,
    parse_time_to_seconds,
)


EVENT_COLUMNS = ["event_id", "event_name", "event_date", "location", "source_url"]
FIGHT_COLUMNS = [
    "fight_id",
    "event_id",
    "event_date",
    "weight_class",
    "is_mens_bout",
    "is_catchweight_or_openweight",
    "fighter_red_id",
    "fighter_blue_id",
    "winner_id",
    "loser_id",
    "result",
    "method",
    "round",
    "time",
    "time_format",
    "referee",
    "source_url",
]
FIGHT_STATS_COLUMNS = [
    "fight_id",
    "event_id",
    "event_date",
    "fighter_id",
    "fighter_name",
    "opponent_id",
    "opponent_name",
    "result",
    "won",
    "knockdowns",
    "significant_strikes_landed",
    "significant_strikes_attempted",
    "total_strikes_landed",
    "total_strikes_attempted",
    "takedowns_landed",
    "takedowns_attempted",
    "submission_attempts",
    "reversals",
    "control_time",
    "control_time_seconds",
    "head_significant_strikes_landed",
    "head_significant_strikes_attempted",
    "body_significant_strikes_landed",
    "body_significant_strikes_attempted",
    "leg_significant_strikes_landed",
    "leg_significant_strikes_attempted",
    "distance_significant_strikes_landed",
    "distance_significant_strikes_attempted",
    "clinch_significant_strikes_landed",
    "clinch_significant_strikes_attempted",
    "ground_significant_strikes_landed",
    "ground_significant_strikes_attempted",
    "elapsed_seconds",
    "source_url",
]
FIGHTER_COLUMNS = [
    "fighter_id",
    "fighter_name",
    "height",
    "height_cm",
    "weight",
    "weight_lbs",
    "reach",
    "reach_cm",
    "stance",
    "date_of_birth",
    "source_url",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest normalized men's UFC tables from UFCStats."
    )
    parser.add_argument("--out", default="data/raw/ufcstats_men", help="Output folder.")
    parser.add_argument("--cache", default="cache", help="HTML cache folder.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between fresh requests.")
    parser.add_argument("--max-events", type=int, default=None, help="Limit completed events scanned.")
    parser.add_argument("--max-fights", type=int, default=None, help="Limit men's fights fetched.")
    parser.add_argument("--start-date", default=None, help="Earliest event date, YYYY-MM-DD.")
    parser.add_argument("--end-date", default=None, help="Latest event date, YYYY-MM-DD.")
    parser.add_argument("--refresh-cache", action="store_true", help="Ignore cached HTML.")
    parser.add_argument(
        "--skip-profiles",
        action="store_true",
        help="Skip fighter profile pages; useful for fast parser smoke tests.",
    )
    return parser.parse_args()


def is_mens_weight_class(weight_class: Any) -> bool:
    text = clean_text(weight_class).lower()
    return bool(text) and "women" not in text


def is_catchweight_or_openweight(weight_class: Any) -> bool:
    text = clean_text(weight_class).lower()
    return "catch" in text or "openweight" in text or "open weight" in text


def iso_date(value: Any) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(ts) else ts.strftime("%Y-%m-%d")


def save_csv(df: pd.DataFrame, path: Path, columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns:
        for col in columns:
            if col not in df.columns:
                df[col] = pd.NA
        df = df[columns]
    df.to_csv(path, index=False, encoding="utf-8-sig")


def normalize_result_marker(marker: Any) -> str:
    marker_text = clean_text(marker)
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


def result_from_marker(marker: Any, method: Any) -> str | None:
    marker_text = normalize_result_marker(marker)
    method_text = clean_text(method).lower()
    if marker_text == "W":
        return "win"
    if marker_text == "L":
        return "loss"
    if marker_text == "D":
        return "draw"
    if marker_text == "NC":
        return "no_contest"
    if "draw" in method_text:
        return "draw"
    if "no contest" in method_text or "overturned" in method_text:
        return "no_contest"
    return None


def parse_result_box(soup: Any, fight_meta: dict[str, Any]) -> dict[str, Any]:
    result = {
        "method": fight_meta.get("method"),
        "round": fight_meta.get("round"),
        "time": fight_meta.get("time"),
        "time_format": None,
        "referee": None,
        "details": None,
    }
    text_items = [
        clean_text(item.get_text(" "))
        for item in soup.select("i[class*=b-fight-details__text-item]")
    ]
    detail_lines: list[str] = []
    collecting_details = False
    for text in text_items:
        lower = text.lower()
        if lower.startswith("method:"):
            result["method"] = clean_text(text.split(":", 1)[1])
            collecting_details = False
        elif lower.startswith("round:"):
            result["round"] = parse_int(text.split(":", 1)[1])
            collecting_details = False
        elif lower.startswith("time:") and not lower.startswith("time format:"):
            result["time"] = clean_text(text.split(":", 1)[1])
            collecting_details = False
        elif lower.startswith("time format:"):
            result["time_format"] = clean_text(text.split(":", 1)[1])
            collecting_details = False
        elif lower.startswith("referee:"):
            result["referee"] = clean_text(text.split(":", 1)[1])
            collecting_details = False
        elif lower.startswith("details:"):
            collecting_details = True
            after = clean_text(text.split(":", 1)[1])
            if after:
                detail_lines.append(after)
        elif collecting_details and text and ":" not in text:
            detail_lines.append(text)
    if detail_lines:
        result["details"] = " | ".join(detail_lines)
    return result


def first_direct_table_with_headers(soup: Any, required_headers: set[str]) -> Any | None:
    for table in soup.select("table.b-fight-details__table"):
        headers = direct_headers(table)
        normalized = {h.lower().replace(" ", "") for h in headers}
        if required_headers.issubset(normalized):
            return table
    return None


def direct_headers(table: Any) -> list[str]:
    thead = table.find("thead", recursive=False)
    tr = thead.find("tr", recursive=False) if thead else None
    if not tr:
        return []
    return [clean_text(th.get_text(" ")) for th in tr.find_all("th", recursive=False)]


def direct_row_cells(table: Any) -> list[Any]:
    tbody = table.find("tbody", recursive=False)
    row = tbody.find("tr", recursive=False) if tbody else None
    if not row:
        return []
    return row.find_all("td", recursive=False)


def cell_pair(cell: Any) -> list[str]:
    values = [clean_text(p.get_text(" ")) for p in cell.find_all("p", recursive=False)]
    if not values:
        values = [clean_text(cell.get_text(" "))]
    values = values[:2]
    while len(values) < 2:
        values.append("")
    return values


def assign_int(rows: list[dict[str, Any]], values: list[str], column: str) -> None:
    for idx in range(min(2, len(values))):
        rows[idx][column] = parse_int(values[idx])


def assign_time(rows: list[dict[str, Any]], values: list[str], raw_col: str, seconds_col: str) -> None:
    for idx in range(min(2, len(values))):
        rows[idx][raw_col] = values[idx]
        rows[idx][seconds_col] = parse_time_to_seconds(values[idx])


def assign_landed_attempted(
    rows: list[dict[str, Any]],
    values: list[str],
    landed_col: str,
    attempted_col: str,
) -> None:
    for idx in range(min(2, len(values))):
        landed, attempted = parse_landed_attempted(values[idx])
        rows[idx][landed_col] = landed
        rows[idx][attempted_col] = attempted


def parse_detail_stat_rows(soup: Any) -> list[dict[str, Any]]:
    rows = [{}, {}]

    totals = first_direct_table_with_headers(
        soup, {"fighter", "kd", "sig.str.", "totalstr.", "sub.att", "rev.", "ctrl"}
    )
    if totals is not None:
        cells = direct_row_cells(totals)
        if len(cells) >= 10:
            names = cell_pair(cells[0])
            for idx, name in enumerate(names[:2]):
                rows[idx]["fighter_name"] = name
            assign_int(rows, cell_pair(cells[1]), "knockdowns")
            assign_landed_attempted(
                rows,
                cell_pair(cells[2]),
                "significant_strikes_landed",
                "significant_strikes_attempted",
            )
            assign_landed_attempted(
                rows, cell_pair(cells[4]), "total_strikes_landed", "total_strikes_attempted"
            )
            # UFCStats currently labels both TD columns as "Td %" in the header.
            # Position 5 is landed/attempted; position 6 is percentage.
            assign_landed_attempted(
                rows, cell_pair(cells[5]), "takedowns_landed", "takedowns_attempted"
            )
            for idx, value in enumerate(cell_pair(cells[6])[:2]):
                rows[idx]["takedown_pct"] = parse_percent(value)
            assign_int(rows, cell_pair(cells[7]), "submission_attempts")
            assign_int(rows, cell_pair(cells[8]), "reversals")
            assign_time(rows, cell_pair(cells[9]), "control_time", "control_time_seconds")

    sig = first_direct_table_with_headers(
        soup, {"fighter", "sig.str", "head", "body", "leg", "distance", "clinch", "ground"}
    )
    if sig is not None:
        cells = direct_row_cells(sig)
        if len(cells) >= 9:
            names = cell_pair(cells[0])
            for idx, name in enumerate(names[:2]):
                rows[idx].setdefault("fighter_name", name)
            assign_landed_attempted(
                rows,
                cell_pair(cells[1]),
                "significant_strikes_landed",
                "significant_strikes_attempted",
            )
            assign_landed_attempted(
                rows,
                cell_pair(cells[3]),
                "head_significant_strikes_landed",
                "head_significant_strikes_attempted",
            )
            assign_landed_attempted(
                rows,
                cell_pair(cells[4]),
                "body_significant_strikes_landed",
                "body_significant_strikes_attempted",
            )
            assign_landed_attempted(
                rows,
                cell_pair(cells[5]),
                "leg_significant_strikes_landed",
                "leg_significant_strikes_attempted",
            )
            assign_landed_attempted(
                rows,
                cell_pair(cells[6]),
                "distance_significant_strikes_landed",
                "distance_significant_strikes_attempted",
            )
            assign_landed_attempted(
                rows,
                cell_pair(cells[7]),
                "clinch_significant_strikes_landed",
                "clinch_significant_strikes_attempted",
            )
            assign_landed_attempted(
                rows,
                cell_pair(cells[8]),
                "ground_significant_strikes_landed",
                "ground_significant_strikes_attempted",
            )

    return rows


def fight_result_label(method: Any, winner_id: Any) -> str:
    method_text = clean_text(method).lower()
    if "draw" in method_text:
        return "draw"
    if "no contest" in method_text or "overturned" in method_text:
        return "no_contest"
    if winner_id:
        return "win_loss"
    return "unknown"


def fight_result_from_fighter_rows(method: Any, winner_id: Any, fighter_rows: list[dict[str, Any]]) -> str:
    row_results = {clean_text(row.get("result")).lower() for row in fighter_rows}
    if "draw" in row_results:
        return "draw"
    if "no_contest" in row_results:
        return "no_contest"
    return fight_result_label(method, winner_id)


def parse_fight_detail(
    scraper: UFCStatsScraper,
    event_row: pd.Series,
    fight_meta: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
    fight_url = ensure_http(fight_meta["fight_url"])
    soup = scraper.soup(fight_url)
    fight_id = id_from_url(fight_url)
    result_box = parse_result_box(soup, fight_meta)
    method = result_box.get("method")
    round_value = result_box.get("round")
    time_value = result_box.get("time")
    elapsed_seconds = fight_elapsed_seconds(round_value, time_value)

    title = soup.select_one("i.b-fight-details__fight-title")
    weight_class = normalize_division(
        fight_meta.get("bout_type") or (title.get_text(" ") if title else "")
    )

    name_links = soup.select("h3.b-fight-details__person-name a")
    names = [clean_text(a.get_text(" ")) for a in name_links]
    urls = [ensure_http(urljoin(BASE_URL, a.get("href"))) for a in name_links]
    if len(names) < 2:
        names = [fight_meta.get("fighter_1"), fight_meta.get("fighter_2")]
        urls = [fight_meta.get("fighter_1_profile_url"), fight_meta.get("fighter_2_profile_url")]

    statuses = [
        clean_text(item.get_text(" "))
        for item in soup.select("i.b-fight-details__person-status")
    ]
    detail_stats = parse_detail_stat_rows(soup)

    fighter_rows: list[dict[str, Any]] = []
    for idx in range(2):
        profile_url = ensure_http(urls[idx]) if idx < len(urls) and urls[idx] else ""
        fighter_id = id_from_url(profile_url) if profile_url else ""
        name = names[idx] if idx < len(names) else detail_stats[idx].get("fighter_name")
        marker = statuses[idx] if idx < len(statuses) else None
        result = result_from_marker(marker, method)
        if result is None:
            result = result_from_marker(fight_meta.get(f"fighter_{idx + 1}_result_marker"), method)
        row = {
            "fight_id": fight_id,
            "event_id": event_row.get("event_id"),
            "event_date": iso_date(event_row.get("event_date")),
            "fighter_id": fighter_id,
            "fighter_name": name,
            "result": result,
            "won": 1 if result == "win" else 0 if result == "loss" else pd.NA,
            "elapsed_seconds": elapsed_seconds,
            "source_url": fight_url,
        }
        row.update(detail_stats[idx])
        fighter_rows.append(row)

    if len(fighter_rows) == 2:
        fighter_rows[0]["opponent_id"] = fighter_rows[1].get("fighter_id")
        fighter_rows[0]["opponent_name"] = fighter_rows[1].get("fighter_name")
        fighter_rows[1]["opponent_id"] = fighter_rows[0].get("fighter_id")
        fighter_rows[1]["opponent_name"] = fighter_rows[0].get("fighter_name")

    winner_id = ""
    loser_id = ""
    for row in fighter_rows:
        if row.get("result") == "win":
            winner_id = row.get("fighter_id") or ""
        elif row.get("result") == "loss":
            loser_id = row.get("fighter_id") or ""

    fight_row = {
        "fight_id": fight_id,
        "event_id": event_row.get("event_id"),
        "event_date": iso_date(event_row.get("event_date")),
        "weight_class": weight_class,
        "is_mens_bout": is_mens_weight_class(weight_class),
        "is_catchweight_or_openweight": is_catchweight_or_openweight(weight_class),
        "fighter_red_id": fighter_rows[0].get("fighter_id") if len(fighter_rows) > 0 else "",
        "fighter_blue_id": fighter_rows[1].get("fighter_id") if len(fighter_rows) > 1 else "",
        "winner_id": winner_id,
        "loser_id": loser_id,
        "result": fight_result_from_fighter_rows(method, winner_id, fighter_rows),
        "method": method,
        "round": round_value,
        "time": time_value,
        "time_format": result_box.get("time_format"),
        "referee": result_box.get("referee"),
        "source_url": fight_url,
    }
    profile_urls = {
        row.get("fighter_id"): urls[idx]
        for idx, row in enumerate(fighter_rows)
        if row.get("fighter_id") and idx < len(urls) and urls[idx]
    }
    return fight_row, fighter_rows, profile_urls


def normalize_profile(profile: dict[str, Any], fallback_url: str = "") -> dict[str, Any]:
    source_url = ensure_http(profile.get("profile_url") or fallback_url)
    return {
        "fighter_id": profile.get("fighter_id") or (id_from_url(source_url) if source_url else ""),
        "fighter_name": profile.get("fighter"),
        "height": profile.get("height_raw"),
        "height_cm": profile.get("height_cm"),
        "weight": profile.get("weight_raw"),
        "weight_lbs": profile.get("weight_lbs"),
        "reach": profile.get("reach_raw"),
        "reach_cm": profile.get("reach_cm"),
        "stance": profile.get("stance"),
        "date_of_birth": iso_date(profile.get("dob")),
        "source_url": source_url,
    }


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    scraper = UFCStatsScraper(
        cache_dir=args.cache,
        sleep_seconds=args.sleep,
        refresh_cache=args.refresh_cache,
    )

    events = scraper.get_completed_events()
    events["event_date"] = pd.to_datetime(events["event_date"], errors="coerce")
    events = events.sort_values("event_date", ascending=False).reset_index(drop=True)
    if args.start_date:
        events = events[events["event_date"] >= pd.to_datetime(args.start_date, errors="coerce")]
    if args.end_date:
        events = events[events["event_date"] <= pd.to_datetime(args.end_date, errors="coerce")]
    if args.max_events is not None:
        events = events.head(args.max_events)

    events_out = events.rename(columns={"event_url": "source_url"}).copy()
    events_out["event_date"] = events_out["event_date"].map(iso_date)
    save_csv(events_out, out_dir / "events.csv", EVENT_COLUMNS)

    fights: list[dict[str, Any]] = []
    fight_stats: list[dict[str, Any]] = []
    profile_urls: dict[str, str] = {}
    issues: list[dict[str, Any]] = []

    fight_limit_reached = False
    for event_idx, event in events.iterrows():
        if fight_limit_reached:
            break
        print(
            f"[{event_idx + 1}/{len(events)}] {iso_date(event['event_date'])} - {event['event_name']}"
        )
        try:
            event_fights = scraper.get_event_fights(event["event_url"])
        except Exception as exc:
            issues.append(
                {
                    "stage": "event",
                    "event_id": event.get("event_id"),
                    "source_url": event.get("event_url"),
                    "error": str(exc),
                }
            )
            continue

        mens_fights = [
            fight
            for fight in event_fights
            if not is_womens_bout(fight.get("bout_type")) and is_mens_weight_class(fight.get("division"))
        ]
        for fight_meta in mens_fights:
            if args.max_fights is not None and len(fights) >= args.max_fights:
                fight_limit_reached = True
                break
            try:
                fight_row, stat_rows, urls = parse_fight_detail(scraper, event, fight_meta)
            except Exception as exc:
                issues.append(
                    {
                        "stage": "fight",
                        "event_id": event.get("event_id"),
                        "source_url": fight_meta.get("fight_url"),
                        "error": str(exc),
                    }
                )
                continue
            if not fight_row.get("is_mens_bout"):
                continue
            fights.append(fight_row)
            fight_stats.extend(stat_rows)
            profile_urls.update({k: v for k, v in urls.items() if k and v})

    fighters: list[dict[str, Any]] = []
    if not args.skip_profiles:
        print(f"Downloading fighter profiles: {len(profile_urls):,}")
        for idx, (fighter_id, profile_url) in enumerate(sorted(profile_urls.items()), start=1):
            try:
                print(f"  [{idx}/{len(profile_urls)}] {fighter_id}")
                profile = scraper.get_fighter_profile(profile_url)
                fighters.append(normalize_profile(profile, profile_url))
            except Exception as exc:
                issues.append(
                    {
                        "stage": "profile",
                        "fighter_id": fighter_id,
                        "source_url": profile_url,
                        "error": str(exc),
                    }
                )
                fighters.append(
                    {
                        "fighter_id": fighter_id,
                        "fighter_name": "",
                        "source_url": ensure_http(profile_url),
                    }
                )
    else:
        seen: dict[str, str] = {}
        for row in fight_stats:
            if row.get("fighter_id"):
                seen[row["fighter_id"]] = row.get("fighter_name") or ""
        fighters = [
            {
                "fighter_id": fighter_id,
                "fighter_name": fighter_name,
                "source_url": profile_urls.get(fighter_id, ""),
            }
            for fighter_id, fighter_name in sorted(seen.items())
        ]

    fights_df = pd.DataFrame(fights)
    fight_stats_df = pd.DataFrame(fight_stats)
    fighters_df = pd.DataFrame(fighters).drop_duplicates("fighter_id") if fighters else pd.DataFrame()

    save_csv(fights_df, out_dir / "fights.csv", FIGHT_COLUMNS)
    save_csv(fight_stats_df, out_dir / "fight_stats.csv", FIGHT_STATS_COLUMNS)
    save_csv(fighters_df, out_dir / "fighters.csv", FIGHTER_COLUMNS)

    manifest = {
        "source": "UFCStats completed events and fight/fighter detail pages",
        "events_scanned": int(len(events)),
        "mens_fights_written": int(len(fights_df)),
        "fight_stats_rows_written": int(len(fight_stats_df)),
        "fighters_written": int(len(fighters_df)),
        "issues": issues,
    }
    (out_dir / "ingest_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
