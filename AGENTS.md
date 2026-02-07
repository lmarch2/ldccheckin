# Repository Guidelines

## Project Structure & Module Organization
- Core implementation lives in the `ldccheckin/` package:
  - `cli_checkin.py` (check-in CLI)
  - `cli_wizard.py` (interactive setup wizard)
  - `constants.py` (shared defaults and host mappings)
- `scripts/` contains runnable entrypoints:
  - `scripts/checkin.py` and `scripts/wizard.py`
- Runtime-only data stays in `state/` and debug output in `artifacts/` (both Git-ignored).
- Docs and onboarding are in `README.md`; sample configs are `action_ids.example.json` and `shops.example.txt`.

## Build, Test, and Development Commands
- `python scripts/checkin.py --help` — show check-in CLI options.
- `python scripts/wizard.py --help` — show wizard options.
- `python scripts/checkin.py --base-url https://oeo.cc.cd/` — run one target shop.
- `python scripts/checkin.py --run-all` — run all built-in shops once.
- `python -m py_compile ldccheckin/*.py scripts/*.py` — fast syntax validation.

## Coding Style & Naming Conventions
- Python 3.10+, PEP 8, 4-space indentation, descriptive snake_case names.
- Keep business logic in `ldccheckin/`; keep `scripts/` as thin wrappers.
- Reuse `ldccheckin/constants.py` for defaults to avoid duplicated host/config maps.
- Preserve stable CLI flags and config keys (`--action-config-file`, `status_action_id`, `checkin_action_id`).

## Testing Guidelines
- No formal test framework yet.
- Minimum validation per change:
  - `python -m py_compile ldccheckin/*.py scripts/*.py`
  - at least one local smoke run (e.g., `python scripts/checkin.py --base-url ...`).
- If adding tests, place them in `tests/` using `test_<feature>.py` naming.

## Commit & Pull Request Guidelines
- Use Conventional Commits (e.g., `feat(checkin): ...`, `fix(readme): ...`).
- Keep each commit focused on one logical change.
- PRs should include summary, validation commands/results, and config/behavior impacts.

## Security & Configuration Tips
- Never commit real cookies, tokens, or debug payloads.
- Keep secrets under `state/` only.
- Use `action_ids.example.json` as template and write local values to `state/action_ids.json`.
