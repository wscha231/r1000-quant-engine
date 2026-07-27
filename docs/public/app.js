const state = {
  data: null,
  portfolio: "main",
  holdingsSearch: "",
  tradeSearch: "",
  tradeSide: "all",
  tradeLimit: 80,
  lastLedgerTrigger: null,
};

const COLORS = {
  main: "#54e1ad",
  concentrated: "#6ea8ff",
  cash: "#5a6d86",
};

const allocationColors = [
  "#54e1ad", "#6ea8ff", "#b68cff", "#ffcc73", "#59c4da",
  "#f58eae", "#72d887", "#8f9cff", "#de9c5d", "#75b7a7",
  "#c7e06f", "#ee7c65", "#8bd3ff", "#d69fea", "#a5b689", "#eebc8b",
];

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function valueOrDash(value) {
  return value === null || value === undefined || value === "" ? "—" : value;
}

function percent(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(digits)}%` : "—";
}

function signedPercent(value, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const sign = number > 0 ? "+" : "";
  return `${sign}${(number * 100).toFixed(digits)}%p`;
}

function price(value) {
  const number = Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(number)
    : "—";
}

function number(value, digits = 2) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : "—";
}

function formatDate(value) {
  if (!value) return "—";
  const [year, month, day] = String(value).slice(0, 10).split("-");
  return year && month && day ? `${year}.${month}.${day}` : String(value);
}

function formatTimestamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date) + " KST";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function portfolioData(portfolio = state.portfolio) {
  return state.data?.portfolios?.[portfolio] || { holdings: [], trades: [], metrics: {} };
}

function metricCard(portfolio, item) {
  const metrics = item.metrics || {};
  return `
    <article class="metric-card" data-portfolio="${portfolio}">
      <div class="metric-card-head">
        <span class="portfolio-name">${escapeHtml(item.label || portfolio)}</span>
        <span class="portfolio-count">${item.holding_count ?? item.holdings?.length ?? 0} holdings</span>
      </div>
      <div class="metric-main">
        <div><span>CAGR</span><strong class="positive">${percent(metrics.cagr)}</strong></div>
        <div><span>${metrics.max_drawdown_exact === false ? "MAX DRAWDOWN (BOUND)" : "MAX DRAWDOWN"}</span><strong class="drawdown">${percent(metrics.max_drawdown)}</strong></div>
        <div><span>LATEST CASH</span><strong>${percent(item.cash_weight)}</strong></div>
      </div>
      <dl class="metric-minor">
        <div><dt>Sharpe</dt><dd>${number(metrics.sharpe)}</dd></div>
        <div><dt>평균 현금</dt><dd>${percent(metrics.average_cash_weight)}</dd></div>
        <div><dt>OOS CAGR</dt><dd>${percent(metrics.oos_cagr)}</dd></div>
        <div><dt>거래 수</dt><dd>${Number(metrics.trade_count || 0).toLocaleString("en-US")}</dd></div>
      </dl>
    </article>`;
}

function renderHeader() {
  const data = state.data;
  $("#as-of-close").textContent = formatDate(data.as_of_close);
  $("#generated-at").textContent = formatTimestamp(data.generated_at_utc);
  $("#source-label").textContent = valueOrDash(data.source?.label);
  $("#decision-label").textContent = valueOrDash(data.status?.promotion_state || data.status?.decision);
  $("#header-status-text").textContent = `${formatDate(data.as_of_close)} 종가 반영`;
  $("#allocation-asof").textContent = formatDate(data.as_of_close);
}

function renderMetricCards() {
  const html = ["main", "concentrated"]
    .filter((portfolio) => state.data.portfolios?.[portfolio])
    .map((portfolio) => metricCard(portfolio, state.data.portfolios[portfolio]))
    .join("");
  $("#metric-grid").innerHTML = html;
}

function allocationItems(portfolio) {
  const item = portfolioData(portfolio);
  const holdings = (item.holdings || []).map((holding, index) => ({
    ticker: holding.ticker,
    weight: Number(holding.weight || 0),
    color: allocationColors[index % allocationColors.length],
  }));
  holdings.push({ ticker: "CASH", weight: Number(item.cash_weight || 0), color: COLORS.cash });
  return holdings.filter((holding) => holding.weight > 0);
}

function donutGradient(items) {
  const total = items.reduce((sum, item) => sum + item.weight, 0) || 1;
  let cursor = 0;
  const segments = items.map((item) => {
    const start = cursor;
    cursor += item.weight / total * 100;
    return `${item.color} ${start.toFixed(4)}% ${cursor.toFixed(4)}%`;
  });
  return `conic-gradient(from -90deg, ${segments.join(", ")})`;
}

function renderAllocationDonuts() {
  $("#allocation-donuts").innerHTML = ["main", "concentrated"]
    .filter((portfolio) => state.data.portfolios?.[portfolio])
    .map((portfolio) => {
      const data = portfolioData(portfolio);
      const items = allocationItems(portfolio);
      const tradeCount = (data.trades || []).length;
      const legend = items.map((item) => `
        <li>
          <span class="donut-legend-name"><span class="donut-swatch" style="background:${item.color}"></span>${escapeHtml(item.ticker)}</span>
          <strong>${percent(item.weight)}</strong>
        </li>`).join("");
      return `
        <article class="donut-card" data-portfolio="${portfolio}">
          <div class="donut-card-head">
            <div>
              <span class="donut-portfolio-label">${escapeHtml(data.label || portfolio)}</span>
              <small>${data.holding_count ?? data.holdings?.length ?? 0}종목 + 현금</small>
            </div>
            <span class="donut-cash-chip">현금 ${percent(data.cash_weight)}</span>
          </div>
          <div class="donut-card-body">
            <div class="donut-chart" style="background:${donutGradient(items)}" role="img" aria-label="${escapeHtml(data.label || portfolio)} 종목별 보유 비중 원형 차트">
              <div class="donut-center">
                <strong>${percent(1 - Number(data.cash_weight || 0), 1)}</strong>
                <span>주식 비중</span>
              </div>
            </div>
            <ol class="donut-legend" aria-label="${escapeHtml(data.label || portfolio)} 종목별 비중">${legend}</ol>
          </div>
          <button class="ledger-open" type="button" data-ledger-portfolio="${portfolio}" aria-controls="trade-section" aria-expanded="false">
            <span>${escapeHtml(data.label || portfolio)} 백테스트 매수·매도 기록</span>
            <strong>${tradeCount.toLocaleString("en-US")}건 보기 →</strong>
          </button>
        </article>`;
    }).join("");
}

function chartPoints(curve, minValue, maxValue, width, height, padding) {
  if (!curve.length) return "";
  const spread = Math.max(maxValue - minValue, 1);
  return curve.map((point, index) => {
    const x = padding.left + (index / Math.max(curve.length - 1, 1)) * (width - padding.left - padding.right);
    const y = padding.top + (1 - (point.index - minValue) / spread) * (height - padding.top - padding.bottom);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
}

function renderChart() {
  const svg = $("#equity-chart");
  const series = ["main", "concentrated"]
    .map((portfolio) => ({ portfolio, curve: portfolioData(portfolio).equity_curve || [] }))
    .filter((item) => item.curve.length > 1);

  if (!series.length) {
    svg.hidden = true;
    $("#chart-empty").hidden = false;
    $("#chart-legend").innerHTML = "";
    return;
  }

  svg.hidden = false;
  $("#chart-empty").hidden = true;
  const width = 1000;
  const height = 340;
  const padding = { top: 18, right: 16, bottom: 38, left: 62 };
  const values = series.flatMap((item) => item.curve.map((point) => Number(point.index))).filter(Number.isFinite);
  const minRaw = Math.min(...values);
  const maxRaw = Math.max(...values);
  const minValue = Math.floor(Math.min(100, minRaw) / 100) * 100;
  const maxValue = Math.ceil(maxRaw / 100) * 100;
  const tickCount = 4;
  const parts = [];

  for (let index = 0; index <= tickCount; index += 1) {
    const y = padding.top + index / tickCount * (height - padding.top - padding.bottom);
    const label = maxValue - index / tickCount * (maxValue - minValue);
    parts.push(`<line class="chart-grid" x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}"></line>`);
    parts.push(`<text class="chart-label" x="${padding.left - 12}" y="${y + 7}" text-anchor="end">${Math.round(label)}</text>`);
  }

  const longest = series.reduce((current, item) => item.curve.length > current.curve.length ? item : current, series[0]);
  const xLabels = [0, Math.floor((longest.curve.length - 1) / 2), longest.curve.length - 1];
  xLabels.forEach((curveIndex, labelIndex) => {
    const x = padding.left + labelIndex / 2 * (width - padding.left - padding.right);
    parts.push(`<text class="chart-label" x="${x}" y="${height - 7}" text-anchor="${labelIndex === 0 ? "start" : labelIndex === 2 ? "end" : "middle"}">${escapeHtml(formatDate(longest.curve[curveIndex]?.date))}</text>`);
  });

  series.forEach(({ portfolio, curve }) => {
    const points = chartPoints(curve, minValue, maxValue, width, height, padding);
    const first = points.split(" ")[0];
    const last = points.split(" ").at(-1);
    const area = `${first.split(",")[0]},${height - padding.bottom} ${points} ${last.split(",")[0]},${height - padding.bottom}`;
    parts.push(`<polygon class="chart-area" points="${area}" fill="${COLORS[portfolio]}"></polygon>`);
    parts.push(`<polyline class="chart-line" points="${points}" stroke="${COLORS[portfolio]}"></polyline>`);
  });

  svg.innerHTML = parts.join("");
  $("#chart-legend").innerHTML = series.map(({ portfolio }) => `
    <span class="legend-item"><span class="legend-swatch" style="background:${COLORS[portfolio]}"></span>${escapeHtml(portfolioData(portfolio).label || portfolio)}</span>
  `).join("");
}

