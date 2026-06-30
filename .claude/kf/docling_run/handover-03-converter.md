# Handover 03 — Warm converter singleton + startup warmup (agent B1)

Status: COMPLETE. Code written + verified (compile/lint/import). NOT timed — docling
not yet installed in the venv (see Open items for DD-B1).

## What changed (2 files)

### 1. NEW: `pipeline/pipeline/adapters/docling_extract/converter.py`
Process-global, lock-guarded, warm `DocumentConverter` singleton tuned for speed.
Lazy docling imports (inside functions) so importing the module is cheap and never
crashes when docling is absent.

Public interface:
- `get_converter()` → builds the `DocumentConverter` ONCE, caches in module global
  `_converter`, guarded by `threading.Lock` (double-checked locking: lock-free warm
  read, lock only on first build). Subsequent calls return the cached instance.
- `warm_converter() -> None` (sync) → just calls `get_converter()`. Used by startup.
- `is_warm() -> bool` → diagnostic; True once `_converter is not None`. Lock-free.

Core options block (inside `_build_tuned_converter()`):
```python
num_threads = settings.docling_num_threads or os.cpu_count() or 1
try:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        AcceleratorDevice, AcceleratorOptions, PdfPipelineOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    accelerator_options = AcceleratorOptions(
        num_threads=num_threads, device=AcceleratorDevice.AUTO,
    )
    pipeline_options = PdfPipelineOptions(
        do_ocr=settings.docling_do_ocr, do_table_structure=True,
    )
    pipeline_options.accelerator_options = accelerator_options
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )
    return converter
except Exception as exc:  # version drift → graceful fallback
    from .logic.services.docling_converter import build_converter
    log.warning("... falling back to bare build_converter() ...", exc)
    return build_converter()
```

### 2. EDIT: `pipeline/pipeline/mcp_server/server.py`
- Added `import asyncio` to the top imports.
- Added module-level helper `_warm_docling()` (local import of `warm_converter`,
  runs it via `asyncio.to_thread`, swallows + logs any exception as a warning).
- In `mcp_lifespan()` (the streamable-HTTP session-manager context manager), added
  ONE line before `async with mcp.session_manager.run():`:
```python
build_mcp_asgi_app()  # ensure session_manager exists
asyncio.create_task(_warm_docling())   # ← added: background, non-blocking warmup
async with mcp.session_manager.run():
    ...
    finally:
        await aclose_http()   # unchanged
```
Existing session-manager / `aclose_http` behavior is untouched; warmup is purely additive.

## Version-drift fallback behavior
If the tuning imports (`InputFormat`, `PdfPipelineOptions`, `AcceleratorOptions`,
`AcceleratorDevice`, `PdfFormatOption`) are missing or moved in the installed docling
version — or option construction raises for any reason — `_build_tuned_converter()`
catches it, logs a WARNING naming the exception, and returns the vendored bare
`build_converter()` (which itself has a `DocumentStream` import fallback). Net effect:
conversion still works on any docling 2.x; only the perf tuning is skipped. The chosen
path is logged at INFO (tuned) or WARNING (fallback) so DD can see which ran.

## Performance rationale recap
- Warm singleton removes the ~4 s per-call model-load cost — paid once at boot, not
  per `fetch_document`.
- Accelerator threads (`docling_num_threads or os.cpu_count()`) parallelize a single
  conversion across cores.
- OCR off (born-digital docs) + table-structure on cuts per-page time dramatically
  (~1-4 s/page vs ~30 s/page with OCR) while still feeding the facts extractor.

## Data-structure / coherency
None. No persistence, no DB, no schema/migration. Pure in-process singleton + config reads.

## Verification done
- `py_compile` both files → `PY_COMPILE_OK`.
- `ruff check` both files → `All checks passed!`.
- `ast.parse(converter.py)` → `parsed`.
- Clean import of `converter.py` with docling ABSENT:
  `import ok True True True` (get_converter / warm_converter / is_warm all present).
  Confirms lazy-import design: module imports fine without docling and despite
  `pipeline.config` only being touched lazily inside the functions.
- Did NOT run a conversion (model download slow, per task).

## Open items for DD-B1
- **docling is NOT installed yet** in `pipeline/.venv` (`import docling` →
  ModuleNotFoundError). Wave 5 install must finish first.
- **Needs a real warm-load TIMING measurement** once docling + models are present.
  How to measure (from `pipeline/`, env with SUPABASE_URL set):
  ```python
  import time
  from pipeline.adapters.docling_extract.converter import (
      get_converter, warm_converter, is_warm,
  )
  t = time.perf_counter(); warm_converter()                 # COLD: build (may DOWNLOAD models)
  print("cold warm_converter:", time.perf_counter() - t, "is_warm:", is_warm())
  t = time.perf_counter(); get_converter()                  # WARM: should be ~instant (cached)
  print("second get_converter:", time.perf_counter() - t)
  ```
  Expect: first call seconds-to-minutes (model download on a truly fresh cache, else
  ~4 s); second call near-zero. Also confirm logs show the "tuned" INFO path (not the
  fallback WARNING) on the installed docling version.
