import pytest

from pipeline.adapters.conversation import ConversationAdapter
from pipeline.errors import AdapterError
from pipeline.models import ConversationRequest


def test_basic_transcript():
    adapter = ConversationAdapter()
    req = ConversationRequest(content="Meeting about Q4 results\nWe discussed revenue growth.")
    items = adapter.process(req)
    assert len(items) == 1
    assert items[0].kind == "document"
    assert items[0].label == "Meeting about Q4 results"
    assert items[0].type == "document"
    assert "Meeting about Q4 results" in items[0].content


def test_explicit_title():
    adapter = ConversationAdapter()
    req = ConversationRequest(content="some content", title="Weekly Standup")
    items = adapter.process(req)
    assert items[0].label == "Weekly Standup"


def test_participants_in_metadata():
    adapter = ConversationAdapter()
    req = ConversationRequest(
        content="notes",
        participants=["Alice", "Bob"],
        source="zoom",
    )
    items = adapter.process(req)
    assert items[0].metadata["participants"] == ["Alice", "Bob"]
    assert items[0].metadata["conversation_source"] == "zoom"
    assert items[0].source == "conversation:zoom"


def test_empty_lines_skip_for_title():
    adapter = ConversationAdapter()
    req = ConversationRequest(content="\n\n\nActual first line\nMore text")
    items = adapter.process(req)
    assert items[0].label == "Actual first line"


def test_whitespace_only_content_rejected():
    adapter = ConversationAdapter()
    req = ConversationRequest(content="   \n\t  ")
    with pytest.raises(AdapterError):
        adapter.process(req)
