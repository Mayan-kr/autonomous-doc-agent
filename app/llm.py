"""Groq LLM client with retry + fallback.

This is the reliability layer. Every LLM call in the agent goes through
`chat()`, which:
  1. Retries transient failures (rate limits, network blips) with backoff.
  2. Falls back to a smaller/faster model if the primary keeps failing.

That way a single flaky API call never crashes the whole agent run.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_API_KEY = os.getenv("GROQ_API_KEY")
PRIMARY_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant")

if not _API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
    )

_client = Groq(api_key=_API_KEY)


class LLMError(RuntimeError):
    """Raised when every model + retry has been exhausted."""


def chat(
    messages: List[Dict[str, str]],
    *,
    json_mode: bool = False,
    temperature: float = 0.4,
    max_retries: int = 3,
) -> str:
    """Call the LLM and return the assistant's text.

    Tries the primary model with `max_retries` attempts (exponential backoff),
    then repeats the whole loop on the fallback model before giving up.
    """
    models = [PRIMARY_MODEL, FALLBACK_MODEL]
    last_error: Optional[Exception] = None

    for model in models:
        for attempt in range(1, max_retries + 1):
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                completion = _client.chat.completions.create(**kwargs)
                content = completion.choices[0].message.content
                if content:
                    return content
                raise LLMError("Empty response from model.")

            except Exception as exc:  # noqa: BLE001 - we deliberately catch broadly
                last_error = exc
                wait = 2 ** (attempt - 1)  # 1s, 2s, 4s
                print(
                    f"[llm] {model} attempt {attempt}/{max_retries} failed: {exc} "
                    f"-> retrying in {wait}s"
                )
                time.sleep(wait)

        print(f"[llm] giving up on {model}, trying fallback model next.")

    raise LLMError(f"All models failed. Last error: {last_error}")


def chat_json(messages: List[Dict[str, str]], **kwargs: Any) -> Dict[str, Any]:
    """Like `chat`, but parses the reply as JSON.

    Guarantees valid JSON is returned to the caller: if the model emits stray
    prose around the JSON, we salvage the object between the first '{' and last '}'.
    """
    raw = chat(messages, json_mode=True, **kwargs)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            return json.loads(raw[start : end + 1])
        raise LLMError(f"Model did not return valid JSON:\n{raw}")
