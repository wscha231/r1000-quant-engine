# ETF116 private Actions Sheet probe H2

RESEARCH_ONLY. Separate stacked Draft above frozen PR645; no source admission.
The existing gdrive_smoke_test.yml keeps its default drive_marker path.
Explicit etf116_private_sheet_probe mode reuses twelve_private_capture.OwnerDrive
and the repository RCLONE_CONFIG_GDRIVE OAuth credential preferred by the
existing free-data workflow. No Source collector is called or edited.

Only the fixed private copy is reachable; target IDs have no override. Actual
Actions manual event/repository/run/attempt and an explicitly supplied exact
code SHA are required. The fixed parent, owner-only permissions, canEdit, Sheet
MIME and existing sentinel tab ID are checked. Each run/attempt derives its own
ETF116_ACTIONS_PROBE_<run_id>_<attempt> tab and A1:C9 range. The existing
ETF116_CONNECTOR_PROBE tab and its connector proof are never written.

One Sheets batchUpdate atomically adds the new tab with an explicit sheetId
and populates exactly27 literal string cells through updateCells using that
same ID. A name/ID collision invalidates the entire batch: even a foreign
client racing after metadata inspection cannot turn this into an overwrite.
No existing-sheet update path or standalone values PUT exists. An independent
values GET and final owner check must succeed. A preexisting exact run/attempt
tab permits GET-only reconciliation only when its literal marker matches;
that state is separately reported and does not prove a new write. Different
attempts use separate tabs and preserve prior evidence. Ambiguous batch
results are never retried, cleared or cleaned up.

The CLI records fixed stages for owner initialization, private checks, Sheets
metadata GET, existing-marker GET, pre-write recheck, atomic POST, readback GET
and final private check. Both typed OwnerDrive refusals and ordinary exceptions
at `SHEETS_ATOMIC_POST` produce `ATOMIC_POST_OUTCOME_UNKNOWN`: NETWORK, HTTP_ERROR,
RESPONSE_SIZE, INVALID_JSON and CREDENTIAL_ECHO may follow an applied POST.
Only reviewed cause codes are persisted; arbitrary exception/response text is
never exposed. An UNKNOWN receipt is not proof of an OAuth failure or a write.
Do not replay it. Reconcile its exact binding/marker through the existing
`literal_private_tab(..., existing_only=True)` GET-only path; missing, foreign
or mismatched markers refuse without creating a tab or replacing the receipt.
This does not confer a fresh CREATE_AND_READBACK proof or publisher authority.

The registered H2 tests exercise the native CLI and unchanged transport/JSON
decoder with committed-response-loss fixtures. The registered H3 suite also
runs H2/H3 in a native optimized child interpreter; its launcher skips itself
under -O. POSIX locking/calendar modules are required, without substitute shims.

Receipt reservation precedes auth/network. Receipts contain hashes and run
binding, no tokens, account email, original research cells or HTTP/error body.
Service-account-only auth refuses rather than silently changing the principal.
If needed, that mode requires its own reviewed private-access contract.

After exact-head CI/review, an authorized manual invocation of the EXISTING
workflow uses probe_mode=etf116_private_sheet_probe,
confirm_private_sheet_probe=true, expected_code_sha=<exact branch HEAD>.
Native fixture results and this document do not prove that invocation occurred.
Inspect the actual workflow artifact/readback before claiming Actions rights.
No cron, automatic refresh, original research Sheet write or current-pointer
publication exists in this path. TR rights/CA/availability and two positive
real-session trials remain independent gates; this marker confers no PIT or
economic authority. Identical-marker readback is reported separately from a
new write and does not imply automatic-refresh readiness.

## Actual authorized trial, 2026-10-22 KST

The existing workflow's private mode ran once at exact
8b8797392ea31367e1acce752aa17ed01c9a8b8e, run39692292244/attempt1,
job119541191906. Its native H2 normal23/23 and -O23/23 passed. The real
access step stopped at SHEETS_METADATA_GET with PERMISSION (HTTP403), after
owner initialization and the fixed private Sheet's Drive checks/canEdit.
No Sheets mutation POST was reached. OAuth maintenance requests are not
counted by that statement. This is not an UNKNOWN POST or successful private
write/readback; API enablement versus token scope/other 403 causes remains
unresolved. No failed-job rerun or recovery write was performed.

Artifact12388907782 ZIP SHA256
f6cfefe4d0f7e0911dd29eb466c3df1fc49c06cca76baca268e0dc8be4aa3036;
the actual single JSON receipt SHA256
3a4675fa32eee01aa6654c01c1b96522694008e8c833da714f71db4a9f2361bd.
A separate read-only A6 independently verified the exact run, source stage,
artifact bytes and blocked/no-Sheets-write conclusion. Fresh activation and
Drive-result-sharing approval was received, but admitted TR, accepted anchor,
two actual completed-session E2Es and the remaining deployment gates still
have to pass. Automatic refresh remains disabled.

API contracts:
https://developers.google.com/workspace/sheets/api/guides/batch
https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate
https://developers.google.com/workspace/drive/api/reference/rest/v3/files