function renderAllocationStrip(holdings, cashWeight) {
  const all = [...holdings.map((item, index) => ({ ...item, color: allocationColors[index % allocationColors.length] })), {
    ticker: "CASH",
    weight: Number(cashWeight || 0),
    color: COLORS.cash,
  }].filter((item) => Number(item.weight) > 0);
  $("#allocation-strip").innerHTML = all.map((item) => `
    <span class="allocation-segment" style="width:${Math.max(Number(item.weight) * 100, 0)}%;background:${item.color}" title="${escapeHtml(item.ticker)} ${percent(item.weight)}"></span>
  `).join("");
}

function holdingsRow(item, rank) {
  const delta = Number(item.target_weight) - Number(item.weight);
  const hasTarget = item.target_weight !== null && item.target_weight !== undefined && Number.isFinite(Number(item.target_weight));
  const deltaClass = !hasTarget ? "" : delta > 0 ? "weight-delta-positive" : delta < 0 ? "weight-delta-negative" : "";
  return `
    <tr>
      <td class="rank-cell">${String(rank).padStart(2, "0")}</td>
      <td class="ticker-cell">${escapeHtml(item.ticker)}</td>
      <td class="number">${price(item.price)}</td>
      <td class="number">${percent(item.weight)}</td>
      <td class="number">${hasTarget ? percent(item.target_weight) : "—"}</td>
      <td class="number ${deltaClass}">${hasTarget ? signedPercent(delta) : "—"}</td>
    </tr>`;
}

