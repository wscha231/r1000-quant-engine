#!/usr/bin/env python3
"""etf_leadership_snapshot - Phase 17 v3 Layer 8 ETF leadership tracker.

Captures trailing 1m / 3m / 6m returns for major sector and theme ETFs. The
leader_state output can feed adaptive sector caps, concentrated picker bias,
and monthly alerting.

Usage
-----
    python tools/etf_leadership_snapshot.py
    python tools/etf_leadership_snapshot.py --telegram
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "cloud_results" / "etf_leadership"

# Tickers to track + their human-readable theme labels
SECTOR_ETFS = {
    "XLK": "tech",
    "XLF": "financials",
    "XLE": "energy",
    "XLV": "health_care",
    "XLY": "consumer_discretionary",
    "XLI": "industrials",
    "XLB": "materials",
    "XLP": "consumer_staples",
    "XLU": "utilities",
    "XLRE": "real_estate",
    "XLC": "communication_services",
}

THEME_ETFS = {
    "DRAM": "memory_semiconductors",
    "SOXX": "semiconductors",
    "SMH": "semiconductors_broad",
    "XSD": "semiconductors_equal_weight",
    "XBI": "biotech_small",
    "IBB": "biotech_large",
    "ARKK": "innovation",
    "ICLN": "clean_energy",
    "KWEB": "china_internet",
    "TAN": "solar",
    "XME": "mining",
    "XOP": "oil_gas_ep",
    "XHB": "homebuilders",
}

ALL_ETFS = {**SECTOR_ETFS, **THEME_ETFS}

# Leader state thresholds (trailing 1m return)
LEADER_HOT_RET_1M = 0.08      # > 8% in 1mo = leader
LEADER_WARM_RET_1M = 0.04     # > 4% = warm
LEADER_COLD_RET_1M = -0.04    # < -4% = lagging
LEADER_BEAR_RET_1M = -0.08    # < -8% = capitulating


def fetch_etf_history(ticker: str, days: int = 260):
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        from datetime import timedelta
        end = datetime.now()
        start = end - timedelta(days=int(days * 1.7))
        df = yf.Ticker(ticker).history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
        )
        if df.empty:
            return None
        return df
    except Exception:
        return None


def compute_etf_metrics(ticker: str, label: str, *, history_loader=None) -> dict | None:
    df = (history_loader or fetch_etf_history)(ticker)
    if df is None or len(df) < 22:
        return None
    close = df["Close"]
    last = float(close.iloc[-1])
    rec = {
        "ticker": ticker,
        "label": label,
        "close": last,
    }
    for window_days, name in ((21, "ret_1m"), (63, "ret_3m"), (126, "ret_6m")):
        if len(close) > window_days:
            base = float(close.iloc[-window_days - 1])
            rec[name] = float(last / base - 1.0) if base > 0 else None
        else:
            rec[name] = None
    # Vs SPY relative strength (approximate -- use cached SPY if available)
    return rec


def classify_state(ret_1m: float | None) -> str:
    if ret_1m is None:
        return "unknown"
    if ret_1m >= LEADER_HOT_RET_1M:
        return "hot"
    if ret_1m >= LEADER_WARM_RET_1M:
        return "warm"
    if ret_1m <= LEADER_BEAR_RET_1M:
        return "capitulating"
    if ret_1m <= LEADER_COLD_RET_1M:
        return "lagging"
    return "neutral"


def build_snapshot(*, history_loader=None) -> dict:
    asof = datetime.now(timezone.utc)
    snap = {
        "asof": asof.strftime("%Y-%m-%d %H:%M UTC"),
        "asof_date": asof.strftime("%Y-%m-%d"),
        "etfs": {},
        "leaders_1m": [],
        "laggards_1m": [],
        "sector_states": {},
    }

    metrics: list[dict] = []
    for ticker, label in ALL_ETFS.items():
        m = compute_etf_metrics(ticker, label, history_loader=history_loader)
        if m is None:
            continue
        m["state_1m"] = classify_state(m.get("ret_1m"))
        metrics.append(m)
        snap["etfs"][ticker] = m

    # Rank leaders / laggards by 1m return
    valid_1m = [m for m in metrics if m.get("ret_1m") is not None]
    valid_1m.sort(key=lambda m: m["ret_1m"], reverse=True)
    snap["leaders_1m"] = [
        {"ticker": m["ticker"], "label": m["label"], "ret_1m": m["ret_1m"], "state": m["state_1m"]}
        for m in valid_1m[:5]
    ]
    snap["laggards_1m"] = [
        {"ticker": m["ticker"], "label": m["label"], "ret_1m": m["ret_1m"], "state": m["state_1m"]}
        for m in valid_1m[-5:]
    ]
    # Sector-only state map (used by adaptive sleeve cap downstream)
    snap["sector_states"] = {
        SECTOR_ETFS[m["ticker"]]: m["state_1m"]
        for m in metrics
        if m["ticker"] in SECTOR_ETFS
    }

    return snap


def telegram_send(msg: str) -> None:
    tok = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15).read()
    except Exception:
        pass


def publish_rotation_review(result, producer, observed_at, contract, remote=None):
    """Publish originals privately, then a decoder-bound metadata capsule."""
    import hashlib
    from tools import run287_etf_rotation as helper
    if remote is None:
        from tools.macro_research_checkpoint import RcloneTransport
        namespace = os.environ.get("MACRO_RESEARCH_REMOTE", "")
        if not namespace.endswith("/scheduled"):
            return helper.public_receipt(result, producer, observed_at, None)
        remote = RcloneTransport(namespace)
    receipt = helper.publish_private(result, producer, observed_at, remote)
    if receipt["private_payload_sha256"] is None:
        return receipt
    try:
        raw = helper.canonical({**result, "producer": producer, "observed_at_utc": observed_at.isoformat()})
        restored = remote.read(helper.PRIVATE_PREFIX + receipt["private_payload_sha256"])
        if len(restored) > 1_000_000 or restored != raw:
            raise ValueError("private_original_readback")
        requests = helper.decode_a3_review_requests({**receipt, "status": receipt["price_status"]}, restored, contract)
        fields = ("request_id", "agent", "subject", "status", "event_family", "requested_slices", "requires", "execute")
        capsule = dict(schema="etf-published-review-handoff-v1", producer=producer,
            observed_at_utc=observed_at.isoformat(), session=receipt["session"],
            private_payload_sha256=receipt["private_payload_sha256"], readback_sha256=helper.sha256(restored),
            decoder="tools.run287_etf_rotation.decode_a3_review_requests",
            decoder_git_lf_sha256=hashlib.sha256(Path(helper.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
            producer_git_lf_sha256=hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
            policy_sha256=receipt["policy_sha256"], requests=[{k: r[k] for k in fields} for r in requests], safety=helper.SAFETY)
        capsule["binding_sha256"] = helper.sha256(helper.canonical(capsule))
        receipt["safe_review_handoff"] = capsule
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        receipt["safe_review_error"] = "PRIVATE_READBACK_OR_DECODER_REFUSED"
    return receipt


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--telegram", action="store_true")
    p.add_argument("--out-dir", default=str(OUTPUT_DIR))
    p.add_argument("--scheduled-rotation", action="store_true")
    args = p.parse_args()

    rotation = None
    if args.scheduled_rotation:
        if (os.environ.get("GITHUB_REF") != "refs/heads/master"
                or os.environ.get("GITHUB_EVENT_NAME") != "schedule"
                or os.environ.get("GITHUB_REPOSITORY") != "wscha231/r1000-quant-engine"):
            p.error("rotation requires the existing scheduled default-branch run")
        sys.path.insert(0, str(REPO_ROOT))
        from tools.run287_etf_rotation import ScheduledRotation

        try:
            contract = json.loads((REPO_ROOT / "docs/run287_daily_research_monitor_contract.json").read_bytes())
            rotation = ScheduledRotation(contract, datetime.now(timezone.utc))
        except (ImportError, OSError, ValueError, KeyError, TypeError):
            print("[etf-rotation] CONFIGURATION_BLOCKED")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    loader = None if rotation is None else lambda ticker: rotation.legacy_history(fetch_etf_history, ticker)
    snap = build_snapshot(history_loader=loader)

    daily_path = out_dir / f"snapshot_{snap['asof_date']}.json"
    daily_path.write_text(json.dumps(snap, indent=2, default=str))
    (out_dir / "latest.json").write_text(json.dumps(snap, indent=2, default=str))

    # CSV leaderboard for human review
    try:
        import pandas as pd
        rows = list(snap["etfs"].values())
        if rows:
            df = pd.DataFrame(rows)[["ticker", "label", "close", "ret_1m", "ret_3m", "ret_6m", "state_1m"]]
            df = df.sort_values("ret_1m", ascending=False, na_position="last")
            df.to_csv(out_dir / "leaderboard_30d.csv", index=False)
    except ImportError:
        pass

    print(f"[etf-leader] {len(snap['etfs'])} ETFs scored")
    print(f"[etf-leader] top leaders 1m:")
    for l in snap["leaders_1m"]:
        ret = l.get("ret_1m")
        print(f"             {l['ticker']:>5}  {l['label']:<25}  {ret:+.2%}  ({l['state']})")
    print(f"[etf-leader] sector states: {snap['sector_states']}")
    print(f"[etf-leader] wrote {daily_path}")

    if args.telegram and snap["leaders_1m"]:
        body = [f"[etf-leadership {snap['asof_date']}]", "Top 5 leaders (1m):"]
        for l in snap["leaders_1m"]:
            ret = l.get("ret_1m") or 0
            body.append(f"  {l['ticker']:>5} {l['label']:<22} {ret:+.2%}")
        body.append("Bottom 5 (1m):")
        for l in snap["laggards_1m"]:
            ret = l.get("ret_1m") or 0
            body.append(f"  {l['ticker']:>5} {l['label']:<22} {ret:+.2%}")
        telegram_send("\n".join(body))
    if rotation is not None:
        from tools.run287_etf_rotation import canonical

        try:
            result = rotation.finish()
            producer = {"run_id": int(os.environ["GITHUB_RUN_ID"]),
                        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
                        "head_sha": os.environ["GITHUB_SHA"]}
            receipt = publish_rotation_review(result, producer, datetime.now(timezone.utc), rotation.contract)
            destination = REPO_ROOT / "outputs/after_close_daily/etf_rotation_receipt.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as handle:
                handle.write(canonical(receipt))
            print(f"[etf-rotation] {receipt['price_status']} / {receipt['a3_handoff_status']}")
        except (ImportError, OSError, ValueError, KeyError, TypeError):
            print("[etf-rotation] OBSERVATION_BLOCKED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
