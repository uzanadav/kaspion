from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Protocol

import requests

# Built-in categories live in the dbt seed the dashboard is built on. Categories the
# household adds from the dashboard live in state.categories. VALID_CATEGORIES stays
# as the seed-only list so importing this module never needs a database; call
# valid_categories() wherever owner-added categories must count too.
_CATEGORY_SEED = Path(__file__).resolve().parents[2] / "dbt" / "seeds" / "dim_category_seed.csv"
VALID_CATEGORIES = [
    row["category_id"] for row in csv.DictReader(_CATEGORY_SEED.open(encoding="utf-8"))
]


def valid_categories() -> list[str]:
    """Seed categories plus any the owner added. Falls back to the seed alone if the
    database isn't reachable yet (first run, or a read during a rebuild)."""
    try:
        from kaspion.db import connect

        con = connect()
        extra = [r[0] for r in con.execute("SELECT category_id FROM state.categories").fetchall()]
        con.close()
    except Exception:  # noqa: BLE001 - the seed list is always a usable answer
        return list(VALID_CATEGORIES)
    return VALID_CATEGORIES + [c for c in extra if c not in VALID_CATEGORIES]

PROMPT = """You categorize Israeli household transactions. Merchants may be Hebrew or English.
Return ONLY a JSON array of category ids, one per merchant below, in the SAME ORDER.
Do not repeat the merchant names — many contain quotes/brackets that break JSON when echoed
back, so the array position is what maps each answer to its merchant, not the text.
Each value must be exactly one category id from this list:
{categories}

Example: for merchants ["רמי לוי", "netflix.com", "חברת החשמל"], return exactly:
["groceries", "subscriptions", "housing"]

Merchants ({n}):
{merchants}
"""


def _build_prompt(merchants: list[str]) -> str:
    return PROMPT.format(
        categories=", ".join(valid_categories()),
        n=len(merchants),
        merchants="\n".join(f"{i + 1}. {m}" for i, m in enumerate(merchants)),
    )


class Provider(Protocol):
    name: str
    model: str

    def categorize(self, merchants: list[str]) -> dict[str, str]: ...


class OllamaProvider:
    """Default: free, fully local. Requires `ollama pull llama3.2:3b` first.
    Model tiers (override via KASPION_OLLAMA_MODEL):
      llama3.2:1b  ~1.3GB  too weak in practice — scored 10% on our Hebrew-merchant eval
      llama3.2:3b  ~2.0GB  the sensible default
      llama3.1:8b  ~4.9GB  best quality, needs ~8GB RAM
    """

    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None):
        self.model = model or os.environ.get("KASPION_OLLAMA_MODEL", "llama3.2:3b")
        self.host = host or os.environ.get("KASPION_OLLAMA_HOST", "http://127.0.0.1:11434")

    def categorize(self, merchants: list[str]) -> dict[str, str]:
        # a full JSON-schema format (not just "json") makes Ollama constrain decoding to
        # an array of exactly len(merchants) valid category ids — the earlier free-form
        # "json" mode let the model wander into an unrelated object shape.
        schema = {
            "type": "array",
            "items": {"type": "string", "enum": valid_categories()},
            "minItems": len(merchants),
            "maxItems": len(merchants),
        }
        resp = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": _build_prompt(merchants)}],
                "format": schema,
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=300,
        )
        resp.raise_for_status()
        return _clean(json.loads(resp.json()["message"]["content"]), merchants)


class ClaudeProvider:
    """Opt-in, paid (cents). Needs ANTHROPIC_API_KEY env var and `pip install anthropic`."""

    name = "claude"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("KASPION_CLAUDE_MODEL", "claude-haiku-4-5")

    def categorize(self, merchants: list[str]) -> dict[str, str]:
        import anthropic

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        msg = client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": _build_prompt(merchants)}],
        )
        text = msg.content[0].text
        text = text[text.index("[") : text.rindex("]") + 1]  # tolerate prose around JSON
        return _clean(json.loads(text), merchants)


class NoneProvider:
    """Manual mode: propose nothing; everything defaults to 'other' until overridden."""

    name = "none"
    model = "none"

    def categorize(self, merchants: list[str]) -> dict[str, str]:
        return {}


def _clean(categories: list[str], merchants: list[str]) -> dict[str, str]:
    """Zip positionally with merchants. A length mismatch means the model dropped or
    added an entry — positions would no longer line up, so the whole batch is discarded
    rather than risk silently pairing a category with the wrong merchant."""
    if not isinstance(categories, list) or len(categories) != len(merchants):
        return {}
    allowed = set(valid_categories())
    return {m: c for m, c in zip(merchants, categories, strict=True) if c in allowed}


def get_provider() -> Provider:
    # "none" by default: no model download, works on any machine. Ollama/Claude stay
    # fully available, opt-in via KASPION_AI_PROVIDER or --provider.
    choice = os.environ.get("KASPION_AI_PROVIDER", "none")
    return {"ollama": OllamaProvider, "claude": ClaudeProvider, "none": NoneProvider}[choice]()
