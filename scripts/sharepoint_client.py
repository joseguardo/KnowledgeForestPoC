# Re-export shim. The SharePoint Graph client now lives in the pipeline package
# (pipeline/pipeline/adapters/sharepoint.py) so the MCP server can import it too.
# These standalone scripts keep importing `from sharepoint_client import ...`
# unchanged; they run inside pipeline/.venv where the `pipeline` package — and
# its msal/requests deps — are installed.
try:
    from pipeline.adapters.sharepoint import GRAPH_BASE, SharePointClient
except ModuleNotFoundError as exc:  # pragma: no cover
    raise ModuleNotFoundError(
        "Could not import the pipeline package. Run these SharePoint scripts with "
        "the pipeline virtualenv, e.g. `pipeline/.venv/bin/python scripts/...`."
    ) from exc

__all__ = ["GRAPH_BASE", "SharePointClient"]
