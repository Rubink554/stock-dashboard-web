from __future__ import annotations

from datetime import datetime, timezone


DEFAULT_WEIGHTS = {
    "value": 0.25,
    "quality": 0.30,
    "momentum": 0.25,
    "growth": 0.10,
    "stability": 0.10,
}


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def score_metrics(metrics: dict, weights: dict | None = None) -> dict:
    weights = normalize_weights(weights or DEFAULT_WEIGHTS)
    per = metrics.get("per")
    pbr = metrics.get("pbr")
    roe = metrics.get("roe")
    op_margin = metrics.get("operating_margin")
    debt_ratio = metrics.get("debt_ratio")
    ytd = metrics.get("ytd")
    m1 = metrics.get("m1")
    d1 = metrics.get("d1")
    revenue_growth = metrics.get("revenue_growth")
    op_growth = metrics.get("operating_income_growth")
    high52 = metrics.get("high52")
    low52 = metrics.get("low52")
    price = metrics.get("price")

    value_parts = []
    if isinstance(per, (int, float)) and per > 0:
        value_parts.append(clamp(100 - per * 2.5))
    if isinstance(pbr, (int, float)) and pbr > 0:
        value_parts.append(clamp(100 - pbr * 20))
    value_score = avg(value_parts, 50)

    quality_parts = []
    if isinstance(roe, (int, float)):
        quality_parts.append(clamp(roe * 4))
    if isinstance(op_margin, (int, float)):
        quality_parts.append(clamp(op_margin * 250))
    if isinstance(debt_ratio, (int, float)):
        quality_parts.append(clamp(100 - debt_ratio * 0.35))
    quality_score = avg(quality_parts, 50)

    momentum_parts = []
    for value, multiplier in [(ytd, 35), (m1, 80), (d1, 160)]:
        if isinstance(value, (int, float)):
            momentum_parts.append(clamp(50 + value * multiplier))
    momentum_score = avg(momentum_parts, 50)

    growth_parts = []
    if isinstance(revenue_growth, (int, float)):
        growth_parts.append(clamp(50 + revenue_growth * 120))
    if isinstance(op_growth, (int, float)):
        growth_parts.append(clamp(50 + op_growth * 100))
    growth_score = avg(growth_parts, 50)

    stability_score = 50
    if all(isinstance(v, (int, float)) for v in [price, high52, low52]) and high52 != low52:
        position = clamp((price - low52) / (high52 - low52), 0, 1)
        stability_score = clamp((1 - abs(position - 0.5)) * 100)

    total = (
        value_score * weights["value"]
        + quality_score * weights["quality"]
        + momentum_score * weights["momentum"]
        + growth_score * weights["growth"]
        + stability_score * weights["stability"]
    )
    return {
        "value_score": round(value_score, 2),
        "quality_score": round(quality_score, 2),
        "momentum_score": round(momentum_score, 2),
        "growth_score": round(growth_score, 2),
        "stability_score": round(stability_score, 2),
        "total_score": round(total, 2),
        "calculated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def avg(values: list[float], fallback: float) -> float:
    return sum(values) / len(values) if values else fallback


def normalize_weights(weights: dict) -> dict:
    merged = {**DEFAULT_WEIGHTS, **{k: float(v) for k, v in weights.items() if k in DEFAULT_WEIGHTS}}
    total = sum(merged.values()) or 1
    return {key: value / total for key, value in merged.items()}
