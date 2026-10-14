"""Test isolation: all state goes to a throwaway folder, never the real data/."""
import os
import tempfile

from cryptography.fernet import Fernet

os.environ["GROWTH_OS_DATA"] = tempfile.mkdtemp(prefix="kgos-test-")
os.environ.setdefault("GROWTH_OS_SECRET_KEY", Fernet.generate_key().decode())
