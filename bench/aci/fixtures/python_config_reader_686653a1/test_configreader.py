"""Tests for configreader's error-reporting contract.

A missing *setting key* must surface as ``KeyError``; only a genuinely
missing config *file* may be reported as ``FileNotFoundError``.
"""

import os
import tempfile
import unittest

import configreader


CONFIG_TEXT = (
    "# sample configuration\n"
    "host = example.com\n"
    "port = 8080\n"
    "debug = true\n"
)


class ConfigReaderErrorContractTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = tmp.name
        self.existing_path = os.path.join(self.directory, "app.cfg")
        self.missing_path = os.path.join(self.directory, "absent.cfg")
        with open(self.existing_path, "w", encoding="utf-8") as handle:
            handle.write(CONFIG_TEXT)

    def capture(self, path, key):
        try:
            configreader.read_setting(path, key)
        except Exception as exc:  # noqa: BLE001 - captured deliberately
            return exc
        return None

    # -- missing key -------------------------------------------------

    def test_missing_key_raises_key_error(self):
        error = self.capture(self.existing_path, "nonexistent_key")
        self.assertIsNotNone(error)
        self.assertIsInstance(error, KeyError)

    def test_missing_key_error_type_name(self):
        error = self.capture(self.existing_path, "timeout")
        self.assertIsNotNone(error)
        self.assertEqual(type(error).__name__, "KeyError")

    def test_missing_key_is_not_reported_as_missing_file(self):
        error = self.capture(self.existing_path, "missing_setting")
        self.assertIsNotNone(error)
        self.assertNotIsInstance(error, FileNotFoundError)
        self.assertNotEqual(type(error), FileNotFoundError)

    def test_missing_key_message_names_the_key(self):
        with self.assertRaises(KeyError) as ctx:
            configreader.read_setting(self.existing_path, "retries")
        self.assertIn("retries", str(ctx.exception))

    def test_missing_key_message_does_not_claim_file_is_missing(self):
        error = self.capture(self.existing_path, "log_level")
        self.assertIsNotNone(error)
        self.assertNotIn("config file not found", str(error))

    def test_missing_key_message_does_not_mention_files_at_all(self):
        error = self.capture(self.existing_path, "absent_option")
        self.assertIsNotNone(error)
        self.assertIn("absent_option", str(error))
        self.assertNotIn("file", str(error).lower())

    # -- missing file ------------------------------------------------

    def test_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            configreader.read_setting(self.missing_path, "host")

    def test_missing_file_message_mentions_the_path(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            configreader.read_setting(self.missing_path, "port")
        self.assertIn(self.missing_path, str(ctx.exception))

    def test_missing_file_message_does_not_mask_key_errors(self):
        key_error = self.capture(self.existing_path, "no_such_key")
        file_error = self.capture(self.missing_path, "host")
        self.assertIsNotNone(key_error)
        self.assertIsNotNone(file_error)
        self.assertIsInstance(key_error, KeyError)
        self.assertIsInstance(file_error, FileNotFoundError)
        self.assertNotEqual(str(key_error), str(file_error))

    # -- happy path --------------------------------------------------

    def test_read_setting_returns_values(self):
        self.assertEqual(
            configreader.read_setting(self.existing_path, "host"),
            "example.com",
        )
        self.assertEqual(
            configreader.read_setting(self.existing_path, "port"),
            "8080",
        )
        self.assertEqual(
            configreader.read_setting(self.existing_path, "debug"),
            "true",
        )

    def test_read_settings_parses_all_pairs(self):
        settings = configreader.read_settings(self.existing_path)
        self.assertEqual(settings.get("host"), "example.com")
        self.assertEqual(settings.get("port"), "8080")
        self.assertEqual(settings.get("debug"), "true")
        self.assertEqual(len(settings), 3)


if __name__ == "__main__":
    unittest.main()
