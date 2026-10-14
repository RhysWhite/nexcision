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

## NEXUS bracket comments and quoted text

NEXCISION recognises NEXUS square-bracket comments, including inline,
multiline, and nested comments. A semicolon or `MATRIX`, `FORMAT`, `DIMENSIONS`,
`ntax`, or `nchar` text **inside a comment** is not interpreted as NEXUS syntax.
Quoted strings are likewise excluded from structural-command and semicolon
recognition. Comments on retained matrix rows are preserved unchanged;
comments attached to removed rows are also retained, without their removed
matrix states. Unbalanced brackets or unterminated quoted strings are rejected
before any output is written.

This is limited, comment-aware handling for the supported **one-matrix,
coordinate-labelled-row** model, not validation or rewriting of arbitrary
NEXUS commands and linked character partitions.

## Other NEXUS blocks

When the target character matrix is in a `DATA` or `CHARACTERS` block,
NEXCISION distinguishes its `MATRIX` command from the separate `MATRIX`
command permitted in a `DISTANCES` block. For supported transposed site
matrices, independently defined `TREES` and `DISTANCES` blocks are retained
byte-for-byte unchanged: excision removes character rows, not taxa. NEXCISION
does not recompute tree topologies, branch lengths, or taxon distances.

This preservation rule does not override the linked-metadata safeguard below:
recognized character-indexed statements that could become invalid after
excision cause a controlled error. NEXCISION is not a general NEXUS validator;
users remain responsible for assessing whether unrecognized/custom blocks
contain dependencies on the removed characters.

## Linked NEXUS metadata and partitions

NEXCISION changes **matrix row numbering** when one or more sites are
removed. Other NEXUS statements may refer to characters by position and
become invalid after this change. NEXCISION deliberately does **not** attempt
to interpret or renumber those linked definitions.

If at least one matrix row would be excised, the program rejects files
containing recognized character-indexed commands outside MATRIX, including
`CHARSET`, `CHARPARTITION`, `EXSET`, `WTSET`, `TYPESET`, `ANCSTATES`,
`CODONPOSSET`, `CODESET`, `ELIMINATE`, `CHARLABELS`, `STATELABELS`,
`CHARSTATELABELS`, and `CHARWEIGHTS`. For non-transposed matrices, it also
rejects recognized taxon-indexed definitions (e.g. `TAXSET`, `TAXPARTITION`,
`TAXLABELS`, `TRANSLATE`, `TREE`, and `UTREE`) because filtering removes taxa
rather than characters. Taxon sets in transposed matrices remain permissible
because the taxa (columns) do not change.

The guard recognizes NEXUS commands outside the matrix, ignoring appearances
of their names inside quoted strings or bracket comments. A true no-op filter
(`0` removed rows) preserves linked metadata without modification. The guard
applies even when `--update-dimension none` is supplied and fails before any
output is written or overwritten.

To excise sites from a file containing such metadata, first remove or
regenerate the positional definitions in a separate, validated NEXUS-aware
workflow. NEXCISION is **not a complete NEXUS validator**: custom extensions
and other unrecognized commands may also depend on character order. Users
must validate linked metadata that falls outside the supported model.

## Line endings and retained text

NEXCISION reads valid UTF-8 NEXUS files without converting newline sequences.
It preserves existing LF (`\n`), CRLF (`\r\n`), and CR (`\r`) endings,
including files containing a mixture of these sequences. Unchanged matrix rows,
comments, and text outside the MATRIX block therefore retain their original
bytes. Removed rows and any necessary numeric dimension update are intentional
changes to the output; generated counts and JSON report files use LF endings.

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

NEXCISION supports one target character `MATRIX` in a `DATA` or `CHARACTERS` block; a separate `DISTANCES` block may contain its own matrix without being treated as a second target. NEXCISION is not intended to be a general-purpose NEXUS parser.

Before filtering, confirm that:

- genomic sites are represented as matrix rows;
- the first token of each relevant row contains a coordinate that can be parsed by the selected regular expression;
- the regions use the same coordinate system as the matrix identifiers.
- all parsed site labels identify a single reference coordinate axis (mixed
  contig/chromosome/plasmid prefixes are rejected before writing outputs).
