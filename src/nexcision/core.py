"""Core filtering logic for NEXCISION."""

from __future__ import annotations

import bisect
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal, Pattern, Sequence

from ._version import VERSION

DEFAULT_POSITION_PATTERN = r"_(\d+)$"
DimensionPolicy = Literal["auto", "ntax", "nchar", "none"]


class NexusFilterError(ValueError):
    """Raised when NEXCISION cannot filter an input safely."""


@dataclass(frozen=True)
class Region:
    """A 1-based, inclusive genomic interval."""

    region_id: int
    start: int
    end: int
    name: str


@dataclass(frozen=True)
class FilterResult:
    """Summary returned after filtering."""

    regions_loaded: int
    matrix_rows_read: int
    rows_removed: int
    rows_kept: int
    unparsed_rows: int
    dimension_updated: str | None
    dimension_before: int | None
    dimension_after: int | None
    warnings: tuple[str, ...]


def load_regions(path: str | Path) -> list[Region]:
    """Load 1-based, inclusive regions from a whitespace-delimited file.

    The first two columns are integer start and end coordinates. A third column
    may provide a region name. Blank lines, ``#`` comments, and a header whose
    first field is ``start`` are ignored.
    """

    regions: list[Region] = []
    region_path = Path(path)

    try:
        handle = region_path.open("r", encoding="utf-8")
    except OSError as exc:
        raise NexusFilterError(
            f"Cannot open regions file '{region_path}': {exc}"
        ) from exc

    with handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            fields = re.split(r"\s+", line)
            if fields[0].lower() == "start":
                continue
            if len(fields) < 2:
                raise NexusFilterError(
                    f"Regions file line {line_number} must contain start and end."
                )

            try:
                start = int(fields[0])
                end = int(fields[1])
            except ValueError as exc:
                raise NexusFilterError(
                    f"Regions file line {line_number} has non-integer coordinates: "
                    f"{line!r}"
                ) from exc

            if start < 1 or end < 1:
                raise NexusFilterError(
                    f"Regions file line {line_number} contains a coordinate below 1."
                )
            if start > end:
                start, end = end, start

            region_id = len(regions) + 1
            name = fields[2] if len(fields) >= 3 else f"region_{region_id}"
            regions.append(Region(region_id, start, end, name))

    if not regions:
        raise NexusFilterError(f"No valid regions were found in '{region_path}'.")

    return regions


def compile_position_pattern(pattern: str = DEFAULT_POSITION_PATTERN) -> Pattern[str]:
    """Compile and validate a coordinate-extraction regular expression."""

    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise NexusFilterError(f"Invalid position regular expression: {exc}") from exc

    if compiled.groups != 1:
        raise NexusFilterError(
            "The position regular expression must contain exactly one capture group."
        )
    return compiled


def extract_position(line: str, pattern: Pattern[str]) -> int | None:
    """Extract a genomic coordinate from the first matrix token."""

    stripped = line.strip()
    if not stripped:
        return None

    token = stripped.split(maxsplit=1)[0].strip("'\"")
    match = pattern.search(token)
    if match is None:
        return None

    try:
        position = int(match.group(1))
    except ValueError as exc:
        raise NexusFilterError(
            f"Position pattern captured a non-integer value from token '{token}'."
        ) from exc

    if position < 1:
        raise NexusFilterError(
            f"Position pattern captured a coordinate below 1 from token '{token}'."
        )
    return position


def _merge_regions(
    regions: Sequence[Region],
) -> tuple[list[int], list[tuple[int, int]]]:
    intervals = sorted((region.start, region.end) for region in regions)
    merged: list[tuple[int, int]] = []

    for start, end in intervals:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))

    starts = [start for start, _ in merged]
    return starts, merged


def _is_excluded(
    position: int,
    starts: Sequence[int],
    intervals: Sequence[tuple[int, int]],
) -> bool:
    index = bisect.bisect_right(starts, position) - 1
    return index >= 0 and position <= intervals[index][1]


def _is_comment_or_blank(content: str) -> bool:
    stripped = content.strip()
    return not stripped or stripped.startswith("[")


def _matrix_is_transposed(prefix: str) -> bool:
    """Return whether the last FORMAT command declares TRANSPOSE."""

    format_commands = re.findall(r"(?is)\bformat\b(.*?);", prefix)
    for command in reversed(format_commands):
        if not re.search(r"(?i)\btranspose\b", command):
            continue
        disabled = re.search(
            r"(?i)\btranspose\s*=\s*(?:no|false|0)\b", command
        )
        return disabled is None
    return False


def _resolve_dimension(policy: DimensionPolicy, prefix: str) -> str | None:
    if policy == "none":
        return None
    if policy in {"ntax", "nchar"}:
        return policy
    if policy != "auto":
        raise NexusFilterError(
            "Dimension policy must be one of: auto, ntax, nchar, none."
        )
    return "nchar" if _matrix_is_transposed(prefix) else "ntax"


