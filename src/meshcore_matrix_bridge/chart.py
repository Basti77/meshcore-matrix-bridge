"""Render a simple PNG chart of a telemetry timeseries.

Lazy-imports matplotlib so a missing dep only breaks the chart command,
not the whole bridge.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any


def render_chart(
    rows: list[dict[str, Any]],
    target: str,
    hours: float,
) -> tuple[bytes, int, int]:
    """Return (png_bytes, width, height). Raises on missing matplotlib."""
    import matplotlib  # type: ignore

    matplotlib.use("Agg")
    import matplotlib.dates as mdates  # type: ignore
    import matplotlib.pyplot as plt  # type: ignore

    # split into series by key
    series: dict[str, list[tuple[datetime, float]]] = {}
    for r in rows:
        ts = r.get("ts")
        vals = r.get("values") or {}
        if not ts or not isinstance(vals, dict):
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        for k, v in vals.items():
            if not isinstance(v, (int, float)):
                continue
            series.setdefault(k, []).append((dt, float(v)))

    # prioritize voltage + temperature
    ordered_keys: list[str] = []
    for prefer in ("voltage", "battery", "temperature", "humidity", "pressure"):
        for k in list(series.keys()):
            if k == prefer or k.startswith(prefer + "@"):
                if k not in ordered_keys:
                    ordered_keys.append(k)
    for k in series:
        if k not in ordered_keys:
            ordered_keys.append(k)

    volt_keys = [k for k in ordered_keys if k.startswith("voltage") or k.startswith("battery")]
    temp_keys = [k for k in ordered_keys if k.startswith("temperature")]
    other_keys = [k for k in ordered_keys if k not in volt_keys and k not in temp_keys]

    fig, ax_v = plt.subplots(figsize=(9, 4.5), dpi=110)
    fig.patch.set_facecolor("white")
    ax_v.set_title(f"{target} — last {hours:g} h  (n={len(rows)})")
    ax_v.set_xlabel("time (local)")
    ax_v.grid(True, alpha=0.3)

    lines = []
    labels = []
    if volt_keys:
        for k in volt_keys:
            xs, ys = zip(*series[k]) if series[k] else ([], [])
            (ln,) = ax_v.plot(xs, ys, "-", color="#b5491a", label=k)
            lines.append(ln)
            labels.append(k)
        ax_v.set_ylabel("Voltage [V]", color="#b5491a")
        ax_v.tick_params(axis="y", labelcolor="#b5491a")
    else:
        ax_v.set_ylabel("value")

    ax_t = None
    if temp_keys:
        ax_t = ax_v.twinx()
        for k in temp_keys:
            xs, ys = zip(*series[k]) if series[k] else ([], [])
            (ln,) = ax_t.plot(xs, ys, "-", color="#1f6fb5", label=k)
            lines.append(ln)
            labels.append(k)
        ax_t.set_ylabel("Temperature [°C]", color="#1f6fb5")
        ax_t.tick_params(axis="y", labelcolor="#1f6fb5")

    if other_keys and ax_t is None:
        for k in other_keys:
            xs, ys = zip(*series[k]) if series[k] else ([], [])
            (ln,) = ax_v.plot(xs, ys, "-", label=k)
            lines.append(ln)
            labels.append(k)

    if lines:
        ax_v.legend(lines, labels, loc="upper left", fontsize=8, framealpha=0.85)

    locator = mdates.AutoDateLocator()
    ax_v.xaxis.set_major_locator(locator)
    ax_v.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    fig.autofmt_xdate()
    fig.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    data = buf.getvalue()
    w, h = fig.canvas.get_width_height()
    return data, w, h
