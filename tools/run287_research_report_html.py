"""Self-contained internal research report. No hosting, telemetry or account data."""
from __future__ import annotations

import base64
import hashlib
import html
import json


STYLE = """
:root{color-scheme:dark;--bg:#091321;--panel:#111e30;--line:#2c3c51;--text:#edf2fa;--muted:#acbbce;--mint:#82dec5;--amber:#f2c784}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.6 system-ui,-apple-system,sans-serif}
main{max-width:1440px;margin:auto;padding:32px}a{color:var(--mint)}h1,h2,p{margin:0}h1{font-size:30px;letter-spacing:-.7px}h2{font-size:21px}
header{display:flex;justify-content:space-between;gap:24px;align-items:center;margin-bottom:24px}.eyebrow{font-size:14px;letter-spacing:2px;color:var(--mint)}
.muted,small{color:var(--muted)}small{display:block;font-size:14px}.badge{border:1px solid var(--line);border-radius:30px;padding:6px 14px;color:var(--amber);white-space:nowrap}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}.metric,section{border:1px solid var(--line);background:var(--panel);border-radius:12px}
.metric{padding:20px}.metric strong{display:block;font-size:26px;margin:8px 0}.metric p{color:var(--muted);font-size:14px}
section{margin-top:20px;padding:24px}.section-title{display:flex;justify-content:space-between;align-items:baseline;gap:16px;margin-bottom:16px}
.notice{border-left:3px solid var(--amber);padding:4px 0 4px 16px;color:var(--muted)}.filters{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}
input,select,button{font:inherit;border:1px solid var(--line);border-radius:6px;padding:9px 12px;background:var(--bg);color:var(--text)}input{min-width:180px}button{cursor:pointer}
label{display:flex;align-items:center;gap:8px;font-size:14px}input:focus-visible,select:focus-visible,button:focus-visible,a:focus-visible{outline:2px solid var(--mint);outline-offset:3px}
.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;text-align:left}th{font-size:14px;color:var(--muted);font-weight:500;white-space:nowrap}th,td{padding:14px 12px;border-bottom:1px solid var(--line);vertical-align:top}
td{font-variant-numeric:tabular-nums}td:first-child{font-weight:650}.num{text-align:right;white-space:nowrap}.status{font-size:14px;max-width:340px;overflow-wrap:anywhere}.ok{color:var(--mint)}
.sources{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.source{border-top:1px solid var(--line);padding-top:14px;overflow-wrap:anywhere}.source strong{display:block}.source code{font-size:14px}
details{margin-top:16px}summary{cursor:pointer;color:var(--mint)}pre{overflow:auto;font-size:14px;padding:16px;background:var(--bg);border-radius:6px}li{overflow-wrap:anywhere;margin:8px 0}
footer{padding:24px 0;color:var(--muted);font-size:14px}.empty{padding:20px;color:var(--muted)}[hidden]{display:none!important}
@media(max-width:850px){main{padding:18px}.metrics{grid-template-columns:repeat(2,1fr)}header{align-items:flex-start;flex-direction:column}.sources{grid-template-columns:1fr}section{padding:18px}h1{font-size:26px}}
@media(max-width:460px){.metrics{grid-template-columns:1fr}label,input,select{width:100%}.section-title{display:block}}
"""
SCRIPT = """
const query=document.getElementById('query'),market=document.getElementById('market'),coverage=document.getElementById('coverage');
function filter(){let count=0;const q=query.value.trim().toUpperCase();document.querySelectorAll('#watchlist tbody tr').forEach(row=>{
const show=(!q||row.dataset.ticker.includes(q))&&(!market.value||row.dataset.market===market.value)&&(!coverage.value||row.dataset.coverage===coverage.value);
row.hidden=!show;if(show)count++;});document.getElementById('visible-count').textContent=count+'개 종목';document.getElementById('empty').hidden=count!==0;}
query.addEventListener('input',filter);market.addEventListener('change',filter);coverage.addEventListener('change',filter);
document.getElementById('reset').addEventListener('click',()=>{query.value='';market.value='';coverage.value='';filter();query.focus();});filter();
"""


def esc(value) -> str:
    return html.escape("—" if value is None else str(value), quote=True)


def numeric(value, digits: int = 2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}"


