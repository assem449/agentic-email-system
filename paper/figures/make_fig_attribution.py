"""Fig. 2: measured vs attributable cost reduction (values from app/cost_attribution.py)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

SYSTEMS = [  # (label, measured, attributable), top to bottom
    ("Rules v1 (frozen)", 28.98, 13.57),
    ("TF-IDF + SVM (OOF)", 40.71, 34.11),
    ("DistilBERT v2 (OOF)", 38.53, 35.78),
]
MEASURED, ATTRIB = "#9a9a9a", "#262626"
INK, MUTED, GRID = "#1a1a1a", "#555555", "#e3e3e3"

plt.rcParams.update({"font.family": "serif", "font.size": 8})
fig, ax = plt.subplots(figsize=(3.45, 2.05), dpi=300)

h, gap = 0.34, 0.04
for i, (name, m, a) in enumerate(SYSTEMS):
    y = len(SYSTEMS) - 1 - i
    for val, off, col in ((m, h / 2 + gap / 2, MEASURED), (a, -(h / 2 + gap / 2), ATTRIB)):
        ax.barh(y + off, val, height=h, color=col, edgecolor="white", linewidth=0.6, zorder=3)
        ax.text(val + 0.8, y + off, f"{val:.2f}%", va="center", ha="left",
                fontsize=7, color=INK, zorder=4)

ax.set_yticks(range(len(SYSTEMS)))
ax.set_yticklabels([s[0] for s in reversed(SYSTEMS)], color=INK)
ax.set_xlim(0, 50)
ax.set_xticks(range(0, 51, 10))
ax.set_xticklabels([f"{t}%" for t in range(0, 51, 10)], color=MUTED, fontsize=7)
ax.set_xlabel("Cost reduction vs. always-LLM", color=MUTED, fontsize=7)
ax.xaxis.grid(True, color=GRID, linewidth=0.5, zorder=0)
ax.tick_params(axis="both", length=0)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.spines["bottom"].set_color("#bdbdbd")
ax.spines["bottom"].set_linewidth(0.6)

from matplotlib.patches import Patch
ax.legend(handles=[Patch(color=MEASURED, label="measured"),
                   Patch(color=ATTRIB, label="attributable to correct routing")],
          loc="lower center", bbox_to_anchor=(0.42, 1.0), ncol=2, frameon=False,
          fontsize=7, handlelength=1.2, columnspacing=1.2)
fig.tight_layout(pad=0.3)
fig.savefig("paper/figures/fig3.png", dpi=300)
fig.savefig("paper/figures/fig3.pdf")
print("saved paper/figures/fig3.png and fig3.pdf")
