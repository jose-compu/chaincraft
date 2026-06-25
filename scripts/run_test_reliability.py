#!/usr/bin/env python3
"""Run the pytest suite repeatedly and write EVAL.md reliability metrics."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run_once(pytest_args: list[str], cwd: Path) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "pytest", *pytest_args]
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output


def parse_summary(output: str) -> str:
    for line in reversed(output.splitlines()):
        stripped = line.strip().strip("=")
        if not stripped:
            continue
        lower = stripped.lower()
        if "passed" in lower or "failed" in lower or "error" in lower:
            return stripped
    tail = output.strip().splitlines()
    return tail[-1] if tail else "ok"


def write_eval(
    path: Path,
    *,
    runs: int,
    clean: int,
    failures: list[tuple[int, int, str]],
    pytest_args: list[str],
) -> None:
    reliability = (100.0 * clean / runs) if runs else 0.0
    lines = [
        "# Chaincraft test reliability",
        "",
        f"- **Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"- **Command:** `python -m pytest {' '.join(pytest_args)}`",
        f"- **Runs:** {runs}",
        f"- **Clean runs:** {clean}",
        f"- **Failed runs:** {len(failures)}",
        f"- **Reliability:** {reliability:.1f}%",
        "",
    ]
    if failures:
        lines.append("## Failed runs")
        lines.append("")
        for run_no, code, summary in failures:
            lines.append(f"### Run {run_no} (exit {code})")
            lines.append("")
            lines.append(f"`{summary}`")
            lines.append("")
    else:
        lines.append("All runs passed.")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-n",
        "--runs",
        type=int,
        default=3,
        help="Number of full-suite repetitions (default: 3)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="EVAL.md",
        help="Markdown report path (default: EVAL.md)",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Arguments after -- passed to pytest (default: tests -q)",
    )
    args = parser.parse_args()
    pytest_args = args.pytest_args
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]
    if not pytest_args:
        pytest_args = ["tests", "-q"]

    repo_root = Path(__file__).resolve().parents[1]
    failures: list[tuple[int, int, str]] = []
    clean = 0

    print(f"Running pytest {args.runs} time(s): {' '.join(pytest_args)}")
    for i in range(1, args.runs + 1):
        print(f"\n--- run {i}/{args.runs} ---", flush=True)
        code, output = run_once(pytest_args, repo_root)
        summary = parse_summary(output)
        print(summary, flush=True)
        if code == 0:
            clean += 1
        else:
            failures.append((i, code, summary))
            print(output[-4000:], file=sys.stderr)

    out_path = repo_root / args.output
    write_eval(
        out_path,
        runs=args.runs,
        clean=clean,
        failures=failures,
        pytest_args=pytest_args,
    )
    print(f"\nWrote {out_path} — reliability {100.0 * clean / args.runs:.1f}%")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
