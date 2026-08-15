# Outputs and provenance

NEXCISION can produce a filtered NEXUS matrix, a per-region counts table, and an optional JSON provenance report.

## Filtered NEXUS matrix

The primary output is the input NEXUS matrix with coordinate-labelled rows overlapping the supplied regions removed.

The default path is:

```text
filtered.nex
```

Choose another path with:

```bash
--output PATH
```

Rows retained by the filtering operation are preserved rather than reconstructed from parsed matrix states.

NEXCISION also applies the selected dimension-handling policy after filtering. See [Filtering and coordinates](filtering-and-coordinates.md).

## Per-region removal counts

NEXCISION writes a tab-separated counts table by default:

```text
removed_counts_per_region.tsv
```

Choose another path with:

```bash
--counts PATH
```

The table contains five columns:

| Column | Meaning |
|---|---|
| `region_id` | Internal identifier assigned to the supplied region. |
| `region_name` | Region name from the optional third input field. |
| `start` | Normalised 1-based inclusive start coordinate. |
| `end` | Normalised 1-based inclusive end coordinate. |
| `removed_rows` | Number of removed matrix positions falling within that region. |

The header is:

```text
region_id    region_name    start    end    removed_rows
```

Overlapping regions are counted independently. A matrix row is removed only once from the filtered NEXUS matrix even when its coordinate contributes to more than one region count.

## JSON provenance report

Use:

```bash
--report PATH
```

to request a deterministic JSON report describing the run.

For example:

```bash
nexcise input.nex regions.tsv \
  --output filtered.nex \
  --counts removed_counts_per_region.tsv \
  --report nexcision_report.json
```

The report contains five top-level sections:

```text
software
inputs
parameters
results
outputs
```

### `software`

Records:

- software name;
- NEXCISION version.

### `inputs`

Records the path and SHA-256 checksum of:

- the input NEXUS file;
- the regions file.

The structure is:

```json
{
  "inputs": {
    "nexus": {
      "path": "...",
      "sha256": "..."
    },
    "regions": {
      "path": "...",
      "sha256": "..."
    }
  }
}
```

These checksums allow a workflow or later audit to verify the exact input bytes used for the run.

### `parameters`

Records the filtering settings:

```text
allow_empty
allow_unparsed
position_regex
update_dimension
```

These correspond to the explicit command-line behaviour controlling empty outputs, unmatched matrix rows, coordinate parsing, and dimension handling.

### `results`

Records the complete `FilterResult` summary:

| Field | Meaning |
|---|---|
| `regions_loaded` | Number of genomic regions loaded. |
| `matrix_rows_read` | Number of matrix rows processed. |
| `rows_removed` | Number of matrix rows removed. |
| `rows_kept` | Number of matrix rows retained. |
| `unparsed_rows` | Number of unmatched rows preserved under `--allow-unparsed`. |
| `dimension_updated` | Dimension changed by NEXCISION, or `null` when none was changed. |
| `dimension_before` | Original value of the selected dimension, when applicable. |
| `dimension_after` | Resulting value of the selected dimension, when applicable. |
| `warnings` | Warnings produced during the run. |

The row totals provide a simple consistency relationship:

```text
matrix_rows_read = rows_removed + rows_kept
```

### `outputs`

Records the path and SHA-256 checksum of:

- the filtered NEXUS content;
- the per-region counts content.

The report therefore links the recorded inputs and parameters to the two principal generated outputs.

## What the checksums establish

The recorded SHA-256 values can be used to detect changes to the input files or generated outputs after a run.

They support questions such as:

- Are these the same NEXUS and regions files used previously?
- Does this filtered NEXUS match the recorded output?
- Does this counts table match the recorded output?

The checksums do not establish that an input file is biologically appropriate for a particular analysis. Coordinate-system compatibility, mask selection, and downstream acceptance criteria remain analysis-specific decisions.

See [Workflow integration](workflow-integration.md) for examples of checking these fields programmatically.

## Warnings

Warnings are retained in the `results.warnings` field of the JSON report.

A warning does not necessarily mean that the output is unusable. For example, a dimension mismatch may cause NEXCISION to leave a dimension unchanged rather than guess.

Automated workflows can decide whether warnings are acceptable for a particular analysis.

## Existing output files

Requested outputs are not overwritten by default.

Use:

```bash
--force
```

when replacement of existing outputs is intentional.

NEXCISION stages requested outputs before committing them, providing transactional behaviour for multi-output runs rather than intentionally leaving only part of an output set updated after a write failure.
