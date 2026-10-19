"""Model registry. A model is named "provider:model", for example
    groq:openai/gpt-oss-120b   anthropic:claude-sonnet-5-5   openai:gpt-5-mini
    ollama:qwen2.5-coder:7b    lmstudio:openai/gpt-oss-20b

Cloud keys come from .env (GROQ_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY). Local models are served by
Ollama or LM Studio through their OpenAI-compatible endpoints. DEFAULT_LLM picks the model used when a
session does not choose one.
"""

from __future__ import annotations

import json
import os
import urllib.request
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_MODEL = "openai/gpt-oss-120b"
LOCAL_URLS = {"ollama": "http://localhost:11434", "lmstudio": "http://localhost:1234"}
KEYS = {"groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
PROVIDERS = ("groq", "anthropic", "openai", "ollama", "lmstudio", "mcp")
SUGGESTED = {
    "groq": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"],
    "anthropic": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
    "openai": [],
    "ollama": ["qwen2.5-coder:7b", "qwen2.5-coder:14b", "gpt-oss:20b", "llama3.1:8b"],
    "lmstudio": [],
    "mcp": ["claude"],
}
# Groq's free tier allows 8,000 tokens per minute, and a single request (prompt plus answer) has to fit.
GROQ_FREE_TPM = 8000
_REFS: dict[int, str] = {}


def default_ref() -> str | None:
    """The model sessions use unless they pick one: DEFAULT_LLM, else the first configured cloud provider."""
    if os.getenv("DEFAULT_LLM"):
        return os.getenv("DEFAULT_LLM")
    legacy = os.getenv("LLM_PROVIDER", "").lower()
    if legacy in LOCAL_URLS:
        return f"{legacy}:{os.getenv('LOCAL_LLM_MODEL', 'openai/gpt-oss-20b')}"
    if os.getenv("GROQ_API_KEY"):
        return f"groq:{os.getenv('GROQ_MODEL', DEFAULT_MODEL)}"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic:claude-sonnet-5-5"
    if os.getenv("OPENAI_API_KEY"):
        return "openai:gpt-5-mini"
    return None


def split(ref: str) -> tuple[str, str]:
    provider, _, model = ref.partition(":")
    if provider not in PROVIDERS or not model:
        raise ValueError(f"model must look like provider:model with provider in {PROVIDERS}, got {ref!r}")
    return provider, model


def local_url(provider: str) -> str:
    env = "OLLAMA_URL" if provider == "ollama" else "LMSTUDIO_URL"
    return os.getenv(env, os.getenv("LOCAL_LLM_URL", LOCAL_URLS[provider])).rstrip("/").removesuffix("/v1")


@lru_cache(maxsize=16)
def make(ref: str, temperature: float = 0.2):
    """Chat model for a provider:model reference."""
    provider, model = split(ref)
    if provider in KEYS and not os.getenv(KEYS[provider]):
        raise ValueError(f"{KEYS[provider]} is not set in .env")
    if provider == "mcp":
        return McpBrain()
    if provider == "groq":
        from langchain_groq import ChatGroq

        extra = {"reasoning_effort": "low"} if model.startswith("openai/gpt-oss") else {}
        return ChatGroq(model=model, temperature=temperature, max_retries=0, **extra)
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, temperature=temperature, max_tokens=8000, max_retries=1)
    from langchain_openai import ChatOpenAI

    if provider == "openai":
        return ChatOpenAI(model=model, max_retries=1)
    return ChatOpenAI(model=model, base_url=local_url(provider) + "/v1", api_key="local", temperature=temperature,
                      timeout=900, max_retries=0)


class McpBrain:
    """Stands in for a model whose answers come from a connected MCP client (Claude Code): the agent
    pauses with its prompt and the client replies through the answer_task tool."""


def is_mcp(ref: str | None) -> bool:
    return bool(ref) and ref.startswith("mcp:")


def get_llm(model: str | None = None):
    """The default chat model (or the given reference), or None when nothing is configured."""
    ref = model or default_ref()
    if not ref:
        return None
    if ":" not in ref:
        ref = f"groq:{ref}"
    try:
        llm = make(ref)
    except ValueError:
        return None
    _REFS[id(llm)] = ref
    return llm


def request_budget(ref: str | None) -> int | None:
    """Tokens one request may use in total, or None when the provider has no practical per-request limit."""
    if not ref or not ref.startswith("groq:"):
        return None
    return int(os.getenv("GROQ_TPM", GROQ_FREE_TPM))


def model_name(llm) -> str:
    return _REFS.get(id(llm)) or getattr(llm, "model_name", None) or type(llm).__name__


def _get_json(url: str, headers: dict | None = None, timeout: float = 4) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "rtl-coverage-agents", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def catalog() -> list[dict]:
    """Every provider with whether it is usable right now and the models it offers."""
    out = []
    for p in PROVIDERS:
        entry = {"provider": p, "ready": False, "models": [], "suggested": SUGGESTED[p], "detail": ""}
        if p == "mcp":
            out.append({**entry, "ready": True, "models": ["claude"], "detail": "Claude Code answers each agent "
                        "step through the MCP tools next_task and answer_task, so no API key is needed"})
            continue
        try:
            if p in KEYS:
                key = os.getenv(KEYS[p])
                if not key:
                    entry["detail"] = f"add {KEYS[p]} to .env"
                elif p == "groq":
                    data = _get_json("https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {key}"})
                    entry["models"] = sorted(m["id"] for m in data["data"] if "whisper" not in m["id"]
                                             and "guard" not in m["id"] and "orpheus" not in m["id"])
                elif p == "anthropic":
                    data = _get_json("https://api.anthropic.com/v1/models",
                                     {"x-api-key": key, "anthropic-version": "2023-06-01"})
                    entry["models"] = [m["id"] for m in data["data"]]
                else:
                    data = _get_json("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"})
                    entry["models"] = sorted(m["id"] for m in data["data"] if m["id"].startswith(("gpt", "o")))
            elif p == "ollama":
                data = _get_json(local_url(p) + "/api/tags", timeout=2)
                entry["models"] = [m["name"] for m in data.get("models", [])]
            else:
                data = _get_json(local_url(p) + "/v1/models", timeout=2)
                entry["models"] = [m["id"] for m in data.get("data", [])]
            entry["ready"] = bool(entry["models"]) or p in KEYS and bool(os.getenv(KEYS[p]))
            if p in LOCAL_URLS and not entry["models"]:
                entry["detail"] = "running, but no models installed"
        except Exception as e:
            if p in LOCAL_URLS:
                entry["detail"] = f"not running at {local_url(p)}"
            elif not entry["detail"]:
                entry["ready"] = bool(os.getenv(KEYS[p]))
                entry["detail"] = f"key set, but listing models failed: {type(e).__name__}"
        out.append(entry)
    return out
