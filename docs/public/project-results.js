/* Public research observations. Does not write portfolio state or issue orders. */
(() => {
  const labels = {
    VERIFIED_ARTIFACT: '출처 파일 검증됨', UPSTREAM_FAILED: '최근 처리 실패',
    UPSTREAM_IN_PROGRESS: '처리 중', MISSING_RUN: '운영 결과 대기',
    MISSING_ARTIFACT: '결과 파일 없음', MISSING_CONTRACT_MEMBERS: '필수 자료 누락',
    BLOCKED_SOURCE: '자료 확인 필요', WORKFLOW_SUCCESS_DATA_UNVERIFIED: '처리 완료 · 데이터 검증 별도'
  };
  const esc = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('ko-KR', {maximumFractionDigits: 4}) : '—';
  let packet = null;
  let quotes = null;
  function quotesCurrent() {
    return quotes?.status === 'COMPLETE' && quotes?.expected_session_date === packet?.expected_us_session &&
      Date.parse(quotes?.freshness_valid_until_utc) > Date.now();
  }
  function scoresCurrent() {
    const s = packet?.research_scores;
    const source = packet?.sources.find(row => row?.key === 'operating');
    const hex = (value, size) => typeof value === 'string' && new RegExp(`^[a-f0-9]{${size}}$`).test(value);
    const stamp = value => typeof value === 'string' && /(Z|[+-]\d{2}:\d{2})$/.test(value) ? Date.parse(value) : NaN;
    if (s?.status !== 'VERIFIED_CURRENT_NONRANKING_SCORES' || s.ready !== true ||
        s.ranking_allowed !== false || s.predictive_value_validated !== false ||
        s.score_as_of !== packet.expected_us_session ||
        !Number.isSafeInteger(s.verified_ticker_count) || s.verified_ticker_count < 2 ||
        !Number.isSafeInteger(s.source_run_id) || s.source_run_id <= 0 ||
        !Number.isSafeInteger(s.source_artifact_id) || s.source_artifact_id <= 0 ||
        !hex(s.engine_code_sha, 40) || !hex(s.model_anchor_sha256, 64) || !hex(s.model_meta_sha256, 64) ||
        source?.status !== 'VERIFIED_ARTIFACT' || source.artifact_verified !== true ||
        source.commit !== s.engine_code_sha || !hex(s.source_artifact_sha256, 64) ||
        source.artifact_sha256 !== s.source_artifact_sha256 ||
        source.run_id !== s.source_run_id || source.artifact_id !== s.source_artifact_id) return false;
    const available = stamp(s.feature_available_from), decision = stamp(s.decision_time_utc),
      executed = stamp(s.executed_at_utc), checked = stamp(s.checked_at_utc),
      close = stamp(s.session_close_utc), deadline = stamp(s.freshness_valid_until_utc);
    return available <= decision && close <= decision && decision <= executed && executed <= checked &&
      checked === stamp(packet.generated_at) && checked <= Date.now() && Date.now() < deadline &&
      s.session_close_utc.slice(0, 10) === s.score_as_of;
  }
  function render() {
    const message = document.getElementById('project-results-status');
    if (!packet) {
      message.textContent = '연구 결과를 불러올 수 없습니다. 다음 갱신 때 다시 확인합니다.';
      document.getElementById('project-source-cards').replaceChildren();
      document.getElementById('research-results-body').replaceChildren();
      document.getElementById('project-diagnostics').replaceChildren();
      return;
    }
    const scoreFresh = scoresCurrent(), priceFresh = quotesCurrent();
    message.textContent = `검사 대상 종가 ${packet.expected_us_session} · 결과 수집 ${packet.generated_at.slice(0,16).replace('T',' ')} UTC${scoreFresh ? ' · 현재 연구 점수' : ' · 연구 점수 최신성 확인 필요'}${priceFresh ? '' : ' · 공개 시세 확인 필요'}`;
    document.getElementById('project-source-cards').innerHTML = packet.sources.map(source => {
      const link = Number.isSafeInteger(source.run_id) && source.run_id > 0
        ? `<a href="https://github.com/wscha231/r1000-quant-engine/actions/runs/${source.run_id}" target="_blank" rel="noopener noreferrer">처리 내역 보기 ↗</a>` : '';
      return `<article class="project-source"><strong>${esc(source.label)}</strong><p>${esc(labels[source.status] || '자료 확인 필요')}</p>${link}</article>`;
    }).join('');
    const query = document.getElementById('research-results-search').value.trim().toUpperCase();
    document.getElementById('research-results-body').innerHTML = packet.rows.filter(row => row.ticker.includes(query)).map(row => {
      const score = scoreFresh && row.market === 'US' && row.score_as_of === packet.expected_us_session ? row.engine_score : null;
      const status = row.market === 'KR' ? '한국 데이터 연결 대기' : score === null ? '검증된 현재 점수 없음' : row.quarantined ? '기업행동 검토 · 선별 제외' : row.eligible ? '연구 점수 · 투자 순위 산출 전' : '연구 점수 · 선별 적격 아님';
      return `<tr><td>${esc(row.ticker)} <small>${esc(row.market)}</small></td><td class="number">${number(priceFresh ? row.close : null)}<small>${esc(row.price_as_of)}</small></td><td class="number">${number(score)}<small>${esc(row.score_as_of)}</small></td><td>${status}</td></tr>`;
    }).join('') || '<tr><td colspan="4">검색 결과가 없습니다.</td></tr>';
    const d = packet.diagnostics;
    document.getElementById('project-diagnostics').textContent =
      `테마 분석: 가격 기준 ${d.theme.data_as_of || '미확인'}, 평가 ${d.theme.scored_count ?? '—'}종목 / 유동성 통과 ${d.theme.liquid_count ?? '—'}종목. ` +
      `거시 자료: 수집일 ${d.macro.collection_date || '미확인'}, 개별 관측일 검증 필요. ` +
      `ETF 자료: 수집일 ${d.etfs.collection_date || '미확인'}, 유효 종가 ${d.etfs.finite_close_count}/${d.etfs.total}개, 개별 관측일 검증 필요. ` +
      (scoreFresh ? `점수 엔진 ${packet.research_scores.engine_code_sha.slice(0,8)} · 모형 ${packet.research_scores.model_anchor_sha256.slice(0,8)}. 예측력·포트폴리오 성과 검증 전.` : '검증된 현재 점수 모형 대기.');
  }
  async function refresh() {
    try {
      const responses = await Promise.all(['project-results.json','market-quotes.json','dashboard.json'].map(async name => {
        try { const response = await fetch(`./data/${name}?v=${Date.now()}`, {cache:'no-store'}); return response.ok ? await response.json() : null; }
        catch { return null; }
      }));
      const data = responses[0];
      if (data?.schema_version !== 'run287-public-project-results-v1' || data.review_only !== true || data.live_trading_enabled !== false || data.ranking_ready !== false || !Array.isArray(data.rows) || !Array.isArray(data.sources) || typeof data.generated_at !== 'string') throw new Error('invalid public research');
      packet = data;
      const dashboard = responses[2];
      quotes = null;
      if (dashboard?.schema_version === 'run287-public-dashboard-v1' &&
          dashboard.status?.review_only === true && dashboard.status?.live_trading_enabled === false) {
        try { quotes = validateQuotes(responses[1], dashboard); } catch { quotes = null; }
      }
    } catch { packet = null; quotes = null; }
    render();
  }
  document.getElementById('research-results-search').addEventListener('input', render);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  window.addEventListener('focus', refresh);
  window.setInterval(refresh, 300000);
  // Expiry also applies while an open tab is not fetching new data.
  window.setInterval(render, 30000);
  refresh();
})();
