# Installation

NEXCISION is a dependency-free Python command-line tool and requires Python 3.10 or later.

## PyPI

Install the current stable release from PyPI:

```bash
python -m pip install nexcision
```

To install the current release explicitly by version:

```bash
python -m pip install nexcision==0.1.1
```

Confirm the installed version with:

```bash
nexcise --version
```

## Bioconda

The recommended installation method for Conda-based bioinformatics environments is Bioconda:

```bash
conda install -c conda-forge -c bioconda nexcision
```

Confirm the installed version with:

```bash
nexcise --version
```

## Install the stable tagged release from GitHub

The current stable software release is NEXCISION v0.1.1.

Install that exact release directly from GitHub:

```bash
python -m pip install \
  git+https://github.com/RhysWhite/nexcision.git@v0.1.1
```

Or clone the repository and install the tagged release locally:

```bash
git clone https://github.com/RhysWhite/nexcision.git
cd nexcision
git checkout v0.1.1
python -m pip install .
```

Then confirm the installation:

```bash
nexcise --version
```

Expected output:

```text
NEXCISION 0.1.1
```

## Install the current development branch

The `main` branch may contain documentation, packaging, or development changes made after the most recent tagged software release.

To install the current `main` branch:

```bash
python -m pip install \
  git+https://github.com/RhysWhite/nexcision.git
```

For reproducible analyses, prefer a tagged release or a versioned package rather than an unpinned development branch.

## Command-line entry point

Installation provides the `nexcise` command:

```bash
nexcise --help
```

The command accepts two required positional inputs:

```text
nexcise NEXUS REGIONS
```

where:

- `NEXUS` is the input NEXUS matrix;
- `REGIONS` is a whitespace-delimited file defining genomic intervals to remove.

Output paths, coordinate parsing, dimension handling, and explicit safety opt-ins are controlled with command-line options described in the remaining documentation.

## Supported Python versions

The package metadata require Python 3.10 or later.

The repository test workflow runs the test suite on Python 3.10–3.14 across Ubuntu, macOS, and Windows. A separate packaging job builds and installs a wheel, reruns the tests against that installed wheel, and reproduces the bundled example.

## Archival release

NEXCISION v0.1.1 is archived in Zenodo:

**DOI:** [10.5281/zenodo.21936049](https://doi.org/10.5281/zenodo.21936049)
