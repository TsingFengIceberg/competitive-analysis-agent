"""Tests for competition/visualization.py — chart generation."""

from __future__ import annotations

import pytest

try:
    import matplotlib  # noqa: F401
except ImportError:
    pytest.skip("matplotlib not installed", allow_module_level=True)

from competition.visualization import (  # noqa: E402
    generate_bar_chart,
    generate_heatmap,
    generate_line_chart,
    generate_pie_chart,
    generate_radar_chart,
    generate_wordcloud,
)


class TestRadarChart:
    def test_basic(self, tmp_path):
        path = tmp_path / "radar.png"
        generate_radar_chart(
            ["A", "B"], ["Price", "Features", "Users"],
            {("A", "Price"): 4, ("A", "Features"): 5, ("A", "Users"): 3,
             ("B", "Price"): 3, ("B", "Features"): 4, ("B", "Users"): 4},
            str(path),
        )
        assert path.exists()
        assert path.stat().st_size > 0


class TestHeatmap:
    def test_basic(self, tmp_path):
        path = tmp_path / "heatmap.png"
        generate_heatmap(
            ["A", "B", "C"], ["D1", "D2", "D3", "D4", "D5"],
            {("A", "D1"): 4, ("B", "D3"): 3, ("C", "D5"): 5},
            str(path),
        )
        assert path.exists()


class TestBarChart:
    def test_basic(self, tmp_path):
        path = tmp_path / "bar.png"
        generate_bar_chart(
            ["Pro", "Team", "Enterprise"],
            {"Product A": [20, 40, 80], "Product B": [19, 39, 75]},
            ["Product A", "Product B"],
            str(path), title="定价对比",
        )
        assert path.exists()


class TestLineChart:
    def test_basic(self, tmp_path):
        path = tmp_path / "line.png"
        generate_line_chart(
            ["Jan", "Feb", "Mar", "Apr"],
            {"Cursor": [10, 12, 15, 18], "Copilot": [8, 9, 11, 14]},
            str(path), title="Star 增长趋势",
        )
        assert path.exists()


class TestPieChart:
    def test_basic(self, tmp_path):
        path = tmp_path / "pie.png"
        generate_pie_chart(
            ["正面", "中性", "负面"], [60, 25, 15], str(path), title="用户情感分布",
        )
        assert path.exists()


class TestWordcloud:
    def test_basic(self, tmp_path):
        path = tmp_path / "wordcloud.png"
        generate_wordcloud(
            {"AI": 50, "补全": 40, "延迟": 30, "定价": 20, "UX": 15},
            str(path),
        )
        assert path.exists()  # bar chart fallback works too
