"""
predict_matchup_advanced.py

Version: v6 - live round-duration features and cleaner fallback.

Live UFC women's matchup predictor using the advanced feature dataset.

Recommended use from project root:

python predict_matchup_advanced.py ^
  --fighter-a "Valentina Shevchenko" ^
  --fighter-b "Manon Fiorot" ^
  --division "Women's Flyweight" ^
  --fight-date 2026-04-30

Optional odds comparison:

python predict_matchup_advanced.py ^
  --fighter-a "Valentina Shevchenko" ^
  --fighter-b "Manon Fiorot" ^
  --division "Women's Flyweight" ^
  --fight-date 2026-04-30 ^
  --fighter-a-odds 1.90 ^
  --fighter-b-odds 1.95

This script intentionally does NOT replace predict_matchup.py.
It trains on output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv
and computes live pre-fight snapshots from the fighter-fight stats file.

By default, the model is trained only on rows with event_date < --fight-date,
which avoids leakage when using the script for historical/as-of predictions.
"""

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


EXCLUDED_DIFF_FEATURES = {
    "fighter_a_won",
    "market_prob_diff",
    "market_no_vig_prob_diff",
    "opening_market_prob_diff",
    "closing_market_prob_diff",
    "odds_diff",
}

DIVISION_WEIGHTS_LBS = {
    "women's strawweight": 115,
    "strawweight": 115,
    "women's flyweight": 125,
    "flyweight": 125,
    "women's bantamweight": 135,
    "bantamweight": 135,
    "women's featherweight": 145,
    "featherweight": 145,
}


# --------------------------------------------------------------------------------------
# CLI / compatibility helpers
# --------------------------------------------------------------------------------------


def parse_args():
    p = argparse.ArgumentParser()

    p.add_argument("--fighter-a", required=True)
    p.add_argument("--fighter-b", required=True)
    p.add_argument("--division", required=True)

    p.add_argument(
        "--data",
        default="output_bayesian_prefight_smoothing_sig_fixed_v1/ufc_womens_model_training_rows_advanced_plus_bayes_prefight_smoothing_v1.csv",
        help="Advanced model-training CSV.",
    )

    p.add_argument(
        "--stats",
        default="output_td_repaired/ufc_womens_fighter_fight_stats_td_control_repaired.csv",
        help="Final repaired fighter-fight stats CSV.",
    )

    p.add_argument(
        "--snapshots",
        default="output_advanced_features/advanced_prefight_snapshots.csv",
        help="Optional advanced pre-fight snapshots CSV used only as a fallback for unknown feature names.",
    )

    p.add_argument("--profiles", default=None)
    p.add_argument("--fight-date", default=None)
    p.add_argument(
        "--allow-manual-profile-fallback",
        action="store_true",
        help=(
            "Allow fighters found only in --profiles to use the existing no-history "
            "snapshot path with explicit low-information warnings."
        ),
    )

    # Optional market odds. These are reporting-only and do not affect model features or predictions.
    p.add_argument("--fighter-a-odds", default=None)
    p.add_argument("--fighter-b-odds", default=None)
    p.add_argument(
        "--odds-format",
        default="auto",
        choices=["auto", "decimal", "american"],
        help=(
            "How to parse --fighter-a-odds and --fighter-b-odds. "
            "Default auto accepts decimal odds or signed American odds."
        ),
    )

    p.add_argument("--out", default=None)
    p.add_argument(
        "--json-out",
        default=None,
        help=(
            "Optional structured JSON summary output for batch/reporting tools. "
            "This does not change prediction calculations or console output."
        ),
    )

    p.add_argument(
        "--strict-features",
        action="store_true",
        help="Raise an error if any model diff feature cannot be computed live.",
    )

    p.add_argument(
        "--no-snapshot-fallback",
        action="store_true",
        help="Do not fill unknown live feature keys from advanced_prefight_snapshots.csv.",
    )

    p.add_argument(
        "--quiet-diagnostics",
        action="store_true",
        help="Suppress feature-coverage diagnostics.",
    )

    p.add_argument(
        "--show-fallback-keys",
        action="store_true",
        help="Print the exact live feature bases filled from advanced_prefight_snapshots.csv.",
    )

    p.add_argument(
        "--show-method-values",
        action="store_true",
        help="Print prior-fight method values and detected method categories for both fighters.",
    )

    p.add_argument(
        "--no-train-date-filter",
        action="store_true",
        help=(
            "Train on all rows in the advanced dataset instead of filtering training rows to "
            "event_date < fight_date. Leave this off for historical/as-of predictions to avoid leakage."
        ),
    )

    return p.parse_args()


def normalize_name_text(value):
    text = str(value).strip()

    # Repair common UTF-8-as-Latin-1 mojibake before stripping accents.
    for _ in range(3):
        repaired = None
        for encoding in ("latin1", "cp1252"):
            try:
                candidate = text.encode(encoding).decode("utf-8")
            except UnicodeError:
                continue
            if candidate != text:
                repaired = candidate
                break
        if repaired is None:
            break
        text = repaired

    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate({
        0x0141: "L",
        0x0142: "l",
        0x2018: "'",
        0x2019: "'",
        0x0060: "'",
    })
    text = text.lower()
    text = text.replace(".", "").replace(",", "")
    text = re.sub(r"[^a-z0-9\s'\-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_name(name):
    if pd.isna(name):
        return ""

    name = normalize_name_text(name)

    aliases = {
        "joanne calderwood": "joanne wood",
        "tecia torres": "tecia pennington",
        "jj aldrich": "jj aldrich",
    }

    return aliases.get(name, name)

    name = str(name).strip().lower()

    replacements = {
        "Ã©": "e", "Ã¨": "e", "Ãª": "e", "Ã«": "e",
        "Ã¡": "a", "Ã ": "a", "Ã£": "a", "Ã¢": "a", "Ã¤": "a",
        "Ã­": "i", "Ã¬": "i", "Ã®": "i", "Ã¯": "i",
        "Ã³": "o", "Ã²": "o", "Ã´": "o", "Ãµ": "o", "Ã¶": "o",
        "Ãº": "u", "Ã¹": "u", "Ã»": "u", "Ã¼": "u",
        "Ã§": "c", "Ã±": "n", "Å‚": "l",
        "â€™": "'", "â€˜": "'", "`": "'",
        ".": "", ",": "",
    }

    for old, new in replacements.items():
        name = name.replace(old, new)

    name = re.sub(r"[^a-z0-9\s'\-]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()

    aliases = {
        "joanne calderwood": "joanne wood",
        "tecia torres": "tecia pennington",
        "jessica andrade": "jessica andrade",
        "jessica andradÃ©": "jessica andrade",
        "jÃ©ssica andrade": "jessica andrade",
        "jj aldrich": "jj aldrich",
    }

    return aliases.get(name, name)


def normalize_division(division):
    if pd.isna(division):
        return ""
    return re.sub(r"\s+", " ", str(division).strip().lower())


def division_weight_lbs(division):
    return DIVISION_WEIGHTS_LBS.get(normalize_division(division), np.nan)


def make_onehot():
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=False)


def make_calibrated(estimator, method="sigmoid", cv=5):
    try:
        return CalibratedClassifierCV(estimator=estimator, method=method, cv=cv)
    except TypeError:
        return CalibratedClassifierCV(base_estimator=estimator, method=method, cv=cv)


def safe_div(num, den):
    if pd.isna(num) or pd.isna(den) or den == 0:
        return np.nan
    return num / den


def safe_numeric(value):
    return pd.to_numeric(value, errors="coerce")


def decimal_to_implied_prob(decimal_odds):
    if decimal_odds is None or pd.isna(decimal_odds) or decimal_odds <= 1:
        return np.nan
    return 1.0 / decimal_odds


def decimal_implied_prob(decimal_odds):
    return decimal_to_implied_prob(decimal_odds)


def american_to_decimal(value):
    try:
        american = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid American odds: {value!r}") from exc

    if not np.isfinite(american):
        raise ValueError(f"American odds must be finite: {value!r}")
    if american == 0:
        raise ValueError("American odds cannot be 0")
    if abs(american) < 100:
        raise ValueError("American odds must be >= +100 or <= -100")

    if american > 0:
        return 1.0 + american / 100.0
    return 1.0 + 100.0 / abs(american)


def _strip_odds_prefix(text):
    match = re.match(r"^(american|decimal)\s*:\s*(.+)$", text, flags=re.IGNORECASE)
    if not match:
        return None, text
    return match.group(1).lower(), match.group(2).strip()


def parse_odds_input(value, odds_format="auto"):
    if value is None:
        return None

    original = str(value).strip()
    if not original:
        return None

    odds_format = (odds_format or "auto").lower()
    if odds_format not in {"auto", "decimal", "american"}:
        raise ValueError(f"Unsupported odds format: {odds_format!r}")

    prefixed_format, cleaned = _strip_odds_prefix(original)
    if prefixed_format and odds_format != "auto" and prefixed_format != odds_format:
        raise ValueError(
            f"Odds input {original!r} specifies {prefixed_format}, "
            f"but --odds-format is {odds_format}."
        )

    effective_format = prefixed_format or odds_format
    if effective_format == "auto":
        signed = cleaned.startswith(("+", "-"))
        try:
            numeric = float(cleaned)
        except ValueError as exc:
            raise ValueError(f"could not parse odds value: {original!r}") from exc

        if signed:
            effective_format = "american"
        elif numeric > 100 or numeric <= -100:
            effective_format = "american"
        elif numeric > 1.0:
            effective_format = "decimal"
        else:
            raise ValueError(
                f"decimal odds must be > 1.0 unless American odds are signed: {original!r}"
            )

    if effective_format == "decimal":
        try:
            decimal_odds = float(cleaned)
        except ValueError as exc:
            raise ValueError(f"could not parse decimal odds: {original!r}") from exc
        if not np.isfinite(decimal_odds) or decimal_odds <= 1.0:
            raise ValueError(f"decimal odds must be > 1.0: {original!r}")
    else:
        decimal_odds = american_to_decimal(cleaned)

    return {
        "input": original,
        "normalized_input": cleaned,
        "format_detected": effective_format,
        "decimal_odds": float(decimal_odds),
        "implied_probability": float(decimal_to_implied_prob(decimal_odds)),
    }


def _market_comparison_empty(warning=None):
    return {
        "market_comparison_available": False,
        "market_comparison_warning": warning,
        "fighter_a_odds_input": None,
        "fighter_b_odds_input": None,
        "fighter_a_odds_format_detected": None,
        "fighter_b_odds_format_detected": None,
        "fighter_a_decimal_odds": None,
        "fighter_b_decimal_odds": None,
        "fighter_a_implied_probability": None,
        "fighter_b_implied_probability": None,
        "fighter_a_no_vig_market_probability": None,
        "fighter_b_no_vig_market_probability": None,
        "fighter_a_model_minus_market": None,
        "fighter_b_model_minus_market": None,
    }


def _market_edge_empty():
    return {
        "market_edge_available": False,
        "market_edge_label": None,
        "market_edge_confidence": None,
        "market_edge_fighter": None,
        "market_edge_side": None,
        "market_edge_probability_delta": None,
        "market_edge_abs_delta": None,
        "market_edge_review_priority": None,
        "market_edge_warning": None,
        "market_edge_note": None,
        "market_pick_favorite": None,
        "model_pick_differs_from_market_favorite": None,
    }


def normalize_market_odds(fighter_a_odds, fighter_b_odds, odds_format="auto"):
    a_supplied = fighter_a_odds is not None and str(fighter_a_odds).strip() != ""
    b_supplied = fighter_b_odds is not None and str(fighter_b_odds).strip() != ""

    if not a_supplied and not b_supplied:
        return _market_comparison_empty()

    if a_supplied != b_supplied:
        result = _market_comparison_empty(
            "Both fighter odds are required for market comparison."
        )
        result["fighter_a_odds_input"] = str(fighter_a_odds).strip() if a_supplied else None
        result["fighter_b_odds_input"] = str(fighter_b_odds).strip() if b_supplied else None
        return result

    a = parse_odds_input(fighter_a_odds, odds_format=odds_format)
    b = parse_odds_input(fighter_b_odds, odds_format=odds_format)
    a_imp = a["implied_probability"]
    b_imp = b["implied_probability"]
    overround = a_imp + b_imp
    if pd.isna(overround) or overround <= 0:
        result = _market_comparison_empty(
            "Could not compute no-vig probabilities from supplied odds."
        )
    else:
        result = _market_comparison_empty()
        result["market_comparison_available"] = True
        result["fighter_a_no_vig_market_probability"] = float(a_imp / overround)
        result["fighter_b_no_vig_market_probability"] = float(b_imp / overround)

    result.update(
        {
            "fighter_a_odds_input": a["input"],
            "fighter_b_odds_input": b["input"],
            "fighter_a_odds_format_detected": a["format_detected"],
            "fighter_b_odds_format_detected": b["format_detected"],
            "fighter_a_decimal_odds": a["decimal_odds"],
            "fighter_b_decimal_odds": b["decimal_odds"],
            "fighter_a_implied_probability": a_imp,
            "fighter_b_implied_probability": b_imp,
        }
    )
    return result


def add_model_market_edges(market_comparison, primary_prob_a):
    out = dict(market_comparison or _market_comparison_empty())
    if out.get("market_comparison_available"):
        a_no_vig = out["fighter_a_no_vig_market_probability"]
        b_no_vig = out["fighter_b_no_vig_market_probability"]
        out["fighter_a_model_minus_market"] = float(primary_prob_a - a_no_vig)
        out["fighter_b_model_minus_market"] = float((1.0 - primary_prob_a) - b_no_vig)
    return out


def _edge_bucket(abs_delta):
    if pd.isna(abs_delta):
        return "unavailable"
    if abs_delta < 0.03:
        return "no_clear_edge"
    if abs_delta < 0.07:
        return "small_edge"
    if abs_delta < 0.12:
        return "notable_edge"
    return "large_edge"


def compute_market_edge_interpretation(
    fighter_a,
    fighter_b,
    fighter_a_model_probability,
    fighter_b_model_probability,
    fighter_a_no_vig_market_probability,
    fighter_b_no_vig_market_probability,
    fighter_a_model_minus_market,
    fighter_b_model_minus_market,
    predicted_winner,
    reliability_label,
    reliability_score,
    model_spread,
    direction_disagreement,
    model_vote=None,
):
    out = _market_edge_empty()
    required_values = [
        fighter_a_model_probability,
        fighter_b_model_probability,
        fighter_a_no_vig_market_probability,
        fighter_b_no_vig_market_probability,
        fighter_a_model_minus_market,
        fighter_b_model_minus_market,
    ]
    if any(pd.isna(value) for value in required_values):
        return out

    a_market = float(fighter_a_no_vig_market_probability)
    b_market = float(fighter_b_no_vig_market_probability)
    a_delta = float(fighter_a_model_minus_market)
    b_delta = float(fighter_b_model_minus_market)

    if a_market > b_market:
        market_favorite = fighter_a
    elif b_market > a_market:
        market_favorite = fighter_b
    else:
        market_favorite = "even_market"

    predicted_winner = str(predicted_winner or "").strip()
    if predicted_winner == fighter_a:
        edge_fighter = fighter_a
        edge_delta = a_delta
        edge_side = "predicted_winner"
    elif predicted_winner == fighter_b:
        edge_fighter = fighter_b
        edge_delta = b_delta
        edge_side = "predicted_winner"
    elif abs(a_delta) >= abs(b_delta):
        edge_fighter = fighter_a
        edge_delta = a_delta
        edge_side = "strongest_abs_edge"
    else:
        edge_fighter = fighter_b
        edge_delta = b_delta
        edge_side = "strongest_abs_edge"

    abs_delta = abs(edge_delta)
    edge_bucket = _edge_bucket(abs_delta)
    model_pick_differs = bool(
        predicted_winner
        and market_favorite not in {None, "even_market"}
        and predicted_winner != market_favorite
    )

    reliability_label = str(reliability_label or "").strip()
    label = edge_bucket
    confidence = "weak"
    review_priority = "review"
    warning = None
    note_parts = []

    if edge_bucket == "no_clear_edge":
        label = "no_clear_edge"
        confidence = "weak"
        review_priority = "stable"
        note_parts.append("Model-market gap is below 3%, so there is no clear model-market signal.")
    elif edge_delta <= 0:
        label = "market_agrees_or_model_cautious"
        confidence = "weak"
        review_priority = "review"
        note_parts.append("Model does not show positive edge on the predicted winner.")
    elif edge_bucket == "small_edge":
        label = "small_edge"
        confidence = "weak"
        review_priority = "review"
        note_parts.append("Model-market gap is small.")
    elif reliability_label == "High":
        label = "model_value_signal"
        confidence = "stronger"
        review_priority = "review"
        note_parts.append(
            "Model is meaningfully above the no-vig market on the predicted winner, and reliability is High."
        )
    elif reliability_label == "Medium":
        label = "model_value_signal"
        confidence = "moderate"
        review_priority = "review"
        note_parts.append(
            "Model is above market, but reliability is Medium; review matchup context."
        )
    elif reliability_label == "Low":
        label = "speculative_edge_low_reliability"
        confidence = "weak"
        review_priority = "manual_review"
        warning = (
            "Large model-market gap, but reliability is Low; treat as speculative and manually review."
        )
        note_parts.append(
            "The model is meaningfully above the no-vig market, but reliability is Low. "
            "Treat this as a manual-review signal, not a betting recommendation."
        )
    else:
        label = "model_market_signal_review"
        confidence = "weak"
        review_priority = "review"
        note_parts.append("Model is above market, but reliability is unavailable; review manually.")

    if model_pick_differs:
        note_parts.append("Model pick differs from market favorite.")
        if warning:
            warning = warning + " Model pick differs from market favorite."
        else:
            warning = "Model pick differs from market favorite."

    out.update(
        {
            "market_edge_available": True,
            "market_edge_label": label,
            "market_edge_confidence": confidence,
            "market_edge_fighter": edge_fighter,
            "market_edge_side": edge_side,
            "market_edge_probability_delta": float(edge_delta),
            "market_edge_abs_delta": float(abs_delta),
            "market_edge_review_priority": review_priority,
            "market_edge_warning": warning,
            "market_edge_note": " ".join(note_parts),
            "market_pick_favorite": market_favorite,
            "model_pick_differs_from_market_favorite": model_pick_differs,
        }
    )
    return out


def market_edge_label_display(label):
    labels = {
        "no_clear_edge": "No clear edge",
        "small_edge": "Small edge",
        "notable_edge": "Notable edge",
        "large_edge": "Large edge",
        "model_value_signal": "Possible value signal",
        "speculative_edge_low_reliability": "Speculative edge - low reliability",
        "market_agrees_or_model_cautious": "Market agrees or model cautious",
        "model_market_signal_review": "Model-market signal - review",
    }
    return labels.get(str(label or ""), str(label or "Unavailable").replace("_", " ").title())


def format_odds_input_for_market(parsed_input, detected_format, decimal_odds):
    if detected_format == "american":
        return f"{parsed_input} American -> decimal {decimal_odds:.3f}"
    return f"decimal {decimal_odds:.3f}"


def format_prob(x):
    if pd.isna(x):
        return "N/A"
    return f"{x * 100:.1f}%"


def canonicalize_fighter_name(requested, known_names):
    req_norm = normalize_name(requested)

    norm_to_original = {}
    for name in known_names:
        norm_to_original[normalize_name(name)] = name

    if req_norm in norm_to_original:
        return norm_to_original[req_norm]

    req_tokens = set(req_norm.split())
    if not req_tokens:
        raise ValueError(f"Could not find fighter: {requested}")

    token_matches = []
    contains_matches = []
    for name in known_names:
        norm = normalize_name(name)
        tokens = set(norm.split())
        if len(req_tokens) == 1 and next(iter(req_tokens)) in tokens:
            token_matches.append(name)
        elif len(req_tokens) > 1 and req_tokens.issubset(tokens):
            contains_matches.append(name)

    if len(req_tokens) == 1:
        if len(token_matches) == 1:
            return token_matches[0]
        if len(token_matches) > 1:
            sample = ", ".join(sorted(token_matches)[:12])
            more = "..." if len(token_matches) > 12 else ""
            raise ValueError(
                f"Ambiguous fighter name: {requested!r}. "
                f"Possible matches: {sample}{more}"
            )

    if len(contains_matches) == 1:
        return contains_matches[0]
    if len(contains_matches) > 1:
        sample = ", ".join(sorted(contains_matches)[:12])
        more = "..." if len(contains_matches) > 12 else ""
        raise ValueError(
            f"Ambiguous fighter name: {requested!r}. "
            f"Possible matches: {sample}{more}"
        )

    scored = []
    for name in known_names:
        tokens = set(normalize_name(name).split())
        if not tokens:
            continue
        overlap = len(req_tokens & tokens)
        if overlap:
            scored.append((overlap / len(req_tokens | tokens), overlap, name))

    scored.sort(reverse=True)
    if scored and scored[0][1] >= max(2, len(req_tokens) - 1):
        top_score = scored[0][0]
        top = [name for score, _, name in scored if abs(score - top_score) < 1e-12]
        if len(top) == 1:
            return top[0]

    raise ValueError(f"Could not find fighter: {requested}")


# --------------------------------------------------------------------------------------
# Loading profiles / snapshots
# --------------------------------------------------------------------------------------


def find_profile_file(profiles_arg):
    if profiles_arg:
        path = Path(profiles_arg)
        if path.exists():
            return path
        return None

    candidates = [
        Path("output_advanced_features/ufc_womens_fighter_profiles.csv"),
        Path("output_td_repaired/ufc_womens_fighter_profiles.csv"),
        Path("output_quality_fixed/ufc_womens_fighter_profiles.csv"),
        Path("output_fixed/ufc_womens_fighter_profiles.csv"),
        Path("output/ufc_womens_fighter_profiles.csv"),
    ]

    for path in candidates:
        if path.exists():
            return path

    return None


def first_existing_column(df, candidates):
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def profile_name_columns(df):
    return [
        column
        for column in ["fighter", "fighter_name", "name", "canonical_name", "fighter_display_name"]
        if column in df.columns
    ]


def profile_row_names(row, columns):
    names = []
    for column in columns:
        value = row.get(column)
        if pd.isna(value):
            continue
        text = str(value).strip()
        if text:
            names.append(text)
    return names


def load_manual_profile_names(profile_path):
    if profile_path is None or not Path(profile_path).exists():
        return {}

    profiles = pd.read_csv(profile_path)
    if "route_model" in profiles.columns:
        profiles = profiles[
            profiles["route_model"].fillna("").astype(str).str.strip().str.lower().isin({"", "women", "woman", "female", "w"})
        ].copy()

    columns = profile_name_columns(profiles)
    if not columns:
        return {}

    names = {}
    for _, row in profiles.iterrows():
        canonical = row.get("canonical_name")
        canonical = "" if pd.isna(canonical) else str(canonical).strip()
        for name in profile_row_names(row, columns):
            display = canonical or name
            names[normalize_name(name)] = display
            names[normalize_name(display)] = display
    return {key: value for key, value in names.items() if key and value}


def load_profiles(profile_path, train_df, snapshots_df=None):
    profile_map = {}

    # Fallback profile info from model-training rows.
    for side in ["a", "b"]:
        name_col = f"fighter_{side}"

        if name_col not in train_df.columns:
            continue

        for _, r in train_df.sort_values("event_date").iterrows():
            name = r.get(name_col)

            if pd.isna(name):
                continue

            key = normalize_name(name)
            profile_map.setdefault(key, {})

            for base in ["height_cm", "reach_cm", "age_at_fight", "stance"]:
                col = f"fighter_{side}_{base}"
                if col in train_df.columns and pd.notna(r.get(col)):
                    profile_map[key][base] = r.get(col)

            age_col = f"fighter_{side}_age_at_fight"
            if age_col in train_df.columns and pd.notna(r.get(age_col)):
                profile_map[key]["latest_age_at_fight"] = r.get(age_col)
                profile_map[key]["latest_age_event_date"] = r.get("event_date")

    # Fallback profile info from advanced snapshots, if available.
    if snapshots_df is not None and not snapshots_df.empty:
        name_col = first_existing_column(snapshots_df, ["fighter", "fighter_name", "name"])
        if name_col is not None:
            temp = snapshots_df.copy()
            if "event_date" in temp.columns:
                temp["event_date"] = pd.to_datetime(temp["event_date"], errors="coerce")
                temp = temp.sort_values("event_date")
            for _, r in temp.iterrows():
                name = r.get(name_col)
                if pd.isna(name):
                    continue
                key = normalize_name(name)
                profile_map.setdefault(key, {})
                for base in ["height_cm", "reach_cm", "stance"]:
                    if base in temp.columns and pd.notna(r.get(base)):
                        profile_map[key][base] = r.get(base)
                if "age_at_fight" in temp.columns and pd.notna(r.get("age_at_fight")):
                    profile_map[key]["latest_age_at_fight"] = r.get("age_at_fight")
                    profile_map[key]["latest_age_event_date"] = r.get("event_date")

    if profile_path is None or not Path(profile_path).exists():
        return profile_map

    profiles = pd.read_csv(profile_path)

    if "route_model" in profiles.columns:
        profiles = profiles[
            profiles["route_model"].fillna("").astype(str).str.strip().str.lower().isin({"", "women", "woman", "female", "w"})
        ].copy()

    name_cols = profile_name_columns(profiles)
    if not name_cols:
        return profile_map

    for _, r in profiles.iterrows():
        names = profile_row_names(r, name_cols)
        if not names:
            continue

        profile_values = {}
        for candidate in ["height_cm", "height"]:
            if candidate in profiles.columns and pd.notna(r.get(candidate)):
                profile_values["height_cm"] = r.get(candidate)
                break

        for candidate in ["reach_cm", "reach"]:
            if candidate in profiles.columns and pd.notna(r.get(candidate)):
                profile_values["reach_cm"] = r.get(candidate)
                break

        if "stance" in profiles.columns and pd.notna(r.get("stance")):
            stance = str(r.get("stance")).strip()
            profile_values["stance"] = stance if stance else "Unknown"

        for candidate in ["dob", "date_of_birth", "birth_date"]:
            if candidate in profiles.columns and pd.notna(r.get(candidate)):
                profile_values["dob"] = r.get(candidate)
                break

        for name in names:
            key = normalize_name(name)
            if not key:
                continue
            profile_map.setdefault(key, {})
            profile_map[key].update(profile_values)

    return profile_map


def load_snapshots(path):
    path = Path(path) if path else None
    if path is None or not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)
    if "event_date" in df.columns:
        df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    return df


