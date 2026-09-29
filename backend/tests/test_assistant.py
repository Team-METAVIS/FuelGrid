from types import SimpleNamespace

import httpx
import pytest
import respx

from app.db.repo import Repo
from app.decision.engine import DecisionEngine
from app.intelligence import assistant
from app.intelligence.llm import GEMINI_BASE, GROQ_BASE, LlmRouter
from tests.conftest import make_snapshot
from tests.test_engine import LOW, FakeClient


@pytest.fixture
async def rt(cfg, store):
    store.snapshot = make_snapshot(hour=8, station_inv=LOW)
    eng = DecisionEngine(cfg, store, FakeClient(), Repo(None), "t")
    await eng.cycle()
    return SimpleNamespace(store=store, engine=eng, cfg=cfg, client=eng.client, repo=eng.repo, llm=LlmRouter(None, None))


async def test_answers_are_grounded_in_live_data(rt):
    risk = assistant.grounded_answer(rt, "how is mirpur diesel doing?")
    assert "mirpur" in risk.lower() and "300" in risk  # the real inventory
    did = next(d.id for d in rt.engine.decisions.values() if d.status == "PROPOSED")
    why = assistant.grounded_answer(rt, f"why recommendation #{did}?")
    assert "Recommendation #" in why and "chance of running out" in why
    at_risk = assistant.grounded_answer(rt, "which stations are at risk?")
    assert "need attention" in at_risk and "Mirpur" in at_risk.title() or "mirpur" in at_risk.lower()
    assert "await approval" in assistant.grounded_answer(rt, "what should I approve next?")
    assert "unmet" in assistant.grounded_answer(rt, "is the optimizer better than doing nothing?")
    assert "policy in use" in assistant.grounded_answer(rt, "is the system healthy?")
    assert assistant.grounded_answer(rt, "tell me something").strip()  # falls back to the briefing


def test_number_guard_rejects_invented_figures():
    src = ["Mirpur has 300 L, stockout in 1.5 h"]
    assert assistant.numbers_are_grounded("Mirpur holds 300 L and has about 1.5 h left.", src)
    assert not assistant.numbers_are_grounded("Mirpur holds 3,000 L.", src)


async def test_no_key_means_grounded_mode(rt):
    out = await assistant.ask(rt, "any incidents?")
    assert out["mode"] == "grounded" and out["answer"]


def _gen(text):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


@respx.mock
async def test_gemini_reword_is_used_when_numbers_match(rt):
    rt.llm = LlmRouter("gk", None)
    draft = assistant.grounded_answer(rt, "what should I approve next?")
    respx.get(f"{GEMINI_BASE}/models").mock(return_value=httpx.Response(200, json={"models": [{"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]}]}))
    respx.post(f"{GEMINI_BASE}/models/gemini-2.5-flash-lite:generateContent").mock(return_value=_gen(draft + " Please review."))
    out = await assistant.ask(rt, "what should I approve next?")
    assert out["mode"] == "llm" and out["provider"] == "gemini" and out["model"] == "gemini-2.5-flash-lite"


@respx.mock
async def test_invented_numbers_are_rejected_and_next_model_is_tried(rt):
    rt.llm = LlmRouter("gk", None)
    listing = {"models": [{"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]}, {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]}]}
    respx.get(f"{GEMINI_BASE}/models").mock(return_value=httpx.Response(200, json=listing))
    respx.post(f"{GEMINI_BASE}/models/gemini-2.5-flash-lite:generateContent").mock(return_value=_gen("Send 99,999 L right now."))
    draft = assistant.grounded_answer(rt, "what should I approve next?")
    respx.post(f"{GEMINI_BASE}/models/gemini-2.5-flash:generateContent").mock(return_value=_gen(draft))
    out = await assistant.ask(rt, "what should I approve next?")
    assert out["mode"] == "llm" and out["model"] == "gemini-2.5-flash" and "99,999" not in out["answer"]


@respx.mock
async def test_all_providers_down_falls_back_to_builtin_answer(rt):
    rt.llm = LlmRouter("gk", "qk")
    respx.get(f"{GEMINI_BASE}/models").mock(return_value=httpx.Response(500))
    respx.post(url__startswith=f"{GEMINI_BASE}/models/").mock(return_value=httpx.Response(503))
    respx.get(f"{GROQ_BASE}/models").mock(return_value=httpx.Response(500))
    respx.post(f"{GROQ_BASE}/chat/completions").mock(return_value=httpx.Response(503))
    out = await assistant.ask(rt, "what should I approve next?")
    assert out["mode"] == "grounded" and out["answer"] and "await approval" in out["answer"]
