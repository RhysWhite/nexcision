from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from nexcision.cli import main


class CliTests(unittest.TestCase):
    def test_cli_runs_example(self) -> None:
        nexus_text = """#NEXUS
Begin data;
Dimensions ntax=2 nchar=2;
Matrix
ref_10 01
ref_20 10
;
End;
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nexus = root / "input.nex"
            regions = root / "regions.tsv"
            output = root / "filtered.nex"
            counts = root / "counts.tsv"
            nexus.write_text(nexus_text, encoding="utf-8")
            regions.write_text("20\t20\tremove\n", encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
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

            self.assertEqual(return_code, 0)
            self.assertIn("Rows removed: 1", stdout.getvalue())
            self.assertIn("Dimensions ntax=1 nchar=2;", output.read_text())

    def test_cli_returns_two_for_invalid_input(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            return_code = main(["missing.nex", "missing.tsv"])
        self.assertEqual(return_code, 2)
        self.assertIn("ERROR:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
