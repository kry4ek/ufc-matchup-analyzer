from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

import numpy as np
import pandas as pd

from src.common.utils import safe_div


STAT_COLUMNS = [
    "knockdowns",
    "significant_strikes_landed",
    "significant_strikes_attempted",
    "total_strikes_landed",
    "total_strikes_attempted",
    "takedowns_landed",
    "takedowns_attempted",
    "submission_attempts",
    "reversals",
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
]

DIFF_FEATURES = [
    "age_at_fight",
    "height_cm",
    "reach_cm",
    "ufc_fights_before",
    "ufc_wins_before",
    "ufc_losses_before",
    "ufc_win_pct_before",
    "current_win_streak",
    "current_loss_streak",
    "days_since_last_fight",
    "career_minutes_before",
    "career_slpm_before",
    "career_sapm_before",
    "career_sig_str_accuracy_before",
    "career_sig_str_defense_before",
    "career_total_str_accuracy_before",
    "career_total_str_defense_before",
    "career_td_avg_per15_before",
    "career_td_accuracy_before",
    "career_td_defense_before",
    "career_sub_attempts_per15_before",
    "career_control_seconds_per15_before",
    "last_3_win_pct",
    "last_3_sig_str_diff_per_min",
    "last_3_td_diff_per15",
    "last_5_win_pct",
    "last_5_sig_str_diff_per_min",
    "last_5_td_diff_per15",
]


