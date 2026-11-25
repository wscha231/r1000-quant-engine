from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Iterable, Mapping
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
from urllib.request import Request, urlopen

CHECKPOINT_SCHEMA = "telegram-insidertracking-checkpoint-v1"
EVENT_SCHEMA = "telegram-insidertracking-event-v1"
A2_SCHEMA = "a2-telegram-discovery-input-v1"
LATEST_POINTER_SCHEMA = "telegram-insidertracking-latest-pointer-v1"
POINTER_FILES = ("checkpoint.json", "events.ndjson", "a2_discovery_inputs.json", "receipt.json")
RUN_KEY_RE = re.compile(r"^[0-9]+-[0-9]+$")
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 50_000
MAX_PAGES_DEFAULT = 10
CHANNEL_RE = re.compile(r"^[A-Za-z0-9_]{3,64}$")
POST_RE = re.compile(r"^([A-Za-z0-9_]{3,64})/(\d+)$")
TICKER_RE = re.compile(r"(?<![A-Za-z0-9])\$?([A-Z]{2,5}(?:\.[A-Z])?)(?![A-Za-z0-9])")

CATEGORY_TERMS = {
    "AI_SEMICONDUCTORS": ("AI", "인공지능", "반도체", "HBM", "GPU", "NVIDIA", "NVDA", "MICRON", "MU", "TSMC", "TSM", "ASML"),
    "ENERGY_COMMODITIES": ("원유", "유가", "OIL", "CRUDE", "천연가스", "NATURAL GAS", "LNG", "우라늄", "URANIUM", "구리", "COPPER", "금 ", "GOLD"),
    "GEOPOLITICS_DEFENSE": ("전쟁", "공습", "미사일", "드론", "이란", "이스라엘", "레바논", "후티", "러시아", "우크라이나", "대만", "중국", "제재", "방산", "DEFENSE", "SANCTION", "WAR"),
    "RATES_FX_LIQUIDITY": ("금리", "연준", "FED", "FOMC", "국채", "YIELD", "달러", "엔화", "환율", "CFTC", "LIQUIDITY", "RRP", "TGA"),
    "CRYPTO": ("비트코인", "BITCOIN", "BTC", "이더리움", "ETHEREUM", "ETH", "STABLECOIN", "스테이블코인", "RWA", "CRYPTO"),
    "EARNINGS_CORPORATE": ("실적", "가이던스", "GUIDANCE", "EARNINGS", "수주", "CONTRACT", "M&A", "인수", "합병", "CAPEX", "매출", "EPS"),
    "POLICY_MACRO": ("관세", "TARIFF", "규제", "REGULATION", "법안", "실업률", "고용", "CPI", "PCE", "GDP", "PMI", "ISM"),
}

