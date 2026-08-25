# Instructions for AI assistants working on this repository

## Attribution — non-negotiable

- NEVER add an AI co-author trailer to commits (no `Co-Authored-By: Claude …`
  or any similar line). The repository owner has explicitly forbidden it.
- NEVER put AI session links, AI tool names, or "Generated with …" footers in
  commit messages, PR titles/descriptions, code comments, or issue comments.
- Commit as the repository owner: `Cosmin Novac <cosminnovac@gmail.com>`.
- Branch names must be plain and descriptive — never prefixed with `claude/`
  or any other AI tool name.

## Project basics

- Plotly Dash (Flask) app; entry point `main.py` (exposes `server` for
  gunicorn). Python 3.11.
- Run tests with `pytest` (a venv with `requirements.txt` installed; keep
  `setuptools<81` — Dash 2.9 still imports `pkg_resources`).
- Number/currency formatting must go through `core/utils.py` helpers
  (`fmt_eur`, `fmt_num`, `fmt_pct`) so German/English output stays consistent.
- UI strings live in `components/i18n.py` — always add both `en` and `de`.
