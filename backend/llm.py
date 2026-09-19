"""
LLM provider adapter — provider-agnostic via environment variables.

Supported env vars (all required unless noted):
  LLM_PROVIDER    anthropic | openai | gemini | openai-compatible | openrouter
  LLM_MODEL       e.g. claude-sonnet-4-5, gpt-4.1, gemini-2.5-pro, google/gemini-3.1-flash-lite
  LLM_API_KEY
  LLM_BASE_URL    optional; used by openai/openai-compatible providers. openrouter ignores this and always uses https://openrouter.ai/api/v1
"""

import os
import json
import re

import httpx
from dotenv import load_dotenv

load_dotenv()


def _get_config() -> dict:
    load_dotenv(override=True)
    return {
        "provider": os.getenv("LLM_PROVIDER", "").strip().lower(),
        "model": os.getenv("LLM_MODEL", "").strip(),
        "api_key": os.getenv("LLM_API_KEY", "").strip(),
        "base_url": os.getenv("LLM_BASE_URL", "").strip(),
    }


def _strip_fences(text: str) -> str:
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n```\s*$", text, re.DOTALL)
    return m.group(1) if m else text


def _parse_json(text: str):
    cleaned = _strip_fences(text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


async def callLLM(system: str, user: str) -> dict:
    """
    Dispatch a chat completion to the configured provider and return the parsed JSON body.
    Retries once with a stricter prompt on invalid JSON.
    Temperature is always 0.
    """
    cfg = _get_config()
    provider = cfg["provider"]
    if not provider:
        raise ValueError("LLM_PROVIDER is not set in environment.")
    if not cfg["model"]:
        raise ValueError("LLM_MODEL is not set in environment.")
    if not cfg["api_key"]:
        raise ValueError("LLM_API_KEY is not set in environment.")

    attempts = [{"system": system, "user": user}]
    attempts.append({
        "system": system,
        "user": user + "\n\nReturn valid JSON only. No prose, no markdown fences."
    })

    last_raw = ""
    for attempt in attempts:
        try:
            last_raw = await _call_provider(cfg, attempt["system"], attempt["user"])
        except Exception as exc:
            raise ValueError(f"LLM request failed ({provider}): {exc}") from exc

        parsed = _parse_json(last_raw)
        if parsed is not None:
            return parsed

    raise ValueError(
        "LLM returned invalid JSON on both attempts. "
        "Raw response: " + repr(last_raw[:500])
    )


async def _call_provider(cfg: dict, system: str, user: str) -> str:
    provider = cfg["provider"]
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if provider == "anthropic":
            return await _call_anthropic(client, cfg, system, user)
        elif provider in ("openai", "openai-compatible", "openrouter"):
            return await _call_openai_compatible(client, cfg, system, user)
        elif provider == "gemini":
            return await _call_gemini(client, cfg, system, user)
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: '{provider}'. Use anthropic | openai | gemini | openai-compatible | openrouter")


async def _call_anthropic(client: httpx.AsyncClient, cfg: dict, system: str, user: str) -> str:
    resp = await client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": cfg["api_key"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": cfg["model"],
            "max_tokens": 4096,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    parts = data.get("content", [])
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")


async def _call_openai_compatible(client: httpx.AsyncClient, cfg: dict, system: str, user: str) -> str:
    provider = cfg["provider"]
    if provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
    else:
        base_url = cfg["base_url"] or "https://api.openai.com/v1"
    base_url = base_url.rstrip("/")
    payload = {
        "model": cfg["model"],
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if provider != "openrouter":
        payload["response_format"] = {"type": "json_object"}
    resp = await client.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    if resp.status_code != 200:
        raise ValueError(f"HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    if "error" in data:
        raise ValueError(f"Provider error: {data['error']}")
    choices = data.get("choices")
    if not choices or not isinstance(choices, list) or not choices[0].get("message", {}).get("content"):
        raise ValueError(f"Unexpected response shape: {data}")
    return choices[0]["message"]["content"]


async def _call_gemini(client: httpx.AsyncClient, cfg: dict, system: str, user: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent"
        f"?key={cfg['api_key']}"
    )
    resp = await client.post(
        url,
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]
