from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.features.build_mens_advanced_features import (
    DEBUTANT_NUMERIC,
    RATE_SPECS,
    SMOOTHED_DIFFS,
    _clean_id,
    _fighter_snapshot,
    _num,
    _rate_parts_from_row,
    _update_history,
    _update_rate_totals,
    _zero_history,
    _zero_rate_totals,
    build_elo_lookup,
    debutant_status,
    normalize_stats,
)


@dataclass
class LiveV2Context:
    stats: pd.DataFrame
    fights: pd.DataFrame
    elo_lookup: dict[tuple[str, str], float]
    date_groups: list[tuple[pd.Timestamp, pd.DataFrame]] = field(default_factory=list)
    cursor_index: int = 0
    histories: dict[str, dict[str, Any]] = field(default_factory=lambda: defaultdict(_zero_history))
    global_totals: dict[str, dict[str, float]] = field(default_factory=_zero_rate_totals)
    division_totals: dict[str, dict[str, dict[str, float]]] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveV2FeatureRows:
    forward: dict[str, Any]
    reverse: dict[str, Any]
    warnings: list[str]
    fighter_a_comparison: dict[str, Any] = field(default_factory=dict)
    fighter_b_comparison: dict[str, Any] = field(default_factory=dict)


def prepare_live_v2_context(fights: pd.DataFrame, fight_stats: pd.DataFrame) -> LiveV2Context:
    fights_copy = fights.copy()
    stats_copy = fight_stats.copy()
    fights_copy["event_date"] = pd.to_datetime(fights_copy["event_date"], errors="coerce")
    stats_copy["event_date"] = pd.to_datetime(stats_copy["event_date"], errors="coerce")
    normalized = normalize_stats(stats_copy, fights_copy)
    date_groups = [
        (pd.to_datetime(event_date), group.copy())
        for event_date, group in normalized.groupby("event_date", sort=True, dropna=False)
    ]
    return LiveV2Context(
        stats=normalized,
        fights=fights_copy,
        elo_lookup=build_elo_lookup(fights_copy),
        date_groups=date_groups,
    )


def _process_date_group(
    *,
    context: LiveV2Context,
    date_group: pd.DataFrame,
    histories: dict[str, dict[str, Any]],
    global_totals: dict[str, dict[str, float]],
    division_totals: dict[str, dict[str, dict[str, float]]],
) -> None:
    date_snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    for _, row in date_group.iterrows():
        fighter_id = _clean_id(row.get("fighter_id"))
        if not fighter_id:
            continue
        snap = _fighter_snapshot(row, histories[fighter_id], global_totals, division_totals)
        date_snapshots[(_clean_id(row.get("fight_id")), fighter_id)] = snap

    for _, row in date_group.iterrows():
        fighter_id = _clean_id(row.get("fighter_id"))
        opponent_id = _clean_id(row.get("opponent_id"))
        if not fighter_id:
            continue
        opponent_snap = date_snapshots.get((_clean_id(row.get("fight_id")), opponent_id), {})
        opponent_elo = context.elo_lookup.get((_clean_id(row.get("fight_id")), opponent_id), np.nan)
        _update_history(
            histories[fighter_id],
            row,
            opponent_elo_before=opponent_elo,
            opponent_win_pct_before=_num(opponent_snap.get("ufc_win_pct_before"), default=np.nan),
        )
        _update_rate_totals(row, global_totals, division_totals)


def _recompute_state_before(
    context: LiveV2Context,
    cutoff: pd.Timestamp,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, float]], dict[str, dict[str, dict[str, float]]]]:
    histories: dict[str, dict[str, Any]] = defaultdict(_zero_history)
    global_totals = _zero_rate_totals()
    division_totals: dict[str, dict[str, dict[str, float]]] = {}
    for event_date, date_group in context.date_groups:
        if pd.isna(event_date) or event_date >= cutoff:
            break
        _process_date_group(
            context=context,
            date_group=date_group,
            histories=histories,
            global_totals=global_totals,
            division_totals=division_totals,
        )
    return histories, global_totals, division_totals


def _state_before(
    context: LiveV2Context,
    fight_date: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, float]], dict[str, dict[str, dict[str, float]]]]:
    cutoff = pd.to_datetime(fight_date, errors="coerce")
    if pd.isna(cutoff):
        raise ValueError(f"Invalid fight date for v2 live features: {fight_date}")

    if context.cursor_index < len(context.date_groups):
        next_date = context.date_groups[context.cursor_index][0]
        if pd.notna(next_date) and cutoff < next_date:
            return _recompute_state_before(context, cutoff)

    while context.cursor_index < len(context.date_groups):
        event_date, date_group = context.date_groups[context.cursor_index]
        if pd.isna(event_date) or event_date >= cutoff:
            break
        _process_date_group(
            context=context,
            date_group=date_group,
            histories=context.histories,
            global_totals=context.global_totals,
            division_totals=context.division_totals,
        )
        context.cursor_index += 1

    return context.histories, context.global_totals, context.division_totals


def _prediction_snapshot(
    *,
    fighter: Any,
    fight_date: Any,
    weight_class: str,
    histories: dict[str, dict[str, Any]],
    global_totals: dict[str, dict[str, float]],
    division_totals: dict[str, dict[str, dict[str, float]]],
) -> dict[str, Any]:
    row = pd.Series(
        {
            "fight_id": "__prediction_matchup__",
            "fighter_id": fighter.fighter_id,
            "event_date": fight_date,
            "weight_class": weight_class,
        }
    )
    return _fighter_snapshot(row, histories[fighter.fighter_id], global_totals, division_totals)


