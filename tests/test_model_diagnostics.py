"""Regression tests for model selection and offline diagnostics."""
import unittest
from unittest.mock import patch

from core import model_config
from core.model_diagnostics import diagnostic_report


class ModelSelectionTests(unittest.TestCase):
    def test_empty_primary_override_is_not_a_model(self):
        with patch.object(model_config, "_saved_models", return_value=""):
            with patch.dict("os.environ", {"ASSISTANT_TEXT_FALLBACK_MODEL": "fallback-only"}, clear=True):
                self.assertEqual(model_config.get_text_models()[0], "fallback-only")
                self.assertNotIn("", model_config.get_text_models())

    def test_duplicate_live_model_is_not_retried(self):
        with patch.object(model_config, "_saved_models", return_value=""):
            with patch.dict("os.environ", {
                "ASSISTANT_LIVE_MODEL": "same-live",
                "ASSISTANT_LIVE_FALLBACK_MODEL": "same-live",
            }, clear=True):
                self.assertEqual(model_config.get_live_models(), ("same-live",))

    def test_diagnostics_never_prints_credentials(self):
        with patch.object(model_config, "_saved_models", return_value=""):
            with patch.dict("os.environ", {"GEMINI_API_KEY": "secret-token"}, clear=True):
                report = diagnostic_report()
                self.assertIn("Live model priority", report)
                self.assertNotIn("secret-token", report)


if __name__ == "__main__":
    unittest.main()
