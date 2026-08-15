# NEXCISION code walkthrough

This document explains the NEXCISION v0.1.1 implementation in plain English. It is intended for readers who want to audit what the program does without needing to be experienced Python programmers.

The walkthrough follows the actual source files in `src/nexcision/` and the command-line entry point declared in `pyproject.toml`. Line numbers refer to the v0.1.1 source snapshot. Blank lines are omitted from the explanation because they do not change program behaviour.

## 1. What happens when you type `nexcise`?

The complete execution path is:

```text
nexcise input.nex regions.tsv ...
        |
        v
pyproject.toml -> nexcision.cli:main
        |
        v
cli.py -> parse command-line arguments
        |
        v
core.py -> filter_nexus_file(...)
        |
        +--> read NEXUS file
        +--> load and validate regions
        +--> filter_nexus_text(...)
        |       +--> locate MATRIX block
        |       +--> extract row coordinates
        |       +--> test coordinates against regions
        |       +--> remove matching rows
        |       +--> update the appropriate dimension
        |       +--> build per-region counts
        |
        +--> optionally build JSON provenance report
        +--> stage all requested outputs
        +--> commit outputs
        |
        v
cli.py -> print run summary and exit status
```

The important separation is that `cli.py` handles the command-line interface, while `core.py` contains the filtering and file-safety logic.

---

## 2. Package entry points and version information

### `pyproject.toml`: installed command

The installed command is declared as:

```toml
[project.scripts]
nexcise = "nexcision.cli:main"
```

This tells Python packaging tools to create a command named `nexcise`. When that command is run, Python imports the `nexcision.cli` module and calls its `main()` function.

### `src/nexcision/_version.py`

