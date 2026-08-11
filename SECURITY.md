# Security & privacy posture

## Threat model

This tool handles real financial data for one household, on one machine.
It is not, and must never become, a hosted service.

## Guarantees

- **Local-only.** The dashboard is a static file; the optional edit server
  (`python3 -m kaspion.serve`) and the future MCP server bind to `127.0.0.1` only.
  Nothing listens on the LAN or internet.
- **Data at rest.** `data/finance.duckdb` and the encryption key live only in `data/`,
  which is gitignored. Back up by copying the file.
- **Credentials.** Bank credentials are encrypted with AES-256-GCM
  (`kaspion/ingest/crypto.py`). The key file has 0600 permissions. Credentials are
  passed to the Node scraper via environment variables — never argv, never logged.
- **Outbound traffic.** Exactly two possible destinations:
  1. your bank/card issuer (scraping, over TLS via israeli-bank-scrapers);
  2. the Anthropic API — only if `KASPION_AI_PROVIDER=claude` is explicitly set,
     and only merchant name strings (never amounts, dates, or account details).
  The default provider (Ollama) keeps everything fully offline.
- **Committed sample data** is synthetic, produced by `generate_seed.py`.

## Known caveats

- Automated scraping may violate your bank's Terms of Service. Use only with your
  own accounts, on your own machine, at your own discretion.
- The DuckDB file itself is not encrypted at rest; rely on full-disk encryption
  (FileVault) for that layer.
- If you ever expose the dashboard beyond localhost (e.g. Tailscale for a second
  device), that is a deliberate opt-in decision — add authentication first.
