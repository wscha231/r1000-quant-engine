"""Shared helpers for research-only historical challenger replays."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
CASH_TICKER = "CASH"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def read_table(path_like: str | Path) -> pd.DataFrame:
    path = repo_path(path_like)
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def write_json(path_like: str | Path, payload: Any) -> None:
    path = repo_path(path_like)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path_like: str | Path, text: str) -> None:
    path = repo_path(path_like)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_rows(path_like: str | Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path = repo_path(path_like)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def blocked_payload(reason: str, required_path: Path, output_dir: Path, experiment_id: str) -> dict[str, Any]:
    payload = {
        "experiment_id": experiment_id,
        "status": "blocked",
        "reason": reason,
        "required_path": str(required_path),
        "research_only": True,
        "production_activation_allowed": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", payload)
    write_text(
        output_dir / "replay_report.md",
        f"# {experiment_id}\n\nStatus: `blocked`\n\nReason: {reason}\n\nRequired path: `{required_path}`\n",
    )
    return payload


def infer_return_col(frame: pd.DataFrame) -> str | None:
    for col in ("period_forward_return", "r_1m", "y_blend", "pred_forward_return"):
        if col in frame.columns:
            return col
    return None


def normalize_rebalance_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["rebalance_date"])
    out["rebalance_date"] = out["rebalance_date"].dt.strftime("%Y-%m-%d")
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out = out[(out["ticker"] != "") & (out["ticker"] != CASH_TICKER)]
    return out


def score_power_weights(rows: list[dict[str, Any]], score_key: str, single_name_cap: float = 1.0) -> dict[str, float]:
    if not rows:
        return {}
    scores = [safe_float(row.get(score_key), 0.0) for row in rows]
    min_score = min(scores)
    raw: dict[str, float] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker or ticker == CASH_TICKER:
            continue
        shifted = max(safe_float(row.get(score_key), 0.0) - min_score + 0.25, 1e-6)
        raw[ticker] = shifted * shifted
    total = sum(raw.values())
    if total <= 0:
        equal = 1.0 / len(raw)
        return {ticker: min(equal, single_name_cap) for ticker in raw}
    capped = {ticker: min(value / total, single_name_cap) for ticker, value in raw.items()}
    capped_sum = sum(capped.values())
    if capped_sum <= 0:
        return capped
    return {ticker: value / capped_sum for ticker, value in capped.items()}


def turnover(prev: dict[str, float], cur: dict[str, float]) -> float:
    keys = set(prev) | set(cur)
    return 0.5 * sum(abs(float(cur.get(key, 0.0)) - float(prev.get(key, 0.0))) for key in keys)


def calc_metrics(monthly_returns: list[float]) -> dict[str, Any]:
    rets = [float(x) for x in monthly_returns if math.isfinite(float(x))]
    if not rets:
        return {
            "months": 0,
            "cagr": None,
            "sharpe": None,
            "max_dd": None,
            "calmar": None,
            "vol_ann": None,
            "ending_equity": 1.0,
        }
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    curve = []
    for ret in rets:
        equity *= 1.0 + ret
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1.0)
        curve.append(equity)
    years = len(rets) / 12.0
    cagr = equity ** (1.0 / years) - 1.0 if years > 0 and equity > 0 else None
    mean = sum(rets) / len(rets)
    variance = sum((ret - mean) ** 2 for ret in rets) / len(rets)
    std = math.sqrt(variance)
    sharpe = (mean * 12.0) / (std * math.sqrt(12.0)) if std > 0 else 0.0
    vol_ann = std * math.sqrt(12.0)
    calmar = cagr / abs(max_dd) if cagr is not None and max_dd < 0 else None
    return {
        "months": len(rets),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "vol_ann": vol_ann,
        "ending_equity": equity,
    }


def equity_curve_rows(monthly_rows: list[dict[str, Any]], return_key: str = "net_return") -> list[dict[str, Any]]:
    equity = 1.0
    peak = 1.0
    out: list[dict[str, Any]] = []
    for row in monthly_rows:
        ret = safe_float(row.get(return_key), 0.0)
        equity *= 1.0 + ret
        peak = max(peak, equity)
        out.append(
            {
                **row,
                "equity": equity,
                "drawdown": equity / peak - 1.0,
            }
        )
    return out


def worst_month_rows(curve_rows: list[dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    rows = sorted(curve_rows, key=lambda row: safe_float(row.get("net_return"), 0.0))[:n]
    return [
        {
            "rebalance_date": row.get("rebalance_date"),
            "net_return": row.get("net_return"),
            "drawdown": row.get("drawdown"),
            "regime_state": row.get("regime_state"),
        }
        for row in rows
    ]
