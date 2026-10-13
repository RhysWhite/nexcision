# Filtering and coordinates

NEXCISION removes coordinate-labelled **matrix rows** whose parsed genomic positions overlap user-supplied intervals.

It does not remove alignment columns and does not infer genomic coordinates from matrix content.

## Filtering rule

For each relevant matrix row, NEXCISION:

1. reads the first token;
2. extracts one genomic coordinate using the configured regular expression;
3. tests that coordinate against the supplied regions;
4. removes the row when its coordinate falls within at least one region;
5. otherwise retains the row unchanged.

Region coordinates are 1-based and inclusive.

For a region:

```text
170 260
```

rows at positions `170`, `260`, and every coordinate between them are selected for removal.

## Coordinate parsing

The default coordinate pattern is:

```text
_(\d+)$
```

For example:

```text
CP013831_180
```

is interpreted as genomic position `180`.

Use `--position-regex` when identifiers follow another format:

```bash
nexcise input.nex regions.tsv \
  --position-regex 'site:(\d+)$'
```

The expression must contain exactly one capture group representing the coordinate.

See [Input formats](input-formats.md) for the complete input requirements.

## Comment-aware parsing

NEXUS bracket comments, including nested and multiline comments, are excluded
from matrix-command, matrix-terminator and dimension-declaration detection.
A semicolon inside a comment is not the MATRIX terminator. NEXCISION retains
bracket comments even when their associated coordinate-labelled row is removed.
Unterminated comments and quoted strings cause a controlled error before output
files are written. This does not make NEXCISION a general NEXUS parser.

## Reference-coordinate axis safeguard

The regions file defines genomic positions, **not reference-sequence identifiers**.
Consequently, all coordinate-labelled MATRIX row identifiers must use one shared
reference-coordinate axis. NEXCISION checks that the non-coordinate part of
each parsed row label is identical across the matrix. With the default pattern,
`CP013831_100` and `CP013831_200` are compatible, whereas `chrA_100` and
`chrB_100` cause a controlled error **before any output is written**.

A user-specified coordinate regex still defines the captured position; the
remaining row-label characters are used for the reference-axis consistency
check. A coordinate-only row label contains no reference identifier, so
NEXCISION cannot independently establish its biological reference origin.

For matrices representing multiple contigs, chromosomes, or plasmids with
independent coordinate systems, **split the matrix by reference coordinate
axis and filter each against the appropriate regions**. NEXCISION does not
accept contig-specific region files or infer mappings between reference axes.

## Unparsed rows

A non-comment matrix row that cannot be parsed is rejected by default.

Use:

```bash
--allow-unparsed
```

only when unmatched rows are intentionally expected and should be preserved unchanged.

The number of preserved unparsed rows is included in the run summary and, when requested, the JSON report.

## Overlapping regions

Regions may overlap.

If one matrix position falls inside several supplied intervals:

- the matrix row is removed only once;
- each overlapping region receives its own removal count.

This separates the physical filtering operation from the per-region accounting.

## Empty-output protection

By default, NEXCISION rejects a filtering operation that would remove every matrix row.

This protects against accidentally producing an empty matrix because of an incorrect mask, coordinate system, or parsing rule.

If an empty matrix is genuinely intended, it must be explicitly permitted with:

```bash
--allow-empty
```

With this option enabled, filtering may produce zero retained rows and the relevant NEXUS dimension may be updated to zero.

## Dimension handling

Filtering changes the number of matrix rows. NEXCISION therefore provides controlled handling of the corresponding NEXUS dimension.

The available policies are:

```text
auto
ntax
nchar
none
```

### `auto`

This is the default.

NEXCISION selects:

- `nchar` when the preceding `FORMAT` command declares `TRANSPOSE`;
- `ntax` otherwise.

The selected dimension is updated only when its original value equals the number of matrix rows read before filtering.

If it does not match, NEXCISION leaves the value unchanged and emits a warning rather than guessing.

### `ntax`

```bash
--update-dimension ntax
```

Requests explicit handling of `ntax`.

### `nchar`

```bash
--update-dimension nchar
```

Requests explicit handling of `nchar`.

### `none`

```bash
--update-dimension none
```

Disables dimension updating.

## Linked character and taxon definitions

Removing character rows can invalidate existing NEXUS character sets,
partitions, character-indexed assumptions, codon-position sets, or character
labels. NEXCISION intentionally **rejects excision** when it finds recognized
linked character-indexed commands rather than silently carrying forward
obsolete indices. Non-transposed inputs receive an additional taxon-metadata
safeguard. Comments and quoted mentions of these commands do not trigger the
check, and no-op filtering is allowed. This check is independent of the
`--update-dimension` setting.

See [Input formats](input-formats.md#linked-nexus-metadata-and-partitions)
for the guarded commands and limitations. Arbitrary NEXUS extensions are not
validated or automatically rewritten.

## Existing outputs

NEXCISION does not overwrite existing output files by default.

Use:

```bash
--force
```

only when replacement of existing requested outputs is intentional.

When multiple outputs are requested, NEXCISION stages them before committing the write operation so that a failure does not intentionally leave a partially updated output set.

## Scope of interpretation

NEXCISION deliberately avoids inferring biological meaning from region labels or matrix states.

Its filtering decision is determined by:

- the coordinate parsed from the row identifier;
- the supplied inclusive intervals;
- the explicit command-line settings.

NEXCISION rejects conflicting reference prefixes, but cannot determine whether the
numeric intervals and the single observed reference actually correspond to
the same biological reference sequence. Users must verify this relationship.
