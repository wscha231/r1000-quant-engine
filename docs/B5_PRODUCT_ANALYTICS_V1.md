# B5 Product Analytics V1 — pre-transmission foundation

Status: `PREPARED_NOT_TRANSMITTING`

This contract is B-side only. It does not change Leadership, RS, Fundamentals,
ER/Thesis, ranking, portfolio targets, broker/paper books, publication authority,
or any A-side investment meaning.

## Purpose

Establish a deterministic, privacy-minimal analytics contract before any browser
tracking is transmitted. V1 measures only session-level product-value proxies
from explicit, consented event exports/fixtures. It does not create a collector,
persistent anonymous identifier, signup system, user-level retention identity,
payment flow, advertising profile, or session replay.

## Privacy boundary

- analytics consent is required before an event may exist;
- pre-auth identity is an ephemeral session ID only;
- persistent anonymous IDs and user IDs are prohibited in v1;
- raw IP, full user-agent/referrer, free-text search, email, phone, account and
  broker fields are not part of the schema;
- autocapture, session replay, ad tracking and cross-site tracking remain off;
- raw events must not be stored in the public GitHub repository;
- raw event retention is capped at 90 days when a private collector is later
  approved; identifier-free aggregates are capped at 13 months.

## Allowed events

1. `site_viewed`
2. `research_search_succeeded`
3. `research_source_opened`
4. `trade_ledger_opened`

A qualified anonymous value session requires a usable-data
`research_search_succeeded` plus either `research_source_opened` or
`trade_ledger_opened` in the same deterministic session segment. `site_viewed`
alone is never activation.

## Session and data-state rules

The canonical timeout is 30 minutes of inactivity. The offline aggregator does
not trust a client session ID across an inactivity gap: it deterministically
splits the supplied ID when the gap exceeds 1,800 seconds.

Only a session segment whose every event has `data_state=USABLE` may form a
qualified value session. A mixed segment containing any stale, degraded,
incomplete or blocked event is classified as degraded and cannot count as a
qualified activation proxy.

KPI dates use `Asia/Seoul` calendar days. Raw timestamps remain UTC.

Offline inputs fail closed before aggregation: event exports are bounded to
16 MiB and 100,000 events; decoded JSON is bounded to depth 32 and 2,000,000
value/container nodes across the complete export, including JSONL inputs.
Timestamp conversion into the KPI timezone also fails closed on range overflow.
The optional `--contract` path may not weaken the
frozen v1 identity, consent, field allowlist/denylist, tracking or transmission
boundary.

## D1 / D7 / D30

User retention is deliberately `NOT_AVAILABLE` in v1 because the privacy gate
forbids persistent anonymous/user identifiers and signup is not implemented.
Do not convert missing user identity into zero retention. The current measurable
proxy is `anonymous_qualified_value_session_rate` among usable sessions.

## Deployment boundary

`collector_endpoint=null` and `transmission_enabled=false` are frozen v1
requirements. Browser instrumentation and a private first-party collector are a
separate B5-P01b task after hosting/provider review and privacy-policy update.
No public-site file is changed by this foundation PR, so the frozen B1 homepage
PR can remain independent.
