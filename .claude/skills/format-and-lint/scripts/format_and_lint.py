#!/usr/bin/env python3
"""Format and lint the repo: ruff (Python), prettier (Markdown/JSON/YAML),
and an mpy-cross syntax check of the MicroPython device code.

    python3 .claude/skills/format-and-lint/scripts/format_and_lint.py           # fix
    python3 .claude/skills/format-and-lint/scripts/format_and_lint.py --check   # report only
    python3 .claude/skills/format-and-lint/scripts/format_and_lint.py PATH ...  # only these

Exits non-zero if anything still fails after fixing (or, with --check,
if anything would change). Settings live in pyproject.toml,
.prettierrc.json and .prettierignore at the repo root.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PRETTIER = "prettier@3.9.6"
MPY_CROSS_VERSION = "v1.22"  # UIFlow 2.0's MicroPython
PRETTIER_EXTS = {".md", ".json", ".yaml", ".yml"}
DEVICE_DIRS = ("buddy/device", "buddy/device-core2")


def _repo_root():
    """The checkout you're in (so a worktree checks itself), falling
    back to the checkout this script lives in."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if out:
            return Path(out)
    except (OSError, subprocess.CalledProcessError):
        pass
    return Path(__file__).resolve().parents[4]


ROOT = _repo_root()


def venv_python():
    for rel in (".venv/bin/python", ".venv/Scripts/python.exe"):
        p = ROOT / rel
        if p.exists():
            return str(p)
    return sys.executable


def has_module(python, module):
    r = subprocess.run(
        [python, "-c", f"import {module}"], capture_output=True, cwd=ROOT, check=False
    )
    return r.returncode == 0


def ruff_cmd():
    py = venv_python()
    if has_module(py, "ruff"):
        return [py, "-m", "ruff"]
    exe = shutil.which("ruff")
    if exe:
        return [exe]
    sys.exit(
        "ruff not found. Install the dev tools:\n"
        f"  {py} -m pip install -r requirements-dev.txt"
    )


def mpy_cross_cmd():
    py = venv_python()
    if not has_module(py, "mpy_cross"):
        sys.exit(
            "mpy-cross not found. Install the dev tools:\n"
            f"  {py} -m pip install -r requirements-dev.txt"
        )
    cmd = [py, "-m", "mpy_cross"]
    out = subprocess.run(
        cmd + ["--version"], capture_output=True, text=True, check=False
    ).stdout
    if MPY_CROSS_VERSION not in out:
        print(
            f"warning: mpy-cross is {out.strip()!r}, expected MicroPython "
            f"{MPY_CROSS_VERSION} (see requirements-dev.txt)"
        )
    return cmd


def run(label, cmd):
    print(f"\n== {label}\n$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode == 0


def is_device_file(path):
    rel = (
        path.resolve().relative_to(ROOT).as_posix()
        if path.is_absolute()
        else path.as_posix()
    )
    return rel.endswith(".py") and any(
        rel == d or rel.startswith(d + "/") for d in DEVICE_DIRS
    )


def device_files(paths):
    if paths is None:
        files = []
        for d in DEVICE_DIRS:
            files += [
                p for p in (ROOT / d).rglob("*.py") if "__pycache__" not in p.parts
            ]
        return sorted(files)
    out = []
    for p in paths:
        p = (ROOT / p) if not Path(p).is_absolute() else Path(p)
        if p.is_dir():
            out += [q for q in p.rglob("*.py") if "__pycache__" not in q.parts]
        elif p.suffix == ".py":
            out.append(p)
    return sorted(q for q in out if is_device_file(q.resolve()))


def mpy_check(files):
    print(f"\n== mpy-cross syntax check ({len(files)} device files)", flush=True)
    cmd = mpy_cross_cmd()
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out.mpy")
        for f in files:
            r = subprocess.run(
                cmd + ["-o", out, str(f)],
                capture_output=True,
                text=True,
                cwd=ROOT,
                check=False,
            )
            if r.returncode != 0:
                ok = False
                print(f"FAIL {f.relative_to(ROOT)}\n{r.stderr or r.stdout}")
    if ok:
        print("all compile")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="report only, change nothing")
    ap.add_argument(
        "paths", nargs="*", help="files or directories (default: whole repo)"
    )
    args = ap.parse_args()
    paths = args.paths or None

    ruff = ruff_cmd()
    py_targets = (
        [p for p in args.paths if p.endswith(".py") or (ROOT / p).is_dir()]
        if paths
        else ["."]
    )
    pretty_targets = (
        [
            p
            for p in args.paths
            if Path(p).suffix in PRETTIER_EXTS or (ROOT / p).is_dir()
        ]
        if paths
        else ["."]
    )

    results = {}
    if py_targets:
        if args.check:
            results["ruff format"] = run(
                "ruff format --check",
                ruff + ["format", "--check", "--diff"] + py_targets,
            )
            results["ruff check"] = run("ruff check", ruff + ["check"] + py_targets)
        else:
            results["ruff format"] = run("ruff format", ruff + ["format"] + py_targets)
            results["ruff check"] = run(
                "ruff check --fix", ruff + ["check", "--fix"] + py_targets
            )

    if pretty_targets:
        npx = shutil.which("npx")
        if not npx:
            print(
                "\n== prettier\nnpx not found — install Node.js to format Markdown/JSON."
            )
            results["prettier"] = False
        else:
            mode = "--check" if args.check else "--write"
            results["prettier"] = run(
                f"prettier {mode}",
                [
                    npx,
                    "--yes",
                    PRETTIER,
                    mode,
                    "--ignore-unknown",
                    "--log-level",
                    "warn",
                ]
                + pretty_targets,
            )

    dev = device_files(paths)
    if dev:
        results["mpy-cross"] = mpy_check(dev)

    print("\n== summary")
    for name, ok in results.items():
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
