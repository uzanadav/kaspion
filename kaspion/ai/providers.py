from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Protocol

import requests

# single source of truth for categories: the dbt seed the dashboard is built on.
# add a category there and every layer (AI, CLI, UI) picks it up automatically.
_CATEGORY_SEED = Path(__file__).resolve().parents[2] / "dbt" / "seeds" / "dim_category_seed.csv"
VALID_CATEGORIES = [
    row["category_id"] for row in csv.DictReader(_CATEGORY_SEED.open(encoding="utf-8"))
]

PROMPT = """You categorize Israeli household transactions. Merchants may be Hebrew or English.
Return ONLY a JSON object. Keys: EXACTLY the merchant strings given below, unchanged.
Values: exactly one category id from this list:
{categories}

Examples of correct output:
{{"רמי לוי": "groceries", "וולט": "restaurants", "netflix.com": "subscriptions", "חברת החשמל": "housing", "סופר פארם": "health", "רב קו": "transport", "gett": "transport", "ארנונה חולון": "housing", "שכר דירה": "housing"}}

Merchants:
{merchants}
"""


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
        prompt = PROMPT.format(
            categories=", ".join(VALID_CATEGORIES), merchants="\n".join(merchants)
        )
        resp = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
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
        prompt = PROMPT.format(
            categories=", ".join(VALID_CATEGORIES), merchants="\n".join(merchants)
        )
        msg = client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text
        text = text[text.index("{") : text.rindex("}") + 1]  # tolerate prose around JSON
        return _clean(json.loads(text), merchants)


class NoneProvider:
    """Manual mode: propose nothing; everything defaults to 'other' until overridden."""

    name = "none"
    model = "none"

    def categorize(self, merchants: list[str]) -> dict[str, str]:
        return {}


def _clean(raw: dict[str, str], merchants: list[str]) -> dict[str, str]:
    """Keep only known merchants mapped to valid categories."""
    return {m: raw[m] for m in merchants if raw.get(m) in VALID_CATEGORIES}


def get_provider() -> Provider:
    choice = os.environ.get("KASPION_AI_PROVIDER", "ollama")
    return {"ollama": OllamaProvider, "claude": ClaudeProvider, "none": NoneProvider}[choice]()
