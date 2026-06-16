import pytest
from unittest.mock import AsyncMock

from pipeline.models import AttributeSpec, LinkSpec, NormalizedItem
from pipeline.router import route


def _mock_client():
    mock = AsyncMock()
    mock.insert_pointer.return_value = {"status": "created", "pointer_id": "p-1"}
    mock.ingest_document.return_value = {
        "status": "created",
        "pointer_id": "d-1",
        "canonical_key": "doc:abc",
        "chunks_total": 2,
        "chunks_inserted": 2,
    }
    mock.ingest_batch.return_value = {
        "summary": {"total": 2, "created": 2, "merged": 0, "pending_review": 0, "errors": 0},
        "results": [
            {"index": 0, "status": "created", "pointer_id": "b-1"},
            {"index": 1, "status": "created", "pointer_id": "b-2"},
        ],
    }
    return mock


@pytest.mark.asyncio
async def test_single_pointer_uses_insert_pointer():
    client = _mock_client()
    items = [NormalizedItem(kind="pointer", label="Acme", type="company")]
    results, errors = await route(items, client)

    client.insert_pointer.assert_called_once()
    assert len(results) == 1
    assert results[0].status == "created"


@pytest.mark.asyncio
async def test_multiple_pointers_use_ingest_batch():
    client = _mock_client()
    items = [
        NormalizedItem(kind="pointer", label="Acme", type="company"),
        NormalizedItem(kind="pointer", label="Jane", type="person"),
    ]
    results, errors = await route(items, client)

    client.ingest_batch.assert_called_once()
    assert len(results) == 2


@pytest.mark.asyncio
async def test_document_uses_ingest_document():
    client = _mock_client()
    items = [NormalizedItem(kind="document", label="My Doc", type="document", content="Hello")]
    results, errors = await route(items, client)

    client.ingest_document.assert_called_once()
    assert results[0].pointer_id == "d-1"


@pytest.mark.asyncio
async def test_mixed_items():
    client = _mock_client()
    items = [
        NormalizedItem(kind="document", label="Doc", type="document", content="text"),
        NormalizedItem(kind="pointer", label="X", type="company"),
    ]
    results, errors = await route(items, client)

    client.ingest_document.assert_called_once()
    client.insert_pointer.assert_called_once()
    assert len(results) == 2
    assert len(errors) == 0


@pytest.mark.asyncio
async def test_pointer_with_attributes():
    client = _mock_client()
    items = [
        NormalizedItem(
            kind="pointer",
            label="Acme",
            type="company",
            attributes=[AttributeSpec(key="Stage", value="Series B")],
        )
    ]
    results, errors = await route(items, client)

    call_kwargs = client.insert_pointer.call_args.kwargs
    assert call_kwargs["attributes"] == [{"key": "Stage", "value": "Series B", "data_type": "string"}]


@pytest.mark.asyncio
async def test_document_with_link():
    client = _mock_client()
    items = [
        NormalizedItem(
            kind="document",
            label="Memo",
            type="document",
            content="content",
            link=LinkSpec(target_canonical_key="acme-corp", relationship_type="describes"),
        )
    ]
    results, errors = await route(items, client)

    call_kwargs = client.ingest_document.call_args.kwargs
    assert call_kwargs["link"]["target_canonical_key"] == "acme-corp"


@pytest.mark.asyncio
async def test_large_batch_chunked():
    """More than 50 pointers should be split into multiple ingest-batch calls."""
    client = _mock_client()
    # Return matching results per call
    client.ingest_batch.side_effect = [
        {"results": [{"index": i, "status": "created", "pointer_id": f"p-{i}"} for i in range(50)]},
        {"results": [{"index": i, "status": "created", "pointer_id": f"p-{50+i}"} for i in range(25)]},
    ]

    items = [NormalizedItem(kind="pointer", label=f"Item {i}", type="company") for i in range(75)]
    results, errors = await route(items, client)

    assert client.ingest_batch.call_count == 2
    first_call = client.ingest_batch.call_args_list[0].kwargs["items"]
    second_call = client.ingest_batch.call_args_list[1].kwargs["items"]
    assert len(first_call) == 50
    assert len(second_call) == 25


@pytest.mark.asyncio
async def test_batch_per_item_error_goes_to_errors():
    """A batch result with status='error' must land in errors, not results."""
    client = _mock_client()
    client.ingest_batch.return_value = {
        "results": [
            {"index": 0, "status": "created", "pointer_id": "b-1"},
            {"index": 1, "status": "error", "error": "label and type are required"},
            {"index": 2, "status": "merged", "pointer_id": "b-3"},
        ],
    }
    items = [
        NormalizedItem(kind="pointer", label="A", type="company"),
        NormalizedItem(kind="pointer", label="B", type="company"),
        NormalizedItem(kind="pointer", label="C", type="company"),
    ]
    results, errors = await route(items, client)

    assert {r.index for r in results} == {0, 2}
    assert len(errors) == 1
    assert errors[0].index == 1
    assert errors[0].error_type == "edge_function"
    assert "label and type" in errors[0].message
    assert errors[0].retryable is False


@pytest.mark.asyncio
async def test_batch_out_of_range_index_skipped():
    """An out-of-range index is dropped rather than raising IndexError."""
    client = _mock_client()
    client.ingest_batch.return_value = {
        "results": [
            {"index": 0, "status": "created", "pointer_id": "b-1"},
            {"index": 99, "status": "created", "pointer_id": "b-x"},
        ],
    }
    items = [
        NormalizedItem(kind="pointer", label="A", type="company"),
        NormalizedItem(kind="pointer", label="B", type="company"),
    ]
    results, errors = await route(items, client)

    assert [r.index for r in results] == [0]
    assert errors == []