function renderHoldings() {
  const portfolio = portfolioData();
  const query = state.holdingsSearch.trim().toUpperCase();
  const holdings = (portfolio.holdings || []).filter((item) => !query || item.ticker.includes(query));
  const body = holdings.map(holdingsRow).join("");
  const cashTarget = Number(portfolio.target_cash_weight);
  const cashDelta = cashTarget - Number(portfolio.cash_weight);
  const cashTargetValid = portfolio.target_cash_weight !== null && portfolio.target_cash_weight !== undefined && Number.isFinite(cashTarget);
  const cashRow = query && !"CASH".includes(query) ? "" : `
    <tr class="cash-row">
      <td class="rank-cell">—</td>
      <td class="ticker-cell">CASH</td>
      <td class="number">—</td>
      <td class="number">${percent(portfolio.cash_weight)}</td>
      <td class="number">${cashTargetValid ? percent(cashTarget) : "—"}</td>
      <td class="number">${cashTargetValid ? signedPercent(cashDelta) : "—"}</td>
    </tr>`;
  $("#holdings-body").innerHTML = body + cashRow || `<tr><td colspan="6" class="empty-state">검색 결과가 없습니다.</td></tr>`;
  $("#holdings-footer").textContent = `${portfolio.label || state.portfolio} · 주식 ${portfolio.holding_count ?? holdings.length}종목 · 현금 ${percent(portfolio.cash_weight)}`;
  renderAllocationStrip(portfolio.holdings || [], portfolio.cash_weight);
}

