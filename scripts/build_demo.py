#!/usr/bin/env python3
"""Bundle the three frontends + a subset of the data into ONE self-contained HTML file for public demos.

Usage:
  python3 scripts/build_demo.py output/demo.html [--pages 10] [--levels 4]

Each page runs in its own <iframe srcdoc>, with its data embedded inline. A small prelude script
redirects fetch() and <img src> for the original relative paths to the embedded data, so the page
sources are used unchanged (apart from the editor's "only when served over http" check).
"""
import argparse
import base64
import io
import json
import re
from html import escape
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SCANS = ROOT / "模擬醫療記錄單30份_手寫掃描檔"
ALIGNED = ROOT / "work/aligned"
EXTRACT = ROOT / "work/extract"
TEMPLATE = ROOT / "templates/medical_record_1_2.json"
BLANK = ROOT / "templates/medical_record_1_2.blank.png"
OCR_RAW = ROOT / "ocr_raw/v6-medium"

PRELUDE = r"""<script>
(function(){
  const VFS = __VFS__;
  const key = u => { try { u = decodeURIComponent(String(u)); } catch(e) {}
    return u.replace(/^[a-z]+:\/\/[^/]*\//i,'').replace(/^(\.\.?\/)+/,'').replace(/^\/+/,''); };
  const hit = u => VFS[key(u)];
  const _fetch = window.fetch;
  window.fetch = function(u, o){
    const v = hit(u);
    if(v === undefined) return _fetch ? _fetch.apply(this, arguments) : Promise.reject(new Error('not found'));
    return Promise.resolve(new Response(typeof v === 'string' ? v : JSON.stringify(v), {headers:{'Content-Type':'application/json'}}));
  };
  const d = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
  Object.defineProperty(HTMLImageElement.prototype, 'src', {configurable:true, get(){ return d.get.call(this); },
    set(v){ const h = hit(v); d.set.call(this, typeof h === 'string' && h.startsWith('data:') ? h : v); }});
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {
    if(n.nodeType !== 1) return;
    (n.tagName === 'IMG' ? [n] : n.querySelectorAll('img')).forEach(img => {
      const s = img.getAttribute('src'); const h = s && hit(s);
      if(typeof h === 'string' && h.startsWith('data:')) img.setAttribute('src', h);
    });
  }))).observe(document.documentElement, {childList:true, subtree:true});
  // sandboxed hosts may block localStorage: fall back to memory so the pages still work
  try { localStorage.setItem('__t','1'); localStorage.removeItem('__t'); }
  catch(e) { const m = {}; Object.defineProperty(window, 'localStorage', {value:{
    getItem:k => k in m ? m[k] : null, setItem:(k,v) => { m[k] = String(v); }, removeItem:k => { delete m[k]; }, clear:() => {}}}); }
})();
</script>"""


