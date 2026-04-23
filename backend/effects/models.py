"""Data models for the Effects system."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import uuid
import time


@dataclass
class Effect:
    name: str
    code: str                          # Python source (defines tick(t, ctx))
    description: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "code": self.code,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Effect":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", "Untitled"),
            description=d.get("description", ""),
            code=d.get("code", ""),
            enabled=d.get("enabled", True),
            created_at=d.get("created_at", time.time()),
        )


@dataclass
class EffectContext:
    """Context passed to tick() in user scripts."""
    channel_count: int
    people: int = 0
    fps: float = 30.0
