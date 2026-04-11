"""
LLM Client Wrapper
Unified OpenAI format API calls
Supports Ollama num_ctx parameter to prevent prompt truncation
"""

import json
import os
import re
import random
import time
from typing import Optional, Dict, Any, List
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError, RateLimitError

from ..config import Config


class LLMClient:
    """LLM Client"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 300.0
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("LLM_API_KEY not configured")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
        )

        self._openrouter_http_referer = Config.OPENROUTER_HTTP_REFERER
        self._openrouter_x_title = Config.OPENROUTER_X_TITLE
        self._benchmark_mode = Config.BENCHMARK_MODE
        self._benchmark_temperature = Config.BENCHMARK_TEMPERATURE
        self._benchmark_seed = Config.BENCHMARK_SEED
        if self._benchmark_mode:
            self._benchmark_temperature = self._coerce_float(
                Config.BENCHMARK_TEMPERATURE,
                "BENCHMARK_TEMPERATURE",
            )
            self._benchmark_seed = self._coerce_int(
                Config.BENCHMARK_SEED,
                "BENCHMARK_SEED",
            )
        self._retry_max_retries = self._coerce_non_negative_int(
            Config.LLM_RETRY_MAX_RETRIES,
            "LLM_RETRY_MAX_RETRIES",
        )
        self._retry_initial_delay = self._coerce_non_negative_float(
            Config.LLM_RETRY_INITIAL_DELAY,
            "LLM_RETRY_INITIAL_DELAY",
        )
        self._retry_max_delay = self._coerce_non_negative_float(
            Config.LLM_RETRY_MAX_DELAY,
            "LLM_RETRY_MAX_DELAY",
        )
        self._retry_jitter_max = self._coerce_non_negative_float(
            Config.LLM_RETRY_JITTER_MAX,
            "LLM_RETRY_JITTER_MAX",
        )

        # Ollama context window size — prevents prompt truncation.
        # Read from env OLLAMA_NUM_CTX, default 8192 (Ollama default is only 2048).
        self._num_ctx = int(os.environ.get('OLLAMA_NUM_CTX', '8192'))

    def _is_ollama(self) -> bool:
        """Check if we're talking to an Ollama server."""
        return '11434' in (self.base_url or '')

    @staticmethod
    def _extract_error_code(error: Exception) -> Optional[str]:
        body = getattr(error, 'body', None)
        if isinstance(body, dict):
            detail = body.get('error', body)
            if isinstance(detail, dict):
                code = detail.get('code') or detail.get('type')
                if isinstance(code, str):
                    return code.lower()
        return None

    @staticmethod
    def _coerce_non_negative_int(value: Any, name: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} must be an integer >= 0") from error
        return max(0, parsed)

    @staticmethod
    def _coerce_non_negative_float(value: Any, name: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} must be a number >= 0") from error
        return max(0.0, parsed)

    @staticmethod
    def _coerce_int(value: Any, name: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} must be an integer") from error

    @staticmethod
    def _coerce_float(value: Any, name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} must be a number") from error

    def _is_retryable_error(self, error: Exception) -> bool:
        if isinstance(error, (APIConnectionError, APITimeoutError, TimeoutError, ConnectionError)):
            return True

        error_code = self._extract_error_code(error)
        quota_codes = {'insufficient_quota', 'quota_exceeded'}
        if isinstance(error, RateLimitError):
            return error_code not in quota_codes

        if isinstance(error, APIStatusError):
            status_code = getattr(error, 'status_code', None)
            if status_code == 429:
                return error_code not in quota_codes
            return isinstance(status_code, int) and 500 <= status_code < 600

        return False

    def _chat_create_with_retry(self, kwargs: Dict[str, Any]):
        delay = max(0.0, self._retry_initial_delay)

        for attempt in range(self._retry_max_retries + 1):
            try:
                return self.client.chat.completions.create(**kwargs)
            except Exception as error:
                should_retry = self._is_retryable_error(error)
                if attempt >= self._retry_max_retries or not should_retry:
                    raise

                current_delay = min(delay, self._retry_max_delay)
                sleep_delay = current_delay
                if self._retry_jitter_max > 0:
                    sleep_delay += random.uniform(0, self._retry_jitter_max)

                time.sleep(sleep_delay)
                delay = min(delay * 2 if delay > 0 else 0.0, self._retry_max_delay)

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        Send chat request

        Args:
            messages: Message list
            temperature: Temperature parameter
            max_tokens: Max token count
            response_format: Response format (e.g., JSON mode)

        Returns:
            Model response text
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": self._benchmark_temperature if self._benchmark_mode else temperature,
            "max_tokens": max_tokens,
        }

        if self._benchmark_mode:
            kwargs["seed"] = self._benchmark_seed

        if response_format:
            kwargs["response_format"] = response_format

        extra_headers = {}
        if self._openrouter_http_referer:
            extra_headers["HTTP-Referer"] = self._openrouter_http_referer
        if self._openrouter_x_title:
            extra_headers["X-Title"] = self._openrouter_x_title
        if extra_headers:
            kwargs["extra_headers"] = extra_headers

        # For Ollama: pass num_ctx via extra_body to prevent prompt truncation
        if self._is_ollama() and self._num_ctx:
            kwargs["extra_body"] = {
                "options": {"num_ctx": self._num_ctx}
            }

        response = self._chat_create_with_retry(kwargs)
        content = response.choices[0].message.content
        # Some models (like MiniMax M2.5) include <think>thinking content in response, need to remove
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        Send chat request and return JSON

        Args:
            messages: Message list
            temperature: Temperature parameter
            max_tokens: Max token count

        Returns:
            Parsed JSON object
        """
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"}
        )
        # Clean markdown code block markers
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON format from LLM: {cleaned_response}")
