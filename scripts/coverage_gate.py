"""Check that an lcov report reaches 100 % coverage: lines, functions and branches.

    python scripts/coverage_gate.py coverage/js/lcov.info --name JS

Prints a per-file table and what is left uncovered, then exits with an error below the threshold.
In GitHub Actions, the same summary is appended as Markdown to $GITHUB_STEP_SUMMARY.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

METRICS = (("lines", "Lines"), ("functions", "Functions"), ("branches", "Branches"))
# Totals computed by the tool that wrote the report: they win when present.
SUMMARY_KEYS = {
    "LF": ("lines", "found"),
    "LH": ("lines", "hit"),
    "FNF": ("functions", "found"),
    "FNH": ("functions", "hit"),
    "BRF": ("branches", "found"),
    "BRH": ("branches", "hit"),
}


@dataclass
class Counter:
    """Number of items found in a file and how many of them were hit by the tests."""

    found: int = 0
    hit: int = 0

    @property
    def percent(self) -> float:
        """Coverage percentage; a file with nothing to measure counts as fully covered."""
        return 100.0 if self.found == 0 else 100.0 * self.hit / self.found

    def add(self, other: Counter) -> None:
        """Accumulate another counter into this one."""
        self.found += other.found
        self.hit += other.hit


@dataclass
class FileCoverage:
    """Coverage of one source file, with what is left uncovered."""

    path: str
    lines: Counter = field(default_factory=Counter)
    functions: Counter = field(default_factory=Counter)
    branches: Counter = field(default_factory=Counter)
    missed_lines: list[int] = field(default_factory=list)
    missed_functions: list[str] = field(default_factory=list)
    missed_branches: list[int] = field(default_factory=list)

    def counter(self, metric: str) -> Counter:
        """Counter for "lines", "functions" or "branches"."""
        counter: Counter = getattr(self, metric)
        return counter

    def misses(self) -> list[str]:
        """Human-readable list of what is not covered."""
        details = []
        if self.missed_lines:
            details.append(f"uncovered lines: {ranges(self.missed_lines)}")
        if self.missed_functions:
            details.append(f"functions never called: {', '.join(self.missed_functions)}")
        if self.missed_branches:
            details.append(f"branches not taken (lines): {ranges(self.missed_branches)}")
        return details


class _Record:
    """One `SF:` ... `end_of_record` block of an lcov file."""

    def __init__(self, path: str) -> None:
        self.file = FileCoverage(path)
        self.function_hits: dict[str, int] = {}
        self.summary: dict[tuple[str, str], int] = {}

    def feed(self, key: str, value: str) -> None:
        """Handle one `KEY:value` line of the block."""
        if key == "DA":
            self._line(value)
        elif key == "FN":
            self.function_hits.setdefault(value.split(",")[-1], 0)
        elif key in ("FNDA", "FNA"):
            # FNDA:<calls>,<name> (lcov 1) or FNA:<index>,<calls>,<name> (lcov 2).
            fields = value.split(",", 2 if key == "FNA" else 1)
            self.function_hits[fields[-1]] = max(self.function_hits.get(fields[-1], 0), int(fields[-2]))
        elif key == "BRDA":
            self._branch(value)
        elif key in SUMMARY_KEYS:
            self.summary[SUMMARY_KEYS[key]] = int(value)

    def _line(self, value: str) -> None:
        line, count = value.split(",")[:2]
        self.file.lines.found += 1
        if int(count) > 0:
            self.file.lines.hit += 1
        else:
            self.file.missed_lines.append(int(line))

    def _branch(self, value: str) -> None:
        line, _block, _branch, taken = value.split(",")[:4]
        self.file.branches.found += 1
        if taken not in ("-", "0"):
            self.file.branches.hit += 1
        elif int(line) not in self.file.missed_branches:
            self.file.missed_branches.append(int(line))

    def finish(self) -> FileCoverage:
        """Close the block, preferring the totals written by the coverage tool."""
        hits = self.function_hits
        self.file.functions = Counter(len(hits), sum(1 for n in hits.values() if n))
        self.file.missed_functions = [name for name, n in hits.items() if not n]
        for (metric, attr), number in self.summary.items():
            setattr(self.file.counter(metric), attr, number)
        return self.file


def parse_lcov(text: str) -> list[FileCoverage]:
    """Parse an lcov report into one FileCoverage per source file."""
    files: list[FileCoverage] = []
    record: _Record | None = None
    for raw in text.splitlines():
        key, _, value = raw.strip().partition(":")
        if key == "SF":
            record = _Record(value)
        elif record is not None and key == "end_of_record":
            files.append(record.finish())
            record = None
        elif record is not None:
            record.feed(key, value)
    return files


def ranges(numbers: list[int]) -> str:
    """[3, 4, 5, 9] -> "3-5, 9"."""
    spans: list[list[int]] = []
    for n in sorted(set(numbers)):
        if spans and n == spans[-1][-1] + 1:
            spans[-1].append(n)
        else:
            spans.append([n])
    return ", ".join(str(s[0]) if len(s) == 1 else f"{s[0]}-{s[-1]}" for s in spans)


def pct(counter: Counter) -> str:
    """Percentage with one decimal, e.g. "96.3 %" or "100 %"."""
    return f"{counter.percent:.1f}".removesuffix(".0") + " %"


def cell(counter: Counter) -> str:
    """Table cell, e.g. "131/136 (96.3 %)"."""
    return f"{counter.hit}/{counter.found} ({pct(counter)})"


def passes(total: FileCoverage, threshold: float) -> bool:
    """True when every metric reaches the threshold."""
    return all(total.counter(metric).percent >= threshold for metric, _ in METRICS)


def verdict(name: str, total: FileCoverage, threshold: float) -> str:
    """Last line of the report: success, or the measured values against the target."""
    if passes(total, threshold):
        goal = "100 %" if threshold >= 100 else f"at least {threshold:g} %"
        return f"✓ {name} coverage: {goal} of lines, functions and branches."
    measured = ", ".join(f"{label.lower()} {pct(total.counter(m))}" for m, label in METRICS)
    return f"✗ {name} coverage too low: {measured}. Every metric must reach {threshold:g} %."


def text_report(name: str, source: Path, files: list[FileCoverage], total: FileCoverage) -> list[str]:
    """Terminal table with one row per file, the total and what is left to cover."""
    width = max(len(f.path) for f in [*files, total])

    def row(f: FileCoverage) -> str:
        return f"{f.path:<{width}}  " + "  ".join(f"{cell(f.counter(m)):>18}" for m, _ in METRICS)

    head = f"{'File':<{width}}  " + "  ".join(f"{label:>18}" for _, label in METRICS)
    lines = [f"{name} coverage: {source}", head, *map(row, files), "-" * len(head), row(total)]
    for f in files:
        if details := f.misses():
            lines += ["", f"  {f.path}", *(f"    {d}" for d in details)]
    return lines


def markdown_report(name: str, files: list[FileCoverage], total: FileCoverage, threshold: float) -> list[str]:
    """Same report as a Markdown table, for the GitHub Actions job summary."""
    icon = "✅" if passes(total, threshold) else "❌"
    lines = [
        f"### {icon} {name} coverage: {pct(total.lines)} of lines",
        "",
        "| File | " + " | ".join(label for _, label in METRICS) + " |",
        "| --- |" + " ---: |" * len(METRICS),
        *(f"| `{f.path}` | " + " | ".join(cell(f.counter(m)) for m, _ in METRICS) + " |" for f in files),
        "| **Total** | " + " | ".join(f"**{cell(total.counter(m))}**" for m, _ in METRICS) + " |",
    ]
    uncovered = [f"- `{f.path}`: {'; '.join(details)}" for f in files if (details := f.misses())]
    if uncovered:
        lines += ["", "Still to cover:", "", *uncovered]
    return lines


def main(argv: list[str] | None = None) -> int:
    """Command line entry point: 0 when the gate passes, 1 below the threshold, 2 on a bad report."""
    parser = argparse.ArgumentParser(description="Fail when an lcov report is below the coverage threshold.")
    parser.add_argument("lcov", type=Path, help="lcov file (lcov.info)")
    parser.add_argument("--name", default="", help="name shown in the summary, e.g. JS or Python")
    parser.add_argument("--threshold", type=float, default=100.0, help="threshold in %% (default: 100)")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="root used to shorten file paths")
    args = parser.parse_args(argv)

    if not args.lcov.is_file():
        print(f"✗ Coverage report not found: {args.lcov}", file=sys.stderr)
        return 2
    files = parse_lcov(args.lcov.read_text(encoding="utf-8"))
    if not files:
        print(f"✗ No measured file in {args.lcov}: did the tests run?", file=sys.stderr)
        return 2

    root = args.root.resolve()
    total = FileCoverage("Total")
    for f in files:
        path = Path(f.path)
        if path.is_absolute() and path.is_relative_to(root):
            f.path = str(path.relative_to(root))
        for metric, _ in METRICS:
            total.counter(metric).add(f.counter(metric))

    name = args.name or args.lcov.stem
    last = verdict(name, total, args.threshold)
    print("\n".join([*text_report(name, args.lcov, files, total), "", last]))
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_file).open("a", encoding="utf-8") as out:
            out.write("\n".join([*markdown_report(name, files, total, args.threshold), "", last, "", ""]))
    return 0 if passes(total, args.threshold) else 1


if __name__ == "__main__":
    sys.exit(main())