[Source](https://github.com/RhysWhite/nexcision/blob/main/src/nexcision/_version.py)

```python
1  """Single source of truth for the NEXCISION version."""
3  VERSION = "0.1.1"
```

- **Line 1** is a module-level documentation string: a human-readable description of the file.
- **Line 3** stores the software version in one constant named `VERSION`.

The command-line `--version` output and the JSON provenance report both ultimately use this value.

### `src/nexcision/__init__.py`

[Source](https://github.com/RhysWhite/nexcision/blob/main/src/nexcision/__init__.py)

```python
1   """NEXCISION: precise region-based excision from NEXUS matrices."""
3   from ._version import VERSION as __version__
4   from .core import (
5       FilterResult,
6       NexusFilterError,
7       Region,
8       filter_nexus_file,
9       filter_nexus_text,
10      load_regions,
11  )
13  __all__ = [
14      "FilterResult",
15      "NexusFilterError",
16      "Region",
17      "filter_nexus_file",
18      "filter_nexus_text",
19      "load_regions",
20  ]
```

- **Line 3** imports `VERSION` and exposes it as `nexcision.__version__`.
- **Lines 4–11** import the main public classes and functions from `core.py` so users can import them directly from the `nexcision` package.
- **Lines 13–20** define the names considered the package's public API when code uses `from nexcision import *`.

No filtering happens in this file.

### `src/nexcision/__main__.py`

[Source](https://github.com/RhysWhite/nexcision/blob/main/src/nexcision/__main__.py)

```python
1  """Run NEXCISION with ``python -m nexcision``."""
3  from .cli import main
5  raise SystemExit(main())
```

- **Line 3** imports the same `main()` function used by the installed `nexcise` command.
- **Line 5** runs `main()` and converts its returned integer into the process exit status.

This is why `python -m nexcision ...` and `nexcise ...` use the same program logic.

---

## 3. Command-line interface: `cli.py`

[Full source](https://github.com/RhysWhite/nexcision/blob/main/src/nexcision/cli.py)

### Lines 1–10: imports

```python
1   """Command-line interface for NEXCISION."""
3   from __future__ import annotations
5   import argparse
6   import sys
7   from pathlib import Path
9   from . import __version__
10  from .core import DEFAULT_POSITION_PATTERN, NexusFilterError, filter_nexus_file
```

- **Line 1** describes the module.
- **Line 3** postpones evaluation of type annotations. This is a Python compatibility/convenience feature; it does not alter filtering.
- **Line 5** imports `argparse`, Python's standard-library command-line parser.
- **Line 6** imports `sys`, used here to write errors and warnings to standard error.
- **Line 7** imports `Path`, Python's object for filesystem paths.
- **Line 9** imports the NEXCISION version.
- **Line 10** imports the default coordinate pattern, the program's controlled error type, and the file-level filtering function.

NEXCISION has no third-party runtime dependency here: all imported modules other than NEXCISION's own files are from the Python standard library.

### Lines 13–20: create the parser

```python
13  def build_parser() -> argparse.ArgumentParser:
14      parser = argparse.ArgumentParser(
15          prog="nexcise",
16          description=(
17              "Excise coordinate-labelled NEXUS matrix rows that overlap "
18              "1-based inclusive genomic regions."
19          ),
20      )
```

- **Line 13** defines a function called `build_parser()` that will construct and return the command-line parser.
- **Line 14** creates the parser.
- **Line 15** sets the command name shown in help text to `nexcise`.
- **Lines 16–19** provide the description shown by `nexcise --help`.

### Lines 21–26: required input files

```python
21  parser.add_argument("nexus", type=Path, help="Input NEXUS file.")
22  parser.add_argument(
23      "regions",
24      type=Path,
25      help="Whitespace-delimited start/end regions file.",
26  )
```

These are positional arguments, so both are required:

1. `nexus` — the input NEXUS file;
2. `regions` — the genomic interval file.

`type=Path` converts the text supplied on the command line into `Path` objects.

### Lines 27–47: output paths

```python
27  parser.add_argument(
28      "-o",
29      "--output",
30      type=Path,
31      default=Path("filtered.nex"),
32      help="Filtered NEXUS output (default: filtered.nex).",
33  )
34  parser.add_argument(
35      "--counts",
36      type=Path,
37      default=Path("removed_counts_per_region.tsv"),
38      help=(
39          "Per-region removal counts "
40          "(default: removed_counts_per_region.tsv)."
41      ),
42  )
43  parser.add_argument(
44      "--report",
45      type=Path,
46      help="Optional deterministic JSON report with checksums and run parameters.",
47  )
```

- **Lines 27–33** define the filtered NEXUS output. If not supplied, it is `filtered.nex`.
- **Lines 34–42** define the per-region count output. Its default is `removed_counts_per_region.tsv`.
- **Lines 43–47** define an optional JSON report. There is no default report path, so no JSON report is written unless `--report` is supplied.

### Lines 48–57: coordinate regular expression

```python
48  parser.add_argument(
49      "--position-regex",
50      default=DEFAULT_POSITION_PATTERN,
51      metavar="REGEX",
52      help=(
53          "Regex applied to the first matrix token. It must contain exactly one "
54          "coordinate capture group "
55          f"(default: {DEFAULT_POSITION_PATTERN!r})."
56      ),
57  )
```

This option controls how NEXCISION extracts the genomic coordinate from the first token of each matrix row.

The default pattern, defined in `core.py`, is:

```text
_(\d+)$
```

In ordinary language: find an underscore, followed by one or more digits, at the end of the first token, and capture the digits as the coordinate.

For example:

```text
CP013831_180
```

produces coordinate `180`.

### Lines 58–70: explicit safety opt-ins

```python
58  parser.add_argument(
59      "--allow-unparsed",
60      action="store_true",
61      help="Preserve non-comment matrix rows that do not match --position-regex.",
62  )
63  parser.add_argument(
64      "--allow-empty",
65      action="store_true",
66      help=(
67          "Permit filtering to remove every matrix row and produce nchar=0 "
68          "(disabled by default)."
69      ),
70  )
```

`action="store_true"` means each option is `False` unless the user explicitly includes the flag.

- `--allow-unparsed` permits a matrix row that cannot be assigned a coordinate to survive unchanged. Without it, such a row causes an error.
- `--allow-empty` permits every matrix row to be removed. Without it, NEXCISION refuses to create an empty matrix.

These are opt-ins rather than defaults because both behaviours weaken normal validation assumptions.

### Lines 71–79: dimension policy

```python
71  parser.add_argument(
72      "--update-dimension",
73      choices=("auto", "ntax", "nchar", "none"),
74      default="auto",
75      help=(
76          "Dimension field to update after filtering. auto selects nchar when "
77          "FORMAT declares TRANSPOSE and ntax otherwise (default: auto)."
78      ),
79  )
```

Only four values are accepted:

- `auto` — infer the row dimension from whether the matrix is declared `TRANSPOSE`;
- `ntax` — explicitly update `ntax`;
- `nchar` — explicitly update `nchar`;
- `none` — do not update either field.

The default is `auto`.

### Lines 80–89: overwrite and version options

```python
80  parser.add_argument(
81      "--force",
82      action="store_true",
83      help="Replace existing output files.",
84  )
85  parser.add_argument(
86      "--version",
87      action="version",
88      version=f"NEXCISION {__version__}",
89  )
```

- `--force` is `False` by default. Existing output files therefore block the run unless replacement is explicitly requested.
- `--version` prints the version imported from `_version.py` and exits.

### Line 90: return the parser

```python
90  return parser
```

The fully configured parser is returned to the caller.

### Lines 93–94: start a run and parse arguments

```python
93  def main(argv: list[str] | None = None) -> int:
94      args = build_parser().parse_args(argv)
```

- **Line 93** defines the main command-line function. The `-> int` annotation says it returns an integer exit code.
- **Line 94** builds the parser and converts the user's command-line text into named values such as `args.nexus`, `args.output`, and `args.allow_empty`.

When `argv` is `None`, `argparse` reads the actual command line supplied to the process.

### Lines 96–108: hand validated arguments to the core

```python
96      try:
97          result = filter_nexus_file(
98              args.nexus,
99              args.regions,
100             args.output,
101             args.counts,
102             report_path=args.report,
103             position_pattern=args.position_regex,
104             allow_unparsed=args.allow_unparsed,
105             allow_empty=args.allow_empty,
106             update_dimension=args.update_dimension,
107             force=args.force,
108         )
```

This is the hand-off from the interface to the actual filtering logic.

Every relevant command-line option is passed explicitly to `filter_nexus_file()`.

`try:` means the following operation is allowed to raise a controlled error that will be handled immediately below.

### Lines 109–111: controlled failure

```python
109  except NexusFilterError as exc:
110      print(f"ERROR: {exc}", file=sys.stderr)
111      return 2
```

If core logic raises `NexusFilterError`:

- the message is printed to standard error with an `ERROR:` prefix;
- `main()` returns exit code `2`.

This gives shell scripts and workflow managers a non-zero status that indicates failure.

### Lines 113–130: successful run summary

```python
113  print(f"Regions loaded: {result.regions_loaded}")
114  print(f"Matrix rows read: {result.matrix_rows_read}")
115  print(f"Rows removed: {result.rows_removed}")
116  print(f"Rows kept: {result.rows_kept}")
117  print(f"Unparsed rows preserved: {result.unparsed_rows}")
118  if result.dimension_updated is None:
119      print("Dimension updated: no")
120  else:
121      print(
122          f"Dimension updated: {result.dimension_updated} "
123          f"({result.dimension_before} -> {result.dimension_after})"
124      )
125  print(f"Filtered NEXUS: {args.output}")
126  print(f"Region counts: {args.counts}")
127  if args.report is not None:
128      print(f"Run report: {args.report}")
129  for warning in result.warnings:
130      print(f"WARNING: {warning}", file=sys.stderr)
```

These lines do not change the files. They report what has already happened.

- **Lines 113–117** print counts from the returned `FilterResult`.
- **Lines 118–124** state whether a NEXUS dimension was updated and, if so, show the old and new values.
- **Lines 125–128** print output paths.
- **Lines 129–130** print any non-fatal warnings to standard error.

### Line 132: successful exit

```python
132  return 0
```

Exit code `0` indicates successful completion.

---

## 4. Core implementation: `core.py`

[Full source](https://github.com/RhysWhite/nexcision/blob/main/src/nexcision/core.py)

`core.py` contains the input validation, coordinate parsing, filtering, dimension correction, count generation, checksum generation, report construction, and output-write logic.

## 4.1 Lines 1–18: imports and constants

```python
1   """Core filtering logic for NEXCISION."""
3   from __future__ import annotations
5   import bisect
6   import hashlib
7   import json
8   import os
9   import re
10  import tempfile
11  from dataclasses import asdict, dataclass
12  from pathlib import Path
13  from typing import Iterable, Literal, Pattern, Sequence
15  from ._version import VERSION
17  DEFAULT_POSITION_PATTERN = r"_(\d+)$"
18  DimensionPolicy = Literal["auto", "ntax", "nchar", "none"]
```

The standard-library modules have specific jobs:

- `bisect` — fast searches in sorted coordinate/interval lists;
- `hashlib` — SHA-256 checksums;
- `json` — JSON report serialization;
- `os` — filesystem replacement operations;
- `re` — regular expressions;
- `tempfile` — temporary staging and backup files;
- `dataclasses` — compact structured records;
- `Path` — filesystem paths;
- `typing` — type annotations.

**Line 17** defines the default row-coordinate regular expression.

**Line 18** documents that the dimension policy is expected to be one of exactly four strings. `Literal` is primarily a type-checking aid; `_resolve_dimension()` also validates the value at runtime.

## 4.2 Lines 21–47: controlled errors and data records

```python
21  class NexusFilterError(ValueError):
22      """Raised when NEXCISION cannot filter an input safely."""
```

`NexusFilterError` is the program's own controlled exception type. The CLI specifically catches this error and returns exit status `2`.

```python
25  @dataclass(frozen=True)
26  class Region:
27      """A 1-based, inclusive genomic interval."""
29      region_id: int
30      start: int
31      end: int
32      name: str
```

A `Region` stores four values:

- sequential ID;
- inclusive start coordinate;
- inclusive end coordinate;
- name.

`@dataclass` makes Python generate routine constructor/comparison methods. `frozen=True` prevents fields from being reassigned after a `Region` is created.

```python
35  @dataclass(frozen=True)
36  class FilterResult:
37      """Summary returned after filtering."""
39      regions_loaded: int
40      matrix_rows_read: int
41      rows_removed: int
42      rows_kept: int
43      unparsed_rows: int
44      dimension_updated: str | None
45      dimension_before: int | None
46      dimension_after: int | None
47      warnings: tuple[str, ...]
```

`FilterResult` is the structured summary returned by filtering. `str | None` and `int | None` mean the value may be absent (`None`) when no dimension update occurred.

---

## 5. Reading and validating genomic regions

### `load_regions()` — lines 50–110

```python
50  def load_regions(path: str | Path) -> list[Region]:
51      """Load 1-based, inclusive regions from a whitespace-delimited file.
52
53      The first two columns are integer start and end coordinates. A third column
54      may provide a region name. Blank lines, ``#`` comments, and a header whose
55      first field is ``start`` are ignored.
56      """
```

The function accepts either a string path or a `Path` and returns a list of `Region` records.

```python
58  regions: list[Region] = []
59  region_path = Path(path)
```

- **Line 58** starts an empty list that will hold validated regions.
- **Line 59** normalizes the supplied path into a `Path` object.

```python
61  try:
62      handle = region_path.open("r", encoding="utf-8")
63  except OSError as exc:
64      raise NexusFilterError(
65          f"Cannot open regions file '{region_path}': {exc}"
66      ) from exc
```

NEXCISION opens the file explicitly as UTF-8 text. Filesystem failures are converted into `NexusFilterError` so the CLI can report them consistently.

```python
68  try:
69      with handle:
70          for line_number, raw_line in enumerate(handle, start=1):
71              line = raw_line.strip()
72              if not line or line.startswith("#"):
73                  continue
```

- `with handle` ensures the file is closed afterwards.
- `enumerate(..., start=1)` tracks human-readable line numbers beginning at 1.
- `.strip()` removes surrounding whitespace.
- blank lines and `#` comment lines are skipped.

```python
75  fields = re.split(r"\s+", line)
76  if fields[0].lower() == "start":
77      continue
78  if len(fields) < 2:
79      raise NexusFilterError(
80          f"Regions file line {line_number} must contain start and end."
81      )
```

- **Line 75** splits on one or more whitespace characters, so spaces or tabs both work.
- **Lines 76–77** skip a header whose first field is `start`, case-insensitively.
- **Lines 78–81** reject lines that do not contain at least a start and end value.

```python
83  try:
84      start = int(fields[0])
85      end = int(fields[1])
86  except ValueError as exc:
87      raise NexusFilterError(
88          f"Regions file line {line_number} has non-integer coordinates: "
89          f"{line!r}"
90      ) from exc
```

The first two fields must convert to integers. Non-integer coordinates stop the run with a line-specific error.

```python
92  if start < 1 or end < 1:
93      raise NexusFilterError(
94          f"Regions file line {line_number} contains a coordinate below 1."
95      )
96  if start > end:
97      start, end = end, start
```

- Coordinates below 1 are invalid because NEXCISION uses 1-based genomic coordinates.
- Reversed intervals are normalized by swapping the two values.

Thus an input interval `260 170` becomes `170 260` rather than failing.

```python
99   region_id = len(regions) + 1
100  name = fields[2] if len(fields) >= 3 else f"region_{region_id}"
101  regions.append(Region(region_id, start, end, name))
```

- IDs are assigned in input order starting at 1.
- The third field is used as the name if present.
- Otherwise NEXCISION generates names such as `region_1`.
- The validated region is appended to the list.

```python
102  except UnicodeError as exc:
103      raise NexusFilterError(
104          f"Cannot decode regions file '{region_path}' as UTF-8: {exc}"
105      ) from exc
```

If UTF-8 decoding fails while reading, NEXCISION converts that failure to a controlled error rather than continuing with corrupted text.

```python
107  if not regions:
108      raise NexusFilterError(f"No valid regions were found in '{region_path}'.")
110  return regions
```

An empty regions list is not accepted. Otherwise the fully validated list is returned.

---

## 6. Compiling and applying the coordinate pattern

### `compile_position_pattern()` — lines 113–125

```python
113  def compile_position_pattern(pattern: str = DEFAULT_POSITION_PATTERN) -> Pattern[str]:
114      """Compile and validate a coordinate-extraction regular expression."""
116      try:
117          compiled = re.compile(pattern)
118      except re.error as exc:
119          raise NexusFilterError(f"Invalid position regular expression: {exc}") from exc
```

The user-supplied or default regular expression is compiled. Invalid regex syntax becomes a controlled NEXCISION error.

```python
121  if compiled.groups != 1:
122      raise NexusFilterError(
123          "The position regular expression must contain exactly one capture group."
124      )
125  return compiled
```

NEXCISION requires exactly one capture group because that group is interpreted as the genomic coordinate. A pattern with zero or multiple capture groups is rejected.

### `extract_position()` — lines 128–151

```python
128  def extract_position(line: str, pattern: Pattern[str]) -> int | None:
129      """Extract a genomic coordinate from the first matrix token."""
131      stripped = line.strip()
132      if not stripped:
133          return None
```

Whitespace is removed. An empty line has no coordinate and returns `None`.

```python
135  token = stripped.split(maxsplit=1)[0].strip("'\"")
136  match = pattern.search(token)
137  if match is None:
138      return None
```

- Only the first whitespace-delimited token is examined.
- Surrounding single or double quotes are removed from that token.
- The coordinate regex is searched against that token.
- No regex match returns `None`.

For:

```text
CP013831_180    1101
```

only `CP013831_180` is examined.

```python
140  try:
141      position = int(match.group(1))
142  except ValueError as exc:
143      raise NexusFilterError(
144          f"Position pattern captured a non-integer value from token '{token}'."
145      ) from exc
```

The single capture group is converted to an integer. A regex that captures non-numeric text therefore fails explicitly.

```python
147  if position < 1:
148      raise NexusFilterError(
149          f"Position pattern captured a coordinate below 1 from token '{token}'."
150      )
151  return position
```

Coordinates below 1 are rejected. Otherwise the integer coordinate is returned.

---

## 7. Preparing intervals for efficient row removal

### `_merge_regions()` — lines 154–168

The leading underscore in `_merge_regions` is a Python convention meaning "internal helper" rather than part of the public API.

```python
154  def _merge_regions(
155      regions: Sequence[Region],
156  ) -> tuple[list[int], list[tuple[int, int]]]:
157      intervals = sorted((region.start, region.end) for region in regions)
158      merged: list[tuple[int, int]] = []
```

The original regions are converted to `(start, end)` pairs and sorted by coordinate. A new list will hold a merged representation used only for deciding whether a row is removed.

```python
160  for start, end in intervals:
161      if not merged or start > merged[-1][1] + 1:
162          merged.append((start, end))
163      else:
164          previous_start, previous_end = merged[-1]
165          merged[-1] = (previous_start, max(previous_end, end))
```

For each interval:

- if it is separated from the previous merged interval by at least one coordinate, it starts a new merged interval;
- if it overlaps or directly touches the previous interval, they are combined.

For example:

```text
100-150
140-200
201-220
```

becomes one internal removal interval:

```text
100-220
```

This does **not** destroy the original region definitions used for the per-region count table. It only makes the yes/no removal lookup efficient and ensures a matrix row is removed once even if several supplied regions cover it.

```python
167  starts = [start for start, _ in merged]
168  return starts, merged
```

A separate sorted list of interval starts is created for binary searching. Both structures are returned.

### `_is_excluded()` — lines 171–177

```python
171  def _is_excluded(
172      position: int,
173      starts: Sequence[int],
174      intervals: Sequence[tuple[int, int]],
175  ) -> bool:
176      index = bisect.bisect_right(starts, position) - 1
177      return index >= 0 and position <= intervals[index][1]
```

This answers one question: **does this genomic coordinate fall inside any merged exclusion interval?**

`bisect_right()` finds the rightmost interval start that is not greater than the position. NEXCISION then checks whether the position is also no greater than that interval's inclusive end.

Example with merged interval `170-260`:

- position `169` -> `False`;
- position `170` -> `True`;
- position `180` -> `True`;
- position `260` -> `True`;
- position `261` -> `False`.

This is the exact point where 1-based inclusive region membership is applied.

---

## 8. Recognizing blank/comment rows and matrix orientation

### `_is_comment_or_blank()` — lines 180–182

```python
180  def _is_comment_or_blank(content: str) -> bool:
181      stripped = content.strip()
182      return not stripped or stripped.startswith("[")
```

A matrix line is treated as non-data if, after removing surrounding whitespace, it is either empty or starts with `[` (the NEXUS comment form handled here).

Such lines are preserved rather than interpreted as coordinate-labelled rows.

### `_matrix_is_transposed()` — lines 185–196

```python
185  def _matrix_is_transposed(prefix: str) -> bool:
186      """Return whether the last FORMAT command declares TRANSPOSE."""
188      format_commands = re.findall(r"(?is)\bformat\b(.*?);", prefix)
```

All `FORMAT ... ;` commands before the `MATRIX` line are found. The regex flags make matching case-insensitive and allow matching across line breaks.

```python
189  for command in reversed(format_commands):
190      if not re.search(r"(?i)\btranspose\b", command):
191          continue
```

The commands are inspected from last to first. Commands that never mention `TRANSPOSE` are skipped.

```python
192  disabled = re.search(
193      r"(?i)\btranspose\s*=\s*(?:no|false|0)\b", command
194  )
195  return disabled is None
196  return False
```

For the most recent relevant command:

- `transpose=no`, `transpose=false`, or `transpose=0` means not transposed;
- another declaration containing `transpose` is treated as transposed;
- if no preceding `FORMAT` command mentions `transpose`, the result is `False`.

---

## 9. Choosing and updating the NEXUS dimension

### `_resolve_dimension()` — lines 199–208

```python
199  def _resolve_dimension(policy: DimensionPolicy, prefix: str) -> str | None:
200      if policy == "none":
201          return None
202      if policy in {"ntax", "nchar"}:
203          return policy
204      if policy != "auto":
205          raise NexusFilterError(
206              "Dimension policy must be one of: auto, ntax, nchar, none."
207          )
208      return "nchar" if _matrix_is_transposed(prefix) else "ntax"
```

The policy is resolved as follows:

- `none` -> update nothing;
- explicit `ntax` or `nchar` -> use that field;
- anything other than `auto` -> error;
- `auto` -> use `nchar` for a matrix declared transposed, otherwise `ntax`.

### `_update_dimension()` — lines 211–262

```python
211  def _update_dimension(
212      lines: list[str],
213      matrix_start_index: int,
214      original_rows: int,
215      kept_rows: int,
216      policy: DimensionPolicy,
217  ) -> tuple[list[str], str | None, int | None, int | None, str | None]:
218      prefix = "".join(lines[:matrix_start_index])
219      suffix = "".join(lines[matrix_start_index:])
220      field = _resolve_dimension(policy, prefix)
```

The already-filtered text is divided into:

- everything before the `MATRIX` line (`prefix`);
- the `MATRIX` line and everything after it (`suffix`).

The function then decides which dimension field, if any, should be changed.

```python
221  if field is None:
222      return lines, None, None, None, None
```

If the policy is `none`, the content is returned unchanged with no warning.

```python
224  matches = list(re.finditer(rf"(?i)\b{field}\s*=\s*(\d+)", prefix))
225  if not matches:
226      return (
227          lines,
228          None,
229          None,
230          None,
231          f"No {field} field was found before MATRIX; dimensions were unchanged.",
232      )
```

NEXCISION searches the pre-matrix text for declarations such as `ntax=5` or `nchar = 5`. If the selected field is absent, it does **not** guess or insert one; it leaves dimensions unchanged and returns a warning.

```python
233  if len(matches) > 1:
234      return (
235          lines,
236          None,
237          None,
238          None,
239          f"Multiple {field} fields were found before MATRIX; dimensions were "
240          "unchanged.",
241      )
```

Multiple matching declarations are also treated conservatively. NEXCISION leaves them untouched and reports a warning.

```python
243  declared = int(matches[0].group(1))
244  if declared != original_rows:
245      return (
246          lines,
247          None,
248          declared,
249          None,
250          f"Declared {field}={declared} does not match the {original_rows} matrix "
251          "rows; dimensions were unchanged. Use --update-dimension to override "
252          "automatic dimension selection if required.",
253      )
```

Even when there is exactly one selected dimension declaration, NEXCISION changes it only if its existing value equals the number of matrix rows read.

If the declaration and observed row count disagree, the program preserves the declaration and emits a warning instead of assuming which value is correct.

```python
255  replacement = re.sub(
256      rf"(?i)(\b{field}\s*=\s*)\d+",
257      lambda found: f"{found.group(1)}{kept_rows}",
258      prefix,
259      count=1,
260  )
261  updated = (replacement + suffix).splitlines(keepends=True)
262  return updated, field, declared, kept_rows, None
```

When the selected declaration is unambiguous and consistent with the original matrix row count:

- only its numeric value is replaced;
- the surrounding spelling/spacing before the number is preserved;
- only the first match is changed (`count=1`);
- the matrix and following text are reattached;
- the function reports which field changed and its before/after values.

---

## 10. Transactional output writing

### `_write_outputs_atomically()` — lines 265–377

This function is responsible for avoiding a normal run in which one requested output is written successfully but a later output fails, leaving an apparently complete but inconsistent result set.

```python
265  def _write_outputs_atomically(
266      outputs: Sequence[tuple[Path, str]],
267      *,
268      force: bool,
269  ) -> None:
270      """Stage and commit all outputs as one failure-safe operation.
271
272      Every file is first written to a temporary file in its destination
273      directory. No final output is replaced until all temporary files have
274      been written successfully. Existing files are backed up when ``force`` is
275      used so that an unexpected commit failure can be rolled back.
276      """
```

Each `outputs` entry contains a destination path and the complete text to write there.

### Lines 278–286: normalize paths and reject nesting

```python
278  resolved = [(path.resolve(), content) for path, content in outputs]
279  paths = [path for path, _ in resolved]
281  for index, path in enumerate(paths):
282      for other in paths[index + 1 :]:
283          if path in other.parents or other in path.parents:
284              raise NexusFilterError(
285                  "Output paths must not be nested within one another."
286              )
```

Paths are converted to resolved absolute paths. Every pair is checked to ensure one output path is not a parent of another output path.

For example, using `result` as one output and `result/counts.tsv` as another is rejected before writing.

### Lines 288–301: preflight existing paths

```python
288  for path in paths:
289      if path.exists():
290          if path.is_dir():
291              raise NexusFilterError(f"Output path is a directory: '{path}'.")
292          if not force:
293              raise NexusFilterError(
294                  f"Output file already exists: '{path}'. Use --force to replace it."
295              )
297      parent = path.parent
298      if parent.exists() and not parent.is_dir():
299          raise NexusFilterError(
300              f"Output parent path is not a directory: '{parent}'."
301          )
```

Before any output is staged:

- an output path that is a directory is rejected;
- an existing file is rejected unless `force=True`;
- an existing parent path that is not a directory is rejected.

### Lines 303–305: transaction bookkeeping

```python
303  staged: list[tuple[Path, Path]] = []
304  backups: dict[Path, Path] = {}
305  committed: list[Path] = []
```

NEXCISION tracks:

- temporary file -> final destination pairs;
- original file -> backup pairs when forcing replacement;
- final paths already committed during the current transaction.

These lists are needed if a later filesystem operation fails.

### Lines 307–321: stage every output first

```python
307  try:
308      # Stage every output before touching any final destination.
309      for path, content in resolved:
310          path.parent.mkdir(parents=True, exist_ok=True)
311          with tempfile.NamedTemporaryFile(
312              mode="w",
313              encoding="utf-8",
314              newline="",
315              dir=path.parent,
316              prefix=f".{path.name}.",
317              suffix=".tmp",
318              delete=False,
319          ) as handle:
320              handle.write(content)
321              staged.append((Path(handle.name), path))
```

Every requested output is first written completely to a temporary UTF-8 file in the same directory as its eventual destination.

The final destination is not replaced at this stage.

Using the same directory is important because the later `os.replace()` operation occurs within that destination filesystem.

### Lines 323–337: preserve old outputs when `--force` is used

```python
323  # Move existing files aside so a failed forced replacement can roll back.
324  if force:
325      for path in paths:
326          if not path.exists():
327              continue
328          descriptor, backup_name = tempfile.mkstemp(
329              dir=path.parent,
330              prefix=f".{path.name}.",
331              suffix=".bak",
332          )
333          os.close(descriptor)
334          backup = Path(backup_name)
335          backup.unlink()
336          os.replace(path, backup)
337          backups[path] = backup
```

When replacing existing outputs:

1. a unique backup filename is obtained;
2. the temporary placeholder is closed and removed;
3. the existing final file is moved to the backup path with `os.replace()`;
4. the mapping is recorded so it can be restored if needed.

### Lines 339–341: commit staged outputs

```python
339  for temporary, path in staged:
340      os.replace(temporary, path)
341      committed.append(path)
```

Only after **all** outputs have been staged does NEXCISION move the temporary files into their final locations.

Each successful final replacement is recorded in `committed`.

### Lines 343–370: cleanup and rollback after a write failure

```python
343  except OSError as exc:
344      for temporary, _path in staged:
345          try:
346              temporary.unlink()
347          except FileNotFoundError:
348              pass
349          except OSError:
350              pass
```

If a filesystem `OSError` occurs during the transaction, NEXCISION first attempts to remove any temporary staging files that still exist. Cleanup errors are suppressed here so the original write failure remains the primary reported error.

```python
352      for path in committed:
353          try:
354              path.unlink()
355          except FileNotFoundError:
356              pass
357          except OSError:
358              pass
```

Any new final outputs already committed during this attempted transaction are then removed where possible.

```python
360      for path, backup in backups.items():
361          if backup.exists():
362              try:
363                  os.replace(backup, path)
364              except OSError:
365                  pass
```

Any pre-existing output files moved aside under `--force` are then restored where possible. Restoration errors are suppressed so that NEXCISION reports the original transaction failure.

This rollback code is deliberately defensive, but like all filesystem rollback logic it depends on the operating system permitting the cleanup/restoration operations.

```python
367      target_list = ", ".join(str(path) for path in paths)
368      raise NexusFilterError(
369          f"Cannot write output files ({target_list}): {exc}"
370      ) from exc
```

The original filesystem problem is converted into a controlled `NexusFilterError` that names the requested output paths.

### Lines 372–377: successful transaction cleanup

```python
372  else:
373      for backup in backups.values():
374          try:
375              backup.unlink()
376          except FileNotFoundError:
377              pass
```

If no `OSError` occurred during staging, backup creation, or commit, old backup files are deleted. A backup already absent is harmless.

---

## 11. Building the per-region counts table

### `_counts_tsv()` — lines 380–397

```python
380  def _counts_tsv(regions: Sequence[Region], removed_positions: Iterable[int]) -> str:
381      positions = sorted(removed_positions)
382      rows = [["region_id", "region_name", "start", "end", "removed_rows"]]
```

Removed coordinates are sorted. The first TSV row is the header.

```python
384  for region in regions:
385      left = bisect.bisect_left(positions, region.start)
386      right = bisect.bisect_right(positions, region.end)
```

For each **original supplied region**, binary searches locate the first removed position at or after the inclusive start and the first removed position after the inclusive end.

Therefore `right - left` is the number of removed matrix-row coordinates falling inside that region.

```python
387  rows.append(
388      [
389          str(region.region_id),
390          region.name,
391          str(region.start),
392          str(region.end),
393          str(right - left),
394      ]
395  )
```

One row is appended containing region metadata and its count.

Because counts are calculated against each original region independently, a removed coordinate covered by two overlapping regions contributes to both region counts even though the matrix row itself was removed only once.

```python
397  return "\n".join("\t".join(row) for row in rows) + "\n"
```

Fields are joined by tabs, rows by newlines, and the file ends with a newline.

---

## 12. SHA-256 checksum helpers

### `_sha256_bytes()` — lines 400–401

```python
400  def _sha256_bytes(content: bytes) -> str:
401      return hashlib.sha256(content).hexdigest()
```

Computes SHA-256 over raw bytes and returns the conventional hexadecimal digest.

### `_sha256_text()` — lines 404–405

```python
404  def _sha256_text(content: str) -> str:
405      return _sha256_bytes(content.encode("utf-8"))
```

Text is encoded as UTF-8 bytes and passed to `_sha256_bytes()`.

### `_sha256_file()` — lines 408–416

```python
408  def _sha256_file(path: Path) -> str:
409      digest = hashlib.sha256()
410      try:
411          with path.open("rb") as handle:
412              for chunk in iter(lambda: handle.read(1024 * 1024), b""):
413                  digest.update(chunk)
```

The input file is opened in binary mode and read in 1 MiB chunks. Each chunk updates the SHA-256 digest, avoiding the need to load the entire file into memory solely for checksumming.

```python
414  except OSError as exc:
415      raise NexusFilterError(f"Cannot checksum input file '{path}': {exc}") from exc
416  return digest.hexdigest()
```

Filesystem errors become controlled NEXCISION errors; otherwise the final hexadecimal digest is returned.

---

## 13. The main in-memory filtering engine

### `filter_nexus_text()` — lines 419–549

This function performs the central transformation. It accepts already-read NEXUS text plus validated regions and returns:

1. filtered NEXUS text;
2. per-region counts TSV text;
3. a `FilterResult` summary.

It does **not** write files itself.

### Lines 419–427: inputs and defaults

```python
419  def filter_nexus_text(
420      text: str,
421      regions: Sequence[Region],
422      *,
423      position_pattern: str = DEFAULT_POSITION_PATTERN,
424      allow_unparsed: bool = False,
425      allow_empty: bool = False,
426      update_dimension: DimensionPolicy = "auto",
427  ) -> tuple[str, str, FilterResult]:
```

The `*` means arguments after it must be supplied by name rather than accidentally by position. This makes calls such as `allow_empty=True` explicit.

### Lines 430–435: validate prerequisites and prepare text

```python
430  if not regions:
431      raise NexusFilterError("At least one region is required.")
433  pattern = compile_position_pattern(position_pattern)
434  starts, merged_regions = _merge_regions(regions)
435  lines = text.splitlines(keepends=True)
```

- A non-empty region list is mandatory.
- The coordinate regex is compiled and validated.
- Supplied regions are merged into the efficient internal lookup form.
- NEXUS text is split into lines while retaining line-ending characters, helping preserve the original file structure.

### Lines 437–446: find exactly one standalone `MATRIX` line

```python
437  matrix_indices = [
438      index for index, line in enumerate(lines) if line.strip().lower() == "matrix"
439  ]
440  if not matrix_indices:
441      raise NexusFilterError("No standalone MATRIX line was found in the NEXUS file.")
442  if len(matrix_indices) > 1:
443      raise NexusFilterError(
444          "More than one MATRIX block was found; NEXCISION intentionally supports "
445          "one block per input."
446      )
```

A line qualifies only when stripping whitespace and lowercasing it gives exactly `matrix`.

- zero such lines -> error;
- more than one -> error;
- exactly one -> proceed.

This implements NEXCISION's deliberate one-MATRIX-block scope.

### Lines 448–456: initialize filtering state

```python
448  matrix_start = matrix_indices[0]
449  output_lines = lines[: matrix_start + 1]
450  in_matrix = True
451  terminated = False
452  parsed_rows = 0
453  rows_removed = 0
454  parsed_rows_kept = 0
455  unparsed_rows = 0
456  removed_positions: list[int] = []
```

- The text through and including the `MATRIX` line is copied unchanged into the future output.
- Boolean variables track whether parsing is still inside the matrix and whether its semicolon terminator has been found.
- Counters begin at zero.
- Removed genomic coordinates will be recorded for the per-region count table.

### Lines 458–462: walk through all subsequent lines

```python
458  for index in range(matrix_start + 1, len(lines)):
459      line = lines[index]
460      if not in_matrix:
461          output_lines.append(line)
462          continue
```

Every line after `MATRIX` is inspected in order.

Once the matrix has ended, remaining lines are copied unchanged without coordinate parsing.

### Lines 464–470: separate content from the first semicolon

```python
464  before, separator, after = line.partition(";")
465  content = before if separator else line
467  if separator and content.strip().lower() in {"end", "endblock"}:
468      raise NexusFilterError(
469          "The MATRIX block is not terminated before the enclosing block ends."
470      )
```

`partition(";")` divides the line at its first semicolon into:

- content before `;`;
- the separator itself (or an empty string if absent);
- content after `;`.

If NEXCISION encounters `END;` or `ENDBLOCK;` while still expecting the matrix terminator, it reports that the matrix was not properly terminated.

### Lines 472–477: preserve comments and blank lines

```python
472  if _is_comment_or_blank(content):
473      output_lines.append(line)
474      if separator:
475          in_matrix = False
476          terminated = True
477      continue
```

Blank/comment content is preserved. If such a line also carries the matrix's semicolon terminator, the matrix is marked complete.

### Lines 479–491: parse the row coordinate or handle an unparsed row

```python
479  position = extract_position(content, pattern)
480  if position is None:
481      unparsed_rows += 1
482      if not allow_unparsed:
483          raise NexusFilterError(
484              f"Matrix line {index + 1} does not match the position pattern: "
485              f"{content.strip()!r}. Use --allow-unparsed to preserve it."
486          )
487      output_lines.append(line)
488      if separator:
489          in_matrix = False
490          terminated = True
491      continue
```

If no coordinate can be extracted:

1. the unparsed-row counter increases;
2. default behaviour is to stop with an error;
3. with `allow_unparsed=True`, the entire original line is preserved unchanged;
4. a semicolon on that line still closes the matrix.

Thus `--allow-unparsed` means **preserve**, not "try to infer".

### Lines 493–506: make the removal decision

```python
493  parsed_rows += 1
494  if _is_excluded(position, starts, merged_regions):
495      rows_removed += 1
496      removed_positions.append(position)
```

A successfully parsed row increments `parsed_rows`. Its coordinate is tested against the merged exclusion intervals.

When excluded:

- the removal counter increments;
- the coordinate is stored for later per-region counting;
- the matrix-row content is **not** appended to output.

```python
497      if separator:
498          newline = "\n" if line.endswith("\n") else ""
499          output_lines.append(f";{after.rstrip(chr(10))}{newline}")
```

There is one special case: the removed data row itself may also contain the semicolon that terminates the matrix.

NEXCISION removes the row content but preserves the terminator and any text following it. This prevents row removal from accidentally deleting the structural end of the matrix.

```python
500  else:
501      parsed_rows_kept += 1
502      output_lines.append(line)
```

If the coordinate is outside all exclusion intervals, the entire original line is retained unchanged.

```python
504  if separator:
505      in_matrix = False
506      terminated = True
```

Whether the parsed row was removed or kept, a semicolon on that row ends matrix parsing.

### Lines 508–513: structural validation after scanning

```python
508  if not terminated:
509      raise NexusFilterError("The MATRIX block is not terminated by a semicolon.")
510  if parsed_rows == 0:
511      raise NexusFilterError(
512          "No coordinate-labelled rows were parsed from the MATRIX block."
513      )
```

NEXCISION requires:

- a terminating semicolon;
- at least one row that actually matched the coordinate pattern.

Even with `allow_unparsed=True`, a matrix containing only unparsed rows is not accepted as a valid coordinate-labelled matrix for this tool.

### Lines 515–522: calculate final row counts and prevent accidental empty matrices

```python
515  matrix_rows = parsed_rows + unparsed_rows
516  rows_kept = parsed_rows_kept + unparsed_rows
517  if rows_kept == 0 and not allow_empty:
518      raise NexusFilterError(
519          f"Filtering would remove all {matrix_rows} matrix rows. "
520          "No output was written. Use --allow-empty to create an empty "
521          "matrix intentionally."
522      )
```

`matrix_rows` includes both parsed and explicitly preserved unparsed data rows. `rows_kept` does the same for retained rows.

If nothing would remain, NEXCISION stops by default. The user must explicitly set `allow_empty=True` / `--allow-empty` to authorize an empty matrix.

At this stage no file output has been written, because this function works only in memory.

### Lines 524–535: update the selected dimension

```python
524  warnings: list[str] = []
525  output_lines, dimension_name, dimension_before, dimension_after, warning = (
526      _update_dimension(
527          output_lines,
528          matrix_start,
529          matrix_rows,
530          rows_kept,
531          update_dimension,
532      )
533  )
534  if warning:
535      warnings.append(warning)
```

The filtered output is passed to `_update_dimension()` along with the observed before/after matrix-row counts.

Dimension inconsistencies described earlier are non-fatal warnings, so they are collected rather than raised as errors.

### Lines 537–548: build counts and the structured summary

```python
537  counts = _counts_tsv(regions, removed_positions)
538  result = FilterResult(
539      regions_loaded=len(regions),
540      matrix_rows_read=matrix_rows,
541      rows_removed=rows_removed,
542      rows_kept=rows_kept,
543      unparsed_rows=unparsed_rows,
544      dimension_updated=dimension_name,
545      dimension_before=dimension_before,
546      dimension_after=dimension_after,
547      warnings=tuple(warnings),
548  )
```

- Per-region counts are calculated from the original region list and removed coordinates.
- All summary values are stored in an immutable `FilterResult`.
- The warning list is converted to an immutable tuple.

### Line 549: return all in-memory results

```python
549  return "".join(output_lines), counts, result
```

The filtered lines are joined back into one NEXUS string, then returned with the TSV text and summary object.

No filesystem writing has happened inside `filter_nexus_text()`.

---

## 14. Constructing the JSON provenance report

### `_run_report()` — lines 552–590

```python
552  def _run_report(
553      *,
554      nexus: Path,
555      regions: Path,
556      output: Path,
557      counts: Path,
558      filtered_text: str,
559      counts_text: str,
560      result: FilterResult,
561      position_pattern: str,
562      allow_unparsed: bool,
563      allow_empty: bool,
564      update_dimension: DimensionPolicy,
565  ) -> str:
```

All arguments are keyword-only. The function builds report text but does not write the report itself.

```python
566  payload = {
567      "software": {"name": "NEXCISION", "version": VERSION},
```

The report records the software name and version.

```python
568      "inputs": {
569          "nexus": {"path": str(nexus), "sha256": _sha256_file(nexus)},
570          "regions": {"path": str(regions), "sha256": _sha256_file(regions)},
571      },
```

Both input paths and SHA-256 checksums of the original input files are recorded.

```python
572      "parameters": {
573          "allow_empty": allow_empty,
574          "allow_unparsed": allow_unparsed,
575          "position_regex": position_pattern,
576          "update_dimension": update_dimension,
577      },
```

The filtering settings that can change interpretation of the input are recorded explicitly.

`force` is not included because it controls whether existing destination files may be replaced; it does not change the filtering calculation or generated file contents.

```python
578      "results": asdict(result),
```

The `FilterResult` dataclass is converted into ordinary key/value data for JSON serialization.

```python
579      "outputs": {
580          "filtered_nexus": {
581              "path": str(output),
582              "sha256": _sha256_text(filtered_text),
583          },
584          "region_counts": {
585              "path": str(counts),
586              "sha256": _sha256_text(counts_text),
587          },
588      },
589  }
```

The intended output paths and SHA-256 checksums of the exact generated filtered NEXUS and count text are recorded before those outputs are committed to disk.

```python
590  return json.dumps(payload, indent=2, sort_keys=True) + "\n"
```

The report is serialized with:

- two-space indentation;
- alphabetically sorted JSON keys;
- a final newline.

There is no timestamp or random identifier in this payload, which avoids introducing a run-time-varying field into otherwise identical report content. Paths remain part of the report, so changing paths changes the report text even when input file contents are identical.

---

## 15. File-level orchestration

### `filter_nexus_file()` — lines 593–662

This is the function called by `cli.py`. It coordinates file paths, input reading, filtering, optional report construction, and transactional output writing.

### Lines 593–605: function interface

```python
593  def filter_nexus_file(
594      nexus_path: str | Path,
595      regions_path: str | Path,
596      output_path: str | Path,
597      counts_path: str | Path,
598      *,
599      report_path: str | Path | None = None,
600      position_pattern: str = DEFAULT_POSITION_PATTERN,
601      allow_unparsed: bool = False,
602      allow_empty: bool = False,
603      update_dimension: DimensionPolicy = "auto",
604      force: bool = False,
605  ) -> FilterResult:
```

Four paths are required: NEXUS input, regions input, filtered NEXUS output, and count output. The report and behavioural options are keyword-only.

### Lines 608–612: normalize path objects

```python
608  nexus = Path(nexus_path)
609  regions_file = Path(regions_path)
610  output = Path(output_path)
611  counts = Path(counts_path)
612  report = Path(report_path) if report_path is not None else None
```

String paths are converted to `Path` objects. The report stays `None` when the user did not request one.

### Lines 614–621: prevent output-path collisions

```python
614  input_paths = {nexus.resolve(), regions_file.resolve()}
615  destinations = [output, counts] + ([report] if report is not None else [])
616  output_paths = {destination.resolve() for destination in destinations}
```

Resolved absolute paths are collected for both inputs and all requested outputs.

```python
618  if len(output_paths) != len(destinations):
619      raise NexusFilterError("Every output path must be different.")
620  if input_paths & output_paths:
621      raise NexusFilterError("Output paths must not overwrite an input file.")
```

NEXCISION refuses to proceed when:

- two requested outputs resolve to the same path;
- any output resolves to either input path.

This check occurs before reading/filtering or writing outputs.

### Lines 623–626: read the NEXUS file as UTF-8

```python
623  try:
624      text = nexus.read_text(encoding="utf-8")
625  except (OSError, UnicodeError) as exc:
626      raise NexusFilterError(f"Cannot open NEXUS file '{nexus}': {exc}") from exc
```

Filesystem errors and invalid UTF-8 input are both converted into a controlled NEXCISION error.

### Lines 628–636: load regions and perform the in-memory transformation

```python
628  regions = load_regions(regions_file)
629  filtered, counts_text, result = filter_nexus_text(
630      text,
631      regions,
632      position_pattern=position_pattern,
633      allow_unparsed=allow_unparsed,
634      allow_empty=allow_empty,
635      update_dimension=update_dimension,
636  )
```

The regions file is validated first. Then the entire in-memory NEXUS transformation described in Section 13 is performed.

If any validation/filtering error occurs here, output writing has not started.

### Lines 638–652: optionally generate report text

```python
638  report_text = None
639  if report is not None:
640      report_text = _run_report(
641          nexus=nexus,
642          regions=regions_file,
643          output=output,
644          counts=counts,
645          filtered_text=filtered,
646          counts_text=counts_text,
647          result=result,
648          position_pattern=position_pattern,
649          allow_unparsed=allow_unparsed,
650          allow_empty=allow_empty,
651          update_dimension=update_dimension,
652      )
```

No report is constructed unless a report destination was requested. When it is requested, all filtering results and checksum inputs are available before any final output is committed.

### Lines 654–659: assemble the complete output transaction

```python
654  output_contents: list[tuple[Path, str]] = [
655      (output, filtered),
656      (counts, counts_text),
657  ]
658  if report is not None and report_text is not None:
659      output_contents.append((report, report_text))
```

The filtered NEXUS and count table are always included. The report is included only when requested and successfully constructed.

### Lines 661–662: commit outputs and return the summary

```python
661  _write_outputs_atomically(output_contents, force=force)
662  return result
```

All requested outputs are passed to the transactional writer **together**. Only after that function succeeds is the `FilterResult` returned to the CLI for printing.

This ordering is important: the CLI's success summary occurs only after the output transaction returns successfully.

---

## 16. Worked example: following one matrix row through the code

The bundled example contains:

```text
CP013831_180 1101
```

and the regions file contains:

```text
170 260 recombination_block_1
300 350 recombination_block_2
```

Here is exactly what happens to the row at coordinate 180.

### Step 1: the regions are loaded

`load_regions()` creates approximately these internal records:

```text
Region(1, 170, 260, "recombination_block_1")
Region(2, 300, 350, "recombination_block_2")
```

Both intervals are already valid 1-based inclusive intervals.

### Step 2: removal intervals are prepared

`_merge_regions()` produces:

```text
starts         = [170, 300]
merged_regions = [(170, 260), (300, 350)]
```

They do not overlap or touch, so they remain separate.

### Step 3: NEXCISION reaches the matrix row

Inside `filter_nexus_text()`, the line is passed to `extract_position()`.

The first token is:

```text
CP013831_180
```

The default regex `_(\d+)$` captures:

```text
180
```

It is converted to integer `180`.

### Step 4: coordinate 180 is tested against the regions

`_is_excluded(180, starts, merged_regions)` finds the interval beginning at 170 and checks whether:

```text
180 <= 260
```

This is true, so the row is excluded.

### Step 5: the row is not copied to the output

`rows_removed` increases by one and `180` is appended to `removed_positions`.

The original row text is not appended to `output_lines`.

NEXCISION does not alter `1101`; it removes the complete coordinate-labelled row because its coordinate is inside the mask.

### Step 6: counts are calculated after all rows have been examined

For `recombination_block_1`, removed coordinates inside `170-260` are `180` and `250`, so `removed_rows=2`.

For `recombination_block_2`, coordinate `320` is inside `300-350`, so `removed_rows=1`.

### Step 7: the matrix dimension is updated conservatively

The bundled example is not declared `TRANSPOSE`, so automatic dimension selection chooses `ntax`.

The input has five matrix rows and declares:

```text
ntax=5
```

Three rows are removed and two remain. Because the declared value exactly matches the original observed row count, it is safely changed to:

```text
ntax=2
```

`nchar=4` is left untouched.

### Step 8: outputs are staged and then committed

The complete filtered NEXUS and count table are generated in memory first. If a report was requested, it is also generated before final output commit.

All requested output texts are then written to temporary files before being moved into their final destinations.

The expected filtered matrix is therefore:

```text
Matrix
CP013831_100 0101
CP013831_500 0011
;
```

with all non-excluded rows retained in their original order and content.

---

## 17. What the implementation deliberately does not infer

Reading the code is also useful for understanding what NEXCISION refuses to guess.

The v0.1.1 implementation does **not**:

- silently accept an empty region set;
- infer a coordinate from anywhere other than the first matrix token;
- accept a coordinate regex with zero or multiple capture groups;
- silently preserve an unparsed data row unless `--allow-unparsed` is explicitly supplied;
- silently produce a matrix with zero rows unless `--allow-empty` is explicitly supplied;
- accept multiple standalone `MATRIX` blocks;
- choose between multiple candidate dimension declarations;
- rewrite a selected dimension when its declared value disagrees with the observed original matrix-row count;
- overwrite an input file with an output;
- write two outputs to the same resolved path;
- overwrite an existing output unless `--force` is supplied.

These behaviours follow directly from explicit checks in `core.py`, rather than from assumptions made outside the program.

---

## 18. Error, warning, and success behaviour

NEXCISION distinguishes three outcomes.

### Error

A condition that prevents safe filtering raises `NexusFilterError`. Examples include invalid coordinates, malformed regex, no valid regions, malformed matrix termination, an unparsed row without opt-in, accidental empty output, output collisions, and controlled filesystem failures.

At the command line, `cli.py` prints:

```text
ERROR: ...
```

and returns exit code `2`.

### Warning

A condition that does not invalidate row filtering but prevents a safe dimension rewrite is returned in `FilterResult.warnings`. The filtered output can still be written, while the dimension remains unchanged.

At the command line, warnings are printed as:

```text
WARNING: ...
```

### Success

After all requested outputs have been committed successfully, `main()` prints the run summary and returns exit code `0`.

---

## 19. Safety regression tests added for v0.1.1

The permanent tests in [`tests/test_release_safety.py`](https://github.com/RhysWhite/nexcision/blob/main/tests/test_release_safety.py) exercise the safety behaviour restored in v0.1.1.

They check that:

- removing every row is rejected by default;
- `allow_empty=True` explicitly permits an empty matrix;
- the command-line interface requires the `--allow-empty` opt-in;
- invalid UTF-8 in the NEXUS input fails without creating outputs;
- invalid UTF-8 in the regions file fails cleanly;
- nested output paths are rejected before writing;
- a deliberately simulated failure during the second output commit leaves no newly committed outputs in that test scenario;
- the JSON provenance report records `allow_empty`.

These tests complement the existing core and CLI test suites. They are regression tests: their purpose is to make future changes fail visibly if these specific behaviours are accidentally removed.

---

## 20. Short audit summary

At its core, NEXCISION v0.1.1 performs this sequence:

1. Parse and validate the requested command-line settings.
2. Read the NEXUS and regions files as UTF-8.
3. Validate and normalize 1-based inclusive regions.
4. Locate exactly one standalone NEXUS `MATRIX` block.
5. Extract a coordinate from the first token of each data row.
6. Test that coordinate against merged exclusion intervals.
7. Omit rows whose coordinates fall inside those intervals; preserve non-excluded rows unchanged.
8. Refuse unparsed rows or an empty resulting matrix unless the corresponding explicit opt-in is supplied.
9. Update `ntax` or `nchar` only when the selected field can be changed unambiguously and its original value agrees with the observed input row count.
10. Calculate counts against each original supplied region.
11. Optionally build a JSON report containing version, parameters, results, paths, and SHA-256 checksums.
12. Stage all requested outputs before committing them to their final paths.
13. Return a structured summary to the command-line interface, which prints success information only after output writing succeeds.

For the validation and benchmarking evidence supporting the software beyond this source-level walkthrough, see the [NEXCISION benchmarking repository](https://github.com/RhysWhite/nexcision-benchmarking).