def _update_dimension(
    lines: list[str],
    matrix_start_index: int,
    original_rows: int,
    kept_rows: int,
    policy: DimensionPolicy,
) -> tuple[list[str], str | None, int | None, int | None, str | None]:
    prefix = "".join(lines[:matrix_start_index])
    suffix = "".join(lines[matrix_start_index:])
    field = _resolve_dimension(policy, prefix)
    if field is None:
        return lines, None, None, None, None

    matches = list(re.finditer(rf"(?i)\b{field}\s*=\s*(\d+)", prefix))
    if not matches:
        return (
            lines,
            None,
            None,
            None,
            f"No {field} field was found before MATRIX; dimensions were unchanged.",
        )
    if len(matches) > 1:
        return (
            lines,
            None,
            None,
            None,
            f"Multiple {field} fields were found before MATRIX; dimensions were "
            "unchanged.",
        )

    declared = int(matches[0].group(1))
    if declared != original_rows:
        return (
            lines,
            None,
            declared,
            None,
            f"Declared {field}={declared} does not match the {original_rows} matrix "
            "rows; dimensions were unchanged. Use --update-dimension to override "
            "automatic dimension selection if required.",
        )

    replacement = re.sub(
        rf"(?i)(\b{field}\s*=\s*)\d+",
        lambda found: f"{found.group(1)}{kept_rows}",
        prefix,
        count=1,
    )
    updated = (replacement + suffix).splitlines(keepends=True)
    return updated, field, declared, kept_rows, None


