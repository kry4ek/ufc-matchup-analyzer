from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


STARTING_ELO = 1500.0
DEFAULT_K_FACTOR = 32.0
DECISIVE_RESULT = "win_loss"


@dataclass(frozen=True)
class EloConfig:
    starting_elo: float = STARTING_ELO
    k_factor: float = DEFAULT_K_FACTOR
    trend_fights: int = 3
    opponent_summary_fights: int = 5


def _clean_id(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _clean_text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def update_elo_pair(
    rating_a: float,
    rating_b: float,
    score_a: float,
    k_factor: float = DEFAULT_K_FACTOR,
) -> tuple[float, float]:
    expected_a = expected_score(rating_a, rating_b)
    expected_b = 1.0 - expected_a
    score_b = 1.0 - score_a
    return (
        rating_a + k_factor * (score_a - expected_a),
        rating_b + k_factor * (score_b - expected_b),
    )


def _recent_trend(history: deque[float], current_rating: float, config: EloConfig) -> float:
    if not history:
        return 0.0
    lookback = min(config.trend_fights, len(history))
    return current_rating - float(list(history)[-lookback])


def _days_since(last_date: pd.Timestamp | None, event_date: pd.Timestamp) -> float:
    if last_date is None or pd.isna(last_date) or pd.isna(event_date):
        return np.nan
    return float((event_date - last_date).days)


def _snapshot_for_fighter(
    *,
    fight: pd.Series,
    fighter_id: str,
    opponent_id: str,
    side: str,
    ratings: dict[str, float],
    division_ratings: dict[tuple[str, str], float],
    rating_history: dict[str, deque[float]],
    last_update_dates: dict[str, pd.Timestamp],
    opponent_elo_history: dict[str, deque[float]],
    config: EloConfig,
) -> dict[str, Any]:
    event_date = pd.to_datetime(fight.get("event_date"), errors="coerce")
    weight_class = _clean_text(fight.get("weight_class"))
    overall_elo = float(ratings.get(fighter_id, config.starting_elo))
    division_elo = float(division_ratings.get((fighter_id, weight_class), config.starting_elo))
    opponent_history = list(opponent_elo_history.get(fighter_id, []))
    last_update_date = last_update_dates.get(fighter_id)

    return {
        "fight_id": fight.get("fight_id"),
        "event_id": fight.get("event_id"),
        "event_date": event_date,
        "weight_class": weight_class,
        "fighter_id": fighter_id,
        "opponent_id": opponent_id,
        "side": side,
        "result": fight.get("result"),
        "elo_before": overall_elo,
        "division_elo_before": division_elo,
        "elo_recent_trend": _recent_trend(rating_history[fighter_id], overall_elo, config),
        "days_since_elo_update": _days_since(last_update_date, event_date),
        "avg_opponent_elo_before": float(np.mean(opponent_history)) if opponent_history else np.nan,
        "last_elo_update_date_before": last_update_date,
    }


def _is_decisive_update(row: pd.Series) -> bool:
    winner_id = _clean_id(row.get("winner_id"))
    loser_id = _clean_id(row.get("loser_id"))
    return (
        _clean_text(row.get("result")) == DECISIVE_RESULT
        and bool(winner_id)
        and bool(loser_id)
        and winner_id != loser_id
    )


def validate_same_date_no_leakage(snapshots: pd.DataFrame) -> dict[str, Any]:
    if snapshots.empty:
        return {
            "passed": True,
            "same_date_overall_rating_violations": 0,
            "same_date_division_rating_violations": 0,
            "last_update_not_before_event_violations": 0,
            "checked_same_date_fighter_groups": 0,
            "checked_same_date_division_groups": 0,
        }

    df = snapshots.copy()
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    df["last_elo_update_date_before"] = pd.to_datetime(
        df["last_elo_update_date_before"], errors="coerce"
    )
    dated = df[pd.notna(df["event_date"])].copy()

    overall_groups = dated.groupby(["event_date", "fighter_id"], dropna=False)
    multi_overall = overall_groups.filter(lambda group: len(group) > 1)
    overall_violations = 0
    if not multi_overall.empty:
        overall_violations = int(
            multi_overall.groupby(["event_date", "fighter_id"], dropna=False)["elo_before"]
            .nunique(dropna=False)
            .gt(1)
            .sum()
        )

    division_groups = dated.groupby(["event_date", "fighter_id", "weight_class"], dropna=False)
    multi_division = division_groups.filter(lambda group: len(group) > 1)
    division_violations = 0
    if not multi_division.empty:
        division_violations = int(
            multi_division.groupby(["event_date", "fighter_id", "weight_class"], dropna=False)[
                "division_elo_before"
            ]
            .nunique(dropna=False)
            .gt(1)
            .sum()
        )

    bad_last_update = dated[
        pd.notna(dated["last_elo_update_date_before"])
        & (dated["last_elo_update_date_before"] >= dated["event_date"])
    ]

    return {
        "passed": bool(
            overall_violations == 0
            and division_violations == 0
            and len(bad_last_update) == 0
        ),
        "same_date_overall_rating_violations": overall_violations,
        "same_date_division_rating_violations": division_violations,
        "last_update_not_before_event_violations": int(len(bad_last_update)),
        "checked_same_date_fighter_groups": int(
            multi_overall.groupby(["event_date", "fighter_id"], dropna=False).ngroups
            if not multi_overall.empty
            else 0
        ),
        "checked_same_date_division_groups": int(
            multi_division.groupby(["event_date", "fighter_id", "weight_class"], dropna=False).ngroups
            if not multi_division.empty
            else 0
        ),
    }


def build_mens_elo_features(
    fights_df: pd.DataFrame,
    config: EloConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    config = config or EloConfig()
    required = {
        "fight_id",
        "event_id",
        "event_date",
        "weight_class",
        "fighter_red_id",
        "fighter_blue_id",
        "winner_id",
        "loser_id",
        "result",
    }
    missing = sorted(required - set(fights_df.columns))
    if missing:
        raise ValueError(f"Missing required fights columns: {missing}")

    fights = fights_df.copy()
    fights["event_date"] = pd.to_datetime(fights["event_date"], errors="coerce")
    fights = fights.sort_values(["event_date", "event_id", "fight_id"], na_position="last").reset_index(
        drop=True
    )

    ratings: dict[str, float] = defaultdict(lambda: config.starting_elo)
    division_ratings: dict[tuple[str, str], float] = defaultdict(lambda: config.starting_elo)
    rating_history: dict[str, deque[float]] = defaultdict(deque)
    last_update_dates: dict[str, pd.Timestamp] = {}
    opponent_elo_history: dict[str, deque[float]] = defaultdict(
        lambda: deque(maxlen=config.opponent_summary_fights)
    )

    snapshots: list[dict[str, Any]] = []
    update_count = 0
    skipped_updates: list[dict[str, Any]] = []
    decisive_fight_count = int((fights["result"].astype(str) == DECISIVE_RESULT).sum())

    for _, date_group in fights.groupby("event_date", sort=True, dropna=False):
        for _, fight in date_group.iterrows():
            red_id = _clean_id(fight.get("fighter_red_id"))
            blue_id = _clean_id(fight.get("fighter_blue_id"))
            if not red_id or not blue_id:
                continue
            snapshots.append(
                _snapshot_for_fighter(
                    fight=fight,
                    fighter_id=red_id,
                    opponent_id=blue_id,
                    side="red",
                    ratings=ratings,
                    division_ratings=division_ratings,
                    rating_history=rating_history,
                    last_update_dates=last_update_dates,
                    opponent_elo_history=opponent_elo_history,
                    config=config,
                )
            )
            snapshots.append(
                _snapshot_for_fighter(
                    fight=fight,
                    fighter_id=blue_id,
                    opponent_id=red_id,
                    side="blue",
                    ratings=ratings,
                    division_ratings=division_ratings,
                    rating_history=rating_history,
                    last_update_dates=last_update_dates,
                    opponent_elo_history=opponent_elo_history,
                    config=config,
                )
            )

        for _, fight in date_group.iterrows():
            if not _is_decisive_update(fight):
                continue

            winner_id = _clean_id(fight.get("winner_id"))
            loser_id = _clean_id(fight.get("loser_id"))
            fight_fighters = {
                _clean_id(fight.get("fighter_red_id")),
                _clean_id(fight.get("fighter_blue_id")),
            }
            if winner_id not in fight_fighters or loser_id not in fight_fighters:
                skipped_updates.append(
                    {
                        "fight_id": fight.get("fight_id"),
                        "reason": "winner_or_loser_not_in_fight_fighters",
                    }
                )
                continue

            event_date = pd.to_datetime(fight.get("event_date"), errors="coerce")
            weight_class = _clean_text(fight.get("weight_class"))
            winner_before = float(ratings[winner_id])
            loser_before = float(ratings[loser_id])
            winner_after, loser_after = update_elo_pair(
                winner_before,
                loser_before,
                score_a=1.0,
                k_factor=config.k_factor,
            )
            ratings[winner_id] = winner_after
            ratings[loser_id] = loser_after

            div_winner_key = (winner_id, weight_class)
            div_loser_key = (loser_id, weight_class)
            div_winner_after, div_loser_after = update_elo_pair(
                float(division_ratings[div_winner_key]),
                float(division_ratings[div_loser_key]),
                score_a=1.0,
                k_factor=config.k_factor,
            )
            division_ratings[div_winner_key] = div_winner_after
            division_ratings[div_loser_key] = div_loser_after

            rating_history[winner_id].append(winner_after)
            rating_history[loser_id].append(loser_after)
            opponent_elo_history[winner_id].append(loser_before)
            opponent_elo_history[loser_id].append(winner_before)
            if pd.notna(event_date):
                last_update_dates[winner_id] = event_date
                last_update_dates[loser_id] = event_date
            update_count += 1

    snapshots_df = pd.DataFrame(snapshots)
    same_date_check = validate_same_date_no_leakage(snapshots_df)
    audit = {
        "starting_elo": config.starting_elo,
        "k_factor": config.k_factor,
        "trend_fights": config.trend_fights,
        "opponent_summary_fights": config.opponent_summary_fights,
        "normalized_fights": int(len(fights)),
        "snapshot_rows": int(len(snapshots_df)),
        "decisive_fights": decisive_fight_count,
        "elo_updated_fights": int(update_count),
        "skipped_update_count": int(len(skipped_updates)),
        "skipped_updates_sample": skipped_updates[:20],
        "draw_no_contest_policy": "draw and no_contest rows receive pre-fight snapshots but do not update Elo",
        "same_date_leakage_check": same_date_check,
    }
    return snapshots_df, audit
