"""Figures for the publication package, drawn ONLY from measured result files (no invented values).

    ..\\.venv-gpu\\Scripts\\python tools\\make_publication_figures.py
Inputs : outputs/benchmarks/phase1/results.json, outputs/benchmarks/soak/soak_10min_{before,after}_fix.json
Outputs: publication/figures/*.png
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "publication" / "figures"
OUT.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150})
NAMES = {"ssdlite": "SSDLite320\n(previous)", "rfdetr-nano": "RF-DETR Nano\n(selected)", "yolo26n": "YOLO26n",
         "yolo26s": "YOLO26s"}


def bench():
    r = json.loads((ROOT / "outputs" / "benchmarks" / "phase1" / "results.json").read_text(encoding="utf-8"))
    rows = {}
    for x in r["runs"]:
        d = rows.setdefault(x["model"], {})
        d[x["device"]] = x["speed"]["latency_ms_mean"]
        if "quality_vocdetiv_val" in x:
            d["q"] = x["quality_vocdetiv_val"]
    return rows


def fig_latency(rows):
    models = [m for m in NAMES if m in rows]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    w = 0.38
    for i, m in enumerate(models):
        ax.bar(i - w / 2, rows[m]["cpu"], w, color="#8a94b8", label="CPU (Ryzen 7 7840HS)" if i == 0 else None)
        ax.bar(i + w / 2, rows[m]["cuda"], w, color="#e0a800", label="GPU (RTX 4050 Laptop)" if i == 0 else None)
        ax.text(i - w / 2, rows[m]["cpu"] + 2, f"{rows[m]['cpu']:.0f}", ha="center", fontsize=8)
        ax.text(i + w / 2, rows[m]["cuda"] + 2, f"{rows[m]['cuda']:.0f}", ha="center", fontsize=8)
    ax.set_xticks(range(len(models)), [NAMES[m] for m in models])
    ax.set_ylabel("mean latency per frame (ms)")
    ax.set_title("Detector latency (Phase 1 benchmark), 640×480 recorded frames, FP32, batch 1", fontsize=10)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "fig2_detector_latency.png")
    plt.close(fig)


def fig_accuracy(rows):
    models = [m for m in NAMES if m in rows and "q" in rows[m]]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    w = 0.26
    keys = [("person_AP50", "AP@0.5", "#3d6fb6"), ("person_AP50_95", "AP@0.5:0.95", "#7aa6e0"),
            ("recall_at_0.40", "Recall @ 0.40", "#e0a800")]
    for k, (key, lab, col) in enumerate(keys):
        for i, m in enumerate(models):
            v = rows[m]["q"][key]
            ax.bar(i + (k - 1) * w, v, w, color=col, label=lab if i == 0 else None)
            ax.text(i + (k - 1) * w, v + 0.01, f"{v:.2f}", ha="center", fontsize=7)
    ax.set_xticks(range(len(models)), [NAMES[m] for m in models])
    ax.set_ylim(0, 0.85)
    ax.set_ylabel("score")
    ax.set_title("Person detection, 365 near-IR validation images (129 people)", fontsize=10)
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "fig3_person_detection_quality.png")
    plt.close(fig)


def fig_cpu_threads():
    # measured in-process at 5 frames/s, RF-DETR on GPU (docs/NEUROSONIC_FINAL_TECHNICAL_DOCUMENTATION.md, section 9)
    threads, cpu = [8, 4, 2], [712, 326, 121]
    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    ax.bar([str(t) for t in threads], cpu, color=["#c0504d", "#e0a800", "#3d9e6b"])
    for i, v in enumerate(cpu):
        ax.text(i, v + 10, f"{v} %", ha="center", fontsize=8)
    ax.set_xlabel("PyTorch CPU threads (RF-DETR on GPU)")
    ax.set_ylabel("server CPU, % of one core")
    ax.set_title("CPU use at 5 frames/s\n(median frame time 30 / 38 / 25 ms)", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "fig4_cpu_thread_fix.png")
    plt.close(fig)


def fig_soak():
    """Before/after the single-inference-thread + FP16 change: same clip, 5 frames/s, slow cloud request every 60 s."""
    d = ROOT / "outputs" / "benchmarks" / "soak"
    runs = [("before fix (FP32, new thread per request)", d / "soak_10min_before_fix.json", "#c0504d"),
            ("after fix (FP16, one inference thread)", d / "soak_10min_after_fix.json", "#3d6fb6")]
    runs = [(lab, json.loads(p.read_text(encoding="utf-8"))["windows"], c) for lab, p, c in runs if p.exists()]
    if not runs:
        return False
    fig, axs = plt.subplots(3, 1, figsize=(6.6, 6.0), sharex=True)
    for lab, w, c in runs:
        t = [x["t_s"] / 60 for x in w]
        axs[0].plot(t, [x["fps"] for x in w], color=c, label=lab)
        axs[1].plot(t, [x["lat_median_ms"] for x in w], color=c)
        axs[1].plot(t, [x["lat_p90_ms"] for x in w], color=c, ls=":", lw=1)
        axs[2].plot(t, [x["rss_mib"] for x in w], color=c)
    axs[0].set_ylabel("frames/s")
    axs[0].set_ylim(0, 6)
    axs[0].legend(frameon=False, fontsize=8, loc="lower right")
    axs[1].set_ylabel("request ms\n(solid median,\ndotted p90)")
    axs[1].set_ylim(bottom=0)
    axs[2].set_ylabel("server RAM (MiB)")
    axs[2].set_ylim(bottom=0)
    axs[2].set_xlabel("minutes")
    fig.suptitle("10-minute soak tests: 5 frames/s stream, slow (20 s) cloud request every 60 s", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "fig5_soak_test.png")
    plt.close(fig)
    return True


def box(ax, x, y, w, h, text, fc="#eef2fb", ec="#3d6fb6"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc=fc, ec=ec, lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=8)


def arrow(ax, x1, y1, x2, y2, text=None):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color="#444", lw=1.1))
    if text:
        ax.text((x1 + x2) / 2 + 0.05, (y1 + y2) / 2, text, fontsize=7, color="#444")


def fig_architecture():
    fig, ax = plt.subplots(figsize=(8, 5.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6.6)
    ax.axis("off")
    box(ax, 0.2, 4.6, 2.3, 1.7, "iPhone (Safari)\ncamera · microphone · GPS\nspeaker", fc="#fff6dc", ec="#e0a800")
    box(ax, 3.2, 5.4, 3.2, 0.9, "HTTPS API (Python, local Wi-Fi)\nneurosonic/server.py")
    box(ax, 3.2, 3.75, 3.2, 1.35, "Perception pipeline\nquality check → RF-DETR Nano (GPU)\nor SSDLite (CPU)\n→ camera motion → tracking")
    box(ax, 3.2, 2.5, 3.2, 1.0, "Walking-path state + events\n(entering / crossing)")
    box(ax, 3.2, 1.1, 3.2, 1.0, "Speech: priority queue\nPiper neural voice (offline)")
    box(ax, 7.0, 4.6, 2.8, 1.0, "Voice commands\nVosk (offline)")
    box(ax, 7.0, 3.3, 2.8, 1.0, "Offline map + A* routing\n(OpenStreetMap, Vellore)")
    box(ax, 7.0, 2.0, 2.8, 1.0, "History (SQLite, text only)")
    box(ax, 7.0, 0.5, 2.8, 1.1, "Optional online description\nGemini (opt-in, needs internet)", fc="#f4f4f4", ec="#888")
    arrow(ax, 2.5, 5.6, 3.2, 5.8)
    ax.text(2.55, 5.0, "JPEG 5/s,\nWAV, GPS", fontsize=7, color="#444")
    arrow(ax, 4.8, 5.4, 4.8, 5.1)
    arrow(ax, 4.8, 3.75, 4.8, 3.5)
    arrow(ax, 4.8, 2.5, 4.8, 2.1)
    arrow(ax, 3.2, 1.6, 1.4, 4.6, "spoken alerts")
    arrow(ax, 6.4, 5.85, 7.0, 5.1)
    arrow(ax, 6.4, 5.85, 7.0, 3.8)
    arrow(ax, 6.4, 3.0, 7.0, 2.5)
    arrow(ax, 6.4, 5.85, 7.0, 1.05)
    ax.text(3.2, 0.2, "Laptop: HP Omen, Ryzen 7 7840HS, RTX 4050 Laptop GPU (6 GB)", fontsize=8, color="#444")
    fig.tight_layout()
    fig.savefig(OUT / "fig1_architecture.png")
    plt.close(fig)


def fig_pipeline():
    fig, ax = plt.subplots(figsize=(10, 2.7))
    ax.set_xlim(0, 10.6)
    ax.set_ylim(0, 2.4)
    ax.axis("off")
    steps = ["Camera frame\n320 px JPEG", "Quality +\nsharpness", "Detector\nRF-DETR (GPU)\n/ SSDLite (CPU)",
             "Camera\nmotion\n(LK + RANSAC)", "ByteTrack-\nstyle\ntracking", "Path state\n+ events", "Priority\nspeech\n(Piper)"]
    w, gap = 1.25, 0.25
    for i, s in enumerate(steps):
        x = 0.1 + i * (w + gap)
        box(ax, x, 0.95, w, 1.1, s)
        if i:
            arrow(ax, x - gap, 1.5, x, 1.5)
    ax.text(0.1, 0.5, "Laptop, 5 frames/s, RF-DETR FP16 on the GPU: detector median 53 ms (GPU in its low-power state between "
            "frames);", fontsize=8, color="#444")
    ax.text(0.1, 0.2, "request median 70–78 ms in the 10-minute soak test; capture → answer median 67 ms in the browser test "
            "(loopback, no Wi-Fi).", fontsize=8, color="#444")
    fig.tight_layout()
    fig.savefig(OUT / "fig6_perception_pipeline.png")
    plt.close(fig)


if __name__ == "__main__":
    rows = bench()
    fig_architecture()
    fig_pipeline()
    fig_latency(rows)
    fig_accuracy(rows)
    fig_cpu_threads()
    print("soak figure:", fig_soak())
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))
