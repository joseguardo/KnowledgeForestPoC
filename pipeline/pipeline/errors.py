from __future__ import annotations


class PipelineError(Exception):
    """Base for all pipeline errors."""


class ValidationError(PipelineError):
    """Bad input from the caller."""


class AdapterError(PipelineError):
    """Source-specific failure (PDF unreadable, URL unreachable, empty content)."""


class EdgeFunctionError(PipelineError):
    """Edge function returned a non-success status."""

    def __init__(self, status_code: int, body: dict | str | None = None):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Edge function returned {status_code}: {body}")


class EdgeFunctionTimeout(PipelineError):
    """Edge function did not respond in time."""
