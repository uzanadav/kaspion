"""kaspion — local-only household finance pipeline."""
import sys

# Hebrew + ₪ + ✔ must survive Windows consoles (cp1255/cp437).
# Done once here so every entrypoint that imports kaspion gets it.
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
