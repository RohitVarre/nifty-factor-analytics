# CLAUDE.md

Research project and Dash dashboard comparing 41 Indian NSE Total Return Indices (2005 to today). Methodology, status, roadmap and the full Mistakes Log live in [AGENTS.md](AGENTS.md); this file adds the dev-loop setup. Overview and usage: [README.md](README.md).

## Environment
- Conda env `main`. `CONDA_PREFIX` may be empty, so prefix commands with `conda run -n main --no-capture-output`.
- Install with `uv pip install <pkg>`; record dependencies in `requirements.txt`. Tool settings live in `pyproject.toml`.
- The repo is public. `data/` and `cache/` are gitignored (NSE data): a fresh clone must run `python download_new_indices.py` before the tests or app work. No personal paths, emails or credentials in tracked files.

## Checks
Run by the `check` skill. Tool settings live in pyproject.toml. All checks must pass before a commit.

| Check       | Verify (read-only)                        | Fix                  |
|-------------|-------------------------------------------|----------------------|
| format      | `ruff format --check .`                   | `ruff format .`      |
| lint        | `ruff check .`                            | `ruff check --fix .` |
| types       | `pyright`                                 | —                    |
| tests       | `pytest -q -m "not slow and not review"`  | —                    |
| tests, slow | `pytest -q -m "not review"`               | —                    |

Covered: analytics maths (tests/test_analytics.py) · every Dash callback end to end (tests/test_app_e2e.py)
Other commands (not run by check): refresh data `python download_new_indices.py` · app `python app.py` (port 4400) · notebook `jupyter nbconvert --to notebook --execute --inplace Indian_Indices_Analysis.ipynb`

New tests go in `tests/`. The suite is unittest-style (pytest runs it). `tests/review/0001/` holds unpromoted review tests and has no `review` marker yet.

## Where to look
| Question | File |
|---|---|
| Methodology, status, past mistakes | AGENTS.md |
| Work in progress | `specs/`, `experiments/` |
| Background reading | `notes/research/`, `notes/brainstorm/` |
