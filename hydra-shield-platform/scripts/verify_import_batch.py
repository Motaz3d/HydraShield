#!/usr/bin/env python3
"""Verify an external-research import batch before it enters the CRM.

For every contact in a marketing/imports/*.json seed file, fetch the
declared source_url and check the email literally appears on the page.
When it does not, try standard imprint/contact paths on the official
domain; if the email is found there, the source_url is corrected.
Contacts whose email cannot be found on the official domain are dropped
— unverified (likely pattern-guessed) addresses never enter the store.

DRY RUN by default: prints the verdict per contact and the summary.
--write rewrites the seed file in place with verified+corrected contacts
only and appends the audit line to the batch note.

Usage:
    .venv/bin/python scripts/verify_import_batch.py marketing/imports/deepseek_x.json
    .venv/bin/python scripts/verify_import_batch.py marketing/imports/deepseek_x.json --write
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import List, Optional

FALLBACK_PATHS = [
    "/imprint", "/en/imprint", "/impressum", "/en/impressum",
    "/contact", "/en/contact", "/kontakt", "/kontakt/",
    "/legal-notice", "/en/legal-notice",
    "/contact-us", "/en/contact-us",
    "/about/contact", "/en/about/contact", "/footer/imprint",
]

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126 Safari/537.36"),
}

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch(url: str, timeout: int = 12) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
            return r.read().decode("utf-8", "ignore").lower()
    except Exception:
        return None


def page_has_email(body: Optional[str], email: str) -> bool:
    if not body:
        return False
    email = email.lower()
    deobfuscated = (body.replace(" [at] ", "@").replace("(at)", "@")
                    .replace("[at]", "@").replace("&#64;", "@"))
    return email in body or email in deobfuscated


def verify_batch(seed: dict, fetcher=fetch) -> dict:
    """Return {"ok": [...], "fixed": [...], "dropped": [...]}."""
    ok: List[dict] = []
    fixed: List[dict] = []
    dropped: List[dict] = []
    for contact in seed.get("contacts", []):
        email = (contact.get("email") or "").strip().lower()
        if not email:
            dropped.append(contact)
            continue
        if page_has_email(fetcher(contact.get("source_url") or ""), email):
            ok.append(contact)
            continue
        base_match = re.match(r"(https?://[^/]+)", contact.get("website") or "")
        found_url = None
        if base_match:
            base = base_match.group(1)
            for path in FALLBACK_PATHS:
                if page_has_email(fetcher(base + path), email):
                    found_url = base + path
                    break
        if found_url:
            corrected = dict(contact)
            corrected["source_url"] = found_url
            fixed.append(corrected)
        else:
            dropped.append(contact)
    return {"ok": ok, "fixed": fixed, "dropped": dropped}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("seed_file", help="path to the import seed JSON")
    ap.add_argument("--write", action="store_true",
                    help="rewrite the seed file with verified contacts only")
    args = ap.parse_args(argv)

    path = Path(args.seed_file)
    seed = json.loads(path.read_text(encoding="utf-8"))
    result = verify_batch(seed)

    for c in result["ok"]:
        print(f"OK    {c.get('organization', '?')[:45]}")
    for c in result["fixed"]:
        print(f"FIXED {c.get('organization', '?')[:45]} -> {c['source_url']}")
    for c in result["dropped"]:
        print(f"DROP  {c.get('organization', '?')[:45]} | {c.get('email', '')}")

    n_ok, n_fixed, n_dropped = (len(result["ok"]), len(result["fixed"]),
                                len(result["dropped"]))
    print(f"\nSUMMARY ok={n_ok} fixed={n_fixed} dropped={n_dropped}")

    if args.write:
        seed["contacts"] = result["ok"] + result["fixed"]
        audit = (f" | verified {date.today().isoformat()}: {n_ok} source-confirmed, "
                 f"{n_fixed} source URL corrected, {n_dropped} dropped "
                 f"(email not found on official domain)")
        seed["note"] = (seed.get("note") or "") + audit
        path.write_text(json.dumps(seed, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        print(f"WROTE {path} — {n_ok + n_fixed} verified contacts kept")
    else:
        print("\nDRY RUN — file unchanged. Add --write to apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
