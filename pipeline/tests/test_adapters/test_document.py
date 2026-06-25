import pytest

from pipeline.adapters.document import DocumentAdapter
from pipeline.errors import AdapterError, ValidationError
from pipeline.models import DocumentRequest


def test_text_content():
    adapter = DocumentAdapter()
    req = DocumentRequest(title="My Doc", content="Hello world, this is a test.")
    items = adapter.process_text(req)
    assert len(items) == 1
    assert items[0].kind == "document"
    assert items[0].label == "My Doc"
    assert items[0].content == "Hello world, this is a test."


def test_title_derived_from_content():
    adapter = DocumentAdapter()
    req = DocumentRequest(content="First line of the document\nMore text here.")
    items = adapter.process_text(req)
    assert items[0].label == "First line of the document"


def test_empty_content_raises():
    adapter = DocumentAdapter()
    req = DocumentRequest(title="X", content="")
    with pytest.raises(ValidationError, match="required"):
        adapter.process_text(req)


def test_no_content_raises():
    adapter = DocumentAdapter()
    req = DocumentRequest(title="X")
    with pytest.raises(ValidationError, match="required"):
        adapter.process_text(req)


def test_markdown_title_extraction():
    adapter = DocumentAdapter()
    md_bytes = b"# My Heading\n\nSome paragraph text."
    items = adapter.process_file("readme.md", md_bytes)
    assert items[0].label == "My Heading"
    assert items[0].source == "file-upload:md"


def test_txt_file():
    adapter = DocumentAdapter()
    txt_bytes = b"Just some plain text content here."
    items = adapter.process_file("notes.txt", txt_bytes)
    assert items[0].label == "notes"
    assert items[0].content == "Just some plain text content here."


def test_docx_returns_placeholder_not_garbage():
    # Binary Office formats aren't UTF-8 text; decoding the ZIP yields gibberish.
    # Instead we record a clean placeholder node (so an attachment is still linked).
    adapter = DocumentAdapter()
    items = adapter.process_file("deck.docx", b"PK\x03\x04 binary zip junk")
    assert len(items) == 1
    assert items[0].label == "deck"
    assert "not extracted" in items[0].content.lower()


def test_empty_file_raises():
    adapter = DocumentAdapter()
    with pytest.raises(AdapterError, match="empty"):
        adapter.process_file("empty.txt", b"   ")
