from __future__ import annotations

import json

from kaspion.ai.known_merchants import match
from kaspion.ai.providers import get_provider
from kaspion.db import connect

BATCH_SIZE = 10  # small batches keep local models accurate


def categorize_new_merchants() -> tuple[int, int]:
    """Categorize merchants with no override AND no prior proposal, in two passes:
    1. built-in knowledge of well-known Israeli merchants (free, deterministic);
    2. the AI provider for whatever is left.
    Known merchants are never re-sent — that's what keeps the paid path near-free."""
    con = connect()
    merchants = [
        r[0]
        for r in con.execute(
            """
            SELECT DISTINCT s.merchant_key
            FROM main.stg_transactions s
            WHERE s.amount < 0
              AND s.merchant_key NOT IN (SELECT merchant_key FROM state.merchant_overrides)
              AND s.merchant_key NOT IN (SELECT merchant_key FROM state.ai_proposals)
            """
        ).fetchall()
    ]

    def save(merchant: str, category: str, provider: str, model: str) -> None:
        con.execute(
            """
            INSERT INTO state.ai_proposals (merchant_key, proposed_category_id, provider, model)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (merchant_key) DO UPDATE
                SET proposed_category_id = excluded.proposed_category_id
            """,
            [merchant, category, provider, model],
        )

    # pass 1: built-in Israeli merchant knowledge
    by_rules = 0
    unknown: list[str] = []
    for m in merchants:
        category = match(m)
        if category:
            save(m, category, "rules", "known_merchants")
            by_rules += 1
        else:
            unknown.append(m)

    # pass 2: AI for the rest
    by_ai = 0
    if unknown:
        provider = get_provider()
        for i in range(0, len(unknown), BATCH_SIZE):
            batch = unknown[i : i + BATCH_SIZE]
            # one bad response (malformed JSON, model hiccup) must not lose every other
            # batch — same isolation principle as one bank's scrape failure in sync.py
            try:
                results = provider.categorize(batch)
            except json.JSONDecodeError:
                print(f"      ⚠ AI batch skipped (unreadable response): {batch[0]}...")
                continue
            for merchant, category in results.items():
                save(merchant, category, provider.name, provider.model)
                by_ai += 1
    con.close()
    return by_rules, by_ai
