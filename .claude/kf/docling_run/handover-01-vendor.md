# Handover 01 — Vendor Docling extraction `logic/` tree (agent A1)

Status: COMPLETE. Faithful verbatim port; no logic/imports rewritten. No blockers in A1's scope.

## What changed
New self-contained subpackage created under the KnowledgeForest pipeline. Files created (full paths):

- `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/adapters/docling_extract/__init__.py` — placeholder only: one-line module docstring, NO `extract()` (left for agent C1).
- `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/adapters/docling_extract/logic/__init__.py` — empty (verbatim; source was 0 bytes).
- `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/adapters/docling_extract/logic/services/__init__.py` — empty (verbatim; source was 0 bytes).
- `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/adapters/docling_extract/logic/services/docling_converter.py`
- `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/adapters/docling_extract/logic/services/facts.py`
- `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/adapters/docling_extract/logic/services/normalize.py`
- `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/adapters/docling_extract/logic/services/guardrails.py`
- `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/adapters/docling_extract/logic/services/chunking.py`
- `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/adapters/docling_extract/logic/models/__init__.py` — empty (verbatim; source was 0 bytes).
- `/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/adapters/docling_extract/logic/models/models.py`

Subpackage structure preserved exactly (`logic/services`, `logic/models`) so intra-package relative imports (`from . import chunking`, `from .normalize import ...`, `from .docling_converter import ConvertedDoc`, `from . import normalize`) keep resolving unchanged.

Each non-empty source file got a 2-line vendored header above the original module docstring (`# Vendored verbatim from PlatformRemote ... — do not edit here; keep in sync with source.` + a source path line). The three `__init__.py` files were left empty per "copy verbatim" (source `__init__.py`s are all 0 bytes); the only intentional deviation is the top-level `docling_extract/__init__.py`, which per task gets a one-line docstring placeholder.

## Provenance
Copied FROM (read-only):
`/Users/joseguardo/Desktop/SimpleScripts/PlatformRemote/platform/backend/app/agents/discovery/pdf_extraction/logic/`
into
`/Users/joseguardo/Desktop/SimpleScripts/KnowledgeForestPoC/pipeline/pipeline/adapters/docling_extract/logic/`

## Data structures introduced (Pydantic, in `logic/models/models.py`)
All transient — returned to the MCP client / HTTP surface, NOT persisted by this PoC pipeline. No DB / migration impact.

- **FinancialFact**: `metric:str`, `section:Optional[str]=None`, `dimensions:str=""` (joined with " / "), `value:float`, `raw:str`, `unit:str` (billions|millions|thousands|units|percent), `scale_multiplier:float`, `currency:Optional[str]=None`, `table_index:int`, `page:Optional[int]=None`, `bbox:Optional[list[float]]=None` ([l,t,r,b]), `reconciled:Optional[bool]=None`.
- **TableIssue**: `table:int`, `row:str`, `column:str`, `expected:float`, `got:float`.
- **GuardrailReport**: `grade:str`, `quality_ok:bool`, `furniture_dropped:int`, `body_elements:int`, `tables_audited:int`, `table_issues:list[TableIssue]=[]`, `passed:bool`, `needs_review:bool`.
- **ChunkSummary**: `total:int`, `table:int`, `narrative:int`, `pages:list[int]=[]`.
- **FileExtractResult**: `name:str`, `pages:Optional[int]=None`, `markdown:str=""`, `facts:list[FinancialFact]=[]`, `guardrails:Optional[GuardrailReport]=None`, `chunk_summary:Optional[ChunkSummary]=None`, `error:Optional[str]=None`.
- **ExtractResult**: `files:list[FileExtractResult]=[]`, `combined_markdown:str=""`, `fact_count:int=0`, `needs_review:bool=False`, `download_url:Optional[str]=None`, `platform:Optional[dict[str,Any]]=None`.

Note: there is ALSO a dataclass `FinancialFact` in `logic/services/facts.py` (the working representation; tuple dimensions/bbox). The Pydantic `FinancialFact` in models.py is the serialization boundary and matches `facts.facts_to_records()` field-for-field. Two different `FinancialFact` types live in different modules — do not conflate.

## Verification done
- **py_compile**: PASS — compiled all `.py` in `docling_extract/` (services, models, top-level, logic) with `pipeline/.venv/bin/python -m py_compile`. Output: `PY_COMPILE_OK`.
- **ruff**: PASS — `pipeline/.venv/bin/ruff check pipeline/adapters/docling_extract/` -> "All checks passed!" (exit 0). No warnings.
- **app.* grep**: CLEAN — `grep -rnE 'from app\.|import app\.|from app ' pipeline/adapters/docling_extract/` -> no matches (exit 1). No `app.*` imports to flag. NOT A BLOCKER.

## Open items / blockers for next agents
- **pandas** (A2): `facts.py` does `import pandas as pd` at module top. py_compile passes (syntax only), but importing `facts`/`facts_to_dataframe` at runtime needs pandas in the env. A2 must add the dependency.
- **docling** (install before runtime): `docling_converter.py` lazy-imports `docling.document_converter.DocumentConverter` and `docling.datamodel.base_models.DocumentStream` (with a `docling_core.types.io` fallback) *inside* functions — so importing the module is cheap, but `build_converter()`/`convert_bytes()` need `docling` installed at call time.
- **docling_core** (install before import): `chunking.py` imports `docling_core.transforms.chunker.HierarchicalChunker` and `docling_core.types.doc.document.TableItem` at MODULE TOP (not lazy). Importing `chunking` (and therefore `facts`, which does `from . import chunking`) at runtime requires `docling_core` present. A2 dependency work must cover this.
- **C1**: top-level `docling_extract/__init__.py` is an intentional stub — still needs the `extract()` entrypoint. Not done here by design.

## Interfaces the next agents rely on (confirmed present, real signatures)
- `logic/services/docling_converter.py`
  - `build_converter()` -> `DocumentConverter` — present.
  - `convert_bytes(converter, name: str, data: bytes, *, max_pages: int | None = None) -> ConvertedDoc` — present.
  - `ConvertedDoc` dataclass fields: `name:str`, `markdown:str`, `grade:str`, `doc:Any` (DoclingDocument), `tables:list` (list[pd.DataFrame]), `pages:int|None`. Confirms `.markdown / .grade / .doc / .tables / .pages`.
- `logic/services/guardrails.py`
  - `assess(converted: ConvertedDoc, *, minimum_grade: str = "GOOD") -> dict[str, Any]` — present (note keyword `minimum_grade`, default "GOOD").
- `logic/services/chunking.py`
  - `logical_chunks(doc) -> list[LogicalChunk]` — present.
  - `chunk_summary(chunks: list[LogicalChunk]) -> dict` — present.
- `logic/services/facts.py`
  - `extract_facts(doc) -> list[FinancialFact]` (the dataclass FinancialFact) — present.
  - `facts_to_records(facts: list[FinancialFact]) -> list[dict]` — present (these dicts map field-for-field onto the Pydantic `FinancialFact`).
  - (also available: `facts_from_table(...)`, `detect_scale(...)`, `facts_to_dataframe(...)`.)
