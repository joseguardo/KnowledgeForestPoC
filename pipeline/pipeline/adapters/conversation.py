from __future__ import annotations

from pipeline.adapters.document import _validate_content
from pipeline.models import ConversationRequest, NormalizedItem


class ConversationAdapter:
    def process(self, request: ConversationRequest) -> list[NormalizedItem]:
        _validate_content(request.content)
        title = request.title or _derive_title(request.content)

        metadata: dict = {}
        if request.participants:
            metadata["participants"] = request.participants
        if request.source:
            metadata["conversation_source"] = request.source

        return [NormalizedItem(
            kind="document",
            label=title,
            type="document",
            content=request.content,
            metadata=metadata or None,
            occurred_at=request.occurred_at,
            access_class=request.access_class,
            link=request.link,
            source=f"conversation:{request.source}" if request.source else "conversation",
        )]


def _derive_title(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return "Untitled Conversation"
