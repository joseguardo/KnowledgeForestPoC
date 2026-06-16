from pipeline.adapters.structured import StructuredAdapter
from pipeline.errors import ValidationError
from pipeline.models import AttributeSpec, StructuredItem, StructuredRequest

import pytest


def test_single_item():
    adapter = StructuredAdapter()
    req = StructuredRequest(items=[StructuredItem(label="Acme Corp", type="company")])
    items = adapter.process(req)
    assert len(items) == 1
    assert items[0].kind == "pointer"
    assert items[0].label == "Acme Corp"
    assert items[0].type == "company"
    assert items[0].source == "structured"


def test_multiple_items():
    adapter = StructuredAdapter()
    req = StructuredRequest(
        items=[
            StructuredItem(label="Acme Corp", type="company"),
            StructuredItem(label="Jane Doe", type="person"),
        ],
        source="crm-export",
    )
    items = adapter.process(req)
    assert len(items) == 2
    assert items[0].type == "company"
    assert items[1].type == "person"
    assert all(i.source == "crm-export" for i in items)


def test_attributes_pass_through():
    adapter = StructuredAdapter()
    req = StructuredRequest(
        items=[
            StructuredItem(
                label="Acme Corp",
                type="company",
                attributes=[AttributeSpec(key="Stage", value="Series B")],
            )
        ]
    )
    items = adapter.process(req)
    assert items[0].attributes is not None
    assert items[0].attributes[0].key == "Stage"


def test_invalid_type_raises():
    adapter = StructuredAdapter()
    req = StructuredRequest(items=[StructuredItem(label="X", type="invalid_type")])
    with pytest.raises(ValidationError, match="Invalid pointer type"):
        adapter.process(req)


def test_access_class_fallback():
    adapter = StructuredAdapter()
    req = StructuredRequest(
        items=[StructuredItem(label="X", type="company")],
        access_class="confidential",
    )
    items = adapter.process(req)
    assert items[0].access_class == "confidential"


def test_item_access_class_overrides_request():
    adapter = StructuredAdapter()
    req = StructuredRequest(
        items=[StructuredItem(label="X", type="company", access_class="restricted")],
        access_class="confidential",
    )
    items = adapter.process(req)
    assert items[0].access_class == "restricted"
