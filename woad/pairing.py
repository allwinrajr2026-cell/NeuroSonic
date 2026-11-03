"""Pair IR and depth images by filename.

The original training loader paired them by *exact filename*
(``clouddir + basename(ir_path)``). That is the default here (``match='name'``).
``match='stem'`` additionally allows different extensions (e.g. ir/0001.jpg + depth/0001.png).
"""
from dataclasses import dataclass, field
from pathlib import Path

from .preprocess import IMG_EXTS


class PairingError(ValueError):
    """Raised when IR/depth images cannot be paired."""


@dataclass
class PairingResult:
    pairs: list = field(default_factory=list)          # [(ir_path, depth_path), ...] sorted by name
    ir_without_depth: list = field(default_factory=list)
    depth_without_ir: list = field(default_factory=list)

    @property
    def complete(self):
        return not self.ir_without_depth and not self.depth_without_ir

    def describe_missing(self, limit=10):
        lines = []
        for title, items in (("IR images with no matching depth image", self.ir_without_depth),
                             ("depth images with no matching IR image", self.depth_without_ir)):
            if items:
                shown = ", ".join(p.name for p in items[:limit])
                more = f" ... (+{len(items) - limit} more)" if len(items) > limit else ""
                lines.append(f"  {len(items)} {title}: {shown}{more}")
        return "\n".join(lines)


def _list_images(d):
    return sorted(p for p in Path(d).iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTS)


def _key(p, match):
    return p.name.lower() if match == "name" else p.stem.lower()


def pair_directories(ir_dir, depth_dir, match="name"):
    if match not in ("name", "stem"):
        raise ValueError("match must be 'name' or 'stem'")
    ir_dir, depth_dir = Path(ir_dir), Path(depth_dir)
    for role, d in (("IR", ir_dir), ("depth", depth_dir)):
        if not d.is_dir():
            raise PairingError(f"{role} directory not found: {d}")
    irs, deps = _list_images(ir_dir), _list_images(depth_dir)
    if not irs:
        raise PairingError(f"no images ({', '.join(IMG_EXTS)}) found in IR directory {ir_dir}")
    if not deps:
        raise PairingError(f"no images ({', '.join(IMG_EXTS)}) found in depth directory {depth_dir}")

    def index(files, role):
        idx = {}
        for p in files:
            k = _key(p, match)
            if k in idx:
                raise PairingError(f"ambiguous {role} files for key '{k}': {idx[k].name} and {p.name} "
                                   f"(use --match name, or remove the duplicate)")
            idx[k] = p
        return idx

    ir_idx, dp_idx = index(irs, "IR"), index(deps, "depth")
    res = PairingResult()
    for k in sorted(ir_idx):
        if k in dp_idx:
            res.pairs.append((ir_idx[k], dp_idx[k]))
        else:
            res.ir_without_depth.append(ir_idx[k])
    res.depth_without_ir = [dp_idx[k] for k in sorted(dp_idx) if k not in ir_idx]
    return res


def resolve_source_root(root):
    """A dataset root containing ``ir/`` and ``depth/`` sub-folders (the original LoadImages layout)."""
    root = Path(root)
    ir, dp = root / "ir", root / "depth"
    if not ir.is_dir() or not dp.is_dir():
        raise PairingError(f"--source {root} must contain 'ir/' and 'depth/' sub-folders "
                           f"(found: {', '.join(sorted(p.name for p in root.iterdir() if p.is_dir())) or 'none'})"
                           if root.is_dir() else f"--source directory not found: {root}")
    return ir, dp
