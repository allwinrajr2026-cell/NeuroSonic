"""Detection metrics, vendored from the original repository so results are comparable.

* ``process_batch``  - verbatim from ``original/.../val.py``.
* ``ap_per_class``, ``compute_ap`` - from ``original/.../utils/metrics.py`` with plotting removed and
  ``np.trapz`` -> ``np.trapezoid`` (``np.trapz`` no longer exists in NumPy 2.5; identical maths).
* ``ConfusionMatrix`` - logic from ``original/.../utils/metrics.py`` (plotting removed).
"""
import numpy as np
import torch

from woad.ops import box_iou

IOUV = torch.linspace(0.5, 0.95, 10)  # IoU thresholds for mAP@0.5:0.95 (as in val.py)


def process_batch(detections, labels, iouv=IOUV):
    """Correct-prediction matrix [N, 10]. detections: [N, 6] x1y1x2y2,conf,cls; labels: [M, 5] cls,x1y1x2y2."""
    correct = torch.zeros(detections.shape[0], iouv.shape[0], dtype=torch.bool, device=iouv.device)
    iou = box_iou(labels[:, 1:], detections[:, :4])
    x = torch.where((iou >= iouv[0]) & (labels[:, 0:1] == detections[:, 5]))
    if x[0].shape[0]:
        matches = torch.cat((torch.stack(x, 1), iou[x[0], x[1]][:, None]), 1).cpu().numpy()  # [label, det, iou]
        if x[0].shape[0] > 1:
            matches = matches[matches[:, 2].argsort()[::-1]]
            matches = matches[np.unique(matches[:, 1], return_index=True)[1]]
            matches = matches[np.unique(matches[:, 0], return_index=True)[1]]
        matches = torch.from_numpy(matches).to(iouv.device)
        correct[matches[:, 1].long()] = matches[:, 2:3] >= iouv
    return correct


def compute_ap(recall, precision):
    mrec = np.concatenate(([0.0], recall, [1.0]))
    mpre = np.concatenate(([1.0], precision, [0.0]))
    mpre = np.flip(np.maximum.accumulate(np.flip(mpre)))
    x = np.linspace(0, 1, 101)  # 101-point interpolation (COCO), as in the original
    ap = np.trapezoid(np.interp(x, mrec, mpre), x)
    return ap, mpre, mrec


def ap_per_class(tp, conf, pred_cls, target_cls, eps=1e-16):
    """Returns tp, fp, p, r, f1, ap[nc, 10], unique_classes, plus PR curves (px, p_curve, r_curve, pr_curves)."""
    i = np.argsort(-conf)
    tp, conf, pred_cls = tp[i], conf[i], pred_cls[i]
    unique_classes, nt = np.unique(target_cls, return_counts=True)
    nc = unique_classes.shape[0]
    px, py = np.linspace(0, 1, 1000), []
    ap, p, r = np.zeros((nc, tp.shape[1])), np.zeros((nc, 1000)), np.zeros((nc, 1000))
    for ci, c in enumerate(unique_classes):
        i = pred_cls == c
        n_l = nt[ci]
        n_p = i.sum()
        if n_p == 0 or n_l == 0:
            py.append(np.zeros(1000))
            continue
        fpc = (1 - tp[i]).cumsum(0)
        tpc = tp[i].cumsum(0)
        recall = tpc / (n_l + eps)
        r[ci] = np.interp(-px, -conf[i], recall[:, 0], left=0)
        precision = tpc / (tpc + fpc)
        p[ci] = np.interp(-px, -conf[i], precision[:, 0], left=1)
        for j in range(tp.shape[1]):
            ap[ci, j], mpre, mrec = compute_ap(recall[:, j], precision[:, j])
            if j == 0:
                py.append(np.interp(px, mrec, mpre))
    f1 = 2 * p * r / (p + r + eps)
    i = f1.mean(0).argmax()  # max mean-F1 confidence index (as in the original)
    p_at, r_at, f1_at = p[:, i], r[:, i], f1[:, i]
    tp_n = (r_at * nt).round()
    fp_n = (tp_n / (p_at + eps) - tp_n).round()
    return dict(tp=tp_n, fp=fp_n, p=p_at, r=r_at, f1=f1_at, ap=ap, classes=unique_classes.astype("int32"),
                nt=nt, best_conf=float(px[i]), px=px, pr_curves=np.array(py) if py else np.zeros((0, 1000)))


class ConfusionMatrix:
    """Rows = predicted class (last = background), columns = true class (last = background)."""

    def __init__(self, nc, conf=0.25, iou_thres=0.45):
        self.matrix = np.zeros((nc + 1, nc + 1))
        self.nc, self.conf, self.iou_thres = nc, conf, iou_thres

    def process_batch(self, detections, labels):
        detections = detections[detections[:, 4] > self.conf]
        gt_classes = labels[:, 0].int()
        detection_classes = detections[:, 5].int()
        iou = box_iou(labels[:, 1:], detections[:, :4])
        x = torch.where(iou > self.iou_thres)
        if x[0].shape[0]:
            matches = torch.cat((torch.stack(x, 1), iou[x[0], x[1]][:, None]), 1).cpu().numpy()
            if x[0].shape[0] > 1:
                matches = matches[matches[:, 2].argsort()[::-1]]
                matches = matches[np.unique(matches[:, 1], return_index=True)[1]]
                matches = matches[matches[:, 2].argsort()[::-1]]
                matches = matches[np.unique(matches[:, 0], return_index=True)[1]]
        else:
            matches = np.zeros((0, 3))
        n = matches.shape[0] > 0
        m0, m1, _ = matches.transpose().astype(int)
        for i, gc in enumerate(gt_classes):
            j = m0 == i
            if n and sum(j) == 1:
                self.matrix[detection_classes[m1[j]], gc] += 1
            else:
                self.matrix[self.nc, gc] += 1  # missed ground truth (predicted "background")
        # Original quirk kept for comparability: unmatched detections are only counted when the image has
        # at least one match, so false positives on images with no match are not counted here.
        if n:
            for i, dc in enumerate(detection_classes):
                if not any(m1 == i):
                    self.matrix[dc, self.nc] += 1  # detection with no matching ground truth
