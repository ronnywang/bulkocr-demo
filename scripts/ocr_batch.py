#!/usr/bin/env python3
"""Batch-run OCR over scanned form images and cache raw results as JSON.

Endpoint and credentials come from the environment (nothing hardcoded):
  PADDLEOCR_API_URL   OCR endpoint base URL (required)
  PADDLEOCR_API_KEY   API key (sent as X-Api-Key); otherwise the Bearer token
                      in ~/.config/bulkocr/token.json is used.

Usage:
  python3 scripts/ocr_batch.py <image_dir> [--model v6-medium] [--out ocr_raw] [--workers 2]
"""
import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def auth_headers():
    key = os.environ.get("PADDLEOCR_API_KEY")
    if key:
        return {"X-Api-Key": key}
    p = Path.home() / ".config/bulkocr/token.json"
    if p.exists():
        return {"Authorization": "Bearer " + json.loads(p.read_text())["access_token"]}
    sys.exit("No credentials: set PADDLEOCR_API_KEY or create ~/.config/bulkocr/token.json")


def multipart(fields, file_path):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n".encode()
    )
    parts.append(file_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def ocr_one(url, headers, img, model, retries=8):
    body, ctype = multipart({"model": model}, img)
    delay = 5
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={**headers, "Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r), r.headers.get("X-OCR-Model"), r.headers.get("X-OCR-Elapsed-Ms")
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and attempt < retries - 1:
                print(f"  {img.name}: HTTP {e.code}, retry in {delay}s", flush=True)
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                print(f"  {img.name}: {e}, retry in {delay}s", flush=True)
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image_dir")
    ap.add_argument("--model", default="v6-medium")
    ap.add_argument("--out", default="ocr_raw")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--force", action="store_true", help="re-run even if output exists")
    a = ap.parse_args()

    base = os.environ.get("PADDLEOCR_API_URL")
    if not base:
        sys.exit("Set PADDLEOCR_API_URL")
    url = base.rstrip("/") + "/"
    headers = auth_headers()

    imgs = sorted(p for p in Path(a.image_dir).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    out_dir = Path(a.out) / a.model
    out_dir.mkdir(parents=True, exist_ok=True)

    def job(img):
        out = out_dir / (img.stem + ".json")
        if out.exists() and not a.force:
            return img.name, "cached"
        t0 = time.time()
        items, used_model, ms = ocr_one(url, headers, img, a.model)
        out.write_text(json.dumps({
            "image": img.name, "model": used_model, "elapsed_ms": ms, "items": items,
        }, ensure_ascii=False, indent=1))
        return img.name, f"{len(items)} boxes, server {ms}ms, wall {time.time()-t0:.1f}s"

    with ThreadPoolExecutor(a.workers) as ex:
        for name, msg in ex.map(job, imgs):
            print(f"{name}: {msg}", flush=True)


if __name__ == "__main__":
    main()
