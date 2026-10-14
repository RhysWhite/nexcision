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

    try:
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
    except UnicodeError as exc:
        raise NexusFilterError(
            f"Cannot decode regions file '{region_path}' as UTF-8: {exc}"
        ) from exc

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


def _parse_coordinate_label(
    line: str, pattern: Pattern[str]
) -> tuple[int, str] | None:
    """Return the coordinate and non-coordinate part of a matrix row label.

    The latter is used to detect incompatible reference identifiers. It is
    deliberately derived from the configured capture group, so custom
    coordinate expressions follow the same rule as the default expression.
    """

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

    reference_label = token[:match.start(1)] + token[match.end(1):]
    return position, reference_label


def extract_position(line: str, pattern: Pattern[str]) -> int | None:
    """Extract a genomic coordinate from the first matrix token."""
    parsed = _parse_coordinate_label(line, pattern)
    return None if parsed is None else parsed[0]


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


class _NexusScanner:
    """Recognize nested NEXUS comments and quoted text without changing input.

    ``visible`` masks comments but retains quoted data; ``syntax`` also masks
    quoted text so keywords and semicolons in either cannot be mistaken for
    commands. Character offsets are identical to the original line.
    """

    def __init__(self) -> None:
        self.comment_depth = 0
        self.quote: str | None = None

    def scan(self, line: str, line_number: int) -> tuple[str, str, str | None]:
        # Typical SPANDx matrix rows contain no lexical metacharacters. Keep
        # their parsing on the original fast path, without a character loop.
        if (
            not self.comment_depth
            and self.quote is None
            and not any(char in line for char in "[]'\"")
        ):
            return line, line, None

        visible = list(line)
        syntax = list(line)
        comments: list[str] | None = None

        index = 0
        while index < len(line):
            char = line[index]
            blank = char if char in "\r\n" else " "
            if self.comment_depth:
                if comments is None:
                    comments = [c if c in "\r\n" else " " for c in line]
                comments[index] = char
                visible[index] = blank
                syntax[index] = blank
                if char == "[":
                    self.comment_depth += 1
                elif char == "]":
                    self.comment_depth -= 1
            elif self.quote is not None:
                syntax[index] = blank
                if char == self.quote:
                    if index + 1 < len(line) and line[index + 1] == char:
                        # Two consecutive quote characters represent one
                        # literal quote, not the end of the quoted string.
                        index += 1
                        syntax[index] = " "
                    else:
                        self.quote = None
            elif char == "[":
                self.comment_depth = 1
                if comments is None:
                    comments = [c if c in "\r\n" else " " for c in line]
                comments[index] = char
                visible[index] = blank
                syntax[index] = blank
            elif char == "]":
                raise NexusFilterError(
                    f"Unmatched NEXUS comment closing bracket on line {line_number}."
                )
            elif char in "'\"":
                self.quote = char
                syntax[index] = blank
            index += 1

        return (
            "".join(visible),
            "".join(syntax),
            None if comments is None else "".join(comments),
        )

    def finish(self) -> None:
        if self.comment_depth:
            raise NexusFilterError("Unterminated NEXUS bracket comment.")
        if self.quote is not None:
            raise NexusFilterError("Unterminated NEXUS quoted string.")


def _nexus_syntax(text: str) -> str:
    """Return text with comments and quoted strings masked in-place."""

    scanner = _NexusScanner()
    masked = [
        scanner.scan(line, index)[1]
        for index, line in enumerate(text.splitlines(keepends=True), start=1)
    ]
    scanner.finish()
    return "".join(masked)


def _matrix_is_transposed(syntax_prefix: str) -> bool:
    """Return whether the last relevant FORMAT command declares TRANSPOSE."""

    format_commands = re.findall(r"(?is)\bformat\b(.*?);", syntax_prefix)
    for command in reversed(format_commands):
        if not re.search(r"(?i)\btranspose\b", command):
            continue
        disabled = re.search(
            r"(?i)\btranspose\s*=\s*(?:no|false|0)\b", command
        )
        return disabled is None
    return False


