"""Command-line interface for NEXCISION."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import DEFAULT_POSITION_PATTERN, NexusFilterError, filter_nexus_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nexcise",
        description=(
            "Excise coordinate-labelled NEXUS matrix rows that overlap "
            "1-based inclusive genomic regions."
        ),
    )
    parser.add_argument("nexus", type=Path, help="Input NEXUS file.")
    parser.add_argument(
        "regions",
        type=Path,
        help="Whitespace-delimited start/end regions file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("filtered.nex"),
        help="Filtered NEXUS output (default: filtered.nex).",
    )
    parser.add_argument(
        "--counts",
        type=Path,
        default=Path("removed_counts_per_region.tsv"),
        help=(
            "Per-region removal counts "
            "(default: removed_counts_per_region.tsv)."
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional deterministic JSON report with checksums and run parameters.",
    )
    parser.add_argument(
        "--position-regex",
        default=DEFAULT_POSITION_PATTERN,
        metavar="REGEX",
        help=(
            "Regex applied to the first matrix token. It must contain exactly one "
            "coordinate capture group "
            f"(default: {DEFAULT_POSITION_PATTERN!r})."
        ),
    )
    parser.add_argument(
        "--allow-unparsed",
        action="store_true",
        help="Preserve non-comment matrix rows that do not match --position-regex.",
    )
    parser.add_argument(
        "--update-dimension",
        choices=("auto", "ntax", "nchar", "none"),
        default="auto",
        help=(
            "Dimension field to update after filtering. auto selects nchar when "
            "FORMAT declares TRANSPOSE and ntax otherwise (default: auto)."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing output files.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"NEXCISION {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        result = filter_nexus_file(
            args.nexus,
            args.regions,
            args.output,
            args.counts,
            report_path=args.report,
            position_pattern=args.position_regex,
            allow_unparsed=args.allow_unparsed,
            update_dimension=args.update_dimension,
            force=args.force,
        )
    except NexusFilterError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Regions loaded: {result.regions_loaded}")
    print(f"Matrix rows read: {result.matrix_rows_read}")
    print(f"Rows removed: {result.rows_removed}")
    print(f"Rows kept: {result.rows_kept}")
    print(f"Unparsed rows preserved: {result.unparsed_rows}")
    if result.dimension_updated is None:
        print("Dimension updated: no")
    else:
        print(
            f"Dimension updated: {result.dimension_updated} "
            f"({result.dimension_before} -> {result.dimension_after})"
        )
    print(f"Filtered NEXUS: {args.output}")
    print(f"Region counts: {args.counts}")
    if args.report is not None:
        print(f"Run report: {args.report}")
    for warning in result.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    return 0
