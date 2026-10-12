# CLAUDE.md — GridPulse

Spec for coding assistants. The design lives in `docs/blueprint.md`; progress lives in `docs/STATUS.md`.

## Every session
1. Read `docs/STATUS.md` (current focus, next up, blockers) and the open items in `TODO.md`.
2. Work on the current focus only. New ideas go to "Deferred / later" in STATUS.md.
3. Before ending: update STATUS.md (tick steps only with date + evidence, refresh "Next up", add a session-log line).

## Human tasks (`TODO.md`, git-ignored, never committed)
- Anything only the human can do (accounts, keys, console clicks, installs, approvals) goes in `TODO.md` with the next permanent ID (`#N`, never reused or changed).
- Put it under `## Blocking` if any step is waiting on it (say which), otherwise under `## Non-blocking`. Each section is an ordered list in suggested order; move a task between sections when that changes, keeping its ID.
- Tag each task with its scope: 💻 Local, ☁️ Online (GitHub/AWS), or 💻☁️ Both. Add "What it is" (explain new terms in plain words), numbered steps, and a "Check it worked" command.
- When adding one, start the reply with `🔔 Action needed: TODO #N — <task>` and send a push notification if work is blocked.
- When the human confirms it is done, mark `[x]` with `done YYYY-MM-DD`, move the whole task (guide included) to the `## Done` section at the bottom (newest first), and unblock it in STATUS.md. Never delete tasks.
- Secrets go in `.env` (git-ignored). Never ask for them in chat.

## Blueprint changes
- Edit `docs/blueprint.md` in place when a decision changes, and add a line to its `## Changelog`.
- A change that reverses a decision also gets an ADR in `docs/adr/` (copy `0000-template.md`).

## Conventions
- Python 3.12, `uv` workspace, `ruff` (line length 100). Pin every version: `uv.lock`, Helm chart versions, Terraform providers, image tag + digest.
- Two runtimes, same code: `local` (SeaweedFS S3 + Lakekeeper Iceberg REST + Trino) and `aws` (S3 + Glue + Athena v3). Engine differences go in dbt `adapter.dispatch` macros or config, never in forks of the code.
- dbt: prefixes `stg_`, `int_`, `dim_`, `fct_`, `snap_`; snake_case; units in names (`demand_mwh`); timestamps `_utc` / `_local`; contracts on every mart.
- Domain rules: store UTC, derive local time from the BA seed; interchange is positive for exports (`net_imports` flips the sign); ratios are ratios of sums; flag bad values, never delete them.
- The agent produces metric requests, never SQL.

## Resource hygiene
- Start only the compose profile you need (`make up-lake` / `up-orch` / `up-app`). Every service has a memory limit.
- Tests create `test_<run_id>` schemas and drop them in teardown. Run `make clean` after heavy work.
- AWS compute is ephemeral: `make aws-down` after every demo. Only the foundation stack stays up.

## Commands
`make help` lists everything. Core: `make setup`, `make lint`, `make test`, `make status`, `make doctor`, `make clean`.