def latest_snapshot_fallback(snapshots_df, fighter, cutoff_date):
    if snapshots_df is None or snapshots_df.empty:
        return {}

    name_col = first_existing_column(snapshots_df, ["fighter", "fighter_name", "name"])
    if name_col is None:
        return {}

    temp = snapshots_df.copy()
    temp["_norm_fighter"] = temp[name_col].map(normalize_name)
    temp = temp[temp["_norm_fighter"] == normalize_name(fighter)].copy()

    if temp.empty:
        return {}

    if "event_date" in temp.columns:
        temp = temp[pd.to_datetime(temp["event_date"], errors="coerce") < cutoff_date]
        temp = temp.sort_values("event_date")

    if temp.empty:
        return {}

    row = temp.iloc[-1].to_dict()
    row.pop("_norm_fighter", None)
    return row


def apply_snapshot_fallback(snapshot, fallback_row, required_bases):
    """
    Fill only truly absent keys from advanced_prefight_snapshots.csv.

    Important: do not overwrite a live-computed key just because its value is NaN.
    In several features, NaN is meaningful. Example: if a fighter has no prior UFC loss,
    days_since_last_loss should stay NaN rather than being backfilled from a stale snapshot.
    """
    if not fallback_row:
        return []

    filled = []
    for base in required_bases:
        if base in snapshot:
            continue

        candidates = [
            base,
            f"fighter_{base}",
            f"{base}_before",
            base.replace("ko_", "ko_tko_"),
            base.replace("ko_tko_", "ko_"),
        ]

        for candidate in candidates:
            if candidate in fallback_row and pd.notna(fallback_row.get(candidate)):
                snapshot[base] = fallback_row.get(candidate)
                filled.append(base)
                break

    return filled


# --------------------------------------------------------------------------------------
# Data cleaning / per-fight derived data
# --------------------------------------------------------------------------------------


def compute_age(profile, fight_date):
    dob = profile.get("dob")

    if dob is not None and pd.notna(dob):
        dob = pd.to_datetime(dob, errors="coerce")
        if pd.notna(dob):
            return (fight_date - dob).days / 365.25

    latest_age = profile.get("latest_age_at_fight")
    latest_date = profile.get("latest_age_event_date")

    if latest_age is not None and latest_date is not None and pd.notna(latest_age):
        latest_date = pd.to_datetime(latest_date, errors="coerce")
        if pd.notna(latest_date):
            return float(latest_age) + ((fight_date - latest_date).days / 365.25)

    return np.nan



def parse_round_count_from_text(value):
    """Return a scheduled round count from common fight-format text, or NaN."""
    if pd.isna(value):
        return np.nan
    text = str(value).strip().lower()
    if not text or text in {"nan", "none", "null"}:
        return np.nan
    patterns = [r"\b([35])\s*(?:rnd|round|rounds)\b", r"\b(?:rnd|round|rounds)\s*([35])\b"]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return np.nan
    if text in {"3", "5"}:
        return float(text)
    return np.nan


def add_round_context(stats):
    """Add per-fight round context for scheduled-five and late-round history."""
    stats = stats.copy()
    scheduled_rounds = pd.Series(np.nan, index=stats.index, dtype="float64")
    scheduled_candidates = [
        "scheduled_rounds", "scheduled_round_count", "fight_scheduled_rounds",
        "number_of_scheduled_rounds", "num_scheduled_rounds", "rounds_scheduled",
        "total_rounds", "num_rounds", "number_of_rounds",
    ]
    for col in scheduled_candidates:
        if col in stats.columns:
            scheduled_rounds = scheduled_rounds.fillna(pd.to_numeric(stats[col], errors="coerce"))
    format_candidates = [
        "fight_format", "format", "time_format", "bout_format", "round_format",
        "scheduled_time", "scheduled_duration",
    ]
    for col in format_candidates:
        if col in stats.columns:
            scheduled_rounds = scheduled_rounds.fillna(stats[col].map(parse_round_count_from_text))
    elapsed = pd.to_numeric(stats.get("elapsed_seconds", np.nan), errors="coerce")
    scheduled_rounds = scheduled_rounds.mask(scheduled_rounds.isna() & (elapsed > 900), 5.0)

    final_round = pd.Series(np.nan, index=stats.index, dtype="float64")
    final_round_candidates = ["round", "ending_round", "end_round", "last_round", "finish_round", "final_round"]
    for col in final_round_candidates:
        if col in stats.columns:
            final_round = final_round.fillna(pd.to_numeric(stats[col], errors="coerce"))
    inferred_final_round = np.ceil(elapsed / 300.0)
    inferred_final_round = pd.Series(inferred_final_round, index=stats.index).where(elapsed > 0, np.nan)
    final_round = final_round.fillna(inferred_final_round)

    stats["live_scheduled_rounds"] = scheduled_rounds
    stats["live_final_round"] = final_round
    stats["is_scheduled_five_rounds"] = np.where(scheduled_rounds.notna(), (scheduled_rounds >= 5).astype(int), np.nan)
    stats["reached_late_round"] = np.where(final_round.notna(), (final_round >= 4).astype(int), np.nan)
    return stats

