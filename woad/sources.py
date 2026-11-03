"""Frame sources. A source yields `Frame`s; live sensor sources (Stage 3) will implement the same iterator.

`ReplaySource` replays recorded IR + depth pairs as a deterministic, timed stream:
  * frame timestamps are synthetic (index / fps), so replays are reproducible;
  * `segment_gap`: recorded sets such as detec_test are collections of short clips. When the numeric part
    of consecutive filenames jumps by more than `segment_gap`, the frame starts a new segment and
    consumers (the alert engine) reset their tracking state instead of carrying objects across a cut.
  * unreadable or invalid images are yielded as frames with `error` set (not skipped), so a consumer can
    report the input failure.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from .pairing import PairingError, pair_directories, resolve_source_root
from .preprocess import InputImageError, read_image

_DIGITS = re.compile(r"(\d+)")


@dataclass
class Frame:
    index: int                      # position in the stream (0-based)
    frame_id: str                   # e.g. the IR filename
    timestamp: float                # seconds since stream start
    segment: int                    # clip number (0-based)
    segment_start: bool             # True for the first frame of a segment
    ir: Optional[np.ndarray] = None       # BGR uint8 (grey replicated) or None on error
    depth: Optional[np.ndarray] = None    # BGR uint8 colour-mapped depth or None on error
    error: Optional[str] = None
    meta: dict = field(default_factory=dict)


def _number(name):
    m = _DIGITS.findall(Path(name).stem)
    return int(m[-1]) if m else None


class ReplaySource:
    def __init__(self, ir_dir, depth_dir, fps=5.0, match="name", segment_gap=None, start=0, limit=None):
        if fps <= 0:
            raise ValueError("fps must be > 0")
        pairing = pair_directories(ir_dir, depth_dir, match=match)
        if not pairing.complete:
            raise PairingError("unpaired files in replay source:\n" + pairing.describe_missing())
        pairs = sorted(pairing.pairs, key=lambda p: (_number(p[0].name) is None, _number(p[0].name) or 0, p[0].name))
        self.pairs = pairs[start:None if limit is None else start + limit]
        self.fps, self.segment_gap = float(fps), segment_gap
        self.ir_dir, self.depth_dir = Path(ir_dir), Path(depth_dir)

    @classmethod
    def from_root(cls, root, **kw):
        ir, dp = resolve_source_root(root)
        return cls(ir, dp, **kw)

    def __len__(self):
        return len(self.pairs)

    def describe(self):
        return {"type": "replay", "ir_dir": str(self.ir_dir), "depth_dir": str(self.depth_dir), "frames": len(self),
                "fps": self.fps, "segment_gap": self.segment_gap, "timestamps": "synthetic (index / fps)"}

    def __iter__(self):
        segment, prev = -1, None
        for i, (ir_p, dp_p) in enumerate(self.pairs):
            n = _number(ir_p.name)
            if i == 0:
                new_segment = True
            elif self.segment_gap is None:
                new_segment = False
            else:
                new_segment = n is None or prev is None or n - prev > self.segment_gap
            if new_segment:
                segment += 1
            prev = n
            frame = Frame(index=i, frame_id=ir_p.name, timestamp=i / self.fps, segment=segment,
                          segment_start=new_segment,
                          meta={"ir_path": str(ir_p), "depth_path": str(dp_p)})
            try:
                frame.ir = read_image(ir_p, "IR")
                frame.depth = read_image(dp_p, "depth")
            except InputImageError as e:
                frame.ir = frame.depth = None
                frame.error = str(e)
            yield frame
