"""Two report charts (PNG) for docs/analytics/scoring-model.md."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.metrics import roc_curve  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT2 = "#52514e"
GRID = "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # categorical slots 1-3 of the reference palette


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=TEXT2, labelsize=9)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def roc_plot(frames: dict, metrics: dict, path: Path):
    fig, ax = plt.subplots(figsize=(6.4, 5.2), dpi=130, facecolor=SURFACE)
    _style(ax)
    labels = {"train": "обучающая", "test": "тестовая", "oot": "вне времени (2025H1)"}
    for color, name in zip(SERIES, ["train", "test", "oot"]):
        fr = frames[name]
        fpr, tpr, _ = roc_curve(fr["default"], -fr["score"])
        ax.plot(fpr, tpr, color=color, linewidth=2, label=f"{labels[name]}: Gini {metrics[name]['gini']:.3f}")
    ax.plot([0, 1], [0, 1], color=TEXT2, linewidth=1, linestyle="--")
    ax.set_xlabel("Доля хороших заемщиков ниже порога балла (FPR)", color=TEXT, fontsize=10)
    ax.set_ylabel("Доля дефолтов ниже порога балла (TPR)", color=TEXT, fontsize=10)
    ax.set_title("ROC-кривые балльной карты", color=TEXT, fontsize=12, loc="left")
    leg = ax.legend(frameon=False, fontsize=9, loc="lower right")
    for t in leg.get_texts():
        t.set_color(TEXT)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def grade_plot(grades: list[dict], path: Path):
    g = [r["grade"] for r in grades]
    x = np.arange(len(g))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), dpi=130, facecolor=SURFACE)
    ax = axes[0]
    _style(ax)
    w = 0.38
    dev_share = [(r["train"]["n"] + r["test"]["n"]) for r in grades]
    tot = sum(dev_share)
    dev_share = [v / tot * 100 for v in dev_share]
    oot_share = [r["oot"]["share"] * 100 for r in grades]
    ax.bar(x - w / 2 - 0.01, dev_share, w, color=SERIES[0], label="2024H2 (разработка)")
    ax.bar(x + w / 2 + 0.01, oot_share, w, color=SERIES[1], label="2025H1 (вне времени)")
    ax.set_xticks(x, g)
    ax.set_ylabel("Доля заявок, %", color=TEXT, fontsize=10)
    ax.set_title("Распределение по грейдам", color=TEXT, fontsize=12, loc="left")
    ax.legend(frameon=False, fontsize=9)
    ax = axes[1]
    _style(ax)
    obs_t = [(r["test"]["dr"] or 0) * 100 for r in grades]
    obs_o = [(r["oot"]["dr"] or 0) * 100 for r in grades]
    pred = [(r["test"]["pd_model_mean"] or 0) * 100 for r in grades]
    ax.bar(x - w / 2 - 0.01, obs_t, w, color=SERIES[0], label="наблюдаемый DR, тест")
    ax.bar(x + w / 2 + 0.01, obs_o, w, color=SERIES[1], label="наблюдаемый DR, вне времени")
    ax.plot(x, pred, color=SERIES[2], marker="o", markersize=7, linewidth=2, label="прогноз модели (средний PD)")
    for xi, v in zip(x, obs_t):
        ax.annotate(f"{v:.1f}", (xi - w / 2, v), textcoords="offset points", xytext=(0, 3), ha="center", fontsize=8, color=TEXT2)
    ax.set_xticks(x, g)
    ax.set_ylabel("Уровень дефолтов, %", color=TEXT, fontsize=10)
    ax.set_title("Калибровка: прогноз и факт по грейдам", color=TEXT, fontsize=12, loc="left")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
