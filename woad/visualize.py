"""Drawing helpers (OpenCV only). Colours follow the original Ultralytics palette used in training plots."""
import cv2
import numpy as np

_HEX = ('FF3838', 'FF9D97', 'FF701F', 'FFB21D', 'CFD231', '48F90A', '92CC17', '3DDB86', '1A9334', '00D4BB')


def color_bgr(cls):
    h = _HEX[int(cls) % len(_HEX)]
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return b, g, r


def draw_detections(img_bgr, detections, line_width=None):
    """Return a copy of ``img_bgr`` with boxes and 'label conf' tags drawn."""
    im = img_bgr.copy()
    lw = line_width or max(round(sum(im.shape[:2]) / 2 * 0.003), 2)
    tf = max(lw - 1, 1)
    for d in detections:
        x1, y1, x2, y2 = (int(round(v)) for v in d["box_xyxy"])
        c = color_bgr(d["class_id"])
        cv2.rectangle(im, (x1, y1), (x2, y2), c, lw, cv2.LINE_AA)
        label = f"{d['class_name']} {d['confidence']:.2f}"
        (tw, th), _ = cv2.getTextSize(label, 0, lw / 3, tf)
        outside = y1 - th - 3 >= 0
        ty2 = y1 - th - 3 if outside else y1 + th + 3
        cv2.rectangle(im, (x1, y1), (x1 + tw, ty2), c, -1, cv2.LINE_AA)
        cv2.putText(im, label, (x1, y1 - 2 if outside else y1 + th + 2), 0, lw / 3, (255, 255, 255), tf, cv2.LINE_AA)
    return im


def side_by_side(ir_annotated, depth_annotated, banner=None):
    """IR | depth panel. The depth panel is resized to the IR height if needed."""
    h = ir_annotated.shape[0]
    d = depth_annotated
    if d.shape[0] != h:
        d = cv2.resize(d, (int(d.shape[1] * h / d.shape[0]), h))
    panel = np.concatenate([ir_annotated, np.full((h, 4, 3), 255, np.uint8), d], axis=1)
    if banner:
        bar = np.zeros((28, panel.shape[1], 3), np.uint8)
        cv2.putText(bar, banner, (6, 20), 0, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        panel = np.concatenate([bar, panel], axis=0)
    return panel
