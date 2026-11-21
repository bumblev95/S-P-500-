"""Frozen forecast-combination rules for prospective-blend-v1."""
from __future__ import annotations

from datetime import date, timedelta

HORIZON = 21
COHORT_COUNT = 5
DIRECTION_CUTOFF = 0.02
V5_WEIGHT = 0.50
# SHA-256 of the protocol committed on 2026-10-23 before candidate code was
# added. A later protocol edit must use a new version rather than changing this
# prospective study after registration.
REGISTERED_PROTOCOL_SHA256 = "c2608373068c24f4a2512c1bb07fe68aefa642b6c574e6218649bb78e10cb674"

# Official NYSE full-closure dates for the enrollment window. Early-close days
# remain sessions. Keep this list aligned with the linked NYSE calendar and
# fail closed outside these years rather than silently treating weekdays as
# sessions.
XNYS_HOLIDAYS = frozenset({
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
    "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06",
    "2027-11-25", "2027-12-24",
})
XNYS_EARLY_CLOSES = frozenset({
    "2026-11-27", "2026-12-24", "2027-11-26",
})


def is_xnys_session(day_value: str) -> bool:
    day = date.fromisoformat(day_value)
    if day.year not in (2026, 2027):
        raise ValueError("The frozen prospective calendar covers 2026–2027 only")
    return day.weekday() < 5 and day_value not in XNYS_HOLIDAYS


def direction(value: float) -> int:
    """Map a simple return to down/flat/up using the preregistered ±2% rule."""
    return 1 if value > DIRECTION_CUTOFF else -1 if value < -DIRECTION_CUTOFF else 0


def sessions_after(origin: str, count: int = HORIZON) -> list[str]:
    """Return XNYS full and early-close sessions strictly after ``origin``."""
    start = date.fromisoformat(origin)
    if start.year not in (2026, 2027) or count < 1:
        raise ValueError("The frozen prospective calendar covers 2026–2027 only")
    if not is_xnys_session(origin):
        raise ValueError(f"Forecast origin is not an XNYS session: {origin}")
    out: list[str] = []
    day = start + timedelta(days=1)
    while len(out) < count:
        if day.year not in (2026, 2027):
            raise ValueError("Target exceeds the frozen 2026–2027 XNYS calendar")
        iso = day.isoformat()
        if day.weekday() < 5 and iso not in XNYS_HOLIDAYS:
            out.append(iso)
        day += timedelta(days=1)
    return out


def target_date(origin: str, horizon: int = HORIZON) -> str:
    return sessions_after(origin, horizon)[-1]


def component_return(point: float, component_anchor: float) -> float:
    if component_anchor <= 0:
        raise ValueError("Forecast anchors must be positive")
    return float(point) / float(component_anchor) - 1.0


def build_methods(v5_return: float, trend_return: float, common_anchor: float) -> dict:
    """Build control and candidate point forecasts without rounding or fitting."""
    if common_anchor <= 0:
        raise ValueError("The common origin anchor must be positive")
    fixed = V5_WEIGHT * v5_return + (1.0 - V5_WEIGHT) * trend_return
    override = trend_return if direction(trend_return) == -1 else v5_return
    returns = {
        "noChange": 0.0,
        "v5": float(v5_return),
        "simpleTrend": float(trend_return),
        "fixed50": fixed,
        "downsideOverride": override,
    }
    methods = {}
    for name, predicted_return in returns.items():
        point = common_anchor * (1.0 + predicted_return)
        if point <= 0:
            raise ValueError(f"Non-positive derived point forecast for {name}")
        methods[name] = {
            "predictedReturn": predicted_return,
            "predictedPrice": point,
            "direction": direction(predicted_return),
        }
    return methods


