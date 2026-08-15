# NEXCISION

NEXCISION is a dependency-free Python command-line tool for exact, reproducible removal of coordinate-labelled genomic sites from NEXUS matrices.

It is designed primarily for transposed NEXUS matrices in which each matrix row represents a genomic site. NEXCISION reads the genomic coordinate from each row identifier, compares it with user-defined genomic intervals, removes matching rows, and preserves the remaining matrix content and structure.

## Installation

NEXCISION requires Python 3.10 or later.

### PyPI

```bash
python -m pip install nexcision
```

### Bioconda

```bash
conda install -c conda-forge -c bioconda nexcision
```

### Stable tagged release

```bash
python -m pip install git+https://github.com/RhysWhite/nexcision.git@v0.1.1
```

See [Installation](installation.md) for all installation options.

## Basic usage

```bash
nexcise input.nex regions.tsv \
  --output filtered.nex \
  --counts removed_counts_per_region.tsv \
  --report nexcision_report.json
```

Coordinates in the regions file are 1-based and inclusive. Existing outputs are not overwritten unless explicitly requested.

## Start here

- [Workflow integration](workflow-integration.md): provenance reports, checksums, validation policies, and a Snakemake example.
- [Code walkthrough](code-walkthrough.md): detailed explanation of the command-line interface and implementation.
- [GitHub repository](https://github.com/RhysWhite/nexcision): installation, examples, source code, issues, and release information.
- [Benchmarking and validation repository](https://github.com/RhysWhite/nexcision-benchmarking): formal correctness testing, adversarial validation, and scalability benchmarking.

## Citation and archival records

The NEXCISION v0.1.1 software release is archived in Zenodo with DOI **10.5281/zenodo.21936049**.

The benchmarking and validation release is archived separately with DOI **10.5281/zenodo.21935598**.

The methods and validation are described in:

> White RT. **NEXCISION: exact, validated, and scalable excision of genomic regions from phylogenomic NEXUS matrices.** *bioRxiv* [Preprint]. 2026. doi: 10.64898/2026.07.26.740842
