from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
import json
import math
import sys
from analyzer_protocol import progress as stage_progress


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.model_registry import (
    DEFAULT_MODEL_VERSION,
    get_model_config,
    resolve_training_path,
)
from src.models.train_baseline import (
    TARGET_COLUMN,
    build_ensemble_base_pipelines,
    build_model_pipeline,
    compute_model_weights,
)


DEFAULT_TRAINING = "data/processed/mens_training_rows_with_elo.csv"
DEFAULT_TRAINING_V2 = "data/processed/mens_training_rows_v2_advanced.csv"
DEFAULT_RAW_DIR = "data/raw/ufcstats_men"
PREDICTION_FIGHT_ID = "__prediction_matchup__"
PREDICTION_EVENT_ID = "__prediction_event__"
MIN_TRAINING_ROWS = 200
MIN_TRAINING_FIGHTS = 100

MEN_WEIGHT_CLASS_ALIASES = {
    "heavyweight": "Heavyweight",
    "heavy weight": "Heavyweight",
    "hw": "Heavyweight",
    "light heavyweight": "Light Heavyweight",
    "lightheavyweight": "Light Heavyweight",
    "lhw": "Light Heavyweight",
    "middleweight": "Middleweight",
    "middle weight": "Middleweight",
    "mw": "Middleweight",
    "welterweight": "Welterweight",
    "welter weight": "Welterweight",
    "ww": "Welterweight",
    "lightweight": "Lightweight",
    "light weight": "Lightweight",
    "lw": "Lightweight",
    "featherweight": "Featherweight",
    "feather weight": "Featherweight",
    "fw": "Featherweight",
    "bantamweight": "Bantamweight",
    "bantam weight": "Bantamweight",
    "bw": "Bantamweight",
    "flyweight": "Flyweight",
    "fly weight": "Flyweight",
    "flw": "Flyweight",
    "catchweight": "Catch Weight",
    "catch weight": "Catch Weight",
    "openweight": "Open Weight",
    "open weight": "Open Weight",
    "super heavyweight": "Super Heavyweight",
    "unknown": "Unknown",
}

NON_STANDARD_WEIGHT_CLASSES = {"Catch Weight", "Open Weight", "Super Heavyweight", "Unknown"}
SNAPSHOT_WARNING_FIELDS = [
    ("age_at_fight", "age"),
    ("height_cm", "height"),
    ("reach_cm", "reach"),
    ("stance", "stance"),
]
PROFILE_INPUT_FIELDS = ["height_cm", "reach_cm", "stance", "date_of_birth"]


@dataclass(frozen=True)
class PredictionResources:
    training_path: Path
    raw_dir: Path
    model_version: str
    training_df: Any
    fights: Any
    fighters_raw: Any
    fight_stats: Any
    fighters_lookup: Any


@dataclass(frozen=True)
class ModelBundle:
    fight_date: Any
    model_version: str
    model_name: str
    feature_policy: str
    logistic_c: float
    registered_shrink_factor: float
    model: Any
    features: list[str]
    training_summary: dict[str, Any]


def _clean_weight_key(value: str) -> str:
    return " ".join(str(value).replace("-", " ").replace("_", " ").casefold().split())


def normalize_weight_class(value: Any) -> tuple[str, str | None]:
    import pandas as pd

    if value is None or pd.isna(value) or str(value).strip() == "":
        return "Unknown", None
    text = str(value).strip()
    key = _clean_weight_key(text)
    if key in MEN_WEIGHT_CLASS_ALIASES:
        return MEN_WEIGHT_CLASS_ALIASES[key], None
    title = " ".join(part.capitalize() for part in key.split())
    return title or "Unknown", f"Unrecognized weight class spelling '{text}' was passed through as '{title}'."


def is_non_standard_weight_class(weight_class: str) -> bool:
    return weight_class in NON_STANDARD_WEIGHT_CLASSES


def _json_default(value: Any) -> Any:
    try:
        import numpy as np
        import pandas as pd

        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            if np.isnan(value):
                return None
            return float(value)
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d") if pd.notna(value) else None
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _jsonable(value: Any) -> Any:
    try:
        import numpy as np
        import pandas as pd

        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            return None if np.isnan(value) else float(value)
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d") if pd.notna(value) else None
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def serialize_prediction(payload: dict[str, Any]) -> dict[str, Any]:
    return _jsonable(payload)


