from __future__ import annotations

from pipeline.errors import ValidationError
from pipeline.models import NormalizedItem, StructuredRequest

VALID_POINTER_TYPES = {
    "company", "person", "sector", "geography", "regulation",
    "document", "timeseries", "agent", "skill", "tool",
    "flow", "component", "architecture", "best_practice", "meta", "event",
    "message",
}


class StructuredAdapter:
    def process(self, request: StructuredRequest) -> list[NormalizedItem]:
        items: list[NormalizedItem] = []
        for item in request.items:
            if item.type not in VALID_POINTER_TYPES:
                raise ValidationError(
                    f"Invalid pointer type '{item.type}'. "
                    f"Valid types: {', '.join(sorted(VALID_POINTER_TYPES))}"
                )
            items.append(NormalizedItem(
                kind="pointer",
                label=item.label,
                type=item.type,
                canonical_key=item.canonical_key,
                metadata=item.metadata,
                occurred_at=item.occurred_at,
                access_class=item.access_class or request.access_class,
                source=request.source or "structured",
                attributes=item.attributes,
            ))
        return items
