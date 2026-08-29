"""
query_llm.py — Centralized Groq LLM Query Handler for Ledger AI.

Provides robust Groq API key resolution across GROQ_API_KEY, GROQ_API_KEY1, GROQ_API_KEY2,
and executes LLM completions with failover key rotation and model fallbacks.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load root and frontend environment variables
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)
load_dotenv(ROOT / "frontend" / ".env", override=True)


def get_all_groq_keys() -> list[str]:
    """Retrieve all distinct non-empty Groq API keys from environment variables."""
    keys = []
    for var_name in ["GROQ_API_KEY", "GROQ_API_KEY1", "GROQ_API_KEY2", "GROQ_KEY"]:
        val = os.getenv(var_name, "").strip().rstrip("\\")
        if val and val not in keys and val.startswith("gsk_"):
            keys.append(val)
    return keys


def get_groq_api_key() -> str:
    """Returns the primary active Groq API key."""
    keys = get_all_groq_keys()
    return keys[0] if keys else ""


def get_groq_model() -> str:
    """Returns configured model name with safe default."""
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
    if not model or model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b", "qwen/qwen3.8-27b"):
        return model if model else "openai/gpt-oss-120b"
    return "openai/gpt-oss-120b"


def query_llm(prompt: str, system_prompt: str = None, model: str = None, temperature: float = 0.0) -> str:
    """
    Query Groq LLM with prompt and return text response.
    Supports automatic key rotation across GROQ_API_KEY, GROQ_API_KEY1, GROQ_API_KEY2.
    """
    keys = get_all_groq_keys()
    if not keys:
        print("[query_llm Warning] No GROQ API keys found in environment.")
        return ""

    if not model:
        model = get_groq_model()

    from groq import Groq

    models_to_try = [model, "openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"]
    # Deduplicate model list maintaining order
    seen = set()
    models_to_try = [m for m in models_to_try if not (m in seen or seen.add(m))]

    last_error = None

    for key in keys:
        try:
            client = Groq(api_key=key, timeout=15.0)
            for m in models_to_try:
                try:
                    messages = []
                    if system_prompt:
                        messages.append({"role": "system", "content": system_prompt})
                    messages.append({"role": "user", "content": prompt})

                    response = client.chat.completions.create(
                        model=m,
                        messages=messages,
                        temperature=temperature,
                    )
                    if response and response.choices:
                        content = response.choices[0].message.content or ""
                        return content.strip()
                except Exception as m_exc:
                    last_error = m_exc
                    err_str = str(m_exc).lower()
                    if "401" in err_str or "invalid api key" in err_str:
                        # Break model loop to try next key immediately
                        break
                    continue
        except Exception as k_exc:
            last_error = k_exc
            continue

    print(f"[query_llm Error] All Groq API key attempts failed. Last error: {last_error}")
    return ""
