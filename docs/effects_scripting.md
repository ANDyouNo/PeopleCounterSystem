# Showcase Effects — Scripting API

Effects are Python scripts that run inside the People Counter backend at **30 fps**.
Each frame your `tick()` function is called and the returned brightness values are
sent directly to the ESP8266 → PCA9685 → showcase LED strips.

---

## Basic structure

Every effect script must define exactly one function:

```python
def tick(t, ctx):
    ...
    return [...]   # list of brightness values
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `t` | `float` | Seconds elapsed since the effect was activated |
| `ctx` | `EffectContext` | Runtime context (see below) |

### Return value

Return a **list of `float`** values, one per showcase channel, in the range `0.0` (off) to `1.0` (full brightness).

```python
# Turn all showcases on at 80%
def tick(t, ctx):
    return [0.8] * ctx.channel_count
```

You can also return a **dict** mapping channel index to brightness — useful when you only want to control specific showcases:

```python
# Only showcase 0 and 2, others stay off
def tick(t, ctx):
    return {0: 1.0, 2: 0.5}
```

Values outside `[0.0, 1.0]` are automatically clamped.

---

## EffectContext reference

`ctx` is passed to every `tick()` call.

| Attribute | Type | Description |
|-----------|------|-------------|
| `ctx.channel_count` | `int` | Number of showcase channels (from Settings) |
| `ctx.people` | `int` | People currently detected in frame |
| `ctx.fps` | `float` | Engine frame rate (30.0) |

---

## Available modules

These modules are pre-imported and available without an explicit `import` statement:

| Module | Usage |
|--------|-------|
| `math` | Trigonometry, `sin`, `cos`, `pi`, `sqrt`, … |
| `time` | `time.time()` for wall-clock timestamps |

Standard Python builtins are also available: `abs`, `int`, `float`, `range`, `len`, `min`, `max`, `round`, `sum`, `enumerate`, `zip`, `list`, `dict`, `map`, `bool`, `str`, `type`, `tuple`, `print`.

> **Note:** Network access, file I/O, `os`, `sys`, and `subprocess` are **not available** in effect scripts.

---

## Examples

### Breathing (70% – 100%)

```python
import math

def tick(t, ctx):
    period = 3.0  # seconds per breath
    v = 0.70 + 0.30 * (math.sin(t * 2 * math.pi / period) * 0.5 + 0.5)
    return [v] * ctx.channel_count
```

### Sequential on / off

```python
def tick(t, ctx):
    n = ctx.channel_count
    cycle = 8.0        # total cycle length in seconds
    on_time = cycle / n

    pos = (t % cycle) / on_time  # 0 .. n
    result = []
    for i in range(n):
        if i < int(pos):
            result.append(1.0)
        elif i == int(pos):
            result.append(pos - int(pos))  # smooth fade-in for current
        else:
            result.append(0.0)
    return result
```

### Wave across showcases

```python
import math

def tick(t, ctx):
    n     = ctx.channel_count
    speed = 0.8  # wave cycles per second

    result = []
    for i in range(n):
        phase = (i / n) * 2 * math.pi
        v = 0.5 + 0.5 * math.sin(t * speed * 2 * math.pi - phase)
        result.append(v)
    return result
```

### React to people count

```python
import math

def tick(t, ctx):
    if ctx.people == 0:
        # Slow breathing when room is empty
        v = 0.3 + 0.2 * math.sin(t * 2 * math.pi / 4.0)
        return [v] * ctx.channel_count
    else:
        # All on full when someone is in the room
        return [1.0] * ctx.channel_count
```

### Strobe (use carefully — slow frequency recommended)

```python
def tick(t, ctx):
    freq = 1.0  # flashes per second
    on = (t * freq % 1.0) < 0.5
    return [1.0 if on else 0.0] * ctx.channel_count
```

### Alternating groups

```python
import math

def tick(t, ctx):
    n = ctx.channel_count
    speed = 0.5  # group swaps per second
    phase = (t * speed) % 1.0
    result = []
    for i in range(n):
        group = i % 2  # even / odd
        result.append(1.0 if (group == int(phase * 2)) else 0.1)
    return result
```

### Per-showcase brightness with individual timings

```python
import math

def tick(t, ctx):
    result = []
    for i in range(ctx.channel_count):
        phase  = i * 0.7      # offset between showcases
        period = 2.0 + i * 0.3  # slightly different speed per showcase
        v = 0.6 + 0.4 * math.sin((t + phase) * 2 * math.pi / period)
        result.append(v)
    return result
```

---

## Tips & common mistakes

**Use `t` for time, not `time.time()`**
`t` resets to 0 each time the effect is activated, making the animation always start from the beginning. `time.time()` gives an absolute timestamp.

**Keep `tick()` fast**
The function is called 30 times per second. Avoid heavy computation or loops with thousands of iterations.

**Test math before deploying**
Errors at runtime (e.g. division by zero, wrong types) are caught and displayed in the Effects page error banner. The showcases will go dark until the error is fixed and the effect is reactivated.

**Importing `math` is optional but explicit is better**
The `math` module is always available, but adding `import math` at the top makes scripts portable and readable.

**`print()` works**
Output from `print()` goes to the server console — useful for debugging value ranges while developing.

---

## Lifecycle

1. You click **▶ Activate** — the script is compiled.
2. If compilation fails (syntax error, missing `tick` function), an error is shown and nothing changes.
3. If compilation succeeds, the engine starts calling `tick()` at 30 fps.
4. Runtime errors (exceptions inside `tick()`) are displayed in the error banner; the showcases go dark.
5. You click **■ Stop** — the effect stops, showcases hold the last values until the engine is disabled or another effect starts.
6. Disabling the **Effects Engine** toggle sends `MODE:auto` to the ESP — showcases return to the normal auto/manual mode.

---

## ESP watchdog

When the effects engine is active, the ESP expects a UDP packet every **3 seconds** at minimum.
The engine sends frames at 30 fps, so under normal operation the watchdog never fires.
If the Python backend crashes or loses WiFi, the ESP will turn off all showcases after 3 seconds automatically.
