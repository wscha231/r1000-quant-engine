"""r1000_opus_data_prep - Prepare rich data samples for Opus rule discovery.

For Phase 3 (Opus-based rule discovery), we sample strategically from the
84-month production data:

  Bucket A: BIG WINNERS  (forward 12m return > +50%)
  Bucket B: BIG LOSERS   (forward 12m return < -30%)
  Bucket C: AVERAGE      (forward 12m return between -10% and +20%)

For each bucket, sample 50 stock-month observations across 4 regimes:
  - 2019 (pre-COVID stable bull)
  - 2020 (COVID crash + V-shape)
  - 2022 (rate hike bear)
  - 2024 (AI bull market)

Output: rich markdown reports per bucket × regime that Opus can analyze
to find patterns differentiating winners from losers.

The reports include:
  - Top features (sage scores, RS, momentum, theme phase)
  - Fundamentals snapshot (PE, growth, ROE)
  - Sector + theme context
  - Insider/analyst data
  - Macro at the time

Usage:
  py -3 r1000_opus_data_prep.py
  -> outputs/opus_analysis/winners_2019.md, losers_2019.md, ...
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))


REGIMES = {
    "2019_pre_covid": ("2019-03-31", "2019-12-31"),
    "2020_covid": ("2020-02-28", "2020-12-31"),
    "2022_bear": ("2022-01-31", "2022-12-31"),
    "2024_ai_bull": ("2024-01-31", "2024-12-31"),
}

# Features to surface to Opus (curated subset of the 429 columns)
KEY_FEATURES = [
    "ticker", "Name", "sector", "industry", "rebalance_date",
    # Price action
    "current_price_live", "mktcap", "px",
    "mom_1m", "mom_3m", "mom_6m", "mom_12m", "mom_18m",
    "rs_benchmark_3m", "rs_benchmark_6m", "rs_benchmark_12m",
    "rs_industry_3m", "rs_industry_6m", "rs_industry_12m",
    "dist_ma200", "rsi14", "vol_252d", "dd_1y",
    "near_52w_high_pct",
    # Fundamentals
    "ep_ttm", "sp_ttm", "fcfy_ttm", "op_margin_ttm",
    "return_on_equity_effective",
    "sales_growth_yoy", "net_income_growth_yoy",
    "forward_pe_final", "peg_final",
    # Sage scores
    "sage_composite_score", "sage_g_score", "sage_v_score",
    "sage_q_score", "sage_c_score",
    # Quality + technical scores
    "score", "score_model_core", "score_quality_core",
    "quality_trend_score", "moat_proxy_score",
    "minervini_trend_template_score", "uptrend_continuation_score",
    "volatility_contraction_score",
    # Theme + leader
    "dynamic_leader_score", "industry_rotation_signal",
    "industry_within_leader_rank",
    "anticipatory_growth_score",
    # Insider / analyst (if available)
    "insider_buy_ratio", "insider_net_shares_ratio",
    "fh_rec_bull_ratio", "fh_rec_buy_delta_mom",
    # Macro
    "spy_above_ma200", "vix_z_63d", "m2_yoy_lag1m",
    "core_cpi_yoy", "macro_regime_score",
    # Forward returns (TARGETS — for Opus to see outcome)
    "r_3m", "r_6m", "r_12m",
]


def load_panel(parquet_path: Path) -> pd.DataFrame:
    """Load scored_oos with rebalance_date typed."""
    df = pd.read_parquet(parquet_path)
    df["rebalance_date"] = pd.to_datetime(df["rebalance_date"])
    return df


def categorize(df: pd.DataFrame) -> pd.DataFrame:
    """Add 'outcome_bucket' column based on r_12m forward return."""
    r12 = pd.to_numeric(df["r_12m"], errors="coerce")
    df = df.copy()
    df["outcome_bucket"] = pd.NA
    df.loc[r12 > 0.50, "outcome_bucket"] = "WINNER"
    df.loc[r12 < -0.30, "outcome_bucket"] = "LOSER"
    df.loc[(r12 >= -0.10) & (r12 <= 0.20), "outcome_bucket"] = "AVERAGE"
    return df


def sample_regime(
    df: pd.DataFrame, start: str, end: str, bucket: str, n: int, seed: int = 42,
) -> pd.DataFrame:
    """Sample n observations from a regime+bucket."""
    mask = (
        (df["rebalance_date"] >= start)
        & (df["rebalance_date"] <= end)
        & (df["outcome_bucket"] == bucket)
    )
    sub = df.loc[mask].copy()
    if len(sub) == 0:
        return pd.DataFrame()
    if len(sub) <= n:
        return sub
    return sub.sample(n=n, random_state=seed)


def write_markdown(df: pd.DataFrame, out_path: Path, title: str) -> None:
    """Write a markdown report with rich feature snapshots."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", "", f"_n={len(df)} stock-month observations_", ""]

    if df.empty:
        lines.append("**No samples in this bucket+regime.**")
        out_path.write_text("\n".join(lines), encoding="utf-8")
        return

    # Aggregate stats first (to give Opus a high-level view)
    lines.append("## Bucket aggregate stats")
    lines.append("")
    lines.append("| Metric | Median | Mean | P25 | P75 |")
    lines.append("|---|---|---|---|---|")
    summary_cols = [
        "r_12m", "score", "sage_composite_score",
        "rs_benchmark_12m", "mom_12m", "dist_ma200",
        "ep_ttm", "sp_ttm", "fcfy_ttm",
        "op_margin_ttm", "sales_growth_yoy",
        "forward_pe_final", "peg_final",
        "rsi14", "vol_252d",
        "minervini_trend_template_score",
    ]
    for c in summary_cols:
        if c not in df.columns:
            continue
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if len(s) == 0:
            continue
        lines.append(
            f"| {c} | {s.median():.4f} | {s.mean():.4f} | "
            f"{s.quantile(0.25):.4f} | {s.quantile(0.75):.4f} |"
        )
    lines.append("")

    # Top 20 sample observations (rich detail)
    lines.append("## Top 20 sample observations (sorted by forward return)")
    lines.append("")
    sorted_df = df.sort_values("r_12m", ascending=False).head(20)
    for _, row in sorted_df.iterrows():
        ticker = row.get("ticker", "?")
        name = row.get("Name", "")
        date = row.get("rebalance_date")
        sector = row.get("sector", "")
        r12 = row.get("r_12m")

        lines.append(f"### {ticker} ({name}) - {date.date() if pd.notna(date) else '?'}")
        lines.append(f"  Sector: {sector}  |  r_12m forward: **{r12*100:+.1f}%**")
        lines.append("")
        lines.append("  | Feature | Value |")
        lines.append("  |---|---|")
        for c in KEY_FEATURES:
            if c in ("ticker", "Name", "sector", "rebalance_date", "industry", "r_12m"):
                continue
            if c not in row.index:
                continue
            v = row[c]
            if pd.isna(v):
                continue
            if isinstance(v, (float, np.floating)):
                lines.append(f"  | {c} | {v:.4f} |")
            else:
                lines.append(f"  | {c} | {v} |")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--scored-oos",
        default=r"G:/내 드라이브/r1000_top30_institutional/feature_store/scored_oos_latest.parquet",
    )
    p.add_argument("--output-dir", default="outputs/opus_analysis")
    p.add_argument("--n-per-cell", type=int, default=50)
    args = p.parse_args()

    print("=" * 70)
    print("Opus Data Prep - sampling 4 regimes x 3 buckets x 50 obs")
    print("=" * 70)

    df = load_panel(Path(args.scored_oos))
    print(f"[load] scored_oos: {len(df)} rows")
    df = categorize(df)
    print(f"[bucket] WINNER (r12>+50%):  {(df['outcome_bucket']=='WINNER').sum()}")
    print(f"[bucket] LOSER  (r12<-30%):  {(df['outcome_bucket']=='LOSER').sum()}")
    print(f"[bucket] AVERAGE             {(df['outcome_bucket']=='AVERAGE').sum()}")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate markdown reports
    for regime_name, (start, end) in REGIMES.items():
        for bucket in ("WINNER", "LOSER", "AVERAGE"):
            sample = sample_regime(df, start, end, bucket, args.n_per_cell)
            fname = out_dir / f"{regime_name}_{bucket.lower()}.md"
            title = f"{regime_name} - {bucket} (forward 12m sorted)"
            write_markdown(sample, fname, title)
            print(f"  {regime_name:<22} {bucket:<8} n={len(sample):>3} -> {fname.name}")

    # Also write a master summary
    summary_path = out_dir / "00_OVERVIEW.md"
    summary_lines = [
        "# Opus Rule Discovery - Data Sample Overview",
        "",
        f"_Generated: {pd.Timestamp.now()}_",
        "",
        "## Source",
        f"- scored_oos_latest.parquet: {len(df)} rows, "
        f"{df['rebalance_date'].min().date()} ~ {df['rebalance_date'].max().date()}",
        "",
        "## Bucket definitions",
        "- **WINNER**: r_12m forward > +50%",
        "- **LOSER**:  r_12m forward < -30%",
        "- **AVERAGE**: r_12m forward in [-10%, +20%]",
        "",
        "## Regime windows",
    ]
    for r, (s, e) in REGIMES.items():
        summary_lines.append(f"- **{r}**: {s} ~ {e}")
    summary_lines.extend([
        "",
        "## Files",
        "- `<regime>_winner.md` - top winners + their features at signal time",
        "- `<regime>_loser.md`  - big losers + their features",
        "- `<regime>_average.md` - control group",
        "",
        "## How to analyze",
        "Read winner.md and loser.md for the SAME regime side-by-side.",
        "Look for features where WINNERS systematically differ from LOSERS.",
        "Validate any hypothesis via r1000_opus_hypothesis_tester.py.",
    ])
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"\n[save] {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
