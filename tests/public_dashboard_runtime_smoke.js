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
const document = {
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, { hidden: false, textContent: '', classList: { toggle() {} } });
    return elements.get(selector);
  },
  querySelectorAll() { return []; },
};
const context = vm.createContext({ document, Date: ClockDate, Intl, console });
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
vm.runInContext('state.quotes=validateQuotes(quoteInput,input);renderPreviews()', context);
assert.equal(vm.runInContext('isPortfolioStale()', context), false); // weekend is calendar-aware
assert.equal(elements.get('#preview-section').hidden, false);
clock = Date.parse('2026-09-14T20:00:00Z');
vm.runInContext('renderPreviews()', context);
assert.equal(vm.runInContext('isPortfolioStale()', context), true); // next close invalidates old freshness
assert.equal(elements.get('#preview-section').hidden, true);
assert.ok(!vm.runInContext('holdingsRow(input.portfolios.main.holdings[0], 0)', context).includes('90.00%'));
context.quoteInput = { ...quotes, freshness_valid_until_utc: 'invalid' };
assert.equal(vm.runInContext('validateQuotes(quoteInput,input)', context), null);
context.quoteInput = { ...quotes, portfolio_as_of_close: '2026-09-10' };
assert.equal(vm.runInContext('validateQuotes(quoteInput,input)', context), null);
assert.equal(vm.runInContext('price(null)', context), '—');
console.log('public_dashboard_runtime_smoke: PASS');