def render_html(report: dict) -> str:
    """Render only escaped report data; filters do not assign investment ranks."""
    rows = report["watchlist"]
    prices = sum(row["close"] is not None for row in rows)
    scores = sum(row["current_engine_score"] is not None for row in rows)
    alerts = report["alerts"]
    body = []
    for row in rows:
        available = row["current_engine_score"] is not None
        status = "계산 결과 확인 · 순위 산출 전" if available else row["current_engine_status"]
        if available and row.get("engine_corporate_action_quarantine"):
            status = "기업행동 검토 대상 · 선별 제외"
        elif available and row.get("engine_research_eligible") is not True:
            status = "계산 결과 확인 · 선별 적격 아님"
        gaps = row.get("engine_critical_missing_fields") or row["data_gap"]
        body.append(f'''<tr data-ticker="{esc(row['ticker'])}" data-market="{esc(row['market'])}" data-coverage="{'ready' if available else 'missing'}">
<td>{esc(row['ticker'])}<small>{esc(row['market'])}</small></td>
<td class="num">{numeric(row['close'])}<small>{esc(row.get('currency'))} · {esc(row['price_as_of'])}</small></td>
<td class="num">{numeric(row['current_engine_score'], 6)}<small>{esc(row.get('engine_score_as_of'))}</small></td>
<td class="num">{numeric(row['ownership_score'], 4)}<small>분기 공시 기반</small></td>
<td class="status"><span class="{'ok' if available else 'muted'}">{esc(status)}</span><small>{esc(gaps)}</small></td></tr>''')
    sources = []
    for key, source in report["sources"].items():
        run = source.get("run") or {}
        run_id = run.get("id")
        link = (f'<a href="https://github.com/{esc(report["repository"])}/actions/runs/{run_id}">실행 {run_id}</a>'
                if type(run_id) is int else "실행 정보 없음")
        sources.append(f'<div class="source"><strong>{esc(key)} · {esc(source.get("status"))}</strong>{link}'
                       f'<small>수집 시작 {esc(run.get("created_at"))}</small>'
                       f'<small>소스 커밋 <code>{esc(run.get("head_sha"))}</code></small></div>')
    digest = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'sha256-{digest}'; base-uri 'none'; form-action 'none'">
<title>R1000 연구 운용 점검 · {esc(report['expected_us_session'])}</title><style>{STYLE}</style></head>
<body><main><header><div><p class="eyebrow">R1000 · RESEARCH DESK</p><h1>오늘의 자료와 엔진 상태</h1>
<p class="muted">미국 종가 기준 {esc(report['expected_us_session'])} · 생성 {esc(report['generated_at_utc'])}</p></div>
<span class="badge">{'확인 필요' if alerts else '자료 수집 완료'} · 내부 연구용</span></header>
<p class="notice">종목별 계산 결과와 자료 상태를 확인하는 화면입니다. 투자 순위와 포트폴리오는 별도 검증 단계에 있습니다.</p>
<div class="metrics"><article class="metric"><span>검증된 당일 가격</span><strong>{prices} / {len(rows)}</strong><p>미국·한국 관심종목 전체 기준</p></article>
<article class="metric"><span>현재 엔진 점수 연결</span><strong>{scores} / {len(rows)}</strong><p>기존 점수 척도 · 가중치 재조정 없음</p></article>
<article class="metric"><span>현재 포트폴리오</span><strong>연결 대기</strong><p>인정 계좌 원장 검증 필요</p></article>
<article class="metric"><span>확인할 데이터 상태</span><strong>{len(alerts)}</strong><p>누락·기준일·실행 결과 점검</p></article></div>
<section><div class="section-title"><h2>종목별 연구 입력</h2><span id="visible-count" class="muted" aria-live="polite">{len(rows)}개 종목</span></div>
<p class="muted">13F 수급 점수는 보고 분기의 보유 공시입니다. 실시간 매수세나 검증된 추가 가점으로 해석하지 않습니다.</p>
<div class="filters"><label>종목 <input id="query" type="search" placeholder="예: ETN, 000660" autocomplete="off"></label>
<label>시장 <select id="market"><option value="">전체</option value="US">미국</option><option value="KR">한국</option></select></label>
<label>점수 연결 <select id="coverage"><option value="">전체</option><option value="ready">연결됨</option><option value="missing">연결 필요</option></select></label>
<button id="reset" type="button">필터 초기화</button></div>
<div class="table-wrap"><table id="watchlist"><thead><tr><th scope="col">종목 / 시장</th><th scope="col" class="num">종가 / 기준일</th><th scope="col" class="num">엔진 점수 / 기준일</th><th scope="col" class="num">기존 수급 점수</th><th scope="col">검증 상태 / 남은 자료</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>
<p id="empty" class="empty" hidden>선택한 조건에 맞는 종목이 없습니다.</p></section>
<section><h2>보유 비중·매매 기록·성과 연결</h2><p class="notice">인정된 계좌 원본이 연결되면 보유 비중, 거래 이력, 누적 성과를 표시합니다. 현재는 검증된 계좌 입력이 없어 CAGR·MDD와 비중을 표시할 수 없습니다.</p>
<p class="muted">과거 재현 실험과 앞으로 누적할 모의 운용 기록은 각각의 시작일·검증 상태와 함께 제공해야 합니다.</p></section>
<section><h2>수집 근거</h2><div class="sources">{''.join(sources)}</div>
<details><summary>자료별 기준일과 점수 검증 근거 보기</summary><pre>{esc(json.dumps(report['observations'],ensure_ascii=False,indent=2))}</pre></details>
<details open><summary>확인할 항목 {len(alerts)}개</summary><ul>{''.join('<li>'+esc(x)+'</li>' for x in alerts)}</ul></details></section>
<footer>보고서 코드 {esc(report.get('code_sha'))}<br>정기 실행마다 새로운 보고서가 생성됩니다. 이 파일은 생성 시점의 스냅샷이며 자동으로 새로고침되지 않습니다.</footer>
</main><script>{SCRIPT}</script></body></html>'''
