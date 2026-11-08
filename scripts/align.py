#!/usr/bin/env python3
"""Align every scanned page to a reference page using printed-text anchors.

Printed labels are identical on every copy of the form, so an OCR string that
appears (once) on most pages with the same text is almost certainly printed.
Its box corners give point correspondences, and a robust affine fit maps each
page into the reference frame.

Outputs (in <out_dir>):
  anchors.json        anchor texts and their reference-frame boxes
  transforms.json     per-page affine (page -> reference) + fit residuals
  aligned/<page>.png  page warped into the reference frame
  blank.png           pixel-wise median of the aligned pages (handwriting removed)

Usage: python3 scripts/align.py <image_dir> <ocr_json_dir> <out_dir> [--ref 01]
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image


def corners(box):
    b = np.array(box, dtype=float)
    return np.array([b[:, 0].min(), b[:, 1].min(), b[:, 0].max(), b[:, 1].max()])


def fit_affine(src, dst):
    """Least-squares affine: dst ~ A @ [x, y, 1]."""
    X = np.hstack([src, np.ones((len(src), 1))])
    A, *_ = np.linalg.lstsq(X, dst, rcond=None)
    return A.T  # 2x3


def apply(A, pts):
    return pts @ A[:, :2].T + A[:, 2]


def robust_affine(src, dst, iters=500, thresh=6.0, seed=0):
    rng = np.random.default_rng(seed)
    best = None
    n = len(src)
    for _ in range(iters):
        idx = rng.choice(n, 3, replace=False)
        try:
            A = fit_affine(src[idx], dst[idx])
        except np.linalg.LinAlgError:
            continue
        err = np.linalg.norm(apply(A, src) - dst, axis=1)
        inl = err < thresh
        if best is None or inl.sum() > best.sum():
            best = inl
    A = fit_affine(src[best], dst[best])
    err = np.linalg.norm(apply(A, src[best]) - dst[best], axis=1)
    return A, best, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image_dir")
    ap.add_argument("ocr_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--ref", default="01", help="suffix of the reference page")
    ap.add_argument("--min-pages", type=float, default=0.6)
    a = ap.parse_args()

    ocr_files = sorted(Path(a.ocr_dir).glob("*.json"))
    pages = {f.stem: json.loads(f.read_text()) for f in ocr_files}
    ref_key = next(k for k in pages if k.endswith("_" + a.ref))

    # texts that occur exactly once on a page, counted over pages
    per_page = {}
    cnt = Counter()
    for k, d in pages.items():
        c = Counter(it["text"] for it in d["items"])
        uniq = {it["text"]: it for it in d["items"] if c[it["text"]] == 1 and len(it["text"]) >= 2}
        per_page[k] = uniq
        cnt.update(uniq.keys())
    need = a.min_pages * len(pages)
    anchor_texts = [t for t, n in cnt.items() if n >= need and t in per_page[ref_key]]
    ref_boxes = {t: corners(per_page[ref_key][t]["box"]) for t in anchor_texts}

    out = Path(a.out_dir)
    (out / "aligned").mkdir(parents=True, exist_ok=True)
    (out / "anchors.json").write_text(json.dumps(
        {t: ref_boxes[t].round(1).tolist() for t in sorted(anchor_texts, key=lambda t: ref_boxes[t][1])},
        ensure_ascii=False, indent=1))

    ref_img = Image.open(Path(a.image_dir) / pages[ref_key]["image"]).convert("L")
    W, H = ref_img.size
    transforms = {}
    stack = []
    for k, d in pages.items():
        src, dst = [], []
        for t in anchor_texts:
            if t in per_page[k]:
                s, r = corners(per_page[k][t]["box"]), ref_boxes[t]
                # left-top and left-bottom corners are most stable; right edge varies with glyph width
                src += [[s[0], s[1]], [s[0], s[3]], [s[2], s[1]], [s[2], s[3]]]
                dst += [[r[0], r[1]], [r[0], r[3]], [r[2], r[1]], [r[2], r[3]]]
        src, dst = np.array(src), np.array(dst)
        A, inl, err = robust_affine(src, dst)
        transforms[k] = {
            "image": d["image"],
            "affine": A.round(6).tolist(),  # page -> reference
            "anchors": int(len(src) // 4),
            "inliers": int(inl.sum()), "points": int(len(src)),
            "rmse_px": round(float(np.sqrt((err ** 2).mean())), 2),
            "rotation_deg": round(float(np.degrees(np.arctan2(A[1, 0], A[0, 0]))), 3),
            "scale": round(float(np.hypot(A[0, 0], A[1, 0])), 4),
        }
        # PIL wants the inverse map: reference -> page
        M = np.vstack([A, [0, 0, 1]])
        Minv = np.linalg.inv(M)
        img = Image.open(Path(a.image_dir) / d["image"]).convert("L")
        warped = img.transform((W, H), Image.AFFINE, Minv[:2].flatten().tolist(),
                               resample=Image.BILINEAR, fillcolor=255)
        warped.save(out / "aligned" / (d["image"].rsplit(".", 1)[0] + ".png"))
        stack.append(np.asarray(warped))
        print(f"{k[-2:]}: anchors={transforms[k]['anchors']:3d} inliers={transforms[k]['inliers']}/{transforms[k]['points']} "
              f"rmse={transforms[k]['rmse_px']:.2f}px rot={transforms[k]['rotation_deg']:+.2f}° scale={transforms[k]['scale']:.4f}")

    (out / "transforms.json").write_text(json.dumps({"reference": pages[ref_key]["image"], "size": [W, H],
                                                      "pages": transforms}, ensure_ascii=False, indent=1))
    blank = np.median(np.stack(stack), axis=0).astype(np.uint8)
    Image.fromarray(blank).save(out / "blank.png")
    print(f"anchors: {len(anchor_texts)}  -> {out}/blank.png")


if __name__ == "__main__":
    main()
