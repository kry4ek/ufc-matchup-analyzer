from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any, Mapping
import re
import unicodedata

import pandas as pd


DETAIL_COLUMNS = [
    "fighter_id",
    "fighter_name",
    "height_cm",
    "reach_cm",
    "stance",
    "date_of_birth",
    "weight_lbs",
]


@dataclass(frozen=True)
class FighterLookupResult:
    fighter_id: str
    fighter_name: str
    details: dict[str, Any]


class FighterLookupError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        suggestions: list[str] | None = None,
        duplicates: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.suggestions = suggestions or []
        self.duplicates = duplicates or []


def normalize_name(value: Any) -> str:
    text = "" if pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def _row_details(row: pd.Series) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for column in DETAIL_COLUMNS:
        if column not in row.index:
            continue
        value = row.get(column)
        if pd.isna(value):
            details[column] = None
        elif column in {"height_cm", "reach_cm", "weight_lbs"}:
            details[column] = float(value)
        else:
            details[column] = str(value)
    return details


def _manual_id_from_name(name: str) -> str:
    normalized = normalize_name(name)
    slug = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    return f"manual_{slug or 'fighter'}"


def _manual_detail_value(column: str, value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if value is None or str(value).strip() == "":
        return None
    if column in {"height_cm", "reach_cm", "weight_lbs"}:
        parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        return None if pd.isna(parsed) else float(parsed)
    return str(value).strip()


def manual_fighter_result(
    name: str,
    *,
    fighter_id: str | None = None,
    profile: Mapping[str, Any] | None = None,
) -> FighterLookupResult:
    cleaned_name = str(name or "").strip()
    if not cleaned_name:
        raise FighterLookupError("Fighter name is empty")
    cleaned_id = str(fighter_id or "").strip() or _manual_id_from_name(cleaned_name)
    profile = profile or {}
    details: dict[str, Any] = {
        "fighter_id": cleaned_id,
        "fighter_name": cleaned_name,
        "manual_profile": True,
        "no_ufc_history": True,
    }
    for column in DETAIL_COLUMNS:
        if column in {"fighter_id", "fighter_name"}:
            continue
        details[column] = _manual_detail_value(column, profile.get(column))
    return FighterLookupResult(
        fighter_id=cleaned_id,
        fighter_name=cleaned_name,
        details=details,
    )


def _details_for_rows(rows: pd.DataFrame) -> list[dict[str, Any]]:
    if rows.empty:
        return []
    unique = rows.drop_duplicates("fighter_id").copy()
    return [_row_details(row) for _, row in unique.iterrows()]


def load_fighters(path: str) -> pd.DataFrame:
    fighters = pd.read_csv(path)
    required = {"fighter_id", "fighter_name"}
    missing = sorted(required - set(fighters.columns))
    if missing:
        raise ValueError(f"Missing required fighter columns: {missing}")
    fighters = fighters.copy()
    fighters["fighter_id"] = fighters["fighter_id"].astype(str).str.strip()
    fighters["fighter_name"] = fighters["fighter_name"].astype(str).str.strip()
    fighters["_lookup_name"] = fighters["fighter_name"].map(normalize_name)
    return fighters


def suggest_fighter_names(fighters: pd.DataFrame, query: str, *, limit: int = 8) -> list[str]:
    normalized_query = normalize_name(query)
    name_map = (
        fighters[["_lookup_name", "fighter_name"]]
        .dropna()
        .drop_duplicates("_lookup_name")
        .set_index("_lookup_name")["fighter_name"]
        .to_dict()
    )
    close = get_close_matches(normalized_query, list(name_map), n=limit, cutoff=0.55)
    return [name_map[item] for item in close]


def lookup_fighter(fighters: pd.DataFrame, name: str) -> FighterLookupResult:
    normalized_query = normalize_name(name)
    if not normalized_query:
        raise FighterLookupError("Fighter name is empty")

    exact = fighters[fighters["_lookup_name"] == normalized_query].copy()
    if exact.empty:
        suggestions = suggest_fighter_names(fighters, name)
        message = f"Fighter not found: {name}"
        if suggestions:
            message += f". Closest known names: {', '.join(suggestions)}"
        raise FighterLookupError(message, suggestions=suggestions)

    unique = exact.drop_duplicates("fighter_id")
    if len(unique) > 1:
        duplicates = _details_for_rows(unique)
        ids = ", ".join(item["fighter_id"] for item in duplicates)
        raise FighterLookupError(
            f"Multiple fighter IDs match '{name}'. Use a unique fighter name; matched IDs: {ids}",
            duplicates=duplicates,
        )

    row = unique.iloc[0]
    return FighterLookupResult(
        fighter_id=str(row["fighter_id"]),
        fighter_name=str(row["fighter_name"]),
        details=_row_details(row),
    )


def lookup_fighter_by_id(fighters: pd.DataFrame, fighter_id: str) -> FighterLookupResult:
    requested_id = str(fighter_id or "").strip()
    if not requested_id:
        raise FighterLookupError("Fighter ID is empty")

    exact = fighters[fighters["fighter_id"].astype(str).str.casefold() == requested_id.casefold()].copy()
    if exact.empty:
        raise FighterLookupError(f"Fighter ID not found: {fighter_id}")

    unique = exact.drop_duplicates("fighter_id")
    row = unique.iloc[0]
    return FighterLookupResult(
        fighter_id=str(row["fighter_id"]),
        fighter_name=str(row["fighter_name"]),
        details=_row_details(row),
    )


def format_lookup_error(error: FighterLookupError) -> str:
    lines = [str(error)]
    if error.duplicates:
        lines.append("Matching fighter records:")
        for item in error.duplicates:
            lines.append(
                "- "
                + ", ".join(
                    f"{key}={value}" for key, value in item.items() if value not in {None, ""}
                )
            )
    if error.suggestions:
        lines.append("Closest known names:")
        for name in error.suggestions:
            lines.append(f"- {name}")
    return "\n".join(lines)
