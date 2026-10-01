#!/usr/bin/env python3
"""
Incrementally update the local UFC women's MMA dataset from UFCStats.

What it does:
1. Reads the current cleaned fighter-fight stats CSV.
2. Scrapes only completed UFCStats events newer than the current max event_date
   unless --from-date is provided.
3. Scrapes women's bouts from those new event pages/fight-detail pages.
4. Appends new fighter-fight rows to the stats CSV.
5. Optionally updates fighter profiles for newly seen fighters.
6. Appends new pre-fight model-training rows to the sig-fixed advanced dataset
   using the same live feature builder used by predict_matchup_advanced.py.

Safe behavior:
- Nothing is written unless --apply is passed.
- When --apply is used, existing files are backed up first.

Requirements:
    pip install requests beautifulsoup4 pandas numpy scikit-learn
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup


UFCSTATS_COMPLETED_EVENTS_URL = "http://ufcstats.com/statistics/events/completed?page=all"
WOMENS_DIVISIONS = {
    "Women's Strawweight",
    "Women's Flyweight",
    "Women's Bantamweight",
    "Women's Featherweight",
}
BAYESIAN_OUT_DIR = Path("output_bayesian_prefight_smoothing_sig_fixed_v1")
BAYESIAN_OUTPUT_FILE = BAYESIAN_OUT_DIR / "ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv"
UNSAFE_SKIP_STATUSES = {
    "skipped_future_event",
    "skipped_unresolved_result",
    "skipped_no_winner_loser",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Incrementally scrape new UFCStats women's fights and append them to the local datasets."
    )

    p.add_argument("--stats", default="output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv")
    p.add_argument(
        "--advanced-data",
        default="output_advanced_features_sig_fixed/ufc_womens_model_training_rows_advanced_sig_fixed.csv",
        help="Current sig-fixed advanced training dataset to append new training rows to.",
    )
    p.add_argument("--predictor", default="predict_matchup_advanced.py")
    p.add_argument("--profiles", default=None, help="Optional fighter profiles CSV to update/use.")
    p.add_argument("--events-url", default=UFCSTATS_COMPLETED_EVENTS_URL)
    p.add_argument("--from-date", default=None, help="Scrape events on/after this date instead of using max existing event_date + 1 day.")
    p.add_argument("--max-events", type=int, default=None, help="Limit number of new events to process.")
    p.add_argument("--max-fights", type=int, default=None, help="Limit number of new women's fights to process.")
    p.add_argument("--sleep", type=float, default=0.6)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--apply", action="store_true", help="Actually write updated CSVs. Without this, dry-run only.")
    p.add_argument(
        "--allow-future-events",
        action="store_true",
        help="Allow event dates after today to be inspected and accepted if they otherwise have completed W/L results.",
    )
    p.add_argument(
        "--allow-unsafe-apply",
        action="store_true",
        help="Allow --apply even if the new-row safety audit finds unsafe rows. Intended only for manual repair work.",
    )
    p.add_argument(
        "--rebuild-bayesian",
        action="store_true",
        help="After a successful --apply update, rebuild the prefight Bayesian-smoothed sig-fixed dataset.",
    )
    p.add_argument(
        "--audit",
        action="store_true",
        help="Write post-update audit CSV/JSON into the manifest folder and print the audit summary.",
    )
    p.add_argument("--no-profile-update", action="store_true")
    p.add_argument("--no-advanced-update", action="store_true")
    p.add_argument("--backup-dir", default=None)
    p.add_argument("--manifest-dir", default="_update_manifests")
    p.add_argument(
        "--user-agent",
        default=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
    )

    return p.parse_args()


# --------------------------------------------------------------------------------------
# General helpers
# --------------------------------------------------------------------------------------


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def clean_text(x: Any) -> str:
    if x is None:
        return ""
    return re.sub(r"\s+", " ", str(x).replace("\xa0", " ")).strip()


def safe_float(x: Any, default: float = np.nan) -> float:
    try:
        if pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def safe_int(x: Any, default: int = 0) -> int:
    try:
        if pd.isna(x):
            return default
        return int(float(x))
    except Exception:
        return default


def normalize_name(name: Any) -> str:
    if pd.isna(name):
        return ""
    name = str(name).strip().lower()
    replacements = {
        "é": "e", "è": "e", "ê": "e", "ë": "e",
        "á": "a", "à": "a", "ã": "a", "â": "a", "ä": "a",
        "í": "i", "ì": "i", "î": "i", "ï": "i",
        "ó": "o", "ò": "o", "ô": "o", "õ": "o", "ö": "o",
        "ú": "u", "ù": "u", "û": "u", "ü": "u",
        "ç": "c", "ñ": "n", "ł": "l",
        "’": "'", "‘": "'", "`": "'",
        ".": "", ",": "",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)
    name = re.sub(r"[^a-z0-9\s'\-]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    aliases = {
        "joanne calderwood": "joanne wood",
        "tecia torres": "tecia pennington",
    }
    return aliases.get(name, name)


def extract_id_from_url(url: str) -> str:
    return str(url).rstrip("/").split("/")[-1]


def is_ufcstats_browser_check(html: str) -> bool:
    text = html or ""
    lowered = text.lower()
    return (
        "checking your browser" in lowered
        and "/__c" in text
        and "nonce" in lowered
        and "sha256" in lowered
    )


def solve_browser_check_answer(html: str) -> Tuple[str, int]:
    nonce_match = re.search(r'var\s+nonce\s*=\s*"([^"]+)"', html)
    target_match = re.search(r"target\s*=\s*new Array\((\d+)\+1\)", html)
    if not nonce_match or not target_match:
        raise RuntimeError("UFCStats browser check shape was not recognized.")

    nonce = nonce_match.group(1)
    target = "0" * int(target_match.group(1))
    max_attempts = 10_000_000
    for n in range(max_attempts):
        digest = hashlib.sha256(f"{nonce}:{n}".encode("utf-8")).hexdigest()
        if digest.startswith(target):
            return nonce, n
    raise RuntimeError("UFCStats browser check proof-of-work exceeded the local attempt limit.")


def clear_ufcstats_browser_check(session: requests.Session, url: str, html: str, timeout: float) -> None:
    nonce, answer = solve_browser_check_answer(html)
    resp = session.post(
        urljoin(url, "/__c"),
        data={"nonce": nonce, "n": str(answer)},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=timeout,
    )
    if resp.status_code < 200 or resp.status_code >= 300:
        raise RuntimeError(f"UFCStats browser check POST returned HTTP {resp.status_code}.")


def make_session(user_agent: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return s


def fetch_soup(session: requests.Session, url: str, timeout: float, sleep: float, retries: int = 3) -> BeautifulSoup:
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200:
                if is_ufcstats_browser_check(resp.text):
                    clear_ufcstats_browser_check(session, url, resp.text, timeout=timeout)
                    time.sleep(sleep)
                    resp = session.get(url, timeout=timeout)
                    if resp.status_code != 200:
                        last_exc = RuntimeError(f"HTTP {resp.status_code} for {url} after browser check")
                        continue
                    if is_ufcstats_browser_check(resp.text):
                        last_exc = RuntimeError("UFCStats browser check did not clear after proof-of-work response.")
                        continue
                time.sleep(sleep)
                return BeautifulSoup(resp.text, "html.parser")
            last_exc = RuntimeError(f"HTTP {resp.status_code} for {url}")
        except Exception as exc:
            last_exc = exc
        time.sleep(max(sleep, 0.5) * attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_exc}")


class SkippedFight(Exception):
    def __init__(self, status: str, reason: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.details = details or {}


def today_timestamp() -> pd.Timestamp:
    return pd.Timestamp(datetime.now().date())


def marker_value(marker: Any) -> str:
    return clean_text(marker).upper()


def is_blank_marker(marker: Any) -> bool:
    marker = marker_value(marker)
    return marker in {"", "--", "---", "NAN", "NONE", "NULL"}


def validate_completed_people(
    people: List[Dict[str, str]],
    event: Dict[str, Any],
    today: pd.Timestamp,
    allow_future_events: bool,
) -> None:
    event_date = pd.to_datetime(event.get("event_date"), errors="coerce")
    event_date = pd.Timestamp(event_date).normalize() if pd.notna(event_date) else pd.NaT
    markers = [marker_value(p.get("result_marker", "")) for p in people[:2]]
    details = {
        "event_name": event.get("event_name", ""),
        "event_date": event_date.date().isoformat() if pd.notna(event_date) else "",
        "fighter_1": people[0].get("fighter", "") if len(people) > 0 else "",
        "fighter_2": people[1].get("fighter", "") if len(people) > 1 else "",
        "result_marker_1": markers[0] if len(markers) > 0 else "",
        "result_marker_2": markers[1] if len(markers) > 1 else "",
    }

    if pd.notna(event_date) and event_date > today and not allow_future_events:
        raise SkippedFight("skipped_future_event", "event date is after today", details)

    if len(people) != 2 or not people[0].get("fighter") or not people[1].get("fighter"):
        raise SkippedFight("skipped_unresolved_result", "could not parse both fighters", details)

    if any(is_blank_marker(m) for m in markers):
        raise SkippedFight("skipped_unresolved_result", "blank result marker", details)

    if any(m not in {"W", "L", "D", "NC", "N/C"} for m in markers):
        raise SkippedFight("skipped_unresolved_result", f"unsupported result markers: {markers}", details)

    if markers.count("W") != 1 or markers.count("L") != 1:
        raise SkippedFight("skipped_no_winner_loser", f"no single W/L result pair: {markers}", details)


# --------------------------------------------------------------------------------------
# UFCStats parsing helpers
# --------------------------------------------------------------------------------------


def select_completed_events(events, cutoff, today, max_events=None):
    """Exclude future listings before imposing the bounded inspection limit."""
    selected = [event for event in events if cutoff <= pd.Timestamp(event["event_date"]).normalize() <= today]
    return selected[:max_events] if max_events is not None else selected


def parse_event_list(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    events = []

    date_re = re.compile(
        r"\b("
        r"January|February|March|April|May|June|July|August|September|October|November|December"
        r")\s+\d{1,2},\s+\d{4}\b",
        flags=re.I,
    )

    for row in soup.select("tr"):
        link = row.select_one('a[href*="/event-details/"]')
        if not link:
            continue

        event_url = link.get("href")
        event_name = clean_text(link.get_text(" "))

        row_text = clean_text(row.get_text(" "))
        cells = [clean_text(td.get_text(" ")) for td in row.select("td")]

        event_date = None
        location = ""

        # Original behavior: try to parse date from individual cells.
        for cell in cells:
            dt = pd.to_datetime(cell, errors="coerce")
            if pd.notna(dt):
                event_date = pd.Timestamp(dt).normalize()
                break

        # Robust fallback: UFCStats may expose row text like:
        # "UFC Fight Night: Song vs. Figueiredo May 30, 2026 Macau, China"
        if event_date is None:
            m = date_re.search(row_text)
            if m:
                dt = pd.to_datetime(m.group(0), errors="coerce")
                if pd.notna(dt):
                    event_date = pd.Timestamp(dt).normalize()

        # Location fallback.
        if cells:
            location = cells[-1]

        if not location and event_date is not None:
            cleaned = row_text
            if event_name:
                cleaned = cleaned.replace(event_name, "", 1).strip()
            m = date_re.search(cleaned)
            if m:
                cleaned = cleaned.replace(m.group(0), "", 1).strip()
            location = clean_text(cleaned)

        if event_url and event_name and event_date is not None:
            events.append(
                {
                    "event_name": event_name,
                    "event_date": event_date,
                    "event_url": event_url,
                    "location": location,
                }
            )

    # Deduplicate and sort oldest first for append logic.
    seen = set()
    unique = []
    for e in events:
        if e["event_url"] in seen:
            continue
        seen.add(e["event_url"])
        unique.append(e)

    return sorted(unique, key=lambda x: x["event_date"])

def parse_fight_links_from_event(soup: BeautifulSoup) -> List[str]:
    links = []
    # Event page rows sometimes expose the fight URL through data-link, and also through hrefs.
    for row in soup.select("tr"):
        data_link = row.get("data-link")
        if data_link and "/fight-details/" in data_link:
            links.append(data_link)
        for a in row.select('a[href*="/fight-details/"]'):
            links.append(a.get("href"))
    # Preserve order but dedupe.
    out = []
    seen = set()
    for link in links:
        if link and link not in seen:
            seen.add(link)
            out.append(link)
    return out


def parse_bout_type_and_division(soup: BeautifulSoup) -> Tuple[str, str]:
    title_el = soup.select_one(".b-fight-details__fight-title")
    title = clean_text(title_el.get_text(" ")) if title_el else ""
    bout_type = title.replace(" Bout", "").strip() if title else ""

    division = ""
    for div in WOMENS_DIVISIONS:
        if div.lower() in title.lower():
            division = div
            break
    if not division and "women" in title.lower():
        # Fall back to stripped title for unexpected future division naming.
        division = bout_type
    return bout_type, division


def parse_people(soup: BeautifulSoup) -> List[Dict[str, str]]:
    people = []
    blocks = soup.select(".b-fight-details__person")
    for block in blocks[:2]:
        name_el = block.select_one(".b-fight-details__person-name")
        status_el = block.select_one(".b-fight-details__person-status")
        link_el = block.select_one('a[href*="/fighter-details/"]')
        people.append(
            {
                "fighter": clean_text(name_el.get_text(" ")) if name_el else "",
                "result_marker": clean_text(status_el.get_text(" ")).upper() if status_el else "",
                "profile_url": link_el.get("href") if link_el else "",
            }
        )
    return people


def parse_fight_meta(soup: BeautifulSoup) -> Dict[str, Any]:
    meta = {
        "method": "",
        "round": np.nan,
        "time": "",
        "time_format": "",
        "referee": "",
        "details": "",
    }
    items = soup.select(".b-fight-details__text-item")
    for item in items:
        label_el = item.select_one(".b-fight-details__label")
        label = clean_text(label_el.get_text(" ")).replace(":", "").lower() if label_el else ""
        text = clean_text(item.get_text(" "))
        if label_el:
            value = clean_text(text.replace(clean_text(label_el.get_text(" ")), "", 1))
        else:
            value = text
        if label == "method":
            meta["method"] = value
        elif label == "round":
            meta["round"] = pd.to_numeric(value, errors="coerce")
        elif label == "time":
            meta["time"] = value
        elif label in {"time format", "timeformat"}:
            meta["time_format"] = value
        elif label == "referee":
            meta["referee"] = value
        elif label == "details":
            meta["details"] = value

    # Fallback: direct regex over full detail text.
    full_text = clean_text(" ".join(x.get_text(" ") for x in soup.select(".b-fight-details__text")))
    if not meta["method"]:
        m = re.search(r"Method:\s*(.*?)\s+Round:", full_text, re.I)
        if m:
            meta["method"] = clean_text(m.group(1))
    if pd.isna(meta["round"]):
        m = re.search(r"Round:\s*(\d+)", full_text, re.I)
        if m:
            meta["round"] = int(m.group(1))
    if not meta["time"]:
        m = re.search(r"Time:\s*([0-9]+:[0-9]{2})", full_text, re.I)
        if m:
            meta["time"] = m.group(1)
    if not meta["time_format"]:
        m = re.search(r"Time format:\s*(.*?)\s+Referee:", full_text, re.I)
        if m:
            meta["time_format"] = clean_text(m.group(1))
    if not meta["referee"]:
        m = re.search(r"Referee:\s*(.*?)\s+Details:", full_text, re.I)
        if m:
            meta["referee"] = clean_text(m.group(1))
    if not meta["details"]:
        m = re.search(r"Details:\s*(.*)$", full_text, re.I)
        if m:
            meta["details"] = clean_text(m.group(1))
    return meta


def time_to_elapsed_seconds(round_no: Any, time_str: str) -> float:
    r = safe_int(round_no, default=0)
    m = re.match(r"^(\d+):(\d{2})$", clean_text(time_str))
    if r <= 0 or not m:
        return np.nan
    return (r - 1) * 300 + int(m.group(1)) * 60 + int(m.group(2))


def parse_pair_text_from_cell(cell) -> List[str]:
    vals = [clean_text(p.get_text(" ")) for p in cell.select("p")]
    vals = [v for v in vals if v != ""]
    if len(vals) >= 2:
        return vals[:2]
    text = clean_text(cell.get_text(" "))
    # Try to split repeated paired values if paragraph tags were missing.
    if " of " in text:
        parts = re.findall(r"\d+\s+of\s+\d+", text, flags=re.I)
        if len(parts) >= 2:
            return parts[:2]
    nums = re.findall(r"\d+", text)
    if len(nums) >= 2:
        return nums[:2]
    return [text, ""]


def parse_of_stat(value: str) -> Tuple[float, float]:
    value = clean_text(value)
    m = re.match(r"^(\d+)\s+of\s+(\d+)$", value, flags=re.I)
    if m:
        return float(m.group(1)), float(m.group(2))
    # Sometimes just one number.
    nums = re.findall(r"\d+", value)
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    if len(nums) == 1:
        return float(nums[0]), np.nan
    return np.nan, np.nan


def parse_control_seconds(value: str) -> float:
    value = clean_text(value)
    if value in {"", "--", "---", "0"}:
        return 0.0
    m = re.match(r"^(\d+):(\d{2})$", value)
    if m:
        return float(int(m.group(1)) * 60 + int(m.group(2)))
    return pd.to_numeric(value, errors="coerce")


def normalize_header(h: str) -> str:
    h = clean_text(h).upper()
    h = h.replace(".", "")
    h = re.sub(r"\s+", " ", h)
    return h


def find_stat_table(soup: BeautifulSoup, required_headers: Iterable[str]) -> Optional[Any]:
    required = [normalize_header(x) for x in required_headers]
    for table in soup.select("table"):
        headers = [normalize_header(th.get_text(" ")) for th in table.select("thead th")]
        header_text = " | ".join(headers)
        if all(req in header_text for req in required):
            return table
    return None


def parse_table_total_pairs(table) -> Dict[str, List[str]]:
    if table is None:
        return {}
    headers = [normalize_header(th.get_text(" ")) for th in table.select("thead th")]
    rows = table.select("tbody tr")
    chosen = None
    for row in rows:
        cells = row.select("td")
        if not cells:
            continue
        first = clean_text(cells[0].get_text(" ")).upper()
        if "TOTAL" in first:
            chosen = cells
            break
    if chosen is None and rows:
        chosen = rows[0].select("td")
    if not chosen:
        return {}

    # Align headers and cells. UFCStats tables often include a ROUND column first.
    pairs = {}
    for i, cell in enumerate(chosen):
        header = headers[i] if i < len(headers) else f"COL_{i}"
        if header in {"ROUND", "FIGHTER"}:
            continue
        pairs[header] = parse_pair_text_from_cell(cell)
    return pairs


def get_pair(pairs: Dict[str, List[str]], *header_options: str) -> List[str]:
    normalized_options = [normalize_header(x) for x in header_options]
    for opt in normalized_options:
        if opt in pairs:
            return pairs[opt]
    for key, value in pairs.items():
        if any(opt in key or key in opt for opt in normalized_options):
            return value
    return ["", ""]


def result_from_marker(marker: str) -> Tuple[str, float]:
    marker = clean_text(marker).upper()
    if marker == "W":
        return "win", 1.0
    if marker == "L":
        return "loss", 0.0
    if marker == "D":
        return "draw", np.nan
    if marker in {"NC", "N/C"}:
        return "nc", np.nan
    return "", np.nan


def parse_fight_page(
    session: requests.Session,
    fight_url: str,
    event: Dict[str, Any],
    timeout: float,
    sleep: float,
    today: pd.Timestamp,
    allow_future_events: bool,
) -> List[Dict[str, Any]]:
    soup = fetch_soup(session, fight_url, timeout=timeout, sleep=sleep)
    fight_id = extract_id_from_url(fight_url)
    bout_type, division = parse_bout_type_and_division(soup)
    if not division.startswith("Women's"):
        return []

    people = parse_people(soup)
    if len(people) != 2 or not people[0]["fighter"] or not people[1]["fighter"]:
        raise RuntimeError(f"Could not parse fighters for {fight_url}")
    validate_completed_people(people, event, today=today, allow_future_events=allow_future_events)

    meta = parse_fight_meta(soup)
    elapsed_seconds = time_to_elapsed_seconds(meta["round"], meta["time"])

    total_table = find_stat_table(soup, ["KD", "SIG. STR.", "TOTAL STR.", "TD", "CTRL"])
    sig_table = find_stat_table(soup, ["SIG. STR.", "HEAD", "BODY", "LEG", "DISTANCE", "CLINCH", "GROUND"])
    total_pairs = parse_table_total_pairs(total_table)
    sig_pairs = parse_table_total_pairs(sig_table)

    kd = get_pair(total_pairs, "KD")
    sig_total = get_pair(total_pairs, "SIG. STR.")
    if not sig_total[0]:
        sig_total = get_pair(sig_pairs, "SIG. STR.")
    total_str = get_pair(total_pairs, "TOTAL STR.")
    td = get_pair(total_pairs, "TD")
    sub = get_pair(total_pairs, "SUB.ATT", "SUB ATT", "SUB")
    rev = get_pair(total_pairs, "REV.", "REV")
    ctrl = get_pair(total_pairs, "CTRL")

    head = get_pair(sig_pairs, "HEAD")
    body = get_pair(sig_pairs, "BODY")
    leg = get_pair(sig_pairs, "LEG")
    distance = get_pair(sig_pairs, "DISTANCE")
    clinch = get_pair(sig_pairs, "CLINCH")
    ground = get_pair(sig_pairs, "GROUND")

    # Build per-fighter raw stats first.
    raw = []
    for i in [0, 1]:
        result, won = result_from_marker(people[i]["result_marker"])
        sig_l, sig_a = parse_of_stat(sig_total[i])
        total_l, total_a = parse_of_stat(total_str[i])
        td_l, td_a = parse_of_stat(td[i])
        head_l, head_a = parse_of_stat(head[i])
        body_l, body_a = parse_of_stat(body[i])
        leg_l, leg_a = parse_of_stat(leg[i])
        distance_l, distance_a = parse_of_stat(distance[i])
        clinch_l, clinch_a = parse_of_stat(clinch[i])
        ground_l, ground_a = parse_of_stat(ground[i])

        raw.append(
            {
                "fight_id": fight_id,
                "fight_url": fight_url,
                "event_name": event["event_name"],
                "event_date": pd.Timestamp(event["event_date"]).date().isoformat(),
                "location": event.get("location", ""),
                "bout_type": bout_type,
                "division": division,
                "fighter": people[i]["fighter"],
                "opponent": people[1 - i]["fighter"],
                "profile_url": people[i].get("profile_url", ""),
                "result_marker": people[i]["result_marker"],
                "result": result,
                "won": won,
                "method": meta["method"],
                "round": safe_int(meta["round"], default=0),
                "time": meta["time"],
                "elapsed_seconds": elapsed_seconds,
                "time_format": meta["time_format"],
                "referee": meta["referee"],
                "details": meta["details"],
                "head_sig_landed": head_l,
                "head_sig_attempted": head_a,
                "body_sig_landed": body_l,
                "body_sig_attempted": body_a,
                "leg_sig_landed": leg_l,
                "leg_sig_attempted": leg_a,
                "distance_sig_landed": distance_l,
                "distance_sig_attempted": distance_a,
                "clinch_sig_landed": clinch_l,
                "clinch_sig_attempted": clinch_a,
                "ground_sig_landed": ground_l,
                "ground_sig_attempted": ground_a,
                "sig_str_landed_total": sig_l,
                "sig_str_attempted_total": sig_a,
                "total_str_landed": total_l,
                "total_str_attempted": total_a,
                "td_landed": td_l,
                "td_attempted": td_a,
                "sub_attempts": safe_int(sub[i], default=0),
                "reversals": safe_int(rev[i], default=0),
                "control_time_seconds": parse_control_seconds(ctrl[i]),
                "kd_landed": safe_int(kd[i], default=0),
            }
        )

    # Add opponent columns symmetrically.
    rows = []
    for i in [0, 1]:
        r = dict(raw[i])
        o = raw[1 - i]
        for base in [
            "head_sig_landed", "head_sig_attempted", "body_sig_landed", "body_sig_attempted",
            "leg_sig_landed", "leg_sig_attempted", "distance_sig_landed", "distance_sig_attempted",
            "clinch_sig_landed", "clinch_sig_attempted", "ground_sig_landed", "ground_sig_attempted",
            "sig_str_landed_total", "sig_str_attempted_total", "total_str_landed", "total_str_attempted",
            "td_landed", "td_attempted", "sub_attempts", "reversals", "control_time_seconds",
        ]:
            r[f"opponent_{base}"] = o.get(base, np.nan)
        r["kd_absorbed"] = o.get("kd_landed", 0)
        # Keep repaired columns present, but do not rely on them. For newly scraped rows these
        # detailed totals should be full-fight TOTAL-row sig breakdowns, not final-round-only values.
        r["sig_str_landed_repaired"] = np.nansum([r.get("head_sig_landed"), r.get("body_sig_landed"), r.get("leg_sig_landed")])
        r["sig_str_attempted_repaired"] = np.nansum([r.get("head_sig_attempted"), r.get("body_sig_attempted"), r.get("leg_sig_attempted")])
        r["opponent_sig_str_landed_repaired"] = np.nansum([r.get("opponent_head_sig_landed"), r.get("opponent_body_sig_landed"), r.get("opponent_leg_sig_landed")])
        r["opponent_sig_str_attempted_repaired"] = np.nansum([r.get("opponent_head_sig_attempted"), r.get("opponent_body_sig_attempted"), r.get("opponent_leg_sig_attempted")])
        r["minutes"] = safe_float(r.get("elapsed_seconds"), 0.0) / 60.0 if pd.notna(r.get("elapsed_seconds")) else np.nan
        rows.append(r)
    return rows


# --------------------------------------------------------------------------------------
# Fighter profile scrape/update
# --------------------------------------------------------------------------------------


def inches_height_to_cm(text: str) -> float:
    text = clean_text(text)
    if not text or text == "--":
        return np.nan
    m = re.match(r"^(\d+)'\s*(\d+)", text)
    if m:
        inches = int(m.group(1)) * 12 + int(m.group(2))
        return inches * 2.54
    return np.nan


def reach_to_cm(text: str) -> float:
    text = clean_text(text)
    if not text or text == "--":
        return np.nan
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if m:
        return float(m.group(1)) * 2.54
    return np.nan


def scrape_profile(session: requests.Session, url: str, fighter_name: str, timeout: float, sleep: float) -> Dict[str, Any]:
    if not url:
        return {"fighter": fighter_name}
    soup = fetch_soup(session, url, timeout=timeout, sleep=sleep)
    out = {"fighter": fighter_name, "profile_url": url}
    title = soup.select_one(".b-content__title-highlight")
    if title:
        out["fighter"] = clean_text(title.get_text(" ")) or fighter_name
    items = soup.select(".b-list__box-list-item")
    for item in items:
        label_el = item.select_one("i") or item.select_one("b")
        text = clean_text(item.get_text(" "))
        label = ""
        value = text
        # UFCStats labels often appear as bold text at the start.
        m = re.match(r"^(HEIGHT|WEIGHT|REACH|STANCE|DOB):\s*(.*)$", text, flags=re.I)
        if m:
            label = m.group(1).lower()
            value = m.group(2).strip()
        elif label_el:
            label = clean_text(label_el.get_text(" ")).replace(":", "").lower()
            value = clean_text(text.replace(clean_text(label_el.get_text(" ")), "", 1))
        if label == "height":
            out["height"] = value
            out["height_cm"] = inches_height_to_cm(value)
        elif label == "reach":
            out["reach"] = value
            out["reach_cm"] = reach_to_cm(value)
        elif label == "stance":
            out["stance"] = value if value and value != "--" else "Unknown"
        elif label == "dob":
            dt = pd.to_datetime(value, errors="coerce")
            out["dob"] = dt.date().isoformat() if pd.notna(dt) else ""
    return out


def find_profile_file(profiles_arg: Optional[str]) -> Optional[Path]:
    if profiles_arg:
        return Path(profiles_arg)
    candidates = [
        Path("output_td_repaired/ufc_womens_fighter_profiles.csv"),
        Path("output_quality_fixed/ufc_womens_fighter_profiles.csv"),
        Path("output_fixed/ufc_womens_fighter_profiles.csv"),
        Path("output/ufc_womens_fighter_profiles.csv"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


# --------------------------------------------------------------------------------------
# Advanced dataset append logic
# --------------------------------------------------------------------------------------


def import_predictor(path: str):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    spec = importlib.util.spec_from_file_location("predictor_module", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_elo_state(predictor, stats: pd.DataFrame, fight_date: pd.Timestamp):
    if hasattr(predictor, "build_elo_history_until"):
        return predictor.build_elo_history_until(stats, fight_date)
    if hasattr(predictor, "compute_elo_until"):
        overall_elo, division_elo = predictor.compute_elo_until(stats, fight_date)
        return stats[stats["event_date"] < fight_date].copy(), overall_elo, division_elo
    raise RuntimeError("Predictor has neither build_elo_history_until nor compute_elo_until")


def build_snapshot(predictor, fighter: str, division: str, fight_date: pd.Timestamp, hist_stats, profile_map, overall_elo, division_elo):
    return predictor.build_current_snapshot(
        fighter,
        division,
        fight_date,
        hist_stats,
        profile_map,
        overall_elo,
        division_elo,
    )


def add_side_columns(row: Dict[str, Any], side: str, snapshot: Dict[str, Any], train_cols: Iterable[str]) -> None:
    train_cols = set(train_cols)
    prefix = f"fighter_{side}_"
    for key, value in snapshot.items():
        col = prefix + key
        if col in train_cols:
            row[col] = value


def build_new_training_rows(predictor, advanced_df: pd.DataFrame, updated_stats: pd.DataFrame, profile_path: Optional[Path], new_stats_rows: pd.DataFrame) -> pd.DataFrame:
    if new_stats_rows.empty:
        return pd.DataFrame(columns=advanced_df.columns)

    updated_stats = predictor.clean_numeric_columns(updated_stats)
    advanced_df = advanced_df.copy()
    advanced_df["event_date"] = pd.to_datetime(advanced_df["event_date"], errors="coerce")

    # The predictor profile loader expects the training dataframe for fallback ages/profiles.
    profile_map = predictor.load_profiles(profile_path, advanced_df)

    train_cols = list(advanced_df.columns)
    new_rows = []

    for fight_id, g in new_stats_rows.groupby("fight_id"):
        if len(g) != 2:
            print(f"WARNING: fight_id {fight_id} has {len(g)} rows; skipping advanced append")
            continue
        g = g.sort_values("fighter").copy()
        r1 = g.iloc[0]
        r2 = g.iloc[1]
        fight_date = pd.to_datetime(r1["event_date"], errors="coerce").normalize()
        division = r1.get("division", "")

        hist_stats, overall_elo, division_elo = get_elo_state(predictor, updated_stats, fight_date)
        snap1 = build_snapshot(predictor, r1["fighter"], division, fight_date, hist_stats, profile_map, overall_elo, division_elo)
        snap2 = build_snapshot(predictor, r2["fighter"], division, fight_date, hist_stats, profile_map, overall_elo, division_elo)

        orientations = [(r1, r2, snap1, snap2), (r2, r1, snap2, snap1)]
        for fa, fb, sa, sb in orientations:
            pred = predictor.build_prediction_row(advanced_df, sa, sb, division).iloc[0].to_dict()
            row = {col: np.nan for col in train_cols}
            row.update(pred)
            row.update(
                {
                    "fight_id": fight_id,
                    "event_date": fight_date.date().isoformat(),
                    "event_name": fa.get("event_name"),
                    "division": division,
                    "fighter_a": fa.get("fighter"),
                    "fighter_b": fb.get("fighter"),
                    "fighter_a_result": fa.get("result"),
                    "fighter_b_result": fb.get("result"),
                    "fighter_a_won": fa.get("won"),
                    "method": fa.get("method"),
                    "round": fa.get("round"),
                    "time": fa.get("time"),
                }
            )
            add_side_columns(row, "a", sa, train_cols)
            add_side_columns(row, "b", sb, train_cols)
            new_rows.append(row)

    out = pd.DataFrame(new_rows)
    for col in train_cols:
        if col not in out.columns:
            out[col] = np.nan
    return out[train_cols]


# --------------------------------------------------------------------------------------
# Main update flow
# --------------------------------------------------------------------------------------


def backup_file(path: Path, backup_dir: Path) -> Optional[Path]:
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / path.name
    shutil.copy2(path, dest)
    return dest


def blankish_series(series: pd.Series) -> pd.Series:
    return series.isna() | series.astype(str).map(clean_text).str.lower().isin({"", "nan", "none", "null", "--", "---"})


def latest_date_string(df: Optional[pd.DataFrame]) -> str:
    if df is None or df.empty or "event_date" not in df.columns:
        return ""
    dates = pd.to_datetime(df["event_date"], errors="coerce")
    if dates.notna().sum() == 0:
        return ""
    return dates.max().date().isoformat()


def unique_fight_count(df: Optional[pd.DataFrame]) -> int:
    if df is None or df.empty or "fight_id" not in df.columns:
        return 0
    return int(df["fight_id"].dropna().astype(str).nunique())


def count_future_rows(df: Optional[pd.DataFrame], today: pd.Timestamp) -> int:
    if df is None or df.empty or "event_date" not in df.columns:
        return 0
    dates = pd.to_datetime(df["event_date"], errors="coerce")
    return int((dates > today).sum())


def count_may30_or_future_rows(df: Optional[pd.DataFrame], today: pd.Timestamp) -> int:
    if df is None or df.empty or "event_date" not in df.columns:
        return 0
    dates = pd.to_datetime(df["event_date"], errors="coerce")
    may30 = pd.Timestamp("2026-05-30")
    return int(((dates >= may30) | (dates > today)).sum())


def count_nan_won_rows(df: Optional[pd.DataFrame]) -> int:
    if df is None or df.empty:
        return 0
    won_cols = [c for c in ["won", "fighter_a_won"] if c in df.columns]
    if not won_cols:
        return 0
    mask = pd.Series(False, index=df.index)
    for col in won_cols:
        mask = mask | pd.to_numeric(df[col], errors="coerce").isna()
    return int(mask.sum())


def count_unresolved_result_rows(df: Optional[pd.DataFrame]) -> int:
    if df is None or df.empty:
        return 0
    if "result_marker" in df.columns:
        markers = df["result_marker"].astype(str).map(marker_value)
        marker_blank = markers.isin({"", "--", "---", "NAN", "NONE", "NULL"})
        result_blank = blankish_series(df["result"]) if "result" in df.columns else pd.Series(False, index=df.index)
        completed_non_wl = markers.isin({"D", "NC", "N/C"})
        return int(((marker_blank | result_blank) & ~completed_non_wl).sum())
    result_cols = [c for c in ["result", "fighter_a_result", "fighter_b_result"] if c in df.columns]
    if not result_cols:
        return 0
    mask = pd.Series(False, index=df.index)
    for col in result_cols:
        mask = mask | blankish_series(df[col])
    return int(mask.sum())


def count_overfull_fight_ids(df: Optional[pd.DataFrame]) -> int:
    if df is None or df.empty or "fight_id" not in df.columns:
        return 0
    counts = df["fight_id"].dropna().astype(str).value_counts()
    return int((counts > 2).sum())


def count_one_sided_fight_ids(df: Optional[pd.DataFrame]) -> int:
    if df is None or df.empty or "fight_id" not in df.columns:
        return 0
    counts = df["fight_id"].dropna().astype(str).value_counts()
    return int((counts != 2).sum())


def dataset_audit_metrics(prefix: str, df: Optional[pd.DataFrame], before: Optional[pd.DataFrame], today: pd.Timestamp) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        f"{prefix}_rows": int(len(df)) if df is not None else 0,
        f"{prefix}_unique_fights": unique_fight_count(df),
        f"{prefix}_latest_date": latest_date_string(df),
        f"{prefix}_future_rows_count": count_future_rows(df, today),
        f"{prefix}_unresolved_nan_result_rows_count": count_unresolved_result_rows(df),
        f"{prefix}_nan_won_rows_count": count_nan_won_rows(df),
        f"{prefix}_duplicate_fight_id_count": count_overfull_fight_ids(df),
        f"{prefix}_one_sided_fight_id_count": count_one_sided_fight_ids(df),
        f"{prefix}_may30_or_future_rows_count": count_may30_or_future_rows(df, today),
    }
    if before is not None:
        metrics[f"{prefix}_rows_before"] = int(len(before))
        metrics[f"{prefix}_rows_after"] = int(len(df)) if df is not None else 0
        metrics[f"{prefix}_unique_fights_before"] = unique_fight_count(before)
        metrics[f"{prefix}_unique_fights_after"] = unique_fight_count(df)
        metrics[f"{prefix}_latest_date_before"] = latest_date_string(before)
        metrics[f"{prefix}_latest_date_after"] = latest_date_string(df)
    return metrics


def audit_new_rows_for_apply(
    new_stats: pd.DataFrame,
    existing_fight_ids: set,
    today: pd.Timestamp,
    allow_future_events: bool,
) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    unsafe_indices = set()

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

    if new_stats.empty:
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

    if "won" not in new_stats.columns:
        add_issue("missing_won", "new rows have no won column", new_stats.index)
    else:
        won = pd.to_numeric(new_stats["won"], errors="coerce")
        add_issue("nan_won", "new rows have NaN won", won[won.isna()].index)

    if "fight_id" not in new_stats.columns:
        add_issue("missing_fight_id", "new rows have no fight_id column", new_stats.index)
    else:
        fight_ids = new_stats["fight_id"].astype(str)
        add_issue(
            "duplicate_existing_fight_id",
            "new rows contain fight_id values already present in the project dataset",
            new_stats[fight_ids.isin(existing_fight_ids)].index,
        )
        for fight_id, group in new_stats.groupby(fight_ids):
            bad_shape = len(group) != 2
            if "fighter" in group.columns:
                bad_shape = bad_shape or group["fighter"].isna().any() or group["fighter"].astype(str).map(clean_text).eq("").any()
                bad_shape = bad_shape or group["fighter"].dropna().astype(str).map(normalize_name).nunique() != 2
            if bad_shape:
                add_issue("one_sided_fighter_rows", f"fight_id {fight_id} does not have exactly two fighter rows", group.index)

            if "result_marker" in group.columns:
                markers = [marker_value(x) for x in group["result_marker"].tolist()]
                if markers.count("W") != 1 or markers.count("L") != 1:
                    add_issue("missing_winner_loser", f"fight_id {fight_id} does not have one W and one L marker", group.index)
            elif "won" in group.columns:
                won_values = pd.to_numeric(group["won"], errors="coerce").dropna().tolist()
                if sorted(won_values) != [0.0, 1.0]:
                    add_issue("missing_winner_loser", f"fight_id {fight_id} does not have one winner and one loser", group.index)

    unsafe_fights = 0
    if unsafe_indices and "fight_id" in new_stats.columns:
        unsafe_fights = int(new_stats.loc[list(unsafe_indices), "fight_id"].dropna().astype(str).nunique())
    return {
        "unsafe_rows_count": int(len(unsafe_indices)),
        "unsafe_fight_count": unsafe_fights,
        "issues": issues,
    }


def count_rejected_unsafe_rows(fight_manifest: List[Dict[str, Any]]) -> int:
    rows = 0
    for rec in fight_manifest:
        if rec.get("status") not in UNSAFE_SKIP_STATUSES:
            continue
        if rec.get("fighter_1") and rec.get("fighter_2"):
            rows += 2
    return rows


def write_post_update_audit(
    manifest_dir: Path,
    stamp: str,
    mode: str,
    apply_status: str,
    today: pd.Timestamp,
    stats_before: pd.DataFrame,
    stats_after: pd.DataFrame,
    advanced_before: Optional[pd.DataFrame],
    advanced_after: Optional[pd.DataFrame],
    new_stats: pd.DataFrame,
    new_advanced_rows: pd.DataFrame,
    safety_audit: Dict[str, Any],
    bayesian_rebuild_run: bool,
) -> Dict[str, Any]:
    bayesian_df = pd.read_csv(BAYESIAN_OUTPUT_FILE) if BAYESIAN_OUTPUT_FILE.exists() else None
    audit: Dict[str, Any] = {
        "generated_at": stamp,
        "mode": mode,
        "apply_status": apply_status,
        "today": today.date().isoformat(),
        "bayesian_rebuild_run": bool(bayesian_rebuild_run),
        "new_stats_rows": int(len(new_stats)),
        "new_stats_unique_fights": unique_fight_count(new_stats),
        "new_advanced_rows": int(len(new_advanced_rows)),
        "new_unsafe_rows_count": int(safety_audit.get("unsafe_rows_count", 0)),
        "new_unsafe_fight_count": int(safety_audit.get("unsafe_fight_count", 0)),
        "new_unsafe_issue_count": int(len(safety_audit.get("issues", []))),
        "new_unsafe_issues_json": json.dumps(safety_audit.get("issues", []), sort_keys=True),
    }
    audit.update(dataset_audit_metrics("stats", stats_after, stats_before, today))
    if advanced_after is not None:
        audit.update(dataset_audit_metrics("advanced", advanced_after, advanced_before, today))
    else:
        audit.update(dataset_audit_metrics("advanced", advanced_before, advanced_before, today))
    audit.update(dataset_audit_metrics("bayesian", bayesian_df, None, today))
    audit["future_rows_count"] = int(
        audit.get("stats_future_rows_count", 0)
        + audit.get("advanced_future_rows_count", 0)
        + audit.get("bayesian_future_rows_count", 0)
    )
    audit["unresolved_nan_result_rows_count"] = int(
        audit.get("stats_unresolved_nan_result_rows_count", 0)
        + audit.get("advanced_unresolved_nan_result_rows_count", 0)
        + audit.get("bayesian_unresolved_nan_result_rows_count", 0)
    )
    audit["duplicate_fight_id_count"] = int(
        audit.get("stats_duplicate_fight_id_count", 0)
        + audit.get("advanced_duplicate_fight_id_count", 0)
        + audit.get("bayesian_duplicate_fight_id_count", 0)
    )
    audit["may30_or_future_rows_count"] = int(
        audit.get("stats_may30_or_future_rows_count", 0)
        + audit.get("advanced_may30_or_future_rows_count", 0)
        + audit.get("bayesian_may30_or_future_rows_count", 0)
    )

    csv_path = manifest_dir / "post_update_audit.csv"
    json_path = manifest_dir / "post_update_audit.json"
    pd.DataFrame([audit]).to_csv(csv_path, index=False)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, sort_keys=True)

    print("\nPOST-UPDATE AUDIT")
    print("=" * 100)
    for key in [
        "stats_rows",
        "stats_unique_fights",
        "stats_latest_date",
        "advanced_rows",
        "advanced_unique_fights",
        "advanced_latest_date",
        "bayesian_rows",
        "bayesian_unique_fights",
        "bayesian_latest_date",
        "future_rows_count",
        "unresolved_nan_result_rows_count",
        "duplicate_fight_id_count",
        "may30_or_future_rows_count",
        "new_unsafe_rows_count",
    ]:
        print(f"{key}: {audit.get(key, '')}")
    print(f"Audit CSV:  {csv_path}")
    print(f"Audit JSON: {json_path}")
    return audit


def backup_bayesian_output(stamp: str) -> Optional[Path]:
    if not BAYESIAN_OUT_DIR.exists():
        return None
    backup_dir = Path(f"_backup_bayes_before_rebuild_{stamp}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in BAYESIAN_OUT_DIR.iterdir():
        if path.is_file():
            shutil.copy2(path, backup_dir / path.name)
    return backup_dir


def run_bayesian_rebuild(stats_path: Path, advanced_path: Path, stamp: str) -> None:
    backup_dir = backup_bayesian_output(stamp)
    cmd = [
        sys.executable,
        "build_prefight_bayesian_smoothing_v1_REBUILT.py",
        "build",
        "--training-rows",
        str(advanced_path),
        "--fighter-stats",
        str(stats_path),
        "--out-dir",
        str(BAYESIAN_OUT_DIR),
    ]
    print("\nREBUILDING BAYESIAN PREFIGHT SMOOTHING")
    print("=" * 100)
    if backup_dir is not None:
        print(f"Bayesian backup folder: {backup_dir}")
    print("Command: " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def print_safe_update_summary(summary: Dict[str, Any]) -> None:
    print("\nSAFE UPDATE SUMMARY")
    print("=" * 100)
    for label, key in [
        ("completed events found", "completed_events_found"),
        ("events inspected", "events_inspected"),
        ("women fights scraped", "women_fights_scraped"),
        ("rows to add", "rows_to_add"),
        ("unsafe rows blocked", "unsafe_rows_blocked"),
        ("stats rows before/after", "stats_rows_before_after"),
        ("advanced rows before/after", "advanced_rows_before_after"),
        ("Bayesian rebuild run", "bayesian_rebuild_run"),
        ("final latest date", "final_latest_date"),
        ("apply status", "apply_status"),
    ]:
        print(f"- {label}: {summary.get(key, '')}")


def legacy_main_before_hardening() -> None:
    args = parse_args()
    stamp = now_stamp()

    stats_path = Path(args.stats)
    advanced_path = Path(args.advanced_data)
    profile_path = find_profile_file(args.profiles)
    manifest_dir = Path(args.manifest_dir) / stamp
    manifest_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(args.backup_dir) if args.backup_dir else Path(f"_backup_before_update_{stamp}")

    if not stats_path.exists():
        raise FileNotFoundError(stats_path)
    if not args.no_advanced_update and not advanced_path.exists():
        raise FileNotFoundError(advanced_path)

    session = make_session(args.user_agent)

    existing_stats = pd.read_csv(stats_path)
    existing_stats["event_date"] = pd.to_datetime(existing_stats["event_date"], errors="coerce")
    existing_fight_ids = set(existing_stats["fight_id"].dropna().astype(str))

    if args.from_date:
        cutoff = pd.to_datetime(args.from_date, errors="coerce")
    else:
        cutoff = existing_stats["event_date"].max() + pd.Timedelta(days=1)
    if pd.isna(cutoff):
        raise ValueError("Could not determine cutoff date. Use --from-date YYYY-MM-DD.")
    cutoff = pd.Timestamp(cutoff).normalize()

    print("\nINCREMENTAL UFC WOMEN'S DATASET UPDATE")
    print("=" * 100)
    print(f"Stats file:       {stats_path}")
    print(f"Advanced file:    {advanced_path if not args.no_advanced_update else 'SKIPPED'}")
    print(f"Profiles file:    {profile_path if not args.no_profile_update else 'SKIPPED'}")
    print(f"Existing rows:    {len(existing_stats):,}")
    print(f"Existing fights:  {len(existing_fight_ids):,}")
    print(f"Latest date:      {existing_stats['event_date'].max().date()}")
    print(f"Scrape cutoff:    event_date >= {cutoff.date()}")
    print(f"Mode:             {'APPLY' if args.apply else 'DRY RUN'}")

    events_soup = fetch_soup(session, args.events_url, timeout=args.timeout, sleep=args.sleep)
    raw_event_links = events_soup.select('a[href*="/event-details/"]')
    events = parse_event_list(events_soup)
    if not events:
        raise ValueError("UFCStats returned no parseable completed events; refusing an apparent empty update.")
    print(f"Raw event links found:        {len(raw_event_links)}")
    new_events = [e for e in events if pd.Timestamp(e["event_date"]).normalize() >= cutoff]
    if args.max_events:
        new_events = new_events[: args.max_events]

    print(f"Completed UFCStats events found: {len(events)}")
    print(f"Events to inspect:              {len(new_events)}")

    all_new_fight_rows: List[Dict[str, Any]] = []
    event_manifest = []
    fight_manifest = []

    fights_processed = 0
    for event in new_events:
        print(f"\nEvent: {event['event_date'].date()} | {event['event_name']}")
        try:
            event_soup = fetch_soup(session, event["event_url"], timeout=args.timeout, sleep=args.sleep)
            fight_links = parse_fight_links_from_event(event_soup)
        except Exception as exc:
            print(f"  ERROR fetching event: {exc}")
            event_manifest.append({**event, "status": "event_fetch_error", "error": str(exc)})
            continue

        event_manifest.append({**event, "status": "ok", "fight_links_found": len(fight_links)})
        print(f"  fight links found: {len(fight_links)}")

        for fight_url in fight_links:
            fight_id = extract_id_from_url(fight_url)
            if fight_id in existing_fight_ids:
                fight_manifest.append({"fight_id": fight_id, "fight_url": fight_url, "status": "already_exists"})
                continue
            if args.max_fights is not None and fights_processed >= args.max_fights:
                break
            try:
                rows = parse_fight_page(session, fight_url, event, timeout=args.timeout, sleep=args.sleep)
                if not rows:
                    fight_manifest.append({"fight_id": fight_id, "fight_url": fight_url, "status": "not_womens_bout"})
                    continue
                all_new_fight_rows.extend(rows)
                fights_processed += 1
                print(f"  + women's fight: {rows[0]['fighter']} vs {rows[1]['fighter']} | {rows[0]['division']}")
                fight_manifest.append(
                    {
                        "fight_id": fight_id,
                        "fight_url": fight_url,
                        "status": "scraped",
                        "event_name": event["event_name"],
                        "event_date": event["event_date"].date().isoformat(),
                        "division": rows[0]["division"],
                        "fighter_1": rows[0]["fighter"],
                        "fighter_2": rows[1]["fighter"],
                    }
                )
            except Exception as exc:
                print(f"  ERROR fight {fight_id}: {exc}")
                fight_manifest.append({"fight_id": fight_id, "fight_url": fight_url, "status": "fight_fetch_error", "error": str(exc)})
        if args.max_fights is not None and fights_processed >= args.max_fights:
            break

    new_stats = pd.DataFrame(all_new_fight_rows) if all_new_fight_rows else pd.DataFrame(columns=existing_stats.columns)
    if not new_stats.empty:
        # Align to existing stats columns, adding any new columns at the end.
        for col in existing_stats.columns:
            if col not in new_stats.columns:
                new_stats[col] = np.nan
        extra_cols = [c for c in new_stats.columns if c not in existing_stats.columns]
        new_stats = new_stats[list(existing_stats.columns) + extra_cols]

    # Save manifests even in dry-run.
    pd.DataFrame(event_manifest).to_csv(manifest_dir / "events_inspected.csv", index=False)
    pd.DataFrame(fight_manifest).to_csv(manifest_dir / "fights_inspected.csv", index=False)
    new_stats.to_csv(manifest_dir / "new_fighter_fight_rows_preview.csv", index=False)

    print("\nSCRAPE SUMMARY")
    print("=" * 100)
    print(f"New women's fights scraped: {new_stats['fight_id'].nunique() if not new_stats.empty else 0}")
    print(f"New fighter-fight rows:     {len(new_stats)}")
    print(f"Manifest folder:            {manifest_dir}")

    if new_stats.empty:
        print("\nNo new women's fights found. Nothing to update.")
        return

    updated_stats = pd.concat([existing_stats, new_stats], ignore_index=True)
    updated_stats["event_date"] = pd.to_datetime(updated_stats["event_date"], errors="coerce")
    updated_stats = updated_stats.sort_values(["event_date", "fight_id", "fighter"]).copy()

    # Profile update.
    updated_profiles = None
    if not args.no_profile_update and profile_path is not None:
        if profile_path.exists():
            profiles = pd.read_csv(profile_path)
        else:
            profiles = pd.DataFrame(columns=["fighter", "profile_url", "height", "height_cm", "reach", "reach_cm", "stance", "dob"])
        name_col = "fighter" if "fighter" in profiles.columns else profiles.columns[0] if len(profiles.columns) else "fighter"
        known_profiles = set(profiles[name_col].dropna().astype(str).map(normalize_name)) if not profiles.empty else set()
        new_profile_records = []
        for _, r in new_stats.drop_duplicates("fighter").iterrows():
            if normalize_name(r["fighter"]) in known_profiles:
                continue
            try:
                rec = scrape_profile(session, r.get("profile_url", ""), r["fighter"], timeout=args.timeout, sleep=args.sleep)
                new_profile_records.append(rec)
                print(f"  + profile: {rec.get('fighter')}")
            except Exception as exc:
                print(f"  WARNING profile scrape failed for {r['fighter']}: {exc}")
                new_profile_records.append({"fighter": r["fighter"], "profile_url": r.get("profile_url", "")})
        if new_profile_records:
            updated_profiles = pd.concat([profiles, pd.DataFrame(new_profile_records)], ignore_index=True)
        else:
            updated_profiles = profiles

    # Advanced training rows append.
    updated_advanced = None
    new_advanced_rows = pd.DataFrame()
    if not args.no_advanced_update:
        predictor = import_predictor(args.predictor)
        advanced_df = pd.read_csv(advanced_path)
        existing_advanced_fights = set(advanced_df["fight_id"].dropna().astype(str))
        new_stats_for_advanced = new_stats[~new_stats["fight_id"].astype(str).isin(existing_advanced_fights)].copy()
        if not new_stats_for_advanced.empty:
            new_advanced_rows = build_new_training_rows(
                predictor=predictor,
                advanced_df=advanced_df,
                updated_stats=updated_stats,
                profile_path=profile_path if profile_path and profile_path.exists() else None,
                new_stats_rows=new_stats_for_advanced,
            )
            updated_advanced = pd.concat([advanced_df, new_advanced_rows], ignore_index=True)
            updated_advanced["event_date"] = pd.to_datetime(updated_advanced["event_date"], errors="coerce")
            updated_advanced = updated_advanced.sort_values(["event_date", "fight_id", "fighter_a", "fighter_b"]).copy()
        else:
            updated_advanced = advanced_df
        new_advanced_rows.to_csv(manifest_dir / "new_advanced_training_rows_preview.csv", index=False)
        print(f"New advanced training rows: {len(new_advanced_rows)}")

    if not args.apply:
        print("\nDRY RUN COMPLETE — no project files were changed.")
        print("Review preview files in the manifest folder. Re-run with --apply to write updates.")
        return

    print("\nWRITING UPDATES")
    print("=" * 100)
    backup_file(stats_path, backup_dir)
    updated_stats.to_csv(stats_path, index=False)
    print(f"Updated stats file: {stats_path}")

    if updated_profiles is not None and profile_path is not None:
        backup_file(profile_path, backup_dir)
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        updated_profiles.to_csv(profile_path, index=False)
        print(f"Updated profiles file: {profile_path}")

    if updated_advanced is not None:
        backup_file(advanced_path, backup_dir)
        updated_advanced.to_csv(advanced_path, index=False)
        print(f"Updated advanced file: {advanced_path}")

    print(f"Backup folder: {backup_dir}")
    print(f"Manifest folder: {manifest_dir}")
    print("\nUpdate complete.")


def main() -> None:
    args = parse_args()
    stamp = now_stamp()
    today = today_timestamp()

    stats_path = Path(args.stats)
    advanced_path = Path(args.advanced_data)
    profile_path = find_profile_file(args.profiles)
    manifest_dir = Path(args.manifest_dir) / stamp
    manifest_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(args.backup_dir) if args.backup_dir else Path(f"_backup_before_update_{stamp}")

    if not stats_path.exists():
        raise FileNotFoundError(stats_path)
    if not args.no_advanced_update and not advanced_path.exists():
        raise FileNotFoundError(advanced_path)

    session = make_session(args.user_agent)

    existing_stats = pd.read_csv(stats_path)
    existing_stats["event_date"] = pd.to_datetime(existing_stats["event_date"], errors="coerce")
    existing_fight_ids = set(existing_stats["fight_id"].dropna().astype(str))
    existing_advanced = None if args.no_advanced_update else pd.read_csv(advanced_path)

    if args.from_date:
        cutoff = pd.to_datetime(args.from_date, errors="coerce")
    else:
        cutoff = existing_stats["event_date"].max() + pd.Timedelta(days=1)
    if pd.isna(cutoff):
        raise ValueError("Could not determine cutoff date. Use --from-date YYYY-MM-DD.")
    cutoff = pd.Timestamp(cutoff).normalize()

    print("\nINCREMENTAL UFC WOMEN'S DATASET UPDATE")
    print("=" * 100)
    print(f"Stats file:       {stats_path}")
    print(f"Advanced file:    {advanced_path if not args.no_advanced_update else 'SKIPPED'}")
    print(f"Profiles file:    {profile_path if not args.no_profile_update else 'SKIPPED'}")
    print(f"Existing rows:    {len(existing_stats):,}")
    print(f"Existing fights:  {len(existing_fight_ids):,}")
    print(f"Latest date:      {existing_stats['event_date'].max().date()}")
    print(f"Scrape cutoff:    event_date >= {cutoff.date()}")
    print(f"Today:            {today.date()}")
    print(f"Mode:             {'APPLY' if args.apply else 'DRY RUN'}")

    events_soup = fetch_soup(session, args.events_url, timeout=args.timeout, sleep=args.sleep)
    raw_event_links = events_soup.select('a[href*="/event-details/"]')
    events = parse_event_list(events_soup)
    if not events:
        raise ValueError("UFCStats returned no parseable completed events; refusing an apparent empty update.")
    print(f"Raw event links found:        {len(raw_event_links)}")
    new_events = select_completed_events(events, cutoff, today, args.max_events)

    print(f"Completed UFCStats events found: {len(events)}")
    print(f"Events to inspect:              {len(new_events)}")

    all_new_fight_rows: List[Dict[str, Any]] = []
    event_manifest: List[Dict[str, Any]] = []
    fight_manifest: List[Dict[str, Any]] = []

    fights_processed = 0
    events_inspected = 0
    for event in new_events:
        print(f"\nEvent: {event['event_date'].date()} | {event['event_name']}")
        try:
            event_soup = fetch_soup(session, event["event_url"], timeout=args.timeout, sleep=args.sleep)
            fight_links = parse_fight_links_from_event(event_soup)
            events_inspected += 1
        except Exception as exc:
            print(f"  ERROR fetching event: {exc}")
            event_manifest.append({**event, "status": "event_fetch_error", "error": str(exc)})
            continue

        event_manifest.append({**event, "status": "ok", "fight_links_found": len(fight_links)})
        print(f"  fight links found: {len(fight_links)}")

        for fight_url in fight_links:
            fight_id = extract_id_from_url(fight_url)
            if fight_id in existing_fight_ids:
                fight_manifest.append({"fight_id": fight_id, "fight_url": fight_url, "status": "already_exists"})
                continue
            if args.max_fights is not None and fights_processed >= args.max_fights:
                break
            try:
                rows = parse_fight_page(
                    session,
                    fight_url,
                    event,
                    timeout=args.timeout,
                    sleep=args.sleep,
                    today=today,
                    allow_future_events=args.allow_future_events,
                )
                if not rows:
                    fight_manifest.append({"fight_id": fight_id, "fight_url": fight_url, "status": "not_womens_bout"})
                    continue
                all_new_fight_rows.extend(rows)
                fights_processed += 1
                print(f"  + women's fight: {rows[0]['fighter']} vs {rows[1]['fighter']} | {rows[0]['division']}")
                fight_manifest.append(
                    {
                        "fight_id": fight_id,
                        "fight_url": fight_url,
                        "status": "scraped",
                        "event_name": event["event_name"],
                        "event_date": event["event_date"].date().isoformat(),
                        "division": rows[0]["division"],
                        "fighter_1": rows[0]["fighter"],
                        "fighter_2": rows[1]["fighter"],
                    }
                )
            except SkippedFight as exc:
                rec = {
                    "fight_id": fight_id,
                    "fight_url": fight_url,
                    "status": exc.status,
                    "reason": exc.reason,
                    "event_name": event["event_name"],
                    "event_date": event["event_date"].date().isoformat(),
                }
                rec.update(exc.details)
                fight_manifest.append(rec)
                print(f"  - {exc.status}: {rec.get('fighter_1', '')} vs {rec.get('fighter_2', '')} ({exc.reason})")
            except Exception as exc:
                print(f"  ERROR fight {fight_id}: {exc}")
                fight_manifest.append({"fight_id": fight_id, "fight_url": fight_url, "status": "fight_fetch_error", "error": str(exc)})
        if args.max_fights is not None and fights_processed >= args.max_fights:
            break

    new_stats = pd.DataFrame(all_new_fight_rows) if all_new_fight_rows else pd.DataFrame(columns=existing_stats.columns)
    if not new_stats.empty:
        for col in existing_stats.columns:
            if col not in new_stats.columns:
                new_stats[col] = np.nan
        extra_cols = [c for c in new_stats.columns if c not in existing_stats.columns]
        new_stats = new_stats[list(existing_stats.columns) + extra_cols]

    pd.DataFrame(event_manifest).to_csv(manifest_dir / "events_inspected.csv", index=False)
    pd.DataFrame(fight_manifest).to_csv(manifest_dir / "fights_inspected.csv", index=False)
    new_stats.to_csv(manifest_dir / "new_fighter_fight_rows_preview.csv", index=False)

    safety_audit = audit_new_rows_for_apply(
        new_stats=new_stats,
        existing_fight_ids=existing_fight_ids,
        today=today,
        allow_future_events=args.allow_future_events,
    )
    with open(manifest_dir / "new_rows_safety_audit.json", "w", encoding="utf-8") as f:
        json.dump(safety_audit, f, indent=2, sort_keys=True)

    print("\nSCRAPE SUMMARY")
    print("=" * 100)
    print(f"New women's fights scraped: {unique_fight_count(new_stats)}")
    print(f"New fighter-fight rows:     {len(new_stats)}")
    print(f"Unsafe new rows found:      {safety_audit['unsafe_rows_count']}")
    print(f"Manifest folder:            {manifest_dir}")

    updated_stats = pd.concat([existing_stats, new_stats], ignore_index=True) if not new_stats.empty else existing_stats.copy()
    updated_stats["event_date"] = pd.to_datetime(updated_stats["event_date"], errors="coerce")
    updated_stats = updated_stats.sort_values(["event_date", "fight_id", "fighter"]).copy()

    updated_profiles = None
    if not new_stats.empty and not args.no_profile_update and profile_path is not None:
        if profile_path.exists():
            profiles = pd.read_csv(profile_path)
        else:
            profiles = pd.DataFrame(columns=["fighter", "profile_url", "height", "height_cm", "reach", "reach_cm", "stance", "dob"])
        name_col = "fighter" if "fighter" in profiles.columns else profiles.columns[0] if len(profiles.columns) else "fighter"
        known_profiles = set(profiles[name_col].dropna().astype(str).map(normalize_name)) if not profiles.empty else set()
        new_profile_records = []
        for _, r in new_stats.drop_duplicates("fighter").iterrows():
            if normalize_name(r["fighter"]) in known_profiles:
                continue
            try:
                rec = scrape_profile(session, r.get("profile_url", ""), r["fighter"], timeout=args.timeout, sleep=args.sleep)
                new_profile_records.append(rec)
                print(f"  + profile: {rec.get('fighter')}")
            except Exception as exc:
                print(f"  WARNING profile scrape failed for {r['fighter']}: {exc}")
                new_profile_records.append({"fighter": r["fighter"], "profile_url": r.get("profile_url", "")})
        updated_profiles = pd.concat([profiles, pd.DataFrame(new_profile_records)], ignore_index=True) if new_profile_records else profiles

    updated_advanced = existing_advanced
    new_advanced_rows = pd.DataFrame()
    if not args.no_advanced_update:
        if not new_stats.empty:
            predictor = import_predictor(args.predictor)
            advanced_df = existing_advanced.copy()
            existing_advanced_fights = set(advanced_df["fight_id"].dropna().astype(str))
            new_stats_for_advanced = new_stats[~new_stats["fight_id"].astype(str).isin(existing_advanced_fights)].copy()
            if not new_stats_for_advanced.empty:
                new_advanced_rows = build_new_training_rows(
                    predictor=predictor,
                    advanced_df=advanced_df,
                    updated_stats=updated_stats,
                    profile_path=profile_path if profile_path and profile_path.exists() else None,
                    new_stats_rows=new_stats_for_advanced,
                )
                updated_advanced = pd.concat([advanced_df, new_advanced_rows], ignore_index=True)
                updated_advanced["event_date"] = pd.to_datetime(updated_advanced["event_date"], errors="coerce")
                updated_advanced = updated_advanced.sort_values(["event_date", "fight_id", "fighter_a", "fighter_b"]).copy()
        new_advanced_rows.to_csv(manifest_dir / "new_advanced_training_rows_preview.csv", index=False)
        print(f"New advanced training rows: {len(new_advanced_rows)}")

    if args.apply and args.rebuild_bayesian and args.no_advanced_update and not new_stats.empty:
        raise ValueError("--rebuild-bayesian requires advanced update to be enabled when new rows are added.")

    rejected_unsafe_rows = count_rejected_unsafe_rows(fight_manifest)
    unsafe_rows_blocked = int(safety_audit["unsafe_rows_count"]) + rejected_unsafe_rows
    bayesian_rebuild_run = False
    apply_status = "dry_run"

    def make_summary(status: str, stats_after: pd.DataFrame, advanced_after: Optional[pd.DataFrame]) -> Dict[str, Any]:
        return {
            "completed_events_found": len(events),
            "events_inspected": events_inspected,
            "women_fights_scraped": unique_fight_count(new_stats),
            "rows_to_add": len(new_stats),
            "unsafe_rows_blocked": unsafe_rows_blocked,
            "stats_rows_before_after": f"{len(existing_stats)} / {len(stats_after)}",
            "advanced_rows_before_after": f"{len(existing_advanced) if existing_advanced is not None else 'SKIPPED'} / {len(advanced_after) if advanced_after is not None else 'SKIPPED'}",
            "bayesian_rebuild_run": "yes" if bayesian_rebuild_run else "no",
            "final_latest_date": latest_date_string(stats_after),
            "apply_status": status,
        }

    if not args.apply:
        if args.audit:
            write_post_update_audit(
                manifest_dir=manifest_dir,
                stamp=stamp,
                mode="dry_run",
                apply_status=apply_status,
                today=today,
                stats_before=existing_stats,
                stats_after=updated_stats,
                advanced_before=existing_advanced,
                advanced_after=updated_advanced,
                new_stats=new_stats,
                new_advanced_rows=new_advanced_rows,
                safety_audit=safety_audit,
                bayesian_rebuild_run=bayesian_rebuild_run,
            )
        print("\nDRY RUN COMPLETE - no project files were changed.")
        print("Review preview files in the manifest folder. Re-run with --apply only if the manifest is safe.")
        print_safe_update_summary(make_summary(apply_status, updated_stats, updated_advanced))
        return

    if safety_audit["unsafe_rows_count"] > 0 and not args.allow_unsafe_apply:
        apply_status = "blocked_unsafe"
        if args.audit:
            write_post_update_audit(
                manifest_dir=manifest_dir,
                stamp=stamp,
                mode="apply_blocked",
                apply_status=apply_status,
                today=today,
                stats_before=existing_stats,
                stats_after=existing_stats,
                advanced_before=existing_advanced,
                advanced_after=existing_advanced,
                new_stats=new_stats,
                new_advanced_rows=new_advanced_rows,
                safety_audit=safety_audit,
                bayesian_rebuild_run=bayesian_rebuild_run,
            )
        print("\nUnsafe update blocked. Review manifest.")
        print_safe_update_summary(make_summary(apply_status, existing_stats, existing_advanced))
        raise SystemExit(2)

    if new_stats.empty:
        apply_status = "no_changes"
        if args.audit:
            write_post_update_audit(
                manifest_dir=manifest_dir,
                stamp=stamp,
                mode="apply_no_changes",
                apply_status=apply_status,
                today=today,
                stats_before=existing_stats,
                stats_after=existing_stats,
                advanced_before=existing_advanced,
                advanced_after=existing_advanced,
                new_stats=new_stats,
                new_advanced_rows=new_advanced_rows,
                safety_audit=safety_audit,
                bayesian_rebuild_run=bayesian_rebuild_run,
            )
        print("\nNo new women's fights found. Nothing to update.")
        print_safe_update_summary(make_summary(apply_status, existing_stats, existing_advanced))
        return

    print("\nWRITING UPDATES")
    print("=" * 100)
    backup_file(stats_path, backup_dir)
    updated_stats.to_csv(stats_path, index=False)
    print(f"Updated stats file: {stats_path}")

    if updated_profiles is not None and profile_path is not None:
        backup_file(profile_path, backup_dir)
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        updated_profiles.to_csv(profile_path, index=False)
        print(f"Updated profiles file: {profile_path}")

    if updated_advanced is not None:
        backup_file(advanced_path, backup_dir)
        updated_advanced.to_csv(advanced_path, index=False)
        print(f"Updated advanced file: {advanced_path}")

    apply_status = "applied"
    if args.rebuild_bayesian:
        run_bayesian_rebuild(stats_path=stats_path, advanced_path=advanced_path, stamp=stamp)
        bayesian_rebuild_run = True

    written_stats = pd.read_csv(stats_path)
    written_stats["event_date"] = pd.to_datetime(written_stats["event_date"], errors="coerce")
    written_advanced = pd.read_csv(advanced_path) if not args.no_advanced_update else existing_advanced
    if args.audit:
        write_post_update_audit(
            manifest_dir=manifest_dir,
            stamp=stamp,
            mode="apply",
            apply_status=apply_status,
            today=today,
            stats_before=existing_stats,
            stats_after=written_stats,
            advanced_before=existing_advanced,
            advanced_after=written_advanced,
            new_stats=new_stats,
            new_advanced_rows=new_advanced_rows,
            safety_audit=safety_audit,
            bayesian_rebuild_run=bayesian_rebuild_run,
        )

    print(f"Backup folder: {backup_dir}")
    print(f"Manifest folder: {manifest_dir}")
    print("\nUpdate complete.")
    print_safe_update_summary(make_summary(apply_status, written_stats, written_advanced))


if __name__ == "__main__":
    main()