# The rows in the supported transposed matrix model are characters, so
# excision changes their numerical positions. These NEXUS statements can
# define positional metadata that cannot safely be left untouched. This is
# deliberately a conservative allow-list *of hazards*, not a general NEXUS
# grammar or an attempt to renumber external definitions.
_CHARACTER_INDEXED_COMMANDS = frozenset(
    {
        "charset",
        "charpartition",
        "charlabels",
        "charstatelabels",
        "statelabels",
        "eliminate",
        "exset",
        "wtset",
        "typeset",
        "ancstates",
        "codonposset",
        "codeset",
        "charweights",
    }
)

# When rows represent taxa rather than characters, linked taxon definitions
# may also become stale. TRANSPOSE is determined from the input declaration,
# not from the user-selected dimension-update override.
_TAXON_INDEXED_COMMANDS = frozenset(
    {
        "taxset",
        "taxpartition",
        "taxlabels",
        "translate",
        "tree",
        "utree",
    }
)


def _reject_indexed_metadata(
    lines: Sequence[str],
    matrix_start: int,
    matrix_end: int,
    matrix_terminator: int,
) -> None:
    """Fail closed on known position-linked commands when rows are removed.

    Only commands outside MATRIX are examined. Masking comments and quoted
    strings before splitting real semicolon-delimited statements prevents
    matching textual mentions of a command and quoted semicolons. This check
    intentionally does not purport to validate arbitrary NEXUS extensions.
    """

    prefix = "".join(lines[:matrix_start])
    suffix = (
        lines[matrix_end][matrix_terminator + 1 :]
        + "".join(lines[matrix_end + 1 :])
    )
    syntax = _nexus_syntax(prefix + "\n" + suffix)
    # NEXUS's magic header is not itself a semicolon-terminated command.
    syntax = re.sub(r"(?im)^\s*#nexus\b", "", syntax, count=1)
    changed_taxa = not _matrix_is_transposed(_nexus_syntax(prefix))
    hazardous = _CHARACTER_INDEXED_COMMANDS
    if changed_taxa:
        hazardous = hazardous | _TAXON_INDEXED_COMMANDS

    for statement in syntax.split(";"):
        match = re.match(r"\s*([A-Za-z][A-Za-z0-9_]*)\b", statement)
        if match is None:
            continue
        command = match.group(1).lower()
        if command in hazardous:
            raise NexusFilterError(
                f"NEXUS {command.upper()} metadata may contain character- or "
                "taxon-indexed references that become invalid after matrix-row "
                "excision. NEXCISION cannot safely renumber these definitions; "
                "remove or rebuild the linked metadata before filtering. "
                "No output was written."
            )


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
    # Comment text such as [nchar=99] must never count as a declaration.
    # Keeping original offsets permits changing only the true numeric value.
    syntax_prefix = _nexus_syntax(prefix)
    suffix = "".join(lines[matrix_start_index:])
    field = _resolve_dimension(policy, syntax_prefix)
    if field is None:
        return lines, None, None, None, None

    matches = list(re.finditer(rf"(?i)\b{field}\s*=\s*(\d+)", syntax_prefix))
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

    value_span = matches[0].span(1)
    replacement = prefix[:value_span[0]] + str(kept_rows) + prefix[value_span[1]:]
    updated = (replacement + suffix).splitlines(keepends=True)
    return updated, field, declared, kept_rows, None


