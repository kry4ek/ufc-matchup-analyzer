from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from src.common.utils import (
    clean_text,
    ensure_http,
    id_from_url,
    normalize_division,
    parse_float,
    parse_int,
    slugify_url,
)


BASE_URL = "http://ufcstats.com"
COMPLETED_EVENTS_URL = f"{BASE_URL}/statistics/events/completed?page=all"


def _build_retry_adapter() -> HTTPAdapter:
    """Retry transient network failures (dropped connections, 429, 5xx) with
    exponential backoff, so an unattended weekly run survives a blip instead of
    aborting the whole update. Cached pages mean re-runs are cheap regardless."""
    retry = Retry(
        total=4, connect=4, read=4, backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    return HTTPAdapter(max_retries=retry)


def is_ufcstats_browser_check(html: str) -> bool:
    text = html or ""
    lowered = text.lower()
    return (
        "checking your browser" in lowered
        and "/__c" in text
        and "nonce" in lowered
        and "sha256" in lowered
    )


def solve_browser_check_answer(html: str) -> tuple[str, int]:
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


class UFCStatsScraper:
    def __init__(
        self,
        cache_dir: str | Path = "cache",
        sleep_seconds: float = 0.5,
        refresh_cache: bool = False,
        timeout: int = 30,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.sleep_seconds = sleep_seconds
        self.refresh_cache = refresh_cache
        self.timeout = timeout
        self.session = requests.Session()
        adapter = _build_retry_adapter()
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def clear_browser_check(self, url: str, html: str) -> None:
        nonce, answer = solve_browser_check_answer(html)
        response = self.session.post(
            urljoin(url, "/__c"),
            data={"nonce": nonce, "n": str(answer)},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout,
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"UFCStats browser check POST returned HTTP {response.status_code}.")

    def fetch_html(self, url: str) -> str:
        url = ensure_http(url)
        cache_path = self.cache_dir / slugify_url(url)
        if cache_path.exists() and not self.refresh_cache:
            cached = cache_path.read_text(encoding="utf-8", errors="ignore")
            if not is_ufcstats_browser_check(cached):
                return cached

        time.sleep(self.sleep_seconds)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        html = response.text
        if is_ufcstats_browser_check(html):
            self.clear_browser_check(url, html)
            time.sleep(self.sleep_seconds)
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            html = response.text
            if is_ufcstats_browser_check(html):
                raise RuntimeError("UFCStats browser check did not clear after proof-of-work response.")

        cache_path.write_text(html, encoding="utf-8")
        return html

    def soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self.fetch_html(url), "lxml")

    def get_completed_events(self) -> pd.DataFrame:
        soup = self.soup(COMPLETED_EVENTS_URL)
        rows = []
        date_pattern = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")
        for table_row in soup.select("tr.b-statistics__table-row"):
            link = table_row.select_one("a.b-link")
            if not link or not link.get("href"):
                continue
            event_url = ensure_http(urljoin(BASE_URL, link["href"]))
            event_name = clean_text(link.get_text(" "))
            raw_cells = [cell.get_text("\n", strip=True) for cell in table_row.select("td")]
            cells = [clean_text(raw) for raw in raw_cells]
            date_text = ""
            location_text = ""

            for idx, raw in enumerate(raw_cells):
                parts = [clean_text(part) for part in raw.splitlines() if clean_text(part)]
                for part in parts:
                    match = date_pattern.search(part)
                    if match and not date_text:
                        date_text = match.group(1)

                non_date_parts = [part for part in parts if not date_pattern.search(part)]
                if idx == 1 and non_date_parts:
                    location_text = non_date_parts[-1]

            if not date_text:
                match = date_pattern.search(clean_text(table_row.get_text(" ")))
                date_text = match.group(1) if match else ""
            if not location_text and len(cells) >= 2:
                location_text = cells[1]

            rows.append(
                {
                    "event_id": id_from_url(event_url),
                    "event_name": event_name,
                    "event_date": pd.to_datetime(date_text, errors="coerce"),
                    "location": location_text,
                    "event_url": event_url,
                }
            )
        return pd.DataFrame(rows)

    def get_event_fights(self, event_url: str) -> list[dict[str, Any]]:
        soup = self.soup(event_url)
        event_name_node = soup.select_one("h2.b-content__title")
        event_name = clean_text(event_name_node.get_text(" ")) if event_name_node else ""
        event_date = ""
        location = ""
        for item in soup.select("li.b-list__box-list-item"):
            text = clean_text(item.get_text(" "))
            lower = text.lower()
            if lower.startswith("date:"):
                event_date = clean_text(text.split(":", 1)[1])
            elif lower.startswith("location:"):
                location = clean_text(text.split(":", 1)[1])

        fights = []
        for table_row in soup.select("tr.b-fight-details__table-row"):
            fight_url = table_row.get("data-link")
            if not fight_url:
                link = table_row.select_one("a[href*='/fight-details/']")
                fight_url = link.get("href") if link else None
            if not fight_url:
                continue
            fight_url = ensure_http(urljoin(BASE_URL, fight_url))

            cells = table_row.select("td")
            if len(cells) < 10:
                continue

            fighter_links = cells[1].select("a[href*='/fighter-details/']")
            fighter_names = [clean_text(link.get_text(" ")) for link in fighter_links]
            fighter_urls = [
                ensure_http(urljoin(BASE_URL, link.get("href"))) for link in fighter_links
            ]
            result_markers = [clean_text(item.get_text(" ")) for item in cells[0].select("p")]
            bout_type = clean_text(cells[6].get_text(" "))
            method = clean_text(cells[7].get_text(" "))
            round_number = clean_text(cells[8].get_text(" "))
            time_value = clean_text(cells[9].get_text(" "))

            fights.append(
                {
                    "event_id": id_from_url(event_url),
                    "event_url": ensure_http(event_url),
                    "event_name": event_name,
                    "event_date": pd.to_datetime(event_date, errors="coerce"),
                    "location": location,
                    "fight_id": id_from_url(fight_url),
                    "fight_url": fight_url,
                    "fighter_1": fighter_names[0] if len(fighter_names) > 0 else None,
                    "fighter_2": fighter_names[1] if len(fighter_names) > 1 else None,
                    "fighter_1_profile_url": fighter_urls[0] if len(fighter_urls) > 0 else None,
                    "fighter_2_profile_url": fighter_urls[1] if len(fighter_urls) > 1 else None,
                    "fighter_1_result_marker": result_markers[0] if len(result_markers) > 0 else None,
                    "fighter_2_result_marker": result_markers[1] if len(result_markers) > 1 else None,
                    "bout_type": bout_type,
                    "division": normalize_division(bout_type),
                    "method": method,
                    "round": parse_int(round_number),
                    "time": time_value,
                }
            )
        return fights

    def get_fighter_profile(self, profile_url: str) -> dict[str, Any]:
        soup = self.soup(profile_url)
        name_node = soup.select_one("span.b-content__title-highlight")
        profile = {
            "fighter": clean_text(name_node.get_text(" ")) if name_node else "",
            "profile_url": ensure_http(profile_url),
            "fighter_id": id_from_url(profile_url),
        }
        for item in soup.select("li.b-list__box-list-item"):
            text = clean_text(item.get_text(" "))
            lower = text.lower()
            if lower.startswith("height:"):
                profile["height_raw"] = clean_text(text.split(":", 1)[1])
                profile["height_cm"] = self._height_to_cm(profile["height_raw"])
            elif lower.startswith("weight:"):
                profile["weight_raw"] = clean_text(text.split(":", 1)[1])
                profile["weight_lbs"] = parse_float(profile["weight_raw"])
            elif lower.startswith("reach:"):
                profile["reach_raw"] = clean_text(text.split(":", 1)[1])
                profile["reach_cm"] = self._reach_to_cm(profile["reach_raw"])
            elif lower.startswith("stance:"):
                profile["stance"] = clean_text(text.split(":", 1)[1])
            elif lower.startswith("dob:"):
                profile["dob_raw"] = clean_text(text.split(":", 1)[1])
                profile["dob"] = pd.to_datetime(profile["dob_raw"], errors="coerce")
        return profile

    @staticmethod
    def _height_to_cm(value: Any) -> float | None:
        text = clean_text(value)
        if text in {"", "--"}:
            return None
        match = re.search(r"(\d+)\s*'\s*(\d+)", text)
        if match:
            feet = int(match.group(1))
            inches = int(match.group(2))
            return round((feet * 12 + inches) * 2.54, 2)
        return None

    @staticmethod
    def _reach_to_cm(value: Any) -> float | None:
        text = clean_text(value)
        if text in {"", "--"}:
            return None
        value_float = parse_float(text)
        return round(value_float * 2.54, 2) if value_float is not None else None