STOP_TICKERS = {
    "AI", "US", "USA", "ETF", "CPI", "PCE", "GDP", "PMI", "ISM", "FED", "FOMC", "CFTC", "LNG", "RWA", "EPS", "SEC", "USD", "KST", "UTC", "WAR"
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_latest_pointer(*, channel: str, source_url: str, run_key: str, head_sha: str, generated_at: str, outputs: Mapping[str, bytes]) -> bytes:
    if not CHANNEL_RE.fullmatch(channel):
        raise ValueError("invalid_channel")
    validate_source_url(source_url, channel)
    if not RUN_KEY_RE.fullmatch(run_key):
        raise ValueError("invalid_pointer_run_key")
    if not HEX40_RE.fullmatch(head_sha):
        raise ValueError("invalid_pointer_head_sha")
    _parse_aware_utc(generated_at, "pointer_generated_at")
    if set(outputs) != set(POINTER_FILES):
        raise ValueError("invalid_pointer_output_set")
    pointer = {
        "schema_version": LATEST_POINTER_SCHEMA,
        "channel": channel.lower(),
        "source_url": source_url,
        "run_key": run_key,
        "head_sha": head_sha,
        "generated_at": generated_at,
        "files": {name: sha256_bytes(outputs[name]) for name in POINTER_FILES},
    }
    return canonical_json_bytes(pointer)


def parse_latest_pointer(raw: bytes, *, channel: str, source_url: str) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid_latest_pointer_json") from exc
    if value.get("schema_version") != LATEST_POINTER_SCHEMA:
        raise ValueError("invalid_latest_pointer_schema")
    if value.get("channel") != channel.lower():
        raise ValueError("latest_pointer_channel_mismatch")
    if value.get("source_url") != source_url:
        raise ValueError("latest_pointer_source_mismatch")
    if not RUN_KEY_RE.fullmatch(str(value.get("run_key") or "")):
        raise ValueError("invalid_pointer_run_key")
    if not HEX40_RE.fullmatch(str(value.get("head_sha") or "")):
        raise ValueError("invalid_pointer_head_sha")
    _parse_aware_utc(str(value.get("generated_at") or ""), "pointer_generated_at")
    files = value.get("files")
    if not isinstance(files, dict) or set(files) != set(POINTER_FILES):
        raise ValueError("invalid_pointer_files")
    if any(not HEX64_RE.fullmatch(str(files[name])) for name in POINTER_FILES):
        raise ValueError("invalid_pointer_file_hash")
    return value


def verify_latest_pointer_files(pointer: Mapping[str, object], files: Mapping[str, bytes]) -> None:
    if set(files) != set(POINTER_FILES):
        raise ValueError("pointer_file_set_mismatch")
    expected = pointer.get("files")
    if not isinstance(expected, dict):
        raise ValueError("invalid_pointer_files")
    for name in POINTER_FILES:
        if sha256_bytes(files[name]) != expected.get(name):
            raise ValueError(f"pointer_file_hash_mismatch:{name}")


def normalize_text(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\u200b", "").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    out = "\n".join(line for line in lines if line)
    return out[:MAX_TEXT_CHARS]


@dataclass(frozen=True)
class ParsedPost:
    channel: str
    post_id: int
    published_at: str | None
    text: str
    source_url: str


class _TelegramHTMLParser(HTMLParser):
    def __init__(self, expected_channel: str):
        super().__init__(convert_charrefs=True)
        self.expected_channel = expected_channel
        self._message_stack: list[dict] = []
        self._text_depth = 0
        self._time_depth = 0
        self._current_time: str | None = None
        self.posts: list[ParsedPost] = []

    def handle_starttag(self, tag: str, attrs):
        attrs_d = {k: v for k, v in attrs}
        classes = set((attrs_d.get("class") or "").split())
        data_post = attrs_d.get("data-post")
        if tag == "div" and data_post:
            match = POST_RE.match(data_post)
            if match and match.group(1).lower() == self.expected_channel.lower():
                self._message_stack.append({
                    "channel": match.group(1),
                    "post_id": int(match.group(2)),
                    "text": [],
                    "published_at": None,
                    "depth": 1,
                })
                return
        if self._message_stack:
            if tag in {"br", "img", "meta", "link", "input", "hr", "source", "wbr"}:
                if self._text_depth and tag == "br":
                    self._message_stack[-1]["text"].append("\n")
                return
            self._message_stack[-1]["depth"] += 1
            if tag == "div" and "tgme_widget_message_text" in classes:
                self._text_depth = 1
            elif self._text_depth:
                self._text_depth += 1
            if tag == "time" and attrs_d.get("datetime"):
                self._current_time = attrs_d.get("datetime")
                self._message_stack[-1]["published_at"] = self._current_time
                self._time_depth = 1
            elif self._time_depth:
                self._time_depth += 1

    def handle_startendtag(self, tag: str, attrs):
        if self._message_stack and self._text_depth and tag == "br":
            self._message_stack[-1]["text"].append("\n")

    def handle_endtag(self, tag: str):
        if not self._message_stack:
            return
        if self._text_depth:
            self._text_depth -= 1
        if self._time_depth:
            self._time_depth -= 1
            if self._time_depth == 0:
                self._current_time = None
        self._message_stack[-1]["depth"] -= 1
        if self._message_stack[-1]["depth"] == 0:
            msg = self._message_stack.pop()
            text = normalize_text("".join(msg["text"]))
            self.posts.append(ParsedPost(
                channel=msg["channel"],
                post_id=msg["post_id"],
                published_at=msg["published_at"],
                text=text,
                source_url=f"https://t.me/{msg['channel']}/{msg['post_id']}",
            ))
            self._text_depth = 0
            self._time_depth = 0

    def handle_data(self, data: str):
        if self._message_stack and self._text_depth:
            self._message_stack[-1]["text"].append(data)


def parse_telegram_html(page: bytes, expected_channel: str) -> list[ParsedPost]:
    if not CHANNEL_RE.fullmatch(expected_channel):
        raise ValueError("invalid_channel")
    if len(page) > MAX_PAGE_BYTES:
        raise ValueError("page_too_large")
    text = page.decode("utf-8", errors="strict")
    parser = _TelegramHTMLParser(expected_channel)
    parser.feed(text)
    dedup: dict[int, ParsedPost] = {}
    for post in parser.posts:
        prior = dedup.get(post.post_id)
        if prior and prior != post:
            raise ValueError(f"conflicting_duplicate_post:{post.post_id}")
        dedup[post.post_id] = post
    return [dedup[k] for k in sorted(dedup)]


def validate_source_url(source_url: str, channel: str) -> None:
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "t.me":
        raise ValueError("unapproved_source_url")
    if parsed.path.rstrip("/") != f"/s/{channel}":
        raise ValueError("source_channel_path_mismatch")


def _parse_aware_utc(value: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as exc:
        raise ValueError(f"invalid_{field}") from exc
    if dt.tzinfo is None:
        raise ValueError(f"naive_{field}")
    return dt.astimezone(timezone.utc)


def _with_before(source_url: str, before_id: int) -> str:
    parsed = urlparse(source_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["before"] = str(before_id)
    return urlunparse(parsed._replace(query=urlencode(query)))


def fetch_page(url: str, timeout: float = 20.0) -> bytes:
    req = Request(url, headers={"User-Agent": "r1000-research-telegram-ingest/1.0 (+https://github.com/wscha231/r1000-quant-engine)"})
    with urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", 200)
        if status != 200:
            raise RuntimeError(f"telegram_http_status:{status}")
        data = resp.read(MAX_PAGE_BYTES + 1)
    if len(data) > MAX_PAGE_BYTES:
        raise RuntimeError("telegram_page_too_large")
    return data


def collect_since(*, source_url: str, channel: str, last_post_id: int, max_pages: int = MAX_PAGES_DEFAULT, fetcher=fetch_page) -> tuple[list[ParsedPost], dict]:
    validate_source_url(source_url, channel)
    if last_post_id < 0:
        raise ValueError("negative_last_post_id")
    if max_pages < 1 or max_pages > 50:
        raise ValueError("invalid_max_pages")
    all_posts: dict[int, ParsedPost] = {}
    page_hashes: list[dict] = []
    next_url = source_url
    gap_unresolved = False
    for page_index in range(max_pages):
        page = fetcher(next_url)
        page_hashes.append({"url": next_url, "sha256": sha256_bytes(page), "bytes": len(page)})
        posts = parse_telegram_html(page, channel)
        if not posts:
            if page_index == 0:
                raise RuntimeError("telegram_no_posts_parsed")
            gap_unresolved = True
            break
        for post in posts:
            existing = all_posts.get(post.post_id)
            if existing and existing != post:
                raise RuntimeError(f"telegram_cross_page_conflict:{post.post_id}")
            all_posts[post.post_id] = post
        min_id = min(p.post_id for p in posts)
        if min_id <= last_post_id + 1:
            break
        next_url = _with_before(source_url, min_id)
    else:
        min_seen = min(all_posts) if all_posts else None
        if min_seen is None or min_seen > last_post_id + 1:
            gap_unresolved = True
    new_posts = [all_posts[k] for k in sorted(all_posts) if k > last_post_id]
    # Telegram message IDs can legitimately have holes (for example deleted or
    # non-public messages). Completeness is therefore defined by crossing the
    # durable checkpoint boundary in the public archive, not by requiring every
    # integer ID to exist. If bounded pagination never reaches that boundary,
    # fail closed instead of advancing.
    meta = {
        "pages_fetched": len(page_hashes),
        "page_receipts": page_hashes,
        "gap_unresolved": gap_unresolved,
        "first_new_post_id": new_posts[0].post_id if new_posts else None,
        "last_new_post_id": new_posts[-1].post_id if new_posts else None,
    }
    return new_posts, meta


def classify_text(text: str) -> tuple[list[str], list[str]]:
    upper = text.upper()
    categories = []
    for category, terms in CATEGORY_TERMS.items():
        if any(term.upper() in upper for term in terms):
            categories.append(category)
    tickers = []
    for match in TICKER_RE.finditer(text):
        ticker = match.group(1).upper()
        if ticker not in STOP_TICKERS and ticker not in tickers:
            tickers.append(ticker)
    return categories, tickers[:20]


def build_event(post: ParsedPost, collected_at: str) -> dict:
    collected_dt = _parse_aware_utc(collected_at, "collected_at")
    if post.published_at is not None:
        published_dt = _parse_aware_utc(post.published_at, "published_at")
        if published_dt > collected_dt:
            raise ValueError(f"future_published_at:{post.post_id}")
    categories, tickers = classify_text(post.text)
    relevant = bool(categories or tickers)
    return {
        "schema_version": EVENT_SCHEMA,
        "channel": post.channel.lower(),
        "post_id": post.post_id,
        "published_at": post.published_at,
        "collected_at": collected_at,
        "available_from": collected_at,
        "source_url": post.source_url,
        "text": post.text,
        "text_sha256": sha256_bytes(post.text.encode("utf-8")),
        "content_status": "TEXT" if post.text else "MEDIA_OR_EMPTY",
        "relevance_categories": categories,
        "tickers_detected": tickers,
        "a2_discovery_eligible": relevant,
        "verification_status": "UNVERIFIED_TELEGRAM_ONLY",
        "score_contribution": 0.0,
        "a3_er_eligible": False,
        "selector_eligible": False,
        "target_authority": False,
        "order_authority": False,
    }


def _seed_event_chain(channel: str, initial_last_post_id: int) -> str:
    return sha256_bytes(canonical_json_bytes({
        "domain": "telegram-event-chain-seed-v1",
        "channel": channel.lower(),
        "seed_last_post_id": initial_last_post_id,
    }))


def _extend_event_chain(previous_chain: str, *, event_delta_sha256: str, first_post_id: int, last_post_id: int, event_count: int) -> str:
    if not HEX64_RE.fullmatch(previous_chain):
        raise ValueError("invalid_previous_event_chain")
    if not HEX64_RE.fullmatch(event_delta_sha256):
        raise ValueError("invalid_event_delta_sha256")
    if event_count < 1 or first_post_id < 0 or last_post_id < first_post_id:
        raise ValueError("invalid_event_chain_delta_range")
    return sha256_bytes(canonical_json_bytes({
        "domain": "telegram-event-chain-link-v1",
        "previous_event_chain_sha256": previous_chain,
        "event_delta_sha256": event_delta_sha256,
        "first_post_id": first_post_id,
        "last_post_id": last_post_id,
        "event_count": event_count,
    }))


def parse_checkpoint(raw: bytes | None, *, channel: str, source_url: str, initial_last_post_id: int) -> tuple[dict, str | None]:
    validate_source_url(source_url, channel)
    seed_chain = _seed_event_chain(channel, initial_last_post_id)
    if raw is None or not raw.strip():
        if initial_last_post_id < 0:
            raise ValueError("invalid_initial_last_post_id")
        return {
            "schema_version": CHECKPOINT_SCHEMA,
            "channel": channel.lower(),
            "source_url": source_url,
            "last_post_id": initial_last_post_id,
            "event_chain_sha256": seed_chain,
            "bootstrap_seed": True,
        }, None
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid_checkpoint_json") from exc
    if value.get("schema_version") != CHECKPOINT_SCHEMA:
        raise ValueError("invalid_checkpoint_schema")
    if value.get("channel") != channel.lower():
        raise ValueError("checkpoint_channel_mismatch")
    if value.get("source_url") != source_url:
        raise ValueError("checkpoint_source_mismatch")
    pid = value.get("last_post_id")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < initial_last_post_id:
        raise ValueError("invalid_checkpoint_post_id")
    chain = str(value.get("event_chain_sha256") or "")
    if not HEX64_RE.fullmatch(chain):
        raise ValueError("invalid_checkpoint_event_chain")
    return value, sha256_bytes(raw)


def parse_event_delta(raw: bytes, *, channel: str, previous_last_post_id: int, current_last_post_id: int) -> list[dict]:
    out = []
    seen = set()
    for lineno, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            raise ValueError(f"invalid_event_delta_json:{lineno}") from exc
        if row.get("schema_version") != EVENT_SCHEMA or row.get("channel") != channel.lower():
            raise ValueError(f"invalid_event_delta_row:{lineno}")
        pid = row.get("post_id")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= previous_last_post_id or pid in seen:
            raise ValueError(f"invalid_or_duplicate_event_delta_id:{lineno}")
        if out and pid <= out[-1]["post_id"]:
            raise ValueError(f"event_delta_not_strictly_ascending:{lineno}")
        seen.add(pid)
        out.append(row)
    if not out:
        if current_last_post_id != previous_last_post_id:
            raise ValueError("empty_delta_with_advanced_checkpoint")
        return []
    if out[-1]["post_id"] != current_last_post_id:
        raise ValueError("event_delta_last_post_mismatch")
    return out


def encode_ndjson(rows: Iterable[dict]) -> bytes:
    return b"".join(canonical_json_bytes(row) for row in rows)


def verify_run_bundle(*, checkpoint_raw: bytes, event_delta_raw: bytes, a2_raw: bytes, receipt_raw: bytes, channel: str, source_url: str, initial_last_post_id: int) -> None:
    checkpoint, _ = parse_checkpoint(
        checkpoint_raw,
        channel=channel,
        source_url=source_url,
        initial_last_post_id=initial_last_post_id,
    )
    try:
        receipt = json.loads(receipt_raw.decode("utf-8"))
        a2 = json.loads(a2_raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid_run_bundle_json") from exc
    if receipt.get("schema_version") != "telegram-insidertracking-receipt-v1":
        raise ValueError("invalid_receipt_schema")
    if receipt.get("channel") != channel.lower() or a2.get("channel") != channel.lower():
        raise ValueError("run_bundle_channel_mismatch")
    if a2.get("schema_version") != A2_SCHEMA or a2.get("source_url") != source_url:
        raise ValueError("invalid_a2_bundle")
    if receipt.get("checkpoint_sha256") != sha256_bytes(checkpoint_raw):
        raise ValueError("receipt_checkpoint_hash_mismatch")
    if receipt.get("event_delta_sha256") != sha256_bytes(event_delta_raw):
        raise ValueError("receipt_event_delta_hash_mismatch")
    if receipt.get("a2_discovery_sha256") != sha256_bytes(a2_raw):
        raise ValueError("receipt_a2_hash_mismatch")
    if receipt.get("event_chain_sha256") != checkpoint.get("event_chain_sha256"):
        raise ValueError("receipt_event_chain_mismatch")
    if checkpoint.get("event_delta_committed") is not True or receipt.get("event_delta_committed") is not True:
        raise ValueError("uncommitted_event_delta_in_latest_bundle")
    previous_last = checkpoint.get("previous_last_post_id")
    if isinstance(previous_last, bool) or not isinstance(previous_last, int):
        raise ValueError("invalid_checkpoint_previous_last_post_id")
    parse_event_delta(
        event_delta_raw,
        channel=channel,
        previous_last_post_id=previous_last,
        current_last_post_id=checkpoint["last_post_id"],
    )
    if a2.get("score_contribution") != 0.0 or a2.get("research_only") is not True:
        raise ValueError("invalid_a2_authority_boundary")
    for row in a2.get("events") or []:
        if row.get("score_contribution") != 0.0 or row.get("requires_independent_verification") is not True:
            raise ValueError("invalid_a2_event_authority_boundary")


def build_outputs(*, channel: str, source_url: str, checkpoint_raw: bytes | None, initial_last_post_id: int, max_pages: int = MAX_PAGES_DEFAULT, fetcher=fetch_page, collected_at: str | None = None) -> dict[str, bytes]:
    if not CHANNEL_RE.fullmatch(channel):
        raise ValueError("invalid_channel")
    collected_at = collected_at or _utc_now()
    _parse_aware_utc(collected_at, "collected_at")
    old_checkpoint, old_checkpoint_sha = parse_checkpoint(
        checkpoint_raw,
        channel=channel,
        source_url=source_url,
        initial_last_post_id=initial_last_post_id,
    )
    last_post_id = old_checkpoint["last_post_id"]
    previous_event_chain = old_checkpoint["event_chain_sha256"]
    posts, fetch_meta = collect_since(
        source_url=source_url,
        channel=channel,
        last_post_id=last_post_id,
        max_pages=max_pages,
        fetcher=fetcher,
    )
    new_rows = [build_event(post, collected_at) for post in posts]
    event_delta_raw = encode_ndjson(new_rows)
    event_delta_sha = sha256_bytes(event_delta_raw)

    if fetch_meta["gap_unresolved"]:
        new_last_post_id = last_post_id
        new_event_chain = previous_event_chain
        status = "BLOCKED_GAP_UNRESOLVED"
        publish_rows = []
        checkpoint_advanced = False
        event_delta_committed = False
    else:
        new_last_post_id = max([last_post_id] + [row["post_id"] for row in new_rows])
        status = "READY_DISCOVERY_ONLY" if new_rows else "UNCHANGED"
        publish_rows = new_rows
        checkpoint_advanced = new_last_post_id != last_post_id
        event_delta_committed = True
        if new_rows:
            new_event_chain = _extend_event_chain(
                previous_event_chain,
                event_delta_sha256=event_delta_sha,
                first_post_id=new_rows[0]["post_id"],
                last_post_id=new_rows[-1]["post_id"],
                event_count=len(new_rows),
            )
        else:
            new_event_chain = previous_event_chain

    checkpoint = {
        "schema_version": CHECKPOINT_SCHEMA,
        "channel": channel.lower(),
        "source_url": source_url,
        "last_post_id": new_last_post_id,
        "previous_last_post_id": last_post_id,
        "checkpoint_advanced": checkpoint_advanced,
        "collected_at": collected_at,
        "previous_checkpoint_sha256": old_checkpoint_sha,
        "previous_event_chain_sha256": previous_event_chain,
        "event_chain_sha256": new_event_chain,
        "event_delta_sha256": event_delta_sha,
        "event_delta_committed": event_delta_committed,
        "status": status,
        "gap_unresolved": bool(fetch_meta["gap_unresolved"]),
        "first_new_post_id": fetch_meta["first_new_post_id"],
        "last_new_post_id": fetch_meta["last_new_post_id"],
        "pages_fetched": fetch_meta["pages_fetched"],
    }
    checkpoint_bytes = canonical_json_bytes(checkpoint)

    leadership_events = []
    for row in publish_rows:
        if not row["a2_discovery_eligible"]:
            continue
        leadership_events.append({
            "event_id": f"telegram:{channel.lower()}:{row['post_id']}",
            "source_kind": "PUBLIC_TELEGRAM_CHANNEL",
            "source_url": row["source_url"],
            "source_text_sha256": row["text_sha256"],
            "published_at": row["published_at"],
            "available_from": row["available_from"],
            "collected_at": row["collected_at"],
            "relevance_categories": row["relevance_categories"],
            "tickers_detected": row["tickers_detected"],
            "claim_text": row["text"],
            "impact_direction": "UNKNOWN",
            "verification_status": row["verification_status"],
            "score_contribution": 0.0,
            "discovery_only": True,
            "requires_independent_verification": True,
            "a3_er_eligible": False,
            "selector_eligible": False,
            "target_authority": False,
            "order_authority": False,
        })
    a2 = {
        "schema_version": A2_SCHEMA,
        "generated_at": collected_at,
        "channel": channel.lower(),
        "source_url": source_url,
        "status": status,
        "research_only": True,
        "input_role": "discovery_inputs",
        "intended_agent": "A2",
        "source_trust": "SECONDARY_UNVERIFIED",
        "score_contribution": 0.0,
        "verification_policy": "Telegram claims trigger discovery only. Independent primary/authoritative corroboration is required before any score, ER, selector, target or order use.",
        "events": leadership_events,
    }
    a2_bytes = canonical_json_bytes(a2)
    receipt = {
        "schema_version": "telegram-insidertracking-receipt-v1",
        "generated_at": collected_at,
        "channel": channel.lower(),
        "status": status,
        "previous_checkpoint_sha256": old_checkpoint_sha,
        "checkpoint_sha256": sha256_bytes(checkpoint_bytes),
        "previous_event_chain_sha256": previous_event_chain,
        "event_chain_sha256": new_event_chain,
        "event_delta_sha256": event_delta_sha,
        "event_delta_committed": event_delta_committed,
        "a2_discovery_sha256": sha256_bytes(a2_bytes),
        "new_post_count": len(new_rows),
        "a2_event_count": len(leadership_events),
        "pages_fetched": fetch_meta["pages_fetched"],
        "page_receipts": fetch_meta["page_receipts"],
        "gap_unresolved": bool(fetch_meta["gap_unresolved"]),
        "research_only": True,
        "score_contribution": 0.0,
        "a3_er_eligible": False,
        "selector_eligible": False,
        "target_authority": False,
        "order_authority": False,
    }
    return {
        "checkpoint.json": checkpoint_bytes,
        "events.ndjson": event_delta_raw,
        "a2_discovery_inputs.json": a2_bytes,
        "receipt.json": canonical_json_bytes(receipt),
    }