def _clean_id(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def stance_matchup(a_stance: Any, b_stance: Any) -> str:
    def clean(value: Any) -> str:
        if pd.isna(value) or not str(value).strip():
            return "Unknown"
        return str(value).strip()

    return f"{clean(a_stance)}_vs_{clean(b_stance)}"


def _num(value: Any, default: float = 0.0) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return default if pd.isna(parsed) else float(parsed)


def add_opponent_stats(stats_df: pd.DataFrame) -> pd.DataFrame:
    df = stats_df.copy()
    for col in STAT_COLUMNS + ["elapsed_seconds", "won"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    keep = ["fight_id", "fighter_id"] + [c for c in STAT_COLUMNS if c in df.columns]
    opponent = df[keep].copy()
    opponent = opponent.rename(
        columns={
            "fighter_id": "opponent_id",
            **{col: f"opponent_{col}" for col in keep if col not in {"fight_id", "fighter_id"}},
        }
    )
    df = df.merge(opponent, on=["fight_id", "opponent_id"], how="left")
    return df


def _zero_history() -> dict[str, Any]:
    return {
        "fights": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "no_contests": 0,
        "minutes": 0.0,
        "sig_str_landed": 0.0,
        "sig_str_attempted": 0.0,
        "sig_str_absorbed": 0.0,
        "opponent_sig_str_attempted": 0.0,
        "total_str_landed": 0.0,
        "total_str_attempted": 0.0,
        "total_str_absorbed": 0.0,
        "opponent_total_str_attempted": 0.0,
        "td_landed": 0.0,
        "td_attempted": 0.0,
        "opponent_td_landed": 0.0,
        "opponent_td_attempted": 0.0,
        "sub_attempts": 0.0,
        "control_time_seconds": 0.0,
        "last_fight_date": pd.NaT,
        "history_max_event_date_before": pd.NaT,
        "current_win_streak": 0,
        "current_loss_streak": 0,
        "recent": deque(maxlen=5),
    }


def _recent_win_pct(items: list[dict[str, Any]]) -> float:
    valid = [item for item in items if item.get("result") in {"win", "loss"}]
    if not valid:
        return np.nan
    return sum(1 for item in valid if item.get("result") == "win") / len(valid)


def _recent_sig_diff_per_min(items: list[dict[str, Any]]) -> float:
    minutes = sum(_num(item.get("minutes")) for item in items)
    if minutes <= 0:
        return np.nan
    diff = sum(
        _num(item.get("sig_str_landed"))
        - _num(item.get("sig_str_absorbed"))
        for item in items
    )
    return diff / minutes


def _recent_td_diff_per15(items: list[dict[str, Any]]) -> float:
    minutes = sum(_num(item.get("minutes")) for item in items)
    if minutes <= 0:
        return np.nan
    diff = sum(
        _num(item.get("td_landed")) - _num(item.get("td_absorbed"))
        for item in items
    )
    return diff / minutes * 15.0


def _snapshot_from_history(history: dict[str, Any], event_date: pd.Timestamp) -> dict[str, Any]:
    recent = list(history["recent"])
    last3 = recent[-3:]
    last5 = recent[-5:]
    last_fight_date = pd.to_datetime(history["last_fight_date"], errors="coerce")
    days_since_last = np.nan
    if pd.notna(last_fight_date) and pd.notna(event_date):
        days_since_last = (event_date - last_fight_date).days

    minutes = history["minutes"]
    return {
        "ufc_fights_before": history["fights"],
        "ufc_wins_before": history["wins"],
        "ufc_losses_before": history["losses"],
        "ufc_draws_before": history["draws"],
        "ufc_no_contests_before": history["no_contests"],
        "ufc_win_pct_before": safe_div(history["wins"], history["wins"] + history["losses"], np.nan),
        "current_win_streak": history["current_win_streak"],
        "current_loss_streak": history["current_loss_streak"],
        "days_since_last_fight": days_since_last,
        "career_minutes_before": minutes,
        "career_slpm_before": safe_div(history["sig_str_landed"], minutes, np.nan),
        "career_sapm_before": safe_div(history["sig_str_absorbed"], minutes, np.nan),
        "career_sig_str_accuracy_before": safe_div(
            history["sig_str_landed"], history["sig_str_attempted"], np.nan
        ),
        "career_sig_str_defense_before": safe_div(
            history["opponent_sig_str_attempted"] - history["sig_str_absorbed"],
            history["opponent_sig_str_attempted"],
            np.nan,
        ),
        "career_total_str_accuracy_before": safe_div(
            history["total_str_landed"], history["total_str_attempted"], np.nan
        ),
        "career_total_str_defense_before": safe_div(
            history["opponent_total_str_attempted"] - history["total_str_absorbed"],
            history["opponent_total_str_attempted"],
            np.nan,
        ),
        "career_td_avg_per15_before": safe_div(history["td_landed"], minutes, np.nan) * 15.0
        if minutes > 0
        else np.nan,
        "career_td_accuracy_before": safe_div(history["td_landed"], history["td_attempted"], np.nan),
        "career_td_defense_before": safe_div(
            history["opponent_td_attempted"] - history["opponent_td_landed"],
            history["opponent_td_attempted"],
            np.nan,
        ),
        "career_sub_attempts_per15_before": safe_div(history["sub_attempts"], minutes, np.nan) * 15.0
        if minutes > 0
        else np.nan,
        "career_control_seconds_per15_before": safe_div(
            history["control_time_seconds"], minutes, np.nan
        )
        * 15.0
        if minutes > 0
        else np.nan,
        "last_3_win_pct": _recent_win_pct(last3),
        "last_3_sig_str_diff_per_min": _recent_sig_diff_per_min(last3),
        "last_3_td_diff_per15": _recent_td_diff_per15(last3),
        "last_5_win_pct": _recent_win_pct(last5),
        "last_5_sig_str_diff_per_min": _recent_sig_diff_per_min(last5),
        "last_5_td_diff_per15": _recent_td_diff_per15(last5),
        "history_max_event_date_before": history["history_max_event_date_before"],
    }


def _update_history(history: dict[str, Any], row: pd.Series) -> None:
    result = row.get("result")
    event_date = pd.to_datetime(row.get("event_date"), errors="coerce")
    elapsed = _num(row.get("elapsed_seconds"))
    minutes = elapsed / 60.0 if elapsed > 0 else 0.0

    if result == "win":
        history["wins"] += 1
        history["current_win_streak"] += 1
        history["current_loss_streak"] = 0
    elif result == "loss":
        history["losses"] += 1
        history["current_loss_streak"] += 1
        history["current_win_streak"] = 0
    elif result == "draw":
        history["draws"] += 1
        history["current_win_streak"] = 0
        history["current_loss_streak"] = 0
    elif result == "no_contest":
        history["no_contests"] += 1

    history["fights"] += 1
    history["minutes"] += minutes
    history["sig_str_landed"] += _num(row.get("significant_strikes_landed"))
    history["sig_str_attempted"] += _num(row.get("significant_strikes_attempted"))
    history["sig_str_absorbed"] += _num(row.get("opponent_significant_strikes_landed"))
    history["opponent_sig_str_attempted"] += _num(row.get("opponent_significant_strikes_attempted"))
    history["total_str_landed"] += _num(row.get("total_strikes_landed"))
    history["total_str_attempted"] += _num(row.get("total_strikes_attempted"))
    history["total_str_absorbed"] += _num(row.get("opponent_total_strikes_landed"))
    history["opponent_total_str_attempted"] += _num(row.get("opponent_total_strikes_attempted"))
    history["td_landed"] += _num(row.get("takedowns_landed"))
    history["td_attempted"] += _num(row.get("takedowns_attempted"))
    history["opponent_td_landed"] += _num(row.get("opponent_takedowns_landed"))
    history["opponent_td_attempted"] += _num(row.get("opponent_takedowns_attempted"))
    history["sub_attempts"] += _num(row.get("submission_attempts"))
    history["control_time_seconds"] += _num(row.get("control_time_seconds"))
    if pd.notna(event_date):
        history["last_fight_date"] = event_date
        history["history_max_event_date_before"] = event_date
    history["recent"].append(
        {
            "result": result,
            "minutes": minutes,
            "sig_str_landed": _num(row.get("significant_strikes_landed")),
            "sig_str_absorbed": _num(row.get("opponent_significant_strikes_landed")),
            "td_landed": _num(row.get("takedowns_landed")),
            "td_absorbed": _num(row.get("opponent_takedowns_landed")),
        }
    )


def build_prefight_snapshots(
    fight_stats_df: pd.DataFrame,
    fighters_df: pd.DataFrame,
    fights_df: pd.DataFrame,
) -> pd.DataFrame:
    stats = add_opponent_stats(fight_stats_df)
    fights_meta = fights_df[
        [
            "fight_id",
            "event_id",
            "event_date",
            "weight_class",
            "is_catchweight_or_openweight",
            "result",
            "method",
            "round",
            "time",
        ]
    ].rename(columns={"result": "fight_result"})
    stats = stats.merge(fights_meta, on=["fight_id", "event_id", "event_date"], how="left")
    stats["event_date"] = pd.to_datetime(stats["event_date"], errors="coerce")
    stats = stats.sort_values(["event_date", "event_id", "fight_id", "fighter_id"]).reset_index(drop=True)

    profiles = fighters_df.copy()
    if not profiles.empty:
        profiles["date_of_birth"] = pd.to_datetime(profiles.get("date_of_birth"), errors="coerce")
        for col in ["height_cm", "reach_cm", "weight_lbs"]:
            if col in profiles.columns:
                profiles[col] = pd.to_numeric(profiles[col], errors="coerce")
        profile_keep = [
            c
            for c in [
                "fighter_id",
                "fighter_name",
                "date_of_birth",
                "height_cm",
                "reach_cm",
                "weight_lbs",
                "stance",
            ]
            if c in profiles.columns
        ]
        profile_map = profiles[profile_keep].drop_duplicates("fighter_id").set_index("fighter_id").to_dict("index")
    else:
        profile_map = {}

    histories = defaultdict(_zero_history)
    snapshots: list[dict[str, Any]] = []

    for event_date, date_group in stats.groupby("event_date", sort=True, dropna=False):
        event_date = pd.to_datetime(event_date, errors="coerce")
        # Build every snapshot for this event date before any same-date history update.
        for _, row in date_group.iterrows():
            fighter_id = _clean_id(row.get("fighter_id"))
            profile = profile_map.get(fighter_id, {})
            snap = {
                "fight_id": row.get("fight_id"),
                "event_id": row.get("event_id"),
                "event_date": row.get("event_date"),
                "weight_class": row.get("weight_class"),
                "is_catchweight_or_openweight": row.get("is_catchweight_or_openweight"),
                "fighter_id": fighter_id,
                "fighter_name": row.get("fighter_name") or profile.get("fighter_name"),
                "opponent_id": row.get("opponent_id"),
                "opponent_name": row.get("opponent_name"),
                "result": row.get("result"),
                "won": row.get("won"),
                "method": row.get("method"),
                "round": row.get("round"),
                "time": row.get("time"),
                "stance": profile.get("stance"),
                "height_cm": profile.get("height_cm"),
                "reach_cm": profile.get("reach_cm"),
                "weight_lbs": profile.get("weight_lbs"),
            }
            dob = pd.to_datetime(profile.get("date_of_birth"), errors="coerce")
            snap["age_at_fight"] = (
                (event_date - dob).days / 365.25 if pd.notna(event_date) and pd.notna(dob) else np.nan
            )
            snap.update(_snapshot_from_history(histories[fighter_id], event_date))
            snapshots.append(snap)

        for _, row in date_group.iterrows():
            _update_history(histories[_clean_id(row.get("fighter_id"))], row)

    out = pd.DataFrame(snapshots)
    if "history_max_event_date_before" in out.columns:
        out["history_max_event_date_before"] = pd.to_datetime(
            out["history_max_event_date_before"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")
        out["history_max_event_date_before"] = out["history_max_event_date_before"].replace("NaT", "")
    return out


def _numeric_value(row: pd.Series, column: str) -> float:
    return pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]


def build_model_ready_matchups(prefight_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    df = prefight_df.copy()
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")

    for fight_id, group in df.groupby("fight_id", sort=False):
        if len(group) != 2:
            continue
        fighters = group.sort_values("fighter_name").reset_index(drop=True)
        a = fighters.iloc[0]
        b = fighters.iloc[1]
        a_won = a.get("result") == "win"
        b_won = b.get("result") == "win"
        if a_won:
            target = 1
        elif b_won:
            target = 0
        else:
            target = np.nan

        row = {
            "fight_id": fight_id,
            "event_id": a.get("event_id"),
            "event_date": a.get("event_date"),
            "weight_class": a.get("weight_class"),
            "is_catchweight_or_openweight": a.get("is_catchweight_or_openweight"),
            "fighter_a_id": a.get("fighter_id"),
            "fighter_b_id": b.get("fighter_id"),
            "fighter_a": a.get("fighter_name"),
            "fighter_b": b.get("fighter_name"),
            "fighter_a_result": a.get("result"),
            "fighter_b_result": b.get("result"),
            "fighter_a_won": target,
            "method": a.get("method"),
            "round": a.get("round"),
            "time": a.get("time"),
            "stance_matchup": stance_matchup(a.get("stance"), b.get("stance")),
            "fighter_a_history_max_event_date_before": a.get("history_max_event_date_before"),
            "fighter_b_history_max_event_date_before": b.get("history_max_event_date_before"),
        }
        for col in DIFF_FEATURES:
            row[f"{col}_diff"] = _numeric_value(a, col) - _numeric_value(b, col)
            row[f"fighter_a_{col}"] = a.get(col)
            row[f"fighter_b_{col}"] = b.get(col)
        rows.append(row)

    return pd.DataFrame(rows)


def build_model_training_rows(model_matchups_df: pd.DataFrame, mirrored: bool = True) -> pd.DataFrame:
    if model_matchups_df.empty:
        return pd.DataFrame()
    if not mirrored:
        out = model_matchups_df.copy()
        out["row_direction"] = "a_minus_b"
        return out

    rows: list[dict[str, Any]] = []
    diff_cols = [col for col in model_matchups_df.columns if col.endswith("_diff")]
    a_cols = [col for col in model_matchups_df.columns if col.startswith("fighter_a_")]
    for _, row in model_matchups_df.iterrows():
        base = row.to_dict()
        base["row_direction"] = "a_minus_b"
        rows.append(base)

        mirror = row.to_dict()
        mirror["fighter_a"], mirror["fighter_b"] = row.get("fighter_b"), row.get("fighter_a")
        mirror["fighter_a_id"], mirror["fighter_b_id"] = row.get("fighter_b_id"), row.get("fighter_a_id")
        mirror["fighter_a_result"], mirror["fighter_b_result"] = (
            row.get("fighter_b_result"),
            row.get("fighter_a_result"),
        )
        if pd.isna(row.get("fighter_a_won")):
            mirror["fighter_a_won"] = np.nan
        else:
            mirror["fighter_a_won"] = 1 - int(row.get("fighter_a_won"))
        if "_vs_" in str(row.get("stance_matchup", "")):
            left, right = str(row.get("stance_matchup")).split("_vs_", 1)
            mirror["stance_matchup"] = f"{right}_vs_{left}"
        for col in diff_cols:
            mirror[col] = -row.get(col) if pd.notna(row.get(col)) else np.nan
        for a_col in a_cols:
            b_col = "fighter_b_" + a_col[len("fighter_a_") :]
            if b_col in model_matchups_df.columns:
                mirror[a_col] = row.get(b_col)
                mirror[b_col] = row.get(a_col)
        mirror["row_direction"] = "b_minus_a"
        rows.append(mirror)
    return pd.DataFrame(rows)


def build_training_dataset(
    fights_df: pd.DataFrame,
    fight_stats_df: pd.DataFrame,
    fighters_df: pd.DataFrame,
    mirrored: bool = True,
    drop_invalid_targets: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prefight = build_prefight_snapshots(fight_stats_df, fighters_df, fights_df)
    matchups = build_model_ready_matchups(prefight)
    training = build_model_training_rows(matchups, mirrored=mirrored)
    if drop_invalid_targets and not training.empty:
        training = training.dropna(subset=["fighter_a_won"]).copy()
        training["fighter_a_won"] = training["fighter_a_won"].astype(int)
    return prefight, matchups, training