def classify_methods(stats):
    """
    Add robust method-category flags.

    UFCStats-style data often stores decisions as abbreviations such as U-DEC, S-DEC,
    M-DEC, or DEC rather than the full word "Decision". Earlier versions missed those
    abbreviations, causing decision wins to be counted as finishes. This classifier
    normalizes punctuation and recognizes both full method names and common UFCStats
    abbreviations.
    """
    stats = stats.copy()

    method_candidates = [
        "method",
        "result_method",
        "fight_method",
        "finish_method",
        "win_method",
        "outcome_method",
        "result_type",
        "finish_type",
        "method_detail",
    ]
    method_cols = [c for c in method_candidates if c in stats.columns]

    if method_cols:
        method_text = (
            stats[method_cols]
            .fillna("")
            .astype(str)
            .agg(" | ".join, axis=1)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )
    else:
        method_text = pd.Series("", index=stats.index)

    method_lower = method_text.str.lower().str.strip()
    method_norm = (
        method_lower
        .str.replace(r"[^a-z0-9]+", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    method_known = method_norm.str.len().gt(0) & ~method_norm.isin({"nan", "none", "null"})

    # Decisions: UFCStats commonly uses U-DEC, S-DEC, M-DEC, or DEC.
    is_decision = (
        method_norm.str.contains(r"\bdecision\b", regex=True)
        | method_norm.str.contains(r"\bdec\b", regex=True)
        | method_norm.str.contains(r"\b(?:u|s|m)\s*dec\b", regex=True)
        | method_norm.str.contains(r"\bunanimous\b", regex=True)
        | method_norm.str.contains(r"\bsplit\b", regex=True)
        | method_norm.str.contains(r"\bmajority\b", regex=True)
    )

    # Submissions: include common text plus common submission names when method_detail is present.
    is_submission = (
        method_norm.str.contains(r"\bsubmission\b", regex=True)
        | method_norm.str.contains(r"\bsub\b", regex=True)
        | method_norm.str.contains(
            r"armbar|choke|triangle|guillotine|kimura|keylock|kneebar|heel hook|twister|d arce|darce|anaconda|rear naked",
            regex=True,
        )
    )

    # Knockouts / technical knockouts.
    is_ko_tko = (
        method_norm.str.contains(r"\bko\b", regex=True)
        | method_norm.str.contains(r"\btko\b", regex=True)
        | method_norm.str.contains(r"knockout|doctor stoppage|corner stoppage", regex=True)
    )

    no_contest_like = (
        method_norm.str.contains(r"overturned|no contest", regex=True)
        | method_norm.str.contains(r"\bnc\b", regex=True)
        | method_norm.str.contains(r"\bdraw\b", regex=True)
    )

    # For model features, count finish as an explicit KO/TKO or submission, not merely
    # "anything that is not a decision". This avoids false finishes from DQ/NC/unknown text.
    is_finish = is_ko_tko | is_submission

    stats["_method_text"] = method_text
    stats["_method_normalized"] = method_norm
    stats["_method_source_columns"] = ", ".join(method_cols) if method_cols else "NONE"
    stats["method_known"] = method_known.astype(int)

    valid_method = method_known & ~no_contest_like
    stats["is_decision"] = np.where(valid_method, is_decision.astype(int), np.nan)
    stats["is_submission"] = np.where(valid_method, is_submission.astype(int), np.nan)
    stats["is_ko_tko"] = np.where(valid_method, is_ko_tko.astype(int), np.nan)
    stats["is_finish"] = np.where(valid_method, is_finish.astype(int), np.nan)

    return stats

def add_pair_opponent_fields(stats):
    stats = stats.copy()

    if "opponent" not in stats.columns:
        stats["opponent"] = np.nan
        for fight_id, g in stats.groupby("fight_id"):
            if len(g) == 2:
                i1, i2 = list(g.index)
                stats.at[i1, "opponent"] = stats.at[i2, "fighter"]
                stats.at[i2, "opponent"] = stats.at[i1, "fighter"]

    if "opponent_control_time_seconds" not in stats.columns:
        stats["opponent_control_time_seconds"] = np.nan

    # If opponent control is missing, derive it from the opponent's row in the same fight.
    needs_fill = stats["opponent_control_time_seconds"].isna()
    if needs_fill.any():
        for fight_id, g in stats.groupby("fight_id"):
            if len(g) == 2:
                i1, i2 = list(g.index)
                if pd.isna(stats.at[i1, "opponent_control_time_seconds"]):
                    stats.at[i1, "opponent_control_time_seconds"] = stats.at[i2, "control_time_seconds"]
                if pd.isna(stats.at[i2, "opponent_control_time_seconds"]):
                    stats.at[i2, "opponent_control_time_seconds"] = stats.at[i1, "control_time_seconds"]

    stats["opponent_control_time_seconds"] = pd.to_numeric(
        stats["opponent_control_time_seconds"], errors="coerce"
    ).fillna(0)

    return stats


def clean_numeric_columns(stats):
    stats = stats.copy()

    required_text_cols = ["fighter", "fight_id", "division"]
    for col in required_text_cols:
        if col not in stats.columns:
            stats[col] = ""

    stats["event_date"] = pd.to_datetime(stats["event_date"], errors="coerce")

    # Fallback significant-strike totals if total columns are absent.
    if "sig_str_landed_total" not in stats.columns:
        stats["sig_str_landed_total"] = (
            pd.to_numeric(stats.get("head_sig_landed", 0), errors="coerce").fillna(0)
            + pd.to_numeric(stats.get("body_sig_landed", 0), errors="coerce").fillna(0)
            + pd.to_numeric(stats.get("leg_sig_landed", 0), errors="coerce").fillna(0)
        )

    if "sig_str_attempted_total" not in stats.columns:
        stats["sig_str_attempted_total"] = (
            pd.to_numeric(stats.get("head_sig_attempted", 0), errors="coerce").fillna(0)
            + pd.to_numeric(stats.get("body_sig_attempted", 0), errors="coerce").fillna(0)
            + pd.to_numeric(stats.get("leg_sig_attempted", 0), errors="coerce").fillna(0)
        )

    if "opponent_sig_str_landed_total" not in stats.columns:
        stats["opponent_sig_str_landed_total"] = (
            pd.to_numeric(stats.get("opponent_head_sig_landed", 0), errors="coerce").fillna(0)
            + pd.to_numeric(stats.get("opponent_body_sig_landed", 0), errors="coerce").fillna(0)
            + pd.to_numeric(stats.get("opponent_leg_sig_landed", 0), errors="coerce").fillna(0)
        )

    if "opponent_sig_str_attempted_total" not in stats.columns:
        stats["opponent_sig_str_attempted_total"] = (
            pd.to_numeric(stats.get("opponent_head_sig_attempted", 0), errors="coerce").fillna(0)
            + pd.to_numeric(stats.get("opponent_body_sig_attempted", 0), errors="coerce").fillna(0)
            + pd.to_numeric(stats.get("opponent_leg_sig_attempted", 0), errors="coerce").fillna(0)
        )

    numeric_cols = [
        "elapsed_seconds",
        "sig_str_landed_total",
        "sig_str_attempted_total",
        "opponent_sig_str_landed_total",
        "opponent_sig_str_attempted_total",
        "td_landed",
        "td_attempted",
        "opponent_td_landed",
        "opponent_td_attempted",
        "control_time_seconds",
        "opponent_control_time_seconds",
        "sub_attempts",
        "won",
    ]

    for col in numeric_cols:
        if col not in stats.columns:
            stats[col] = np.nan if col == "opponent_control_time_seconds" else 0
        stats[col] = pd.to_numeric(stats[col], errors="coerce")

    stats["elapsed_seconds"] = stats["elapsed_seconds"].fillna(0)
    stats["minutes"] = stats["elapsed_seconds"] / 60.0

    stats["sig_landed"] = stats["sig_str_landed_total"].fillna(0)
    stats["sig_attempted"] = stats["sig_str_attempted_total"].fillna(0)
    stats["sig_absorbed"] = stats["opponent_sig_str_landed_total"].fillna(0)
    stats["opp_sig_attempted"] = stats["opponent_sig_str_attempted_total"].fillna(0)

    stats["td_landed"] = stats["td_landed"].fillna(0)
    stats["td_attempted"] = stats["td_attempted"].fillna(0)
    stats["td_absorbed"] = stats["opponent_td_landed"].fillna(0)
    stats["opp_td_attempted"] = stats["opponent_td_attempted"].fillna(0)

    stats["control_time_seconds"] = stats["control_time_seconds"].fillna(0)
    stats["sub_attempts"] = stats["sub_attempts"].fillna(0)

    stats = add_pair_opponent_fields(stats)
    stats = classify_methods(stats)
    stats = add_round_context(stats)

    stats["sig_diff"] = stats["sig_landed"] - stats["sig_absorbed"]
    stats["td_diff"] = stats["td_landed"] - stats["td_absorbed"]
    stats["control_diff_seconds"] = stats["control_time_seconds"] - stats["opponent_control_time_seconds"]

    stats["sig_diff_per_min"] = np.where(
        stats["minutes"] > 0,
        stats["sig_diff"] / stats["minutes"],
        np.nan,
    )
    stats["td_diff_per15"] = np.where(
        stats["minutes"] > 0,
        stats["td_diff"] / stats["minutes"] * 15.0,
        np.nan,
    )
    stats["control_diff_per15"] = np.where(
        stats["minutes"] > 0,
        stats["control_diff_seconds"] / stats["minutes"] * 15.0,
        np.nan,
    )

    return stats


# --------------------------------------------------------------------------------------
# Elo with historical opponent strength
# --------------------------------------------------------------------------------------


def build_elo_history_until(stats, cutoff_date):
    hist = stats[stats["event_date"] < cutoff_date].copy()

    hist["pre_elo"] = np.nan
    hist["opponent_elo_before"] = np.nan
    hist["pre_division_elo"] = np.nan
    hist["opponent_division_elo_before"] = np.nan

    overall = defaultdict(lambda: 1500.0)
    division = defaultdict(lambda: 1500.0)
    k = 32.0

    if hist.empty:
        return hist, overall, division

    fight_order = (
        hist.groupby("fight_id", dropna=False)["event_date"]
        .min()
        .reset_index()
        .sort_values(["event_date", "fight_id"])
    )

    for fight_id in fight_order["fight_id"].tolist():
        g = hist[hist["fight_id"] == fight_id].copy()
        if len(g) < 2:
            continue

        # Use the first two rows. UFCStats-style data should have exactly two fighter rows per fight.
        g = g.sort_values("fighter")
        row1 = g.iloc[0]
        row2 = g.iloc[1]

        f1 = row1["fighter"]
        f2 = row2["fighter"]
        div1 = row1.get("division", "")
        div2 = row2.get("division", div1)

        idx1 = row1.name
        idx2 = row2.name

        r1 = overall[f1]
        r2 = overall[f2]
        dr1 = division[(div1, f1)]
        dr2 = division[(div2, f2)]

        hist.at[idx1, "pre_elo"] = r1
        hist.at[idx1, "opponent_elo_before"] = r2
        hist.at[idx1, "pre_division_elo"] = dr1
        hist.at[idx1, "opponent_division_elo_before"] = dr2

        hist.at[idx2, "pre_elo"] = r2
        hist.at[idx2, "opponent_elo_before"] = r1
        hist.at[idx2, "pre_division_elo"] = dr2
        hist.at[idx2, "opponent_division_elo_before"] = dr1

        w1 = row1.get("won")
        w2 = row2.get("won")

        if pd.isna(w1) or pd.isna(w2):
            score1 = 0.5
            score2 = 0.5
        else:
            score1 = float(w1)
            score2 = float(w2)

        exp1 = 1.0 / (1.0 + 10 ** ((r2 - r1) / 400.0))
        exp2 = 1.0 - exp1

        overall[f1] = r1 + k * (score1 - exp1)
        overall[f2] = r2 + k * (score2 - exp2)

        dexp1 = 1.0 / (1.0 + 10 ** ((dr2 - dr1) / 400.0))
        dexp2 = 1.0 - dexp1

        division[(div1, f1)] = dr1 + k * (score1 - dexp1)
        division[(div2, f2)] = dr2 + k * (score2 - dexp2)

    return hist, overall, division


# --------------------------------------------------------------------------------------
# Snapshot feature engineering
# --------------------------------------------------------------------------------------


def recent_win_pct(rows, n):
    recent = rows.tail(n)
    valid = recent[recent["won"].notna()]
    if len(valid) == 0:
        return np.nan
    return valid["won"].mean()


def recent_rate(rows, n, col):
    recent = rows.tail(n)
    minutes = recent["minutes"].sum()
    if minutes <= 0:
        return np.nan

    if col == "sig_diff_per_min":
        return (recent["sig_landed"].sum() - recent["sig_absorbed"].sum()) / minutes

    if col == "td_diff_per15":
        return (recent["td_landed"].sum() - recent["td_absorbed"].sum()) / minutes * 15.0

    if col == "control_diff_per15":
        return (recent["control_diff_seconds"].sum()) / minutes * 15.0

    return np.nan


def weighted_avg(values, weights):
    values = pd.to_numeric(pd.Series(values), errors="coerce")
    weights = pd.to_numeric(pd.Series(weights), errors="coerce")
    valid = values.notna() & weights.notna() & (weights > 0)
    if valid.sum() == 0:
        return np.nan
    return float(np.average(values[valid], weights=weights[valid]))


def sum_since(rows, cutoff_date, condition_col=None, condition_value=None):
    temp = rows[rows["event_date"] >= cutoff_date]
    if condition_col is not None:
        temp = temp[temp[condition_col] == condition_value]
    return int(len(temp))


def add_aliases(snapshot):
    # Finish aliases.
    alias_pairs = [
        ("ko_tko_wins_before", "ko_wins_before"),
        ("ko_tko_losses_before", "ko_losses_before"),
        ("submission_wins_before", "sub_wins_before"),
        ("submission_losses_before", "sub_losses_before"),
        ("decision_wins_before", "wins_by_decision_before"),
        ("finish_wins_before", "wins_by_finish_before"),
        ("ko_tko_wins_before", "wins_by_ko_tko_before"),
        ("submission_wins_before", "wins_by_submission_before"),
        ("decision_losses_before", "losses_by_decision_before"),
        ("finish_losses_before", "losses_by_finish_before"),
        ("ko_tko_losses_before", "losses_by_ko_tko_before"),
        ("submission_losses_before", "losses_by_submission_before"),
    ]

    for source, target in alias_pairs:
        if source in snapshot and target not in snapshot:
            snapshot[target] = snapshot[source]

    # Activity aliases.
    for months in [12, 24]:
        base = f"fights_last_{months}_months_before"
        if base in snapshot:
            snapshot.setdefault(f"activity_last_{months}_months_before", snapshot[base])
            snapshot.setdefault(f"fights_last_{months}_months", snapshot[base])
            snapshot.setdefault(f"activity_last_{months}_months", snapshot[base])

    # Division aliases.
    if "fights_in_division_before" in snapshot:
        snapshot.setdefault("division_experience_before", snapshot["fights_in_division_before"])
        snapshot.setdefault("current_division_fights_before", snapshot["fights_in_division_before"])
        snapshot.setdefault("division_fights_before", snapshot["fights_in_division_before"])

    # Return-after-loss aliases.
    for key in ["returning_after_loss", "returning_after_finish_loss"]:
        if key in snapshot:
            snapshot.setdefault(f"{key}_before", snapshot[key])

    # Days-since aliases.
    for key in ["days_since_last_win", "days_since_last_loss"]:
        if key in snapshot:
            snapshot.setdefault(f"{key}_before", snapshot[key])

    # Age aliases.
    if "age_at_fight" in snapshot and pd.notna(snapshot["age_at_fight"]):
        age = float(snapshot["age_at_fight"])
        snapshot.setdefault("age_squared", age ** 2)
        snapshot.setdefault("age_at_fight_squared", age ** 2)
        snapshot.setdefault("age_sq", age ** 2)
        snapshot.setdefault("over_35", int(age > 35))
        snapshot.setdefault("age_over_35", int(age > 35))
        snapshot.setdefault("under_25", int(age < 25))
        snapshot.setdefault("age_under_25", int(age < 25))
        snapshot.setdefault("prime_26_34", int(26 <= age <= 34))
        snapshot.setdefault("age_prime_26_34", int(26 <= age <= 34))

    # Reach/height aliases.
    if "reach_height_ratio" in snapshot:
        snapshot.setdefault("reach_to_height_ratio", snapshot["reach_height_ratio"])

    # Opponent-adjusted aliases.
    opp_aliases = [
        ("opp_elo_weighted_sig_diff_per_min_before", "opponent_elo_weighted_sig_diff_per_min_before"),
        ("opp_elo_weighted_td_diff_per15_before", "opponent_elo_weighted_td_diff_per15_before"),
        ("opp_elo_weighted_control_diff_per15_before", "opponent_elo_weighted_control_diff_per15_before"),
        ("last_3_opp_elo_weighted_sig_diff_per_min_before", "last_3_opponent_elo_weighted_sig_diff_per_min_before"),
        ("last_3_opp_elo_weighted_td_diff_per15_before", "last_3_opponent_elo_weighted_td_diff_per15_before"),
        ("last_3_opp_elo_weighted_control_diff_per15_before", "last_3_opponent_elo_weighted_control_diff_per15_before"),
    ]
    for source, target in opp_aliases:
        if source in snapshot:
            snapshot.setdefault(target, snapshot[source])

    # Method-rate aliases used by some advanced training columns.
    method_rate_aliases = [
        ("finish_win_pct_before", "finish_win_rate_before"),
        ("decision_win_pct_before", "decision_win_rate_before"),
        ("ko_tko_win_pct_before", "ko_tko_win_rate_before"),
        ("submission_win_pct_before", "submission_win_rate_before"),
        ("submission_win_pct_before", "sub_win_rate_before"),
        ("finish_loss_pct_before", "finish_loss_rate_before"),
        ("decision_loss_pct_before", "decision_loss_rate_before"),
        ("ko_tko_loss_pct_before", "ko_tko_loss_rate_before"),
        ("submission_loss_pct_before", "submission_loss_rate_before"),
        ("submission_loss_pct_before", "sub_loss_rate_before"),
    ]
    for source, target in method_rate_aliases:
        if source in snapshot:
            snapshot.setdefault(target, snapshot[source])

    # Fight-method rates by all known prior fights.
    if "fights_with_known_method_before" in snapshot and snapshot.get("fights_with_known_method_before", 0):
        known = snapshot["fights_with_known_method_before"]
        finish_total = snapshot.get("finish_wins_before", 0) + snapshot.get("finish_losses_before", 0)
        decision_total = snapshot.get("decision_wins_before", 0) + snapshot.get("decision_losses_before", 0)
        ko_total = snapshot.get("ko_tko_wins_before", 0) + snapshot.get("ko_tko_losses_before", 0)
        sub_total = snapshot.get("submission_wins_before", 0) + snapshot.get("submission_losses_before", 0)
        snapshot.setdefault("finish_fight_rate_before", safe_div(finish_total, known))
        snapshot.setdefault("decision_fight_rate_before", safe_div(decision_total, known))
        snapshot.setdefault("ko_tko_fight_rate_before", safe_div(ko_total, known))
        snapshot.setdefault("submission_fight_rate_before", safe_div(sub_total, known))
        snapshot.setdefault("sub_fight_rate_before", safe_div(sub_total, known))

    return snapshot


def build_current_snapshot(
    fighter,
    division,
    fight_date,
    hist_stats,
    profile_map,
    overall_elo,
    division_elo,
):
    fighter_stats = hist_stats[
        (hist_stats["fighter"] == fighter)
        & (hist_stats["event_date"] < fight_date)
    ].sort_values("event_date").copy()

    profile = profile_map.get(normalize_name(fighter), {})

    snapshot = {}

    snapshot["age_at_fight"] = compute_age(profile, fight_date)
    snapshot["height_cm"] = pd.to_numeric(profile.get("height_cm"), errors="coerce")
    snapshot["reach_cm"] = pd.to_numeric(profile.get("reach_cm"), errors="coerce")
    snapshot["reach_height_ratio"] = safe_div(snapshot["reach_cm"], snapshot["height_cm"])

    stance = profile.get("stance", "Unknown")
    if pd.isna(stance) or not str(stance).strip():
        stance = "Unknown"
    snapshot["stance"] = str(stance).strip()

    snapshot["pre_elo"] = overall_elo.get(fighter, 1500.0)
    snapshot["pre_division_elo"] = division_elo.get((division, fighter), 1500.0)

    target_weight = division_weight_lbs(division)
    snapshot["target_division_weight_lbs"] = target_weight

    if fighter_stats.empty:
        snapshot.update(
            {
                "ufc_fights_before": 0,
                "ufc_wins_before": 0,
                "ufc_losses_before": 0,
                "ufc_draws_before": 0,
                "ufc_win_pct_before": np.nan,
                "current_win_streak": 0,
                "current_loss_streak": 0,
                "days_since_last_fight": np.nan,
                "days_since_last_win": np.nan,
                "days_since_last_loss": np.nan,
                "career_slpm_before": np.nan,
                "career_sapm_before": np.nan,
                "career_sig_str_accuracy_before": np.nan,
                "career_sig_str_defense_before": np.nan,
                "career_td_avg_per15_before": np.nan,
                "career_td_accuracy_before": np.nan,
                "career_td_defense_before": np.nan,
                "career_sub_attempts_per15_before": np.nan,
                "career_control_seconds_per15_before": np.nan,
                "career_control_diff_per15_before": np.nan,
                "last_3_win_pct": np.nan,
                "last_3_sig_str_diff_per_min": np.nan,
                "last_3_td_diff_per15": np.nan,
                "last_3_control_diff_per15": np.nan,
                "last_5_win_pct": np.nan,
                "last_5_sig_str_diff_per_min": np.nan,
                "last_5_td_diff_per15": np.nan,
                "last_5_control_diff_per15": np.nan,
                "scheduled_five_round_fights_before": 0,
                "late_round_fights_before": 0,
                "avg_opponent_elo_before": np.nan,
                "last_3_avg_opponent_elo_before": np.nan,
                "best_win_opponent_elo_before": np.nan,
                "avg_loss_opponent_elo_before": np.nan,
                "highest_loss_opponent_elo_before": np.nan,
                "opp_elo_weighted_sig_diff_per_min_before": np.nan,
                "opp_elo_weighted_td_diff_per15_before": np.nan,
                "opp_elo_weighted_control_diff_per15_before": np.nan,
                "last_3_opp_elo_weighted_sig_diff_per_min_before": np.nan,
                "last_3_opp_elo_weighted_td_diff_per15_before": np.nan,
                "last_3_opp_elo_weighted_control_diff_per15_before": np.nan,
                "fights_in_division_before": 0,
                "num_divisions_before": 0,
                "changed_division_since_last_fight": 0,
                "moving_up_division": 0,
                "moving_down_division": 0,
                "division_weight_change_lbs": np.nan,
                "fights_last_12_months_before": 0,
                "fights_last_24_months_before": 0,
                "wins_last_12_months_before": 0,
                "wins_last_24_months_before": 0,
                "losses_last_12_months_before": 0,
                "losses_last_24_months_before": 0,
                "returning_after_loss": 0,
                "returning_after_finish_loss": 0,
                "method_known_fights_before": 0,
                "method_total_fights_before": 0,
                "method_coverage_before": np.nan,
                "_method_source_columns": "NONE",
            }
        )

        # Finish history zeroes.
        for key in [
            "finish_wins_before", "decision_wins_before", "ko_tko_wins_before", "submission_wins_before",
            "finish_losses_before", "decision_losses_before", "ko_tko_losses_before", "submission_losses_before",
            "finish_win_pct_before", "decision_win_pct_before", "ko_tko_win_pct_before", "submission_win_pct_before",
            "finish_loss_pct_before", "decision_loss_pct_before", "ko_tko_loss_pct_before", "submission_loss_pct_before",
        ]:
            snapshot[key] = 0 if key.endswith("_before") and "pct" not in key else np.nan

        return add_aliases(snapshot)

    rows = fighter_stats.copy()
    total_minutes = rows["minutes"].sum()

    method_known_count = int(pd.to_numeric(rows.get("method_known", 0), errors="coerce").fillna(0).sum())
    snapshot["method_known_fights_before"] = method_known_count
    snapshot["fights_with_known_method_before"] = method_known_count
    snapshot["method_total_fights_before"] = int(len(rows))
    snapshot["method_coverage_before"] = safe_div(method_known_count, len(rows))
    if "_method_source_columns" in rows.columns and not rows.empty:
        snapshot["_method_source_columns"] = str(rows["_method_source_columns"].dropna().iloc[-1])
    else:
        snapshot["_method_source_columns"] = "NONE"

    wins = int(rows["won"].eq(1).sum())
    losses = int(rows["won"].eq(0).sum())

    draws = 0
    if "result" in rows.columns:
        draws = int(rows["result"].astype(str).str.lower().eq("draw").sum())

    valid_results = wins + losses

    snapshot["ufc_fights_before"] = int(len(rows))
    snapshot["ufc_wins_before"] = wins
    snapshot["ufc_losses_before"] = losses
    snapshot["ufc_draws_before"] = draws
    snapshot["ufc_win_pct_before"] = safe_div(wins, valid_results)

    current_win_streak = 0
    current_loss_streak = 0

    for value in reversed(rows["won"].tolist()):
        if pd.isna(value):
            continue

        if value == 1:
            if current_loss_streak == 0:
                current_win_streak += 1
            else:
                break
        elif value == 0:
            if current_win_streak == 0:
                current_loss_streak += 1
            else:
                break

    snapshot["current_win_streak"] = current_win_streak
    snapshot["current_loss_streak"] = current_loss_streak

    last_date = rows["event_date"].max()
    snapshot["days_since_last_fight"] = (
        (fight_date - last_date).days if pd.notna(last_date) else np.nan
    )

    win_dates = rows.loc[rows["won"].eq(1), "event_date"]
    loss_dates = rows.loc[rows["won"].eq(0), "event_date"]
    snapshot["days_since_last_win"] = (
        (fight_date - win_dates.max()).days if not win_dates.empty else np.nan
    )
    snapshot["days_since_last_loss"] = (
        (fight_date - loss_dates.max()).days if not loss_dates.empty else np.nan
    )

    sig_landed = rows["sig_landed"].sum()
    sig_attempted = rows["sig_attempted"].sum()
    sig_absorbed = rows["sig_absorbed"].sum()
    opp_sig_attempted = rows["opp_sig_attempted"].sum()

    td_landed = rows["td_landed"].sum()
    td_attempted = rows["td_attempted"].sum()
    td_absorbed = rows["td_absorbed"].sum()
    opp_td_attempted = rows["opp_td_attempted"].sum()

    sub_attempts = rows["sub_attempts"].sum()
    control_seconds = rows["control_time_seconds"].sum()
    control_diff_seconds = rows["control_diff_seconds"].sum()

    snapshot["career_slpm_before"] = safe_div(sig_landed, total_minutes)
    snapshot["career_sapm_before"] = safe_div(sig_absorbed, total_minutes)
    snapshot["career_sig_str_accuracy_before"] = safe_div(sig_landed, sig_attempted)
    snapshot["career_sig_str_defense_before"] = safe_div(
        opp_sig_attempted - sig_absorbed,
        opp_sig_attempted,
    )

    snapshot["career_td_avg_per15_before"] = safe_div(td_landed, total_minutes)
    if pd.notna(snapshot["career_td_avg_per15_before"]):
        snapshot["career_td_avg_per15_before"] *= 15.0

    snapshot["career_td_accuracy_before"] = safe_div(td_landed, td_attempted)
    snapshot["career_td_defense_before"] = safe_div(
        opp_td_attempted - td_absorbed,
        opp_td_attempted,
    )

    snapshot["career_sub_attempts_per15_before"] = safe_div(sub_attempts, total_minutes)
    if pd.notna(snapshot["career_sub_attempts_per15_before"]):
        snapshot["career_sub_attempts_per15_before"] *= 15.0

    snapshot["career_control_seconds_per15_before"] = safe_div(control_seconds, total_minutes)
    if pd.notna(snapshot["career_control_seconds_per15_before"]):
        snapshot["career_control_seconds_per15_before"] *= 15.0

    snapshot["career_control_diff_per15_before"] = safe_div(control_diff_seconds, total_minutes)
    if pd.notna(snapshot["career_control_diff_per15_before"]):
        snapshot["career_control_diff_per15_before"] *= 15.0

    snapshot["last_3_win_pct"] = recent_win_pct(rows, 3)
    snapshot["last_3_sig_str_diff_per_min"] = recent_rate(rows, 3, "sig_diff_per_min")
    snapshot["last_3_td_diff_per15"] = recent_rate(rows, 3, "td_diff_per15")
    snapshot["last_3_control_diff_per15"] = recent_rate(rows, 3, "control_diff_per15")

    snapshot["last_5_win_pct"] = recent_win_pct(rows, 5)
    snapshot["last_5_sig_str_diff_per_min"] = recent_rate(rows, 5, "sig_diff_per_min")
    snapshot["last_5_td_diff_per15"] = recent_rate(rows, 5, "td_diff_per15")
    snapshot["last_5_control_diff_per15"] = recent_rate(rows, 5, "control_diff_per15")

    # Opponent strength / opponent-adjusted performance.
    opp_elo = pd.to_numeric(rows.get("opponent_elo_before"), errors="coerce")
    opp_div_elo = pd.to_numeric(rows.get("opponent_division_elo_before"), errors="coerce")

    snapshot["avg_opponent_elo_before"] = opp_elo.mean()
    snapshot["last_3_avg_opponent_elo_before"] = opp_elo.tail(3).mean()
    snapshot["avg_opponent_division_elo_before"] = opp_div_elo.mean()
    snapshot["last_3_avg_opponent_division_elo_before"] = opp_div_elo.tail(3).mean()

    win_rows = rows[rows["won"].eq(1)]
    loss_rows = rows[rows["won"].eq(0)]

    snapshot["best_win_opponent_elo_before"] = pd.to_numeric(
        win_rows.get("opponent_elo_before"), errors="coerce"
    ).max() if not win_rows.empty else np.nan

    snapshot["avg_loss_opponent_elo_before"] = pd.to_numeric(
        loss_rows.get("opponent_elo_before"), errors="coerce"
    ).mean() if not loss_rows.empty else np.nan

    snapshot["highest_loss_opponent_elo_before"] = pd.to_numeric(
        loss_rows.get("opponent_elo_before"), errors="coerce"
    ).max() if not loss_rows.empty else np.nan

    snapshot["opp_elo_weighted_sig_diff_per_min_before"] = weighted_avg(
        rows["sig_diff_per_min"], rows["opponent_elo_before"]
    )
    snapshot["opp_elo_weighted_td_diff_per15_before"] = weighted_avg(
        rows["td_diff_per15"], rows["opponent_elo_before"]
    )
    snapshot["opp_elo_weighted_control_diff_per15_before"] = weighted_avg(
        rows["control_diff_per15"], rows["opponent_elo_before"]
    )

    recent3 = rows.tail(3)
    snapshot["last_3_opp_elo_weighted_sig_diff_per_min_before"] = weighted_avg(
        recent3["sig_diff_per_min"], recent3["opponent_elo_before"]
    )
    snapshot["last_3_opp_elo_weighted_td_diff_per15_before"] = weighted_avg(
        recent3["td_diff_per15"], recent3["opponent_elo_before"]
    )
    snapshot["last_3_opp_elo_weighted_control_diff_per15_before"] = weighted_avg(
        recent3["control_diff_per15"], recent3["opponent_elo_before"]
    )

    # Finish / decision / KO / submission history.
    method_history_keys = [
        "decision_wins_before", "finish_wins_before", "ko_tko_wins_before", "submission_wins_before",
        "decision_losses_before", "finish_losses_before", "ko_tko_losses_before", "submission_losses_before",
        "finish_win_pct_before", "decision_win_pct_before", "ko_tko_win_pct_before", "submission_win_pct_before",
        "finish_loss_pct_before", "decision_loss_pct_before", "ko_tko_loss_pct_before", "submission_loss_pct_before",
        "career_finish_win_rate_before", "career_decision_win_rate_before", "career_ko_tko_win_rate_before",
        "career_submission_win_rate_before",
    ]

    # Only compute method-history counts when every prior fight has usable method text. Partial
    # method coverage would silently undercount decisions/finishes, so leave these as NaN and let
    # snapshot fallback / training medians handle them.
    if method_known_count == len(rows):
        snapshot["decision_wins_before"] = int((win_rows["is_decision"] == 1).sum())
        snapshot["finish_wins_before"] = int((win_rows["is_finish"] == 1).sum())
        snapshot["ko_tko_wins_before"] = int((win_rows["is_ko_tko"] == 1).sum())
        snapshot["submission_wins_before"] = int((win_rows["is_submission"] == 1).sum())

        snapshot["decision_losses_before"] = int((loss_rows["is_decision"] == 1).sum())
        snapshot["finish_losses_before"] = int((loss_rows["is_finish"] == 1).sum())
        snapshot["ko_tko_losses_before"] = int((loss_rows["is_ko_tko"] == 1).sum())
        snapshot["submission_losses_before"] = int((loss_rows["is_submission"] == 1).sum())

        snapshot["finish_win_pct_before"] = safe_div(snapshot["finish_wins_before"], wins)
        snapshot["decision_win_pct_before"] = safe_div(snapshot["decision_wins_before"], wins)
        snapshot["ko_tko_win_pct_before"] = safe_div(snapshot["ko_tko_wins_before"], wins)
        snapshot["submission_win_pct_before"] = safe_div(snapshot["submission_wins_before"], wins)

        snapshot["finish_loss_pct_before"] = safe_div(snapshot["finish_losses_before"], losses)
        snapshot["decision_loss_pct_before"] = safe_div(snapshot["decision_losses_before"], losses)
        snapshot["ko_tko_loss_pct_before"] = safe_div(snapshot["ko_tko_losses_before"], losses)
        snapshot["submission_loss_pct_before"] = safe_div(snapshot["submission_losses_before"], losses)

        snapshot["career_finish_win_rate_before"] = safe_div(snapshot["finish_wins_before"], valid_results)
        snapshot["career_decision_win_rate_before"] = safe_div(snapshot["decision_wins_before"], valid_results)
        snapshot["career_ko_tko_win_rate_before"] = safe_div(snapshot["ko_tko_wins_before"], valid_results)
        snapshot["career_submission_win_rate_before"] = safe_div(snapshot["submission_wins_before"], valid_results)
    else:
        for key in method_history_keys:
            snapshot[key] = np.nan

    # Division movement / division experience.
    div_norm = rows["division"].map(normalize_division)
    target_div_norm = normalize_division(division)
    snapshot["fights_in_division_before"] = int((div_norm == target_div_norm).sum())
    snapshot["num_divisions_before"] = int(div_norm[div_norm != ""].nunique())
    snapshot["has_fought_in_division_before"] = int(snapshot["fights_in_division_before"] > 0)
    snapshot["first_fight_in_division"] = int(snapshot["fights_in_division_before"] == 0)
    snapshot["multi_division_experience_before"] = int(snapshot["num_divisions_before"] > 1)

    division_rows = rows[div_norm == target_div_norm].copy()
    division_wins = int(division_rows["won"].eq(1).sum()) if not division_rows.empty else 0
    division_losses = int(division_rows["won"].eq(0).sum()) if not division_rows.empty else 0
    snapshot["division_wins_before"] = division_wins
    snapshot["division_losses_before"] = division_losses
    snapshot["division_win_pct_before"] = safe_div(division_wins, division_wins + division_losses)

    last_division = rows.iloc[-1].get("division", "")
    last_weight = division_weight_lbs(last_division)
    snapshot["last_division_weight_lbs"] = last_weight
    snapshot["division_weight_change_lbs"] = (
        target_weight - last_weight
        if pd.notna(target_weight) and pd.notna(last_weight)
        else np.nan
    )
    snapshot["changed_division_since_last_fight"] = int(
        normalize_division(last_division) != target_div_norm
    )
    snapshot["same_division_as_last_fight"] = int(
        normalize_division(last_division) == target_div_norm
    )
    snapshot["moving_up_division"] = int(
        pd.notna(snapshot["division_weight_change_lbs"])
        and snapshot["division_weight_change_lbs"] > 0
    )
    snapshot["moving_down_division"] = int(
        pd.notna(snapshot["division_weight_change_lbs"])
        and snapshot["division_weight_change_lbs"] < 0
    )
    snapshot["previous_division_weight"] = snapshot["last_division_weight_lbs"]
    snapshot["moving_up"] = snapshot["moving_up_division"]
    snapshot["moving_down"] = snapshot["moving_down_division"]

    # Activity windows.
    cutoff_12 = fight_date - pd.DateOffset(months=12)
    cutoff_24 = fight_date - pd.DateOffset(months=24)

    for months, cutoff in [(12, cutoff_12), (24, cutoff_24)]:
        recent = rows[rows["event_date"] >= cutoff]
        snapshot[f"fights_last_{months}_months_before"] = int(len(recent))
        snapshot[f"wins_last_{months}_months_before"] = int(recent["won"].eq(1).sum())
        snapshot[f"losses_last_{months}_months_before"] = int(recent["won"].eq(0).sum())
        snapshot[f"win_pct_last_{months}_months_before"] = safe_div(
            snapshot[f"wins_last_{months}_months_before"],
            snapshot[f"wins_last_{months}_months_before"] + snapshot[f"losses_last_{months}_months_before"],
        )

    # Return-after-loss flags.
    last_row = rows.iloc[-1]
    last_won = last_row.get("won")
    last_finish = last_row.get("is_finish", np.nan)
    snapshot["returning_after_loss"] = int(pd.notna(last_won) and float(last_won) == 0)
    snapshot["returning_after_finish_loss"] = int(
        snapshot["returning_after_loss"] == 1
        and pd.notna(last_finish)
        and int(last_finish) == 1
    )

    # Five-round / late-round history. Uses explicit schedule columns when available,
    # parsed format text when available, and a safe elapsed-time lower-bound for fights
    # that reached round 4+.
    scheduled_five = pd.to_numeric(rows.get("is_scheduled_five_rounds"), errors="coerce")
    if scheduled_five.notna().any():
        snapshot["scheduled_five_round_fights_before"] = int((scheduled_five == 1).sum())
    else:
        snapshot["scheduled_five_round_fights_before"] = np.nan

    late_round = pd.to_numeric(rows.get("reached_late_round"), errors="coerce")
    if late_round.notna().any():
        snapshot["late_round_fights_before"] = int((late_round == 1).sum())
    else:
        snapshot["late_round_fights_before"] = np.nan

    return add_aliases(snapshot)


# --------------------------------------------------------------------------------------
# Matchup row construction / model training
# --------------------------------------------------------------------------------------


def stance_matchup(a_stance, b_stance):
    a = "Unknown" if pd.isna(a_stance) or not str(a_stance).strip() else str(a_stance).strip()
    b = "Unknown" if pd.isna(b_stance) or not str(b_stance).strip() else str(b_stance).strip()
    return f"{a}_vs_{b}"


def get_numeric_features(train_df):
    return [
        c for c in train_df.columns
        if c.endswith("_diff")
        and c not in EXCLUDED_DIFF_FEATURES
        and c != "fighter_a_won"
    ]


def get_categorical_features(train_df):
    return [
        c for c in ["division", "stance_matchup"]
        if c in train_df.columns
    ]


def build_prediction_row(train_df, snapshot_a, snapshot_b, division):
    numeric_features = get_numeric_features(train_df)

    row = {}

    for diff_col in numeric_features:
        base = diff_col[:-5]
        a_value = snapshot_a.get(base, np.nan)
        b_value = snapshot_b.get(base, np.nan)

        try:
            row[diff_col] = pd.to_numeric(a_value, errors="coerce") - pd.to_numeric(b_value, errors="coerce")
        except Exception:
            row[diff_col] = np.nan

    row["division"] = division
    row["stance_matchup"] = stance_matchup(
        snapshot_a.get("stance"),
        snapshot_b.get("stance"),
    )

    return pd.DataFrame([row])


def build_preprocessor(numeric_features, categorical_features):
    transformers = []

    if numeric_features:
        transformers.append(
            (
                "num",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric_features,
            )
        )

    if categorical_features:
        transformers.append(
            (
                "cat",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", make_onehot()),
                    ]
                ),
                categorical_features,
            )
        )

    return ColumnTransformer(
        transformers=transformers,
        remainder="drop",
        sparse_threshold=0.0,
    )


