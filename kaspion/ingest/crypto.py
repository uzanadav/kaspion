"""Bank credentials at rest: AES-256-GCM, key file with 0600 perms.
Never commit, never log, never pass credentials via argv."""
from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from kaspion.paths import data_dir

DATA = data_dir()
KEY_FILE = DATA / ".kaspion_key"
CRED_FILE = DATA / "credentials.json.enc"


def _restrict(path: Path) -> None:
    # os.chmod's permission bits are a POSIX-only concept — Windows silently ignores
    # everything but the read-only flag, so this is a no-op there rather than a broken
    # attempt at one. The file still inherits the user profile's own ACL on Windows,
    # which is the practical protection; hand-rolling ACL code here would be worse than
    # relying on it.
    if os.name != "nt":
        os.chmod(path, 0o600)


def _key() -> bytes:
    DATA.mkdir(parents=True, exist_ok=True)
    if not KEY_FILE.exists():
        KEY_FILE.write_bytes(AESGCM.generate_key(bit_length=256))
        _restrict(KEY_FILE)
    return KEY_FILE.read_bytes()


def save_credentials(creds: dict) -> None:
    """creds is keyed by CONNECTION id, not company id — see company_of()/
    next_connection_id() below. A company's first connection keeps the plain company id
    (e.g. "max"), so every credential file saved before multi-account support existed
    reads back unchanged. A second login to the same company gets "max:2", "max:3", ...

    {"leumi": {"type": "bank", "credentials": {"username": "...", "password": "..."},
               "label": ""},
     "max":   {"type": "credit_card", "credentials": {"username": "...", "password": "..."},
               "label": "בעל הבית"},
     "max:2": {"type": "credit_card", "credentials": {"username": "...", "password": "..."},
               "label": "אשתי"}}
    """
    nonce = os.urandom(12)
    # _key() always runs first here (it's the argument to AESGCM), and it already does
    # the DATA.mkdir — no separate one needed before this write.
    blob = AESGCM(_key()).encrypt(nonce, json.dumps(creds).encode(), None)
    CRED_FILE.write_bytes(nonce + blob)
    _restrict(CRED_FILE)


def load_credentials() -> dict:
    raw = CRED_FILE.read_bytes()
    return json.loads(AESGCM(_key()).decrypt(raw[:12], raw[12:], None))


def company_of(conn_id: str) -> str:
    """"max" -> "max"; "max:2" -> "max". The part before ':' is always the real
    israeli-bank-scrapers company id — needed for KASPION_COMPANY regardless of which
    of a company's several connections this is."""
    return conn_id.split(":", 1)[0]


def next_connection_id(creds: dict, company: str) -> str:
    """First connection to an institution keeps the plain company id — matches every
    credential file saved before multi-account support existed, so no migration is
    needed. Additional connections to the same company get :2, :3, ..."""
    existing = sum(1 for k in creds if company_of(k) == company)
    return company if existing == 0 else f"{company}:{existing + 1}"


def remove_credentials(conn_id: str) -> None:
    creds = load_credentials() if CRED_FILE.exists() else {}
    creds.pop(conn_id, None)
    save_credentials(creds)


# israeli-bank-scrapers credential fields per institution, copied verbatim from that
# library's own SCRAPERS export (see docs/SCRAPER_SETUP.md). Every entry with "blocked"
# is shown greyed out in the dashboard's add-account dialog rather than offered as a
# working login: 'isracard'/'amex' are behind reCAPTCHA, and 'oneZero' needs interactive
# 2FA enrollment a one-shot form can't do. All three stay on the file-upload path.
COMPANY_FIELDS: dict[str, dict] = {
    "leumi":            {"type": "bank", "label": "בנק לאומי",
                          "fields": ["username", "password"]},
    "oneZero":          {"type": "bank", "label": "ONE ZERO", "blocked": "2fa",
                          "fields": ["email", "password", "otpCodeRetriever",
                                     "phoneNumber", "otpLongTermToken"]},
    "hapoalim":         {"type": "bank", "label": "בנק הפועלים",
                          "fields": ["userCode", "password"]},
    "mizrahi":          {"type": "bank", "label": "בנק מזרחי טפחות",
                          "fields": ["username", "password"]},
    "discount":         {"type": "bank", "label": "בנק דיסקונט",
                          "fields": ["id", "password", "num"]},
    "mercantile":       {"type": "bank", "label": "בנק מרכנתיל",
                          "fields": ["id", "password", "num"]},
    "otsarHahayal":     {"type": "bank", "label": "בנק אוצר החייל",
                          "fields": ["username", "password"]},
    "union":            {"type": "bank", "label": "בנק יוניון",
                          "fields": ["username", "password"]},
    "beinleumi":        {"type": "bank", "label": "הבינלאומי",
                          "fields": ["username", "password"]},
    "massad":           {"type": "bank", "label": "בנק מסד",
                          "fields": ["username", "password"]},
    "yahav":            {"type": "bank", "label": "בנק יהב",
                          "fields": ["username", "nationalID", "password"]},
    "beyahadBishvilha": {"type": "bank", "label": "ביחד בשבילך",
                          "fields": ["id", "password"]},
    "behatsdaa":        {"type": "bank", "label": "בהצדעה",
                          "fields": ["id", "password"]},
    "pagi":             {"type": "bank", "label": "בנק פאגי",
                          "fields": ["username", "password"]},
    "max":              {"type": "credit_card", "label": "מקס",
                          "fields": ["username", "password"]},
    "visaCal":          {"type": "credit_card", "label": "כאל",
                          "fields": ["username", "password"]},
    "isracard":         {"type": "credit_card", "label": "ישראכרט", "blocked": "recaptcha",
                          "fields": ["id", "card6Digits", "password"]},
    "amex":             {"type": "credit_card", "label": "אמריקן אקספרס", "blocked": "recaptcha",
                          "fields": ["id", "card6Digits", "password"]},
}

FIELD_LABELS = {
    "username": "שם משתמש", "password": "סיסמה", "userCode": "קוד משתמש",
    "id": 'ת"ז', "card6Digits": "6 ספרות אחרונות של הכרטיס",
    "num": "מספר מזהה", "nationalID": 'ת"ז', "email": "אימייל",
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
        # only ids israeli-bank-scrapers itself defines can ever scrape successfully
        # (see tests/test_company_fields.py) — no free-text fallback for anything else
        if company not in COMPANY_FIELDS:
            print(f"  unknown company id — pick one of: {', '.join(COMPANY_FIELDS)}")
            continue
        acc_type, fields = COMPANY_FIELDS[company]["type"], COMPANY_FIELDS[company]["fields"]
        print(f"  ({acc_type}; needs: {', '.join(fields)})")
        values = {
            f: (getpass.getpass(f"  {f} (hidden): ") if "password" in f.lower()
                else input(f"  {f}: ").strip())
            for f in fields
        }
        creds[company] = {"type": acc_type, "credentials": values}
    if creds:
        save_credentials(creds)
        print(f"encrypted credentials saved for: {', '.join(creds)}")
