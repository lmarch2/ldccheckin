# Repository Guidelines

## Project Structure & Module Organization
- Core logic lives in `scripts/`, currently centered on `scripts/ryanai_store_checkin.py`.
- Runtime-only data is kept under `state/` (cookies, local action ID config) and `artifacts/` (debug responses). Both are ignored by Git.
- Documentation and onboarding are in `README.md`.
- Example configuration for multi-site action IDs is in `action_ids.example.json`.
- No separate `tests/` directory exists yet.

## Build, Test, and Development Commands
- `python scripts/ryanai_store_checkin.py --help` — show CLI options and defaults.
- `python scripts/ryanai_store_checkin.py --base-url https://oeo.cc.cd/` — run a single-site check-in.
- `python -m py_compile scripts/ryanai_store_checkin.py` — fast syntax validation before commit.
- `python scripts/ryanai_store_checkin.py` — default run for `https://store.ryanai.org/`.

## Coding Style & Naming Conventions
- Language: Python 3.10+.
- Follow PEP 8 with 4-space indentation and descriptive snake_case names.
- Keep functions focused and small; prefer explicit error handling over implicit fallbacks.
- Keep CLI flags and config keys stable (`--action-config-file`, `status_action_id`, `checkin_action_id`).
- New files should use clear names aligned with purpose (e.g., `*_checkin.py`, `*.example.json`).

## Testing Guidelines
- There is no formal test framework configured yet.
- Minimum validation for every change:
  - `python -m py_compile scripts/ryanai_store_checkin.py`
  - at least one local CLI smoke run against a target site.
- If you add tests in the future, place them under `tests/` and prefer `test_<feature>.py` naming.

## Commit & Pull Request Guidelines
- Use Conventional Commits (seen in history):
  - `feat(scripts): ...`
  - `fix(readme): ...`
- Keep commits scoped to one logical change.
- PRs should include:
  - change summary,
  - validation commands and outputs,
  - any config or behavior impact.

## Security & Configuration Tips
- Never commit real cookies, tokens, or debug payloads.
- Keep sensitive runtime files in `state/` only.
- Use `action_ids.example.json` as template, then write local values to `state/action_ids.json`.
