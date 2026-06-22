from __future__ import annotations

# Tools register on the FastMCP singleton via @mcp.tool() at import time.
# Importing this package (done from instance.py) wires them all up.
from . import ingest_document, query_knowledge  # noqa: F401
