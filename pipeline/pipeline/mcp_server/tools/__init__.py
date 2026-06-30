from __future__ import annotations

# Tools register on the FastMCP singleton via @mcp.tool() at import time.
# Importing this package (done from instance.py) wires them all up.
from . import fetch_document, ingest_document, query_knowledge, sql_query  # noqa: F401
