#!/usr/bin/env python3
"""feature_gate_proposal - Phase 18c auto feature-gate drafter.

Reads trade-journal insights and drafts proposed signal gates in
research/auto_feature_gates.yaml. The intended flow is human-in-the-loop: open
the YAML as a PR, review it, then merge only approved gates.

Gate categories
---------------
1. signal_regime_disable - weak signal x regime IC.
2. signal_regime_amplify - strong signal x regime IC.
3. pattern_block - weak trade cluster win rate.

Usage
-----
    python tools/feature_gate_proposal.py
    python tools/feature_gate_proposal.py --ic-disable -0.05 --ic-amplify 0.10
    python tools/feature_gate_proposal.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
INSIGHTS_DIR_DEFAULT = REPO_ROOT / "outputs" / "trade_journal" / "insights"
GATES_PATH_DEFAULT = REPO_ROOT / "research" / "auto_feature_gates.yaml"

# Conservative thresholds (only the strongest findings auto-propose).
# Tuned for n=1,680 trade journal (84mo x ~20 names).
DEFAULT_IC_DISABLE = -0.05      # IC <= -0.05 in regime -> disable
DEFAULT_IC_AMPLIFY = 0.10       # IC >= +0.10 in regime -> amplify
DEFAULT_IC_MIN_N = 25           # require n>=25 trades in (signal x regime) cell
DEFAULT_CLUSTER_WINRATE = 0.30  # cluster win_rate <= 0.30 -> block
DEFAULT_CLUSTER_MIN_N = 20      # require n>=20 trades in cluster
DEFAULT_DISABLE_FACTOR = 0.0    # full disable
DEFAULT_AMPLIFY_FACTOR = 1.30   # +30% boost
DEFAULT_GATE_LIFETIME_DAYS = 90 # auto-expire after 1 quarter


def load_csv(path: Path):
    if not path.exists():
        return None
    try:
        import pandas as pd
        return pd.read_csv(path)
    except Exception:
        return None


def propose_signal_regime_gates(
    ic_df,
    ic_disable: float,
    ic_amplify: float,
    min_n: int,
) -> list[dict]:
    """Walk the IC matrix and emit disable/amplify proposals."""
    if ic_df is None or ic_df.empty:
        return []
    proposals: list[dict] = []
    regime_cols = [c for c in ic_df.columns if c.startswith("ic_") and c != "ic_all"]
    n_cols = [c for c in ic_df.columns if c.startswith("n_") and c != "n_all"]
    for _, row in ic_df.iterrows():
        signal = str(row["signal"])
        for ic_col in regime_cols:
            regime = ic_col.replace("ic_", "")
            n_col = f"n_{regime}"
            if n_col not in n_cols:
                continue
            ic = row.get(ic_col)
            n = int(row.get(n_col, 0)) if row.get(n_col) is not None else 0
            try:
                ic = float(ic) if ic is not None else None
            except (TypeError, ValueError):
                continue
            if ic is None or n < min_n:
                continue
            if ic <= ic_disable:
                proposals.append({
                    "kind": "signal_regime_disable",
                    "signal": signal,
                    "regime": regime,
                    "factor": DEFAULT_DISABLE_FACTOR,
                    "ic": round(ic, 4),
                    "n": n,
                    "rationale": f"IC {ic:+.3f} in {regime} (n={n}) <= disable threshold {ic_disable}",
                })
            elif ic >= ic_amplify:
                proposals.append({
                    "kind": "signal_regime_amplify",
                    "signal": signal,
                    "regime": regime,
                    "factor": DEFAULT_AMPLIFY_FACTOR,
                    "ic": round(ic, 4),
                    "n": n,
                    "rationale": f"IC {ic:+.3f} in {regime} (n={n}) >= amplify threshold +{ic_amplify}",
                })
    return proposals


def propose_pattern_blocks(
    cluster_df,
    winrate_max: float,
    min_n: int,
) -> list[dict]:
    """Emit pattern_block proposals from k-means cluster results."""
    if cluster_df is None or cluster_df.empty:
        return []
    if "error" in cluster_df.columns:
        return []
    proposals: list[dict] = []
    for _, row in cluster_df.iterrows():
        try:
            wr = float(row.get("win_rate"))
            n = int(row.get("n", 0))
        except (TypeError, ValueError):
            continue
        if n < min_n or wr > winrate_max:
            continue
        # Build feature_signature from top-3 centroid
        sig = {}
        for i in range(1, 4):
            name = row.get(f"top{i}_signal")
            cz = row.get(f"top{i}_centroid_z")
            if name and cz is not None:
                sig[str(name)] = round(float(cz), 3)
        if not sig:
            continue
        proposals.append({
            "kind": "pattern_block",
            "cluster_id": int(row.get("cluster_id", -1)),
            "win_rate": round(wr, 4),
            "n": n,
            "feature_signature_z": sig,
            "rationale": f"cluster win_rate {wr:.3f} (n={n}) <= block threshold {winrate_max}",
        })
    return proposals


def render_yaml(proposals: list[dict], generated_at: str, lifetime_days: int) -> str:
    """Hand-render YAML to keep diffs minimal and human-readable.
    Avoids dependency on pyyaml's quote/style fluctuations.
    """
    expires_at = (datetime.fromisoformat(generated_at.replace("Z", "")) + timedelta(days=lifetime_days)).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append("# AUTO-GENERATED by tools/feature_gate_proposal.py (Phase 18c).")
    lines.append("# Human reviews via PR before merge. Do NOT hand-edit gates --")
    lines.append("# instead edit the proposal tool's thresholds and re-run.")
    lines.append("# Empty `gates: []` is the safe default (no behavior change).")
    lines.append("")
    lines.append(f"generated_at: '{generated_at}'")
    lines.append(f"expires_at: '{expires_at}'")
    lines.append(f"n_proposals: {len(proposals)}")
    lines.append("")
    lines.append("gates:")
    if not proposals:
        lines.append("  []")
        lines.append("")
        return "\n".join(lines)
    for p in proposals:
        lines.append(f"  - kind: {p['kind']}")
        if p["kind"] in ("signal_regime_disable", "signal_regime_amplify"):
            lines.append(f"    signal: {p['signal']}")
            lines.append(f"    regime: {p['regime']}")
            lines.append(f"    factor: {p['factor']}")
            lines.append(f"    ic: {p['ic']}")
        elif p["kind"] == "pattern_block":
            lines.append(f"    cluster_id: {p['cluster_id']}")
            lines.append(f"    win_rate: {p['win_rate']}")
            lines.append(f"    feature_signature_z:")
            for k, v in p["feature_signature_z"].items():
                lines.append(f"      {k}: {v}")
        lines.append(f"    n: {p['n']}")
        lines.append(f"    rationale: \"{p['rationale']}\"")
        lines.append("")
    return "\n".join(lines)


def diff_yaml(old_text: str, new_text: str) -> str:
    """Lightweight unified-style diff for the proposal_diff.md."""
    import difflib
    diff = difflib.unified_diff(
        (old_text or "").splitlines(),
        (new_text or "").splitlines(),
        fromfile="auto_feature_gates.yaml (current)",
        tofile="auto_feature_gates.yaml (proposed)",
        lineterm="",
        n=3,
    )
    body = "\n".join(diff)
    return body if body else "(no changes)"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--insights", default=str(INSIGHTS_DIR_DEFAULT))
    p.add_argument("--gates-out", default=str(GATES_PATH_DEFAULT))
    p.add_argument("--ic-disable", type=float, default=DEFAULT_IC_DISABLE)
    p.add_argument("--ic-amplify", type=float, default=DEFAULT_IC_AMPLIFY)
    p.add_argument("--ic-min-n", type=int, default=DEFAULT_IC_MIN_N)
    p.add_argument("--cluster-winrate-max", type=float, default=DEFAULT_CLUSTER_WINRATE)
    p.add_argument("--cluster-min-n", type=int, default=DEFAULT_CLUSTER_MIN_N)
    p.add_argument("--lifetime-days", type=int, default=DEFAULT_GATE_LIFETIME_DAYS)
    p.add_argument("--dry-run", action="store_true",
                   help="print proposals + diff but do not write yaml")
    args = p.parse_args()

    insights_dir = Path(args.insights)
    ic_path = insights_dir / "ic_matrix.csv"
    cluster_path = insights_dir / "cluster_winrate.csv"

    ic_df = load_csv(ic_path)
    cluster_df = load_csv(cluster_path)

    if ic_df is None and cluster_df is None:
        print(f"[gate-prop] ERROR: neither {ic_path} nor {cluster_path} found.", file=sys.stderr)
        print(f"[gate-prop] Run tools/trade_insights.py first.", file=sys.stderr)
        return 2

    print(f"[gate-prop] thresholds: ic_disable={args.ic_disable} ic_amplify=+{args.ic_amplify} "
          f"ic_min_n={args.ic_min_n} cluster_winrate_max={args.cluster_winrate_max} "
          f"cluster_min_n={args.cluster_min_n}")

    proposals = []
    if ic_df is not None:
        sig_proposals = propose_signal_regime_gates(ic_df, args.ic_disable, args.ic_amplify, args.ic_min_n)
        proposals.extend(sig_proposals)
        print(f"[gate-prop] signal x regime proposals: {len(sig_proposals)}")
    if cluster_df is not None:
        pat_proposals = propose_pattern_blocks(cluster_df, args.cluster_winrate_max, args.cluster_min_n)
        proposals.extend(pat_proposals)
        print(f"[gate-prop] pattern block proposals:   {len(pat_proposals)}")

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_yaml = render_yaml(proposals, generated_at, args.lifetime_days)

    gates_path = Path(args.gates_out)
    old_yaml = gates_path.read_text() if gates_path.exists() else ""
    diff = diff_yaml(old_yaml, new_yaml)

    print()
    print("[gate-prop] proposed gates (preview):")
    for prop in proposals[:10]:
        if prop["kind"] in ("signal_regime_disable", "signal_regime_amplify"):
            print(f"    {prop['kind']:<24} {prop['signal']:<32} regime={prop['regime']:<12} "
                  f"factor={prop['factor']}  IC={prop['ic']:+.3f}  n={prop['n']}")
        else:
            sig = ", ".join(f"{k}={v:+.2f}" for k, v in list(prop["feature_signature_z"].items())[:3])
            print(f"    pattern_block            cluster={prop['cluster_id']:<3} "
                  f"win_rate={prop['win_rate']:.3f}  n={prop['n']}  sig: {sig}")
    if len(proposals) > 10:
        print(f"    ... {len(proposals) - 10} more")

    diff_path = insights_dir / "proposal_diff.md"
    insights_dir.mkdir(parents=True, exist_ok=True)
    diff_md = (
        f"# Auto Feature Gate Proposal Diff\n\n"
        f"Generated: {generated_at}\n\n"
        f"Total proposals: **{len(proposals)}**\n\n"
        f"```diff\n{diff}\n```\n"
    )
    diff_path.write_text(diff_md)
    print(f"[gate-prop] wrote {diff_path}")

    if args.dry_run:
        print("[gate-prop] --dry-run: no yaml written")
        return 0

    gates_path.parent.mkdir(parents=True, exist_ok=True)
    gates_path.write_text(new_yaml)
    print(f"[gate-prop] wrote {gates_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
