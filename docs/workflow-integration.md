# Workflow integration

NEXCISION can write a deterministic JSON report alongside the filtered NEXUS
matrix and per-region counts file. The report is intended to be inspected by
people or software before downstream analysis proceeds.

The report records **what NEXCISION did with the supplied inputs**. It cannot
determine whether the exclusion intervals are biologically appropriate. A
workflow should therefore apply acceptance criteria that are justified for the
specific analysis rather than treating the existence of an output file as
sufficient evidence of success.

## Generate a report

```bash
nexcise input.nex regions.tsv \
  --output filtered.nex \
  --counts removed_counts_per_region.tsv \
  --report nexcision_report.json
```

The report contains these top-level sections:

| Section | Contents |
|---|---|
| `software` | NEXCISION name and version. |
| `inputs` | Input paths and SHA-256 checksums. |
| `parameters` | Coordinate pattern, unparsed-row policy, and dimension policy. |
| `results` | Matrix-row totals, removal results, dimension handling, and warnings. |
| `outputs` | Output paths and SHA-256 checksums. |

The principal fields for automated checks are:

```text
.results.matrix_rows_read
.results.rows_removed
.results.rows_kept
.results.unparsed_rows
.results.dimension_updated
.results.dimension_before
.results.dimension_after
.results.warnings
.outputs.filtered_nexus.sha256
.outputs.region_counts.sha256
.inputs.nexus.sha256
.inputs.regions.sha256
```

## Choose an analysis-specific acceptance policy

A report with `rows_removed` equal to zero is not inherently invalid. It may be
the expected result when none of the coordinates represented in a matrix fall
inside the supplied intervals. Conversely, zero removals may indicate a wrong
mask or unexpected coordinate system when the analysis was expected to remove
sites.

Useful workflow policies include:

- accept any non-negative removal count while checking structural consistency
  and output checksums;
- require at least one removal when an intersection is expected;
- require an exact, independently established removal count for a fixed input;
- stop on any warning, or record warnings while allowing the workflow to
  continue;
- verify that the files supplied to the downstream step still match the
  checksums recorded when NEXCISION ran.

The per-region counts are intentionally independent. If supplied intervals
overlap, one matrix row is removed only once but can contribute to more than one
regional count. Therefore, the sum of `removed_rows` in the TSV file need not
equal `.results.rows_removed`.

## Inspect fields with `jq`

Display the overall removal result:

```bash
jq '{read: .results.matrix_rows_read,
     removed: .results.rows_removed,
     kept: .results.rows_kept,
     warnings: .results.warnings}' \
  nexcision_report.json
```

Require at least one removed row for an analysis in which an intersection is
expected:

```bash
jq -e '.results.rows_removed >= 1' nexcision_report.json >/dev/null || {
  echo 'ERROR: the exclusion intervals removed no matrix rows' >&2
  exit 1
}
```

Require an exact result for a fixed, independently checked input:

```bash
expected_removed=417
observed_removed=$(jq -er '.results.rows_removed' nexcision_report.json)

if [ "$observed_removed" -ne "$expected_removed" ]; then
  echo "ERROR: expected $expected_removed removals; observed $observed_removed" >&2
  exit 1
fi
```

## Use the bundled validator

[`examples/validate_report.sh`](../examples/validate_report.sh) performs the
following checks:

1. required report fields have the expected types;
2. removed rows plus kept rows equal rows read;
3. reported dimension updates agree with the row totals;
4. the filtered NEXUS and regional-count files match their recorded SHA-256
   checksums;
5. optional minimum/exact removal and warning policies are satisfied;
6. optional input files match their recorded checksums.

The script requires `jq`. It uses `sha256sum`, `shasum`, or Python 3 to calculate
checksums.

Validate outputs without imposing a biological removal threshold:

```bash
bash examples/validate_report.sh \
  nexcision_report.json \
  filtered.nex \
  removed_counts_per_region.tsv
```

Require at least one removal and fail on warnings:

```bash
bash examples/validate_report.sh \
  --min-removed 1 \
  --fail-on-warnings \
  --nexus input.nex \
  --regions regions.tsv \
  nexcision_report.json \
  filtered.nex \
  removed_counts_per_region.tsv
```

For a fixed dataset with an independently established expected result:

```bash
bash examples/validate_report.sh \
  --exact-removed 417 \
  --fail-on-warnings \
  nexcision_report.json \
  filtered.nex \
  removed_counts_per_region.tsv
```

## Snakemake example

The bundled Snakemake example makes downstream execution depend on a validation
marker that is created only when report checks pass:

```text
nexcise
  -> validate_nexcision_report
       -> downstream_analysis
```

After installing NEXCISION, run it with:

```bash
cd examples/snakemake
snakemake --cores 1
```

The example uses the repository's bundled input and expects exactly three rows
to be removed. Edit [`config.yaml`](../examples/snakemake/config.yaml) before
adapting it to another dataset. Set either `exact_removed_rows` or
`minimum_removed_rows`, not both. Omit both settings when zero removals are
acceptable.

The final rule is a placeholder. Replace it with the tree-building or other
downstream command. Its declared inputs include both the filtered matrix and the
validation marker, so it cannot run merely because `filtered.nex` exists.

## What the checksums do—and do not do

The SHA-256 values provide stable identifiers for the exact bytes read or
written by NEXCISION. They can reveal later file modification, file
substitution, or disagreement between repeated runs.

Snakemake, Nextflow, and other workflow systems do not automatically interpret
checksums stored inside an arbitrary JSON file. They have their own rules for
tracking declared inputs, outputs, parameters, software environments, and
cached tasks. The report becomes an active workflow control only when a rule or
process explicitly parses or validates it, as in the bundled example.
