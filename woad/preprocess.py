"""Input loading and preprocessing that reproduces the original training/validation pipeline.

Reference: ``utils/datasets.py`` -> ``LoadImagesAndLabels.load_image`` / ``__getitem__``
(augment=False, i.e. the validation path) in the original repository:

IR image (the "RGB" stream; the sensor's near-infrared frame)
    1. cv2.imread (BGR, 3 channels)
    2. r = 640 / max(h0, w0); if r != 1 resize to (w0*r, h0*r)
       with INTER_AREA when shrinking, INTER_LINEAR when enlarging
    3. letterbox(img, 640, auto=False, scaleup=False)  -> 640x640, pad value 114
Depth image (the "cloud" stream; a colour-mapped depth PNG)
    1. cv2.imread (BGR, 3 channels)
    2. cv2.medianBlur(depth, 3)
    3. letterbox(depth, 640, auto=False)                -> 640x640, pad value 114
Both
    4. HWC -> CHW, BGR -> RGB (``transpose((2, 0, 1))[::-1]``)
    5. float32 / 255  -> [0, 1]
"""
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch

from .ops import letterbox

IMG_SIZE = 640  # fixed: the depth stream was letterboxed to a hard-coded 640 during training
IMG_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


class InputImageError(ValueError):
    """Raised for unreadable or unsupported input images."""


def read_image(path, role):
    """Read an 8-bit 3-channel image with OpenCV (BGR). ``role`` is 'IR' or 'depth' (for messages)."""
    path = Path(path)
    if not path.is_file():
        raise InputImageError(f"{role} image not found: {path}")
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise InputImageError(f"{role} image could not be decoded by OpenCV: {path}")
    if raw.dtype != np.uint8:
        hint = (" The model expects the colour-mapped (8-bit, 3-channel) depth PNG, not raw 16-bit depth."
                if role == "depth" else "")
        raise InputImageError(f"{role} image {path} has dtype {raw.dtype}; only 8-bit images are supported.{hint}")
    if role == "depth" and raw.ndim == 2:
        raise InputImageError(f"depth image {path} is single-channel. The model was trained on colour-mapped "
                              f"(3-channel) depth images; a grayscale depth map is out of distribution.")
    # IR frames may legitimately be single-channel; the original loader (cv2.imread default) expands to 3 channels.
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    return img


def _to_tensor(img_bgr):
    x = img_bgr.transpose((2, 0, 1))[::-1]  # HWC to CHW, BGR to RGB
    x = np.ascontiguousarray(x)
    return torch.from_numpy(x).float() / 255.0


def preprocess_ir(ir_bgr, img_size=IMG_SIZE):
    h0, w0 = ir_bgr.shape[:2]
    r = img_size / max(h0, w0)
    im = ir_bgr
    if r != 1:
        im = cv2.resize(im, (int(w0 * r), int(h0 * r)), interpolation=cv2.INTER_LINEAR if r > 1 else cv2.INTER_AREA)
    im, _, _ = letterbox(im, img_size, auto=False, scaleup=False)
    return im


def preprocess_depth(depth_bgr, img_size=IMG_SIZE):
    d = cv2.medianBlur(depth_bgr, 3)
    d, _, _ = letterbox(d, img_size, auto=False)
    return d


@dataclass
class PreparedPair:
    ir: torch.Tensor          # (1,3,640,640) float32 RGB [0,1]
    depth: torch.Tensor       # (1,3,640,640) float32 RGB [0,1]
    ir_original: np.ndarray   # original IR image (BGR) used for box mapping / drawing
    depth_original: np.ndarray
    size_mismatch: bool       # IR and depth have different original resolutions


def prepare_pair(ir_bgr, depth_bgr, img_size=IMG_SIZE):
    if img_size != IMG_SIZE:
        raise ValueError(f"img_size must be {IMG_SIZE}: the depth stream was trained with a fixed 640 letterbox")
    for name, a in (("IR", ir_bgr), ("depth", depth_bgr)):
        if not isinstance(a, np.ndarray) or a.ndim != 3 or a.shape[2] != 3 or a.dtype != np.uint8:
            raise InputImageError(f"{name} array must be uint8 HxWx3 BGR, got "
                                  f"{getattr(a, 'dtype', type(a))} {getattr(a, 'shape', '')}")
    ir = _to_tensor(preprocess_ir(ir_bgr, img_size))[None]
    dp = _to_tensor(preprocess_depth(depth_bgr, img_size))[None]
    return PreparedPair(ir, dp, ir_bgr, depth_bgr, ir_bgr.shape[:2] != depth_bgr.shape[:2])


def load_pair(ir_path, depth_path, img_size=IMG_SIZE):
    return prepare_pair(read_image(ir_path, "IR"), read_image(depth_path, "depth"), img_size)
