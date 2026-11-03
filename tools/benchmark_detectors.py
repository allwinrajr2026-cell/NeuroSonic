"""Phase 1 controlled detector benchmark: SSDLite320 (current production) vs RF-DETR vs YOLO26, CPU and GPU.

Not used by the app. Run in the separate GPU environment (F:\\Projects\\WOAD-Research\\.venv-gpu):

    ..\\.venv-gpu\\Scripts\\python tools\\benchmark_detectors.py --models ssdlite rfdetr-nano rfdetr-small yolo26n yolo26s
        --devices cpu cuda --out outputs/benchmarks/phase1

Identical inputs for every detector:
  * quality: the published WOAD dataset VOCdevkit_nc_10, val split (365 near-IR images, YOLO labels, class 0 = person);
    person AP@0.5 and AP@0.5:0.95 with the project's own metric code (woad.metrics.ap_per_class, as tools/evaluate.py).
    These are infrared images, not phone colour photos: absolute numbers are a domain-shifted proxy; the comparison
    between detectors on identical images is what this measures.
  * speed: the first N frames of the recorded detec_test sequence (640 x 480 near-IR video frames), each detector at its
    published default input size; latency = preprocessing + inference + postprocessing on an in-memory frame (disk
    reads excluded), after warm-up; GPU timings synchronised; CPU usage via psutil; GPU memory via the PyTorch
    allocator peak and nvidia-smi.
  * qualitative: test_street.jpg (a real Vellore street, colour), detections >= the production threshold 0.40.
All runs are FP32 (no TensorRT, no FP16), batch 1, so the numbers are comparable but not each model's best case.
"""
import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from woad.metrics import ap_per_class, process_batch  # noqa: E402

DATA = ROOT.parent / "datasets"
VAL_IMAGES = DATA / "VOCdetiv_data" / "VOCdevkit_nc_10" / "images" / "val"
VAL_LABELS = DATA / "VOCdetiv_data" / "VOCdevkit_nc_10" / "labels" / "val"
SEQ = DATA / "detec_test" / "detec_test" / "ir"
STREET = ROOT.parent / "test_street.jpg"
SSDLITE_WEIGHTS = ROOT / "models" / "rgb" / "ssdlite320_mobilenet_v3_large_coco-a79551df.pth"
WEIGHTS_DIR = ROOT / "models" / "benchmark"
PROD_THRESHOLD = 0.40
COCO_PERSON_NAME = "person"


# ----------------------------------------------------------------------------- detector wrappers
class Detector:
    """predict(bgr) -> (boxes_xyxy [N,4] float, scores [N], class_names list) in original image pixels."""
    name = ""
    input_desc = ""


class SSDLite(Detector):
    def __init__(self, device):
        from torchvision.models.detection import ssdlite320_mobilenet_v3_large
        self.name, self.input_desc = "ssdlite320 (production)", "320 x 320 (torchvision internal resize)"
        m = ssdlite320_mobilenet_v3_large(weights=None, weights_backbone=None, num_classes=91,
                                          score_thresh=0.001, detections_per_img=300)
        m.load_state_dict(torch.load(SSDLITE_WEIGHTS, map_location="cpu", weights_only=True))
        self.m = m.eval().to(device)
        self.device = device
        from torchvision.models.detection import SSDLite320_MobileNet_V3_Large_Weights
        self.names = SSDLite320_MobileNet_V3_Large_Weights.COCO_V1.meta["categories"]

    @torch.inference_mode()
    def predict(self, bgr):
        x = torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).permute(2, 0, 1).float().div(255).to(self.device)
        o = self.m([x])[0]
        return (o["boxes"].float().cpu().numpy(), o["scores"].float().cpu().numpy(),
                [self.names[i] for i in o["labels"].cpu().tolist()])


class RFDETR(Detector):
    def __init__(self, device, size):
        import rfdetr
        from PIL import Image  # noqa: F401
        cls = {"nano": rfdetr.RFDETRNano, "small": rfdetr.RFDETRSmall}[size]
        cwd = os.getcwd()
        WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        os.chdir(WEIGHTS_DIR)                       # rfdetr downloads its checkpoint into the working directory
        try:
            self.m = cls(device=device)
        finally:
            os.chdir(cwd)
        self.name = f"rf-detr-{size}"
        self.input_desc = f"{self.m.model_config.resolution} x {self.m.model_config.resolution} (package default)"
        from rfdetr.assets.coco_classes import COCO_CLASSES   # COCO category id -> name (1 = person)
        self.names = COCO_CLASSES

    def predict(self, bgr):
        from PIL import Image
        det = self.m.predict(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)), threshold=0.001)
        return (np.asarray(det.xyxy, dtype=np.float32), np.asarray(det.confidence, dtype=np.float32),
                [self.names.get(int(c), str(c)) if isinstance(self.names, dict) else self.names[int(c)] for c in det.class_id])


