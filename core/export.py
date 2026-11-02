"""Exports: talk track (TXT / DOCX), pptx with scripts written into speaker notes, a standalone
HTML auto-player and an MP4 narrated video."""
from __future__ import annotations

import base64
import io
import json
import subprocess
import tempfile
from pathlib import Path
from typing import List

from .deck import Slide


def talk_track_txt(slides: List[Slide], scripts: List[str], title: str = "Talk track") -> str:
    out = [title, "=" * len(title), ""]
    for s, sc in zip(slides, scripts):
        out += [f"Slide {s.number}: {s.title}", "-" * 40, sc.strip(), ""]
    return "\n".join(out)


def talk_track_docx(slides: List[Slide], scripts: List[str], title: str = "Talk track") -> bytes:
    from docx import Document
    from docx.shared import Pt
    d = Document()
    d.add_heading(title, 0)
    for s, sc in zip(slides, scripts):
        d.add_heading(f"Slide {s.number}: {s.title}", level=2)
        for para in [p for p in sc.split("\n") if p.strip()]:
            p = d.add_paragraph(para.strip()); p.runs[0].font.size = Pt(11)
    b = io.BytesIO(); d.save(b)
    return b.getvalue()


def pptx_with_notes(src: str, scripts: List[str]) -> bytes:
    from pptx import Presentation
    prs = Presentation(src)
    for s, sc in zip(prs.slides, scripts):
        s.notes_slide.notes_text_frame.text = sc.strip()
    b = io.BytesIO(); prs.save(b)
    return b.getvalue()


def _b64(path: str, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(Path(path).read_bytes()).decode()


def _img_b64(path: str, max_w: int = 1600) -> str:
    """Slide image as a data URI (JPEG, capped width) so the player stays light and decodes fast."""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        if im.width > max_w:
            im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=88)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return _b64(path, "image/png")


