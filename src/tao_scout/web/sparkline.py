"""Server-rendered SVG sparklines.

Pure Python — no JS, no client-side charting library. The output is a small
inline ``<svg>`` element that templates can drop into a card or table cell.
"""

from __future__ import annotations

from collections.abc import Sequence


def render_sparkline(
    values: Sequence[float],
    *,
    width: int = 120,
    height: int = 30,
    stroke: str = "#2563eb",
    fill: str = "#dbeafe",
    min_value: float = 0.0,
    max_value: float = 10.0,
    label: str | None = None,
) -> str:
    """Return inline SVG markup for a polyline of ``values``.

    Empty list returns a placeholder svg with no glyph (so the layout stays
    stable). A single point renders a small circle. Two or more points render
    a polyline with a soft fill underneath.

    The result is intentionally inline + self-contained so it can be inserted
    into Jinja templates with ``{{ render_sparkline(...) | safe }}``.
    """
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if max_value <= min_value:
        raise ValueError("max_value must be > min_value")

    aria = label or (
        f"score history sparkline, {len(values)} point(s)"
        + (f", latest {values[-1]:.2f}" if values else "")
    )
    common = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{aria}">'
    )

    if not values:
        return common + "</svg>"

    if len(values) == 1:
        cx = width / 2
        cy = height / 2
        return (
            common
            + f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="{stroke}"/>'
            + "</svg>"
        )

    span = max_value - min_value
    n = len(values)
    pad = 2
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad
    pts: list[str] = []
    for i, v in enumerate(values):
        clamped = max(min_value, min(max_value, float(v)))
        x = pad + i * inner_w / (n - 1)
        y = pad + inner_h - ((clamped - min_value) / span) * inner_h
        pts.append(f"{x:.1f},{y:.1f}")
    polyline_pts = " ".join(pts)
    polygon_pts = f"{pad},{height - pad} {polyline_pts} {width - pad},{height - pad}"
    return (
        common
        + f'<polygon points="{polygon_pts}" fill="{fill}" opacity="0.6"/>'
        + f'<polyline points="{polyline_pts}" fill="none" stroke="{stroke}" '
        + 'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        + "</svg>"
    )


__all__ = ["render_sparkline"]
