"""Fail-closed legacy score bridge with a separate whole-universe inventory.

A missing model score is not a neutral/low-confidence model score. Supplemental
Finnhub observations are diagnostic only and never impersonate calibrated ML
outputs, verified market capitalization, forward earnings or a trading target.
Existing compatibility output is preserved if requested names remain unscored.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import tempfile

import pandas as pd

DEFAULT_SCORED_CSV = r"G:/내 드라이브/r1000_top30_institutional/outputs/scored_latest.csv"
DEFAULT_OUTPUT_CSV = r"G:/내 드라이브/r1000_top30_institutional/outputs/scored_unified.csv"


class IncompleteUniverseError(ValueError):
    """Coverage diagnostics were written; no new compatible score was published."""


def percentile_rank(series: pd.Series) -> pd.Series:
    """Preserve missing observations; NaN is not the 50th percentile."""
    values = pd.to_numeric(series, errors='coerce').replace([float('inf'), -float('inf')], float('nan'))
    return values.rank(pct=True, method='average')


def _number(value, positive=False):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) and (not positive or result > 0) else None


def _fraction(row, field):
    value = _number(row.get(field))
    return value / 100.0 if value is not None else None


def compute_live_rs(tickers: list[str], verbose: bool = True) -> dict[str, float]:
    """Optional legacy price diagnostic, not validated total-return model input."""
    from aggressive.data_alpaca import fetch_daily_bars, fetch_spy_benchmark
    class RSPrices(dict):
        pass
    result = RSPrices()
    result.prices = {}
    spy = fetch_spy_benchmark(days=400)
    if spy.empty or len(spy) < 253:
        return result
    if not spy.index.is_unique or not spy.index.is_monotonic_increasing:
        raise ValueError('benchmark_session_identity')
    sessions = spy.index[-253:]
    for ticker in tickers:
        frame = fetch_daily_bars(ticker, days=400)
        if frame.empty or not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            continue
        if frame.index[-1] != sessions[-1] or not sessions.isin(frame.index).all():
            continue
        stock = pd.to_numeric(frame.reindex(sessions)['close'], errors='coerce')
        bench = pd.to_numeric(spy.reindex(sessions)['close'], errors='coerce')
        if any(_number(value, positive=True) is None for value in [*stock, *bench]):
            continue
        # 253 observations are required for 252 elapsed sessions.
        result[ticker] = float(stock.iloc[-1] / stock.iloc[0] - bench.iloc[-1] / bench.iloc[0])
        result.prices[ticker] = float(stock.iloc[-1])
    return result


def build_synthetic_row(ticker, finnhub_row, rs_12m_decimal, sector, name,
                        normalized_metrics, live_price=0.0):
    """Compatibility name retained; now emits an explicitly unscored inventory row."""
    return {
        'ticker': ticker, 'Name': name or ticker, 'sector': sector or 'Unknown',
        'score': None, 'score_model_core': None, 'score_total': None,
        'model_score': None, 'portfolio_sleeve_label': None,
        'portfolio_sleeve_confidence': None, 'score_source': 'UNSCORED_INVENTORY',
        'ranking_eligible': False, 'valuation_approved': False,
        'current_price_live': _number(live_price, positive=True),
        'market_cap_live': None, 'market_cap_reason': 'VERIFIED_VALUE_AND_UNIT_REQUIRED',
        'forward_pe_final': None,
        'trailing_pe_ttm': _number(finnhub_row.get('fh_peExclExtra_ttm'), positive=True),
        'peg_final': _number(finnhub_row.get('fh_peg_5y'), positive=True),
        'mom_12m': None, 'rs_benchmark_12m': _number(rs_12m_decimal),
        'rs_basis': 'LEGACY_PRICE_DIFFERENCE_NOT_CERTIFIED_TOTAL_RETURN',
        'earnings_growth_final': _fraction(finnhub_row, 'fh_epsGrowthQuarterlyYoy'),
        'sales_growth_yoy': _fraction(finnhub_row, 'fh_revenueGrowthQuarterlyYoy'),
        'op_margin_ttm': _fraction(finnhub_row, 'fh_operatingMargin_ttm'),
        'financial_snapshot_present': bool(finnhub_row),
        'missing_reason': 'MODEL_SCORE_MISSING' if finnhub_row else 'MODEL_AND_FINANCIALS_MISSING',
    }


def build_sector_lookup():
    from aggressive.universe import fetch_iwb_holdings
    frame = fetch_iwb_holdings()
    return {str(r['ticker']).upper().strip(): {
        'sector': r.get('Sector', 'Unknown'), 'name': r.get('Name', r['ticker'])
    } for _, r in frame.iterrows()} if not frame.empty else {}


def _atomic_text(path: Path, text: str):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink_output')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def reconcile_inventory(scored, universe, features=None, metadata=None, prices=None, rs=None):
    """Pure whole-universe reconciliation; no collection, ranking or trading."""
    features, metadata, prices, rs = features or {}, metadata or {}, prices or {}, rs or {}
    names = [str(t).upper().strip() for t in universe]
    if not names or len(names) != len(set(names)) or any(not t for t in names):
        raise ValueError('universe_identity')
    frame = scored.copy()
    if 'ticker' not in frame or frame['ticker'].isna().any():
        raise ValueError('score_identity')
    frame['ticker'] = frame['ticker'].astype(str).str.upper().str.strip()
    if frame['ticker'].duplicated().any() or frame['ticker'].eq('').any():
        raise ValueError('score_identity')
    if 'score_source' not in frame:
        frame['score_source'] = 'legacy_model_source_unverified'
    forbidden = frame['score_source'].astype(str).isin(['finnhub_synthetic', 'UNSCORED_INVENTORY'])
    score_valid = (pd.to_numeric(frame['score'], errors='coerce').map(lambda v: _number(v) is not None)
                   if 'score' in frame else pd.Series(False, index=frame.index))
    permitted = (frame['ranking_eligible'].map(lambda v: str(v).strip().lower() == 'true')
                 if 'ranking_eligible' in frame else pd.Series(True, index=frame.index))
    usable = frame.loc[~forbidden & score_valid & permitted & frame['ticker'].isin(names)].copy()
    present = set(usable['ticker'])
    missing = sorted(set(names) - present)
    extra = sorted(set(frame['ticker']) - set(names))
    additions = []
    for ticker in missing:
        meta = metadata.get(ticker, {})
        additions.append(build_synthetic_row(ticker, features.get(ticker, {}), rs.get(ticker),
                         meta.get('sector'), meta.get('name'), {}, prices.get(ticker)))
    inventory = pd.concat([usable, pd.DataFrame(additions)], ignore_index=True, sort=False)
    if len(inventory) != len(names) or set(inventory['ticker']) != set(names):
        raise ValueError('inventory_reconciliation')
    summary = {'requested_securities': len(names), 'existing_score_rows': len(usable),
               'unscored_securities': len(missing), 'missing_tickers': missing,
               'outside_requested_universe': extra, 'rejected_synthetic_rows': int(forbidden.sum()),
               'status': 'BLOCKED_MISSING_MODEL_COVERAGE' if missing else 'LEGACY_COMPATIBILITY_ONLY',
               'financial_coverage_certified': False, 'investment_approved': False,
               'portfolio_weights': None}
    return inventory, summary, usable


def build_unified_scored(scored_csv=DEFAULT_SCORED_CSV, output_csv=DEFAULT_OUTPUT_CSV, verbose=True):
    from aggressive.universe import load_universe
    from aggressive.finnhub_cache_loader import load_finnhub_features_dict
    scored = pd.read_csv(scored_csv)
    universe, universe_meta = load_universe('r1000')
    if len(universe) < 1000 or universe_meta.get('source_used') == 'themes_fallback':
        _atomic_text(Path(str(output_csv) + '.coverage.json'), json.dumps({
            'status': 'BLOCKED_UNIVERSE_SOURCE', 'requested_securities': len(universe),
            'source_used': universe_meta.get('source_used'), 'investment_approved': False,
            'portfolio_weights': None}, indent=2, allow_nan=False))
        raise IncompleteUniverseError('universe_coverage_floor_or_theme_fallback')
    features = load_finnhub_features_dict()
    # No expensive partial live-price collection is needed to discover absent model scores.
    inventory, summary, compatible = reconcile_inventory(scored, universe, features)
    path = Path(output_csv)
    _atomic_text(Path(str(path) + '.coverage.csv'), inventory.to_csv(index=False))
    _atomic_text(Path(str(path) + '.coverage.json'), json.dumps(summary, indent=2, allow_nan=False))
    if summary['unscored_securities']:
        raise IncompleteUniverseError('incomplete_model_coverage; compatibility_output_not_replaced')
    _atomic_text(path, compatible.to_csv(index=False))
    if verbose:
        print(json.dumps(summary, indent=2))
    return compatible


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scored-csv', default=DEFAULT_SCORED_CSV)
    parser.add_argument('--output-csv', default=DEFAULT_OUTPUT_CSV)
    args = parser.parse_args()
    build_unified_scored(args.scored_csv, args.output_csv)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
