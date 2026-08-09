# Changelog

## 0.1.1 — 2026-08-10

- Synchronizes the public source with the implementation used in the formal NEXCISION validation.
- Rejects removal of every matrix row by default; `--allow-empty` permits this only when explicitly requested.
- Stages all requested outputs before committing them and rolls back partial writes if a multi-output operation fails.
- Handles invalid UTF-8 NEXUS and region files with controlled errors.
- Records the `allow_empty` setting in the deterministic JSON provenance report.
- Adds permanent regression tests for these safety behaviours.

## 0.1.0 — 2026-07-21

- Initial NEXCISION release.
- Inclusive region-based row excision with overlap-aware counts.
- Automatic `ntax` or transposed-matrix `nchar` correction.
- Strict validation and overwrite protection.
- Optional deterministic JSON provenance report with SHA-256 checksums.
- Example data, unit tests, GitHub Actions, citation metadata, and MIT licence.
