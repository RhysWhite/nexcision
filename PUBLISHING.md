# Publishing NEXCISION

This document records the release procedure for NEXCISION.

## Before creating a release

1. Confirm that `main` is clean and synchronized with `origin/main`.

2. Run the full unit-test suite:

   ```bash
   python -m unittest discover -s tests -v
   ```

3. Reproduce the bundled example and compare both generated outputs with the expected files.

4. Build an installable wheel, install it into a clean environment, confirm the reported version, and rerun the test suite against the installed wheel.

5. Confirm that the release version agrees in:

   - `pyproject.toml`;
   - `src/nexcision/_version.py`;
   - `CITATION.cff`;
   - `CHANGELOG.md`.

6. Run:

   ```bash
   git diff --check
   ```

7. Push the release-preparation commit and confirm that GitHub Actions passes.

8. If the release is to be archived automatically by Zenodo, confirm that the GitHub repository is enabled in the Zenodo GitHub integration before publishing the GitHub release.

## Create the tag

Create an annotated tag from the audited release commit:

```bash
git tag -a vX.Y.Z -m "NEXCISION vX.Y.Z"
git push origin vX.Y.Z
```

Verify that the local and remote annotated tag both dereference to the intended release commit.

## Create the GitHub release

Create a normal GitHub release from the existing annotated tag.

The GitHub release must use the audited tag and must not move or recreate an earlier release tag.

## After publication

1. Confirm that the GitHub release points to the expected tag and commit.
2. Confirm that Zenodo has archived the release, when applicable.
3. Record the Zenodo DOI in public documentation where appropriate.
4. Confirm that downstream distribution metadata, including Bioconda, refers to the intended NEXCISION version.
