"""Minimal LLM client for the profiler.

The runtime is decided at kickoff and read from the environment — never
hard-coded (AGENTS.md §2):

* ``MODEL_RUNTIME=api``    → any OpenAI-compatible ``/chat/completions`` endpoint
* ``MODEL_RUNTIME=ollama`` → a local Ollama server

Both paths use ``httpx``, which is already a pinned dependency. If no runtime is
configured, ``default_client()`` returns ``None`` and the profiler falls back to
the deterministic extractor, so the demo never depends on the network.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

from . import config

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """The model could not be reached or returned an unusable response."""


class ChatClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class LLMClient:
    def __init__(
        self,
        runtime: str,
        model: str,
        api_key: str = "",
        base_url: str = "",
        ollama_host: str = "",
        post: Callable[..., Any] | None = None,
    ) -> None:
        self.runtime = runtime
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or config.MODEL_BASE_URL).rstrip("/")
        self.ollama_host = (ollama_host or config.OLLAMA_HOST).rstrip("/")
        self._post = post

    def complete(self, system: str, user: str) -> str:
        if self.runtime == "api":
            return self._complete_api(system, user)
        if self.runtime == "ollama":
            return self._complete_ollama(system, user)
        raise LLMUnavailable(f"unknown MODEL_RUNTIME: {self.runtime!r}")

    # -- transports --------------------------------------------------------

    def _http_post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> Any:
        if self._post is not None:
            return self._post(url, json=json, headers=headers)
        import httpx  # local import: keeps this module importable without httpx

        try:
            response = httpx.post(
                url, json=json, headers=headers, timeout=config.LLM_TIMEOUT_SECONDS
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailable(f"{url} failed: {exc}") from exc
        return response

    def _complete_api(self, system: str, user: str) -> str:
        if not self.api_key:
            raise LLMUnavailable("MODEL_API_KEY is empty")
        response = self._http_post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": config.LLM_TEMPERATURE,
                "max_tokens": config.LLM_MAX_TOKENS,
            },
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUnavailable(f"unexpected API response: {exc}") from exc

    def _complete_ollama(self, system: str, user: str) -> str:
        response = self._http_post(
            f"{self.ollama_host}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "options": {"temperature": config.LLM_TEMPERATURE},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            headers={"Content-Type": "application/json"},
        )
        try:
            return response.json()["message"]["content"]
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMUnavailable(f"unexpected Ollama response: {exc}") from exc


def default_client() -> LLMClient | None:
    """Build a client from the environment, or ``None`` when no runtime is set."""
    runtime = config.MODEL_RUNTIME
    if runtime not in {"api", "ollama"}:
        logger.info("MODEL_RUNTIME is %r; using the deterministic extractor.", runtime or "")
        return None
    if not config.MODEL_NAME:
        logger.warning("MODEL_RUNTIME=%s but MODEL_NAME is empty; using the fallback.", runtime)
        return None
    if runtime == "api" and not config.MODEL_API_KEY:
        logger.warning("MODEL_RUNTIME=api but MODEL_API_KEY is empty; using the fallback.")
        return None
    return LLMClient(
        runtime=runtime,
        model=config.MODEL_NAME,
        api_key=config.MODEL_API_KEY,
        base_url=config.MODEL_BASE_URL,
        ollama_host=config.OLLAMA_HOST,
    )
