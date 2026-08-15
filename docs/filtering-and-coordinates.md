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

Users remain responsible for ensuring that the regions and matrix row identifiers use the same reference coordinate system.
