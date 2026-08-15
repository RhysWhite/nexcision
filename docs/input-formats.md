# Input formats

NEXCISION requires two input files:

1. a NEXUS matrix containing coordinate-labelled matrix rows;
2. a whitespace-delimited regions file defining genomic intervals to remove.

## NEXUS matrix

NEXCISION operates on **matrix rows**, not alignment columns.

It is intended for NEXUS matrices in which each relevant row represents a genomic site and the first token contains a genomic coordinate.

For example:

```text
CP013831_160    01001101
CP013831_180    11000110
CP013831_200    01011001
```

By default, NEXCISION extracts the terminal integer following an underscore from the first token of each matrix row.

The default coordinate pattern is:

```text
_(\d+)$
```

For the example above, the parsed coordinates are `160`, `180`, and `200`.

## Custom coordinate identifiers

Use `--position-regex` when row identifiers use a different coordinate format.

The regular expression must contain **exactly one capture group**, and that capture group must represent the genomic coordinate.

For identifiers such as:

```text
site:160
site:180
site:200
```

use:

```bash
nexcise input.nex regions.tsv \
  --position-regex 'site:(\d+)$'
```

## Unparsed matrix rows

Non-comment matrix rows that do not match the coordinate expression are rejected by default.

This fail-closed behaviour prevents an unexpected identifier format from being silently retained.

If unmatched matrix rows are intentionally expected and should remain unchanged, use:

```bash
--allow-unparsed
```

This option is an explicit opt-in. It preserves unmatched non-comment rows rather than assigning them a coordinate.

## Regions file

The regions file is whitespace-delimited.

Each data row must define a start coordinate and an end coordinate. A third name field is optional.

For example:

```text
start   end   name
170     260   recombination_block_1
300     350   recombination_block_2
```

Coordinates are **1-based and inclusive**.

A matrix row is therefore selected for removal when its parsed coordinate falls within a supplied interval, including either interval boundary.

## Region names

The optional third field provides a label for the region.

Names are useful when reviewing the per-region removal counts produced by NEXCISION.

## Blank lines and comments

Blank lines in the regions file are ignored.

Lines beginning with `#` are also ignored, allowing comments to be included alongside interval definitions.

## Reversed coordinates

If a supplied region has its start and end coordinates reversed, NEXCISION normalises the interval automatically.

For example:

```text
350 300 recombination_block_2
```

is treated as the inclusive interval from `300` to `350`.

## Overlapping regions

Supplied regions may overlap.

A matrix row overlapping more than one region is removed only once from the NEXUS matrix, while the per-region counts record that row independently for each overlapping interval.

## Scope

NEXCISION deliberately supports one standalone `MATRIX` block per input file and is not intended to be a general-purpose NEXUS parser.

Before filtering, confirm that:

- genomic sites are represented as matrix rows;
- the first token of each relevant row contains a coordinate that can be parsed by the selected regular expression;
- the regions use the same coordinate system as the matrix identifiers.
