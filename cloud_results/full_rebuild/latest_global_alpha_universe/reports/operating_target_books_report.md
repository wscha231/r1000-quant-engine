# Operating Target Books

Broker replay should use these operating target books when simulating the current account.
Historical research books remain available, but they may be monthly and stale.

| Portfolio | Rows | History max | Output max | Latest target source | Latest close | Operating signal | Appended | Current |
| --- | ---: | --- | --- | --- | --- | --- | ---: | ---: |
| main | 2197 | 2026-02-27 | 2026-05-13 |  | 2026-05-13 | 2026-05-13 | true | true |
| concentrated | 23382 | 2026-02-27 | 2026-05-13 | 2026-05-14 | 2026-05-13 | 2026-05-13 | true | true |

A latest operating signal can be dated to the latest available close and filled by broker replay at the next available close.
