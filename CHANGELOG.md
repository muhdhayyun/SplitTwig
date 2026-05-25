# Changelog

All notable changes to SplitTwig. Versions follow [SemVer](https://semver.org).

## [0.1.0] - 2026-05-21

### Added
- `/add @user 50 dinner` — log a payment on behalf of another group member.
- `/balance` rewrite: per-payer view with per-debtor cumulative subtotals.
- `/balance @user` — filter to a single user's "paid" section.
- Cumulative section at the bottom of `/balance`: settlements applied, netted per pair, with a math breakdown showing every signed component (raw expenses, payments, reverse expenses).
- Settlements listed in their own section at the bottom of `/balance`.
- `run.bat` now uses `watchfiles` to auto-restart the bot when source files change.
- Network-error handler to suppress transient `httpx.ReadError` noise from the logs.
- `CHANGELOG.md` and SemVer-tagged releases.

### Fixed
- Leading `@` in display names is stripped in `/balance` so Telegram does not ping users.
- Markdown special characters (`_`, `*`, `` ` ``, `[`) in member names no longer break message parsing.
- `.env` is loaded from the bot's directory regardless of the working directory.
