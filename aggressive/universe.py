"""Universe loader for Aggressive engine - NO hardcoded tickers.

Design principle (user request 2026-04-23):
  "AMD/LITE 등을 하드코딩하지 말라. 미래에는 어떤 테마가 뜰지 모른다.
   순수하게 종목을 찾아내는 시스템이 필요하다."

Sources (in priority order):
  1. cached iShares IWB holdings (Russell 1000 ETF - live market)
  2. historical_universe_membership file (if main engine has cached it)
  3. themes.yaml members (fallback only - DEPRECATED as primary source)
  4. explicit user ticker list

No ticker is hardcoded in logic. All universes come from a data source.
Smoke tests use explicit tickers but ONLY for testing, never for production.

Usage:
    from aggressive.universe import load_universe
    tickers = load_universe("r1000")          # ~1000 tickers, live
    tickers = load_universe("r1000", max_age_hours=24)  # use cache if fresh
    tickers = load_universe("r1000+adr")      # R1000 + ADRs from adr_universe.yaml
    tickers = load_universe("global_alpha_universe")  # R1000 + ADR/cycle/strategic hardware overlays
    tickers = load_universe("adr")            # ADRs only (whitelist)
    tickers = load_universe("themes")         # legacy: themes.yaml members only
    tickers = load_universe("custom", tickers=["AAPL", "MSFT"])  # explicit

ADR mode (added 2026-04-25):
  ADRs (ASML, TSM, BABA, etc.) are NOT in iShares IWB (Russell 1000 = US-domestic).
  adr_universe.yaml maintains a curated top-mcap whitelist (>=$8B) of ADR/ADS
  and US-listed foreign ordinary shares that trade on NYSE/NASDAQ and are tradeable
  on Alpaca paper. Source for additions:
  PHASE_18A theme discovery + manual mcap review. SK Hynix Oct 2026 watchlist
  documented in adr_universe.yaml's `adr_watchlist` section.
"""
from __future__ import annotations

import io
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from aggressive.agg_config import load_agg_config


_IWB_URL = "https://www.ishares.com/us/products/239707/ishares-russell-1000-etf"
_IWB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_CACHE_TTL_HOURS = 24                 # IWB membership doesn't change often
_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-/]{0,8}$")


def _normalize_ticker(t: str) -> str:
    """Normalize ticker: upper, strip, replace BRK/B -> BRK.B, etc."""
    if not isinstance(t, str):
        return ""
    s = t.strip().upper().replace(" ", "")
    s = s.replace("/", ".")            # BRK/B -> BRK.B
    return s


def _is_valid_ticker(t: str) -> bool:
    return bool(t) and bool(_TICKER_PATTERN.match(t))


def _cache_path() -> Path:
    cfg = load_agg_config()
    cache_dir = cfg.cache_dir / "universe"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "iwb_holdings.parquet"


def _cache_is_fresh(path: Path, max_age_hours: int = _CACHE_TTL_HOURS) -> bool:
    if not path.exists():
        return False
    age_hours = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
    return age_hours < max_age_hours


# --- iShares IWB scrape (live R1000) ---------------------------------------

def _ishares_read_csv(url: str) -> pd.DataFrame:
    """Parse iShares holdings CSV which has ~9 header lines of metadata."""
    import requests
    resp = requests.get(url, headers=_IWB_HEADERS, timeout=60)
    resp.raise_for_status()
    raw = resp.content.decode("utf-8", errors="replace")
    lines = raw.splitlines()
    header_idx = next((i for i, ln in enumerate(lines) if ln.startswith("Ticker,")), None)
    if header_idx is None:
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
    df.columns = [c.strip() for c in df.columns]
    return df


