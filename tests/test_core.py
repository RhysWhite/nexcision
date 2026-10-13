from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from nexcision.core import (
    NexusFilterError,
    Region,
    filter_nexus_file,
    filter_nexus_text,
    load_regions,
)


NEXUS = """#NEXUS
Begin data;
    Dimensions ntax=5 nchar=4;
    Format datatype=standard symbols=\"01\" gap=-;
    Matrix
    CP013831_100 0101
    CP013831_180 1101
    CP013831_250 0001
    CP013831_320 1110
    CP013831_500 0011
    ;
End;
"""

TRANSPOSED_NEXUS = """#NEXUS
Begin data;
    Dimensions ntax=4 nchar=5;
    Format datatype=standard symbols=\"01\" transpose=yes;
    Matrix
    CP013831_100 0101
    CP013831_180 1101
    CP013831_250 0001
    CP013831_320 1110
    CP013831_500 0011
    ;
End;
"""


class LoadRegionsTests(unittest.TestCase):
    def test_loads_header_comments_names_and_reversed_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "regions.tsv"
            path.write_text(
                "start\tend\tname\n# comment\n260\t170\tblock_1\n300 350\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_regions(path),
                [
                    Region(1, 170, 260, "block_1"),
                    Region(2, 300, 350, "region_2"),
                ],
            )

    def test_rejects_empty_regions_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "regions.tsv"
            path.write_text("start\tend\n", encoding="utf-8")
            with self.assertRaisesRegex(NexusFilterError, "No valid regions"):
                load_regions(path)

    def test_rejects_coordinate_below_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "regions.tsv"
            path.write_text("0\t10\n", encoding="utf-8")
            with self.assertRaisesRegex(NexusFilterError, "below 1"):
                load_regions(path)


class FilterTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.regions = [
            Region(1, 170, 260, "block_1"),
            Region(2, 240, 350, "block_2"),
        ]

    def test_filters_rows_counts_overlaps_and_updates_ntax(self) -> None:
        filtered, counts, result = filter_nexus_text(NEXUS, self.regions)

        self.assertIn("Dimensions ntax=2 nchar=4;", filtered)
        self.assertIn("CP013831_100", filtered)
        self.assertIn("CP013831_500", filtered)
        self.assertNotIn("CP013831_180", filtered)
        self.assertNotIn("CP013831_250", filtered)
        self.assertNotIn("CP013831_320", filtered)
        self.assertEqual(result.rows_removed, 3)
        self.assertEqual(result.rows_kept, 2)
        self.assertEqual(result.dimension_updated, "ntax")
        self.assertEqual((result.dimension_before, result.dimension_after), (5, 2))
        self.assertIn("1\tblock_1\t170\t260\t2", counts)
        self.assertIn("2\tblock_2\t240\t350\t2", counts)

    def test_auto_updates_nchar_for_transposed_matrix(self) -> None:
        filtered, _, result = filter_nexus_text(TRANSPOSED_NEXUS, self.regions)
        self.assertIn("Dimensions ntax=4 nchar=2;", filtered)
        self.assertEqual(result.dimension_updated, "nchar")

    def test_explicit_dimension_override(self) -> None:
        filtered, _, result = filter_nexus_text(
            TRANSPOSED_NEXUS,
            self.regions,
            update_dimension="ntax",
        )
        self.assertIn("Dimensions ntax=4 nchar=5;", filtered)
        self.assertIsNone(result.dimension_updated)
        self.assertEqual(len(result.warnings), 1)

    def test_dimension_update_can_be_disabled(self) -> None:
        filtered, _, result = filter_nexus_text(
            NEXUS,
            self.regions,
            update_dimension="none",
        )
        self.assertIn("Dimensions ntax=5 nchar=4;", filtered)
        self.assertIsNone(result.dimension_updated)
        self.assertEqual(result.warnings, ())

    def test_handles_inline_matrix_terminator(self) -> None:
        inline = NEXUS.replace(
            "    CP013831_500 0011\n    ;",
            "    CP013831_500 0011;",
        )
        filtered, _, result = filter_nexus_text(
            inline,
            [Region(1, 500, 500, "last")],
        )
        self.assertEqual(result.rows_removed, 1)
        self.assertRegex(filtered, r"\n;\nEnd;")

    def test_rejects_unparsed_rows_by_default(self) -> None:
        malformed = NEXUS.replace(
            "    CP013831_250 0001",
            "    unexpected_row 0001",
        )
        with self.assertRaisesRegex(NexusFilterError, "does not match"):
            filter_nexus_text(malformed, self.regions)

    def test_preserves_unparsed_rows_and_counts_them_in_ntax(self) -> None:
        malformed = NEXUS.replace(
            "    CP013831_250 0001",
            "    unexpected_row 0001",
        )
        filtered, _, result = filter_nexus_text(
            malformed,
            self.regions,
            allow_unparsed=True,
        )
        self.assertIn("unexpected_row", filtered)
        self.assertIn("Dimensions ntax=3 nchar=4;", filtered)
        self.assertEqual(result.unparsed_rows, 1)
        self.assertEqual(result.rows_kept, 3)

    def test_leaves_mismatched_dimension_unchanged(self) -> None:
        mismatched = NEXUS.replace("ntax=5", "ntax=99")
        filtered, _, result = filter_nexus_text(mismatched, self.regions)
        self.assertIn("ntax=99", filtered)
        self.assertIsNone(result.dimension_updated)
        self.assertEqual(len(result.warnings), 1)

    def test_custom_position_regex(self) -> None:
        custom = NEXUS.replace("CP013831_", "site:")
        filtered, _, result = filter_nexus_text(
            custom,
            [Region(1, 180, 180, "one")],
            position_pattern=r"site:(\d+)$",
        )
        self.assertNotIn("site:180", filtered)
        self.assertEqual(result.rows_removed, 1)

    def test_rejects_multiple_reference_labels_even_if_positions_differ(self) -> None:
        mixed = TRANSPOSED_NEXUS.replace("CP013831_500", "OTHER_REF_500")
        with self.assertRaisesRegex(
            NexusFilterError, "mixed reference coordinate axes cannot be filtered safely"
        ):
            filter_nexus_text(mixed, self.regions)

    def test_rejects_different_contigs_at_same_position(self) -> None:
        mixed = TRANSPOSED_NEXUS.replace("CP013831_180", "plasmid_100")
        with self.assertRaisesRegex(NexusFilterError, "Matrix line 7"):
            filter_nexus_text(mixed, [Region(1, 100, 100, "same-position")])

    def test_rejects_mixed_refs_even_with_allow_unparsed(self) -> None:
        mixed = TRANSPOSED_NEXUS.replace("CP013831_500", "OTHER_REF_500")
        with self.assertRaisesRegex(NexusFilterError, "mixed reference coordinate axes"):
            filter_nexus_text(mixed, self.regions, allow_unparsed=True)

    def test_rejects_mixed_refs_with_custom_coordinate_regex(self) -> None:
        mixed = TRANSPOSED_NEXUS.replace("CP013831_", "chrA:site:")
        mixed = mixed.replace("chrA:site:500", "chrB:site:500")
        with self.assertRaisesRegex(NexusFilterError, "mixed reference coordinate axes"):
            filter_nexus_text(
                mixed,
                self.regions,
                position_pattern=r"site:(\d+)$",
            )

    def test_semicolon_in_standalone_comment_does_not_terminate_matrix(self) -> None:
        matrix = TRANSPOSED_NEXUS.replace(
            "    CP013831_180 1101",
            "    [note; this is not a MATRIX terminator]\n    CP013831_180 1101",
        )
        filtered, _, result = filter_nexus_text(matrix, self.regions)
        self.assertEqual((result.rows_removed, result.rows_kept), (3, 2))
        self.assertIn("[note; this is not a MATRIX terminator]", filtered)
        self.assertIn("Dimensions ntax=4 nchar=2;", filtered)

    def test_comments_spanning_multiple_lines_and_nested_comments(self) -> None:
        matrix = TRANSPOSED_NEXUS.replace(
            "    CP013831_180 1101",
            "    [outer note;\n       [inner MATRIX; END;]\n       still note]\n    CP013831_180 1101",
        )
        filtered, _, result = filter_nexus_text(matrix, self.regions)
        self.assertEqual(result.rows_removed, 3)
        self.assertIn("[inner MATRIX; END;]", filtered)

    def test_ignored_matrix_command_in_comment(self) -> None:
        matrix = TRANSPOSED_NEXUS.replace(
            "Begin data;", "[\nMATRIX\n]\nBegin data;"
        )
        filtered, _, result = filter_nexus_text(matrix, self.regions)
        self.assertEqual(result.rows_removed, 3)
        self.assertIn("[\nMATRIX\n]", filtered)

    def test_ignored_matrix_command_in_quoted_string(self) -> None:
        matrix = TRANSPOSED_NEXUS.replace(
            "Begin data;", "[quoted tokens are not structural]\n'MATRIX'\nBegin data;"
        )
        _, _, result = filter_nexus_text(matrix, self.regions)
        self.assertEqual(result.rows_removed, 3)

    def test_comment_text_does_not_prevent_dimension_update(self) -> None:
        matrix = TRANSPOSED_NEXUS.replace(
            "    Dimensions", "    [nchar=99; DIMENSIONS nchar=77]\n    Dimensions"
        )
        filtered, _, result = filter_nexus_text(matrix, self.regions)
        self.assertEqual(result.dimension_updated, "nchar")
        self.assertEqual(result.warnings, ())
        self.assertIn("[nchar=99; DIMENSIONS nchar=77]", filtered)
        self.assertIn("Dimensions ntax=4 nchar=2;", filtered)

    def test_transpose_detection_ignores_comments_and_quoted_text(self) -> None:
        matrix = NEXUS.replace(
            '    Format datatype=standard symbols="01" gap=-;',
            '    [FORMAT transpose=yes;]\n'
            '    Format datatype=standard symbols="TRANSPOSE=yes;" gap=-;',
        )
        filtered, _, result = filter_nexus_text(matrix, self.regions)
        self.assertEqual(result.dimension_updated, "ntax")
        self.assertIn("Dimensions ntax=2 nchar=4;", filtered)

    def test_real_transpose_with_inline_comments_is_recognized(self) -> None:
        matrix = TRANSPOSED_NEXUS.replace(
            "transpose=yes;", "[note;] transpose = yes;"
        )
        filtered, _, result = filter_nexus_text(matrix, self.regions)
        self.assertEqual(result.dimension_updated, "nchar")
        self.assertIn("nchar=2;", filtered)

    def test_removed_row_preserves_inline_comment_and_semicolon(self) -> None:
        matrix = TRANSPOSED_NEXUS.replace(
            "    CP013831_180 1101",
            "    [keep; this comment] CP013831_180 1101 [also; keep]",
        )
        filtered, _, result = filter_nexus_text(matrix, self.regions)
        self.assertEqual(result.rows_removed, 3)
        self.assertNotIn("CP013831_180", filtered)
        self.assertIn("[keep; this comment]", filtered)
        self.assertIn("[also; keep]", filtered)

    def test_removed_last_row_preserves_real_terminator_and_comment(self) -> None:
        matrix = TRANSPOSED_NEXUS.replace(
            "    CP013831_500 0011\n    ;",
            "    CP013831_500 0011 [note; not the delimiter]; [after;]",
        )
        filtered, _, result = filter_nexus_text(
            matrix, [Region(1, 500, 500, "last")]
        )
        self.assertEqual(result.rows_removed, 1)
        self.assertNotIn("CP013831_500", filtered)
        self.assertIn("[note; not the delimiter]; [after;]", filtered)
        self.assertIn("End;", filtered)

    def test_quoted_semicolon_and_doubled_quote_not_a_terminator(self) -> None:
        matrix = TRANSPOSED_NEXUS.replace(
            "    CP013831_100 0101",
            "    CP013831_100 'a'';b'",
        )
        filtered, _, result = filter_nexus_text(matrix, self.regions)
        self.assertEqual(result.rows_removed, 3)
        self.assertIn("CP013831_100 'a'';b'", filtered)

    def test_unterminated_nexus_comment_rejected(self) -> None:
        matrix = TRANSPOSED_NEXUS + "[unclosed comment;\n"
        with self.assertRaisesRegex(NexusFilterError, "Unterminated NEXUS bracket comment"):
            filter_nexus_text(matrix, self.regions)

    def test_unmatched_nexus_closing_bracket_rejected(self) -> None:
        matrix = TRANSPOSED_NEXUS.replace(
            "    CP013831_180 1101", "    CP013831_180 1101 ]"
        )
        with self.assertRaisesRegex(NexusFilterError, "Unmatched NEXUS comment"):
            filter_nexus_text(matrix, self.regions)

    def test_rejects_multiple_matrix_blocks(self) -> None:
        duplicated = NEXUS + NEXUS
        with self.assertRaisesRegex(NexusFilterError, "More than one MATRIX"):
            filter_nexus_text(duplicated, self.regions)

    def test_rejects_unterminated_matrix(self) -> None:
        unterminated = NEXUS.replace("    ;\nEnd;", "End;")
        with self.assertRaisesRegex(NexusFilterError, "not terminated"):
            filter_nexus_text(unterminated, self.regions)


