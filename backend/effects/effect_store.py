"""Persistence layer for Effects — loads/saves to data/effects.json."""

from __future__ import annotations
import json
import os
from typing import Optional
from .models import Effect

_DEFAULT_EFFECTS: list[dict] = [
    {
        "name": "Breathing",
        "description": "Smooth brightness oscillation between 70% and 100%.",
        "code": (
            "import math\n\n"
            "def tick(t, ctx):\n"
            "    period = 3.0  # seconds per breath\n"
            "    v = 0.70 + 0.30 * (math.sin(t * 2 * math.pi / period) * 0.5 + 0.5)\n"
            "    return [v] * ctx.channel_count\n"
        ),
    },
    {
        "name": "Sequential On",
        "description": "Showcases turn on one by one, then all turn off together.",
        "code": (
            "def tick(t, ctx):\n"
            "    n = ctx.channel_count\n"
            "    cycle = 8.0  # seconds for full cycle\n"
            "    on_time = cycle / n  # time per showcase\n"
            "    pos = (t % cycle) / on_time  # 0..n\n"
            "    result = []\n"
            "    for i in range(n):\n"
            "        if i < int(pos):\n"
            "            result.append(1.0)\n"
            "        elif i == int(pos):\n"
            "            result.append(pos - int(pos))  # fade in\n"
            "        else:\n"
            "            result.append(0.0)\n"
            "    return result\n"
        ),
    },
    {
        "name": "Wave",
        "description": "Brightness wave travelling across showcases.",
        "code": (
            "import math\n\n"
            "def tick(t, ctx):\n"
            "    n = ctx.channel_count\n"
            "    speed = 1.0   # wave cycles per second\n"
            "    result = []\n"
            "    for i in range(n):\n"
            "        phase = (i / n) * 2 * math.pi\n"
            "        v = 0.5 + 0.5 * math.sin(t * speed * 2 * math.pi - phase)\n"
            "        result.append(v)\n"
            "    return result\n"
        ),
    },
    {
        "name": "All On",
        "description": "All showcases at full brightness.",
        "code": (
            "def tick(t, ctx):\n"
            "    return [1.0] * ctx.channel_count\n"
        ),
    },
]


class EffectStore:
    def __init__(self, data_dir: str = "data"):
        self._path = os.path.join(data_dir, "effects.json")
        self._effects: list[Effect] = []
        self._load()

    # ── Public API ───────────────────────────────────────────────

    def all(self) -> list[Effect]:
        return list(self._effects)

    def get(self, effect_id: str) -> Optional[Effect]:
        return next((e for e in self._effects if e.id == effect_id), None)

    def create(self, name: str, code: str, description: str = "") -> Effect:
        effect = Effect(name=name, code=code, description=description)
        self._effects.append(effect)
        self._save()
        return effect

    def update(self, effect_id: str, **kwargs) -> Optional[Effect]:
        effect = self.get(effect_id)
        if effect is None:
            return None
        for k, v in kwargs.items():
            if hasattr(effect, k):
                setattr(effect, k, v)
        self._save()
        return effect

    def delete(self, effect_id: str) -> bool:
        before = len(self._effects)
        self._effects = [e for e in self._effects if e.id != effect_id]
        if len(self._effects) < before:
            self._save()
            return True
        return False

    # ── Persistence ──────────────────────────────────────────────

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._effects = [Effect.from_dict(d) for d in data]
                return
            except Exception as e:
                print(f"  [Effects] Failed to load {self._path}: {e}")
        # First run: seed with built-in examples
        self._effects = [Effect.from_dict(d) for d in _DEFAULT_EFFECTS]
        self._save()

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump([e.to_dict() for e in self._effects], f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"  [Effects] Failed to save: {e}")
