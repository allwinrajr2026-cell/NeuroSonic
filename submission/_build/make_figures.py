"""Figures for the assignment documents. Every number is either from a cited source (noted next to it)
or read from the project's own result files under implementation/outputs/."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

HERE = Path(__file__).resolve().parent
IMPL = HERE.parents[1]
OUT = HERE / "figures"
OUT.mkdir(exist_ok=True)
plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"], "font.size": 9,
                     "axes.spines.top": False, "axes.spines.right": False, "savefig.dpi": 220})
C1, C2, C3 = "#2d5a9e", "#c0504d", "#7f7f7f"


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# A. WHO fact sheet (10 Feb 2026): causes of distance vision impairment or blindness, millions
causes = [("Cataract", 94), ("Refractive error", 88.4), ("AMD", 8), ("Glaucoma", 7.7), ("Diabetic retinopathy", 3.9)]
fig, ax = plt.subplots(figsize=(3.4, 2.0))
ax.barh([c for c, _ in causes][::-1], [v for _, v in causes][::-1], color=C1)
for i, (_, v) in enumerate(causes[::-1]):
    ax.text(v + 1, i, f"{v:g} M", va="center", fontsize=8)
ax.set_xlabel("People (millions)")
ax.set_xlim(0, 110)
save(fig, "figA_who_causes.png")

# B. Lancet Global Health 2021 (GBD 2020): 2020 estimate vs 2050 projection, millions
fig, ax = plt.subplots(figsize=(3.4, 2.0))
groups = ["Blind", "Moderate/severe VI"]
y2020, y2050 = [43.3, 295], [61.0, 474]
x = range(len(groups))
b1 = ax.bar([i - 0.18 for i in x], y2020, 0.36, color=C1, label="2020 (estimate)")
b2 = ax.bar([i + 0.18 for i in x], y2050, 0.36, color=C2, label="2050 (projection)")
for bars in (b1, b2):
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 6, f"{b.get_height():g}", ha="center", fontsize=8)
ax.set_xticks(list(x), groups)
ax.set_ylabel("People (millions)")
ax.set_ylim(0, 540)
ax.legend(frameon=False, fontsize=8)
save(fig, "figB_gbd_projection.png")

# C. India NBVIS 2015-19: prevalence of blindness by age group (%), people aged 50+
ages = [("50-59", 0.5), ("60-69", 1.6), ("70-79", 4.1), ("80+", 11.6)]
fig, ax = plt.subplots(figsize=(3.4, 1.9))
bars = ax.bar([a for a, _ in ages], [v for _, v in ages], color=C1)
for b in bars:
    ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.25, f"{b.get_height():g}%", ha="center", fontsize=8)
ax.axhline(1.99, color=C2, ls="--", lw=1)
ax.text(3.45, 2.3, "all 50+: 1.99%", color=C2, ha="right", fontsize=8)
ax.set_ylabel("Blindness prevalence (%)")
ax.set_xlabel("Age group (years)")
ax.set_ylim(0, 13.5)
save(fig, "figC_india_age.png")

# D. Timeline of the approaches cited in the survey (years of the cited documents)
events = [(1981, "Ultrasonic cane\n(US4280204)", 0), (2005, "Camera + speech\nrecogniser (US2005/0208457)", 1),
          (2016, "Hand-held nav. device\n(US9429446)", 0), (2017, "Wearable ultrasound\n(US9846231)", 1),
          (2019, "RGB-D wearables;\nCaBot robot", 0), (2020, "DETR: transformer\ndetection", 1),
          (2023, "Head-mounted\nwearable (Sensors)", 0), (2025, "WOAD (Nat. Commun.);\nNMI wearable; Glide", 1)]
fig, ax = plt.subplots(figsize=(7.0, 1.9))
ax.axhline(0, color="black", lw=1)
for i, (yr, label, up) in enumerate(events):  # evenly spaced (not to scale); the year is in the label
    y = 0.25 if up else -0.25
    ax.plot([i, i], [0, y], color=C3, lw=0.8)
    ax.plot(i, 0, "o", color=C1, ms=4)
    ax.text(i, y + (0.05 if up else -0.05), f"{yr}\n{label}", ha="center", va="bottom" if up else "top", fontsize=7)
ax.set_ylim(-1.0, 1.0)
ax.set_xlim(-0.7, len(events) - 0.3)
ax.axis("off")
save(fig, "figD_trend_timeline.png")

# E. WOAD exp72 person precision-recall curves on the published dataset (project's own evaluation)
fig, ax = plt.subplots(figsize=(3.4, 2.3))
for run, lab, col in [("nc10_val_person", "val (129 people), AP@0.5 0.218", C1),
                      ("nc10_train_person", "train (458 people), AP@0.5 0.173", C2)]:
    d = json.loads((IMPL / "outputs" / "eval" / run / "pr_curve.json").read_text())
    p = d["precision_at_iou50"]
    p = p["person"] if isinstance(p, dict) else p
    ax.plot(d["recall_grid"], p, color=col, lw=1.2, label=lab)
ax.set_xlabel("Recall")
ax.set_ylabel("Precision")
ax.set_xlim(0, 1)
ax.set_ylim(0, 1.02)
ax.legend(frameon=False, fontsize=7, loc="upper right")
save(fig, "figE_woad_pr_curve.png")

# F. WOAD architecture block diagram (from the verified checkpoint structure)
fig, ax = plt.subplots(figsize=(7.0, 2.3))
ax.axis("off")
ax.set_xlim(0, 100)
ax.set_ylim(0, 34)


def box(x, y, w, h, t, fc="#eef2f9"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4", fc=fc, ec=C1, lw=0.9))
    ax.text(x + w / 2, y + h / 2, t, ha="center", va="center", fontsize=7)


def arrow(x1, y1, x2, y2):
    ax.annotate("", (x2, y2), (x1, y1), arrowprops=dict(arrowstyle="->", lw=0.8, color="#333"))


box(1, 22, 13, 8, "Near-IR frame\n640x480 (CS30)")
box(1, 4, 13, 8, "Colour-mapped\ndepth (CS30 SDK)")
box(19, 22, 14, 8, "YOLOv5s layers 0-2\n64x160x160")
box(19, 4, 14, 8, "Depth stem\nConv-Conv-C3")
box(38, 11, 18, 12, "Avg-pool 8x8 -> 128 tokens\n+ pos. embedding\n8 transformer blocks\n(8 heads, d=64)", "#fbefe9")
box(61, 11, 14, 12, "Re-weight both\nstreams, concat,\nconv fuse")
box(80, 11, 18, 12, "YOLOv5s backbone +\nPAN neck + Detect\n(person, Ebike, Car)\n25,200 candidates")
arrow(14, 26, 19, 26); arrow(14, 8, 19, 8)
arrow(33, 26, 38, 20); arrow(33, 8, 38, 14)
arrow(56, 17, 61, 17); arrow(75, 17, 80, 17)
save(fig, "figF_woad_arch.png")

# H. Reported vs measured person AP@0.5 (different datasets: not like-for-like)
fig, ax = plt.subplots(figsize=(3.4, 2.0))
labs = ["Reported\n(authors' val,\n187 images)", "Measured\n(published val,\n365 images)", "Measured\n(published train,\n1286 images)"]
vals = [0.771, 0.218, 0.173]
bars = ax.bar(labs, vals, color=[C3, C1, C1])
for b in bars:
    ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.02, f"{b.get_height():.3f}", ha="center", fontsize=8)
ax.set_ylabel("Person AP@0.5")
ax.set_ylim(0, 0.9)
ax.tick_params(axis="x", labelsize=7)
save(fig, "figH_reported_vs_measured.png")
print("figures:", sorted(p.name for p in OUT.glob("*.png")))
