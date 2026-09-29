"""Free-tier language-model access with rotation and failover.

Order: Gemini first, Groq as backup. For each provider the list of usable models is discovered from the provider's
own API (cached), ranked so free, fast models come first, and rotated on trouble:

    429 rate limit     -> that model cools down (Retry-After if given, else 90 s), try the next model
    404 / 400          -> model not usable for this call: cools down for an hour, try the next model
    5xx / timeout      -> short cool-down, try the next model
    401 / 403          -> the key itself is bad: provider is switched off for 10 minutes, move to the next provider

If everything fails, `complete` returns None and callers use their own grounded, model-free answer. The language model is
optional: FuelGrid never depends on it for a decision."""
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.core.logging import get_logger

log = get_logger("llm")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GROQ_BASE = "https://api.groq.com/openai/v1"
GEMINI_FALLBACK = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash-lite", "gemini-2.0-flash"]
GROQ_FALLBACK = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "gemma2-9b-it"]
LIST_TTL_S = 3600
MAX_TRIES_PER_PROVIDER = 4


@dataclass
class LlmResult:
    text: str
    provider: str
    model: str


# ------------------------------------------------------------------------------------------------ ranking
def rank_gemini(names: list[str]) -> list[str]:
    """Free-tier friendly first: flash-lite, then flash; stable before preview/experimental; newer before older."""
    bad = ("pro", "embedding", "tts", "image", "live", "audio", "robotics", "computer-use", "aqa", "imagen", "veo", "gemma", "learnlm", "thinking")
    out = []
    for n in names:
        short = n.removeprefix("models/")
        if not short.startswith("gemini-") or any(b in short for b in bad):
            continue
        m = re.match(r"gemini-(\d+(?:\.\d+)?)", short)
        version = float(m.group(1)) if m else 0.0
        tier = 0 if "flash-lite" in short else 1 if "flash" in short else 2
        experimental = 1 if re.search(r"preview|exp|-\d{2}-\d{4}|-\d{3}$", short) else 0
        out.append((experimental, tier, -version, short))
    return [x[3] for x in sorted(out)]


def rank_groq(names: list[str]) -> list[str]:
    bad = ("whisper", "guard", "tts", "playai", "distil", "embed", "vision", "safeguard", "prompt-guard")
    out = []
    for n in names:
        if any(b in n for b in bad):
            continue
        size = 0 if ("8b" in n or "instant" in n) else 1 if ("17b" in n or "scout" in n or "9b" in n) else 2 if "70b" in n or "versatile" in n else 3
        out.append((size, n))
    return [x[1] for x in sorted(out)]


# ------------------------------------------------------------------------------------------------ provider state
class _Provider:
    def __init__(self, name: str, key: str | None, fallback: list[str]):
        self.name, self.key, self.fallback = name, key, fallback
        self.models: list[str] = []
        self.listed_at = 0.0
        self.cool: dict[str, float] = {}
        self.disabled_until = 0.0
        self.last_error: str | None = None
        self.last_model: str | None = None

    @property
    def usable(self) -> bool:
        return bool(self.key) and time.time() >= self.disabled_until

    def candidates(self) -> list[str]:
        now = time.time()
        return [m for m in (self.models or self.fallback) if self.cool.get(m, 0) <= now]

    def status(self) -> dict:
        now = time.time()
        return {"provider": self.name, "configured": bool(self.key), "active": self.usable,
                "models_discovered": len(self.models), "models_cooling": sorted(m for m, t in self.cool.items() if t > now),
                "next_models": self.candidates()[:4], "last_model": self.last_model, "last_error": self.last_error}


