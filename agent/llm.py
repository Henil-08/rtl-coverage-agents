from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "openai/gpt-oss-120b"


@lru_cache(maxsize=4)
def get_llm(model: str | None = None, temperature: float = 0.2):
    if not os.getenv("GROQ_API_KEY"):
        return None
    from langchain_groq import ChatGroq

    return ChatGroq(model=model or os.getenv("GROQ_MODEL", DEFAULT_MODEL), temperature=temperature)
