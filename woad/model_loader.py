"""Safe, verified loading of the WOAD exp72 cross-modal checkpoint.

The checkpoint is a full pickled ``nn.Module`` whose classes live at
``models.yolo.*`` / ``models.common.*`` (the original repository layout).
Instead of putting the original repository on ``sys.path``, we temporarily
alias those module names to the vendored ``woad.arch`` package while
unpickling, then restore ``sys.modules`` exactly as it was.
"""
import contextlib
import hashlib
import sys
import types
from pathlib import Path

import torch

from .arch import common as arch_common
from .arch import yolo as arch_yolo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEIGHTS = ROOT / "weights" / "best.pt"

# SHA-256 of original/Cross-Modal obstacle detection/runs/train/exp72/weights/best.pt
EXP72_BEST_SHA256 = "da043ff2e1edd393fcd329dddbac58676f1305c14f2eb084f928439d7950f8aa"
EXPECTED_NAMES = ["person", "Ebike", "Car"]
EXPECTED_CHILDREN = {"trans_blocks", "fusion_conv1", "fusion_activation", "fusion_conv2", "conv4", "conv3",
                     "bn3", "relu", "avp", "drop", "norm", "model", "model1"}


class CheckpointError(RuntimeError):
    """Raised when a checkpoint is missing, corrupted or not the expected architecture."""


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


@contextlib.contextmanager
def _legacy_module_aliases():
    """Map models / models.yolo / models.common to woad.arch for the duration of unpickling."""
    names = ("models", "models.yolo", "models.common")
    saved = {n: sys.modules.get(n) for n in names}
    pkg = types.ModuleType("models")
    pkg.__path__ = []  # mark as package
    pkg.yolo, pkg.common = arch_yolo, arch_common
    sys.modules.update({"models": pkg, "models.yolo": arch_yolo, "models.common": arch_common})
    try:
        yield
    finally:
        for n, mod in saved.items():
            if mod is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = mod


def select_device(device="auto"):
    if device in (None, "", "auto"):
        return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    if str(device).isdigit():
        device = f"cuda:{device}"
    dev = torch.device(device)
    if dev.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(f"Device '{device}' requested but CUDA is not available in this PyTorch build "
                           f"({torch.__version__}). Use --device cpu.")
    return dev


def load_model(weights=DEFAULT_WEIGHTS, device="cpu", verify_hash=True):
    """Load the cross-modal model in eval/FP32 mode.

    Args:
        weights: path to the checkpoint (defaults to implementation/weights/best.pt).
        device: 'cpu', 'cuda', 'cuda:0', '0' or 'auto'.
        verify_hash: if True and ``weights`` is the default checkpoint, require the exp72 SHA-256.

    Returns:
        (model, info) where info is a dict of checkpoint metadata.
    """
    weights = Path(weights)
    if not weights.is_file():
        raise CheckpointError(f"Checkpoint not found: {weights}")
    digest = sha256(weights)
    if verify_hash and weights.resolve() == DEFAULT_WEIGHTS.resolve() and digest != EXP72_BEST_SHA256:
        raise CheckpointError(f"Checkpoint {weights} has SHA-256 {digest}, expected exp72 best.pt "
                              f"{EXP72_BEST_SHA256}. The file was modified or replaced.")

    with _legacy_module_aliases():
        try:
            # weights_only=False is required: the checkpoint pickles a full nn.Module (YOLOv5 format).
            # Only load checkpoints you trust.
            ckpt = torch.load(weights, map_location="cpu", weights_only=False)
        except Exception as e:  # noqa: BLE001
            raise CheckpointError(f"Failed to unpickle {weights}: {type(e).__name__}: {e}") from e

    model = ckpt.get("ema") or ckpt.get("model")
    if model is None:
        raise CheckpointError(f"{weights} contains neither 'ema' nor 'model'")
    if not isinstance(model, arch_yolo.Model):
        raise CheckpointError(f"{weights} holds {type(model).__module__}.{type(model).__name__}, "
                              f"not the cross-modal Model")
    missing = EXPECTED_CHILDREN - set(model._modules)
    extra = set(model._modules) - EXPECTED_CHILDREN
    if missing or extra:
        raise CheckpointError(f"{weights} is a different cross-modal variant (missing={sorted(missing)}, "
                              f"unexpected={sorted(extra)}). Only the exp72 architecture is supported. "
                              f"Note: the repository-root best.pt is an incompatible 5-class variant.")

    model = model.float().eval().to(select_device(device))
    for p in model.parameters():
        p.requires_grad_(False)
    detect = model.model[-1]
    info = {
        "weights": str(weights),
        "sha256": digest,
        "date": ckpt.get("date"),
        "names": list(model.names),
        "nc": int(detect.nc),
        "stride": [int(s) for s in detect.stride.tolist()],
        "num_params": int(sum(p.numel() for p in model.parameters())),
        "device": str(next(model.parameters()).device),
    }
    return model, info
