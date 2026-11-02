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


def player_html(slides: List[Slide], audio_paths: List[str], scripts: List[str], *, autoplay=True,
                gap_ms=900, height=560, rtl=False) -> str:
    """Self-contained auto walkthrough player: slide image + audio, auto-advances, play/pause/prev/next, progress."""
    items = [{"img": _b64(s.image_path, "image/png"), "audio": _b64(a, "audio/mpeg"), "title": s.title,
              "n": s.number, "script": sc} for s, a, sc in zip(slides, audio_paths, scripts)]
    data = json.dumps(items).replace("</", "<\\/")   # never let script text close the <script> tag
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;font-family:system-ui,Segoe UI,Arial;background:#0f1724;color:#eee}}
#wrap{{max-width:1100px;margin:auto;padding:8px}} img{{width:100%;max-height:{height}px;object-fit:contain;background:#fff;border-radius:8px}}
.bar{{display:flex;gap:8px;align-items:center;margin:8px 0}} button{{background:#2d6cdf;color:#fff;border:0;border-radius:6px;padding:7px 14px;font-size:15px;cursor:pointer}}
#prog{{flex:1;height:8px;background:#334;border-radius:4px;overflow:hidden}} #fill{{height:100%;width:0;background:#4ade80}}
#cap{{font-size:15px;line-height:1.45;color:#cfd8e3;max-height:110px;overflow:auto;direction:{'rtl' if rtl else 'ltr'}}}
</style></head><body><div id="wrap"><img id="img"><div class="bar">
<button id="prev">◀ Prev</button><button id="play">⏸ Pause</button><button id="next">Next ▶</button>
<span id="lab"></span><div id="prog"><div id="fill"></div></div></div><div id="cap"></div></div>
<script>
const S={data};let i=0,playing={str(autoplay).lower()};const A=new Audio();
const img=document.getElementById('img'),lab=document.getElementById('lab'),fill=document.getElementById('fill'),cap=document.getElementById('cap'),pb=document.getElementById('play');
function show(k,start){{i=Math.max(0,Math.min(S.length-1,k));img.src=S[i].img;lab.textContent='Slide '+S[i].n+' / '+S.length;
 cap.textContent=S[i].script;A.src=S[i].audio;fill.style.width=(100*i/Math.max(1,S.length-1))+'%';if(start&&playing)A.play().catch(()=>{{playing=false;pb.textContent='▶ Play';}});}}
A.onended=()=>{{if(i<S.length-1)setTimeout(()=>{{if(playing)show(i+1,true)}},{gap_ms});else{{playing=false;pb.textContent='↺ Replay';}}}};
pb.onclick=()=>{{if(pb.textContent.includes('Replay')){{playing=true;pb.textContent='⏸ Pause';show(0,true);return}}
 playing=!playing;pb.textContent=playing?'⏸ Pause':'▶ Play';if(playing)A.play();else A.pause();}};
document.getElementById('next').onclick=()=>show(i+1,true);document.getElementById('prev').onclick=()=>show(i-1,true);
document.addEventListener('keydown',e=>{{if(e.key==='ArrowRight'||e.key==='PageDown')show(i+1,true);if(e.key==='ArrowLeft'||e.key==='PageUp')show(i-1,true);if(e.key===' '){{e.preventDefault();pb.click();}}}});
if(!playing)pb.textContent='▶ Play';show(0,true);
</script></body></html>"""


def narrated_video(slides: List[Slide], audio_paths: List[str], out_path: str, tail_s: float = 0.8) -> str:
    """MP4: each slide image held for the length of its narration."""
    with tempfile.TemporaryDirectory() as td:
        parts = []
        for k, (s, a) in enumerate(zip(slides, audio_paths)):
            p = Path(td) / f"p{k:03d}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", s.image_path, "-i", a,
                            "-af", f"apad=pad_dur={tail_s}", "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:a", "aac", "-b:a", "128k", "-shortest", str(p)],
                           check=True, capture_output=True, timeout=600)
            parts.append(p)
        lst = Path(td) / "l.txt"; lst.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", out_path],
                       check=True, capture_output=True, timeout=600)
    return out_path
