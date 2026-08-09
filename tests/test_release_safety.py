from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from nexcision.cli import main
from nexcision.core import (
    NexusFilterError,
    Region,
    filter_nexus_file,
    filter_nexus_text,
    load_regions,
)


TRANSPOSED_NEXUS = """#NEXUS
Begin data;
    Dimensions ntax=2 nchar=2;
    Format datatype=standard symbols="01" transpose=yes;
    Matrix
    ref_10 01
    ref_20 10
    ;
End;
"""


class EmptyOutputSafetyTests(unittest.TestCase):
    def test_rejects_removing_every_row_by_default(self) -> None:
        with self.assertRaisesRegex(NexusFilterError, "remove all"):
            filter_nexus_text(
                TRANSPOSED_NEXUS,
                [Region(1, 1, 100, "all")],
            )

    def test_allow_empty_explicitly_permits_empty_matrix(self) -> None:
        filtered, _counts, result = filter_nexus_text(
            TRANSPOSED_NEXUS,
            [Region(1, 1, 100, "all")],
            allow_empty=True,
        )

        self.assertEqual(result.rows_removed, 2)
        self.assertEqual(result.rows_kept, 0)
        self.assertIn("nchar=0", filtered)

    def test_cli_requires_allow_empty_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nexus = root / "input.nex"
            regions = root / "regions.tsv"
            output = root / "filtered.nex"
            counts = root / "counts.tsv"

            nexus.write_text(TRANSPOSED_NEXUS, encoding="utf-8")
            regions.write_text("1\t100\tall\n", encoding="utf-8")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                return_code = main(
                    [
                        str(nexus),
                        str(regions),
                        "--output",
                        str(output),
                        "--counts",
                        str(counts),
                    ]
                )

            self.assertEqual(return_code, 2)
            self.assertFalse(output.exists())
            self.assertFalse(counts.exists())

            return_code = main(
                [
                    str(nexus),
                    str(regions),
                    "--output",
                    str(output),
                    "--counts",
                    str(counts),
                    "--allow-empty",
                ]
            )

            self.assertEqual(return_code, 0)
            self.assertTrue(output.exists())
            self.assertTrue(counts.exists())


class Utf8SafetyTests(unittest.TestCase):
    def test_invalid_utf8_nexus_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nexus = root / "input.nex"
            regions = root / "regions.tsv"
            output = root / "filtered.nex"
            counts = root / "counts.tsv"

            nexus.write_bytes(b"\xff\xfe\xfa")
            regions.write_text("1\t10\n", encoding="utf-8")

            with self.assertRaises(NexusFilterError):
                filter_nexus_file(nexus, regions, output, counts)

            self.assertFalse(output.exists())
            self.assertFalse(counts.exists())

    def test_invalid_utf8_regions_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "regions.tsv"
            path.write_bytes(b"\xff\xfe\xfa")

            with self.assertRaisesRegex(NexusFilterError, "UTF-8"):
                load_regions(path)


class TransactionSafetyTests(unittest.TestCase):
    def test_nested_output_paths_are_rejected_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nexus = root / "input.nex"
            regions = root / "regions.tsv"

            output = root / "result"
            counts = output / "counts.tsv"

            nexus.write_text(TRANSPOSED_NEXUS, encoding="utf-8")
            regions.write_text("10\t10\n", encoding="utf-8")

            with self.assertRaisesRegex(NexusFilterError, "nested"):
                filter_nexus_file(
                    nexus,
                    regions,
                    output,
                    counts,
                )

            self.assertFalse(output.exists())
            self.assertFalse(counts.exists())


    def test_partial_commit_failure_leaves_no_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nexus = root / "input.nex"
            regions = root / "regions.tsv"
            output = root / "filtered.nex"
            counts = root / "counts.tsv"

            nexus.write_text(TRANSPOSED_NEXUS, encoding="utf-8")
            regions.write_text("10\t10\n", encoding="utf-8")

            import os

            real_replace = os.replace
            call_count = 0

            def fail_second_replace(source, destination):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise OSError("simulated commit failure")
                return real_replace(source, destination)

            with mock.patch(
                "nexcision.core.os.replace",
                side_effect=fail_second_replace,
            ):
                with self.assertRaisesRegex(
                    NexusFilterError,
                    "Cannot write output files",
                ):
                    filter_nexus_file(
                        nexus,
                        regions,
                        output,
                        counts,
                    )

            self.assertFalse(output.exists())
            self.assertFalse(counts.exists())


class ProvenanceSafetyTests(unittest.TestCase):
    def test_report_records_allow_empty_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nexus = root / "input.nex"
            regions = root / "regions.tsv"
            output = root / "filtered.nex"
            counts = root / "counts.tsv"
            report = root / "report.json"

            nexus.write_text(TRANSPOSED_NEXUS, encoding="utf-8")
            regions.write_text("1\t100\tall\n", encoding="utf-8")

            filter_nexus_file(
                nexus,
                regions,
                output,
                counts,
                report_path=report,
                allow_empty=True,
            )

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertIs(payload["parameters"]["allow_empty"], True)


if __name__ == "__main__":
    unittest.main()
