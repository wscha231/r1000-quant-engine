# Run287 PIT estimate/guidance 50-security/200-event P1 결과 — 2026-07-15

## 결론

GPT Pro가 P0 selector provenance 다음 단계로 지정한 P1 계약과 fail-closed 검증기를 구현했다.

현재 무료 로컬 자료의 실제 판정은 `BLOCKED_PIT_SAMPLE_CONTRACT_LOCAL_FORWARD_ONLY`다. 이는 검증기 실패가 아니라 올바른 차단이다. 기존 artifact는 863종목을 조회한 한 날짜의 forward snapshot이며, 실제 forward estimate가 있는 종목은 13개뿐이다. `available_from`도 원 관측·배포 시각이 아니라 fetch date다. 이 13개를 역사 revision event로 소급하거나 SEC Companyfacts 실제값을 애널리스트 estimate로 바꾸지 않았다.

이번 단계에서 CAGR/MDD, 종목, 비중, 현금, 주문은 변하지 않았다.

## 동결한 P1 계약

| 항목 | 통과 기준 |
|---|---:|
| 고유 security | 정확히 50 |
| active US | 정확히 20 |
| delisted | 정확히 10 |
| ADR/home | 정확히 10 |
| predecessor/corporate action | 정확히 10 |
| historical estimate/guidance events | 200 이상 |
| 동일 fiscal period revision pair 보유 security | 40 이상 |
| explicit company guidance events | 15 이상 |
| stable issuer/security/listing identity | 50/50 |
| delisted verified outcome | 10/10 |
| ADR/home bridge | 10/10 |
| predecessor continuity | 10/10 |
| exact timestamp + timezone | 100% |
| future row | 0 |
| hash-seeded as-of reproduction | 10/10 |
| 보존·내부재현·파생결과 유지 권리 | 전부 명시·허용 |
| 샘플 비용 | USD 300 이하; 검증기가 구매를 승인하지는 않음 |

`ticker`는 primary key로 사용하지 않는다. issuer, security, listing을 분리하며 ADR과 home listing의 가격이력을 합치지 않는다. revision pointer는 같은 security·event type·metric·fiscal period 안에서 더 이른 `available_from` event를 가리켜야 한다.

이 계약이 통과해도 상태는 `READY_PIT_SAMPLE_SCHEMA_GATE_ONLY`다. alpha pass, 수익률 join, portfolio arm 승격은 별도 단계다.

## 현재 무료 로컬 자료의 측정 결과

실행 경로:

`outputs/run287_pit_estimate_guidance_sample_audit_v2_20260715_local_free/`

| 게이트 | 관측 | 필요 | 판정 |
|---|---:|---:|---|
| stable provider security ID | 0 | 50 | FAIL |
| 이름이 정해진 구 요청행 | 45 | 50 | FAIL |
| qualifying historical PIT event | 0 | 200 | FAIL |
| 현재 forward estimate snapshot | 13 | 200 | 진단 전용, FAIL |
| revision-pair security | 0 | 40 | FAIL |
| explicit guidance event | 0 | 15 | FAIL |
| exact provider availability event | 0 | 200 | FAIL |
| delisted outcome | 0 | 10 | FAIL |
| ADR/home bridge | 0 | 10 | FAIL |
| predecessor continuity | 0 | 10 | FAIL |
| as-of reproduction | 0 | 10 | FAIL |
| rights manifest | 0 | 1 | FAIL |

입력 hash:

- v2 contract: `7853e80d518be6c13f3964ed0dd63c1d0e46387483b1830744f0308392cd8799`
- old 50-row request: `dc44c80a31e7414fff67f33378262cedbcc0fd28289cd0eababf58cf32ac9cc6`
- local forward snapshot: `60a41161ebf851db31cdeb240c334fbcaf10bbed6bb5e1dcfe8b6b4a67961e91`
- source summary: `42e78fa89682f3763b061b47a8c770b33e0fb3f825cb101032a540ad19c34713`

## 왜 기존 무료 자료를 합치지 않았는가

- SEC accepted-time filing과 Companyfacts는 실제 기업 공시 evidence다. consensus estimate revision history가 아니다.
- 2026-07-09 estimate artifact는 append-only forward archive의 시작점으로는 유효하지만, fetch 이전의 역사 상태를 말해주지 않는다.
- FMP historical 경로의 HTTP 402와 Finnhub estimate entitlement 403은 이미 확인됐다. 같은 호출을 반복해도 PIT identity·delisted·rights가 생기지 않는다.
- Nasdaq ZACKS/EEH의 50-row probe는 entitlement가 있을 때 schema 진단만 가능하다. 50개 고유 security와 200개 event가 없으면 v2를 통과하지 못한다.

## 다음에 받을 최소 무료 패킷

이메일, 가입, 결제는 이번 작업에서 수행하지 않았다. 새로 발견하거나 기존 권한으로 내려받은 무료 sample은 다음 네 파일 그대로 검증기에 넣으면 된다.

1. `security_master.csv` — 50개 고유 security와 20/10/10/10 identity strata
2. `estimate_guidance_events.csv` — 200개 이상의 append-only long events
3. `asof_queries.csv` — frozen seed로 만든 10개 query와 expected event ID
4. `rights.json` — timestamp, revision, identity, storage, reproduction, retention, redistribution policy와 비용

실행 예:

```powershell
python tools/audit_run287_pit_estimate_guidance_sample_v2.py `
  --security-master <security_master.csv> `
  --events <estimate_guidance_events.csv> `
  --asof-queries <asof_queries.csv> `
  --rights <rights.json> `
  --output-dir outputs/run287_pit_estimate_guidance_sample_audit_v2_provider
```

현재 비용 효율적인 결정은 기존 forward archive는 $0 범위에서 계속 축적하고, 무료로 이 네 파일을 충족하는 자료가 생길 때만 v2를 한 번 실행하는 것이다. 유료 extract, return join, 역사 source screen 또는 portfolio A/B는 아직 열지 않는다.

## 구현·검증 파일

- `docs/run287_pit_estimate_guidance_sample_contract_v2.json`
- `tools/audit_run287_pit_estimate_guidance_sample_v2.py`
- `tests/run287_pit_estimate_guidance_sample_v2_smoke.py`
- `outputs/run287_pit_estimate_guidance_sample_audit_v2_20260715_local_free/manifest.json`
- `outputs/run287_pit_estimate_guidance_sample_audit_v2_20260715_local_free/local_material_gap.csv`
