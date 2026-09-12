const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'docs/public/app.js'), 'utf8')
  .replace('attachEvents();\nloadDashboard();', '');
let clock = Date.parse('2026-09-12T12:00:00Z');
class ClockDate extends Date {
  constructor(...args) { super(...(args.length ? args : [clock])); }
  static now() { return clock; }
}
const elements = new Map();
const events = new Map();
const timers = new Map();
let timerId = 0;
const window = {
  setTimeout(callback, delay) { timers.set(++timerId, { callback, at: clock + delay }); return timerId; },
  clearTimeout(id) { timers.delete(id); },
  addEventListener(name, callback) { events.set(name, callback); },
};
const document = {
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, { hidden: false, textContent: '', classList: { toggle() {} }, addEventListener() {} });
    return elements.get(selector);
  },
  querySelectorAll() { return []; },
  addEventListener(name, callback) { events.set(name, callback); },
};
const context = vm.createContext({ document, window, Date: ClockDate, Intl, console });
vm.runInContext(source, context);
const data = {
  as_of_close: '2026-09-11',
  portfolios: {
    main: { holdings: [{ ticker: 'AAA', weight: .8, target_weight: .9 }], cash_weight: .2 },
    concentrated: { holdings: [{ ticker: 'BBB', weight: .8 }], cash_weight: .2 },
  },
  order_previews: [{ ticker: 'AAA', portfolio: 'main', current_weight: .8, target_weight: .9 }],
};
const quotes = {
  schema_version: 'run287-public-market-quotes-v1', review_only: true,
  live_trading_enabled: false, portfolio_revalued: false,
  portfolio_as_of_close: '2026-09-11', expected_session_date: '2026-09-11',
  as_of_close: '2026-09-11', status: 'COMPLETE', checked_at_utc: '2026-09-12T03:00:00Z',
  freshness_valid_until_utc: '2026-09-14T20:00:00Z',
  quotes: ['AAA', 'BBB'].map(ticker => ({ ticker, close: 100, currency: 'USD', session_date: '2026-09-11' })),
};
context.input = data;
context.quoteInput = quotes;
vm.runInContext('state.data=input;state.quotes=null;renderPreviews()', context);
assert.equal(elements.get('#preview-section').hidden, true);
assert.equal(vm.runInContext('isPortfolioStale()', context), true);
assert.ok(!vm.runInContext('holdingsRow(input.portfolios.main.holdings[0], 0)', context).includes('90.00%'));
for (const status of ['PARTIAL', 'PROVIDER_UNAVAILABLE', 'UNAVAILABLE', 'WAITING_FOR_COMPLETED_CLOSE']) {
  context.quoteInput = { ...quotes, status, as_of_close: null, quotes: status === 'PARTIAL' ? quotes.quotes.slice(0, 1) : [] };
  vm.runInContext('state.quotes=validateQuotes(quoteInput,input);refreshFreshnessDisplay()', context);
  assert.notEqual(vm.runInContext('state.quotes', context), null); // valid observation, insufficient freshness proof
  assert.equal(vm.runInContext('isPortfolioStale()', context), true);
  assert.equal(elements.get('#preview-section').hidden, true);
  assert.ok(!vm.runInContext('holdingsRow(input.portfolios.main.holdings[0], 0)', context).includes('90.00%'));
}
context.quoteInput = quotes;
vm.runInContext('state.quotes=validateQuotes(quoteInput,input);refreshFreshnessDisplay();attachEvents()', context);
assert.equal(vm.runInContext('isPortfolioStale()', context), false); // weekend is calendar-aware
assert.equal(elements.get('#preview-section').hidden, false);
assert.equal(timers.size, 1);
const deadlineTimer = [...timers.values()][0];
assert.equal(deadlineTimer.at, Date.parse(quotes.freshness_valid_until_utc));
clock = Date.parse('2026-09-14T20:00:00Z');
deadlineTimer.callback(); // browser timer fires without a render call or user action
assert.equal(vm.runInContext('isPortfolioStale()', context), true); // next close invalidates old freshness
assert.equal(elements.get('#preview-section').hidden, true);
assert.ok(!vm.runInContext('holdingsRow(input.portfolios.main.holdings[0], 0)', context).includes('90.00%'));
assert.equal(timers.size, 0);
// A suspended tab also rechecks immediately on visibility/focus restoration.
for (const name of ['visibilitychange', 'focus']) {
  elements.get('#preview-section').hidden = false;
  events.get(name)();
  assert.equal(elements.get('#preview-section').hidden, true);
}
context.quoteInput = { ...quotes, freshness_valid_until_utc: 'invalid' };
assert.equal(vm.runInContext('validateQuotes(quoteInput,input)', context), null);
context.quoteInput = { ...quotes, portfolio_as_of_close: '2026-09-10' };
assert.equal(vm.runInContext('validateQuotes(quoteInput,input)', context), null);
assert.equal(vm.runInContext('price(null)', context), '—');
console.log('public_dashboard_runtime_smoke: PASS');
