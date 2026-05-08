"""Sparkline SVG renderer (M4)."""

from __future__ import annotations

import re

import pytest

from tao_scout.web.sparkline import render_sparkline


def test_empty_values_returns_placeholder_svg() -> None:
    out = render_sparkline([])
    assert out.startswith("<svg")
    assert out.endswith("</svg>")
    assert "polyline" not in out
    assert "circle" not in out


def test_single_value_renders_as_circle() -> None:
    out = render_sparkline([5.0])
    assert "<circle" in out
    assert "polyline" not in out


def test_multiple_values_render_polyline_and_polygon() -> None:
    out = render_sparkline([1.0, 5.0, 7.0, 3.0])
    assert "<polyline" in out
    assert "<polygon" in out
    # Four points → four "x,y" coordinate pairs in the polyline.
    pts = re.search(r'<polyline points="([^"]+)"', out)
    assert pts is not None
    assert len(pts.group(1).split(" ")) == 4


def test_values_are_clamped_to_axis_range() -> None:
    """Values outside [min_value, max_value] must not produce points outside the SVG box."""
    out = render_sparkline([-3.0, 0.0, 5.0, 15.0], width=100, height=40)
    pts = re.search(r'<polyline points="([^"]+)"', out)
    assert pts is not None
    coords = [tuple(map(float, p.split(","))) for p in pts.group(1).split(" ")]
    for x, y in coords:
        assert 0 <= x <= 100, f"x out of range: {x}"
        assert 0 <= y <= 40, f"y out of range: {y}"


def test_dimensions_are_validated() -> None:
    with pytest.raises(ValueError):
        render_sparkline([1.0, 2.0], width=0)
    with pytest.raises(ValueError):
        render_sparkline([1.0, 2.0], height=-5)
    with pytest.raises(ValueError):
        render_sparkline([1.0, 2.0], min_value=10.0, max_value=10.0)


def test_aria_label_includes_count_and_latest() -> None:
    out = render_sparkline([1.0, 4.5, 9.99])
    assert 'aria-label="score history sparkline, 3 point(s), latest 9.99"' in out


def test_custom_label_overrides_default() -> None:
    out = render_sparkline([1.0, 2.0], label="developer fit trend")
    assert 'aria-label="developer fit trend"' in out


def test_output_is_safe_inline_svg() -> None:
    """No external refs, no scripts, no event handlers."""
    out = render_sparkline([1.0, 2.0, 3.0])
    assert "<script" not in out.lower()
    assert "onload" not in out.lower()
    assert "onerror" not in out.lower()
    assert "javascript:" not in out.lower()
