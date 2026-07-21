# NEXCISION

**Precise removal of coordinate-labelled sites from NEXUS matrices.**

NEXCISION removes matrix rows whose genomic coordinates fall within user-specified 
intervals, while preserving the remaining structure and content of the NEXUS file. 

It is designed for transposed NEXUS matrices in which each row represents a 
genomic site and the first token ends with its coordinate, for example:

```text
CP013831_180    01001101
```

In this example, 180 is the genomic coordinate used to determine whether the row should be retained or removed.

## Install

NEXCISION requires Python 3.10 or newer and has no runtime dependencies.

```bash
git clone https://github.com/RhysWhite/nexcision.git
cd nexcision
python -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

## Run

```bash
nexcise input.nex regions.tsv \
  --output filtered.nex \
  --counts removed_counts_per_region.tsv \
  --report nexcision_report.json
```

Existing outputs are not overwritten unless `--force` is supplied.

## Regions file

Coordinates are **1-based and inclusive**. The file is whitespace-delimited;
the name column is optional.

```text
start   end   name
170     260   recombination_block_1
300     350   recombination_block_2
```

Blank lines and `#` comments are ignored. Reversed coordinates are normalised.

## Outputs

- Filtered NEXUS matrix.
- TSV removal counts for every input region.
- Optional JSON report containing NEXCISION version, parameters, results, and
  SHA-256 checksums.

Overlapping regions are counted independently, but each matrix row is removed
only once.

## Dimension handling

By default, NEXCISION safely updates:

- `ntax` for an ordinary matrix;
- `nchar` when the preceding `FORMAT` command declares `TRANSPOSE`.

The selected value is changed only when it equals the original matrix row
count. Otherwise NEXCISION warns and leaves it unchanged. Override this with:

```bash
--update-dimension ntax
--update-dimension nchar
--update-dimension none
```

## Coordinate identifiers

The default coordinate pattern is `_(\d+)$`. For identifiers such as
`site:180`, supply one capture group:

```bash
nexcise input.nex regions.tsv --position-regex 'site:(\d+)$'
```

Matrix rows that do not match are rejected by default. Use `--allow-unparsed`
only when they should be retained unchanged.

## Reproduce the example

```bash
python -m pip install .
nexcise examples/input.nex examples/regions.tsv \
  --output filtered.nex \
  --counts removed_counts_per_region.tsv \
  --report nexcision_report.json

diff -u examples/expected_filtered.nex filtered.nex
diff -u examples/expected_removed_counts_per_region.tsv \
  removed_counts_per_region.tsv
```

## Test

```bash
python -m unittest discover -s tests -v
```

GitHub Actions tests Python 3.10–3.13, reproduces the bundled example, and
builds an installable wheel.

## Scope

NEXCISION filters **matrix rows**, not alignment columns. It deliberately
supports one standalone `MATRIX` block per file and is not a general NEXUS
parser.

## Citation

See [`CITATION.cff`](CITATION.cff).

## License

MIT. Confirm institutional ownership requirements before public release.
