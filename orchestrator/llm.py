"""Google AI Studio's documented OpenAI-compatible function-calling endpoint."""

import hashlib
import json
import os
import re
from pathlib import Path
import time
import requests


class LLMClient:
    _next_request_at = 0.0

    def __init__(self, cache_dir=".cache/llm", trace=None):
        self.key = os.environ.get("GEMINI_API_KEY")
        if not self.key:
            raise ValueError("Set GEMINI_API_KEY to your Google AI Studio API key")
        self.model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.min_interval = max(0.0, float(os.environ.get("GEMINI_MIN_INTERVAL", "4.2")))
        self.url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.trace = trace or (lambda event: None)

    def complete(self, messages, tools):
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "required",
            "temperature": 0,
        }
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        path = self.cache / (digest + ".json")
        self.trace({"event": "llm_request", "request_id": digest, "request": body})
        if path.exists():
            response = json.loads(path.read_text())
            self.trace(
                {
                    "event": "llm_response",
                    "request_id": digest,
                    "cached": True,
                    "response": response,
                }
            )
            return response["choices"][0]["message"]
        for attempt in range(4):
            delay = (
                max(0.0, type(self)._next_request_at - time.monotonic())
                if self.min_interval
                else 0.0
            )
            if delay:
                time.sleep(delay)
            type(self)._next_request_at = time.monotonic() + self.min_interval
            try:
                response = requests.post(
                    self.url,
                    headers={"Authorization": "Bearer " + self.key},
                    json=body,
                    timeout=(15, 90),
                )
            except requests.RequestException as exc:
                self.trace(
                    {
                        "event": "llm_error",
                        "request_id": digest,
                        "attempt": attempt,
                        "error": type(exc).__name__,
                    }
                )
                if attempt == 3:
                    raise RuntimeError("LLM network request failed") from None
                time.sleep(min(2**attempt, 8))
                continue
            provider_error = ""
            if not response.ok:
                try:
                    payload = response.json()
                    items = payload if isinstance(payload, list) else [payload]
                    error_messages = []
                    for item in items:
                        detail = item.get("error", item) if isinstance(item, dict) else item
                        error_messages.append(
                            str(
                                detail.get("message", detail)
                                if isinstance(detail, dict)
                                else detail
                            )
                        )
                    provider_error = "; ".join(error_messages).replace(self.key, "[REDACTED]")[
                        :1000
                    ]
                except (ValueError, AttributeError):
                    provider_error = "Provider returned a non-JSON error"
            if response.status_code in (429, 500, 502, 503, 504):
                self.trace(
                    {
                        "event": "llm_error",
                        "request_id": digest,
                        "attempt": attempt,
                        "http_status": response.status_code,
                        "provider_error": provider_error,
                    }
                )
                if attempt == 3:
                    raise RuntimeError(
                        f'LLM HTTP {response.status_code}; {provider_error or "retry later"}'
                    )
                retry_hint = re.search(r"retry in ([0-9.]+)s", provider_error, re.IGNORECASE)
                hinted_delay = float(retry_hint.group(1)) + 1 if retry_hint else 2 ** (attempt + 1)
                try:
                    delay = float(response.headers.get("Retry-After", hinted_delay))
                except ValueError:
                    delay = hinted_delay
                time.sleep(min(60.0, max(0.0, delay)))
                continue
            if not response.ok:
                self.trace(
                    {
                        "event": "llm_error",
                        "request_id": digest,
                        "http_status": response.status_code,
                        "provider_error": provider_error,
                    }
                )
                raise RuntimeError(
                    f'LLM HTTP {response.status_code}; {provider_error or "check key, model access and free-tier quota"}'
                )
            data = response.json()
            if not data.get("choices"):
                raise ValueError("LLM response has no choices")
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False))
            temporary.replace(path)
            self.trace(
                {"event": "llm_response", "request_id": digest, "cached": False, "response": data}
            )
            return data["choices"][0]["message"]
        raise RuntimeError("LLM retries exhausted")
