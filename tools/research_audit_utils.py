#!/usr/bin/env python3
"""Small shared helpers for research-only audit tools."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def first_existing(frame: pd.DataFrame, names: list[str]) -> str:
    return next((name for name in names if name in frame.columns), "")


def normalize_date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.normalize()


def spearman(x: pd.Series, y: pd.Series) -> float | None:
    d = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(d) < 3 or d["x"].nunique() < 2 or d["y"].nunique() < 2:
        return None
    value = d["x"].rank().corr(d["y"].rank())
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def linear_regression(y: pd.Series, x: pd.DataFrame) -> dict[str, Any]:
    d = pd.concat([y.rename("y"), x], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(d) < max(4, x.shape[1] + 2):
        return {"status": "insufficient_sample", "sample_count": int(len(d))}
    yv = d["y"].astype(float).to_numpy()
    xv = d.drop(columns=["y"]).astype(float).to_numpy()
    design = np.column_stack([np.ones(len(xv)), xv])
    beta, *_ = np.linalg.lstsq(design, yv, rcond=None)
    fitted = design @ beta
    resid = yv - fitted
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((yv - yv.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    out = {
        "status": "completed",
        "sample_count": int(len(d)),
        "intercept": float(beta[0]),
        "r_squared": float(r2),
        "residual_alpha_mean": float(resid.mean()),
    }
    for name, coef in zip(d.drop(columns=["y"]).columns, beta[1:]):
        out[f"{name}_beta"] = float(coef)
    return out
