"""Stand-in OpenAI-compatible LLM server for offline testing (NOT a real model).
Run: python scripts/mock_llm.py 8765  -> base URL http://127.0.0.1:8765/v1, any key, model 'mock'.
Behaviour: the first talk-track attempt for a bullet slide deliberately reads the bullets verbatim, so
the app's overlap check + regeneration path is exercised; the retry returns a paraphrased explanation."""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


STOP = set("the a an is are be by of to in on for and or what which who how will would much many do does it this that".split())


def _words(s):
    return set(re.findall(r"\w+", re.sub(r"(\d)([a-z])", r"\1 \2", s.lower()))) - STOP


def script_reply(msgs):
    user = msgs[1]["content"]
    retry = any("Too close to the slide text" in m["content"] for m in msgs if m["role"] == "user")
    title = re.search(r"Title: (.*)", user).group(1)
    body = re.search(r"Body:\n(.*?)(?:\n[A-Z][a-z]+.*?:|\Z)", user, re.S)
    facts = re.findall(r"^- (.*)$", user.split("Computed facts")[1], re.M) if "Computed facts" in user else []
    notes = user.split("SPEAKER NOTES (presenter's intent, rephrase naturally):\n")[1].strip() if "SPEAKER NOTES" in user else ""
    nxt = re.search(r"Next slide: (.*?)\.\n", user).group(1)
    if body and not retry and not notes:
        bullets = [b.strip("- ").strip() for b in body.group(1).splitlines() if b.strip()]
        return f"{title}. " + ". ".join(bullets) + "."
    parts = [f"So what's the real story behind {title.lower()}?"]
    if notes:
        parts.append("In short, " + notes.split(". ")[0].lower().rstrip(".") + ", and that's the thought I want you to hold on to.")
    if facts:
        parts.append("Look at the shape of the numbers: " + facts[0][0].lower() + facts[0][1:])
    if body:
        parts.append("Taken together, these points tell us the opportunity is real, but it rewards whoever moves first and executes with discipline.")
    parts.append("That matters because it changes where we should put our money and our attention.")
    parts.append("And that leads us to " + (nxt if "none" not in nxt else "our close") + ".")
    return " ".join(parts)


def qa_reply(msgs):
    user = msgs[-1]["content"]
    q = user.split("Question:")[-1].strip()
    blocks = re.findall(r"\[Slide (\d+)([^\]]*)\]\n(.*?)(?=\n\n\[Slide|\n\nQuestion:)", user, re.S)
    def score(b):
        common = _words(q) & _words(b[2])
        return len(common) + sum(1 for w in common if w.isdigit()) + (0.1 if "CURRENT" in b[1] else 0)
    best = max(blocks, key=score)
    first = best[2].strip().splitlines()[0]
    return json.dumps({"answer": f"(mock) Good question. The best evidence is on [Slide {best[0]}], {first}. "
                                 "That's the figure I'd anchor on.", "slides": [int(best[0])], "jump_to": int(best[0])})


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        msgs = body.get("messages", [])
        sysm = msgs[0]["content"] if msgs else ""
        if "SPOKEN talk track" in sysm:
            content = script_reply(msgs)
        elif "live co-presenter" in sysm:
            content = qa_reply(msgs)
        elif sysm.startswith("Translate"):
            lang = re.search(r"spoken (.*?)\.", sysm).group(1)
            content = f"[mock {lang} translation] " + msgs[-1]["content"]
        else:
            content = "ready"
        out = {"id": "mock-1", "object": "chat.completion", "created": 0, "model": body.get("model", "mock"),
               "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
               "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
        data = json.dumps(out).encode()
        self.send_response(200); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"mock LLM on http://127.0.0.1:{port}/v1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
