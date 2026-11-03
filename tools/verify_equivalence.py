"""Check that the vendored woad.arch model is numerically identical to the original repository code.

The original model is executed in a separate Python process (its own ``models`` package on
sys.path, bytecode writing disabled, nothing written inside the original repository).
Both runs use the same seeded random IR/depth tensors at 640x640.

Usage:
    python tools/verify_equivalence.py [--original "<path to Cross-Modal obstacle detection>"]
Exit code 0 = identical (max |diff| <= tolerance), 1 = mismatch, 2 = original repo unavailable.
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_ORIGINAL = ROOT.parent / "original" / "Cross-Modal obstacle detection"

ORIGINAL_SNIPPET = r'''
import sys, numpy as np, torch
repo, inp, out = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo)
import os; os.chdir(repo)
from models.yolo import Model  # noqa: F401  original code
ck = torch.load("runs/train/exp72/weights/best.pt", map_location="cpu", weights_only=False)
m = ck["model"].float().eval()
d = np.load(inp)
with torch.inference_mode():
    p = m(torch.from_numpy(d["ir"]), torch.from_numpy(d["depth"]))[0]
np.save(out, p.numpy())
'''


def make_inputs(seed=0, n=2, size=640):
    g = torch.Generator().manual_seed(seed)
    return torch.rand(n, 3, size, size, generator=g), torch.rand(n, 3, size, size, generator=g)


def run(original=DEFAULT_ORIGINAL, atol=1e-4):
    original = Path(original)
    if not (original / "models" / "yolo.py").is_file():
        return 2, f"original repository not found at {original}"
    from woad.model_loader import load_model
    ir, depth = make_inputs()
    model, _ = load_model(device="cpu")
    with torch.inference_mode():
        mine = model(ir, depth)[0].numpy()
    with tempfile.TemporaryDirectory() as td:
        inp, out = Path(td) / "in.npz", Path(td) / "out.npy"
        np.savez(inp, ir=ir.numpy(), depth=depth.numpy())
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONWARNINGS="ignore")
        r = subprocess.run([sys.executable, "-c", ORIGINAL_SNIPPET, str(original), str(inp), str(out)],
                           capture_output=True, text=True, env=env, timeout=600)
        if r.returncode != 0:
            return 1, f"original model failed:\n{r.stderr[-2000:]}"
        ref = np.load(out)
    if ref.shape != mine.shape:
        return 1, f"shape mismatch: original {ref.shape} vs vendored {mine.shape}"
    diff = float(np.abs(ref - mine).max())
    ok = diff <= atol
    return (0 if ok else 1), f"output shape {mine.shape}, max |original - vendored| = {diff:.3e} (tol {atol})"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--original", default=str(DEFAULT_ORIGINAL))
    a = ap.parse_args()
    code, msg = run(a.original)
    print(("IDENTICAL: " if code == 0 else "FAILED: ") + msg)
    sys.exit(code)