class YOLO26(Detector):
    def __init__(self, device, size):
        from ultralytics import YOLO
        WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        path = WEIGHTS_DIR / f"yolo26{size}.pt"
        cwd = os.getcwd()
        os.chdir(WEIGHTS_DIR)                       # ultralytics downloads into the working directory
        try:
            self.m = YOLO(str(path) if path.exists() else f"yolo26{size}.pt")
        finally:
            os.chdir(cwd)
        self.device = 0 if device == "cuda" else "cpu"
        self.name, self.input_desc = f"yolo26{size}", "640 (letterbox, package default)"

    def predict(self, bgr):
        r = self.m.predict(bgr, imgsz=640, conf=0.001, max_det=300, device=self.device, verbose=False, half=False)[0]
        b = r.boxes
        return (b.xyxy.float().cpu().numpy(), b.conf.float().cpu().numpy(), [r.names[int(c)] for c in b.cls.cpu().tolist()])


def make(model, device):
    if model == "ssdlite":
        return SSDLite(device)
    if model.startswith("rfdetr-"):
        return RFDETR(device, model.split("-", 1)[1])
    if model.startswith("yolo26"):
        return YOLO26(device, model[len("yolo26"):])
    raise ValueError(model)


# ----------------------------------------------------------------------------- helpers
def sync(device):
    if device == "cuda":
        torch.cuda.synchronize()


def nvidia_used_mib():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return None


def read_labels(path, w, h):
    out = []
    if path.exists():
        for line in path.read_text().split("\n"):
            p = line.split()
            if len(p) >= 5 and int(float(p[0])) == 0:              # class 0 = person
                cx, cy, bw, bh = map(float, p[1:5])
                out.append([(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h])
    return np.array(out, dtype=np.float32).reshape(-1, 4)


def evaluate_quality(det, limit=None):
    imgs = sorted(p for p in VAL_IMAGES.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))[:limit]
    stats, n_gt = [], 0
    p40 = {"tp": 0, "fp": 0}
    for p in imgs:
        im = cv2.imread(str(p))
        h, w = im.shape[:2]
        gt = read_labels(VAL_LABELS / (p.stem + ".txt"), w, h)
        n_gt += len(gt)
        boxes, scores, names = det.predict(im)
        keep = np.array([n == COCO_PERSON_NAME for n in names], dtype=bool)
        boxes, scores = boxes[keep], scores[keep]
        detections = torch.from_numpy(np.concatenate([boxes, scores[:, None], np.zeros((len(scores), 1))], 1)
                                      if len(scores) else np.zeros((0, 6), np.float32)).float()
        labels = torch.from_numpy(np.concatenate([np.zeros((len(gt), 1)), gt], 1) if len(gt) else np.zeros((0, 5))).float()
        iouv = torch.linspace(0.5, 0.95, 10)
        if len(detections):
            correct = process_batch(detections, labels, iouv) if len(labels) else torch.zeros(len(detections), 10, dtype=torch.bool)
        else:
            correct = torch.zeros(0, 10, dtype=torch.bool)
        stats.append((correct.cpu(), detections[:, 4].cpu(), detections[:, 5].cpu(), labels[:, 0].cpu()))
        # precision/recall at the production threshold 0.40, IoU 0.5
        m40 = detections[:, 4] >= PROD_THRESHOLD
        p40["tp"] += int(correct[m40, 0].sum()) if len(detections) else 0
        p40["fp"] += int((~correct[m40, 0]).sum()) if len(detections) else 0
    st = [torch.cat(x, 0).numpy() for x in zip(*stats)]
    m = ap_per_class(*st)                                   # dict (woad.metrics), classes = [0] (person)
    ap = np.asarray(m["ap"])
    ap50 = float(ap[0, 0]) if len(ap) else 0.0
    ap5095 = float(ap[0].mean()) if len(ap) else 0.0
    prec40 = p40["tp"] / max(1, p40["tp"] + p40["fp"])
    rec40 = p40["tp"] / max(1, n_gt)
    return {"images": len(imgs), "people": n_gt, "person_AP50": round(ap50, 4), "person_AP50_95": round(ap5095, 4),
            "precision_at_0.40": round(prec40, 4), "recall_at_0.40": round(rec40, 4)}