function previewActionLabel(action) {
  const normalized = String(action || "REVIEW_REQUIRED").toUpperCase();
  if (normalized.includes("BUY") || normalized.includes("ADD")) return "매수 검토";
  if (normalized.includes("SELL") || normalized.includes("EXIT") || normalized.includes("TRIM")) return "매도 검토";
  if (normalized.includes("HOLD")) return "유지 검토";
  return "검토 필요";
}

function renderPreviews() {
  const previews = state.data.order_previews || [];
  $("#preview-section").hidden = previews.length === 0;
  if (!previews.length) return;
  $("#preview-body").innerHTML = previews.slice(0, 60).map((item) => {
    const delta = Number(item.delta_weight);
    const deltaClass = delta > 0 ? "weight-delta-positive" : delta < 0 ? "weight-delta-negative" : "";
    return `
      <tr>
        <td>${escapeHtml(portfolioData(item.portfolio).label || item.portfolio)}</td>
        <td class="ticker-cell">${escapeHtml(item.ticker)}</td>
        <td><span class="action-badge">${previewActionLabel(item.action)}</span></td>
        <td class="number">${percent(item.current_weight)}</td>
        <td class="number">${percent(item.target_weight)}</td>
        <td class="number ${deltaClass}">${signedPercent(item.delta_weight)}</td>
      </tr>`;
  }).join("");
}

function reasonLabel(reason) {
  const labels = {
    target_rebalance: "목표 비중 리밸런스",
    liquidation: "편출/청산",
    cash_rebalance: "현금 비중 조정",
  };
  return labels[reason] || String(reason || "—").replaceAll("_", " ");
}

function renderTrades() {
  const portfolio = portfolioData();
  const query = state.tradeSearch.trim().toUpperCase();
  const trades = (portfolio.trades || []).filter((item) => {
    const sideMatch = state.tradeSide === "all" || item.side === state.tradeSide;
    const tickerMatch = !query || item.ticker.includes(query);
    return sideMatch && tickerMatch;
  });
  const visible = trades.slice(0, state.tradeLimit);
  $("#trades-body").innerHTML = visible.length ? visible.map((item) => `
    <tr>
      <td>${formatDate(item.date)}</td>
      <td>${formatDate(item.signal_date)}</td>
      <td><span class="record-badge ${
        item.record_type === "FORWARD_PAPER"
          ? "record-forward"
          : item.record_type === "FORWARD_PAPER_REPLAY"
            ? "record-replay"
            : "record-backtest"
      }">${
        item.record_type === "FORWARD_PAPER"
          ? "Forward 모의"
          : item.record_type === "FORWARD_PAPER_REPLAY"
            ? "Catch-up replay"
            : "Backtest"
      }</span></td>
      <td><span class="side-badge ${item.side === "BUY" ? "side-buy" : "side-sell"}">${item.side === "BUY" ? "매수" : "매도"}</span></td>
      <td class="ticker-cell">${escapeHtml(item.ticker)}</td>
      <td class="number">${price(item.fill_price)}</td>
      <td class="number">${percent(item.target_weight)}</td>
      <td>${escapeHtml(reasonLabel(item.reason))}</td>
    </tr>`).join("") : `<tr><td colspan="8" class="empty-state">조건에 맞는 매매 기록이 없습니다.</td></tr>`;
  const buyCount = trades.filter((item) => item.side === "BUY").length;
  const sellCount = trades.filter((item) => item.side === "SELL").length;
  $("#trades-footer").textContent = `${portfolio.label || state.portfolio} · ${visible.length}/${trades.length}건 · 매수 ${buyCount} · 매도 ${sellCount}`;
  $("#load-more-trades").hidden = visible.length >= trades.length;
  const historyStatus = state.data.source?.trade_history_status;
  $("#trade-history-status").textContent = historyStatus === "retained_from_last_validated_replay"
    ? "일일 artifact에는 체결 원장이 없어 마지막 검증 replay 이력을 유지합니다. 변경안은 위 표에서 별도로 표시합니다."
    : historyStatus === "validated_replay_plus_forward_paper_fills"
      ? "검증 백테스트와 다음 거래일 종가로 확정된 Forward 모의 체결입니다. 실제 주문이 아니며 수량과 계좌 금액은 공개하지 않습니다."
      : "검증된 모의 브로커 원장의 최근 체결입니다. 수량과 계좌 금액은 공개하지 않습니다.";
}

