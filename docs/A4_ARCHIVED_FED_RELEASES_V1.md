# Offline archived Federal Reserve releases

`tools/a4_archived_fed_releases.py` reads supplied original H.8/H.4.1 HTML.
It makes no network, transport, Source-writer, scheduler, catalog, model or
portfolio calls. Callers supply an independently verified original SHA256,
capture reference and official release-date index. Matching those caller pins
does not authenticate the caller or grant Source/PIT/learning admission.

H.8 returns20 native weekly series: deposits, loans, C&I loans, cash and assets
for all, domestic, large and small banks. Its four Wednesday observations stay
distinct from monthly figures, percentage-growth tables and NSA tables. Table
captions determine scope; a single current-table adjustment/unit declaration is
required. Bounded between-table context is retained in full so an arbitrary
text-tail cutoff cannot hide a contradictory declaration. Large plus small is
compared with domestic banks under the three rounded0.1-billion operands'
0.15-billion tolerance. These levels are not identified inter-market flows.

H.4.1 keeps three weekly averages and their Wednesday levels separate, plus
consolidated Wednesday total assets. H.4.1 RRP-other is not silently replaced
by New York Fed overnight RRP. Both legacy preformatted text and later HTML
require weekly, Wednesday and consolidated-header dates to agree. Average,
Wednesday, eliminations and current amount-unit meanings are checked. Duplicate
RRP children, restarted unfinished blocks and pending parents refuse parsing.
H.4.1 is millions of USD; H.8 is billions of USD. No fixed reserve threshold
classifies risk.

Seasonal and monetary-unit declarations are parsed independently, including
conflicts expressed in different amount units. Legacy preformatted columns use
bounded splitting and token checks rather than a backtracking row expression;
malformed padded rows cannot consume an unbounded replay interval.

Each row retains original URL/hash, release/vintage date, observation date,
scope, SA basis, unit, balance basis and locator. Structural definitions and
footnotes remain recoverable in the original, with its hash referenced by the
row; no reclassification or break adjustment is asserted. Original archived
publication timing is not inferred from the observation date. The next civil
day05:00UTC is an explicitly labelled conservative research assumption, not an
observed first-publication timestamp. Published-at stays null and all admission
flags remain false. These new `frb-archive:` rows do not relabel existing `frb:`
revised SDMX captures as historical vintages or enter the native learner.

Limits are2MiB original bytes,64 tables,100,000 elements,30,000 cells and64
characters per numeric token. Parsing executes no HTML or scripts. The caller
must reuse the existing approved archive/transport, original hash validation,
rights and Source/learning-policy paths before any real consumer integration.
Board-produced statistical material uses its public-domain notice; marked
third-party material and unrelated supplier rights remain separate.

The isolated private pilot retained eight actual documents across four years.
Its348 normalized observations are not continuous history or training inputs.
Initial failures and superseded parsers remain immutable. Later offline fixes
reuse the same originals and preserve their request-start capture-clock precision;
they do not manufacture response-completion or first-publication clocks.
