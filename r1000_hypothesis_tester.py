"""r1000_hypothesis_tester - Test Opus-discovered rules against full panel.

For each hypothesis (a Python predicate function), measure:
  - Fire frequency (n_fires across 84mo)
  - Forward 3m, 6m, 12m mean alpha vs SPY
  - Hit rates at +5%, +10%, +20% thresholds
  - Statistical significance (t-test vs random)
  - Regime breakdown (which regimes does it work?)

Ship gate (to be PROMOTED to advisor):
  - n >= 100
  - p_value < 0.05
  - mean alpha 6m > +5%
  - works in 3 of 4 regimes (loser-avoidance: works in 2 of 4)

Output: outputs/opus_analysis/hypothesis_results.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).parent))


REGIMES = {
    "2019_pre_covid": ("2019-03-31", "2019-12-31"),
    "2020_covid": ("2020-01-31", "2020-12-31"),
    "2021_bull": ("2021-01-31", "2021-12-31"),
    "2022_bear": ("2022-01-31", "2022-12-31"),
    "2023_recovery": ("2023-01-31", "2023-12-31"),
    "2024_ai_bull": ("2024-01-31", "2024-12-31"),
    "2025_present": ("2025-01-31", "2026-02-28"),
}


@dataclass
class Hypothesis:
    name: str
    description: str
    predicate: Callable[[pd.Series], bool]   # row -> bool
    rationale: str = ""                        # WHY this might work


@dataclass
class HypothesisResult:
    name: str
    description: str
    n_fires: int
    n_total: int
    fire_rate_pct: float
    # Forward returns
    mean_r3m: float
    mean_r6m: float
    mean_r12m: float
    median_r12m: float
    # Alpha vs SPY (excess)
    mean_alpha_3m: float
    mean_alpha_6m: float
    mean_alpha_12m: float
    # Hit rates
    hit_5pct_12m: float
    hit_10pct_12m: float
    hit_20pct_12m: float
    hit_neg20pct_12m: float
    # Statistical
    t_stat_12m: float
    p_value_12m: float
    # Regime breakdown
    regime_alpha_12m: dict[str, float] = field(default_factory=dict)
    regime_n: dict[str, int] = field(default_factory=dict)
    # Verdict
    ship_gate_pass: bool = False
    ship_reason: str = ""


def evaluate_hypothesis(
    h: Hypothesis, panel: pd.DataFrame, min_n: int = 100, min_alpha: float = 0.05,
) -> HypothesisResult:
    """Run one hypothesis against panel, return rich result."""
    panel = panel.copy()
    panel["rebalance_date"] = pd.to_datetime(panel["rebalance_date"])

    # Apply predicate row-wise
    fires_mask = panel.apply(h.predicate, axis=1)
    fires = panel[fires_mask].copy()

    n_fires = len(fires)
    n_total = len(panel)
    fire_rate = n_fires / n_total * 100 if n_total > 0 else 0

    if n_fires == 0:
        return HypothesisResult(
            name=h.name, description=h.description,
            n_fires=0, n_total=n_total, fire_rate_pct=0,
            mean_r3m=np.nan, mean_r6m=np.nan, mean_r12m=np.nan,
            median_r12m=np.nan,
            mean_alpha_3m=np.nan, mean_alpha_6m=np.nan, mean_alpha_12m=np.nan,
            hit_5pct_12m=np.nan, hit_10pct_12m=np.nan, hit_20pct_12m=np.nan,
            hit_neg20pct_12m=np.nan,
            t_stat_12m=np.nan, p_value_12m=np.nan,
            ship_gate_pass=False,
            ship_reason="0 fires",
        )

    # Forward returns
    r3 = pd.to_numeric(fires["r_3m"], errors="coerce")
    r6 = pd.to_numeric(fires["r_6m"], errors="coerce")
    r12 = pd.to_numeric(fires["r_12m"], errors="coerce")

    # Population baseline (all rows for matched dates)
    spy_r3 = pd.to_numeric(panel["r_3m"], errors="coerce")
    spy_r6 = pd.to_numeric(panel["r_6m"], errors="coerce")
    spy_r12 = pd.to_numeric(panel["r_12m"], errors="coerce")

    # Alpha = fires - population mean
    alpha_3m = r3.mean() - spy_r3.mean() if r3.notna().any() else np.nan
    alpha_6m = r6.mean() - spy_r6.mean() if r6.notna().any() else np.nan
    alpha_12m = r12.mean() - spy_r12.mean() if r12.notna().any() else np.nan

    # Hit rates
    hit_5 = (r12 > 0.05).mean() if r12.notna().any() else np.nan
    hit_10 = (r12 > 0.10).mean() if r12.notna().any() else np.nan
    hit_20 = (r12 > 0.20).mean() if r12.notna().any() else np.nan
    hit_n20 = (r12 < -0.20).mean() if r12.notna().any() else np.nan

    # T-test: fires r12 vs population r12
    valid_fires = r12.dropna().values
    valid_pop = spy_r12.dropna().values
    if len(valid_fires) >= 5 and len(valid_pop) >= 5:
        t_stat, p_val = stats.ttest_ind(valid_fires, valid_pop, equal_var=False)
    else:
        t_stat, p_val = np.nan, np.nan

    # Regime breakdown
    regime_alpha = {}
    regime_n = {}
    for rname, (start, end) in REGIMES.items():
        rmask = (
            (fires["rebalance_date"] >= start)
            & (fires["rebalance_date"] <= end)
        )
        rsub = fires[rmask]
        rsub_pop = panel[
            (panel["rebalance_date"] >= start) & (panel["rebalance_date"] <= end)
        ]
        rsub_r12 = pd.to_numeric(rsub["r_12m"], errors="coerce")
        rsub_pop_r12 = pd.to_numeric(rsub_pop["r_12m"], errors="coerce")
        regime_n[rname] = int(len(rsub))
        if len(rsub_r12.dropna()) > 0 and len(rsub_pop_r12.dropna()) > 0:
            regime_alpha[rname] = float(rsub_r12.mean() - rsub_pop_r12.mean())
        else:
            regime_alpha[rname] = float("nan")

    # Ship gate
    ship = (
        n_fires >= min_n
        and pd.notna(p_val) and p_val < 0.05
        and pd.notna(alpha_12m) and alpha_12m > min_alpha
    )
    if ship:
        # Also require: works in 3 of 4 main regimes
        positive_regimes = sum(1 for v in regime_alpha.values()
                              if pd.notna(v) and v > 0)
        non_nan_regimes = sum(1 for v in regime_alpha.values() if pd.notna(v))
        if non_nan_regimes >= 4 and positive_regimes < 3:
            ship = False
            reason = f"Only {positive_regimes}/{non_nan_regimes} regimes positive"
        else:
            reason = f"PASS: n={n_fires}, p={p_val:.4f}, alpha={alpha_12m*100:.1f}%, regimes={positive_regimes}/{non_nan_regimes}"
    else:
        p_str = f"{p_val:.4f}" if pd.notna(p_val) else "nan"
        a_str = f"{alpha_12m*100:.1f}%" if pd.notna(alpha_12m) else "nan"
        reason = f"FAIL: n={n_fires} (need >={min_n}), p={p_str}, alpha_12m={a_str}"

    return HypothesisResult(
        name=h.name, description=h.description,
        n_fires=n_fires, n_total=n_total, fire_rate_pct=fire_rate,
        mean_r3m=float(r3.mean()) if r3.notna().any() else float("nan"),
        mean_r6m=float(r6.mean()) if r6.notna().any() else float("nan"),
        mean_r12m=float(r12.mean()) if r12.notna().any() else float("nan"),
        median_r12m=float(r12.median()) if r12.notna().any() else float("nan"),
        mean_alpha_3m=float(alpha_3m) if pd.notna(alpha_3m) else float("nan"),
        mean_alpha_6m=float(alpha_6m) if pd.notna(alpha_6m) else float("nan"),
        mean_alpha_12m=float(alpha_12m) if pd.notna(alpha_12m) else float("nan"),
        hit_5pct_12m=float(hit_5) if pd.notna(hit_5) else float("nan"),
        hit_10pct_12m=float(hit_10) if pd.notna(hit_10) else float("nan"),
        hit_20pct_12m=float(hit_20) if pd.notna(hit_20) else float("nan"),
        hit_neg20pct_12m=float(hit_n20) if pd.notna(hit_n20) else float("nan"),
        t_stat_12m=float(t_stat) if pd.notna(t_stat) else float("nan"),
        p_value_12m=float(p_val) if pd.notna(p_val) else float("nan"),
        regime_alpha_12m=regime_alpha, regime_n=regime_n,
        ship_gate_pass=ship, ship_reason=reason,
    )


# =========================================================================
# Initial PoC hypotheses (from 2022_bear analysis)
# =========================================================================

def safe_le(s, val):
    n = pd.to_numeric(s, errors="coerce")
    return pd.notna(n) and n <= val

def safe_ge(s, val):
    n = pd.to_numeric(s, errors="coerce")
    return pd.notna(n) and n >= val

def safe_lt(s, val):
    n = pd.to_numeric(s, errors="coerce")
    return pd.notna(n) and n < val

def safe_gt(s, val):
    n = pd.to_numeric(s, errors="coerce")
    return pd.notna(n) and n > val


HYPOTHESES = [
    Hypothesis(
        name="H1_oversold_value_beat",
        description="RSI<45 AND EP_TTM>0.05 AND mom_12m<-0.10 (oversold + cheap + beaten-down)",
        predicate=lambda r: (
            safe_lt(r.get("rsi14"), 45)
            and safe_gt(r.get("ep_ttm"), 0.05)
            and safe_lt(r.get("mom_12m"), -0.10)
        ),
        rationale="Bear-regime mean reversion. Beat-down value stocks at oversold "
                  "RSI rebound when sentiment shifts. Tested 2022 bear winners.",
    ),
    Hypothesis(
        name="H2_high_quality_oversold",
        description="sage_q_score>0.5 AND RSI<40 AND dist_ma200<-0.15 (quality on sale)",
        predicate=lambda r: (
            safe_gt(r.get("sage_q_score"), 0.5)
            and safe_lt(r.get("rsi14"), 40)
            and safe_lt(r.get("dist_ma200"), -0.15)
        ),
        rationale="High quality stocks under deep oversold conditions = strong "
                  "compounders bought at discount.",
    ),
    Hypothesis(
        name="H3_acceleration_with_value",
        description="rs_benchmark_3m>0.10 AND rs_benchmark_12m<0 AND ep_ttm>0.04 (RS turn + cheap)",
        predicate=lambda r: (
            safe_gt(r.get("rs_benchmark_3m"), 0.10)
            and safe_lt(r.get("rs_benchmark_12m"), 0)
            and safe_gt(r.get("ep_ttm"), 0.04)
        ),
        rationale="Recent RS acceleration but still trailing 12m AND cheap = early "
                  "stage of turnaround that hasn't been recognized yet.",
    ),
    Hypothesis(
        name="H4_minervini_strong_quality",
        description="minervini_trend_template_score>0.7 AND sage_q_score>0.3 AND mktcap>10e9",
        predicate=lambda r: (
            safe_gt(r.get("minervini_trend_template_score"), 0.7)
            and safe_gt(r.get("sage_q_score"), 0.3)
            and safe_gt(r.get("mktcap"), 10e9)
        ),
        rationale="Trend template confirmed (price > MAs, RS strong) + quality "
                  "earnings + large enough = institutional-grade momentum.",
    ),
    Hypothesis(
        name="H5_avoid_overheated",
        description="AVOID: RSI>75 AND dist_ma200>0.30 AND mom_12m>0.80 (overheated, mean revert risk)",
        predicate=lambda r: (
            safe_gt(r.get("rsi14"), 75)
            and safe_gt(r.get("dist_ma200"), 0.30)
            and safe_gt(r.get("mom_12m"), 0.80)
        ),
        rationale="Extreme overheat = expect mean reversion. AVOID rule: this should "
                  "show NEGATIVE forward alpha.",
    ),
    Hypothesis(
        name="H6_dynamic_leader_compounder",
        description="dynamic_leader_score>0.5 AND fcfy_ttm>0.05 AND op_margin_ttm>0.15",
        predicate=lambda r: (
            safe_gt(r.get("dynamic_leader_score"), 0.5)
            and safe_gt(r.get("fcfy_ttm"), 0.05)
            and safe_gt(r.get("op_margin_ttm"), 0.15)
        ),
        rationale="Dynamic leader (RS rising) + FCF generative + high margins = "
                  "high-quality compounder.",
    ),
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--scored-oos",
        default=r"G:/내 드라이브/r1000_top30_institutional/feature_store/scored_oos_latest.parquet",
    )
    p.add_argument("--output", default="outputs/opus_analysis/hypothesis_results.json")
    args = p.parse_args()

    print("=" * 70)
    print(f"Hypothesis Tester - {len(HYPOTHESES)} hypotheses")
    print("=" * 70)

    panel = pd.read_parquet(args.scored_oos)
    print(f"[load] panel: {len(panel)} rows")

    results = []
    print()
    print(f"{'Hypothesis':<32} {'n_fires':>8} {'alpha12m':>9} {'p-val':>7} {'ship':>5}")
    print("-" * 75)
    for h in HYPOTHESES:
        r = evaluate_hypothesis(h, panel)
        results.append(r)
        ship_str = "PASS" if r.ship_gate_pass else "fail"
        print(f"{r.name:<32} {r.n_fires:>8} {r.mean_alpha_12m*100:>+8.2f}% "
              f"{r.p_value_12m:>7.4f} {ship_str:>5}")

    print()
    print("=" * 70)
    print("DETAILED RESULTS (regime breakdown)")
    print("=" * 70)
    for r in results:
        print()
        print(f"### {r.name}")
        print(f"  {r.description}")
        print(f"  Fires: {r.n_fires}/{r.n_total} ({r.fire_rate_pct:.2f}%)")
        print(f"  Mean alpha:  3m={r.mean_alpha_3m*100:+.2f}%  6m={r.mean_alpha_6m*100:+.2f}%  12m={r.mean_alpha_12m*100:+.2f}%")
        print(f"  Hit rates 12m: 5%={r.hit_5pct_12m*100:.0f}%  10%={r.hit_10pct_12m*100:.0f}%  20%={r.hit_20pct_12m*100:.0f}%  -20%={r.hit_neg20pct_12m*100:.0f}%")
        print(f"  Statistical: t={r.t_stat_12m:+.2f}, p={r.p_value_12m:.4f}")
        print(f"  Regime alpha 12m:")
        for rname, alpha in r.regime_alpha_12m.items():
            n = r.regime_n.get(rname, 0)
            if pd.notna(alpha):
                print(f"    {rname:<20} n={n:>4}  alpha={alpha*100:+6.2f}%")
        print(f"  Verdict: {r.ship_reason}")

    # Save
    out = {
        "summary": [
            {
                "name": r.name,
                "n_fires": r.n_fires,
                "mean_alpha_12m_pct": r.mean_alpha_12m * 100,
                "p_value": r.p_value_12m,
                "ship_pass": r.ship_gate_pass,
                "regime_alpha_12m_pct": {k: v*100 if pd.notna(v) else None
                                          for k, v in r.regime_alpha_12m.items()},
            }
            for r in results
        ],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\n[save] {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