def fetch_iwb_holdings(force_refresh: bool = False) -> pd.DataFrame:
    """Fetch live R1000 from iShares IWB ETF.

    Returns DataFrame with at minimum columns: ticker, Name, Sector, market_value.
    Cached to aggressive/cache/universe/iwb_holdings.parquet for 24h.
    """
    cache = _cache_path()
    if not force_refresh and _cache_is_fresh(cache):
        try:
            return pd.read_parquet(cache)
        except Exception:
            pass

    import requests
    try:
        resp = requests.get(_IWB_URL, headers=_IWB_HEADERS, timeout=60)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        print(f"FAIL: could not reach iShares: {exc}")
        return pd.DataFrame()

    ajax_ids = list(dict.fromkeys(re.findall(r"(\d{13})\.ajax", html)))
    if not ajax_ids:
        print("FAIL: no .ajax id found in iShares page")
        return pd.DataFrame()

    for aid in ajax_ids:
        url = (f"{_IWB_URL.rstrip('/')}/{aid}.ajax"
               f"?fileType=csv&fileName=IWB_holdings&dataType=fund")
        try:
            df = _ishares_read_csv(url)
        except Exception:
            time.sleep(0.2)
            continue
        if not df.empty and "Ticker" in df.columns:
            df = df.rename(columns={"Ticker": "ticker"})
            df["ticker"] = df["ticker"].map(_normalize_ticker)
            df = df[df["ticker"].map(_is_valid_ticker)]
            # Keep useful columns only
            keep = ["ticker", "Name", "Sector", "Asset Class", "Market Value"]
            keep = [c for c in keep if c in df.columns]
            df = df[keep].drop_duplicates(subset=["ticker"])
            # Cache
            try:
                df.to_parquet(cache)
            except Exception:
                pass
            return df
        time.sleep(0.2)

    print("FAIL: no iShares CSV readable")
    return pd.DataFrame()


# --- Fallback: main engine's cached universe -------------------------------