def build_model_pipeline(model, numeric_features, categorical_features):
    return Pipeline(
        [
            ("preprocess", build_preprocessor(numeric_features, categorical_features)),
            ("clf", model),
        ]
    )


def calibration_cv(y_train, requested=5):
    counts = pd.Series(y_train).value_counts()
    if counts.empty:
        return None
    min_class_count = int(counts.min())
    if min_class_count >= 5:
        return min(requested, 5)
    if min_class_count >= 3:
        return 3
    if min_class_count >= 2:
        return 2
    return None


def build_ensemble_cv(y_train):
    counts = pd.Series(y_train).value_counts()
    if counts.empty:
        return None
    min_class_count = int(counts.min())
    if min_class_count >= 5:
        return StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    if min_class_count >= 3:
        return StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    if min_class_count >= 2:
        return StratifiedKFold(n_splits=2, shuffle=True, random_state=42)
    return None


def compute_model_weights(pipelines, X_train, y_train):
    cv = build_ensemble_cv(y_train)
    if cv is None:
        return {name: 1.0 / len(pipelines) for name in pipelines}

    weights = {}
    for name, pipeline in pipelines.items():
        try:
            scores = cross_val_score(
                pipeline,
                X_train,
                y_train,
                scoring="neg_log_loss",
                cv=cv,
                n_jobs=-1,
                error_score="raise",
            )
            loss = -float(np.mean(scores))
            weights[name] = 1.0 / loss if loss > 0 else 1.0
        except Exception as exc:
            # A failed worker must not silently change the selected ensemble.
            # Successful calculations and the legitimate low-row fallback above
            # are unchanged; public callers can diagnose/retry this failure.
            raise RuntimeError("Model weight cross-validation failed; prediction stopped instead of using fallback weights.") from exc

    total = sum(weights.values())
    if not np.isfinite(total) or total <= 0:
        return {name: 1.0 / len(pipelines) for name in pipelines}
    return {name: weight / total for name, weight in weights.items()}


