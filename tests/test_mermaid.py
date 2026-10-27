import logging
import unittest
from unittest.mock import patch

from madblog.markdown._processors import mermaid as mermaid_mod


class ResolveMermaidCmdTest(unittest.TestCase):
    """Tests for the once-per-process Mermaid CLI resolution."""

    def setUp(self):
        mermaid_mod.resolve_mermaid_cmd.cache_clear()
        self.addCleanup(mermaid_mod.resolve_mermaid_cmd.cache_clear)

    def test_missing_binaries_warns_once(self):
        """The missing-dependency warning is only logged once per process."""
        with patch.object(mermaid_mod.shutil, "which", return_value=None):
            with self.assertLogs(mermaid_mod.logger, level=logging.WARNING) as cm:
                self.assertIsNone(mermaid_mod.resolve_mermaid_cmd())
                self.assertIsNone(mermaid_mod.resolve_mermaid_cmd())

        warnings = [r for r in cm.records if r.levelno == logging.WARNING]
        self.assertEqual(1, len(warnings))
        self.assertIn("mmdc", warnings[0].getMessage())

    def test_preprocessor_instantiation_warns_once(self):
        """Repeated preprocessor instantiation doesn't repeat the warning."""
        with patch.object(mermaid_mod.shutil, "which", return_value=None):
            with self.assertLogs(mermaid_mod.logger, level=logging.WARNING) as cm:
                mermaid_mod.MermaidPreprocessor()
                mermaid_mod.MermaidPreprocessor()
                mermaid_mod.MermaidPreprocessor()

        warnings = [r for r in cm.records if r.levelno == logging.WARNING]
        self.assertEqual(1, len(warnings))

    def test_mmdc_takes_precedence(self):
        """mmdc on PATH wins over the npx fallback."""
        with patch.object(
            mermaid_mod.shutil,
            "which",
            side_effect=lambda b: "/usr/bin/mmdc" if b == "mmdc" else None,
        ):
            self.assertEqual(("mmdc",), mermaid_mod.resolve_mermaid_cmd())

    def test_npx_fallback(self):
        """npx is used when mmdc is not on PATH."""
        with patch.object(
            mermaid_mod.shutil,
            "which",
            side_effect=lambda b: "/usr/bin/npx" if b == "npx" else None,
        ):
            self.assertEqual(
                ("npx", "-y", "@mermaid-js/mermaid-cli"),
                mermaid_mod.resolve_mermaid_cmd(),
            )


if __name__ == "__main__":
    unittest.main()
