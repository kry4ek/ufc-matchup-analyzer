from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from pathlib import Path

from src.features import mens_features as base_features
from src.features.build_mens_bayes_smoothing_candidate import (
    DIFF_TEMPLATE_SUFFIXES,
    RATE_FAMILIES,
    SIDE_TEMPLATE_SUFFIXES,
    RateFamily,
    build_strength_lookup,
    diff_col,
    side_col,
    strength_at,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V2_TRAINING_PATH = _PROJECT_ROOT / "data" / "processed" / "mens_training_rows_v2_advanced.csv"
from src.features.mens_live_v2_features import (
    LiveV2Context,
    build_live_v2_feature_rows,
    prepare_live_v2_context,
)


@dataclass(frozen=True)
class LiveV3FighterRef:
    fighter_id: str
    fighter_name: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class BaseRateContext:
    stats: pd.DataFrame
    date_groups: list[tuple[pd.Timestamp, pd.DataFrame]]
    id_to_name: dict[str, str]
    name_to_ids: dict[str, list[str]]
    cursor_index: int = 0
    histories: dict[str, dict[str, Any]] = field(default_factory=lambda: defaultdict(base_features._zero_history))


@dataclass
class LiveV3BayesContext:
    base_context: BaseRateContext
    v2_context: LiveV2Context
    strength_lookup: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveV3BayesFeatureRows:
    forward: dict[str, Any]
    reverse: dict[str, Any]
    warnings: list[str]
    leakage_audit: dict[str, Any]
    fighter_a_comparison: dict[str, Any] = field(default_factory=dict)
    fighter_b_comparison: dict[str, Any] = field(default_factory=dict)


def candidate_v3_bayes_columns() -> list[str]:
    columns: list[str] = []
    for family in RATE_FAMILIES:
        for side in ["a", "b"]:
            columns.extend(side_col(side, family, suffix) for suffix in SIDE_TEMPLATE_SUFFIXES)
        columns.extend(diff_col(family, suffix) for suffix in DIFF_TEMPLATE_SUFFIXES)
    return columns


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _clean_id(value: Any) -> str:
    return _clean_text(value)


def _name_key(value: Any) -> str:
    return " ".join(_clean_text(value).casefold().split())


def _num(value: Any, default: float = np.nan) -> float:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _clip_rate(value: Any) -> float:
    parsed = _num(value)
    if not _is_finite(parsed):
        return np.nan
    return float(min(max(parsed, 0.0), 1.0))


def _safe_smoothed(num: float, den: float, prior: float, strength: float) -> float:
    if not (_is_finite(den) and float(den) >= 0.0 and _is_finite(strength) and float(strength) > 0.0):
        return np.nan
    if not (_is_finite(num) and _is_finite(prior)):
        return np.nan
    value = (float(num) + float(strength) * float(prior)) / (float(den) + float(strength))
    return float(min(max(value, 0.0), 1.0))


def _support_scaled_strength(denominator: float, family: RateFamily) -> float:
    den = _num(denominator, default=0.0)
    if not _is_finite(den) or den < 0.0:
        den = 0.0
    current = float(family.current_men_v2_strength)
    minimum = min(20.0, max(10.0, current / 3.0))
    scaled = current * (current / (den + current))
    return float(min(max(scaled, minimum), current))


def _candidate_prior_source(denominator: float, current_source: Any) -> str:
    source = _clean_text(current_source).casefold()
    has_support = _is_finite(denominator) and float(denominator) > 0.0
    if has_support and source == "division":
        return "division"
    if has_support and source == "global":
        return "global"
    return "prior_only"


def _numeric_diff(a_value: Any, b_value: Any) -> float:
    a_num = _num(a_value)
    b_num = _num(b_value)
    if not (_is_finite(a_num) and _is_finite(b_num)):
        return np.nan
    return float(a_num - b_num)


def _numeric_min(a_value: Any, b_value: Any) -> float:
    values = [value for value in [_num(a_value), _num(b_value)] if _is_finite(value)]
    if not values:
        return np.nan
    return float(min(values))


def _identity_maps(stats: pd.DataFrame) -> tuple[dict[str, str], dict[str, list[str]]]:
    id_to_name: dict[str, str] = {}
    name_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for _, row in stats.iterrows():
        fighter_id = _clean_id(row.get("fighter_id"))
        fighter_name = _clean_text(row.get("fighter_name"))
        if not fighter_id:
            continue
        if fighter_name and fighter_id not in id_to_name:
            id_to_name[fighter_id] = fighter_name
        key = _name_key(fighter_name)
        if key:
            name_counts[key][fighter_id] += 1
    name_to_ids = {
        key: [fighter_id for fighter_id, _ in counts.most_common()]
        for key, counts in name_counts.items()
    }
    return id_to_name, name_to_ids


def _prepare_base_rate_context(fights: pd.DataFrame, fight_stats: pd.DataFrame) -> BaseRateContext:
    stats = base_features.add_opponent_stats(fight_stats.copy())
    stats["event_date"] = pd.to_datetime(stats["event_date"], errors="coerce")
    stats = stats[pd.notna(stats["event_date"])].copy()
    sort_columns = [column for column in ["event_date", "event_id", "fight_id", "fighter_id"] if column in stats.columns]
    stats = stats.sort_values(sort_columns, kind="mergesort").reset_index(drop=True)
    id_to_name, name_to_ids = _identity_maps(stats)
    date_groups = [
        (pd.to_datetime(event_date), group.copy())
        for event_date, group in stats.groupby("event_date", sort=True, dropna=False)
    ]
    return BaseRateContext(
        stats=stats,
        date_groups=date_groups,
        id_to_name=id_to_name,
        name_to_ids=name_to_ids,
    )


def prepare_live_v3_bayes_context(
    fights: pd.DataFrame,
    fight_stats: pd.DataFrame,
    v2_training_path: Path | str | None = None,
) -> LiveV3BayesContext:
    # The empirical-Bayes ("seb") strength estimation must use exactly the
    # same population records as the candidate training rebuild, so both
    # paths derive it from the v2 advanced training CSV (the rebuild's
    # input, regenerated before the v3 step in the derived rebuild chain).
    training_path = Path(v2_training_path) if v2_training_path else DEFAULT_V2_TRAINING_PATH
    if not training_path.exists():
        raise FileNotFoundError(
            f"v2 advanced training CSV required for v3 seb strength estimation: {training_path}"
        )
    strength_lookup = build_strength_lookup(pd.read_csv(training_path))
    return LiveV3BayesContext(
        base_context=_prepare_base_rate_context(fights, fight_stats),
        v2_context=prepare_live_v2_context(fights, fight_stats),
        strength_lookup=strength_lookup,
    )


def _process_base_date_group(
    date_group: pd.DataFrame,
    histories: dict[str, dict[str, Any]],
) -> None:
    for _, row in date_group.iterrows():
        fighter_id = _clean_id(row.get("fighter_id"))
        if not fighter_id:
            continue
        base_features._update_history(histories[fighter_id], row)


def _recompute_base_state_before(
    context: BaseRateContext,
    cutoff: pd.Timestamp,
) -> dict[str, dict[str, Any]]:
    histories: dict[str, dict[str, Any]] = defaultdict(base_features._zero_history)
    for event_date, date_group in context.date_groups:
        if pd.isna(event_date) or event_date >= cutoff:
            break
        _process_base_date_group(date_group, histories)
    return histories


def _base_state_before(context: BaseRateContext, fight_date: Any) -> dict[str, dict[str, Any]]:
    cutoff = pd.to_datetime(fight_date, errors="coerce")
    if pd.isna(cutoff):
        raise ValueError(f"Invalid fight date for v3 Bayesian live features: {fight_date}")

    if context.cursor_index < len(context.date_groups):
        next_date = context.date_groups[context.cursor_index][0]
        if pd.notna(next_date) and cutoff < next_date:
            return _recompute_base_state_before(context, cutoff)

    while context.cursor_index < len(context.date_groups):
        event_date, date_group = context.date_groups[context.cursor_index]
        if pd.isna(event_date) or event_date >= cutoff:
            break
        _process_base_date_group(date_group, context.histories)
        context.cursor_index += 1
    return context.histories


def _resolve_fighter(
    context: BaseRateContext,
    *,
    name: Any,
    fighter_id: Any = None,
    label: str,
) -> tuple[LiveV3FighterRef, list[str]]:
    warnings: list[str] = []
    clean_id = _clean_id(fighter_id)
    clean_name = _clean_text(name)
    if clean_id:
        display_name = clean_name or context.id_to_name.get(clean_id) or clean_id
        details: dict[str, Any] = {}
        if clean_id not in context.id_to_name:
            details = {"manual_profile": True, "no_ufc_history": True}
            warnings.append(f"{label} ({display_name}) ID was not found in raw men stats; using no-history prior-only features.")
        return LiveV3FighterRef(clean_id, display_name, details), warnings

    key = _name_key(clean_name)
    ids = context.name_to_ids.get(key, [])
    if len(ids) == 1:
        resolved_id = ids[0]
        return LiveV3FighterRef(resolved_id, clean_name or context.id_to_name.get(resolved_id) or resolved_id), warnings
    if len(ids) > 1:
        resolved_id = ids[0]
        warnings.append(
            f"{label} ({clean_name}) matched multiple raw men fighter IDs; using most frequent ID {resolved_id}."
        )
        return LiveV3FighterRef(resolved_id, clean_name or context.id_to_name.get(resolved_id) or resolved_id), warnings

    synthetic_id = f"__manual__:{key or label}"
    warnings.append(f"{label} ({clean_name or synthetic_id}) was not found in raw men stats; using no-history prior-only features.")
    return LiveV3FighterRef(
        synthetic_id,
        clean_name or synthetic_id,
        {"manual_profile": True, "no_ufc_history": True},
    ), warnings


def _base_snapshot(
    histories: dict[str, dict[str, Any]],
    fighter: LiveV3FighterRef,
    fight_date: pd.Timestamp,
) -> dict[str, Any]:
    return base_features._snapshot_from_history(histories[fighter.fighter_id], fight_date)


def _side_candidate_values(
    *,
    side: str,
    family: RateFamily,
    base_snapshot: dict[str, Any],
    v2_pair_row: dict[str, Any],
    seb_strength: float,
) -> dict[str, Any]:
    rate = _clip_rate(base_snapshot.get(family.prefight_rate_suffix))
    den = _num(v2_pair_row.get(f"fighter_{side}_{family.current_v2_base}_support_before"))
    den = max(float(den), 0.0) if _is_finite(den) else np.nan
    prior_raw = _clip_rate(v2_pair_row.get(f"fighter_{side}_{family.current_v2_base}_prior_rate_before"))
    prior = float(family.neutral_prior) if not _is_finite(prior_raw) else prior_raw
    prior_den = _num(v2_pair_row.get(f"fighter_{side}_{family.current_v2_base}_prior_den_before"), default=0.0)
    prior_den = max(float(prior_den), 0.0) if _is_finite(prior_den) else 0.0
    source = _candidate_prior_source(den, v2_pair_row.get(f"fighter_{side}_{family.current_v2_base}_prior_source_before"))

    if _is_finite(den) and den > 0.0:
        numerator_estimate = rate * den if _is_finite(rate) else np.nan
    else:
        numerator_estimate = 0.0
    if _is_finite(numerator_estimate):
        numerator_estimate = min(max(float(numerator_estimate), 0.0), den if _is_finite(den) else float(numerator_estimate))

    scaled_strength = _support_scaled_strength(den, family)
    values = {
        side_col(side, family, "prefight_rate_before"): rate,
        side_col(side, family, "raw_num_estimate_before"): numerator_estimate,
        side_col(side, family, "denominator_before"): den,
        side_col(side, family, "prior_mean_used"): prior,
        side_col(side, family, "global_prior_mean"): prior if source == "global" else np.nan,
        side_col(side, family, "division_prior_mean"): prior if source == "division" else np.nan,
        side_col(side, family, "prior_source"): source,
        side_col(side, family, "prior_denominator"): prior_den,
        side_col(side, family, "s20_women_style"): _safe_smoothed(numerator_estimate, den, prior, 20.0),
        side_col(side, family, "s50_moderate"): _safe_smoothed(numerator_estimate, den, prior, 50.0),
        side_col(side, family, "current_men_v2_strength"): _safe_smoothed(
            numerator_estimate,
            den,
            prior,
            family.current_men_v2_strength,
        ),
        side_col(side, family, "support_scaled"): _safe_smoothed(numerator_estimate, den, prior, scaled_strength),
        side_col(side, family, "support_scaled_strength"): scaled_strength,
        side_col(side, family, "seb"): _safe_smoothed(numerator_estimate, den, prior, seb_strength),
        side_col(side, family, "seb_strength"): float(seb_strength),
        side_col(side, family, "prior_only_flag"): int(source == "prior_only"),
        side_col(side, family, "low_support_flag"): int(_is_finite(den) and den < family.low_support_threshold),
    }
    return values


def _add_diff_values(row: dict[str, Any], family: RateFamily) -> None:
    for suffix in [
        "s20_women_style",
        "s50_moderate",
        "current_men_v2_strength",
        "support_scaled",
        "seb",
    ]:
        row[diff_col(family, f"{suffix}_diff")] = _numeric_diff(
            row.get(side_col("a", family, suffix)),
            row.get(side_col("b", family, suffix)),
        )

    a_den = row.get(side_col("a", family, "denominator_before"))
    b_den = row.get(side_col("b", family, "denominator_before"))
    a_low = int(_num(row.get(side_col("a", family, "low_support_flag")), default=0.0))
    b_low = int(_num(row.get(side_col("b", family, "low_support_flag")), default=0.0))
    a_prior_only = int(_num(row.get(side_col("a", family, "prior_only_flag")), default=0.0))
    b_prior_only = int(_num(row.get(side_col("b", family, "prior_only_flag")), default=0.0))

    row[diff_col(family, "support_diff")] = _numeric_diff(a_den, b_den)
    row[diff_col(family, "support_min")] = _numeric_min(a_den, b_den)
    row[diff_col(family, "support_asymmetry_abs")] = abs(_numeric_diff(a_den, b_den))
    row[diff_col(family, "either_low_support_flag")] = int(a_low == 1 or b_low == 1)
    row[diff_col(family, "both_low_support_flag")] = int(a_low == 1 and b_low == 1)
    row[diff_col(family, "either_prior_only_flag")] = int(a_prior_only == 1 or b_prior_only == 1)


def _candidate_pair_row(
    *,
    base_snapshot_a: dict[str, Any],
    base_snapshot_b: dict[str, Any],
    v2_pair_row: dict[str, Any],
    seb_strengths: dict[str, float],
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for family in RATE_FAMILIES:
        family_seb = seb_strengths[family.family]
        row.update(
            _side_candidate_values(
                side="a",
                family=family,
                base_snapshot=base_snapshot_a,
                v2_pair_row=v2_pair_row,
                seb_strength=family_seb,
            )
        )
        row.update(
            _side_candidate_values(
                side="b",
                family=family,
                base_snapshot=base_snapshot_b,
                v2_pair_row=v2_pair_row,
                seb_strength=family_seb,
            )
        )
        _add_diff_values(row, family)
    return row


def _history_warnings(
    *,
    fighter_a: LiveV3FighterRef,
    fighter_b: LiveV3FighterRef,
    snapshots: dict[str, dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    for label, fighter in [("fighter A", fighter_a), ("fighter B", fighter_b)]:
        snapshot = snapshots[label]
        fights_before = _num(snapshot.get("ufc_fights_before"), default=0.0)
        if fights_before <= 0.0:
            warnings.append(f"{label} ({fighter.fighter_name}) has no prior UFC history before fight date; v3 Bayesian values are prior-only where support is zero.")
    return warnings


def build_live_v3_bayes_feature_rows(
    *,
    context: LiveV3BayesContext,
    fighter_a: Any,
    fighter_b: Any,
    fight_date: Any,
    weight_class: str,
    fighter_a_id: Any = None,
    fighter_b_id: Any = None,
) -> LiveV3BayesFeatureRows:
    parsed_date = pd.to_datetime(fight_date, errors="coerce")
    if pd.isna(parsed_date):
        raise ValueError(f"Invalid fight date for v3 Bayesian live features: {fight_date}")

    ref_a, warnings_a = _resolve_fighter(
        context.base_context,
        name=fighter_a,
        fighter_id=fighter_a_id,
        label="fighter A",
    )
    ref_b, warnings_b = _resolve_fighter(
        context.base_context,
        name=fighter_b,
        fighter_id=fighter_b_id,
        label="fighter B",
    )

    histories = _base_state_before(context.base_context, parsed_date)
    base_snapshot_a = _base_snapshot(histories, ref_a, parsed_date)
    base_snapshot_b = _base_snapshot(histories, ref_b, parsed_date)

    v2_rows = build_live_v2_feature_rows(
        context=context.v2_context,
        fighter_a=ref_a,
        fighter_b=ref_b,
        fight_date=parsed_date,
        weight_class=weight_class,
    )
    if not context.strength_lookup:
        raise ValueError(
            "LiveV3BayesContext is missing the seb strength lookup; build it via prepare_live_v3_bayes_context()."
        )
    seb_strengths = {
        family.family: strength_at(context.strength_lookup[family.family], parsed_date)
        for family in RATE_FAMILIES
    }
    forward = _candidate_pair_row(
        base_snapshot_a=base_snapshot_a,
        base_snapshot_b=base_snapshot_b,
        v2_pair_row=v2_rows.forward,
        seb_strengths=seb_strengths,
    )
    reverse = _candidate_pair_row(
        base_snapshot_a=base_snapshot_b,
        base_snapshot_b=base_snapshot_a,
        v2_pair_row=v2_rows.reverse,
        seb_strengths=seb_strengths,
    )
    # Include the v2 live columns so v3 rows are a full feature superset:
    # the v3_bayes_smoothed model consumes both the v2 smoothed rates /
    # debutant flags and the v3 Bayesian candidate diffs.
    forward = {**v2_rows.forward, **forward}
    reverse = {**v2_rows.reverse, **reverse}

    max_history_dates = [
        pd.to_datetime(base_snapshot_a.get("history_max_event_date_before"), errors="coerce"),
        pd.to_datetime(base_snapshot_b.get("history_max_event_date_before"), errors="coerce"),
    ]
    finite_history_dates = [date for date in max_history_dates if pd.notna(date)]
    max_history_date = max(finite_history_dates) if finite_history_dates else pd.NaT
    leakage_audit = {
        "fight_date": parsed_date.strftime("%Y-%m-%d"),
        "fighter_a_base_history_max_event_date_before": None
        if pd.isna(max_history_dates[0])
        else max_history_dates[0].strftime("%Y-%m-%d"),
        "fighter_b_base_history_max_event_date_before": None
        if pd.isna(max_history_dates[1])
        else max_history_dates[1].strftime("%Y-%m-%d"),
        "max_base_history_event_date_before": None
        if pd.isna(max_history_date)
        else max_history_date.strftime("%Y-%m-%d"),
        "same_date_excluded": True,
        "target_fight_stats_excluded": bool(pd.isna(max_history_date) or max_history_date < parsed_date),
    }
    warnings = warnings_a + warnings_b + list(v2_rows.warnings)
    warnings.extend(
        _history_warnings(
            fighter_a=ref_a,
            fighter_b=ref_b,
            snapshots={"fighter A": base_snapshot_a, "fighter B": base_snapshot_b},
        )
    )
    return LiveV3BayesFeatureRows(
        forward=forward,
        reverse=reverse,
        warnings=warnings,
        leakage_audit=leakage_audit,
        fighter_a_comparison=dict(v2_rows.fighter_a_comparison),
        fighter_b_comparison=dict(v2_rows.fighter_b_comparison),
    )
