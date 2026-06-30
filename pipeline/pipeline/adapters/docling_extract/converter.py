# Performance-tuned, warm-at-startup, parallel Docling converter singleton.
"""Process-global warm Docling ``DocumentConverter`` singleton.

Why this module exists
----------------------
Building a ``DocumentConverter`` loads the layout/table models and costs roughly
~4 seconds on first instantiation. The vendored ``build_converter()`` makes a
bare converter every call, so doing that per request would pay that ~4 s cost on
*every* ``fetch_document`` invocation. This module builds the converter exactly
once per process and caches it in a module global, guarded by a ``threading.Lock``
so concurrent first-callers can't race into two builds. Subsequent calls return
the cached instance instantly. ``warm_converter()`` lets the MCP server pay the
build cost once at boot (in a worker thread) so the first real request is fast.

Parallelism / speed
--------------------
The converter is tuned for born-digital PDFs:
- OCR is OFF by default (``settings.docling_do_ocr``) — born-digital docs already
  have an extractable text layer, and OCR is the dominant per-page cost
  (~30 s/page vs ~1-4 s/page without).
- Table structure is ON — the facts extractor needs table cells.
- The accelerator uses multiple threads (``settings.docling_num_threads`` or
  ``os.cpu_count()``) so a single conversion parallelizes across CPU cores.

Version-drift resilience
-------------------------
docling has moved these option/accelerator symbols across 2.x releases. We import
them defensively *inside* ``get_converter()`` and, if any tuning import is
unavailable in the installed docling version, we DEGRADE GRACEFULLY to the
vendored bare ``build_converter()`` rather than crashing. The ``import docling*``
calls stay inside the functions (lazy), so importing this module is cheap and
never fails when docling is absent.
"""
from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger(__name__)

# Module-global warm singleton + the lock that guards its construction.
_converter = None
_lock = threading.Lock()


def is_warm() -> bool:
    """True once the converter singleton has been built and cached.

    Cheap, lock-free diagnostic — safe to call from health/status endpoints.
    """
    return _converter is not None


def _build_tuned_converter():
    """Build a performance-tuned ``DocumentConverter`` (or a bare one on drift).

    Lazy-imports docling inside the function. Attempts to apply the
    OCR-off / table-structure-on / multi-threaded-accelerator options; if any of
    those symbols are missing in the installed docling version, falls back to the
    vendored bare ``build_converter()``.
    """
    from pipeline.config import settings

    num_threads = settings.docling_num_threads or os.cpu_count() or 1

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            AcceleratorDevice,
            AcceleratorOptions,
            PdfPipelineOptions,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption

        accelerator_options = AcceleratorOptions(
            num_threads=num_threads,
            device=AcceleratorDevice.AUTO,
        )
        pipeline_options = PdfPipelineOptions(
            do_ocr=settings.docling_do_ocr,
            do_table_structure=True,
        )
        pipeline_options.accelerator_options = accelerator_options

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            }
        )
        log.info(
            "docling converter built (tuned): do_ocr=%s, table_structure=True, "
            "accelerator_threads=%d, device=AUTO",
            settings.docling_do_ocr,
            num_threads,
        )
        return converter
    except Exception as exc:  # noqa: BLE001 — any import/option drift → graceful fallback
        # Version drift or missing tuning symbols: fall back to the vendored bare
        # converter so conversion still works (just without the perf tuning).
        from .logic.services.docling_converter import build_converter

        log.warning(
            "docling tuned-converter options unavailable (%s); falling back to "
            "bare build_converter() — conversion works, perf tuning skipped.",
            exc,
        )
        return build_converter()


def get_converter():
    """Return the process-global warm ``DocumentConverter``, building it once.

    Thread-safe via double-checked locking: the common (warm) path is a lock-free
    read; only the first caller takes the lock to build. Subsequent calls are
    effectively instant.
    """
    global _converter
    if _converter is not None:
        return _converter
    with _lock:
        if _converter is None:  # re-check under lock (another thread may have built it)
            _converter = _build_tuned_converter()
    return _converter


def warm_converter() -> None:
    """Build + cache the converter now (sync). Used by server startup warmup.

    Synchronous and potentially slow on the very first call (model load, and on a
    fresh install a model download), so callers should run it off the event loop
    (e.g. ``asyncio.to_thread``).
    """
    get_converter()