class LlmRouter:
    def __init__(self, gemini_key: str | None, groq_key: str | None, timeout: float = 8.0, transport: httpx.AsyncBaseTransport | None = None):
        self.gemini = _Provider("gemini", gemini_key, GEMINI_FALLBACK)
        self.groq = _Provider("groq", groq_key, GROQ_FALLBACK)
        self.timeout, self.transport = timeout, transport

    @property
    def configured(self) -> bool:
        return bool(self.gemini.key or self.groq.key)

    def status(self) -> dict:
        return {"configured": self.configured, "providers": [self.gemini.status(), self.groq.status()]}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, transport=self.transport)

    # ------------------------------------------------------------------ discovery
    async def refresh_models(self, p: _Provider, force: bool = False) -> None:
        if not p.key or (p.models and not force and time.time() - p.listed_at < LIST_TTL_S):
            return
        try:
            async with self._client() as h:
                if p.name == "gemini":
                    r = await h.get(f"{GEMINI_BASE}/models", params={"pageSize": 200}, headers={"x-goog-api-key": p.key})
                    r.raise_for_status()
                    names = [m["name"] for m in r.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
                    p.models = rank_gemini(names)
                else:
                    r = await h.get(f"{GROQ_BASE}/models", headers={"Authorization": f"Bearer {p.key}"})
                    r.raise_for_status()
                    p.models = rank_groq([m["id"] for m in r.json().get("data", []) if m.get("active", True)])
            p.listed_at = time.time()
            log.info("llm_models_discovered", provider=p.name, count=len(p.models), first=p.models[:3])
        except Exception as e:  # discovery failure => static fallback list, retried after an hour
            p.listed_at = time.time()
            p.last_error = f"model discovery failed: {str(e)[:80]}"
            log.warning("llm_discovery_failed", provider=p.name, error=str(e)[:100])
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403):
                p.disabled_until = time.time() + 600

    # ------------------------------------------------------------------ one call
    async def _call(self, p: _Provider, model: str, prompt: str) -> str:
        async with self._client() as h:
            if p.name == "gemini":
                r = await h.post(f"{GEMINI_BASE}/models/{model.removeprefix('models/')}:generateContent", headers={"x-goog-api-key": p.key or ""},
                                 json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 700, "temperature": 0.2}})
            else:
                r = await h.post(f"{GROQ_BASE}/chat/completions", headers={"Authorization": f"Bearer {p.key}"},
                                 json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 400, "temperature": 0.2})
            r.raise_for_status()
            data = r.json()
        if p.name == "gemini":
            parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            return "".join(x.get("text", "") for x in parts).strip()
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()

    # ------------------------------------------------------------------ public API
    async def complete(self, prompt: str, validate: Callable[[str], bool] | None = None) -> LlmResult | None:
        for p in (self.gemini, self.groq):
            if not p.usable:
                continue
            await self.refresh_models(p)
            tries = 0
            for model in p.candidates():
                if tries >= MAX_TRIES_PER_PROVIDER or not p.usable:
                    break
                tries += 1
                try:
                    text = await self._call(p, model, prompt)
                    if not text:
                        raise ValueError("empty response")
                    if validate is not None and not validate(text):
                        p.last_error = f"{model}: reply rejected by validation"
                        log.warning("llm_reply_rejected", provider=p.name, model=model)
                        continue  # try the next model; an ungrounded reply is never shown
                    p.last_model, p.last_error = model, None
                    return LlmResult(text, p.name, model)
                except httpx.HTTPStatusError as e:
                    code = e.response.status_code
                    p.last_error = f"{model}: HTTP {code}"
                    if code == 429:
                        ra = e.response.headers.get("retry-after", "")
                        p.cool[model] = time.time() + (float(ra) if ra.replace(".", "", 1).isdigit() else 90.0)
                    elif code in (401, 403):
                        p.disabled_until = time.time() + 600
                        log.error("llm_key_rejected", provider=p.name)
                    elif code in (400, 404):
                        p.cool[model] = time.time() + 3600
                    else:
                        p.cool[model] = time.time() + 20
                except (httpx.HTTPError, ValueError, KeyError) as e:
                    p.last_error = f"{model}: {type(e).__name__}"
                    p.cool[model] = time.time() + 20
                log.warning("llm_rotating", provider=p.name, failed_model=model, reason=p.last_error)
        return None