def fetch_from_main_engine_cache() -> pd.DataFrame:
    """Try reading main engine's historical_universe_membership file."""
    candidates = [
        Path(__file__).parent.parent / "data_raw" / "historical_universe_membership_auto.csv",
        Path(__file__).parent.parent / "data_raw" / "historical_universe_membership.parquet",
        Path(__file__).parent.parent / "data_raw" / "historical_universe_membership.csv",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            if path.suffix == ".parquet":
                df = pd.read_parquet(path)
            else:
                df = pd.read_csv(path)
            if "ticker" in df.columns:
                df["ticker"] = df["ticker"].map(_normalize_ticker)
                df = df[df["ticker"].map(_is_valid_ticker)]
                return df.drop_duplicates(subset=["ticker"])
        except Exception:
            continue
    return pd.DataFrame()


# --- Fallback: themes.yaml members -----------------------------------------

def fetch_from_themes() -> list[str]:
    """Legacy fallback - pulls all tickers from themes.yaml members.
    DEPRECATED: only use when live IWB and main-engine cache both fail.
    """
    from r1000_themes import load_themes, map_tickers_to_themes
    themes = load_themes()
    if not themes:
        return []
    ticker_map = map_tickers_to_themes(themes)
    return sorted(ticker_map.keys())


# --- Main entrypoint -------------------------------------------------------

_ADR_UNIVERSE_PATH = Path(__file__).parent.parent / "adr_universe.yaml"
_CYCLE_PLAY_UNIVERSE_PATH = Path(__file__).parent.parent / "cycle_play_universe.yaml"
_STRATEGIC_GLOBAL_HARDWARE_UNIVERSE_PATH = Path(__file__).parent.parent / "strategic_global_hardware_universe.yaml"


def load_adr_universe(
    min_mcap_usd_b: float = 8.0,
    include_skip: bool = False,
) -> tuple[list[str], list[dict]]:
    """Load curated ADR whitelist from adr_universe.yaml.

    Returns (tickers, metadata_list) where metadata_list contains the full record
    (country, sector, sub_sector, mcap, themes, notes) for each ticker.

    min_mcap_usd_b: filter ADRs by self-reported market cap (default $8B floor).
    include_skip:   if True, also include records with skip:true (e.g. TCEHY OTC).
    """
    if not _ADR_UNIVERSE_PATH.exists():
        return [], []
    try:
        import yaml
    except ImportError:
        return [], []
    try:
        payload = yaml.safe_load(_ADR_UNIVERSE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return [], []

    raw = payload.get("adr_universe", [])
    if not isinstance(raw, list):
        return [], []

    tickers: list[str] = []
    meta_list: list[dict] = []
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        if rec.get("skip") and not include_skip:
            continue
        t = str(rec.get("ticker", "")).upper().strip()
        if not _is_valid_ticker(t):
            continue
        mcap = float(rec.get("mcap_usd_b") or 0.0)
        if mcap < min_mcap_usd_b:
            continue
        tickers.append(t)
        meta_list.append(rec)
    return sorted(set(tickers)), meta_list


def load_cycle_play_universe(
    min_mcap_usd_b: float = 0.3,
    max_mcap_usd_b: float = 30.0,
    include_skip: bool = False,
) -> tuple[list[str], list[dict]]:
    """Load curated cycle-play whitelist from cycle_play_universe.yaml.

    Phase 15-D (2026-04-29): small-mid cap cycle / disruption plays that fall
    below R1000 size threshold but have catalyst potential (BE / PLUG /
    RIVN / ENPH etc.). Filters by mcap range — names that grow into R1000
    (mcap > $30B) are auto-excluded.

    Returns (tickers, metadata_list).
    """
    if not _CYCLE_PLAY_UNIVERSE_PATH.exists():
        return [], []
    try:
        import yaml
    except ImportError:
        return [], []
    try:
        payload = yaml.safe_load(_CYCLE_PLAY_UNIVERSE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return [], []
    raw = payload.get("cycle_play_universe", [])
    if not isinstance(raw, list):
        return [], []
    tickers: list[str] = []
    meta_list: list[dict] = []
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        if rec.get("skip") and not include_skip:
            continue
        t = str(rec.get("ticker", "")).upper().strip()
        if not _is_valid_ticker(t):
            continue
        mcap = float(rec.get("mcap_usd_b") or 0.0)
        if mcap < min_mcap_usd_b or mcap > max_mcap_usd_b:
            continue
        tickers.append(t)
        meta_list.append(rec)
    return sorted(set(tickers)), meta_list


def load_strategic_global_hardware_universe(
    include_skip: bool = False,
) -> tuple[list[str], list[dict]]:
    """Load strategic semiconductor / AI hardware universe from YAML.

    This mirrors the main pipeline overlay and is a candidate universe only,
    not a buy list. It keeps aggressive/tactical research loaders aligned with
    `global_alpha_universe`.
    """
    if not _STRATEGIC_GLOBAL_HARDWARE_UNIVERSE_PATH.exists():
        return [], []
    try:
        import yaml
    except ImportError:
        return [], []
    try:
        payload = yaml.safe_load(_STRATEGIC_GLOBAL_HARDWARE_UNIVERSE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return [], []
    raw = payload.get("strategic_global_hardware_universe", [])
    if not isinstance(raw, list):
        return [], []
    tickers: list[str] = []
    meta_list: list[dict] = []
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        if rec.get("skip") and not include_skip:
            continue
        t = str(rec.get("ticker", "")).upper().strip()
        if not _is_valid_ticker(t):
            continue
        tickers.append(t)
        meta_list.append(rec)
    return sorted(set(tickers)), meta_list


def load_universe(
    source: str = "r1000",
    tickers: Optional[list[str]] = None,
    max_age_hours: int = 24,
    min_market_value_musd: float = 0.0,
    adr_min_mcap_usd_b: float = 8.0,
    cycle_play_min_mcap_usd_b: float = 0.3,
    cycle_play_max_mcap_usd_b: float = 30.0,
) -> tuple[list[str], dict]:
    """Load tradeable universe. Returns (tickers, metadata).

    source:
      'r1000'      - live iShares IWB (fallback: main-engine cache, then themes)
      'r1000+adr'  - R1000 union curated ADR whitelist (adr_universe.yaml)
      'global_alpha_universe' - alias for the shared R1000 + ADR/global-alpha universe
      'adr'        - ADR whitelist only
      'themes'     - themes.yaml members only (legacy)
      'custom'     - explicit ticker list in `tickers` arg
      'auto'       - r1000 with fallbacks

    Returns:
      tickers: sorted list of unique tickers
      metadata: {source_used, count, fetched_at, adr_count?, ...}
    """
    source = {
        "global-alpha": "global_alpha_universe",
        "global_alpha": "global_alpha_universe",
        "global+adr": "global_alpha_universe",
        "global+hardware": "global_alpha_universe",
        "global_hardware": "global_alpha_universe",
        "r1000+adr+cycle": "global_alpha_universe",   # Phase 15-D alias
        "r1000+cycle": "r1000+cycle",
    }.get(str(source), str(source))
    meta = {"source_requested": source, "fetched_at": datetime.now().isoformat()}

    if source == "custom":
        raw = tickers or []
        clean = sorted({_normalize_ticker(t) for t in raw if _is_valid_ticker(_normalize_ticker(t))})
        meta["source_used"] = "custom"
        meta["count"] = len(clean)
        return clean, meta

    if source == "adr":
        adr_tickers, _ = load_adr_universe(min_mcap_usd_b=adr_min_mcap_usd_b)
        meta["source_used"] = "adr_whitelist"
        meta["count"] = len(adr_tickers)
        meta["adr_min_mcap_usd_b"] = adr_min_mcap_usd_b
        return adr_tickers, meta

    if source in ("r1000+adr", "global_alpha_universe"):
        # 1. Pull R1000 the normal way
        r1000_tickers, r1000_meta = load_universe(
            "r1000", max_age_hours=max_age_hours,
            min_market_value_musd=min_market_value_musd,
        )
        # 2. Pull ADR whitelist
        adr_tickers, _ = load_adr_universe(min_mcap_usd_b=adr_min_mcap_usd_b)
        # 3. Phase 15-D: also include cycle play whitelist for global_alpha
        # (R1000 + ADR + cycle plays). r1000+adr legacy mode keeps cycle off.
        cycle_tickers: list[str] = []
        hardware_tickers: list[str] = []
        if source == "global_alpha_universe":
            cycle_tickers, _ = load_cycle_play_universe(
                min_mcap_usd_b=cycle_play_min_mcap_usd_b,
                max_mcap_usd_b=cycle_play_max_mcap_usd_b,
            )
            hardware_tickers, _ = load_strategic_global_hardware_universe()
        # 4. Union, dedup, sort
        combined = sorted(set(r1000_tickers) | set(adr_tickers) | set(cycle_tickers) | set(hardware_tickers))
        meta["source_used"] = f"{r1000_meta.get('source_used', 'r1000')}+global_alpha"
        meta["count"] = len(combined)
        meta["r1000_count"] = len(r1000_tickers)
        meta["adr_count"] = len(adr_tickers)
        meta["adr_added_to_r1000"] = sorted(set(adr_tickers) - set(r1000_tickers))
        if cycle_tickers:
            meta["cycle_play_count"] = len(cycle_tickers)
            meta["cycle_play_added"] = sorted(
                set(cycle_tickers) - set(r1000_tickers) - set(adr_tickers)
            )
        if hardware_tickers:
            meta["strategic_global_hardware_count"] = len(hardware_tickers)
            meta["strategic_global_hardware_added"] = sorted(
                set(hardware_tickers) - set(r1000_tickers) - set(adr_tickers) - set(cycle_tickers)
            )
        return combined, meta

    if source == "r1000+cycle":
        # R1000 + cycle play (no ADR) — minor variant for cycle-only research
        r1000_tickers, r1000_meta = load_universe(
            "r1000", max_age_hours=max_age_hours,
            min_market_value_musd=min_market_value_musd,
        )
        cycle_tickers, _ = load_cycle_play_universe(
            min_mcap_usd_b=cycle_play_min_mcap_usd_b,
            max_mcap_usd_b=cycle_play_max_mcap_usd_b,
        )
        combined = sorted(set(r1000_tickers) | set(cycle_tickers))
        meta["source_used"] = f"{r1000_meta.get('source_used', 'r1000')}+cycle"
        meta["count"] = len(combined)
        meta["r1000_count"] = len(r1000_tickers)
        meta["cycle_play_count"] = len(cycle_tickers)
        meta["cycle_play_added"] = sorted(set(cycle_tickers) - set(r1000_tickers))
        return combined, meta

    if source in ("r1000", "auto"):
        # 1st try: live IWB
        df = fetch_iwb_holdings()
        if not df.empty:
            # Filter by market value if present
            if "Market Value" in df.columns and min_market_value_musd > 0:
                # IWB stores as comma-formatted string like "3,320,046,576.12"
                mv_str = df["Market Value"].astype(str).str.replace(",", "", regex=False)
                mv = pd.to_numeric(mv_str, errors="coerce").fillna(0.0)
                # Market Value in IWB is dollars, convert to millions
                df = df[mv / 1e6 >= min_market_value_musd].copy()
            tickers_out = sorted(df["ticker"].unique())
            meta["source_used"] = "iwb_live"
            meta["count"] = len(tickers_out)
            return tickers_out, meta

        # 2nd try: main engine cache
        df = fetch_from_main_engine_cache()
        if not df.empty:
            tickers_out = sorted(df["ticker"].unique())
            meta["source_used"] = "main_engine_cache"
            meta["count"] = len(tickers_out)
            return tickers_out, meta

    # Final fallback: themes.yaml (legacy)
    tickers_out = fetch_from_themes()
    meta["source_used"] = "themes_fallback"
    meta["count"] = len(tickers_out)
    meta["warning"] = "R1000 sources unavailable; using hardcoded themes.yaml as fallback"
    return tickers_out, meta


# --- Theme annotation (not universe gate!) ---------------------------------

def annotate_with_themes(
    tickers: list[str],
) -> dict[str, dict]:
    """Return per-ticker theme metadata. Tickers NOT in themes.yaml get:
        {"themes": [], "phase": "unknown", "is_unknown": True}
    This surfaces tickers that may be emerging-theme candidates.
    """
    from r1000_themes import load_themes, map_tickers_to_themes
    themes = load_themes()
    ticker_to_themes = map_tickers_to_themes(themes) if themes else {}

    out: dict[str, dict] = {}
    for t in tickers:
        memberships = ticker_to_themes.get(t, [])
        out[t] = {
            "themes": memberships,
            "phase": "unknown",        # will be filled by theme aggregator
            "is_unknown": len(memberships) == 0,
        }
    return out


# --- Smoke test ------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("Universe Loader - Smoke Test (no hardcoded tickers)")
    print("=" * 70)

    print("\n[1] R1000 from iShares IWB (live):")
    tickers, meta = load_universe("r1000")
    print(f"  source_used: {meta['source_used']}")
    print(f"  count: {meta['count']}")
    if tickers:
        print(f"  first 10: {tickers[:10]}")
        print(f"  last 10:  {tickers[-10:]}")

    print("\n[2] Theme coverage audit:")
    if tickers:
        annotations = annotate_with_themes(tickers)
        known = sum(1 for a in annotations.values() if not a["is_unknown"])
        unknown = len(tickers) - known
        pct_covered = known / len(tickers) * 100.0
        print(f"  total R1000 tickers:     {len(tickers)}")
        print(f"  in themes.yaml:          {known} ({pct_covered:.0f}%)")
        print(f"  unknown theme:           {unknown} ({100-pct_covered:.0f}%)")
        print()
        unknowns = sorted([t for t, a in annotations.items() if a["is_unknown"]])
        print(f"  sample 'unknown theme' tickers (first 30):")
        print(f"  {unknowns[:30]}")
        print()
        print(f"  -> these {unknown} tickers are CURRENTLY INVISIBLE to scanner")
        print(f"     after refactor, they will be scanned with phase='unknown'")
        print(f"     unknown-theme candidates showing strength = emerging theme signal")

    print("\nPASS")
