#!/usr/bin/env python3
"""Point-in-time security lifecycle contract shared by Run287 consumers.

The component deliberately separates issuer/security identity from a trading
symbol.  It never removes an economic security merely because a quote is
missing.  A terminal event becomes actionable only after its effective date,
its exact public availability time, and an approved evidence review all agree.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


SCHEMA_VERSION = "run287-security-lifecycle-v1"
BLOCKED_STATUS = "BLOCKED_LIFECYCLE_EVIDENCE"
BLOCKED_NON_USD_LIFECYCLE_PROCEEDS = "BLOCKED_NON_USD_LIFECYCLE_PROCEEDS"
TERMINAL_EVENT_TYPES = {"cash_merger", "liquidation", "bankruptcy", "delisting"}
IDENTITY_EVENT_TYPES = {"ticker_change", "security_successor"}
EVENT_TYPES = TERMINAL_EVENT_TYPES | IDENTITY_EVENT_TYPES
REQUIRED_COLUMNS = {
    "stable_security_id",
    "stable_issuer_id",
    "ticker",
    "aliases",
    "event_type",
    "available_from",
    "effective_date",
    "last_trading_date",
    "predecessor_security_id",
    "successor_security_id",
    "successor_ticker",
    "cash_consideration",
    "delisting_proceeds",
    "currency",
    "source_url",
    "accession_number",
    "stable_event_id",
    "source_sha256",
    "exact_available_from",
    "evidence_status",
    "review_status",
    "notes",
}
VERIFIED_EVIDENCE = {"verified"}
APPROVED_REVIEW = {"approved"}
TRUE_VALUES = {"1", "true", "yes", "y"}
STABLE_ID_RE = re.compile(r"^[A-Z][A-Z0-9_.:-]{2,127}$")
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")


class SecurityLifecycleError(ValueError):
    """Fail-closed lifecycle contract error with a machine-readable status."""

    def __init__(self, reason: str, *, status: str = BLOCKED_STATUS) -> None:
        super().__init__(f"{status}:{reason}")
        self.status = status
        self.reason = reason


def _ticker(value: Any) -> str:
    text = str(value or "").strip().upper()
    return "" if text in {"", "NAN", "NONE"} else text


def _bool(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUE_VALUES


def _aliases(value: Any, ticker: str) -> tuple[str, ...]:
    values = {_ticker(item) for item in str(value or "").split("|")}
    values.add(ticker)
    return tuple(sorted(item for item in values if item))


def _utc(value: Any) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise SecurityLifecycleError("invalid_available_from")
    return pd.Timestamp(parsed)


def _date(value: Any, *, field: str, required: bool = True) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        if required:
            raise SecurityLifecycleError(f"invalid_{field}")
        return None
    return pd.Timestamp(parsed).normalize()


def _number(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = pd.to_numeric(text, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SecurityLifecycleSnapshot:
    source_path: Path | None
    source_sha256: str
    session_date: str
    decision_time_utc: str
    applicable_events: pd.DataFrame
    terminal_events: pd.DataFrame
    identity_events: pd.DataFrame
    terminal_tickers: frozenset[str]
    provider_symbol_overrides: dict[str, str]
    provider_symbol_links: dict[str, dict[str, str]]
    snapshot_hash: str

    def audit(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "source_path": str(self.source_path) if self.source_path is not None else "",
            "source_sha256": self.source_sha256,
            "session_date": self.session_date,
            "decision_time_utc": self.decision_time_utc,
            "applicable_event_count": int(len(self.applicable_events)),
            "terminal_event_count": int(len(self.terminal_events)),
            "identity_event_count": int(len(self.identity_events)),
            "terminal_tickers": sorted(self.terminal_tickers),
            "provider_symbol_overrides": dict(sorted(self.provider_symbol_overrides.items())),
            "provider_symbol_links": {
                key: dict(sorted(value.items()))
                for key, value in sorted(self.provider_symbol_links.items())
            },
            "snapshot_hash": self.snapshot_hash,
            "pit_universe_label_clean": False,
            "survivorship_coverage_claimed": False,
        }


def empty_snapshot(
    *, session_date: pd.Timestamp, decision_time_utc: pd.Timestamp
) -> SecurityLifecycleSnapshot:
    columns = sorted(REQUIRED_COLUMNS)
    empty = pd.DataFrame(columns=columns)
    session = pd.Timestamp(session_date).normalize().date().isoformat()
    decision = _utc(decision_time_utc).isoformat()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "session_date": session,
        "events": [],
    }
    return SecurityLifecycleSnapshot(
        source_path=None,
        source_sha256="",
        session_date=session,
        decision_time_utc=decision,
        applicable_events=empty.copy(),
        terminal_events=empty.copy(),
        identity_events=empty.copy(),
        terminal_tickers=frozenset(),
        provider_symbol_overrides={},
        provider_symbol_links={},
        snapshot_hash=canonical_hash(payload),
    )


def load_security_lifecycle(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"security_lifecycle_events_missing:{path}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise SecurityLifecycleError("columns_missing:" + ",".join(missing))
    if frame.empty:
        return frame.reindex(columns=sorted(REQUIRED_COLUMNS))

    out = frame.copy()
    out["ticker"] = out["ticker"].map(_ticker)
    out["successor_ticker"] = out["successor_ticker"].map(_ticker)
    for column in (
        "stable_security_id",
        "stable_issuer_id",
        "predecessor_security_id",
        "successor_security_id",
        "stable_event_id",
    ):
        out[column] = out[column].astype(str).str.strip().str.upper()
    out["event_type"] = out["event_type"].astype(str).str.strip().str.lower()
    out["evidence_status"] = out["evidence_status"].astype(str).str.strip().str.lower()
    out["review_status"] = out["review_status"].astype(str).str.strip().str.lower()
    out["currency"] = out["currency"].astype(str).str.strip().str.upper()
    out["exact_available_from"] = out["exact_available_from"].map(_bool)
    out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce", utc=True)
    out["effective_date"] = pd.to_datetime(out["effective_date"], errors="coerce").dt.normalize()
    out["last_trading_date"] = pd.to_datetime(
        out["last_trading_date"], errors="coerce"
    ).dt.normalize()
    out["cash_consideration"] = pd.to_numeric(out["cash_consideration"], errors="coerce")
    out["delisting_proceeds"] = pd.to_numeric(out["delisting_proceeds"], errors="coerce")
    out["aliases_normalized"] = ["|".join(_aliases(value, ticker)) for value, ticker in zip(out["aliases"], out["ticker"])]

    stable_ok = out["stable_security_id"].str.fullmatch(STABLE_ID_RE)
    issuer_ok = out["stable_issuer_id"].str.fullmatch(STABLE_ID_RE)
    event_id_ok = out["stable_event_id"].str.fullmatch(STABLE_ID_RE)
    ticker_ok = out["ticker"].str.fullmatch(TICKER_RE)
    sha_ok = out["source_sha256"].astype(str).str.fullmatch(r"[0-9a-fA-F]{64}")
    url_ok = out["source_url"].astype(str).str.startswith("https://")
    structural_bad = (
        ~stable_ok
        | ~issuer_ok
        | ~event_id_ok
        | ~ticker_ok
        | ~out["event_type"].isin(EVENT_TYPES)
        | out["available_from"].isna()
        | out["effective_date"].isna()
        | ~sha_ok
        | ~url_ok
    )
    if structural_bad.any():
        ids = out.loc[structural_bad, "stable_event_id"].replace("", "<blank>").tolist()
        raise SecurityLifecycleError("invalid_rows:" + ",".join(ids))

    for row in out.itertuples(index=False):
        aliases = set(str(row.aliases_normalized).split("|"))
        if any(not TICKER_RE.fullmatch(alias) for alias in aliases if alias):
            raise SecurityLifecycleError(f"invalid_alias:{row.stable_event_id}")
        if row.event_type in TERMINAL_EVENT_TYPES and pd.isna(row.last_trading_date):
            raise SecurityLifecycleError(f"missing_last_trading_date:{row.stable_event_id}")
        if row.event_type in IDENTITY_EVENT_TYPES:
            if pd.isna(row.last_trading_date):
                raise SecurityLifecycleError(f"missing_last_trading_date:{row.stable_event_id}")
            if pd.Timestamp(row.last_trading_date) >= pd.Timestamp(row.effective_date):
                raise SecurityLifecycleError(
                    f"identity_cutover_not_after_last_trade:{row.stable_event_id}"
                )
            if not row.successor_ticker or not TICKER_RE.fullmatch(row.successor_ticker):
                raise SecurityLifecycleError(f"missing_successor_ticker:{row.stable_event_id}")
            if not STABLE_ID_RE.fullmatch(row.predecessor_security_id or ""):
                raise SecurityLifecycleError(f"invalid_predecessor_security_id:{row.stable_event_id}")
            if not STABLE_ID_RE.fullmatch(row.successor_security_id or ""):
                raise SecurityLifecycleError(f"invalid_successor_security_id:{row.stable_event_id}")
            if row.event_type == "ticker_change" and not (
                row.stable_security_id
                == row.predecessor_security_id
                == row.successor_security_id
            ):
                raise SecurityLifecycleError(f"ticker_change_security_mismatch:{row.stable_event_id}")
    return out.sort_values(["available_from", "stable_event_id"]).reset_index(drop=True)


def _event_is_verified(row: Any) -> bool:
    return bool(
        row.exact_available_from
        and row.evidence_status in VERIFIED_EVIDENCE
        and row.review_status in APPROVED_REVIEW
    )


def _terminal_proceeds(row: Any) -> float | None:
    if row.event_type == "cash_merger":
        value = _number(row.cash_consideration)
        return value if value is not None and value > 0 else None
    value = _number(row.delisting_proceeds)
    return value if value is not None and value >= 0 else None


def resolve_security_lifecycle(
    path: Path | None,
    *,
    session_date: pd.Timestamp,
    decision_time_utc: pd.Timestamp,
    active_tickers: Iterable[str] | None = None,
) -> SecurityLifecycleSnapshot:
    session = pd.Timestamp(session_date).normalize()
    decision = _utc(decision_time_utc)
    if path is None:
        return empty_snapshot(session_date=session, decision_time_utc=decision)
    source = Path(path)
    frame = load_security_lifecycle(source)
    known = frame.loc[
        frame["effective_date"].le(session) & frame["available_from"].le(decision)
    ].copy()
    if known.empty:
        base = empty_snapshot(session_date=session, decision_time_utc=decision)
        return SecurityLifecycleSnapshot(
            **{**base.__dict__, "source_path": source, "source_sha256": file_sha256(source)}
        )

    active = None if active_tickers is None else {_ticker(value) for value in active_tickers}
    relevant_rows: list[int] = []
    for index, row in known.iterrows():
        aliases = set(str(row["aliases_normalized"]).split("|"))
        aliases.add(_ticker(row["successor_ticker"]))
        if active is None or bool((aliases - {""}) & active):
            relevant_rows.append(index)
    relevant = known.loc[relevant_rows].copy() if relevant_rows else known.iloc[0:0].copy()

    unverified = relevant.loc[
        ~relevant.apply(lambda row: _event_is_verified(row), axis=1)
    ]
    if not unverified.empty:
        raise SecurityLifecycleError(
            "unverified_active_events:" + ",".join(unverified["stable_event_id"].tolist())
        )

    terminals = known.loc[known["event_type"].isin(TERMINAL_EVENT_TYPES)].copy()
    duplicate_ids = terminals.loc[
        terminals["stable_security_id"].duplicated(False), "stable_security_id"
    ].unique()
    if len(duplicate_ids):
        raise SecurityLifecycleError(
            "duplicate_active_terminal_events:" + ",".join(sorted(map(str, duplicate_ids)))
        )

    relevant_terminals = relevant.loc[
        relevant["event_type"].isin(TERMINAL_EVENT_TYPES)
    ].copy()
    missing_proceeds: list[str] = []
    proceeds: list[float] = []
    for row in relevant_terminals.itertuples(index=False):
        value = _terminal_proceeds(row)
        if value is None:
            missing_proceeds.append(str(row.stable_event_id))
            proceeds.append(float("nan"))
        else:
            proceeds.append(value)
    if missing_proceeds:
        raise SecurityLifecycleError("missing_verified_proceeds:" + ",".join(missing_proceeds))
    if not relevant_terminals.empty:
        non_usd = relevant_terminals.loc[
            relevant_terminals["currency"].ne("USD"), "stable_event_id"
        ].tolist()
        if non_usd:
            raise SecurityLifecycleError(
                "non_usd_terminal_proceeds:" + ",".join(map(str, non_usd)),
                status=BLOCKED_NON_USD_LIFECYCLE_PROCEEDS,
            )
        relevant_terminals["verified_proceeds"] = proceeds
        if (relevant_terminals["last_trading_date"] > relevant_terminals["effective_date"]).any():
            bad = relevant_terminals.loc[
                relevant_terminals["last_trading_date"] > relevant_terminals["effective_date"],
                "stable_event_id",
            ].tolist()
            raise SecurityLifecycleError("last_trade_after_effective_date:" + ",".join(bad))
    proceeds_by_event = {
        str(row.stable_event_id): float(row.verified_proceeds)
        for row in relevant_terminals.itertuples(index=False)
    }

    identity = relevant.loc[relevant["event_type"].isin(IDENTITY_EVENT_TYPES)].copy()
    overrides: dict[str, str] = {}
    links: dict[str, dict[str, str]] = {}
    for row in identity.itertuples(index=False):
        successor = _ticker(row.successor_ticker)
        for alias in str(row.aliases_normalized).split("|"):
            alias = _ticker(alias)
            if alias and alias != successor:
                prior = overrides.setdefault(alias, successor)
                if prior != successor:
                    raise SecurityLifecycleError(f"conflicting_successor:{alias}")
                link = {
                    "stable_event_id": str(row.stable_event_id),
                    "predecessor_ticker": alias,
                    "successor_ticker": successor,
                    "effective_date": pd.Timestamp(row.effective_date).date().isoformat(),
                    "last_trading_date": pd.Timestamp(row.last_trading_date).date().isoformat(),
                }
                existing = links.setdefault(alias, link)
                if existing != link:
                    raise SecurityLifecycleError(f"conflicting_successor_link:{alias}")

    terminal_tickers: set[str] = set()
    for row in relevant_terminals.itertuples(index=False):
        terminal_tickers.update(_aliases(row.aliases_normalized, _ticker(row.ticker)))

    audit_rows = []
    for row in relevant.to_dict("records"):
        audit_rows.append(
            {
                "stable_event_id": row["stable_event_id"],
                "stable_security_id": row["stable_security_id"],
                "ticker": row["ticker"],
                "event_type": row["event_type"],
                "available_from": pd.Timestamp(row["available_from"]).isoformat(),
                "effective_date": pd.Timestamp(row["effective_date"]).date().isoformat(),
                "last_trading_date": (
                    pd.Timestamp(row["last_trading_date"]).date().isoformat()
                    if pd.notna(row["last_trading_date"])
                    else None
                ),
                "predecessor_security_id": row["predecessor_security_id"],
                "successor_security_id": row["successor_security_id"],
                "successor_ticker": row["successor_ticker"],
                "aliases_normalized": row["aliases_normalized"],
                "currency": row["currency"],
                "verified_proceeds": (
                    proceeds_by_event.get(str(row["stable_event_id"]))
                ),
                "source_sha256": row["source_sha256"],
            }
        )
    snapshot_hash = canonical_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "session_date": session.date().isoformat(),
            "events": audit_rows,
        }
    )
    return SecurityLifecycleSnapshot(
        source_path=source,
        source_sha256=file_sha256(source),
        session_date=session.date().isoformat(),
        decision_time_utc=decision.isoformat(),
        applicable_events=relevant.reset_index(drop=True),
        terminal_events=relevant_terminals.reset_index(drop=True),
        identity_events=identity.reset_index(drop=True),
        terminal_tickers=frozenset(terminal_tickers),
        provider_symbol_overrides=overrides,
        provider_symbol_links=links,
        snapshot_hash=snapshot_hash,
    )


def filter_terminal_tickers(
    frame: pd.DataFrame,
    snapshot: SecurityLifecycleSnapshot,
    *,
    ticker_column: str = "ticker",
) -> pd.DataFrame:
    if frame.empty or not snapshot.terminal_tickers:
        return frame.copy()
    tickers = frame[ticker_column].map(_ticker)
    return frame.loc[~tickers.isin(snapshot.terminal_tickers)].copy()


def verified_settlement_by_ticker(
    snapshot: SecurityLifecycleSnapshot,
) -> dict[str, dict[str, Any]]:
    settlements: dict[str, dict[str, Any]] = {}
    for row in snapshot.terminal_events.to_dict("records"):
        payload = {
            **row,
            "verified_proceeds": float(row["verified_proceeds"]),
        }
        for alias in _aliases(row.get("aliases_normalized"), _ticker(row.get("ticker"))):
            if alias in settlements:
                raise SecurityLifecycleError(f"duplicate_terminal_alias:{alias}")
            settlements[alias] = payload
    return settlements
