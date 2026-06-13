# Operating Target Books

Broker replay should use these operating target books when simulating the current account.
Historical research books remain available, but they may be monthly and stale.

| Portfolio | Rows | History max | Output max | Latest target source | Latest close | Operating signal | Appended | Current |
| --- | ---: | --- | --- | --- | --- | --- | ---: | ---: |
| main | 2333 | 2026-03-31 | 2026-06-12 |  | 2026-06-12 | 2026-06-12 | true | true |
| concentrated | 23212 | 2026-03-31 | 2026-06-12 | 2026-06-12 | 2026-06-12 | 2026-06-12 | true | true |

A latest operating signal can be dated to the latest available close and filled by broker replay at the next available close.