def build_models(y_train):
    cv = calibration_cv(y_train, requested=5)
    rf = RandomForestClassifier(
        random_state=42,
        n_estimators=500,
        max_depth=4,
        min_samples_leaf=8,
        class_weight="balanced",
        n_jobs=-1,
    )

    if cv is None:
        rf_model = rf
        counts = pd.Series(y_train).value_counts().to_dict()
        print(
            "WARNING: cal_rf_sigmoid_challenger is using uncalibrated "
            f"RandomForestClassifier because class counts are too small for "
            f"CalibratedClassifierCV: {counts}"
        )
    else:
        rf_model = make_calibrated(rf, method="sigmoid", cv=cv)

    gb = GradientBoostingClassifier(
        random_state=42,
        n_estimators=150,
        learning_rate=0.03,
        max_depth=2,
        subsample=0.80,
    )
    if cv is not None:
        gb = make_calibrated(gb, method="sigmoid", cv=cv)

    logistic = LogisticRegression(
        max_iter=5000,
        class_weight="balanced",
        C=0.25,
        solver="lbfgs",
    )
    if cv is not None:
        logistic = make_calibrated(logistic, method="sigmoid", cv=cv)

    return {
        "gb_shallow_primary": gb,
        "cal_rf_sigmoid_challenger": rf_model,
        "logistic_c025_sanity": logistic,
    }


# --------------------------------------------------------------------------------------
# Diagnostics / printing
# --------------------------------------------------------------------------------------



# --------------------------------------------------------------------------------------
# BAYES_PREFIGHT_SMOOTHING_INTEGRATION_V1_2026_05_13
# BAYES_PREFIGHT_SMOOTHING_DIAGNOSTIC_LABEL_CLEANUP_V1_2026_05_13
# Live Bayesian-smoothed prefight feature computation
# --------------------------------------------------------------------------------------

BAYES_SMOOTHING_FEATURE_MARKER = "_before_bayes_s20"
BAYES_SMOOTHING_EXPECTED_COUNT = 30


def compute_live_bayes_smoothing_feature_dict(
    fighter_a,
    fighter_b,
    division,
    fight_date,
    stats_path,
    prior_strength=20.0,
    min_group_denominator=200.0,
    neutral_prior=0.5,
):
    """
    Compute the same 30 Bayesian-smoothed prefight columns used by the smoothed
    training dataset.

    This intentionally delegates the detailed feature logic to the standalone helper
    script compute_live_bayes_smoothing_features_v1.py, which was audited before
    integration. Only rows with event_date < fight_date are used.
    """
    try:
        from compute_live_bayes_smoothing_features_v1 import (
            SMOOTH_PAIRS,
            compute_priors,
            compute_side_features,
            fighter_history,
            load_stats,
        )
    except Exception as exc:
        return {}, {
            "status": "import_failed",
            "error": repr(exc),
            "expected_features": BAYES_SMOOTHING_EXPECTED_COUNT,
        }

    try:
        fight_ts = pd.Timestamp(fight_date).normalize()
        df, schema = load_stats(Path(stats_path))
        df.attrs["fighter_col"] = schema["fighter_col"]

        before = df[df["__event_date"] < fight_ts].copy()
        excluded = int((df["__event_date"] >= fight_ts).sum())

        prior_rates, _prior_audit_rows = compute_priors(
            before,
            division=division,
            prior_strength=float(prior_strength),
            min_group_denominator=float(min_group_denominator),
            neutral_prior=float(neutral_prior),
        )

        hist_a = fighter_history(before, fighter_a)
        hist_b = fighter_history(before, fighter_b)

        suffix = (
            f"s{int(prior_strength)}"
            if float(prior_strength).is_integer()
            else "s" + str(prior_strength).replace(".", "p")
        )

        side_a, audit_a = compute_side_features(
            "fighter_a",
            fighter_a,
            hist_a,
            prior_rates,
            float(prior_strength),
            suffix,
            schema["fighter_col"],
        )
        side_b, audit_b = compute_side_features(
            "fighter_b",
            fighter_b,
            hist_b,
            prior_rates,
            float(prior_strength),
            suffix,
            schema["fighter_col"],
        )

        features = {}
        features.update(side_a)
        features.update(side_b)

        for pair in SMOOTH_PAIRS:
            a_col = f"fighter_a_{pair.base}_{suffix}"
            b_col = f"fighter_b_{pair.base}_{suffix}"
            diff_col = f"{pair.base}_{suffix}_diff"
            features[diff_col] = float(features[a_col] - features[b_col])

        expected_cols = []
        for side in ["fighter_a", "fighter_b"]:
            for pair in SMOOTH_PAIRS:
                expected_cols.append(f"{side}_{pair.base}_{suffix}")
            for pair in SMOOTH_PAIRS:
                expected_cols.append(f"{side}_{pair.base}_{suffix}_den_before")
        for pair in SMOOTH_PAIRS:
            expected_cols.append(f"{pair.base}_{suffix}_diff")

        missing = [c for c in expected_cols if c not in features]
        extra = [c for c in features if c not in expected_cols]

        value_cols = [c for c in expected_cols if c.endswith(f"_{suffix}") and not c.endswith("_diff")]
        denom_cols = [c for c in expected_cols if c.endswith("_den_before")]
        diff_cols = [c for c in expected_cols if c.endswith("_diff")]

        bad_values = [c for c in value_cols if not (0.0 <= float(features[c]) <= 1.0)]
        bad_denoms = [c for c in denom_cols if not (float(features[c]) >= 0.0)]
        bad_diffs = [c for c in diff_cols if not (-1.0 <= float(features[c]) <= 1.0)]

        status = "ok"
        if missing or extra or bad_values or bad_denoms or bad_diffs:
            status = "review"

        audit = {
            "status": status,
            "expected_features": len(expected_cols),
            "computed_features": len(features),
            "rows_before_fight_date_used": int(len(before)),
            "rows_on_or_after_fight_date_excluded": excluded,
            "fighter_a_matched_rows_before_date": int(audit_a.get("matched_rows_before_date", 0)),
            "fighter_b_matched_rows_before_date": int(audit_b.get("matched_rows_before_date", 0)),
            "fighter_a_last_prior_fight_date": audit_a.get("last_prior_fight_date"),
            "fighter_b_last_prior_fight_date": audit_b.get("last_prior_fight_date"),
            "missing": missing,
            "extra": extra,
            "bad_values": bad_values,
            "bad_denoms": bad_denoms,
            "bad_diffs": bad_diffs,
            "no_leakage_rule": "event_date < fight_date",
        }
        return features, audit
    except Exception as exc:
        return {}, {
            "status": "compute_failed",
            "error": repr(exc),
            "expected_features": BAYES_SMOOTHING_EXPECTED_COUNT,
        }


