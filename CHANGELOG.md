# Change Log

This file is a rolling update log. Keep appending new entries here by date and time.

## 2026-04-09

### 19:21 KST

- Hardened the Colab collector execution path so the run starts more reliably from the project location.
- Goal: reduce path-related failures before the main collection and training flow begins.

### 22:05 KST

- Added a Colab updater cell that downloads `companyfacts.zip` from the SEC bulk archive endpoint.
- The updater now uses a SEC-compatible `User-Agent`, retry and backoff, temp-file replacement, ZIP integrity checks, and a minimum-size guard before replacing the existing file.
- Download target is Google Drive project storage: `/content/drive/MyDrive/r1000_top30_institutional/companyfacts.zip`.

### 22:44 KST

- Changed the automatic `companyfacts.zip` refresh threshold from 7 days to 3 days.
- Goal: keep SEC fundamentals fresh without forcing a download every run.

## 2026-04-10

### 07:58 KST

- Added promotion logic so names initially classified as `early_scout` can be upgraded to `future_winner` when confirmation is already strong enough.
- Promotion now considers fundamental confirmation, market confirmation, statement history depth, benchmark relative strength, Minervini momentum state, and breakout setup quality.
- Reworked sleeve-specific name caps to separate new entry cap, drift cap for already-held winners, and hard absolute risk cap.
- Applied the new cap logic separately for `future_winner` and `early_scout` so speculative new entries stay controlled while strong held names can expand more naturally.
- Updated the monthly backtest state so positions drift with realized monthly returns between rebalances instead of reusing only the previous target weights.
- Added sleeve diagnostics to exported outputs:
  - `portfolio_sleeve_label_raw`
  - `portfolio_sleeve_promotion_signal`
  - `portfolio_sleeve_promoted`
  - `portfolio_prev_weight`
  - `portfolio_existing_holding`
  - `portfolio_name_cap`
- Fixed a follow-up bug where `future_winner` drift caps could bypass stricter active caps already applied to the same name.

## Expected Effect

- Better separation between speculative entries and proven winners.
- Less premature trimming of names that have already worked.
- More realistic portfolio weight evolution in backtests.
- Easier CSV-based diagnosis of sleeve assignment, promotion, previous weight, and effective cap behavior.

## Validation Note

- Local Python runtime was not available in this desktop environment, so no local `py_compile` check was run here.
- The intended validation path remains a fresh Colab rerun producing updated `portfolio_latest.csv`, `top30_latest.csv`, and sleeve backtest outputs.