def img_data(path, levels):
    """Scans are black ink on white paper: a 4-level grayscale PNG keeps strokes crisp at a fraction
    of the JPEG size (scan noise makes JPEG large). Pixel size is unchanged — the pages use pixel coords."""
    im = Image.open(path).convert("L")
    step = 256 / levels
    lut = [min(255, round(int(v / step) * 255 / (levels - 1))) for v in range(256)]
    im = im.point(lut).quantize(levels)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def with_prelude(html, vfs):
    pre = PRELUDE.replace("__VFS__", json.dumps(vfs, ensure_ascii=False).replace("</", "<\\/"))
    # must run before the page's own scripts
    return re.sub(r"(<meta charset=[^>]*>)", lambda m: m.group(1) + pre, html, count=1) if "<meta charset" in html \
        else pre + html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--levels", type=int, default=4, help="gray levels kept in embedded images")
    a = ap.parse_args()
    q = a.levels

    tpl = json.loads(TEMPLATE.read_text())
    res = json.loads((EXTRACT / "results.json").read_text())
    keys = sorted(res["pages"], key=int)[: a.pages]
    res["pages"] = {k: res["pages"][k] for k in keys}

    # --- review page
    vfs = {"templates/medical_record_1_2.json": tpl, "work/extract/results.json": res}
    for k in keys:
        p = res["pages"][k]
        vfs[f"work/aligned/{p['page']}"] = img_data(ALIGNED / p["page"], q)
        for e in p["fields"].values():
            for c in [e.get("crop")] + [o.get("crop") for o in (e.get("other") or {}).values()]:
                if c and f"work/extract/{c}" not in vfs:
                    vfs[f"work/extract/{c}"] = img_data(EXTRACT / c, q)
    review = with_prelude((ROOT / "review/review.html").read_text(), vfs)

    # --- template editor (bundle the blank form; also offer page 1 as a ready-made sample overlay)
    ed = (ROOT / "editor/template_editor.html").read_text()
    ed = ed.replace("if(location.protocol.startsWith('http')){", "if(true){", 1)
    assert "if(true){" in ed, "editor autoload check not found"
    first = res["pages"][keys[0]]["page"]
    ed = ed.replace("</body>", "") + (
        "<script>window.addEventListener('load',()=>{const s=document.getElementById('sample');"
        f"s.src='work/aligned/{first}';}});</script>")
    editor = with_prelude(ed, {
        "templates/medical_record_1_2.json": tpl,
        "templates/medical_record_1_2.blank.png": img_data(BLANK, q),
        f"work/aligned/{first}": vfs[f"work/aligned/{first}"],
    })

    # --- OCR viewer: rebuild with embedded images
    pages = []
    for j in sorted(OCR_RAW.glob("*.json"))[: a.pages]:
        d = json.loads(j.read_text())
        pages.append({"name": d["image"], "src": img_data(SCANS / d["image"], q), "model": d.get("model"), "items": d["items"]})
    viewer_tpl = (ROOT / "scripts/build_ocr_viewer.py").read_text()
    viewer = re.search(r'html = r"""(.*?)"""', viewer_tpl, re.S).group(1)
    viewer = viewer.replace("__DATA__", json.dumps(pages, ensure_ascii=False).replace("</", "<\\/"))

    intro = (ROOT / "scripts/demo_intro.html").read_text().replace("__N__", str(len(keys)))
    frames = [("intro", "概念說明", intro), ("viewer", "① 整頁 OCR", viewer),
              ("editor", "② 模板編輯器", editor), ("review", "③ 欄位校正", review)]
    tabs = "".join(f'<button data-t="{i}"{" class=on" if i == "intro" else ""}>{escape(t)}</button>' for i, t, _ in frames)
    ifr = "".join(f'<iframe id="f_{i}" srcdoc="{escape(h, quote=True)}"{"" if i == "intro" else " hidden"}></iframe>'
                  for i, _, h in frames)
    out = f"""<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>bulkocr：手寫紙本表單批次整理（概念展示）</title>
<style>
html,body{{margin:0;height:100%;font-family:system-ui,-apple-system,"PingFang TC","Noto Sans TC",sans-serif}}
body{{display:flex;flex-direction:column}}
nav{{display:flex;gap:4px;align-items:center;padding:6px 10px;border-bottom:1px solid #ddd;background:#fafafa;flex-wrap:wrap}}
nav b{{margin-right:12px}}
nav button{{border:1px solid #ccc;background:#fff;border-radius:6px;padding:5px 12px;cursor:pointer;font-size:14px}}
nav button.on{{background:#1f6feb;color:#fff;border-color:#1f6feb}}
nav small{{margin-left:auto;color:#888}}
iframe{{flex:1;border:0;width:100%}}
iframe[hidden]{{display:none}}
</style>
<nav><b>bulkocr</b>{tabs}<small>合成模擬資料 · {len(keys)} 份</small></nav>
{ifr}
<script>
document.querySelectorAll('nav button').forEach(b => b.onclick = () => {{
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('iframe').forEach(f => f.hidden = f.id !== 'f_' + b.dataset.t);
}});
window.addEventListener('message', e => {{ if(e.data && e.data.tab) document.querySelector(`nav button[data-t="${{e.data.tab}}"]`).click(); }});
</script>
"""
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(out)
    print(f"wrote {a.out}: {len(keys)} pages, {len(out.encode())/1e6:.1f} MB")


if __name__ == "__main__":
    main()
