from __future__ import annotations

import email
import re
from email import policy
from pathlib import Path

import fitz  # PyMuPDF

from pipeline.config import settings
from pipeline.errors import AdapterError, ValidationError
from pipeline.models import DocumentRequest, LinkSpec, NormalizedItem


# Binary Office formats we can't yet parse to text — recorded as placeholder nodes
# rather than UTF-8-decoded into gibberish.
_BINARY_DOC_EXTS = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls"}


class DocumentAdapter:
    def process_text(self, request: DocumentRequest) -> list[NormalizedItem]:
        if not request.content:
            raise ValidationError("Either file upload or 'content' field is required")

        title = request.title or _title_from_text(request.content)
        _validate_content(request.content)

        return [NormalizedItem(
            kind="document",
            label=title,
            type="document",
            content=request.content,
            metadata=request.metadata,
            occurred_at=request.occurred_at,
            chunk_size=request.chunk_size,
            access_class=request.access_class,
            link=request.link,
            source="text",
        )]

    def process_file(
        self,
        filename: str,
        data: bytes,
        occurred_at: str | None = None,
        chunk_size: int | None = None,
        access_class: str | None = None,
        link: LinkSpec | None = None,
    ) -> list[NormalizedItem]:
        ext = Path(filename).suffix.lower()

        if ext == ".pdf":
            title, content = _extract_pdf(filename, data)
        elif ext in (".eml", ".msg"):
            title, content, occurred_at_parsed = _extract_email(data)
            occurred_at = occurred_at or occurred_at_parsed
        elif ext in (".md", ".txt", ".markdown"):
            content = data.decode("utf-8", errors="replace")
            title = _title_from_markdown(content) or Path(filename).stem
        elif ext in _BINARY_DOC_EXTS:
            # Binary Office formats: decoding as UTF-8 yields gibberish and no
            # parser is wired yet. Record a clean placeholder so the document is
            # still a real (linkable) node; real extraction is a later step.
            title = Path(filename).stem
            content = f"[{filename}] — binary document, text not extracted"
        else:
            # Treat unknown extensions as plain text
            content = data.decode("utf-8", errors="replace")
            title = Path(filename).stem

        _validate_content(content)

        return [NormalizedItem(
            kind="document",
            label=title,
            type="document",
            content=content,
            metadata={"source_filename": filename},
            occurred_at=occurred_at,
            chunk_size=chunk_size,
            access_class=access_class,
            link=link,
            source=f"file-upload:{ext.lstrip('.')}",
        )]


def _extract_pdf(filename: str, data: bytes) -> tuple[str, str]:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise AdapterError(f"Failed to open PDF '{filename}': {exc}") from exc

    title = doc.metadata.get("title") or Path(filename).stem
    pages = []
    for page in doc:
        text = page.get_text()
        if text.strip():
            pages.append(text)
    doc.close()

    if not pages:
        raise AdapterError(f"PDF '{filename}' contains no extractable text")

    return title, "\n\n".join(pages)


def _extract_email(data: bytes) -> tuple[str, str, str | None]:
    msg = email.message_from_bytes(data, policy=policy.default)
    subject = str(msg.get("Subject", "Untitled Email"))

    # Extract date
    date_header = msg.get("Date")
    occurred_at = str(date_header) if date_header else None

    # Prefer plaintext body
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is None:
        raise AdapterError("Email has no readable body")

    content = body.get_content()
    if not isinstance(content, str):
        content = str(content)

    # Strip HTML if we only got the HTML part
    if body.get_content_type() == "text/html":
        from bs4 import BeautifulSoup

        content = BeautifulSoup(content, "html.parser").get_text(separator="\n")

    return subject, content.strip(), occurred_at


def _title_from_text(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return "Untitled"


def _title_from_markdown(content: str) -> str | None:
    match = re.search(r"^#\s+(.+)", content, re.MULTILINE)
    return match.group(1).strip()[:120] if match else None


def _validate_content(content: str) -> None:
    if not content.strip():
        raise AdapterError("Extracted content is empty")
    if len(content) > settings.max_content_length:
        raise ValidationError(
            f"Content length {len(content):,} exceeds maximum {settings.max_content_length:,} characters"
        )
