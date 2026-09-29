import httpx
import respx

from app.intelligence.llm import GEMINI_BASE, GROQ_BASE, LlmRouter, rank_gemini, rank_groq

GEMINI_LIST = {"models": [
    {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-2.5-flash-preview-05-20", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]},
]}
GROQ_LIST = {"data": [
    {"id": "whisper-large-v3", "active": True}, {"id": "llama-3.3-70b-versatile", "active": True},
    {"id": "llama-3.1-8b-instant", "active": True}, {"id": "meta-llama/llama-guard-4-12b", "active": True},
    {"id": "llama-3.2-1b-old", "active": False},
]}


def gen(text):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def chat(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def test_ranking_prefers_free_fast_stable_models_and_drops_unusable_ones():
    names = [m["name"] for m in GEMINI_LIST["models"]]
    ranked = rank_gemini(names)
    assert ranked[0] == "gemini-2.5-flash-lite" and "gemini-2.5-flash" in ranked
    assert ranked.index("gemini-2.5-flash") < ranked.index("gemini-2.5-flash-preview-05-20")  # stable before preview
    assert not any(x in " ".join(ranked) for x in ("pro", "embedding", "tts"))
    assert rank_groq([m["id"] for m in GROQ_LIST["data"] if m["active"]]) == ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]


@respx.mock
async def test_models_are_discovered_dynamically_and_first_choice_is_used():
    respx.get(f"{GEMINI_BASE}/models").mock(return_value=httpx.Response(200, json=GEMINI_LIST))
    call = respx.post(f"{GEMINI_BASE}/models/gemini-2.5-flash-lite:generateContent").mock(return_value=gen("hello"))
    r = LlmRouter("gk", None)
    out = await r.complete("hi")
    assert out and (out.provider, out.model, out.text) == ("gemini", "gemini-2.5-flash-lite", "hello") and call.called
    assert r.status()["providers"][0]["models_discovered"] >= 3


@respx.mock
async def test_rotates_to_next_gemini_model_on_rate_limit_and_remembers_cooldown():
    respx.get(f"{GEMINI_BASE}/models").mock(return_value=httpx.Response(200, json=GEMINI_LIST))
    lite = respx.post(f"{GEMINI_BASE}/models/gemini-2.5-flash-lite:generateContent").mock(return_value=httpx.Response(429, headers={"retry-after": "30"}))
    flash = respx.post(f"{GEMINI_BASE}/models/gemini-2.5-flash:generateContent").mock(return_value=gen("from flash"))
    r = LlmRouter("gk", None)
    first = await r.complete("hi")
    assert first.model == "gemini-2.5-flash" and lite.call_count == 1
    second = await r.complete("hi")
    assert second.model == "gemini-2.5-flash" and lite.call_count == 1, "rate-limited model must be skipped while cooling down"
    assert flash.call_count == 2 and "gemini-2.5-flash-lite" in r.status()["providers"][0]["models_cooling"]


@respx.mock
async def test_falls_back_to_groq_when_gemini_is_exhausted():
    respx.get(f"{GEMINI_BASE}/models").mock(return_value=httpx.Response(200, json=GEMINI_LIST))
    respx.post(url__startswith=f"{GEMINI_BASE}/models/").mock(return_value=httpx.Response(503))
    respx.get(f"{GROQ_BASE}/models").mock(return_value=httpx.Response(200, json=GROQ_LIST))
    respx.post(f"{GROQ_BASE}/chat/completions").mock(return_value=chat("from groq"))
    out = await LlmRouter("gk", "qk").complete("hi")
    assert out and out.provider == "groq" and out.model == "llama-3.1-8b-instant"


@respx.mock
async def test_bad_key_switches_provider_off_and_moves_on():
    respx.get(f"{GEMINI_BASE}/models").mock(return_value=httpx.Response(200, json=GEMINI_LIST))
    bad = respx.post(url__startswith=f"{GEMINI_BASE}/models/").mock(return_value=httpx.Response(403))
    respx.get(f"{GROQ_BASE}/models").mock(return_value=httpx.Response(200, json=GROQ_LIST))
    respx.post(f"{GROQ_BASE}/chat/completions").mock(return_value=chat("ok"))
    r = LlmRouter("bad", "qk")
    assert (await r.complete("hi")).provider == "groq"
    assert bad.call_count == 1, "a rejected key must not be retried on every model"
    assert not r.gemini.usable


@respx.mock
async def test_discovery_failure_uses_static_fallback_list():
    respx.get(f"{GEMINI_BASE}/models").mock(side_effect=httpx.ConnectError("no network"))
    respx.post(f"{GEMINI_BASE}/models/gemini-2.5-flash-lite:generateContent").mock(return_value=gen("still works"))
    out = await LlmRouter("gk", None).complete("hi")
    assert out and out.text == "still works"


@respx.mock
async def test_validation_rejection_rotates_and_nothing_ungrounded_is_returned():
    respx.get(f"{GEMINI_BASE}/models").mock(return_value=httpx.Response(200, json=GEMINI_LIST))
    respx.post(f"{GEMINI_BASE}/models/gemini-2.5-flash-lite:generateContent").mock(return_value=gen("invented 12345 liters"))
    respx.post(f"{GEMINI_BASE}/models/gemini-2.5-flash:generateContent").mock(return_value=gen("300 liters left"))
    out = await LlmRouter("gk", None).complete("hi", validate=lambda t: "12345" not in t)
    assert out.model == "gemini-2.5-flash" and out.text == "300 liters left"


@respx.mock
async def test_if_every_reply_is_ungrounded_nothing_is_returned():
    respx.get(f"{GEMINI_BASE}/models").mock(return_value=httpx.Response(200, json=GEMINI_LIST))
    respx.post(url__startswith=f"{GEMINI_BASE}/models/").mock(return_value=gen("invented 12345"))
    assert await LlmRouter("gk", None).complete("hi", validate=lambda t: "12345" not in t) is None


async def test_no_keys_means_not_configured():
    r = LlmRouter(None, None)
    assert not r.configured and await r.complete("hi") is None
