#!/usr/bin/env python3
"""Build a self-contained HTML viewer that overlays OCR boxes on the scans.

Usage: python3 scripts/build_ocr_viewer.py <image_dir> <ocr_json_dir> <out.html>
Images are referenced by relative path, so open the HTML from the project root.
"""
import json
import os
import sys
from pathlib import Path

img_dir, ocr_dir, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
pages = []
for j in sorted(ocr_dir.glob("*.json")):
    d = json.loads(j.read_text())
    img = img_dir / d["image"]
    pages.append({
        "name": d["image"],
        "src": os.path.relpath(img, out.parent),
        "model": d.get("model"),
        "items": d["items"],
    })

html = r"""<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<title>OCR viewer</title>
<style>
body{margin:0;font-family:system-ui,sans-serif;display:flex;height:100vh}
#side{width:340px;overflow:auto;border-right:1px solid #ccc;padding:8px;box-sizing:border-box;font-size:13px}
#main{flex:1;overflow:auto;position:relative}
#wrap{position:relative;display:inline-block}
#wrap img{display:block}
.box{position:absolute;border:2px solid;box-sizing:border-box;cursor:pointer}
.box:hover,.box.sel{background:rgba(255,255,0,.35)}
.lab{position:absolute;font-size:12px;background:rgba(255,255,255,.85);white-space:nowrap;pointer-events:none;padding:0 2px}
.row{padding:2px 4px;cursor:pointer;border-bottom:1px solid #eee}
.row:hover,.row.sel{background:#ffd}
.lo{color:#c00}
#ctl{position:sticky;top:0;background:#fff;padding-bottom:6px}
</style>
<div id="side"><div id="ctl">
<select id="pg"></select>
<label>縮放 <input id="zm" type="range" min="0.3" max="1.5" step="0.05" value="0.7"></label><br>
<label><input id="showlab" type="checkbox" checked>顯示文字</label>
<label>信心 &lt; <input id="th" type="number" value="0.8" step="0.05" style="width:50px"> 標紅</label>
<div id="stat"></div></div><div id="list"></div></div>
<div id="main"><div id="wrap"><img id="im"></div></div>
<script>
const PAGES = __DATA__;
const pg=document.getElementById('pg'),im=document.getElementById('im'),wrap=document.getElementById('wrap'),
 list=document.getElementById('list'),zm=document.getElementById('zm'),th=document.getElementById('th'),
 showlab=document.getElementById('showlab'),stat=document.getElementById('stat');
PAGES.forEach((p,i)=>pg.add(new Option(p.name.replace(/^.*_頁面_/,'頁 '),i)));
function color(s){const t=+th.value;return s<t?'#e00':s<0.95?'#e90':'#0a0'}
function render(){
 const p=PAGES[pg.value],z=+zm.value;
 im.onload=()=>{
  im.style.width=im.naturalWidth*z+'px';
  wrap.querySelectorAll('.box,.lab').forEach(e=>e.remove());list.innerHTML='';
  let low=0;
  p.items.forEach((it,k)=>{
   const xs=it.box.map(b=>b[0]),ys=it.box.map(b=>b[1]);
   const x=Math.min(...xs)*z,y=Math.min(...ys)*z,w=(Math.max(...xs)-Math.min(...xs))*z,h=(Math.max(...ys)-Math.min(...ys))*z;
   const c=color(it.score);if(it.score<+th.value)low++;
   const b=document.createElement('div');b.className='box';b.style.cssText=`left:${x}px;top:${y}px;width:${w}px;height:${h}px;border-color:${c}`;
   b.title=`${it.text}  (${it.score.toFixed(3)})`;b.dataset.k=k;wrap.appendChild(b);
   if(showlab.checked){const l=document.createElement('div');l.className='lab';l.style.cssText=`left:${x}px;top:${y+h}px;color:${c}`;l.textContent=it.text;wrap.appendChild(l)}
   const r=document.createElement('div');r.className='row'+(it.score<+th.value?' lo':'');r.dataset.k=k;
   r.textContent=`${it.score.toFixed(2)}  ${it.text}`;list.appendChild(r);
   const sel=()=>{document.querySelectorAll('.sel').forEach(e=>e.classList.remove('sel'));b.classList.add('sel');r.classList.add('sel')};
   b.onclick=()=>{sel();r.scrollIntoView({block:'center'})};
   r.onclick=()=>{sel();b.scrollIntoView({block:'center',inline:'center'})};
  });
  stat.textContent=`${p.model||''}｜${p.items.length} 個文字框｜低信心 ${low}`;
 };
 if(im.getAttribute('src')===p.src)im.onload();else im.src=p.src;
}
[pg,zm,th,showlab].forEach(e=>e.oninput=render);
document.onkeydown=e=>{if(e.target.tagName==='INPUT')return;
 if(e.key==='ArrowRight'&&pg.value<PAGES.length-1){pg.value++;render()}
 if(e.key==='ArrowLeft'&&pg.value>0){pg.value--;render()}};
render();
</script></html>"""
out.write_text(html.replace("__DATA__", json.dumps(pages, ensure_ascii=False)))
print(f"wrote {out} ({len(pages)} pages)")