class FilterFileTests(unittest.TestCase):
    def test_writes_outputs_report_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nexus = root / "input.nex"
            regions = root / "regions.tsv"
            output = root / "filtered.nex"
            counts = root / "counts.tsv"
            report = root / "report.json"
            nexus.write_text(NEXUS, encoding="utf-8")
            regions.write_text(
                "start\tend\tname\n170\t260\tblock\n",
                encoding="utf-8",
            )

            result = filter_nexus_file(
                nexus,
                regions,
                output,
                counts,
                report_path=report,
            )
            self.assertEqual(result.rows_removed, 2)
            self.assertTrue(output.exists())
            self.assertTrue(counts.exists())
            self.assertTrue(report.exists())

            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["software"]["name"], "NEXCISION")
            expected_hash = hashlib.sha256(output.read_bytes()).hexdigest()
            self.assertEqual(
                payload["outputs"]["filtered_nexus"]["sha256"],
                expected_hash,
            )

            with self.assertRaisesRegex(NexusFilterError, "already exists"):
                filter_nexus_file(nexus, regions, output, counts)

    def test_mixed_reference_labels_fail_without_writing_any_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nexus = root / "input.nex"
            regions = root / "regions.tsv"
            output = root / "filtered.nex"
            counts = root / "counts.tsv"
            report = root / "report.json"
            nexus.write_text(
                TRANSPOSED_NEXUS.replace("CP013831_500", "plasmid_500"),
                encoding="utf-8",
            )
            regions.write_text("500\t500\n", encoding="utf-8")
            with self.assertRaisesRegex(NexusFilterError, "mixed reference coordinate axes"):
                filter_nexus_file(nexus, regions, output, counts, report_path=report)
            for path in (output, counts, report):
                self.assertFalse(path.exists(), str(path))

    def test_comment_parse_failure_leaves_no_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nexus = root / "input.nex"
            regions = root / "regions.tsv"
            nexus.write_text(TRANSPOSED_NEXUS + "[unclosed;\n", encoding="utf-8")
            regions.write_text("170\t260\n", encoding="utf-8")
            paths = (root / "filtered.nex", root / "counts.tsv", root / "report.json")
            with self.assertRaisesRegex(NexusFilterError, "Unterminated NEXUS"):
                filter_nexus_file(nexus, regions, paths[0], paths[1], report_path=paths[2])
            for path in paths:
                self.assertFalse(path.exists())

    def test_rejects_duplicate_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nexus = root / "input.nex"
            regions = root / "regions.tsv"
            output = root / "same.out"
            nexus.write_text(NEXUS, encoding="utf-8")
            regions.write_text("170\t260\n", encoding="utf-8")
            with self.assertRaisesRegex(NexusFilterError, "Every output path"):
                filter_nexus_file(nexus, regions, output, output)


if __name__ == "__main__":
    unittest.main()