def inject_bayes_smoothing_features_into_prediction_rows(
    pred_row_forward,
    pred_row_reverse,
    feature_cols,
    fighter_a,
    fighter_b,
    division,
    fight_date,
    stats_path,
):
    """
    Add Bayesian-smoothed live features to forward and reverse prediction rows if
    the active training dataset expects them.
    """
    bayes_feature_cols = [c for c in feature_cols if BAYES_SMOOTHING_FEATURE_MARKER in c]
    if not bayes_feature_cols:
        return pred_row_forward, pred_row_reverse

    forward_features, forward_audit = compute_live_bayes_smoothing_feature_dict(
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        division=division,
        fight_date=fight_date,
        stats_path=stats_path,
    )
    reverse_features, reverse_audit = compute_live_bayes_smoothing_feature_dict(
        fighter_a=fighter_b,
        fighter_b=fighter_a,
        division=division,
        fight_date=fight_date,
        stats_path=stats_path,
    )

    # Store all computed Bayesian columns on the prediction rows for diagnostics
    # and reliability reporting. Model scoring still selects only feature_cols.
    for col, value in forward_features.items():
        pred_row_forward[col] = value
    for col, value in reverse_features.items():
        pred_row_reverse[col] = value

    missing_forward = [c for c in bayes_feature_cols if c not in forward_features]
    missing_reverse = [c for c in bayes_feature_cols if c not in reverse_features]

    print("\nBAYESIAN PREFIGHT SMOOTHING LIVE FEATURES")
    print("=" * 100)
    print(f"Expected Bayesian diff features used by predictor: {len(bayes_feature_cols)}")
    print(
        "Forward computation: "
        f"status={forward_audit.get('status')}, computed={forward_audit.get('computed_features')}, "
        f"{fighter_a} prior rows={forward_audit.get('fighter_a_matched_rows_before_date')}, "
        f"{fighter_b} prior rows={forward_audit.get('fighter_b_matched_rows_before_date')}"
    )
    print(
        "Reverse computation: "
        f"status={reverse_audit.get('status')}, computed={reverse_audit.get('computed_features')}, "
        f"{fighter_b} prior rows={reverse_audit.get('fighter_a_matched_rows_before_date')}, "
        f"{fighter_a} prior rows={reverse_audit.get('fighter_b_matched_rows_before_date')}"
    )
    print(f"Rows on/after fight date excluded forward: {forward_audit.get('rows_on_or_after_fight_date_excluded')}")
    print(f"Rows on/after fight date excluded reverse: {reverse_audit.get('rows_on_or_after_fight_date_excluded')}")
    print("No-leakage rule: event_date < fight_date")

    if missing_forward or missing_reverse or forward_audit.get("status") != "ok" or reverse_audit.get("status") != "ok":
        print("WARNING: Bayesian smoothing live-feature computation needs review.")
        if missing_forward:
            print(f"Missing forward Bayesian columns: {missing_forward}")
        if missing_reverse:
            print(f"Missing reverse Bayesian columns: {missing_reverse}")
        if forward_audit.get("error"):
            print(f"Forward error: {forward_audit.get('error')}")
        if reverse_audit.get("error"):
            print(f"Reverse error: {reverse_audit.get('error')}")
    else:
        print("Safety checks: PASS - Bayesian smoothing features injected; predictor uses available *_diff columns.")

    return pred_row_forward, pred_row_reverse


def model_input_feature_status(pred_row_forward, pred_row_reverse, feature_cols):
    missing_forward = [c for c in feature_cols if c not in pred_row_forward.columns]
    missing_reverse = [c for c in feature_cols if c not in pred_row_reverse.columns]
    bayesian_cols = [c for c in feature_cols if BAYES_SMOOTHING_FEATURE_MARKER in c]

    bayesian_all_nan = []
    final_all_nan = []
    for col in feature_cols:
        if col not in pred_row_forward.columns or col not in pred_row_reverse.columns:
            continue
        values = pd.concat([pred_row_forward[col], pred_row_reverse[col]], ignore_index=True)
        if values.isna().all():
            final_all_nan.append(col)
            if col in bayesian_cols:
                bayesian_all_nan.append(col)

    return {
        "feature_count": len(feature_cols),
        "missing_forward": missing_forward,
        "missing_reverse": missing_reverse,
        "bayesian_cols": bayesian_cols,
        "bayesian_all_nan": bayesian_all_nan,
        "final_all_nan": final_all_nan,
    }


def print_method_values(stats, fighter_a, fighter_b, fight_date):
    print("\nMETHOD VALUE DEBUG")
    print("=" * 100)

    for label, fighter in [("Fighter A", fighter_a), ("Fighter B", fighter_b)]:
        rows = stats[(stats["fighter"] == fighter) & (stats["event_date"] < fight_date)].copy()
        print(f"{label}: {fighter}")

        if rows.empty:
            print("  No prior fights found.")
            continue

        cols = [
            "event_date",
            "opponent",
            "won",
            "_method_text",
            "_method_normalized",
            "is_decision",
            "is_finish",
            "is_ko_tko",
            "is_submission",
        ]
        cols = [c for c in cols if c in rows.columns]
        rows = rows.sort_values("event_date")[cols]

        for _, r in rows.iterrows():
            date = pd.to_datetime(r.get("event_date"), errors="coerce")
            date_str = date.date() if pd.notna(date) else "N/A"
            opponent = r.get("opponent", "N/A")
            won = r.get("won", "N/A")
            raw = r.get("_method_text", "")
            norm = r.get("_method_normalized", "")
            dec = r.get("is_decision", np.nan)
            fin = r.get("is_finish", np.nan)
            ko = r.get("is_ko_tko", np.nan)
            sub = r.get("is_submission", np.nan)
            print(
                f"  {date_str} | vs {opponent} | won={won} | raw={raw!r} | norm={norm!r} | "
                f"decision={dec} finish={fin} ko_tko={ko} sub={sub}"
            )


def print_feature_diagnostics(
    train_df,
    snapshot_a,
    snapshot_b,
    numeric_features,
    categorical_features,
    fallback_filled_a,
    fallback_filled_b,
    model_input_status=None,
):
    required_bases = [c[:-5] for c in numeric_features]
    missing_a = [base for base in required_bases if base not in snapshot_a]
    missing_b = [base for base in required_bases if base not in snapshot_b]

    both_nan = []
    for base in required_bases:
        av = snapshot_a.get(base, np.nan)
        bv = snapshot_b.get(base, np.nan)
        if pd.isna(av) and pd.isna(bv):
            both_nan.append(base)

    print("\nADVANCED FEATURE DIAGNOSTICS")
    print("=" * 100)
    print(f"Training rows: {len(train_df):,}")
    print(f"Numeric diff features: {len(numeric_features):,}")
    print(f"Categorical features: {', '.join(categorical_features) if categorical_features else 'None'}")
    print(f"Missing live snapshot base keys, Fighter A: {len(missing_a):,}")
    print(f"Missing live snapshot base keys, Fighter B: {len(missing_b):,}")
    print(f"Snapshot feature bases where both fighters are NaN: {len(both_nan):,}")

    if model_input_status is not None:
        print(f"Final model input features: {model_input_status['feature_count']:,}")
        print(
            "Missing final model input columns before safety fill, forward: "
            f"{len(model_input_status['missing_forward']):,}"
        )
        print(
            "Missing final model input columns before safety fill, reverse: "
            f"{len(model_input_status['missing_reverse']):,}"
        )
        print(f"Bayesian model input *_diff columns: {len(model_input_status['bayesian_cols']):,}")
        print(
            "Bayesian model input columns all-NaN after live injection: "
            f"{len(model_input_status['bayesian_all_nan']):,}"
        )

    a_method_known = snapshot_a.get("method_known_fights_before", np.nan)
    a_method_total = snapshot_a.get("method_total_fights_before", snapshot_a.get("ufc_fights_before", np.nan))
    b_method_known = snapshot_b.get("method_known_fights_before", np.nan)
    b_method_total = snapshot_b.get("method_total_fights_before", snapshot_b.get("ufc_fights_before", np.nan))
    method_sources = sorted({
        str(snapshot_a.get("_method_source_columns", "NONE")),
        str(snapshot_b.get("_method_source_columns", "NONE")),
    })
    print(f"Method-known fights, Fighter A: {a_method_known}/{a_method_total}")
    print(f"Method-known fights, Fighter B: {b_method_known}/{b_method_total}")
    print(f"Method source columns: {', '.join(method_sources)}")

    if fallback_filled_a or fallback_filled_b:
        print(f"Snapshot fallback filled A keys: {len(fallback_filled_a):,}")
        print(f"Snapshot fallback filled B keys: {len(fallback_filled_b):,}")

    if missing_a:
        print("\nFirst missing A snapshot base keys:")
        for base in missing_a[:20]:
            print(f"  - {base}")

    if missing_b:
        print("\nFirst missing B snapshot base keys:")
        for base in missing_b[:20]:
            print(f"  - {base}")

    if both_nan:
        print("\nFirst both-NaN snapshot base keys:")
        for base in both_nan[:20]:
            print(f"  - {base}")

    if model_input_status is not None:
        if model_input_status["missing_forward"]:
            print("\nFirst missing forward final model input columns:")
            for col in model_input_status["missing_forward"][:20]:
                print(f"  - {col}")
        if model_input_status["missing_reverse"]:
            print("\nFirst missing reverse final model input columns:")
            for col in model_input_status["missing_reverse"][:20]:
                print(f"  - {col}")
        if model_input_status["bayesian_all_nan"]:
            print("\nFirst all-NaN Bayesian final model input columns:")
            for col in model_input_status["bayesian_all_nan"][:20]:
                print(f"  - {col}")


def print_advantage_table(snapshot_a, snapshot_b, fighter_a, fighter_b):
    features = [
        ("Age", "age_at_fight"),
        ("Height cm", "height_cm"),
        ("Reach cm", "reach_cm"),
        ("Reach/height", "reach_height_ratio"),
        ("Overall Elo", "pre_elo"),
        ("Division Elo", "pre_division_elo"),
        ("Avg opponent Elo", "avg_opponent_elo_before"),
        ("Last 3 opp Elo", "last_3_avg_opponent_elo_before"),
        ("Best win opp Elo", "best_win_opponent_elo_before"),
        ("UFC fights", "ufc_fights_before"),
        ("UFC win pct", "ufc_win_pct_before"),
        ("SLpM", "career_slpm_before"),
        ("SApM", "career_sapm_before"),
        ("Sig acc", "career_sig_str_accuracy_before"),
        ("Sig def", "career_sig_str_defense_before"),
        ("TD / 15", "career_td_avg_per15_before"),
        ("TD acc", "career_td_accuracy_before"),
        ("TD def", "career_td_defense_before"),
        ("Control diff / 15", "career_control_diff_per15_before"),
        ("Last 3 win pct", "last_3_win_pct"),
        ("Last 3 sig diff/min", "last_3_sig_str_diff_per_min"),
        ("Last 3 TD diff/15", "last_3_td_diff_per15"),
        ("Finish wins", "finish_wins_before"),
        ("Decision wins", "decision_wins_before"),
        ("KO/TKO wins", "ko_tko_wins_before"),
        ("Sub wins", "submission_wins_before"),
        ("Fights in division", "fights_in_division_before"),
        ("Fights last 12 mo", "fights_last_12_months_before"),
        ("Days since win", "days_since_last_win"),
        ("Days since loss", "days_since_last_loss"),
        ("Returning off loss", "returning_after_loss"),
    ]

    print("\nKEY MATCHUP SNAPSHOT")
    print("=" * 100)
    print(f"{'Feature':<26} {fighter_a:<24} {fighter_b:<24} {'Diff A-B':<12}")
    print("-" * 100)

    for label, key in features:
        a = snapshot_a.get(key, np.nan)
        b = snapshot_b.get(key, np.nan)

        try:
            diff = pd.to_numeric(a, errors="coerce") - pd.to_numeric(b, errors="coerce")
        except Exception:
            diff = np.nan

        def fmt(v):
            if pd.isna(v):
                return "N/A"
            if isinstance(v, str):
                return v[:20]
            if "pct" in key or "accuracy" in key or "defense" in key or key.endswith("ratio"):
                return f"{float(v):.3f}"
            return f"{float(v):.2f}"

        print(f"{label:<26} {fmt(a):<24} {fmt(b):<24} {fmt(diff):<12}")


def print_market_comparison(args, fighter_a, fighter_b, primary_prob_a, market_comparison=None):
    market = market_comparison or add_model_market_edges(
        getattr(args, "market_odds", _market_comparison_empty()),
        primary_prob_a,
    )

    if not market.get("market_comparison_available"):
        if market.get("market_comparison_warning"):
            print("\nMARKET COMPARISON")
            print("=" * 100)
            print(market["market_comparison_warning"])
        return

    print("\nMARKET COMPARISON")
    print("=" * 100)
    print(
        f"{fighter_a} odds input: "
        f"{format_odds_input_for_market(market['fighter_a_odds_input'], market['fighter_a_odds_format_detected'], market['fighter_a_decimal_odds'])}"
    )
    print(
        f"{fighter_b} odds input: "
        f"{format_odds_input_for_market(market['fighter_b_odds_input'], market['fighter_b_odds_format_detected'], market['fighter_b_decimal_odds'])}"
    )
    print(f"{fighter_a} no-vig market probability: {format_prob(market['fighter_a_no_vig_market_probability'])}")
    print(f"{fighter_b} no-vig market probability: {format_prob(market['fighter_b_no_vig_market_probability'])}")
    print(f"{fighter_a} model-minus-market: {format_prob(market['fighter_a_model_minus_market'])}")
    print(f"{fighter_b} model-minus-market: {format_prob(market['fighter_b_model_minus_market'])}")


def print_market_edge_interpretation(market_edge, reliability_label, reliability_score):
    if not market_edge or not market_edge.get("market_edge_available"):
        return

    print("\nMARKET EDGE INTERPRETATION")
    print("=" * 100)
    print(f"Model-market signal: {market_edge_label_display(market_edge.get('market_edge_label'))}")
    print(f"Edge side: {market_edge.get('market_edge_fighter')}")
    print(f"Model-minus-market: {format_prob(market_edge.get('market_edge_probability_delta'))}")
    print(f"Reliability: {reliability_label} / {reliability_score}")
    print(f"Review priority: {market_edge.get('market_edge_review_priority')}")
    if market_edge.get("market_pick_favorite"):
        print(f"Market favorite: {market_edge.get('market_pick_favorite')}")
    if market_edge.get("market_edge_warning"):
        print(f"Warning: {market_edge.get('market_edge_warning')}")
    if market_edge.get("market_edge_note"):
        print(f"Note: {market_edge.get('market_edge_note')}")


def reliability_effect(penalty):
    if penalty == 0:
        return "positive"
    if penalty >= -5:
        return "mild concern"
    if penalty >= -10:
        return "moderate concern"
    return "major concern"


def support_from_denominators(pred_row_forward, columns, thresholds):
    values = []
    for col in columns:
        if col not in pred_row_forward.columns:
            continue
        value = pd.to_numeric(pred_row_forward[col].iloc[0], errors="coerce")
        if pd.notna(value):
            values.append(float(value))

    if not values:
        return {
            "status": "unknown/none",
            "penalty": thresholds["missing_penalty"],
            "minimum": np.nan,
        }

    minimum = min(values)
    if minimum >= thresholds["high"]:
        status = "high"
        penalty = 0
    elif minimum >= thresholds["moderate"]:
        status = "moderate"
        penalty = thresholds["moderate_penalty"]
    elif minimum > 0:
        status = "low"
        penalty = thresholds["low_penalty"]
    else:
        status = "unknown/none"
        penalty = thresholds["missing_penalty"]

    return {"status": status, "penalty": penalty, "minimum": minimum}


