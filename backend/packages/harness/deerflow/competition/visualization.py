"""Visualization engine — matplotlib/seaborn chart generation for competitive analysis.

Per COMPETITION_PLAN.md §3.5.4: radar, heatmap, grouped bar, line, pie, wordcloud, bubble.
All charts output to Sandbox paths; PNG files referenced by ReportData sections.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_radar_chart(
    products: list[str], dimensions: list[str], ratings: dict[tuple[str, str], float],
    output_path: str | Path, title: str = "竞品对比雷达图",
) -> str:
    """Multi-product × multi-dimension radar comparison."""
    import math

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n_dims = len(dimensions)
    angles = [n / float(n_dims) * 2 * math.pi for n in range(n_dims)]
    angles += angles[:1]  # close the circle

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={"projection": "polar"})
    for product in products:
        values = [ratings.get((product, dim), 0) for dim in dimensions]
        values += values[:1]
        ax.plot(angles, values, "o-", linewidth=2, label=product)
        ax.fill(angles, values, alpha=0.1)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(dimensions, fontsize=10)
    ax.set_ylim(0, 5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(["1", "2", "3", "4", "5"], fontsize=8)
    ax.set_title(title, fontsize=14, pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))

    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)


def generate_heatmap(
    products: list[str], dimensions: list[str], ratings: dict[tuple[str, str], float],
    output_path: str | Path, title: str = "功能覆盖热力图",
) -> str:
    """Feature coverage matrix heatmap."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    matrix = np.zeros((len(products), len(dimensions)))
    for i, p in enumerate(products):
        for j, d in enumerate(dimensions):
            matrix[i][j] = ratings.get((p, d), 0)

    fig, ax = plt.subplots(figsize=(max(8, len(dimensions) * 1.5), max(4, len(products) * 0.8)))
    im = ax.imshow(matrix, cmap="YlOrRd", vmin=0, vmax=5, aspect="auto")

    ax.set_xticks(range(len(dimensions)))
    ax.set_xticklabels(dimensions, fontsize=9, rotation=45, ha="right")
    ax.set_yticks(range(len(products)))
    ax.set_yticklabels(products, fontsize=10)
    ax.set_title(title, fontsize=14)

    for i in range(len(products)):
        for j in range(len(dimensions)):
            val = matrix[i][j]
            text_color = "white" if val > 3 else "black"
            ax.text(j, i, f"{val:.0f}" if val > 0 else "N/A", ha="center", va="center", color=text_color, fontsize=9)

    fig.colorbar(im, ax=ax, label="Rating (1-5)")
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)


def generate_bar_chart(
    categories: list[str], values: dict[str, list[float]], group_labels: list[str],
    output_path: str | Path, title: str = "对比柱状图", xlabel: str = "", ylabel: str = "",
) -> str:
    """Grouped bar chart for pricing tier comparison etc."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    n_groups = len(categories)
    n_bars = len(group_labels)
    bar_width = 0.8 / n_bars
    x = np.arange(n_groups)

    fig, ax = plt.subplots(figsize=(max(8, n_groups * 1.5), 6))
    for i, label in enumerate(group_labels):
        vals = values.get(label, [0] * n_groups)
        offset = (i - n_bars / 2 + 0.5) * bar_width
        ax.bar(x + offset, vals, bar_width, label=label, alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=10)
    ax.set_title(title, fontsize=14)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.3)

    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)


def generate_line_chart(
    time_points: list[str], series: dict[str, list[float]],
    output_path: str | Path, title: str = "趋势折线图", ylabel: str = "",
) -> str:
    """Multi-series line chart for trend analysis."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    for label, values in series.items():
        ax.plot(time_points, values, "o-", linewidth=2, markersize=6, label=label)

    ax.set_title(title, fontsize=14)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    ax.tick_params(axis="x", rotation=30)

    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)


def generate_pie_chart(
    labels: list[str], sizes: list[float], output_path: str | Path,
    title: str = "情感分布", colors: list[str] | None = None,
) -> str:
    """Pie chart for sentiment distribution or market share."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    default_colors = ["#4CAF50", "#FF9800", "#F44336", "#9E9E9E"]
    if colors is None:
        colors = default_colors[: len(labels)]

    fig, ax = plt.subplots(figsize=(7, 7))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=colors, autopct="%1.1f%%",
        startangle=90, pctdistance=0.85,
    )
    for t in autotexts:
        t.set_fontsize(10)
    ax.set_title(title, fontsize=14)

    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)


def generate_wordcloud(
    word_freq: dict[str, float], output_path: str | Path,
    title: str = "用户高频关键词",
) -> str:
    """Word cloud from user feedback keywords. Falls back to bar chart if wordcloud not installed."""
    try:
        import matplotlib
        from wordcloud import WordCloud
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        wc = WordCloud(
            width=800, height=400, background_color="white",
            font_path=None,  # Use default font
            max_words=100, colormap="viridis",
        )
        wc.generate_from_frequencies(word_freq)

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.imshow(wc, interpolation="bilinear")
        ax.axis("off")
        ax.set_title(title, fontsize=14)
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
    except ImportError:
        logger.info("wordcloud not installed — falling back to bar chart for keywords")
        top = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:20]
        generate_bar_chart(
            [w for w, _ in top],
            {"frequency": [c for _, c in top]},
            ["frequency"],
            output_path, title=title,
        )
    return str(output_path)
