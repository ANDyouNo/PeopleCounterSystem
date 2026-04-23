"""Safe execution of user-supplied effect scripts.

The script must define a function:
    tick(t: float, ctx: EffectContext) -> list[float] | dict[int, float]

  t   — seconds elapsed since the effect started
  ctx — EffectContext with channel_count, people, fps

Returns a list of brightness values (0.0–1.0) per showcase channel,
or a dict mapping channel index → brightness.
"""

from __future__ import annotations
import math
import time
import traceback
from typing import Optional
from .models import EffectContext

# Modules available to effect scripts
_ALLOWED_MODULES = {
    "math":   math,
    "time":   time,
}


class ExecutionError(Exception):
    pass


class EffectExecutor:
    """Compiles and runs a single effect script."""

    def __init__(self, code: str):
        self._code = code
        self._globals: dict = {}
        self._compiled = None
        self._error: Optional[str] = None
        self._compile()

    @property
    def ok(self) -> bool:
        return self._error is None

    @property
    def error(self) -> Optional[str]:
        return self._error

    def _compile(self):
        globs = {"__builtins__": _safe_builtins(_ALLOWED_MODULES)}
        globs.update(_ALLOWED_MODULES)
        try:
            compiled = compile(self._code, "<effect>", "exec")
            exec(compiled, globs)  # noqa: S102
            if "tick" not in globs or not callable(globs["tick"]):
                self._error = "Script must define a callable 'tick(t, ctx)'"
                return
            self._globals = globs
            self._compiled = compiled
        except SyntaxError as e:
            self._error = f"SyntaxError: {e}"
        except Exception as e:
            self._error = f"CompileError: {e}"

    def run(self, t: float, ctx: EffectContext) -> list[float]:
        """Execute tick(t, ctx) and return normalised brightness list."""
        if not self.ok:
            raise ExecutionError(self._error)
        try:
            result = self._globals["tick"](t, ctx)
        except Exception:
            raise ExecutionError(traceback.format_exc())

        return _normalise(result, ctx.channel_count)


def _normalise(result, channel_count: int) -> list[float]:
    """Convert tick() return value to list[float] of length channel_count."""
    if isinstance(result, dict):
        out = [0.0] * channel_count
        for k, v in result.items():
            if isinstance(k, int) and 0 <= k < channel_count:
                out[k] = float(max(0.0, min(1.0, v)))
        return out
    # Assume iterable
    values = list(result)
    out = []
    for v in values[:channel_count]:
        out.append(float(max(0.0, min(1.0, v))))
    # Pad with zeros if shorter
    while len(out) < channel_count:
        out.append(0.0)
    return out


def _make_restricted_import(allowed_modules: dict):
    """Return an __import__ that only allows whitelisted modules."""
    def _import(name, globals=None, locals=None, fromlist=(), level=0):
        if name not in allowed_modules:
            raise ImportError(
                f"Module '{name}' is not available in effect scripts. "
                f"Allowed: {', '.join(sorted(allowed_modules))}"
            )
        return allowed_modules[name]
    return _import


def _safe_builtins(allowed_modules: dict) -> dict:
    """Return a restricted __builtins__ dict safe for untrusted code."""
    allowed = [
        "abs", "bool", "dict", "enumerate", "float", "int", "len",
        "list", "map", "max", "min", "print", "range", "round",
        "str", "sum", "tuple", "type", "zip",
    ]
    import builtins
    result = {name: getattr(builtins, name) for name in allowed if hasattr(builtins, name)}
    result["__import__"] = _make_restricted_import(allowed_modules)
    return result