def player_html(slides: List[Slide], audio_paths: List[str], scripts: List[str], *, autoplay=True,
                gap_ms=900, height=560, rtl=False, lead_ms=700) -> str:
    """Self-contained auto walkthrough player.

    For every slide: show the slide image, wait until it has actually loaded and been painted, hold
    it for `lead_ms` (a short beat so the audience sees the slide first), then play its narration.
    When the narration ends it waits `gap_ms` and moves on. If the browser blocks autoplay, the
    first slide stays visible with a Play button over it. window.__dn exposes state for tests.
    """
    items = [{"img": _img_b64(s.image_path), "audio": _b64(a, "audio/mpeg"), "title": s.title,
              "n": s.number, "script": sc} for s, a, sc in zip(slides, audio_paths, scripts)]
    data = json.dumps(items).replace("</", "<\\/")   # never let script text close the <script> tag
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;font-family:system-ui,Segoe UI,Arial;background:#0f1724;color:#eee}}
#wrap{{max-width:1100px;margin:auto;padding:8px}} #stage{{position:relative}}
img{{display:block;width:100%;max-height:{height}px;object-fit:contain;background:#fff;border-radius:8px;transition:opacity .25s}}
#big{{position:absolute;inset:0;margin:auto;width:120px;height:120px;border-radius:60px;font-size:48px;display:none;opacity:.92}}
.bar{{display:flex;gap:8px;align-items:center;margin:8px 0}} button{{background:#2d6cdf;color:#fff;border:0;border-radius:6px;padding:7px 14px;font-size:15px;cursor:pointer}}
#prog{{flex:1;height:8px;background:#334;border-radius:4px;overflow:hidden}} #fill{{height:100%;width:0;background:#4ade80}}
#cap{{font-size:15px;line-height:1.45;color:#cfd8e3;max-height:110px;overflow:auto;direction:{'rtl' if rtl else 'ltr'}}}
#st{{font-size:12px;color:#8aa}}
</style></head><body><div id="wrap"><div id="stage"><img id="img" alt="slide"><button id="big" title="Play">▶</button></div><div class="bar">
<button id="prev">◀ Prev</button><button id="play">⏸ Pause</button><button id="next">Next ▶</button>
<span id="lab"></span><div id="prog"><div id="fill"></div></div><span id="st"></span></div><div id="cap"></div></div>
<script>
const S={data};const LEAD={int(lead_ms)},GAP={int(gap_ms)};let i=0,playing={str(autoplay).lower()},tok=0,timer=null;const A=new Audio();A.preload='auto';
const $=id=>document.getElementById(id);const img=$('img'),lab=$('lab'),fill=$('fill'),cap=$('cap'),pb=$('play'),big=$('big'),st=$('st');
window.__dn={{log:[],slide:0,state:'init',total:S.length}};
function ev(type){{window.__dn.log.push({{type,slide:i,t:performance.now()}});window.__dn.state=type;window.__dn.slide=i;}}
function status(t){{st.textContent=t;}}
function blocked(){{playing=false;pb.textContent='▶ Play';big.style.display='block';status('Press play to start');ev('blocked');}}
function startAudio(my){{if(my!==tok||!playing)return;A.currentTime=0;const pr=A.play();ev('audio_start');status('narrating');
 if(pr&&pr.catch)pr.catch(()=>{{if(my===tok)blocked();}});}}
function show(k,start){{tok++;const my=tok;clearTimeout(timer);A.pause();
 i=Math.max(0,Math.min(S.length-1,k));img.style.opacity=0.15;
 lab.textContent='Slide '+S[i].n+' / '+S.length;cap.textContent=S[i].script;fill.style.width=(100*i/Math.max(1,S.length-1))+'%';
 A.src=S[i].audio;status('showing slide');
 const shown=()=>{{if(my!==tok)return;img.style.opacity=1;
   requestAnimationFrame(()=>requestAnimationFrame(()=>{{if(my!==tok)return;ev('slide_shown');
     if(start&&playing)timer=setTimeout(()=>startAudio(my),LEAD);}}));}};
 img.onload=shown;img.onerror=shown;img.src=S[i].img;if(img.complete&&img.naturalWidth)shown();}}
A.onended=()=>{{ev('audio_end');if(i<S.length-1){{status('next slide…');timer=setTimeout(()=>{{if(playing)show(i+1,true)}},GAP);}}
 else{{playing=false;pb.textContent='↺ Replay';ev('done');status('finished');}}}};
function play(){{playing=true;pb.textContent='⏸ Pause';big.style.display='none';
 if(window.__dn.state==='slide_shown'||window.__dn.state==='blocked'||A.currentTime===0)show(i,true);else{{A.play();ev('resume');}}}}
pb.onclick=()=>{{if(pb.textContent.includes('Replay')){{i=0;play();return}}
 if(playing){{playing=false;pb.textContent='▶ Play';A.pause();clearTimeout(timer);ev('paused');}}else play();}};
big.onclick=play;
$('next').onclick=()=>show(i+1,true);$('prev').onclick=()=>show(i-1,true);
document.addEventListener('keydown',e=>{{if(e.key==='ArrowRight'||e.key==='PageDown')show(i+1,true);if(e.key==='ArrowLeft'||e.key==='PageUp')show(i-1,true);if(e.key===' '){{e.preventDefault();pb.click();}}}});
if(!playing){{pb.textContent='▶ Play';big.style.display='block';}}show(0,true);
</script></body></html>"""


def narrated_video(slides: List[Slide], audio_paths: List[str], out_path: str, tail_s: float = 0.8, lead_s: float = 0.7) -> str:
    """MP4: each slide appears first, narration starts after `lead_s`, slide held to the end of it."""
    with tempfile.TemporaryDirectory() as td:
        parts = []
        for k, (s, a) in enumerate(zip(slides, audio_paths)):
            p = Path(td) / f"p{k:03d}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", s.image_path, "-i", a,
                            "-af", f"adelay={int(lead_s * 1000)}:all=1,apad=pad_dur={tail_s}", "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:a", "aac", "-b:a", "128k", "-shortest", str(p)],
                           check=True, capture_output=True, timeout=600)
            parts.append(p)
        lst = Path(td) / "l.txt"; lst.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", out_path],
                       check=True, capture_output=True, timeout=600)
    return out_path