def metric(rows: list[dict], method: str) -> dict:
    """Score one frozen symbol cohort against its fixed target prices."""
    if not rows:
        raise ValueError("Cannot score an empty cohort")
    actual = [float(row["actualReturn"]) for row in rows]
    predicted = [float(row["methods"][method]["predictedReturn"]) for row in rows]
    targets = [float(row["targetPrice"]) for row in rows]
    prices = [float(row["methods"][method]["predictedPrice"]) for row in rows]
    actual_labels = [direction(value) for value in actual]
    predicted_labels = [direction(value) for value in predicted]

    up_total = sum(label == 1 for label in actual_labels)
    down_total = sum(label == -1 for label in actual_labels)
    down_warnings = sum(label == -1 for label in predicted_labels)
    true_down = sum(a == -1 and p == -1 for a, p in zip(actual_labels, predicted_labels))
    false_down = sum(a != -1 and p == -1 for a, p in zip(actual_labels, predicted_labels))
    return {
        "n": len(rows),
        "actualUp": up_total,
        "actualDown": down_total,
        "downWarnings": down_warnings,
        "falseDownWarnings": false_down,
        "mape": 100.0 * sum(abs(p / t - 1.0) for p, t in zip(prices, targets)) / len(rows),
        "returnMaePctPoints": 100.0 * sum(abs(p - a) for p, a in zip(predicted, actual)) / len(rows),
        "upRecall": (100.0 * sum(a == 1 and p == 1 for a, p in zip(actual_labels, predicted_labels)) / up_total
                     if up_total else None),
        "downRecall": 100.0 * true_down / down_total if down_total else None,
        "downWarningPrecision": 100.0 * true_down / down_warnings if down_warnings else None,
        "falseDownWarningRate": 100.0 * false_down / len(rows),
    }


def equal_origin_mean(metrics: list[dict], key: str):
    values = [float(item[key]) for item in metrics if item.get(key) is not None]
    return sum(values) / len(values) if values else None


def joint_gate(origin_metrics: dict[str, list[dict]]) -> dict:
    """Apply the frozen no-production joint success rule to five origin scores."""
    n_origins = len(origin_metrics["v5"])
    down_origins = sum(item["actualDown"] > 0 for item in origin_metrics["v5"])
    if n_origins < COHORT_COUNT or down_origins < 2:
        return {
            "evaluable": False,
            "passed": False,
            "reason": "requires_five_complete_origins_and_actual_downs_in_at_least_two_origins",
            "origins": n_origins,
            "originsWithActualDowns": down_origins,
        }

    warning_origins = {
        name: sum(item["downWarnings"] > 0 for item in origin_metrics[name])
        for name in ("simpleTrend", "fixed50", "downsideOverride")
    }
    if any(count < 2 for count in warning_origins.values()):
        return {
            "evaluable": False,
            "passed": False,
            "reason": "down_warning_precision_requires_warnings_in_at_least_two_origins",
            "origins": n_origins,
            "originsWithActualDowns": down_origins,
            "originsWithDownWarnings": warning_origins,
        }

    summary = {
        name: {key: equal_origin_mean(values, key) for key in (
            "mape", "returnMaePctPoints", "upRecall", "downRecall",
            "downWarningPrecision", "falseDownWarningRate",
        )}
        for name, values in origin_metrics.items()
    }
    required_keys = {
        "v5": ("mape", "returnMaePctPoints", "upRecall", "downRecall", "falseDownWarningRate"),
        "simpleTrend": ("downRecall", "downWarningPrecision", "falseDownWarningRate"),
        "fixed50": ("mape", "returnMaePctPoints", "upRecall", "downRecall",
                    "downWarningPrecision", "falseDownWarningRate"),
        "downsideOverride": ("mape", "returnMaePctPoints", "upRecall", "downRecall",
                             "downWarningPrecision", "falseDownWarningRate"),
    }
    # Null metrics mean that an essential denominator is absent; they never pass.
    evaluable = all(summary[method][key] is not None
                    for method, keys in required_keys.items() for key in keys)
    if not evaluable:
        return {"evaluable": False, "passed": False, "reason": "required_metric_undefined",
                "origins": n_origins, "originsWithActualDowns": down_origins, "summary": summary}

    def passes(candidate: str) -> bool:
        cand = summary[candidate]
        return all((
            cand["mape"] <= summary["v5"]["mape"],
            cand["returnMaePctPoints"] <= summary["v5"]["returnMaePctPoints"],
            cand["downRecall"] >= summary["simpleTrend"]["downRecall"],
            cand["downRecall"] > summary["v5"]["downRecall"],
            cand["downWarningPrecision"] >= summary["simpleTrend"]["downWarningPrecision"],
            cand["falseDownWarningRate"] <= summary["simpleTrend"]["falseDownWarningRate"],
            cand["upRecall"] >= summary["v5"]["upRecall"],
        ))

    checks = {"fixed50": passes("fixed50"), "downsideOverride": passes("downsideOverride")}
    return {"evaluable": True, "passed": any(checks.values()), "reason": "frozen_joint_gate",
            "origins": n_origins, "originsWithActualDowns": down_origins,
            "originsWithDownWarnings": warning_origins,
            "summary": summary,
            "candidateChecks": checks,
            "productionPromotion": False}
