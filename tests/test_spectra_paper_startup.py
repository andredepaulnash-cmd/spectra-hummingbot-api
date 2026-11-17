"""Regression tests for Spectra's paper-only connector startup policy.

These tests ensure paper startup is driven by an explicit allowlist rather
than by stored live credential filenames. They intentionally do not initialize
connectors or access exchange credentials.
"""
import unittest
from unittest.mock import patch

from services.unified_connector_service import UnifiedConnectorService


class PaperConnectorStartupSelectionTests(unittest.TestCase):
    def setUp(self):
        self.service = UnifiedConnectorService.__new__(UnifiedConnectorService)
        self.credential_scans = []
        self.service.list_available_credentials = lambda account: (
            self.credential_scans.append(account) or ["kraken"]
        )

    @patch(
        "services.unified_connector_service.configured_paper_connectors",
        return_value=("kraken_paper_trade",),
    )
    @patch("services.unified_connector_service.paper_only_enabled", return_value=True)
    def test_paper_mode_uses_allowlist_not_live_credential_files(
        self, _paper_mode, _configured
    ):
        selected = self.service.list_connectors_to_initialize("master_account")

        self.assertEqual(selected, ["kraken_paper_trade"])
        self.assertEqual(self.credential_scans, [])

    @patch(
        "services.unified_connector_service.configured_paper_connectors",
        return_value=("kraken_paper_trade",),
    )
    @patch("services.unified_connector_service.paper_only_enabled", return_value=True)
    def test_paper_mode_does_not_initialize_connectors_for_other_accounts(
        self, _paper_mode, _configured
    ):
        selected = self.service.list_connectors_to_initialize("secondary_account")

        self.assertEqual(selected, [])
        self.assertEqual(self.credential_scans, [])

    @patch("services.unified_connector_service.paper_only_enabled", return_value=False)
    def test_live_mode_retains_existing_credential_discovery(self, _paper_mode):
        selected = self.service.list_connectors_to_initialize("master_account")

        self.assertEqual(selected, ["kraken"])
        self.assertEqual(self.credential_scans, ["master_account"])


if __name__ == "__main__":
    unittest.main()
