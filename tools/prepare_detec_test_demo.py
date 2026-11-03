"""Copy the published `detec_test` sequence into demo_data/detec_test/{ir,depth}/ with a manifest.

Source: Google Drive file 1ClceTKmjz5Pp1PGdnf4nGyDi3XjBy6In (`detec_test.rar`, linked from
original/.../data/readme.md), extracted to ../datasets/detec_test/. Its `pointcloud/` folder holds the
colour-mapped depth images and becomes `depth/` here (the folder name the CLI's --source mode expects).

Files are copied, never moved; the source is not modified; an existing destination is refused.

  python tools/prepare_detec_test_demo.py --src ../datasets/detec_test/detec_test ^
      --archive ../datasets/download/detec_test.rar
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from woad.pairing import pair_directories  # noqa: E402
from woad.preprocess import read_image  # noqa: E402

DRIVE_ID = "1ClceTKmjz5Pp1PGdnf4nGyDi3XjBy6In"
ARCHIVE_SHA256 = "53cd2d29f90f72e011ede422e22fb1bcdb5a83b6c8f618e76eeea15b022febfd"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, required=True, help="extracted detec_test folder (contains ir/ and pointcloud/)")
    ap.add_argument("--archive", type=Path, help="detec_test.rar, to verify its SHA-256 (optional)")
    ap.add_argument("--dst", type=Path, default=ROOT / "demo_data" / "detec_test")
    a = ap.parse_args(argv)

    if a.dst.exists():
        sys.exit(f"refusing to overwrite existing {a.dst}")
    archive_ok = None
    if a.archive:
        archive_ok = sha256(a.archive) == ARCHIVE_SHA256
        if not archive_ok:
            sys.exit(f"archive SHA-256 mismatch for {a.archive}")
    pairing = pair_directories(a.src / "ir", a.src / "pointcloud", match="name")
    if not pairing.complete:
        sys.exit("source is not fully paired:\n" + pairing.describe_missing())
    for ir, dp in pairing.pairs:  # same validation as inference
        read_image(ir, "IR")
        read_image(dp, "depth")

    (a.dst / "ir").mkdir(parents=True)
    (a.dst / "depth").mkdir()
    files = []
    for ir, dp in pairing.pairs:
        shutil.copy2(ir, a.dst / "ir" / ir.name)
        shutil.copy2(dp, a.dst / "depth" / ir.name)
        files.append({"name": ir.name, "ir_sha256": sha256(a.dst / "ir" / ir.name),
                      "depth_sha256": sha256(a.dst / "depth" / ir.name)})
        if files[-1]["ir_sha256"] != sha256(ir) or files[-1]["depth_sha256"] != sha256(dp):
            sys.exit(f"copy verification failed for {ir.name}")
    manifest = {
        "source": {"google_drive_id": DRIVE_ID, "archive": "detec_test.rar", "archive_sha256": ARCHIVE_SHA256,
                   "archive_verified_here": archive_ok, "mapping": "ir/ -> ir/, pointcloud/ -> depth/"},
        "pairs": len(files), "files": files,
    }
    (a.dst / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"copied {len(files)} pairs to {a.dst}")


if __name__ == "__main__":
    main()
