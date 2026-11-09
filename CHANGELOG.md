# Changelog

## 0.1.0 (2026-11-08)

First packaged release. Install from git (not on PyPI):
`pipx install git+https://github.com/karan-patel11/stock-desk`.

### Added
- `stockdesk` command with one subcommand per tool: `fund`, `tech`, `news`, `precedent`, `verify`, `round`,
  `confidence`, `evidence-table`. Same arguments and the same JSON contract as the old scripts.
- `stockdesk init`: creates `~/.stockdesk` (`evidence/`, `cache/`, `config/`) and `config.env` (mode 0600) with the
  SEC contact. Never changes an existing `config.env` without `--force`. `--copy-config`, `--non-interactive`, `--json`.
- `stockdesk doctor`: PASS/WARN/FAIL checks for Python, the executable, the data home, `SEC_USER_AGENT`, Claude Code,
  Switch Console (WARN: no documented way to detect it), SEC, Yahoo and GDELT (`--offline` skips these), and the
  bundled data.
- `stockdesk template`: writes the Switch desk template (or `--mention-test`) for this machine, with the absolute
  `stockdesk` path and `STOCKDESK_HOME` written into every tool call. Prints the Switch import and Slack steps.
- `pyproject.toml` (setuptools), extras `yaml` and `dev`, `CHANGELOG.md`.

### Changed
- Code moved to `src/stockdesk/`; agents, config JSON and template sources are package data.
- Data home: `STOCKDESK_HOME`, else `STOCKDESK_HOME` in `~/.stockdesk/config.env`, else `~/.stockdesk`. The repo
  folder is no longer used as a fallback, and `.env` is no longer read (`config.env` replaces it).
- A config JSON in `<home>/config/` replaces the bundled copy whole; which one was used is logged to stderr.
- A missing `SEC_USER_AGENT` now says "run `stockdesk init`".
- Agent instructions call `stockdesk <tool>` instead of `$STOCKDESK_PY $STOCKDESK_HOME/tools/<tool>.py`; the
  template's `python` and `stockdesk_home` params are gone.

### Deprecated
- `python tools/<name>.py` and `python scripts/build_template.py`: thin shims to the `stockdesk` command.

### Removed
- `switch/desk-team.template.yaml` (generated per machine now) and `.env.example` (now `config.env.example`).
