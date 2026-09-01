#!/usr/bin/env python3
"""
Idempotent Stripe product/price setup for Talaix billing.

Reads ``STRIPE_SECRET_KEY`` from the environment (never hardcoded), creates the
7 catalog items defined in ``config/stripe_prices.json`` if they do not already
exist, then writes the resolved Stripe price ids back to the JSON file.

Run only against a real Stripe account when the key is intentionally set. In
dev/test environments the script exits cleanly with a clear message.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parent.parent / "config" / "stripe_prices.json"


def load_catalog() -> dict:
    with open(CATALOG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_catalog(catalog: dict) -> None:
    with open(CATALOG_PATH, "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=2)
        fh.write("\n")


def amount_cents(amount_eur) -> int:
    return int(round(float(amount_eur) * 100))


def _read_secret_key() -> str:
    """STRIPE_SECRET_KEY from the env, else an interactive hidden prompt.

    The key never appears in shell history and is never stored by the script.
    """
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if key:
        return key
    import getpass

    print("STRIPE_SECRET_KEY is not set in the environment.")
    return getpass.getpass(
        "Paste the Stripe secret key (input hidden, never stored): "
    ).strip()


def main() -> int:
    secret_key = _read_secret_key()
    if not secret_key:
        print("Error: no Stripe secret key provided.", file=sys.stderr)
        print(
            "Set STRIPE_SECRET_KEY or paste the key at the hidden prompt to run "
            "against a real account. No key is committed in this repository.",
            file=sys.stderr,
        )
        return 1

    try:
        import stripe
    except ImportError as exc:  # pragma: no cover
        print(f"Error: stripe SDK is not installed: {exc}", file=sys.stderr)
        return 1

    stripe.api_key = secret_key

    catalog = load_catalog()
    created = []
    reused = []

    # Fetch existing products once for idempotency.
    existing_products = {
        prod.metadata.get("talaix_key"): prod
        for prod in stripe.Product.list(limit=100).auto_paging_iter()
        if prod.metadata and prod.metadata.get("talaix_key")
    }

    for key, entry in catalog.items():
        name = entry["product_name"]
        interval = entry.get("interval", "one_time")
        recurring = {"interval": interval} if interval != "one_time" else None
        metadata = {"talaix_key": key}

        product = existing_products.get(key)
        if product is None:
            product = stripe.Product.create(
                name=name,
                metadata=metadata,
            )
            created.append(f"product {key}")
        else:
            reused.append(f"product {key}")

        # Look for an existing price for this product with the same key metadata.
        existing_prices = list(stripe.Price.list(product=product.id, limit=10).auto_paging_iter())
        price = next(
            (p for p in existing_prices if p.metadata and p.metadata.get("talaix_key") == key),
            None,
        )
        if price is None:
            price = stripe.Price.create(
                product=product.id,
                unit_amount=amount_cents(entry["amount_eur"]),
                currency="eur",
                recurring=recurring,
                metadata=metadata,
            )
            created.append(f"price {key}")
        else:
            reused.append(f"price {key}")

        entry["price_id"] = price.id

    save_catalog(catalog)

    # Summary table.
    print(f"{'Key':<24} {'Product':<40} {'Price ID':<30} {'Amount':>8} {'Interval':<10}")
    print("-" * 120)
    for key, entry in catalog.items():
        print(
            f"{key:<24} {entry['product_name']:<40} {entry['price_id']:<30} "
            f"€{entry['amount_eur']:>6} {entry.get('interval', 'one_time'):<10}"
        )
    print("-" * 120)
    if created:
        print(f"Created: {', '.join(created)}")
    if reused:
        print(f"Reused:  {', '.join(reused)}")
    print(f"Wrote {len(catalog)} price ids to {CATALOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