def _write_atomic(path: Path, content: str, *, force: bool) -> None:
    path = path.resolve()
    if path.exists() and not force:
        raise NexusFilterError(
            f"Output file already exists: '{path}'. Use --force to replace it."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            temp_name = handle.name
        os.replace(temp_name, path)
    except OSError as exc:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise NexusFilterError(f"Cannot write output file '{path}': {exc}") from exc


def _counts_tsv(regions: Sequence[Region], removed_positions: Iterable[int]) -> str:
    positions = sorted(removed_positions)
    rows = [["region_id", "region_name", "start", "end", "removed_rows"]]

    for region in regions:
        left = bisect.bisect_left(positions, region.start)
        right = bisect.bisect_right(positions, region.end)
        rows.append(
            [
                str(region.region_id),
                region.name,
                str(region.start),
                str(region.end),
                str(right - left),
            ]
        )

    return "\n".join("\t".join(row) for row in rows) + "\n"


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_text(content: str) -> str:
    return _sha256_bytes(content.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise NexusFilterError(f"Cannot checksum input file '{path}': {exc}") from exc
    return digest.hexdigest()


def filter_nexus_text(
    text: str,
    regions: Sequence[Region],
    *,
    position_pattern: str = DEFAULT_POSITION_PATTERN,
    allow_unparsed: bool = False,
    update_dimension: DimensionPolicy = "auto",
) -> tuple[str, str, FilterResult]:
    """Filter coordinate-labelled rows from one NEXUS MATRIX block."""

    if not regions:
        raise NexusFilterError("At least one region is required.")

    pattern = compile_position_pattern(position_pattern)
    starts, merged_regions = _merge_regions(regions)
    lines = text.splitlines(keepends=True)

    matrix_indices = [
        index for index, line in enumerate(lines) if line.strip().lower() == "matrix"
    ]
    if not matrix_indices:
        raise NexusFilterError("No standalone MATRIX line was found in the NEXUS file.")
    if len(matrix_indices) > 1:
        raise NexusFilterError(
            "More than one MATRIX block was found; NEXCISION intentionally supports "
            "one block per input."
        )

    matrix_start = matrix_indices[0]
    output_lines = lines[: matrix_start + 1]
    in_matrix = True
    terminated = False
    parsed_rows = 0
    rows_removed = 0
    parsed_rows_kept = 0
    unparsed_rows = 0
    removed_positions: list[int] = []

    for index in range(matrix_start + 1, len(lines)):
        line = lines[index]
        if not in_matrix:
            output_lines.append(line)
            continue

        before, separator, after = line.partition(";")
        content = before if separator else line

        if separator and content.strip().lower() in {"end", "endblock"}:
            raise NexusFilterError(
                "The MATRIX block is not terminated before the enclosing block ends."
            )

        if _is_comment_or_blank(content):
            output_lines.append(line)
            if separator:
                in_matrix = False
                terminated = True
            continue

        position = extract_position(content, pattern)
        if position is None:
            unparsed_rows += 1
            if not allow_unparsed:
                raise NexusFilterError(
                    f"Matrix line {index + 1} does not match the position pattern: "
                    f"{content.strip()!r}. Use --allow-unparsed to preserve it."
                )
            output_lines.append(line)
            if separator:
                in_matrix = False
                terminated = True
            continue

        parsed_rows += 1
        if _is_excluded(position, starts, merged_regions):
            rows_removed += 1
            removed_positions.append(position)
            if separator:
                newline = "\n" if line.endswith("\n") else ""
                output_lines.append(f";{after.rstrip(chr(10))}{newline}")
        else:
            parsed_rows_kept += 1
            output_lines.append(line)

        if separator:
            in_matrix = False
            terminated = True

    if not terminated:
        raise NexusFilterError("The MATRIX block is not terminated by a semicolon.")
    if parsed_rows == 0:
        raise NexusFilterError(
            "No coordinate-labelled rows were parsed from the MATRIX block."
        )

    matrix_rows = parsed_rows + unparsed_rows
    rows_kept = parsed_rows_kept + unparsed_rows
    warnings: list[str] = []
    output_lines, dimension_name, dimension_before, dimension_after, warning = (
        _update_dimension(
            output_lines,
            matrix_start,
            matrix_rows,
            rows_kept,
            update_dimension,
        )
    )
    if warning:
        warnings.append(warning)

    counts = _counts_tsv(regions, removed_positions)
    result = FilterResult(
        regions_loaded=len(regions),
        matrix_rows_read=matrix_rows,
        rows_removed=rows_removed,
        rows_kept=rows_kept,
        unparsed_rows=unparsed_rows,
        dimension_updated=dimension_name,
        dimension_before=dimension_before,
        dimension_after=dimension_after,
        warnings=tuple(warnings),
    )
    return "".join(output_lines), counts, result


def _run_report(
    *,
    nexus: Path,
    regions: Path,
    output: Path,
    counts: Path,
    filtered_text: str,
    counts_text: str,
    result: FilterResult,
    position_pattern: str,
    allow_unparsed: bool,
    update_dimension: DimensionPolicy,
) -> str:
    payload = {
        "software": {"name": "NEXCISION", "version": VERSION},
        "inputs": {
            "nexus": {"path": str(nexus), "sha256": _sha256_file(nexus)},
            "regions": {"path": str(regions), "sha256": _sha256_file(regions)},
        },
        "parameters": {
            "allow_unparsed": allow_unparsed,
            "position_regex": position_pattern,
            "update_dimension": update_dimension,
        },
        "results": asdict(result),
        "outputs": {
            "filtered_nexus": {
                "path": str(output),
                "sha256": _sha256_text(filtered_text),
            },
            "region_counts": {
                "path": str(counts),
                "sha256": _sha256_text(counts_text),
            },
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def filter_nexus_file(
    nexus_path: str | Path,
    regions_path: str | Path,
    output_path: str | Path,
    counts_path: str | Path,
    *,
    report_path: str | Path | None = None,
    position_pattern: str = DEFAULT_POSITION_PATTERN,
    allow_unparsed: bool = False,
    update_dimension: DimensionPolicy = "auto",
    force: bool = False,
) -> FilterResult:
    """Filter a NEXUS file and write deterministic outputs."""

    nexus = Path(nexus_path)
    regions_file = Path(regions_path)
    output = Path(output_path)
    counts = Path(counts_path)
    report = Path(report_path) if report_path is not None else None

    input_paths = {nexus.resolve(), regions_file.resolve()}
    destinations = [output, counts] + ([report] if report is not None else [])
    output_paths = {destination.resolve() for destination in destinations}

    if len(output_paths) != len(destinations):
        raise NexusFilterError("Every output path must be different.")
    if input_paths & output_paths:
        raise NexusFilterError("Output paths must not overwrite an input file.")

    try:
        text = nexus.read_text(encoding="utf-8")
    except OSError as exc:
        raise NexusFilterError(f"Cannot open NEXUS file '{nexus}': {exc}") from exc

    regions = load_regions(regions_file)
    filtered, counts_text, result = filter_nexus_text(
        text,
        regions,
        position_pattern=position_pattern,
        allow_unparsed=allow_unparsed,
        update_dimension=update_dimension,
    )

    report_text = None
    if report is not None:
        report_text = _run_report(
            nexus=nexus,
            regions=regions_file,
            output=output,
            counts=counts,
            filtered_text=filtered,
            counts_text=counts_text,
            result=result,
            position_pattern=position_pattern,
            allow_unparsed=allow_unparsed,
            update_dimension=update_dimension,
        )

    for destination in destinations:
        if destination.exists() and not force:
            raise NexusFilterError(
                f"Output file already exists: '{destination}'. Use --force to replace it."
            )

    _write_atomic(output, filtered, force=force)
    _write_atomic(counts, counts_text, force=force)
    if report is not None and report_text is not None:
        _write_atomic(report, report_text, force=force)
    return result
