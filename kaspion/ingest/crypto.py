"""Bank credentials at rest: AES-256-GCM, key file with 0600 perms.
Never commit, never log, never pass credentials via argv."""
from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DATA = Path(__file__).resolve().parents[2] / "data"
KEY_FILE = DATA / ".kaspion_key"
CRED_FILE = DATA / "credentials.json.enc"


def _key() -> bytes:
    DATA.mkdir(exist_ok=True)
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(AESGCM.generate_key(bit_length=256))
        os.chmod(KEY_FILE, 0o600)
    return KEY_FILE.read_bytes()


def save_credentials(creds: dict) -> None:
    """creds shape:
    {"leumi": {"type": "bank",        "credentials": {"username": "...", "password": "..."}},
     "max":   {"type": "credit_card", "credentials": {"username": "...", "password": "..."}}}
    """
    nonce = os.urandom(12)
    blob = AESGCM(_key()).encrypt(nonce, json.dumps(creds).encode(), None)
    CRED_FILE.write_bytes(nonce + blob)
    os.chmod(CRED_FILE, 0o600)


def load_credentials() -> dict:
    raw = CRED_FILE.read_bytes()
    return json.loads(AESGCM(_key()).decrypt(raw[:12], raw[12:], None))


# israeli-bank-scrapers credential fields per institution (see docs/SCRAPER_SETUP.md)
COMPANY_FIELDS: dict[str, tuple[str, list[str]]] = {
    "leumi":    ("bank",        ["username", "password"]),
    "hapoalim": ("bank",        ["userCode", "password"]),
    "max":      ("credit_card", ["username", "password"]),
    "isracard": ("credit_card", ["id", "card6Digits", "password"]),
    "visaCal":  ("credit_card", ["username", "password"]),
}

if __name__ == "__main__":
    # interactive setup: python3 -m kaspion.ingest.crypto
    import getpass

    print(f"known companies: {', '.join(COMPANY_FIELDS)}")
    # start from what's already saved and MERGE — adding a second institution must
    # never silently wipe the first one (save_credentials rewrites the whole file).
    creds: dict = {}
    if CRED_FILE.exists():
        try:
            creds = load_credentials()
            print(f"already saved: {', '.join(creds)} (re-entering one replaces just that one)")
        except Exception:  # noqa: BLE001 - unreadable blob shouldn't block re-entry
            print("warning: existing credentials could not be read — they will be replaced")
    while True:
        company = input("company id (empty to finish): ").strip()
        if not company:
            break
        if company in COMPANY_FIELDS:
            acc_type, fields = COMPANY_FIELDS[company]
            print(f"  ({acc_type}; needs: {', '.join(fields)})")
        else:
            acc_type = input("  account type [bank/credit_card]: ").strip()
            fields = [f.strip() for f in input("  credential field names (comma-separated): ").split(",")]
        values = {
            f: (getpass.getpass(f"  {f} (hidden): ") if "password" in f.lower() else input(f"  {f}: ").strip())
            for f in fields
        }
        creds[company] = {"type": acc_type, "credentials": values}
    if creds:
        save_credentials(creds)
        print(f"encrypted credentials saved for: {', '.join(creds)}")