def compute_prediction_reliability(
    primary_prob_a,
    model_probabilities,
    direction_disagreement,
    votes_for_a,
    votes_for_b,
    training_rows_used,
    snapshot_a,
    snapshot_b,
    model_input_status,
    pred_row_forward,
):
    score = 100
    factors = []
    notes = []

    confidence_distance = abs(float(primary_prob_a) - 0.5)
    primary_confidence = max(float(primary_prob_a), 1.0 - float(primary_prob_a))
    if confidence_distance < 0.03:
        penalty = -25
    elif confidence_distance < 0.075:
        penalty = -15
    elif confidence_distance < 0.125:
        penalty = -5
    else:
        penalty = 0
    score += penalty
    factors.append({"factor": "Ensemble confidence", "status": format_prob(primary_confidence), "effect": reliability_effect(penalty)})
    if penalty <= -15:
        notes.append("The ensemble probability is close to 50%, so the estimate is inherently less stable.")
    elif penalty == 0:
        notes.append("The ensemble probability is meaningfully away from 50%.")

    probs = pd.Series(model_probabilities, dtype="float64").dropna()
    model_spread = float(probs.max() - probs.min()) if not probs.empty else np.nan
    if pd.isna(model_spread):
        penalty = -5
    elif model_spread <= 0.05:
        penalty = 0
    elif model_spread <= 0.10:
        penalty = -5
    elif model_spread <= 0.20:
        penalty = -15
    else:
        penalty = -25
    score += penalty
    factors.append({"factor": "Model spread", "status": format_prob(model_spread), "effect": reliability_effect(penalty)})
    if penalty <= -15:
        notes.append("The model spread is wide enough to treat the estimate as unstable.")
    elif penalty == 0:
        notes.append("Model spread is low, so the three model estimates are closely aligned.")

    dd = float(direction_disagreement) if pd.notna(direction_disagreement) else np.nan
    if pd.isna(dd):
        penalty = -5
    elif dd <= 0.05:
        penalty = 0
    elif dd <= 0.10:
        penalty = -5
    elif dd <= 0.20:
        penalty = -10
    else:
        penalty = -20
    score += penalty
    factors.append({"factor": "Direction disagreement", "status": format_prob(dd), "effect": reliability_effect(penalty)})
    if penalty == 0:
        notes.append("Direction disagreement is low, so forward/reverse symmetry is stable.")
    elif penalty <= -10:
        notes.append("Forward/reverse direction disagreement is a material reliability concern.")

    total_votes = int(votes_for_a) + int(votes_for_b)
    if total_votes == 0:
        vote_status = "unknown"
        penalty = -5
    elif max(votes_for_a, votes_for_b) == total_votes:
        vote_status = f"{max(votes_for_a, votes_for_b)}-0"
        penalty = 0
    else:
        vote_status = f"{max(votes_for_a, votes_for_b)}-{min(votes_for_a, votes_for_b)}"
        penalty = -10
    score += penalty
    factors.append({"factor": "Model vote", "status": vote_status, "effect": reliability_effect(penalty)})
    if penalty == 0:
        notes.append("All three models agree on the same winner.")
    elif penalty == -10:
        notes.append("Model vote is split, so the pick depends more on the ensemble average.")

    if training_rows_used >= 1500:
        penalty = 0
    elif training_rows_used >= 1000:
        penalty = -5
    elif training_rows_used >= 500:
        penalty = -10
    else:
        penalty = -20
    score += penalty
    factors.append({"factor": "Training rows", "status": f"{training_rows_used:,}", "effect": reliability_effect(penalty)})
    if penalty <= -10:
        notes.append("The date-filtered training set is small, which limits reliability.")

    a_fights = pd.to_numeric(snapshot_a.get("ufc_fights_before", np.nan), errors="coerce")
    b_fights = pd.to_numeric(snapshot_b.get("ufc_fights_before", np.nan), errors="coerce")
    if pd.isna(a_fights) or pd.isna(b_fights):
        min_fights = np.nan
        penalty = -25
    else:
        min_fights = min(float(a_fights), float(b_fights))
        if min_fights >= 8:
            penalty = 0
        elif min_fights >= 5:
            penalty = -5
        elif min_fights >= 3:
            penalty = -8
        elif min_fights >= 1:
            penalty = -15
        else:
            penalty = -25
    score += penalty
    min_fights_status = "missing" if pd.isna(min_fights) else f"{int(min_fights)}"
    factors.append({"factor": "Minimum UFC fights", "status": min_fights_status, "effect": reliability_effect(penalty)})
    if penalty <= -8:
        if pd.notna(min_fights) and float(min_fights) == 0.0:
            notes.append("At least one fighter has no confirmed UFC history, so the estimate is low-information.")
        else:
            notes.append("Fighter history exists for both fighters, but the smaller UFC sample still limits certainty.")
    elif penalty == 0:
        notes.append("Both fighters have enough UFC history to support the estimate.")

    strike_cols = [
        "fighter_a_career_sig_str_accuracy_before_bayes_s20_den_before",
        "fighter_b_career_sig_str_accuracy_before_bayes_s20_den_before",
        "fighter_a_career_sig_str_allowed_accuracy_before_bayes_s20_den_before",
        "fighter_b_career_sig_str_allowed_accuracy_before_bayes_s20_den_before",
        "fighter_a_career_total_str_accuracy_before_bayes_s20_den_before",
        "fighter_b_career_total_str_accuracy_before_bayes_s20_den_before",
        "fighter_a_career_total_str_allowed_accuracy_before_bayes_s20_den_before",
        "fighter_b_career_total_str_allowed_accuracy_before_bayes_s20_den_before",
    ]
    strike_support = support_from_denominators(
        pred_row_forward,
        strike_cols,
        {"high": 150, "moderate": 60, "moderate_penalty": -3, "low_penalty": -8, "missing_penalty": -10},
    )
    score += strike_support["penalty"]
    strike_status = strike_support["status"]
    if pd.notna(strike_support["minimum"]):
        strike_status = f"{strike_status} (min {strike_support['minimum']:.0f})"
    factors.append({"factor": "Bayesian strike support", "status": strike_status, "effect": reliability_effect(strike_support["penalty"])})
    if strike_support["penalty"] <= -8:
        notes.append("Bayesian strike-data support is sparse, so striking-rate estimates are less stable.")

    td_cols = [
        "fighter_a_career_td_accuracy_before_bayes_s20_den_before",
        "fighter_b_career_td_accuracy_before_bayes_s20_den_before",
        "fighter_a_career_td_allowed_accuracy_before_bayes_s20_den_before",
        "fighter_b_career_td_allowed_accuracy_before_bayes_s20_den_before",
    ]
    td_support = support_from_denominators(
        pred_row_forward,
        td_cols,
        {"high": 20, "moderate": 8, "moderate_penalty": -3, "low_penalty": -6, "missing_penalty": -8},
    )
    score += td_support["penalty"]
    td_status = td_support["status"]
    if pd.notna(td_support["minimum"]):
        td_status = f"{td_status} (min {td_support['minimum']:.0f})"
    factors.append({"factor": "Bayesian takedown support", "status": td_status, "effect": reliability_effect(td_support["penalty"])})
    if td_support["penalty"] <= -6:
        notes.append("Takedown data is relatively sparse, so grappling-rate estimates remain less reliable.")

    missing_final = list(model_input_status.get("missing_forward", [])) + list(model_input_status.get("missing_reverse", []))
    bayesian_all_nan = list(model_input_status.get("bayesian_all_nan", []))
    if missing_final or bayesian_all_nan:
        penalty = -20
        status = "review needed"
    else:
        penalty = 0
        status = "complete"
    score += penalty
    factors.append({"factor": "Final model-input features", "status": status, "effect": reliability_effect(penalty)})
    if penalty == 0:
        notes.append("Final model-input features are complete after Bayesian live-feature injection.")
    else:
        notes.append("One or more final model-input features are missing or unusable.")

    score = int(max(0, min(100, round(score))))
    label = "High" if score >= 75 else "Medium" if score >= 55 else "Low"

    return {
        "label": label,
        "score": score,
        "factors": factors,
        "notes": notes,
        "missing_final_model_inputs": missing_final,
        "bayesian_all_nan": bayesian_all_nan,
    }


def print_prediction_reliability(reliability):
    print("\nPREDICTION RELIABILITY / UNCERTAINTY")
    print("=" * 100)
    print(f"Reliability label: {reliability['label']}")
    print(f"Reliability score: {reliability['score']}/100")
    print("Meaning: reliability estimates how stable the model probability is, not whether the fight is predictable.")

    print()
    print(f"{'Factor':<30} {'Status':<26} {'Effect':<18}")
    print("-" * 100)
    for row in reliability["factors"]:
        print(f"{row['factor']:<30} {row['status']:<26} {row['effect']:<18}")

    print("\nReliability notes:")
    seen = set()
    for note in reliability["notes"]:
        if note in seen:
            continue
        seen.add(note)
        print(f"- {note}")

    if reliability["missing_final_model_inputs"]:
        print("- Missing final model input columns: " + ", ".join(reliability["missing_final_model_inputs"][:12]))
    if reliability["bayesian_all_nan"]:
        print("- All-NaN Bayesian model input columns: " + ", ".join(reliability["bayesian_all_nan"][:12]))


