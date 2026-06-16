from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pipeline.models import NormalizedItem


class BaseAdapter(ABC):
    @abstractmethod
    def process(self, request: Any) -> list[NormalizedItem]:
        ...