function renderChanges() {
  const changes = state.data.changes || [];
  $("#changes-list").innerHTML = changes.length ? changes.map((item) => `
    <li>
      <span class="change-meta">${formatDate(item.date)}<span class="change-commit">${escapeHtml(item.commit)}</span></span>
      <span class="change-summary">${escapeHtml(item.summary)}</span>
    </li>`).join("") : `<li><span class="change-summary">공개 가능한 변경 기록이 아직 없습니다.</span></li>`;
}

function renderAll() {
  renderHeader();
  renderMetricCards();
  renderAllocationDonuts();
  renderChart();
  renderHoldings();
  renderPreviews();
  renderTrades();
  renderChanges();
}

function setActivePortfolio(portfolio) {
  if (!state.data?.portfolios?.[portfolio]) return;
  state.portfolio = portfolio;
  state.tradeLimit = 80;
  $$(".portfolio-tab").forEach((item) => item.classList.toggle("active", item.dataset.portfolio === portfolio));
  $$(".trade-portfolio-tab").forEach((item) => item.classList.toggle("active", item.dataset.tradePortfolio === portfolio));
  renderHoldings();
  renderTrades();
}

function openTradeLedger(portfolio, trigger) {
  setActivePortfolio(portfolio);
  const section = $("#trade-section");
  section.hidden = false;
  state.lastLedgerTrigger = trigger || null;
  $$(".ledger-open").forEach((button) => button.setAttribute("aria-expanded", String(button === trigger)));
  section.scrollIntoView({ behavior: "smooth", block: "start" });
  window.setTimeout(() => $("#trades-title").focus({ preventScroll: true }), 350);
}

function closeTradeLedger() {
  $("#trade-section").hidden = true;
  $$(".ledger-open").forEach((button) => button.setAttribute("aria-expanded", "false"));
  if (state.lastLedgerTrigger) state.lastLedgerTrigger.focus({ preventScroll: false });
}

function attachEvents() {
  $$(".portfolio-tab").forEach((button) => button.addEventListener("click", () => {
    setActivePortfolio(button.dataset.portfolio);
  }));
  $$(".trade-portfolio-tab").forEach((button) => button.addEventListener("click", () => {
    setActivePortfolio(button.dataset.tradePortfolio);
  }));
  $("#allocation-donuts").addEventListener("click", (event) => {
    const button = event.target.closest("[data-ledger-portfolio]");
    if (button) openTradeLedger(button.dataset.ledgerPortfolio, button);
  });
  $("#holdings-search").addEventListener("input", (event) => {
    state.holdingsSearch = event.target.value;
    renderHoldings();
  });
  $("#trade-search").addEventListener("input", (event) => {
    state.tradeSearch = event.target.value;
    state.tradeLimit = 80;
    renderTrades();
  });
  $("#trade-side").addEventListener("change", (event) => {
    state.tradeSide = event.target.value;
    state.tradeLimit = 80;
    renderTrades();
  });
  $("#load-more-trades").addEventListener("click", () => {
    state.tradeLimit += 80;
    renderTrades();
  });
  $("#close-trade-ledger").addEventListener("click", closeTradeLedger);
}

async function loadDashboard() {
  try {
    const response = await fetch(`./data/dashboard.json?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`dashboard request failed: ${response.status}`);
    const data = await response.json();
    if (data.schema_version !== "run287-public-dashboard-v1") throw new Error("unexpected dashboard schema");
    if (data.status?.live_trading_enabled !== false || data.status?.review_only !== true) {
      throw new Error("public safety contract is not fail-closed");
    }
    state.data = data;
    renderAll();
  } catch (error) {
    console.error(error);
    $("#load-error").hidden = false;
    $("#header-status-text").textContent = "데이터 확인 필요";
  }
}

attachEvents();
loadDashboard();
