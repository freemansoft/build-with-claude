---
name: format-and-lint
description: Formats and lints every file in this repo so it passes the project's checks — ruff format + ruff check for Python (host scripts and MicroPython device code), prettier for Markdown, JSON and YAML, and an mpy-cross compile check so device code still runs on UIFlow's MicroPython. Use it before every commit or PR, after editing any .py, .md, .json or .yaml file here, after running a generator script (gen_pet_frames, draw_blob_pet, gen_burst_frames), and whenever the user mentions formatting, linting, prettier, ruff, black, style, or "make it pass CI" — even if they only changed docs.
---

# Format and lint

One script does everything, using the configs at the repo root:

```bash
python3 .claude/skills/format-and-lint/scripts/format_and_lint.py           # fix what it can
python3 .claude/skills/format-and-lint/scripts/format_and_lint.py --check   # report only
python3 .claude/skills/format-and-lint/scripts/format_and_lint.py buddy/device-core2 README.md   # just these
```

| Files                      | Tool                                   | Config                                                    |
| -------------------------- | -------------------------------------- | --------------------------------------------------------- |
| `*.py`                     | `ruff format`, then `ruff check --fix` | `pyproject.toml`                                          |
| `*.md`, `*.json`, `*.yaml` | prettier 3.9.6 via `npx`               | `.prettierrc.json`, `.prettierignore` (plus `.gitignore`) |
| `buddy/device*/**/*.py`    | `mpy-cross` 1.22 compile (syntax only) | `requirements-dev.txt`                                    |

## Workflow

1. **Tools.** The script uses `.venv/` if it exists. If ruff or
   mpy-cross is missing it says so. Install them with
   `.venv/bin/python -m pip install -r requirements-dev.txt` (or
   `python3 -m pip install --user -r requirements-dev.txt`). prettier
   needs Node.js (`npx`).
2. **Run it in fix mode** on the whole repo, or on the paths you
   changed. The whole repo takes a few seconds and catches files you
   forgot.
3. **Fix what's left by hand.** Remaining ruff findings are real
   problems such as unused imports, undefined names or a missing
   `raise ... from`. Fix the code instead of adding `# noqa`. If a rule
   is wrong for this repo, change `pyproject.toml` and say why in a
   comment.
4. **Rerun with `--check`** and confirm the summary is all `ok` before
   you say you're done. Report anything still failing with its output.

## Things specific to this repo

- **Device code is MicroPython, not CPython.** That's why the ruff rule
  set is small (`E4`, `E7`, `E9`, `F`, `B`) and the target is `py37`.
  Many newer rules suggest things MicroPython lacks, such as
  `zip(strict=)`, `str.removeprefix` or `X | None` annotations. Don't
  widen the rule set or apply `--unsafe-fixes` to device code without
  checking that the result still compiles with mpy-cross 1.22. The
  script runs that compile check for you.
- **`E402` is off** on purpose, because the apps set up `sys.path`
  before importing the bundle.
- **Generated files are skipped:** `buddy/device/burst_frames.py` and
  `buddy/device-core2/pet_frames.py`. Change their generator scripts
  instead. `pet_art/blob/manifest.json` is a hand-edited source and is
  formatted. If `draw_blob_pet.py` rewrites it, rerun this script
  afterwards.
- **Markdown keeps its line breaks** (`proseWrap: preserve`). Prettier
  only normalizes tables, lists, code fences and spacing, so hand-wrapped
  prose stays as written.
- **Vendored pyserial** (`.claude/skills/m5-onboard/scripts/vendor/`) is
  excluded from both tools. Leave it as upstream ships it.
- **Worktrees:** the script checks the git checkout you run it from, so
  in a worktree it checks that worktree. Claude Code's agent worktrees
  (`.claude/worktrees/`) are gitignored, which keeps both tools out of
  them.
- **Symlinks:** `buddy/device-core2/` links several files to
  `buddy/device/`. Formatting one formats both, and the change appears
  in git under `buddy/device/`.