def _pair_features(snapshot_a: dict[str, Any], snapshot_b: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for spec in RATE_SPECS:
        a_value = snapshot_a.get(spec.base)
        b_value = snapshot_b.get(spec.base)
        row[f"fighter_a_{spec.base}"] = a_value
        row[f"fighter_b_{spec.base}"] = b_value
        for suffix in ["support_before", "prior_rate_before", "prior_source_before", "prior_den_before"]:
            key = f"{spec.base}_{suffix}"
            row[f"fighter_a_{key}"] = snapshot_a.get(key)
            row[f"fighter_b_{key}"] = snapshot_b.get(key)
        row[f"{spec.base}_diff"] = _num(a_value, default=np.nan) - _num(b_value, default=np.nan)

    row["fighter_a_ufc_debut"] = snapshot_a.get("ufc_debut")
    row["fighter_b_ufc_debut"] = snapshot_b.get("ufc_debut")
    row["fighter_a_is_ufc_debut"] = int(_num(snapshot_a.get("ufc_debut"), default=0.0))
    row["fighter_b_is_ufc_debut"] = int(_num(snapshot_b.get("ufc_debut"), default=0.0))
    row["both_ufc_debut"] = int(
        row["fighter_a_is_ufc_debut"] == 1 and row["fighter_b_is_ufc_debut"] == 1
    )
    row["one_ufc_debut"] = int(
        row["fighter_a_is_ufc_debut"] + row["fighter_b_is_ufc_debut"] == 1
    )
    row["debutant_status"] = debutant_status(
        row["fighter_a_is_ufc_debut"],
        row["fighter_b_is_ufc_debut"],
    )
    return row


def _manual_profile_used(fighter: Any) -> bool:
    details = getattr(fighter, "details", {}) or {}
    return bool(details.get("manual_profile") or details.get("no_ufc_history"))


def _report_snapshot(snapshot: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    """Copy dated values and existing method counters for reporting only."""
    return {
        **snapshot,
        "finish_wins_before": int(history["finish_wins"]),
        "ko_tko_wins_before": int(history["ko_tko_wins"]),
        "submission_wins_before": int(history["sub_wins"]),
        "decision_wins_before": int(history["decision_wins"]),
        "finish_losses_before": int(history["finish_losses"]),
    }


def _warning_label(label: str, fighter: Any) -> str:
    name = getattr(fighter, "fighter_name", "") or getattr(fighter, "fighter_id", "")
    return f"{label} ({name})"


def _feature_warnings(
    *,
    fighter_a: Any,
    fighter_b: Any,
    snapshot_a: dict[str, Any],
    snapshot_b: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    for label, fighter, snapshot in [
        ("fighter A", fighter_a, snapshot_a),
        ("fighter B", fighter_b, snapshot_b),
    ]:
        display = _warning_label(label, fighter)
        if _manual_profile_used(fighter):
            warnings.append(
                f"{display} manual profile/no-history fallback used; v2 debut flags treat this fighter as UFC debut."
            )
        if int(_num(snapshot.get("ufc_debut"), default=0.0)) == 1:
            warnings.append(
                f"{display} has no prior UFC history before fight date; v2 smoothed rates use prior-only values."
            )
        for spec in RATE_SPECS:
            support = _num(snapshot.get(f"{spec.base}_support_before"), default=0.0)
            if support <= 0.0:
                warnings.append(
                    f"{display} {spec.base} has zero support before fight date; prior-only smoothing used."
                )
    return warnings


def build_live_v2_feature_rows(
    *,
    context: LiveV2Context,
    fighter_a: Any,
    fighter_b: Any,
    fight_date: Any,
    weight_class: str,
) -> LiveV2FeatureRows:
    parsed_date = pd.to_datetime(fight_date, errors="coerce")
    if pd.isna(parsed_date):
        raise ValueError(f"Invalid fight date for v2 live features: {fight_date}")

    histories, global_totals, division_totals = _state_before(context, parsed_date)
    snapshot_a = _prediction_snapshot(
        fighter=fighter_a,
        fight_date=parsed_date,
        weight_class=weight_class,
        histories=histories,
        global_totals=global_totals,
        division_totals=division_totals,
    )
    snapshot_b = _prediction_snapshot(
        fighter=fighter_b,
        fight_date=parsed_date,
        weight_class=weight_class,
        histories=histories,
        global_totals=global_totals,
        division_totals=division_totals,
    )
    forward = _pair_features(snapshot_a, snapshot_b)
    reverse = _pair_features(snapshot_b, snapshot_a)
    warnings = _feature_warnings(
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        snapshot_a=snapshot_a,
        snapshot_b=snapshot_b,
    )
    return LiveV2FeatureRows(
        forward=forward,
        reverse=reverse,
        warnings=warnings,
        fighter_a_comparison=_report_snapshot(snapshot_a, histories[fighter_a.fighter_id]),
        fighter_b_comparison=_report_snapshot(snapshot_b, histories[fighter_b.fighter_id]),
    )


SELECTED_LIVE_V2_FEATURES = tuple(SMOOTHED_DIFFS + DEBUTANT_NUMERIC + ["debutant_status"])