def _write_outputs_atomically(
    outputs: Sequence[tuple[Path, str]],
    *,
    force: bool,
) -> None:
    """Stage and commit all outputs as one failure-safe operation.

    Every file is first written to a temporary file in its destination
    directory. No final output is replaced until all temporary files have
    been written successfully. Existing files are backed up when ``force`` is
    used so that an unexpected commit failure can be rolled back.
    """

    resolved = [(path.resolve(), content) for path, content in outputs]
    paths = [path for path, _ in resolved]

    for index, path in enumerate(paths):
        for other in paths[index + 1 :]:
            if path in other.parents or other in path.parents:
                raise NexusFilterError(
                    "Output paths must not be nested within one another."
                )

    for path in paths:
        if path.exists():
            if path.is_dir():
                raise NexusFilterError(f"Output path is a directory: '{path}'.")
            if not force:
                raise NexusFilterError(
                    f"Output file already exists: '{path}'. Use --force to replace it."
                )

        parent = path.parent
        if parent.exists() and not parent.is_dir():
            raise NexusFilterError(
                f"Output parent path is not a directory: '{parent}'."
            )

    staged: list[tuple[Path, Path]] = []
    backups: dict[Path, Path] = {}
    committed: list[Path] = []

    try:
        # Stage every output before touching any final destination.
        for path, content in resolved:
            path.parent.mkdir(parents=True, exist_ok=True)
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
                staged.append((Path(handle.name), path))

        # Move existing files aside so a failed forced replacement can roll back.
        if force:
            for path in paths:
                if not path.exists():
                    continue
                descriptor, backup_name = tempfile.mkstemp(
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    suffix=".bak",
                )
                os.close(descriptor)
                backup = Path(backup_name)
                backup.unlink()
                os.replace(path, backup)
                backups[path] = backup

        for temporary, path in staged:
            os.replace(temporary, path)
            committed.append(path)

    except OSError as exc:
        for temporary, _path in staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

        for path in committed:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

        for path, backup in backups.items():
            if backup.exists():
                try:
                    os.replace(backup, path)
                except OSError:
                    pass

        target_list = ", ".join(str(path) for path in paths)
        raise NexusFilterError(
            f"Cannot write output files ({target_list}): {exc}"
        ) from exc

    else:
        for backup in backups.values():
            try:
                backup.unlink()
            except FileNotFoundError:
                pass


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
    allow_empty: bool = False,
    update_dimension: DimensionPolicy = "auto",
) -> tuple[str, str, FilterResult]:
    """Filter coordinate-labelled rows from one NEXUS MATRIX block."""

    if not regions:
        raise NexusFilterError("At least one region is required.")

    pattern = compile_position_pattern(position_pattern)
    starts, merged_regions = _merge_regions(regions)
    lines = text.splitlines(keepends=True)

    # Find real standalone MATRIX commands, excluding identical words within
    # NEXUS comments and quoted strings. Scan once to catch malformed quotes
    # and comments anywhere in the input, including after the MATRIX block.
    locator = _NexusScanner()
    matrix_indices: list[int] = []
    active_block: str | None = None
    # MATRIX is also a legitimate command in non-character NEXUS blocks,
    # notably DISTANCES. Only DATA/CHARACTERS matrices are site matrices.
    block_boundary = re.compile(
        r"(?i)\bbegin\s+([A-Za-z][A-Za-z0-9_-]*)\s*;|\bend(?:block)?\s*;"
    )
    for index, line in enumerate(lines):
        _visible, syntax, _comments = locator.scan(line, index + 1)
        for boundary in block_boundary.finditer(syntax):
            active_block = boundary.group(1).lower() if boundary.group(1) else None
        if syntax.strip().lower() == "matrix" and active_block in {
            None, "data", "characters"
        }:
            matrix_indices.append(index)
    locator.finish()

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
    matrix_end = -1
    matrix_terminator = -1
    parsed_rows = 0
    rows_removed = 0
    parsed_rows_kept = 0
    unparsed_rows = 0
    removed_positions: list[int] = []
    reference_label: str | None = None
    scanner = _NexusScanner()

    for index in range(matrix_start + 1, len(lines)):
        line = lines[index]
        if not in_matrix:
            output_lines.append(line)
            continue

        visible, syntax, comments = scanner.scan(line, index + 1)
        semicolon = syntax.find(";")
        content = visible[:semicolon] if semicolon >= 0 else visible

        if semicolon >= 0 and syntax[:semicolon].strip().lower() in {"end", "endblock"}:
            raise NexusFilterError(
                "The MATRIX block is not terminated before the enclosing block ends."
            )

        if not content.strip():
            output_lines.append(line)
            if semicolon >= 0:
                in_matrix = False
                terminated = True
                matrix_end = index
                matrix_terminator = semicolon
            continue

        parsed = _parse_coordinate_label(content, pattern)
        if parsed is None:
            unparsed_rows += 1
            if not allow_unparsed:
                raise NexusFilterError(
                    f"Matrix line {index + 1} does not match the position pattern: "
                    f"{content.strip()!r}. Use --allow-unparsed to preserve it."
                )
            output_lines.append(line)
            if semicolon >= 0:
                in_matrix = False
                terminated = True
                matrix_end = index
                matrix_terminator = semicolon
            continue

        position, row_reference_label = parsed
        if reference_label is None:
            reference_label = row_reference_label
        elif row_reference_label != reference_label:
            raise NexusFilterError(
                f"Matrix line {index + 1} uses reference label "
                f"{row_reference_label!r}, but an earlier row uses "
                f"{reference_label!r}. Region intervals specify coordinates "
                "only; mixed reference coordinate axes cannot be filtered safely."
            )

        parsed_rows += 1
        if _is_excluded(position, starts, merged_regions):
            rows_removed += 1
            removed_positions.append(position)
            # Comments attached to an excised row remain in their original
            # order. Preserve the actual MATRIX terminator and everything
            # following it, not a semicolon inside a bracket comment.
            if semicolon >= 0:
                output_lines.append(
                    (comments[:semicolon] if comments is not None else "")
                    + line[semicolon:]
                )
            elif comments is not None:
                output_lines.append(comments)
        else:
            parsed_rows_kept += 1
            output_lines.append(line)

        if semicolon >= 0:
            in_matrix = False
            terminated = True
            matrix_end = index
            matrix_terminator = semicolon

    if not terminated:
        raise NexusFilterError("The MATRIX block is not terminated by a semicolon.")
    if parsed_rows == 0:
        raise NexusFilterError(
            "No coordinate-labelled rows were parsed from the MATRIX block."
        )

    matrix_rows = parsed_rows + unparsed_rows
    rows_kept = parsed_rows_kept + unparsed_rows
    if rows_kept == 0 and not allow_empty:
        raise NexusFilterError(
            f"Filtering would remove all {matrix_rows} matrix rows. "
            "No output was written. Use --allow-empty to create an empty "
            "matrix intentionally."
        )

    if rows_removed:
        _reject_indexed_metadata(lines, matrix_start, matrix_end, matrix_terminator)

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
    allow_empty: bool,
    update_dimension: DimensionPolicy,
) -> str:
    payload = {
        "software": {"name": "NEXCISION", "version": VERSION},
        "inputs": {
            "nexus": {"path": str(nexus), "sha256": _sha256_file(nexus)},
            "regions": {"path": str(regions), "sha256": _sha256_file(regions)},
        },
        "parameters": {
            "allow_empty": allow_empty,
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
    allow_empty: bool = False,
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
        # Path.read_text() uses universal-newline translation and silently
        # converts CRLF/CR to LF. Preserve the original UTF-8 line endings so
        # unchanged NEXUS rows and surrounding content stay byte-identical.
        with nexus.open("r", encoding="utf-8", newline="") as handle:
            text = handle.read()
    except (OSError, UnicodeError) as exc:
        raise NexusFilterError(f"Cannot open NEXUS file '{nexus}': {exc}") from exc

    regions = load_regions(regions_file)
    filtered, counts_text, result = filter_nexus_text(
        text,
        regions,
        position_pattern=position_pattern,
        allow_unparsed=allow_unparsed,
        allow_empty=allow_empty,
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
            allow_empty=allow_empty,
            update_dimension=update_dimension,
        )

    output_contents: list[tuple[Path, str]] = [
        (output, filtered),
        (counts, counts_text),
    ]
    if report is not None and report_text is not None:
        output_contents.append((report, report_text))

    _write_outputs_atomically(output_contents, force=force)
    return result