def dump_prediction_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(serialize_prediction(payload), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _num(value: Any, *, default: float = float("nan")) -> float:
    import pandas as pd

    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return default if pd.isna(parsed) else float(parsed)


def _optional_text(value: Any, default: str = "Unknown") -> str:
    import pandas as pd

    if pd.isna(value) or str(value).strip() == "":
        return default
    return str(value).strip()


def _date_text(value: Any) -> str | None:
    import pandas as pd

    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _profile_text(value: Any) -> str:
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()


def _profile_supplied(profile: dict[str, Any] | None) -> bool:
    if not profile:
        return False
    marker = _profile_text(profile.get("manual_profile")).casefold()
    if marker in {"1", "1.0", "true", "yes", "y", "manual_profile"}:
        return True
    return any(_profile_text(profile.get(field)) for field in PROFILE_INPUT_FIELDS)


def _manual_profile_details(fighter: Any) -> dict[str, Any]:
    details = getattr(fighter, "details", {}) or {}
    if not details.get("manual_profile"):
        return {}
    return {
        field: details.get(field)
        for field in PROFILE_INPUT_FIELDS
        if details.get(field) not in {None, ""}
    }


def _manual_profile_missing_warnings(label: str, profile: dict[str, Any], warnings: list[str]) -> None:
    labels = {
        "height_cm": "height",
        "reach_cm": "reach",
        "stance": "stance",
        "date_of_birth": "date of birth",
    }
    for field, display in labels.items():
        if not _profile_text(profile.get(field)):
            warnings.append(
                f"{label} manual profile missing {display}; model imputation/Unknown handling will be used."
            )


def parse_fight_date(value: Any) -> Any:
    import pandas as pd

    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid fight date: {value}")
    return parsed


def parse_as_of_date(value: Any) -> Any:
    import pandas as pd

    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Invalid as-of date: {value}")
    return parsed.normalize()


def today_timestamp() -> Any:
    import pandas as pd

    return pd.Timestamp(date.today()).normalize()


def resolve_training_as_of_date(fight_date: Any, as_of_date: Any = None) -> tuple[Any, str, bool]:
    import pandas as pd

    parsed_fight_date = parse_fight_date(fight_date).normalize()
    if as_of_date is not None and str(as_of_date).strip() != "":
        return parse_as_of_date(as_of_date), "explicit", True

    today = today_timestamp()
    if parsed_fight_date >= today:
        return today, "default_today_for_live_or_future_fight", True

    return parsed_fight_date - pd.Timedelta(days=1), "default_day_before_historical_fight", False


def load_training_data(
    training_path: str | Path | None = None,
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> Any:
    from src.models.train_baseline import read_training

    return read_training(resolve_training_path(training_path, model_version))


def load_raw_data(raw_dir: str | Path = DEFAULT_RAW_DIR) -> dict[str, Any]:
    import pandas as pd

    raw_path = Path(raw_dir)
    fights_path = raw_path / "fights.csv"
    fighters_path = raw_path / "fighters.csv"
    stats_path = raw_path / "fight_stats.csv"
    for path in [fights_path, fighters_path, stats_path]:
        if not path.exists():
            raise FileNotFoundError(path)
    fights = pd.read_csv(fights_path)
    fighters = pd.read_csv(fighters_path)
    fight_stats = pd.read_csv(stats_path)
    fights["event_date"] = pd.to_datetime(fights["event_date"], errors="coerce")
    fight_stats["event_date"] = pd.to_datetime(fight_stats["event_date"], errors="coerce")
    return {"fights": fights, "fighters_raw": fighters, "fight_stats": fight_stats}


def load_prediction_resources(
    *,
    training_path: str | Path | None = None,
    raw_dir: str | Path = DEFAULT_RAW_DIR,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> PredictionResources:
    from src.prediction.fighter_lookup import load_fighters

    raw_path = Path(raw_dir)
    resolved_training = resolve_training_path(training_path, model_version)
    raw_data = load_raw_data(raw_path)
    return PredictionResources(
        training_path=resolved_training,
        raw_dir=raw_path,
        model_version=model_version,
        training_df=load_training_data(resolved_training, model_version=model_version),
        fights=raw_data["fights"],
        fighters_raw=raw_data["fighters_raw"],
        fight_stats=raw_data["fight_stats"],
        fighters_lookup=load_fighters(str(raw_path / "fighters.csv")),
    )


def _fighter_in_fight_mask(fights: Any, fighter_id: str) -> Any:
    return (fights["fighter_red_id"].astype(str) == fighter_id) | (
        fights["fighter_blue_id"].astype(str) == fighter_id
    )


def infer_weight_class(
    fights: Any,
    fighter_a_id: str,
    fighter_b_id: str,
    fight_date: Any,
    warnings: list[str],
) -> str:
    import pandas as pd

    prior = fights[pd.to_datetime(fights["event_date"], errors="coerce") < fight_date].copy()

    def latest_for(fighter_id: str) -> dict[str, str] | None:
        rows = prior[_fighter_in_fight_mask(prior, fighter_id)].sort_values(
            ["event_date", "fight_id"], ascending=[False, True]
        )
        if rows.empty:
            return None
        row = rows.iloc[0]
        weight_class, warning = normalize_weight_class(row.get("weight_class"))
        if warning:
            warnings.append(warning)
        return {
            "weight_class": weight_class,
            "event_date": pd.to_datetime(row.get("event_date")).strftime("%Y-%m-%d"),
            "fight_id": str(row.get("fight_id")),
        }

    latest_a = latest_for(fighter_a_id)
    latest_b = latest_for(fighter_b_id)
    if latest_a and latest_b and latest_a["weight_class"] == latest_b["weight_class"]:
        return latest_a["weight_class"]
    if latest_a and latest_b:
        warnings.append(
            "Weight class inference was uncertain: latest prior classes differ "
            f"({latest_a['weight_class']} on {latest_a['event_date']} vs "
            f"{latest_b['weight_class']} on {latest_b['event_date']}). Using Unknown."
        )
        return "Unknown"
    if latest_a or latest_b:
        latest = latest_a or latest_b
        assert latest is not None
        warnings.append(
            "Weight class inferred from only one fighter's latest prior UFC fight "
            f"({latest['weight_class']} on {latest['event_date']})."
        )
        return latest["weight_class"]
    warnings.append("Weight class could not be inferred from prior UFC fights. Using Unknown.")
    return "Unknown"


def build_prediction_snapshots(
    *,
    fights: Any,
    fighters: Any,
    fight_stats: Any,
    fighter_a: Any,
    fighter_b: Any,
    fight_date: Any,
    weight_class: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    snapshot_a, snapshot_b = build_target_prefight_snapshots(
        fights=fights,
        fighters=fighters,
        fight_stats=fight_stats,
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        fight_date=fight_date,
        weight_class=weight_class,
    )
    elo_a, elo_b = build_target_elo_snapshots(
        fights=fights,
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        fight_date=fight_date,
        weight_class=weight_class,
    )
    return snapshot_a, snapshot_b, elo_a, elo_b


def build_target_prefight_snapshots(
    *,
    fights: Any,
    fighters: Any,
    fight_stats: Any,
    fighter_a: Any,
    fighter_b: Any,
    fight_date: Any,
    weight_class: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from collections import defaultdict

    import numpy as np
    import pandas as pd

    from src.features.mens_features import (
        _snapshot_from_history,
        _update_history,
        _zero_history,
        add_opponent_stats,
    )

    prior_fights = fights[fights["event_date"] < fight_date].copy()
    prior_stats = fight_stats[fight_stats["event_date"] < fight_date].copy()
    stats = add_opponent_stats(prior_stats)
    fights_meta = prior_fights[
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
    target_ids = {fighter_a.fighter_id, fighter_b.fighter_id}
    stats = stats[stats["fighter_id"].astype(str).isin(target_ids)].copy()
    stats = stats.sort_values(["event_date", "event_id", "fight_id", "fighter_id"]).reset_index(
        drop=True
    )

    profiles = fighters.copy()
    profiles["fighter_id"] = profiles["fighter_id"].astype(str).str.strip()
    if "date_of_birth" in profiles.columns:
        profiles["date_of_birth"] = pd.to_datetime(profiles["date_of_birth"], errors="coerce")
    for column in ["height_cm", "reach_cm", "weight_lbs"]:
        if column in profiles.columns:
            profiles[column] = pd.to_numeric(profiles[column], errors="coerce")
    profile_keep = [
        column
        for column in [
            "fighter_id",
            "fighter_name",
            "date_of_birth",
            "height_cm",
            "reach_cm",
            "weight_lbs",
            "stance",
        ]
        if column in profiles.columns
    ]
    profile_map = profiles[profile_keep].drop_duplicates("fighter_id").set_index("fighter_id").to_dict(
        "index"
    )

    histories = defaultdict(_zero_history)
    for _, row in stats.iterrows():
        _update_history(histories[str(row.get("fighter_id")).strip()], row)

    def snapshot_for(fighter: Any, opponent: Any) -> dict[str, Any]:
        profile = dict(profile_map.get(fighter.fighter_id, {}))
        profile.update(_manual_profile_details(fighter))
        snapshot = {
            "fight_id": PREDICTION_FIGHT_ID,
            "event_id": PREDICTION_EVENT_ID,
            "event_date": fight_date,
            "weight_class": weight_class,
            "is_catchweight_or_openweight": is_non_standard_weight_class(weight_class),
            "fighter_id": fighter.fighter_id,
            "fighter_name": fighter.fighter_name or profile.get("fighter_name"),
            "opponent_id": opponent.fighter_id,
            "opponent_name": opponent.fighter_name,
            "result": "prediction",
            "won": np.nan,
            "method": "",
            "round": "",
            "time": "",
            "stance": profile.get("stance"),
            "height_cm": profile.get("height_cm"),
            "reach_cm": profile.get("reach_cm"),
            "weight_lbs": profile.get("weight_lbs"),
        }
        dob = pd.to_datetime(profile.get("date_of_birth"), errors="coerce")
        snapshot["age_at_fight"] = (
            (fight_date - dob).days / 365.25 if pd.notna(fight_date) and pd.notna(dob) else np.nan
        )
        snapshot.update(_snapshot_from_history(histories[fighter.fighter_id], fight_date))
        history_date = pd.to_datetime(snapshot.get("history_max_event_date_before"), errors="coerce")
        snapshot["history_max_event_date_before"] = (
            history_date.strftime("%Y-%m-%d") if pd.notna(history_date) else ""
        )
        return snapshot

    return snapshot_for(fighter_a, fighter_b), snapshot_for(fighter_b, fighter_a)


def build_target_elo_snapshots(
    *,
    fights: Any,
    fighter_a: Any,
    fighter_b: Any,
    fight_date: Any,
    weight_class: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from collections import defaultdict, deque

    import numpy as np
    import pandas as pd

    from src.features.mens_elo import DECISIVE_RESULT, EloConfig, update_elo_pair

    config = EloConfig()
    prior = fights[fights["event_date"] < fight_date].copy()
    prior["event_date"] = pd.to_datetime(prior["event_date"], errors="coerce")
    prior = prior.sort_values(["event_date", "event_id", "fight_id"]).reset_index(drop=True)

    ratings: dict[str, float] = defaultdict(lambda: config.starting_elo)
    division_ratings: dict[tuple[str, str], float] = defaultdict(lambda: config.starting_elo)
    rating_history: dict[str, deque[float]] = defaultdict(deque)
    last_update_dates: dict[str, Any] = {}
    opponent_elo_history: dict[str, deque[float]] = defaultdict(
        lambda: deque(maxlen=config.opponent_summary_fights)
    )

    for _, fight in prior.iterrows():
        result = _optional_text(fight.get("result"), "")
        winner_id = _optional_text(fight.get("winner_id"), "")
        loser_id = _optional_text(fight.get("loser_id"), "")
        red_id = _optional_text(fight.get("fighter_red_id"), "")
        blue_id = _optional_text(fight.get("fighter_blue_id"), "")
        if (
            result != DECISIVE_RESULT
            or not winner_id
            or not loser_id
            or winner_id == loser_id
            or winner_id not in {red_id, blue_id}
            or loser_id not in {red_id, blue_id}
        ):
            continue

        event_date = pd.to_datetime(fight.get("event_date"), errors="coerce")
        division = _optional_text(fight.get("weight_class"), "Unknown")
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

        div_winner_key = (winner_id, division)
        div_loser_key = (loser_id, division)
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

    def recent_trend(fighter_id: str, current_rating: float) -> float:
        history = rating_history[fighter_id]
        if not history:
            return 0.0
        lookback = min(config.trend_fights, len(history))
        return current_rating - float(list(history)[-lookback])

    def snapshot_for(fighter: Any, opponent: Any, side: str) -> dict[str, Any]:
        fighter_id = fighter.fighter_id
        overall = float(ratings[fighter_id])
        division = float(division_ratings[(fighter_id, weight_class)])
        opponent_history = list(opponent_elo_history.get(fighter_id, []))
        last_update = last_update_dates.get(fighter_id)
        days_since = np.nan
        if last_update is not None and pd.notna(last_update):
            days_since = float((fight_date - last_update).days)
        return {
            "fight_id": PREDICTION_FIGHT_ID,
            "event_id": PREDICTION_EVENT_ID,
            "event_date": fight_date,
            "weight_class": weight_class,
            "fighter_id": fighter_id,
            "opponent_id": opponent.fighter_id,
            "side": side,
            "result": "prediction",
            "elo_before": overall,
            "division_elo_before": division,
            "elo_recent_trend": recent_trend(fighter_id, overall),
            "days_since_elo_update": days_since,
            "avg_opponent_elo_before": float(np.mean(opponent_history)) if opponent_history else np.nan,
            "last_elo_update_date_before": last_update,
        }

    return snapshot_for(fighter_a, fighter_b, "red"), snapshot_for(fighter_b, fighter_a, "blue")


def _add_data_quality_warnings(
    *,
    fighter_label: str,
    snapshot: dict[str, Any],
    warnings: list[str],
) -> None:
    import pandas as pd

    for column, label in SNAPSHOT_WARNING_FIELDS:
        value = snapshot.get(column)
        if pd.isna(value) or str(value).strip() == "":
            warnings.append(f"{fighter_label} is missing {label}; model imputation/Unknown handling will be used.")
    if _num(snapshot.get("ufc_fights_before"), default=0.0) == 0:
        warnings.append(f"{fighter_label} has no prior UFC fights before the selected fight date.")


def build_matchup_row(
    *,
    fighter_a: Any,
    fighter_b: Any,
    snapshot_a: dict[str, Any],
    snapshot_b: dict[str, Any],
    elo_a: dict[str, Any],
    elo_b: dict[str, Any],
    fight_date: Any,
    weight_class: str,
) -> dict[str, Any]:
    import numpy as np

    from src.features.mens_features import DIFF_FEATURES, stance_matchup

    row: dict[str, Any] = {
        "fight_id": PREDICTION_FIGHT_ID,
        "event_id": PREDICTION_EVENT_ID,
        "event_date": fight_date.strftime("%Y-%m-%d"),
        "weight_class": weight_class,
        "is_catchweight_or_openweight": str(is_non_standard_weight_class(weight_class)),
        "fighter_a_id": fighter_a.fighter_id,
        "fighter_b_id": fighter_b.fighter_id,
        "fighter_a": fighter_a.fighter_name,
        "fighter_b": fighter_b.fighter_name,
        "stance_matchup": stance_matchup(snapshot_a.get("stance"), snapshot_b.get("stance")),
        "fighter_a_history_max_event_date_before": snapshot_a.get("history_max_event_date_before"),
        "fighter_b_history_max_event_date_before": snapshot_b.get("history_max_event_date_before"),
    }
    for column in DIFF_FEATURES:
        a_value = snapshot_a.get(column)
        b_value = snapshot_b.get(column)
        row[f"fighter_a_{column}"] = a_value
        row[f"fighter_b_{column}"] = b_value
        a_num = _num(a_value)
        b_num = _num(b_value)
        row[f"{column}_diff"] = np.nan if np.isnan(a_num) or np.isnan(b_num) else a_num - b_num

    elo_columns = [
        "elo_before",
        "division_elo_before",
        "elo_recent_trend",
        "days_since_elo_update",
        "avg_opponent_elo_before",
    ]
    for column in elo_columns:
        row[f"fighter_a_{column}"] = elo_a.get(column)
        row[f"fighter_b_{column}"] = elo_b.get(column)
    row["elo_diff"] = _num(elo_a.get("elo_before")) - _num(elo_b.get("elo_before"))
    row["division_elo_diff"] = _num(elo_a.get("division_elo_before")) - _num(
        elo_b.get("division_elo_before")
    )
    row["elo_recent_trend_diff"] = _num(elo_a.get("elo_recent_trend")) - _num(
        elo_b.get("elo_recent_trend")
    )
    row["days_since_elo_update_diff"] = _num(elo_a.get("days_since_elo_update")) - _num(
        elo_b.get("days_since_elo_update")
    )
    row["avg_opponent_elo_diff"] = _num(elo_a.get("avg_opponent_elo_before")) - _num(
        elo_b.get("avg_opponent_elo_before")
    )
    return row


def train_prediction_model(
    training_path: str | Path | None = None,
    fight_date: Any = None,
    model_name: str | None = None,
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
    training_df: Any = None,
    as_of_date: Any = None,
    allow_future_training_rows: bool = False,
) -> ModelBundle:
    from src.models.train_baseline import (
        TARGET_COLUMN,
        build_model_pipeline,
    )

    if fight_date is None:
        raise ValueError("fight_date is required")
    parsed_fight_date = parse_fight_date(fight_date)
    parsed_as_of_date, as_of_source, enforce_future_training_guard = resolve_training_as_of_date(
        parsed_fight_date,
        as_of_date,
    )
    config = get_model_config(model_version)
    selected_model_name = model_name or config.model_name
    if selected_model_name != config.model_name:
        raise ValueError(
            f"Model version {config.model_version} requires model '{config.model_name}', "
            f"not '{selected_model_name}'."
        )
    resolved_training = resolve_training_path(training_path, config.model_version)
    df = (
        training_df
        if training_df is not None
        else load_training_data(resolved_training, model_version=config.model_version)
    )
    numeric_features = list(config.numeric_features)
    categorical_features = list(config.categorical_features)
    features = numeric_features + categorical_features
    missing = [feature for feature in features if feature not in df.columns]
    if missing:
        raise ValueError(f"Training data missing {config.model_version} feature columns: {missing}")
    source_future_rows = df[df["event_date"] > parsed_as_of_date].copy()
    source_future_unique_fights = int(source_future_rows["fight_id"].nunique())
    if (
        enforce_future_training_guard
        and not source_future_rows.empty
        and not allow_future_training_rows
    ):
        max_future_date = _date_text(source_future_rows["event_date"].max())
        raise ValueError(
            "Training data contains rows after as-of date "
            f"{parsed_as_of_date.strftime('%Y-%m-%d')}: "
            f"{len(source_future_rows)} rows / {source_future_unique_fights} fights, "
            f"max event_date {max_future_date}. "
            "Re-run with --allow-future-training-rows only for an explicit audited exception."
        )
    train_df = df[df["event_date"] <= parsed_as_of_date].copy()
    excluded = df[df["event_date"] > parsed_as_of_date].copy()
    excluded_on_or_after_fight = df[df["event_date"] >= parsed_fight_date].copy()
    train_unique_fights = int(train_df["fight_id"].nunique())
    if len(train_df) < MIN_TRAINING_ROWS or train_unique_fights < MIN_TRAINING_FIGHTS:
        raise ValueError(
            "Too few training rows on or before as-of date "
            f"{parsed_as_of_date.strftime('%Y-%m-%d')}: {len(train_df)} rows / "
            f"{train_unique_fights} fights."
        )
    if train_df[TARGET_COLUMN].nunique() < 2:
        raise ValueError("Training data on or before as-of date has fewer than two target classes.")

    if config.model_name == "ensemble":
        X_train = train_df[features]
        y_train = train_df[TARGET_COLUMN]
        base_pipelines = build_ensemble_base_pipelines(
            numeric_features,
            categorical_features,
            logistic_c=config.logistic_c,
            random_forest_estimators=250,
            random_state=42,
            y_train=y_train,
        )
        ensemble_weights = compute_model_weights(base_pipelines, X_train, y_train)
        model = build_model_pipeline(
            config.model_name,
            numeric_features,
            categorical_features,
            logistic_c=config.logistic_c,
            y_train=y_train,
            ensemble_weights=ensemble_weights,
        )
    else:
        model = build_model_pipeline(
            config.model_name,
            numeric_features,
            categorical_features,
            logistic_c=config.logistic_c,
        )
    model.fit(train_df[features], train_df[TARGET_COLUMN])
    training_summary = {
        "model_version": config.model_version,
        "feature_policy": config.feature_policy,
        "model_name": config.model_name,
        "logistic_c": config.logistic_c,
        "registered_shrink_factor": config.shrink_factor,
        "training_path": str(resolved_training),
        "fight_date": parsed_fight_date.strftime("%Y-%m-%d"),
        "as_of_date": parsed_as_of_date.strftime("%Y-%m-%d"),
        "as_of_date_source": as_of_source,
        "training_filter_cutoff": f"event_date <= {parsed_as_of_date.strftime('%Y-%m-%d')}",
        "training_rows": int(len(train_df)),
        "training_unique_fights": train_unique_fights,
        "training_date_min": _date_text(train_df["event_date"].min()),
        "training_date_max": _date_text(train_df["event_date"].max()),
        "actual_max_training_event_date_used": _date_text(train_df["event_date"].max()),
        "source_training_date_max": _date_text(df["event_date"].max()),
        "source_rows_after_as_of_date": int(len(source_future_rows)),
        "source_unique_fights_after_as_of_date": source_future_unique_fights,
        "future_training_rows_allowed": bool(allow_future_training_rows),
        "excluded_rows_after_as_of_date": int(len(excluded)),
        "excluded_unique_fights_after_as_of_date": int(excluded["fight_id"].nunique()),
        "excluded_rows_on_or_after_fight_date": int(len(excluded_on_or_after_fight)),
        "excluded_unique_fights_on_or_after_fight_date": int(excluded_on_or_after_fight["fight_id"].nunique()),
        "numeric_features": numeric_features,
        "categorical_features": categorical_features,
        "features_used": features,
    }
    return ModelBundle(
        fight_date=parsed_fight_date,
        model_version=config.model_version,
        model_name=config.model_name,
        feature_policy=config.feature_policy,
        logistic_c=config.logistic_c,
        registered_shrink_factor=config.shrink_factor,
        model=model,
        features=features,
        training_summary=training_summary,
    )


def predict_row(model: Any, row: dict[str, Any], features: list[str]) -> float:
    import numpy as np
    import pandas as pd

    from src.models.train_baseline import predict_positive_proba

    frame = pd.DataFrame([row])
    for feature in features:
        if feature not in frame.columns:
            frame[feature] = np.nan
    return float(predict_positive_proba(model, frame, features)[0])


def shrink_probability(probability: float, shrink_factor: float) -> float:
    return 0.5 + shrink_factor * (probability - 0.5)


def confidence_tier(winner_probability: float) -> str:
    if winner_probability < 0.55:
        return "coin flip"
    if winner_probability < 0.60:
        return "lean"
    if winner_probability < 0.70:
        return "moderate"
    if winner_probability < 0.80:
        return "strong"
    return "very strong"


def top_feature_differences(row: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    import numpy as np

    value_base_overrides = {
        "elo_diff": "elo_before",
        "division_elo_diff": "division_elo_before",
        "elo_recent_trend_diff": "elo_recent_trend",
        "days_since_elo_update_diff": "days_since_elo_update",
        "avg_opponent_elo_diff": "avg_opponent_elo_before",
    }
    items: list[dict[str, Any]] = []
    for column, value in row.items():
        if not column.endswith("_diff"):
            continue
        diff = _num(value)
        if np.isnan(diff):
            continue
        base = value_base_overrides.get(column, column[: -len("_diff")])
        items.append(
            {
                "feature": column,
                "fighter_a_value": _json_default(row.get(f"fighter_a_{base}")),
                "fighter_b_value": _json_default(row.get(f"fighter_b_{base}")),
                "difference": float(diff),
                "abs_difference": float(abs(diff)),
            }
        )
    items.sort(key=lambda item: item["abs_difference"], reverse=True)
    for item in items:
        item.pop("abs_difference", None)
    return items[:limit]


def snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    fields = [
        "age_at_fight",
        "height_cm",
        "reach_cm",
        "stance",
        "ufc_fights_before",
        "ufc_wins_before",
        "ufc_losses_before",
        "ufc_win_pct_before",
        "current_win_streak",
        "current_loss_streak",
        "days_since_last_fight",
        "career_slpm_before",
        "career_sapm_before",
        "career_td_avg_per15_before",
        "last_3_win_pct",
        "last_5_win_pct",
        "history_max_event_date_before",
    ]
    return {field: _json_default(snapshot.get(field)) for field in fields}


def prepare_feature_rows(*, fighter_a, fighter_b, fight_date, weight_class,
                         snapshot_a, snapshot_b, elo_a, elo_b, model_version,
                         warnings=None, live_v2_context=None):
    import numpy as np

    warnings = warnings or []
    comparison_a: dict[str, Any] = {}
    comparison_b: dict[str, Any] = {}
    forward_row = build_matchup_row(
        fighter_a=fighter_a,
        fighter_b=fighter_b,
        snapshot_a=snapshot_a,
        snapshot_b=snapshot_b,
        elo_a=elo_a,
        elo_b=elo_b,
        fight_date=fight_date,
        weight_class=weight_class,
    )
    reverse_row = build_matchup_row(
        fighter_a=fighter_b,
        fighter_b=fighter_a,
        snapshot_a=snapshot_b,
        snapshot_b=snapshot_a,
        elo_a=elo_b,
        elo_b=elo_a,
        fight_date=fight_date,
        weight_class=weight_class,
    )

    if model_version == "v2_smoothed_debutant":
        from src.features.mens_live_v2_features import build_live_v2_feature_rows

        if live_v2_context is None:
            raise ValueError("v2_smoothed_debutant requires a live v2 feature context.")
        v2_rows = build_live_v2_feature_rows(
            context=live_v2_context,
            fighter_a=fighter_a,
            fighter_b=fighter_b,
            fight_date=fight_date,
            weight_class=weight_class,
        )
        forward_row.update(v2_rows.forward)
        reverse_row.update(v2_rows.reverse)
        warnings.extend(v2_rows.warnings)
        comparison_a = getattr(v2_rows, "fighter_a_comparison", {})
        comparison_b = getattr(v2_rows, "fighter_b_comparison", {})
    elif model_version == "v3_bayes_smoothed":
        from src.features.mens_live_v3_bayes_features import build_live_v3_bayes_feature_rows

        if live_v2_context is None:
            raise ValueError("v3_bayes_smoothed requires a live v3 Bayesian feature context.")
        v3_rows = build_live_v3_bayes_feature_rows(
            context=live_v2_context,
            fighter_a=fighter_a.fighter_name,
            fighter_b=fighter_b.fighter_name,
            fighter_a_id=fighter_a.fighter_id,
            fighter_b_id=fighter_b.fighter_id,
            fight_date=fight_date,
            weight_class=weight_class,
        )
        forward_row.update(v3_rows.forward)
        reverse_row.update(v3_rows.reverse)
        warnings.extend(v3_rows.warnings)
        comparison_a = getattr(v3_rows, "fighter_a_comparison", {})
        comparison_b = getattr(v3_rows, "fighter_b_comparison", {})

    return dict(forward_row=forward_row, reverse_row=reverse_row,
                comparison_a=comparison_a, comparison_b=comparison_b, warnings=warnings)


def build_prediction_result(
    *,
    fighter_a: Any,
    fighter_b: Any,
    fight_date: Any,
    weight_class: str,
    snapshot_a: dict[str, Any],
    snapshot_b: dict[str, Any],
    elo_a: dict[str, Any],
    elo_b: dict[str, Any],
    model_bundle: ModelBundle,
    shrink_factor: float = 0.90,
    no_shrink: bool = False,
    warnings: list[str] | None = None,
    live_v2_context: Any = None,
    prepared_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import numpy as np
    prepared_features = prepared_features or prepare_feature_rows(
        fighter_a=fighter_a, fighter_b=fighter_b, fight_date=fight_date,
        weight_class=weight_class, snapshot_a=snapshot_a, snapshot_b=snapshot_b,
        elo_a=elo_a, elo_b=elo_b, model_version=model_bundle.model_version,
        warnings=warnings, live_v2_context=live_v2_context)
    forward_row = prepared_features['forward_row']
    reverse_row = prepared_features['reverse_row']
    comparison_a = prepared_features['comparison_a']
    comparison_b = prepared_features['comparison_b']
    warnings = prepared_features['warnings']
    missing_live_features = [feature for feature in model_bundle.features if feature not in forward_row]
    if missing_live_features:
        raise ValueError(
            f"Live feature row missing {model_bundle.model_version} columns: {missing_live_features}"
        )

    fighter_a_raw = predict_row(model_bundle.model, forward_row, model_bundle.features)
    reverse_adjusted = None
    try:
        fighter_b_raw_reverse = predict_row(model_bundle.model, reverse_row, model_bundle.features)
        reverse_adjusted = 1.0 - fighter_b_raw_reverse
    except Exception as exc:
        warnings.append(f"Reverse prediction could not be computed: {exc}")

    raw_values = [fighter_a_raw]
    if reverse_adjusted is not None and not np.isnan(reverse_adjusted):
        raw_values.append(float(reverse_adjusted))
    raw_avg = float(np.mean(raw_values))

    effective_shrink_factor = 1.0 if no_shrink else float(shrink_factor)
    final_a = float(shrink_probability(raw_avg, effective_shrink_factor))
    final_a = float(np.clip(final_a, 0.0, 1.0))
    final_b = 1.0 - final_a
    predicted_winner = fighter_a.fighter_name if final_a >= final_b else fighter_b.fighter_name
    winner_probability = max(final_a, final_b)

    training_summary = model_bundle.training_summary
    return {
        "fighter_a": fighter_a.fighter_name,
        "fighter_a_id": fighter_a.fighter_id,
        "fighter_b": fighter_b.fighter_name,
        "fighter_b_id": fighter_b.fighter_id,
        "fight_date": fight_date.strftime("%Y-%m-%d"),
        "weight_class": weight_class,
        "model": model_bundle.model_name,
        "model_version": model_bundle.model_version,
        "feature_policy": model_bundle.feature_policy,
        "logistic_c": model_bundle.logistic_c,
        "shrink_factor": effective_shrink_factor,
        "shrink_applied": not no_shrink,
        "as_of_date": training_summary["as_of_date"],
        "as_of_date_source": training_summary["as_of_date_source"],
        "training_filter_cutoff": training_summary["training_filter_cutoff"],
        "actual_max_training_event_date_used": training_summary[
            "actual_max_training_event_date_used"
        ],
        "source_training_date_max": training_summary["source_training_date_max"],
        "source_rows_after_as_of_date": training_summary["source_rows_after_as_of_date"],
        "source_unique_fights_after_as_of_date": training_summary[
            "source_unique_fights_after_as_of_date"
        ],
        "future_training_rows_allowed": training_summary["future_training_rows_allowed"],
        "fighter_a_raw_probability": fighter_a_raw,
        "fighter_a_reverse_adjusted_raw_probability": reverse_adjusted,
        "fighter_a_raw_avg_probability": raw_avg,
        "fighter_a_final_probability": final_a,
        "fighter_b_final_probability": final_b,
        "predicted_winner": predicted_winner,
        "confidence_tier": confidence_tier(winner_probability),
        "training_rows": training_summary["training_rows"],
        "training_unique_fights": training_summary["training_unique_fights"],
        "training_date_min": training_summary["training_date_min"],
        "training_date_max": training_summary["training_date_max"],
        "training_cutoff": training_summary["training_filter_cutoff"],
        "excluded_rows_after_as_of_date": training_summary["excluded_rows_after_as_of_date"],
        "excluded_unique_fights_after_as_of_date": training_summary[
            "excluded_unique_fights_after_as_of_date"
        ],
        "excluded_rows_on_or_after_fight_date": training_summary[
            "excluded_rows_on_or_after_fight_date"
        ],
        "excluded_unique_fights_on_or_after_fight_date": training_summary[
            "excluded_unique_fights_on_or_after_fight_date"
        ],
        "features_used": training_summary["features_used"],
        "numeric_features": training_summary["numeric_features"],
        "categorical_features": training_summary["categorical_features"],
        "warnings": sorted(set(warnings)),
        "top_feature_differences": top_feature_differences(forward_row),
        "fighter_a_snapshot": {str(k): _json_default(v) for k, v in snapshot_a.items()},
        "fighter_b_snapshot": {str(k): _json_default(v) for k, v in snapshot_b.items()},
        # Report the already computed live values, without changing model inputs.
        # Keep the legacy snapshots intact for existing JSON consumers.
        "fighter_a_comparison": _jsonable({
            **snapshot_a,
            **comparison_a,
            **elo_a,
            **{k[len("fighter_a_"):]: v for k, v in forward_row.items() if k.startswith("fighter_a_")},
        }),
        "fighter_b_comparison": _jsonable({
            **snapshot_b,
            **comparison_b,
            **elo_b,
            **{k[len("fighter_b_"):]: v for k, v in forward_row.items() if k.startswith("fighter_b_")},
        }),
        "feature_summary": {
            "stance_matchup": forward_row["stance_matchup"],
            "is_catchweight_or_openweight": forward_row["is_catchweight_or_openweight"],
            "fighter_a_snapshot": snapshot_summary(snapshot_a),
            "fighter_b_snapshot": snapshot_summary(snapshot_b),
            "fighter_a_elo_before": _json_default(elo_a.get("elo_before")),
            "fighter_b_elo_before": _json_default(elo_b.get("elo_before")),
            "fighter_a_division_elo_before": _json_default(elo_a.get("division_elo_before")),
            "fighter_b_division_elo_before": _json_default(elo_b.get("division_elo_before")),
        },
    }


def prepare_matchup(
    *,
    fighter_a: str,
    fighter_b: str,
    fight_date: Any,
    fighter_a_id: str | None = None,
    fighter_b_id: str | None = None,
    fighter_a_profile: dict[str, Any] | None = None,
    fighter_b_profile: dict[str, Any] | None = None,
    weight_class: Any = None,
    training_path: str | Path | None = None,
    raw_dir: str | Path = DEFAULT_RAW_DIR,
    model_name: str | None = None,
    model_version: str = DEFAULT_MODEL_VERSION,
    shrink_factor: float = 0.90,
    no_shrink: bool = False,
    as_of_date: Any = None,
    allow_future_training_rows: bool = False,
    resources: PredictionResources | None = None,
    model_bundle: ModelBundle | None = None,
    live_v2_context: Any = None,
    progress=None,
) -> dict[str, Any]:
    notify = progress or stage_progress
    from src.prediction.fighter_lookup import (
        FighterLookupError,
        format_lookup_error,
        lookup_fighter,
        lookup_fighter_by_id,
        manual_fighter_result,
        normalize_name,
    )

    if shrink_factor < 0.0 or shrink_factor > 1.0:
        raise ValueError("--shrink-factor must be between 0.0 and 1.0")

    parsed_fight_date = parse_fight_date(fight_date)
    config = get_model_config(model_version)
    selected_model_name = model_name or config.model_name
    if selected_model_name != config.model_name:
        raise ValueError(
            f"Model version {config.model_version} requires model '{config.model_name}', "
            f"not '{selected_model_name}'."
        )
    notify("loading", "Loading training data and fight history")
    resources = resources or load_prediction_resources(
        training_path=training_path,
        raw_dir=raw_dir,
        model_version=config.model_version,
    )
    warnings: list[str] = []

    def resolve_input_fighter(
        label: str,
        name: str,
        fighter_id: str | None,
        profile: dict[str, Any] | None,
    ) -> Any:
        cleaned_id = str(fighter_id or "").strip()
        allow_manual_profile = _profile_supplied(profile)
        try:
            if cleaned_id:
                result = lookup_fighter_by_id(resources.fighters_lookup, cleaned_id)
                if str(name or "").strip() and normalize_name(name) != normalize_name(result.fighter_name):
                    warnings.append(
                        f"{label} name '{name}' resolved by fighter_id {cleaned_id} to '{result.fighter_name}'."
                    )
                return result
            return lookup_fighter(resources.fighters_lookup, name)
        except FighterLookupError as exc:
            if allow_manual_profile:
                warnings.append(f"{label} has no UFC history; manual profile fallback used")
                _manual_profile_missing_warnings(label, profile or {}, warnings)
                return manual_fighter_result(name, fighter_id=cleaned_id, profile=profile or {})
            raise ValueError(format_lookup_error(exc)) from exc

    fighter_a_result = resolve_input_fighter("fighter A", fighter_a, fighter_a_id, fighter_a_profile)
    fighter_b_result = resolve_input_fighter("fighter B", fighter_b, fighter_b_id, fighter_b_profile)

    if fighter_a_result.fighter_id == fighter_b_result.fighter_id:
        raise ValueError("fighter-a and fighter-b resolve to the same fighter ID.")

    if weight_class is not None and str(weight_class).strip() != "":
        normalized_weight_class, wc_warning = normalize_weight_class(weight_class)
        if wc_warning:
            warnings.append(wc_warning)
    else:
        normalized_weight_class = infer_weight_class(
            resources.fights,
            fighter_a_result.fighter_id,
            fighter_b_result.fighter_id,
            parsed_fight_date,
            warnings,
        )
    if normalized_weight_class == "Unknown":
        warnings.append("Weight class is Unknown; division Elo uses the Unknown category.")

    notify("features", "Preparing dated fighter snapshots and Elo")
    snapshot_a, snapshot_b, elo_a, elo_b = build_prediction_snapshots(
        fights=resources.fights,
        fighters=resources.fighters_raw,
        fight_stats=resources.fight_stats,
        fighter_a=fighter_a_result,
        fighter_b=fighter_b_result,
        fight_date=parsed_fight_date,
        weight_class=normalized_weight_class,
    )
    if not snapshot_a or not snapshot_b:
        raise RuntimeError("Could not build both fighter pre-fight snapshots.")
    if not elo_a or not elo_b:
        raise RuntimeError("Could not build both fighter Elo snapshots.")

    _add_data_quality_warnings(
        fighter_label=fighter_a_result.fighter_name,
        snapshot=snapshot_a,
        warnings=warnings,
    )
    _add_data_quality_warnings(
        fighter_label=fighter_b_result.fighter_name,
        snapshot=snapshot_b,
        warnings=warnings,
    )
    if _optional_text(snapshot_a.get("stance")) == "Unknown" or _optional_text(snapshot_b.get("stance")) == "Unknown":
        warnings.append("At least one stance is missing; stance_matchup uses Unknown.")

    if config.model_version == "v2_smoothed_debutant" and live_v2_context is None:
        from src.features.mens_live_v2_features import prepare_live_v2_context

        live_v2_context = prepare_live_v2_context(resources.fights, resources.fight_stats)
    elif config.model_version == "v3_bayes_smoothed" and live_v2_context is None:
        from src.features.mens_live_v3_bayes_features import prepare_live_v3_bayes_context

        live_v2_context = prepare_live_v3_bayes_context(resources.fights, resources.fight_stats)

    prepared_features = prepare_feature_rows(
        fighter_a=fighter_a_result, fighter_b=fighter_b_result, fight_date=parsed_fight_date,
        weight_class=normalized_weight_class, snapshot_a=snapshot_a, snapshot_b=snapshot_b,
        elo_a=elo_a, elo_b=elo_b, model_version=config.model_version,
        warnings=warnings, live_v2_context=live_v2_context)
    return locals()


def comparison_from_prepared(prepared):
    p = prepared
    f = p['prepared_features']
    payload = dict(fighter_a=p['fighter_a_result'].fighter_name,
                   fighter_b=p['fighter_b_result'].fighter_name,
                   fight_date=_date_text(p['parsed_fight_date']), division=p['normalized_weight_class'],
                   model_version=p['config'].model_version, result_state='comparison',
                   warnings=sorted(set(f['warnings'])))
    for side in ('a', 'b'):
        snapshot = p['snapshot_'+side]
        elo = p['elo_'+side]
        advanced = f['comparison_'+side]
        prefix = 'fighter_'+side+'_'
        payload[prefix+'snapshot'] = snapshot
        payload[prefix+'comparison'] = {**snapshot, **advanced, **elo,
            **{k[len(prefix):]:v for k,v in f['forward_row'].items() if k.startswith(prefix)}}
    return serialize_prediction(payload)


def predict_prepared_matchup(prepared, progress=None):
    notify = progress or stage_progress
    parsed_fight_date = prepared['parsed_fight_date']
    selected_model_name = prepared['selected_model_name']
    config = prepared['config']
    resources = prepared['resources']
    as_of_date = prepared['as_of_date']
    allow_future_training_rows = prepared['allow_future_training_rows']
    model_bundle = prepared['model_bundle']
    fighter_a_result = prepared['fighter_a_result']
    fighter_b_result = prepared['fighter_b_result']
    normalized_weight_class = prepared['normalized_weight_class']
    snapshot_a = prepared['snapshot_a']
    snapshot_b = prepared['snapshot_b']
    elo_a = prepared['elo_a']
    elo_b = prepared['elo_b']
    shrink_factor = prepared['shrink_factor']
    no_shrink = prepared['no_shrink']
    warnings = prepared['warnings']
    live_v2_context = prepared['live_v2_context']
    prepared_features = prepared['prepared_features']
    notify("training", "Fitting the men’s selected model")
    if model_bundle is None:
        model_bundle = train_prediction_model(
            resources.training_path,
            parsed_fight_date,
            selected_model_name,
            model_version=config.model_version,
            training_df=resources.training_df,
            as_of_date=as_of_date,
            allow_future_training_rows=allow_future_training_rows,
        )
    else:
        bundle_date = parse_fight_date(model_bundle.fight_date).strftime("%Y-%m-%d")
        request_date = parsed_fight_date.strftime("%Y-%m-%d")
        if bundle_date != request_date:
            raise ValueError(
                f"Model bundle cutoff {bundle_date} does not match requested fight date {request_date}."
            )
        if model_bundle.model_name != selected_model_name:
            raise ValueError(
                f"Model bundle model {model_bundle.model_name} does not match requested model {selected_model_name}."
            )
        if model_bundle.model_version != config.model_version:
            raise ValueError(
                f"Model bundle version {model_bundle.model_version} does not match requested "
                f"version {config.model_version}."
            )

    notify("prediction", "Calculating forward/reverse probabilities and calibration")
    return serialize_prediction(
        build_prediction_result(
            fighter_a=fighter_a_result,
            fighter_b=fighter_b_result,
            fight_date=parsed_fight_date,
            weight_class=normalized_weight_class,
            snapshot_a=snapshot_a,
            snapshot_b=snapshot_b,
            elo_a=elo_a,
            elo_b=elo_b,
            model_bundle=model_bundle,
            shrink_factor=shrink_factor,
            no_shrink=no_shrink,
            warnings=warnings,
            live_v2_context=live_v2_context,
            prepared_features=prepared_features,
        )
    )


def predict_single_matchup(
    *,
    fighter_a: str,
    fighter_b: str,
    fight_date: Any,
    fighter_a_id: str | None = None,
    fighter_b_id: str | None = None,
    fighter_a_profile: dict[str, Any] | None = None,
    fighter_b_profile: dict[str, Any] | None = None,
    weight_class: Any = None,
    training_path: str | Path | None = None,
    raw_dir: str | Path = DEFAULT_RAW_DIR,
    model_name: str | None = None,
    model_version: str = DEFAULT_MODEL_VERSION,
    shrink_factor: float = 0.90,
    no_shrink: bool = False,
    as_of_date: Any = None,
    allow_future_training_rows: bool = False,
    resources: PredictionResources | None = None,
    model_bundle: ModelBundle | None = None,
    live_v2_context: Any = None,
    progress=None,
) -> dict[str, Any]:
    prepared = prepare_matchup(**locals())
    return predict_prepared_matchup(prepared, progress=progress)