def evaluate_speed(det, device, frames, warmup=10):
    import psutil
    seq = sorted(SEQ.glob("*.png"))[:frames + warmup]
    ims = [cv2.imread(str(p)) for p in seq]
    for im in ims[:warmup]:
        det.predict(im)
    sync(device)
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    proc = psutil.Process()
    proc.cpu_percent(None)
    gpu_used = []
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            v = nvidia_used_mib()
            if v is not None:
                gpu_used.append(v)
            stop.wait(0.5)
    sampler = threading.Thread(target=sample, daemon=True)
    if device == "cuda":
        sampler.start()
    lat = []
    t_all = time.perf_counter()
    for im in ims[warmup:]:
        t = time.perf_counter()
        det.predict(im)
        sync(device)
        lat.append((time.perf_counter() - t) * 1000)
    wall = time.perf_counter() - t_all
    cpu = proc.cpu_percent(None)
    stop.set()
    lat_sorted = sorted(lat)
    res = {"frames": len(lat), "frame_size": f"{ims[0].shape[1]}x{ims[0].shape[0]}",
           "latency_ms_mean": round(statistics.mean(lat), 1), "latency_ms_median": round(statistics.median(lat), 1),
           "latency_ms_p90": round(lat_sorted[int(0.9 * (len(lat) - 1))], 1),
           "fps": round(len(lat) / wall, 1),
           "cpu_percent_of_one_core": round(cpu, 0), "cpu_percent_of_all_cores": round(cpu / psutil.cpu_count(), 1)}
    if device == "cuda":
        res["gpu_peak_allocated_mib"] = round(torch.cuda.max_memory_allocated() / 2 ** 20, 0)
        res["gpu_peak_reserved_mib"] = round(torch.cuda.max_memory_reserved() / 2 ** 20, 0)
        res["nvidia_smi_used_mib_max"] = max(gpu_used) if gpu_used else None
    return res


def street_detections(det):
    im = cv2.imread(str(STREET))
    boxes, scores, names = det.predict(im)
    out = [{"class": n, "confidence": round(float(s), 2), "box": [round(float(v)) for v in b]}
           for b, s, n in zip(boxes, scores, names) if s >= PROD_THRESHOLD]
    return sorted(out, key=lambda d: -d["confidence"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["ssdlite", "rfdetr-nano", "rfdetr-small", "yolo26n", "yolo26s"])
    ap.add_argument("--devices", nargs="+", default=["cpu", "cuda"])
    ap.add_argument("--frames", type=int, default=200, help="timed frames per run (after warm-up)")
    ap.add_argument("--cpu-frames", type=int, default=60, help="timed frames for CPU runs")
    ap.add_argument("--quality-device", default="cuda", help="device used for the (device-independent) quality run")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs" / "benchmarks" / "phase1")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    env = {"python": sys.version.split()[0], "torch": torch.__version__, "cuda_available": torch.cuda.is_available(),
           "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
           "cpu": platform.processor(), "torch_threads": torch.get_num_threads(),
           "nvidia_smi_used_mib_idle": nvidia_used_mib(), "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    results = {"environment": env, "runs": []}
    print(json.dumps(env, indent=1), flush=True)
    for model in a.models:
        for device in a.devices:
            if device == "cuda" and not torch.cuda.is_available():
                continue
            t0 = time.perf_counter()
            det = make(model, device)
            load_s = round(time.perf_counter() - t0, 1)
            run = {"model": model, "name": det.name, "input": det.input_desc, "device": device, "load_s": load_s}
            run["speed"] = evaluate_speed(det, device, a.cpu_frames if device == "cpu" else a.frames)
            if device == a.quality_device or (a.quality_device == "cuda" and not torch.cuda.is_available()):
                run["quality_vocdetiv_val"] = evaluate_quality(det)
                run["street_detections_ge_0.40"] = street_detections(det)
            results["runs"].append(run)
            print(json.dumps(run), flush=True)
            del det
            if device == "cuda":
                torch.cuda.empty_cache()
            (a.out / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print("wrote", a.out / "results.json")


if __name__ == "__main__":
    main()