def json_safe_value(value):
    if isinstance(value, dict):
        return {str(key): json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_value(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    if pd.isna(value):
        return None
    return value


def parse_support_factor_status(reliability, factor_name):
    factor = next((row for row in reliability.get("factors", []) if row.get("factor") == factor_name), None)
    if not factor:
        return None, None

    status = str(factor.get("status", "")).strip()
    minimum = None
    match = re.search(r"\(min\s+([0-9.]+)\)", status)
    if match:
        minimum = float(match.group(1))
        status = re.sub(r"\s*\(min\s+[0-9.]+\)\s*", "", status).strip()
    return status or None, minimum


def build_structured_prediction_summary(
    args,
    fighter_a,
    fighter_b,
    fight_date,
    train_path,
    stats_path,
    model_train_df,
    train_df,
    pred_df,
    ensemble_row,
    reliability,
    primary_prob_a,
    primary_confidence,
    votes_for_a,
    votes_for_b,
    vote_text,
    model_spread,
    model_input_status,
    snapshot_a,
    snapshot_b,
    market_comparison,
    market_edge,
    ensemble_weights,
    pred_row_forward,
):
    predicted_fighter = fighter_a if primary_prob_a >= 0.5 else fighter_b
    predicted_probability = primary_prob_a if primary_prob_a >= 0.5 else 1.0 - primary_prob_a

    a_fights = pd.to_numeric(snapshot_a.get("ufc_fights_before", np.nan), errors="coerce")
    b_fights = pd.to_numeric(snapshot_b.get("ufc_fights_before", np.nan), errors="coerce")
    min_ufc_fights = np.nan
    if pd.notna(a_fights) and pd.notna(b_fights):
        min_ufc_fights = min(float(a_fights), float(b_fights))

    strike_support_level, strike_support_min_denominator = parse_support_factor_status(
        reliability,
        "Bayesian strike support",
    )
    td_support_level, td_support_min_denominator = parse_support_factor_status(
        reliability,
        "Bayesian takedown support",
    )

    model_rows = {
        str(row["model"]): row
        for _, row in pred_df.iterrows()
    }

    summary = {
        "fighter_a": fighter_a,
        "fighter_b": fighter_b,
        "division": args.division,
        "fight_date": fight_date.strftime("%Y-%m-%d") if pd.notna(fight_date) else None,
        "predicted_winner": predicted_fighter,
        "predicted_winner_probability": predicted_probability,
        "fighter_a_win_probability": primary_prob_a,
        "fighter_b_win_probability": 1.0 - primary_prob_a,
        "ensemble_probability": primary_prob_a,
        "ensemble_confidence": primary_confidence,
        "model_vote": vote_text,
        "votes_for_fighter_a": votes_for_a,
        "votes_for_fighter_b": votes_for_b,
        "model_spread": model_spread,
        "direction_disagreement": float(ensemble_row["direction_disagreement"]),
        "training_rows_used": int(len(model_train_df)),
        "training_rows_available": int(len(train_df)),
        "training_data": str(train_path),
        "stats_data": str(stats_path),
        "reliability_label": reliability["label"],
        "reliability_score": int(reliability["score"]),
        "reliability_meaning": "Reliability estimates how stable the model probability is, not whether the fight is predictable.",
        "reliability_note": " ".join(reliability.get("notes", [])[:3]),
        "min_ufc_fights": min_ufc_fights,
        "strike_support_level": strike_support_level,
        "strike_support_min_denominator": strike_support_min_denominator,
        "td_support_level": td_support_level,
        "td_support_min_denominator": td_support_min_denominator,
        "missing_final_feature_count": int(
            len(model_input_status.get("missing_forward", []))
            + len(model_input_status.get("missing_reverse", []))
        ),
        "all_nan_bayes_model_input_count": int(len(model_input_status.get("bayesian_all_nan", []))),
    }

    summary.update(market_comparison or _market_comparison_empty())
    summary.update(market_edge or _market_edge_empty())

    summary["fighter_a_snapshot"] = {
        str(key): json_safe_value(value) for key, value in snapshot_a.items()
    }
    summary["fighter_b_snapshot"] = {
        str(key): json_safe_value(value) for key, value in snapshot_b.items()
    }

    # These are the same live values, weights, and checks used above; reporting
    # exposes them without recomputing features or changing the ensemble.
    for side, snapshot in (("a", snapshot_a), ("b", snapshot_b)):
        prefix = f"fighter_{side}_"
        live_values = {
            str(column)[len(prefix):]: value
            for column, value in pred_row_forward.iloc[0].items()
            if str(column).startswith(prefix)
        }
        summary[f"fighter_{side}_comparison"] = {**snapshot, **live_values}
    summary["model_weights"] = dict(ensemble_weights)
    summary["model_predictions"] = pred_df.to_dict(orient="records") + [dict(ensemble_row)]
    summary["reliability_factors"] = list(reliability.get("factors", []))
    summary["reliability_notes"] = list(reliability.get("notes", []))

    for model_name, row in model_rows.items():
        prefix = model_name
        summary[f"{prefix}_fighter_a_win_probability"] = row["fighter_a_win_probability"]
        summary[f"{prefix}_fighter_b_win_probability"] = row["fighter_b_win_probability"]
        summary[f"{prefix}_direction_disagreement"] = row["direction_disagreement"]

    return {key: json_safe_value(value) for key, value in summary.items()}


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------


from analyzer_protocol import progress as stage_progress


def prepare_matchup(args, progress=None):
    notify = progress or stage_progress

    try:
        args.market_odds = normalize_market_odds(
            args.fighter_a_odds,
            args.fighter_b_odds,
            odds_format=args.odds_format,
        )
    except ValueError as exc:
        raise SystemExit(f"Odds parsing error: {exc}") from None

    train_path = Path(args.data)
    stats_path = Path(args.stats)

    if not train_path.exists():
        raise FileNotFoundError(train_path)

    if not stats_path.exists():
        raise FileNotFoundError(stats_path)

    notify("loading", "Loading women’s training data and fight history")
    train_df = pd.read_csv(train_path)
    train_df["event_date"] = pd.to_datetime(train_df["event_date"], errors="coerce")
    train_df = train_df.dropna(subset=["event_date", "fighter_a_won", "fight_id"]).copy()
    train_df["fighter_a_won"] = train_df["fighter_a_won"].astype(int)

    snapshots_df = load_snapshots(args.snapshots)

    stats = pd.read_csv(stats_path)
    stats = clean_numeric_columns(stats)

    profile_path = find_profile_file(args.profiles)
    manual_profile_names = (
        load_manual_profile_names(profile_path)
        if args.allow_manual_profile_fallback
        else {}
    )

    known_name_set = (
        set(train_df.get("fighter_a", pd.Series(dtype=str)).dropna())
        | set(train_df.get("fighter_b", pd.Series(dtype=str)).dropna())
        | set(stats.get("fighter", pd.Series(dtype=str)).dropna())
    )
    if manual_profile_names:
        known_name_set |= set(manual_profile_names.values())
    known_names = sorted(known_name_set)

    try:
        fighter_a = canonicalize_fighter_name(args.fighter_a, known_names)
        fighter_b = canonicalize_fighter_name(args.fighter_b, known_names)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None

    fight_date = (
        pd.to_datetime(args.fight_date, errors="coerce")
        if args.fight_date
        else pd.Timestamp.today().normalize()
    )

    if pd.isna(fight_date):
        raise ValueError(f"Could not parse fight date: {args.fight_date}")

    if args.no_train_date_filter:
        model_train_df = train_df.copy()
        train_date_filter_note = "none; using all rows because --no-train-date-filter was supplied"
    else:
        model_train_df = train_df[train_df["event_date"] < fight_date].copy()
        train_date_filter_note = f"event_date < {fight_date.date()}"

    if model_train_df.empty and not getattr(args, 'comparison_only', False):
        raise ValueError(
            "No training rows remain after applying the training date filter. "
            "Use a later --fight-date or pass --no-train-date-filter only for non-as-of experiments."
        )

    if model_train_df["fighter_a_won"].nunique() < 2 and not getattr(args, 'comparison_only', False):
        raise ValueError(
            "Training rows after the date filter contain only one outcome class. "
            "Use a later --fight-date or pass --no-train-date-filter only for non-as-of experiments."
        )

    profile_source_df = train_df if args.no_train_date_filter else model_train_df
    profile_map = load_profiles(profile_path, profile_source_df, snapshots_df=snapshots_df)

    notify("features", "Preparing dated fighter snapshots, Elo and Bayesian features")
    hist_stats, overall_elo, division_elo = build_elo_history_until(stats, fight_date)

    snapshot_a = build_current_snapshot(
        fighter_a,
        args.division,
        fight_date,
        hist_stats,
        profile_map,
        overall_elo,
        division_elo,
    )

    snapshot_b = build_current_snapshot(
        fighter_b,
        args.division,
        fight_date,
        hist_stats,
        profile_map,
        overall_elo,
        division_elo,
    )

    manual_profile_fallback_fighters = []
    manual_profile_warnings = []
    if args.allow_manual_profile_fallback and manual_profile_names:
        for fighter, snapshot in [(fighter_a, snapshot_a), (fighter_b, snapshot_b)]:
            if normalize_name(fighter) not in manual_profile_names:
                continue
            prior_fights = pd.to_numeric(snapshot.get("ufc_fights_before", np.nan), errors="coerce")
            if pd.notna(prior_fights) and float(prior_fights) == 0.0:
                manual_profile_fallback_fighters.append(fighter)
                manual_profile_warnings.extend(
                    [
                        f"{fighter}: manual profile fallback used",
                        f"{fighter}: no confirmed UFC history",
                    ]
                )
        if manual_profile_fallback_fighters:
            manual_profile_warnings.append("prediction is low-information")

    numeric_features = get_numeric_features(train_df)
    categorical_features = get_categorical_features(train_df)
    required_bases = [c[:-5] for c in numeric_features]

    fallback_filled_a = []
    fallback_filled_b = []

    if not args.no_snapshot_fallback:
        fallback_a = latest_snapshot_fallback(snapshots_df, fighter_a, fight_date)
        fallback_b = latest_snapshot_fallback(snapshots_df, fighter_b, fight_date)
        fallback_filled_a = apply_snapshot_fallback(snapshot_a, fallback_a, required_bases)
        fallback_filled_b = apply_snapshot_fallback(snapshot_b, fallback_b, required_bases)

    if args.show_fallback_keys:
        if fallback_filled_a:
            print("\nFallback-filled Fighter A bases:")
            for key in fallback_filled_a:
                print(f"  - {key}")
        if fallback_filled_b:
            print("\nFallback-filled Fighter B bases:")
            for key in fallback_filled_b:
                print(f"  - {key}")

    pred_row_forward = build_prediction_row(train_df, snapshot_a, snapshot_b, args.division)
    pred_row_reverse = build_prediction_row(train_df, snapshot_b, snapshot_a, args.division)

    feature_cols = numeric_features + categorical_features


    pred_row_forward, pred_row_reverse = inject_bayes_smoothing_features_into_prediction_rows(
        pred_row_forward=pred_row_forward,
        pred_row_reverse=pred_row_reverse,
        feature_cols=feature_cols,
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        division=args.division,
        fight_date=fight_date,
        stats_path=stats_path,
    )

    missing_model_input_forward = [c for c in feature_cols if c not in pred_row_forward.columns]
    missing_model_input_reverse = [c for c in feature_cols if c not in pred_row_reverse.columns]

    # Ensure prediction rows contain every feature column.
    for col in feature_cols:
        if col not in pred_row_forward.columns:
            pred_row_forward[col] = np.nan
        if col not in pred_row_reverse.columns:
            pred_row_reverse[col] = np.nan

    model_input_status = model_input_feature_status(pred_row_forward, pred_row_reverse, feature_cols)
    model_input_status["missing_forward"] = missing_model_input_forward
    model_input_status["missing_reverse"] = missing_model_input_reverse

    missing_a = [base for base in required_bases if base not in snapshot_a]
    missing_b = [base for base in required_bases if base not in snapshot_b]

    if not args.quiet_diagnostics:
        print_feature_diagnostics(
            model_train_df,
            snapshot_a,
            snapshot_b,
            numeric_features,
            categorical_features,
            fallback_filled_a,
            fallback_filled_b,
            model_input_status,
        )

    if args.show_method_values:
        print_method_values(stats, fighter_a, fighter_b, fight_date)

    strict_missing = (
        model_input_status["missing_forward"]
        or model_input_status["missing_reverse"]
        or model_input_status["bayesian_all_nan"]
    )
    if args.strict_features and strict_missing:
        raise ValueError(
            "Strict feature mode failed. Missing final model input feature columns. "
            f"Forward missing: {model_input_status['missing_forward'][:20]} "
            f"Reverse missing: {model_input_status['missing_reverse'][:20]} "
            f"All-NaN Bayesian inputs: {model_input_status['bayesian_all_nan'][:20]}"
        )

    return locals()


def comparison_from_prepared(prepared):
    p = prepared
    result = dict(fighter_a=p['fighter_a'], fighter_b=p['fighter_b'],
                  fight_date=p['fight_date'].strftime('%Y-%m-%d'), division=p['args'].division,
                  model_version='v1_current_ensemble', result_state='comparison',
                  warnings=list(p['manual_profile_warnings']))
    for side in ('a', 'b'):
        snapshot = p['snapshot_'+side]
        prefix = 'fighter_'+side+'_'
        live = {str(c)[len(prefix):]:v for c,v in p['pred_row_forward'].iloc[0].items() if str(c).startswith(prefix)}
        result[prefix+'snapshot'] = snapshot
        result[prefix+'comparison'] = {**snapshot, **live}
        dates = p['hist_stats'].loc[p['hist_stats']['fighter']==p['fighter_'+side], 'event_date'].dropna()
        result[prefix+'comparison']['history_max_event_date_before'] = dates.max().strftime('%Y-%m-%d') if not dates.empty else None
    return json_safe_value(result)


def predict_prepared_matchup(prepared, progress=None):
    notify = progress or stage_progress
    args = prepared['args']
    categorical_features = prepared['categorical_features']
    feature_cols = prepared['feature_cols']
    fight_date = prepared['fight_date']
    fighter_a = prepared['fighter_a']
    fighter_b = prepared['fighter_b']
    hist_stats = prepared['hist_stats']
    manual_profile_fallback_fighters = prepared['manual_profile_fallback_fighters']
    manual_profile_warnings = prepared['manual_profile_warnings']
    model_input_status = prepared['model_input_status']
    model_train_df = prepared['model_train_df']
    numeric_features = prepared['numeric_features']
    pred_row_forward = prepared['pred_row_forward']
    pred_row_reverse = prepared['pred_row_reverse']
    snapshot_a = prepared['snapshot_a']
    snapshot_b = prepared['snapshot_b']
    stats_path = prepared['stats_path']
    train_date_filter_note = prepared['train_date_filter_note']
    train_df = prepared['train_df']
    train_path = prepared['train_path']
    X_train = model_train_df[feature_cols]
    y_train = model_train_df["fighter_a_won"]

    X_pred_forward = pred_row_forward[feature_cols]
    X_pred_reverse = pred_row_reverse[feature_cols]

    models = build_models(y_train)
    pipelines = {
        name: build_model_pipeline(model, numeric_features, categorical_features)
        for name, model in models.items()
    }
    notify("cross_validation", "Cross-validating women’s ensemble weights")
    ensemble_weights = compute_model_weights(pipelines, X_train, y_train)
    predictions = []

    for model_name, pipeline in pipelines.items():
        notify("training", "Fitting women’s model: "+model_name, completed=len(predictions), total=len(pipelines))
        pipeline.fit(X_train, y_train)

        # Forward: fighter A vs fighter B.
        prob_a_forward = float(pipeline.predict_proba(X_pred_forward)[:, 1][0])

        # Reverse: fighter B vs fighter A. This predicts fighter B as the "fighter A" of the reversed row.
        prob_b_reverse = float(pipeline.predict_proba(X_pred_reverse)[:, 1][0])

        # Convert reverse result back into fighter A probability and average.
        prob_a_from_reverse = 1.0 - prob_b_reverse
        prob_a_final = (prob_a_forward + prob_a_from_reverse) / 2.0

        predictions.append(
            {
                "model": model_name,
                "fighter_a": fighter_a,
                "fighter_b": fighter_b,
                "fighter_a_forward_probability": prob_a_forward,
                "fighter_a_reverse_inverted_probability": prob_a_from_reverse,
                "fighter_a_win_probability": prob_a_final,
                "fighter_b_win_probability": 1.0 - prob_a_final,
                "direction_disagreement": abs(prob_a_forward - prob_a_from_reverse),
            }
        )

    notify("prediction", "Combining forward/reverse estimates and reliability")
    pred_df = pd.DataFrame(predictions)
    base_probs = pred_df["fighter_a_win_probability"].astype(float)
    avg_prob_a = float(base_probs.mean())
    avg_forward = float(pred_df["fighter_a_forward_probability"].astype(float).mean())
    avg_reverse_inverted = float(pred_df["fighter_a_reverse_inverted_probability"].astype(float).mean())
    avg_direction_disagreement = abs(avg_forward - avg_reverse_inverted)

    weighted_prob_a = float(
        sum(
            ensemble_weights.get(row["model"], 0.0) * float(row["fighter_a_win_probability"])
            for _, row in pred_df.iterrows()
        )
    )
    weighted_forward = float(
        sum(
            ensemble_weights.get(row["model"], 0.0) * float(row["fighter_a_forward_probability"])
            for _, row in pred_df.iterrows()
        )
    )
    weighted_reverse = float(
        sum(
            ensemble_weights.get(row["model"], 0.0) * float(row["fighter_a_reverse_inverted_probability"])
            for _, row in pred_df.iterrows()
        )
    )
    weighted_direction_disagreement = abs(weighted_forward - weighted_reverse)

    ensemble_row = {
        "model": "ensemble_average",
        "fighter_a": fighter_a,
        "fighter_b": fighter_b,
        "fighter_a_forward_probability": weighted_forward,
        "fighter_a_reverse_inverted_probability": weighted_reverse,
        "fighter_a_win_probability": weighted_prob_a,
        "fighter_b_win_probability": 1.0 - weighted_prob_a,
        "direction_disagreement": weighted_direction_disagreement,
    }

    display_pred_df = pd.concat([pred_df, pd.DataFrame([ensemble_row])], ignore_index=True)

    print("\nUFC WOMEN'S ADVANCED MATCHUP PREDICTION")
    print("=" * 100)
    print(f"Division:   {args.division}")
    print(f"Fight date: {fight_date.date()}")
    print(f"Fighter A:  {fighter_a}")
    print(f"Fighter B:  {fighter_b}")
    print(f"Training data: {train_path}")
    print(f"Training filter: {train_date_filter_note}")
    print(f"Training rows used: {len(model_train_df):,} / {len(train_df):,}")
    print(f"Stats data:    {stats_path}")

    print("\nMODEL PROBABILITIES - BIDIRECTIONAL AVERAGE")
    print("=" * 100)
    print(f"{'Model':<32} {fighter_a:<18} {fighter_b:<18} {'Disagree':<12}")
    print("-" * 100)

    for _, r in display_pred_df.iterrows():
        print(
            f"{r['model']:<32} "
            f"{format_prob(r['fighter_a_win_probability']):<18} "
            f"{format_prob(r['fighter_b_win_probability']):<18} "
            f"{format_prob(r['direction_disagreement']):<12}"
        )

    print("\nENSEMBLE MODEL WEIGHTS")
    print("=" * 100)
    for model_name, weight in ensemble_weights.items():
        print(f"{model_name:<32} {weight:.3f}")

    primary = pd.Series(ensemble_row)
    primary_prob_a = float(primary["fighter_a_win_probability"])

    print("\nPRIMARY PICK - ENSEMBLE AVERAGE")
    print("=" * 100)

    if primary_prob_a >= 0.5:
        print(f"{fighter_a}: {format_prob(primary_prob_a)}")
    else:
        print(f"{fighter_b}: {format_prob(1.0 - primary_prob_a)}")

    probs = pred_df["fighter_a_win_probability"].astype(float)
    model_spread = probs.max() - probs.min()
    gb_row = pred_df[pred_df["model"] == "gb_shallow_primary"].iloc[0]
    gb_prob_a = float(gb_row["fighter_a_win_probability"])

    print("\nCONFIDENCE NOTES")
    print("=" * 100)

    primary_confidence = max(primary_prob_a, 1.0 - primary_prob_a)
    gb_confidence = max(gb_prob_a, 1.0 - gb_prob_a)
    votes_for_a = int((probs >= 0.5).sum())
    votes_for_b = int((probs < 0.5).sum())

    if votes_for_a > votes_for_b:
        vote_text = f"{fighter_a} {votes_for_a}-{votes_for_b}"
    elif votes_for_b > votes_for_a:
        vote_text = f"{fighter_b} {votes_for_b}-{votes_for_a}"
    else:
        vote_text = "Split"

    print(f"Ensemble confidence: {format_prob(primary_confidence)}")
    print(f"GB primary probability for {fighter_a}: {format_prob(gb_prob_a)}")
    print(f"GB primary confidence: {format_prob(gb_confidence)}")
    print(f"Model vote: {vote_text}")
    print(f"Model spread on {fighter_a}: {format_prob(model_spread)}")
    print(f"Ensemble direction disagreement: {format_prob(primary['direction_disagreement'])}")

    if model_spread >= 0.20:
        print("Interpretation: High model disagreement. Prefer the ensemble average for ranking, but treat as unstable and very low-confidence.")
    elif model_spread >= 0.12:
        print("Interpretation: Meaningful model disagreement. Ensemble lean only; do not treat as a clean signal.")
    elif primary_confidence < 0.56:
        print("Interpretation: Low-confidence ensemble lean.")
    elif primary_confidence < 0.62:
        print("Interpretation: Moderate-confidence ensemble lean.")
    else:
        print("Interpretation: Stronger ensemble lean, but still probabilistic.")

    reliability = compute_prediction_reliability(
        primary_prob_a=primary_prob_a,
        model_probabilities=probs,
        direction_disagreement=float(primary["direction_disagreement"]),
        votes_for_a=votes_for_a,
        votes_for_b=votes_for_b,
        training_rows_used=len(model_train_df),
        snapshot_a=snapshot_a,
        snapshot_b=snapshot_b,
        model_input_status=model_input_status,
        pred_row_forward=pred_row_forward,
    )
    print_prediction_reliability(reliability)
    if manual_profile_warnings:
        print("\nMANUAL PROFILE FALLBACK WARNINGS")
        print("=" * 100)
        for warning in manual_profile_warnings:
            print(f"- {warning}")
    market_comparison = add_model_market_edges(args.market_odds, primary_prob_a)
    predicted_fighter = fighter_a if primary_prob_a >= 0.5 else fighter_b
    market_edge = compute_market_edge_interpretation(
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        fighter_a_model_probability=primary_prob_a,
        fighter_b_model_probability=1.0 - primary_prob_a,
        fighter_a_no_vig_market_probability=market_comparison.get("fighter_a_no_vig_market_probability"),
        fighter_b_no_vig_market_probability=market_comparison.get("fighter_b_no_vig_market_probability"),
        fighter_a_model_minus_market=market_comparison.get("fighter_a_model_minus_market"),
        fighter_b_model_minus_market=market_comparison.get("fighter_b_model_minus_market"),
        predicted_winner=predicted_fighter,
        reliability_label=reliability["label"],
        reliability_score=int(reliability["score"]),
        model_spread=model_spread,
        direction_disagreement=float(primary["direction_disagreement"]),
        model_vote=vote_text,
    )

    summary = build_structured_prediction_summary(
        args=args,
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        fight_date=fight_date,
        train_path=train_path,
        stats_path=stats_path,
        model_train_df=model_train_df,
        train_df=train_df,
        pred_df=pred_df,
        ensemble_row=ensemble_row,
        reliability=reliability,
        primary_prob_a=primary_prob_a,
        primary_confidence=primary_confidence,
        votes_for_a=votes_for_a,
        votes_for_b=votes_for_b,
        vote_text=vote_text,
        model_spread=model_spread,
        model_input_status=model_input_status,
        snapshot_a=snapshot_a,
        snapshot_b=snapshot_b,
        market_comparison=market_comparison,
        market_edge=market_edge,
        ensemble_weights=ensemble_weights,
        pred_row_forward=pred_row_forward,
    )
    for side, fighter in (("a", fighter_a), ("b", fighter_b)):
        history_dates = hist_stats.loc[hist_stats["fighter"] == fighter, "event_date"].dropna()
        summary[f"fighter_{side}_comparison"]["history_max_event_date_before"] = (
            pd.Timestamp(history_dates.max()).strftime("%Y-%m-%d") if not history_dates.empty else None
        )
    summary["manual_profile_fallback_used"] = bool(manual_profile_fallback_fighters)
    summary["manual_profile_fallback_fighters"] = manual_profile_fallback_fighters
    summary["manual_profile_warnings"] = manual_profile_warnings
    if args.json_out:
        json_out_path = Path(args.json_out)
        json_out_path.parent.mkdir(parents=True, exist_ok=True)
        json_out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nSaved structured prediction summary: {json_out_path}")

    print_market_comparison(args, fighter_a, fighter_b, primary_prob_a, market_comparison)
    print_market_edge_interpretation(market_edge, reliability["label"], int(reliability["score"]))
    print_advantage_table(snapshot_a, snapshot_b, fighter_a, fighter_b)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        display_pred_df.to_csv(out_path, index=False)
        print(f"\nSaved prediction file: {out_path}")

    return json_safe_value(summary)


def main():
    prepared = prepare_matchup(parse_args())
    return predict_prepared_matchup(prepared)


if __name__ == "__main__":
    main()
