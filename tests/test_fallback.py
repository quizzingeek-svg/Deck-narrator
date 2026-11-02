import time, httpx, openai, pytest
from core import llm
from core.llm import LLMConfig
import glob

def _slides():
    from core import deck
    f = sorted(glob.glob("samples/*.pptx") + glob.glob("data/*.pptx"))[0]
    fn = getattr(deck, "load_deck", None) or getattr(deck, "parse_pptx", None) or deck.load_pptx
    r = fn(f); return r if isinstance(r, list) else r.slides

def _err(code, msg):
    req = httpx.Request("POST", "https://x/v1/chat/completions")
    resp = httpx.Response(code, request=req, json={"error": {"message": msg}})
    cls = openai.RateLimitError if code == 429 else openai.AuthenticationError
    return cls(msg, response=resp, body=None)

CFG = LLMConfig("k", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash")

@pytest.mark.parametrize("code,kind", [(429, "quota"), (401, "auth")])
def test_breaker(monkeypatch, code, kind):
    llm.reset_breaker(); calls = []
    def boom(*a, **k): calls.append(1); raise _err(code, "Resource exhausted" if code == 429 else "API key not valid")
    monkeypatch.setattr(llm, "_chat", boom)
    s = _slides()
    res = llm.answer_question(CFG, s, "what is the revenue growth?", 0)
    assert res["engine"].startswith("built-in") and res["answer"]
    assert llm.ai_status(CFG)["kind"] == kind and llm.ai_status(CFG)["seconds_left"] > 500
    with pytest.raises(llm.AIUnavailable):
        llm.generate_script(CFG, s, 0)
    llm.answer_question(CFG, s, "anything", 1)
    assert len(calls) == 1  # cooldown: AI not called again
    monkeypatch.setattr(llm, "_DOWN", {k: (time.time() - 1, *v[1:]) for k, v in llm._DOWN.items()})
    assert llm.ai_ok(CFG)  # cooldown expires
