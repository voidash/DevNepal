"""Throwaway test-only RSA fixtures. These keys protect nothing (GIT-001)."""

from pathlib import Path

DATA_DIR = Path(__file__).parent

TEST_APP_KEY_PEM = (DATA_DIR / "test_app_key_pkcs1.pem").read_text(encoding="utf-8")
TEST_APP_KEY_PKCS8_PEM = (DATA_DIR / "test_app_key_pkcs8.pem").read_text(encoding="utf-8")
