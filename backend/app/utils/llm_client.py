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
import logging
from typing import Optional, Dict, Any, List
from openai import OpenAI, APIConnectionError, APITimeoutError, APIStatusError, RateLimitError

from ..config import Config

logger = logging.getLogger("mirofish.llm_client")
ENFORCED_BENCHMARK_TEMPERATURE = 0.0
ENFORCED_BENCHMARK_SEED = 42


class LLMClient:
    """LLM Client"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None
    ):
        self.api_key = api_key or os.environ.get('LLM_API_KEY') or Config.LLM_API_KEY
        self.base_url = base_url or os.environ.get('LLM_BASE_URL') or Config.LLM_BASE_URL
        self.model = model or os.environ.get('LLM_MODEL_NAME') or Config.LLM_MODEL_NAME
        resolved_timeout = float(timeout if timeout is not None else Config.LLM_TIMEOUT_SECONDS)

        # Fallback to OPENAI_* variables if LLM_* are not set (for compatibility with OASIS/CAMEL-AI environment setup)
        if not self.api_key:
            self.api_key = os.environ.get('OPENAI_API_KEY')
        if not self.base_url or self.base_url == 'http://localhost:11434/v1':
            env_base = os.environ.get('OPENAI_API_BASE_URL')
            if env_base:
                self.base_url = env_base

        if not self.api_key:
            raise ValueError("LLM_API_KEY not configured")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=resolved_timeout,
        )

        self._openrouter_http_referer = Config.OPENROUTER_HTTP_REFERER
        self._openrouter_x_title = Config.OPENROUTER_X_TITLE
        self._benchmark_mode = Config.BENCHMARK_MODE
        self._benchmark_temperature = Config.BENCHMARK_TEMPERATURE
        self._benchmark_seed = Config.BENCHMARK_SEED
        if self._benchmark_mode:
            self._warn_if_conflicting_benchmark_config()
            self._benchmark_temperature = ENFORCED_BENCHMARK_TEMPERATURE
            self._benchmark_seed = ENFORCED_BENCHMARK_SEED
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
        self._rate_limit_reset_min_wait = 0.1
        self._rate_limit_reset_max_wait = 300.0

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

    @staticmethod
    def _try_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _try_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _warn_if_conflicting_benchmark_config(self) -> None:
        configured_temperature = self._try_float(Config.BENCHMARK_TEMPERATURE)
        configured_seed = self._try_int(Config.BENCHMARK_SEED)

        if configured_temperature != ENFORCED_BENCHMARK_TEMPERATURE:
            logger.warning(
                "BENCHMARK_MODE enabled: overriding BENCHMARK_TEMPERATURE=%r with enforced value %.1f",
                Config.BENCHMARK_TEMPERATURE,
                ENFORCED_BENCHMARK_TEMPERATURE,
            )
        if configured_seed != ENFORCED_BENCHMARK_SEED:
            logger.warning(
                "BENCHMARK_MODE enabled: overriding BENCHMARK_SEED=%r with enforced value %d",
                Config.BENCHMARK_SEED,
                ENFORCED_BENCHMARK_SEED,
            )

    @staticmethod
    def _is_quota_error_code(error_code: Optional[str]) -> bool:
        return error_code in {'insufficient_quota', 'quota_exceeded'}

    @staticmethod
    def _extract_rate_limit_reset_wait_seconds(error: Exception) -> Optional[float]:
        body = getattr(error, 'body', None)
        if not isinstance(body, dict):
            return None

        detail = body.get('error', body)
        if not isinstance(detail, dict):
            return None

        metadata = detail.get('metadata')
        if not isinstance(metadata, dict):
            return None

        headers = metadata.get('headers')
        if not isinstance(headers, dict):
            return None

        raw_reset = None
        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == 'x-ratelimit-reset':
                raw_reset = value
                break
        if raw_reset is None:
            return None

        try:
            reset_epoch = float(raw_reset)
        except (TypeError, ValueError):
            return None

        reset_epoch_seconds = reset_epoch / 1000.0 if reset_epoch > 100000000000 else reset_epoch
        return max(0.0, reset_epoch_seconds - time.time())

    def _is_rate_limit_error(self, error: Exception) -> bool:
        error_code = self._extract_error_code(error)
        if self._is_quota_error_code(error_code):
            return False

        if isinstance(error, RateLimitError):
            return True

        if isinstance(error, APIStatusError):
            return getattr(error, 'status_code', None) == 429

        return False

    def _normalize_rate_limit_reset_wait_seconds(self, wait_seconds: float) -> float:
        if wait_seconds <= 0:
            return self._rate_limit_reset_min_wait
        return min(wait_seconds, self._rate_limit_reset_max_wait)

    def _compute_retry_sleep_delay(self, delay: float) -> tuple[float, float]:
        current_delay = min(delay, self._retry_max_delay)
        sleep_delay = current_delay
        if self._retry_jitter_max > 0:
            sleep_delay += random.uniform(0, self._retry_jitter_max)
        next_delay = min(delay * 2 if delay > 0 else 0.0, self._retry_max_delay)
        return sleep_delay, next_delay

    def _is_retryable_error(self, error: Exception) -> bool:
        if isinstance(error, (APIConnectionError, APITimeoutError, TimeoutError, ConnectionError)):
            return True

        error_code = self._extract_error_code(error)
        if isinstance(error, RateLimitError):
            return not self._is_quota_error_code(error_code)

        if isinstance(error, APIStatusError):
            status_code = getattr(error, 'status_code', None)
            if status_code == 429:
                return not self._is_quota_error_code(error_code)
            return isinstance(status_code, int) and 500 <= status_code < 600

        return False

    @staticmethod
    def _scan_json_structure(payload: str) -> tuple[list[str], bool, bool]:
        stack: list[str] = []
        in_string = False
        is_escaped = False
        has_mismatched_closer = False

        for char in payload:
            if in_string:
                if is_escaped:
                    is_escaped = False
                    continue
                if char == '\\':
                    is_escaped = True
                    continue
                if char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char in {'{', '['}:
                stack.append(char)
            elif char == '}':
                if not stack or stack[-1] != '{':
                    has_mismatched_closer = True
                    break
                stack.pop()
            elif char == ']':
                if not stack or stack[-1] != '[':
                    has_mismatched_closer = True
                    break
                stack.pop()

        return stack, in_string, has_mismatched_closer

    def _looks_like_truncated_json(self, payload: str, _decode_error: json.JSONDecodeError) -> bool:
        stripped_payload = payload.rstrip()
        if not stripped_payload:
            return False

        stack, in_string, has_mismatched_closer = self._scan_json_structure(stripped_payload)
        if has_mismatched_closer:
            return False

        return in_string or bool(stack)

    def _repair_truncated_json(self, payload: str) -> Optional[str]:
        stripped_payload = payload.rstrip()
        stack, in_string, has_mismatched_closer = self._scan_json_structure(stripped_payload)
        if has_mismatched_closer:
            return None

        repair_suffix = []
        if in_string:
            repair_suffix.append('"')
        for opener in reversed(stack):
            repair_suffix.append('}' if opener == '{' else ']')

        if not repair_suffix:
            return None

        return stripped_payload + ''.join(repair_suffix)

    def _chat_create_with_retry(self, kwargs: Dict[str, Any], enforce_benchmark_params: bool = True):
        request_kwargs = dict(kwargs)
        if self._benchmark_mode and enforce_benchmark_params:
            requested_temperature = request_kwargs.get("temperature")
            parsed_temperature = self._try_float(requested_temperature)
            if parsed_temperature != ENFORCED_BENCHMARK_TEMPERATURE:
                logger.warning(
                    "BENCHMARK_MODE enabled: overriding requested temperature=%r with enforced value %.1f",
                    requested_temperature,
                    ENFORCED_BENCHMARK_TEMPERATURE,
                )

            requested_seed = request_kwargs.get("seed")
            parsed_seed = self._try_int(requested_seed)
            if requested_seed is not None and parsed_seed != ENFORCED_BENCHMARK_SEED:
                logger.warning(
                    "BENCHMARK_MODE enabled: overriding requested seed=%r with enforced value %d",
                    requested_seed,
                    ENFORCED_BENCHMARK_SEED,
                )

            request_kwargs["temperature"] = ENFORCED_BENCHMARK_TEMPERATURE
            request_kwargs["seed"] = ENFORCED_BENCHMARK_SEED

        delay = max(0.0, self._retry_initial_delay)
        attempt = 0

        while True:
            try:
                return self.client.chat.completions.create(**request_kwargs)
            except Exception as error:
                if self._is_rate_limit_error(error):
                    reset_wait = self._extract_rate_limit_reset_wait_seconds(error)
                    if reset_wait is None:
                        sleep_delay, delay = self._compute_retry_sleep_delay(delay)
                    else:
                        sleep_delay = self._normalize_rate_limit_reset_wait_seconds(reset_wait)
                    time.sleep(sleep_delay)
                    continue

                should_retry = self._is_retryable_error(error)
                if attempt >= self._retry_max_retries or not should_retry:
                    raise

                sleep_delay, delay = self._compute_retry_sleep_delay(delay)
                time.sleep(sleep_delay)
                attempt += 1

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: int = 2048,
        response_format: Optional[Dict] = None,
        enforce_benchmark_params: bool = True
    ) -> str:
        """
        Send chat request

        Args:
            messages: Message list
            temperature: Temperature parameter
            max_tokens: Max token count
            response_format: Response format (e.g., JSON mode)
            enforce_benchmark_params: Whether to enforce benchmark mode overrides

        Returns:
            Model response text
        """
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else 0.7,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format
            # CRITICAL FIX: Explicitly disable streaming when JSON Schema/Object mode is used.
            # Some providers (e.g. Cloudflare via OpenRouter) reject JSON schemas with stream=True.
            kwargs["stream"] = False

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

        response = self._chat_create_with_retry(kwargs, enforce_benchmark_params=enforce_benchmark_params)
        
        # Defensive check for OpenRouter/Provider failures that return null choices
        if not hasattr(response, 'choices') or not response.choices:
            error_msg = f"LLM returned no choices. Model: {self.model}. Response: {response}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        content = response.choices[0].message.content
        # Some models (like MiniMax M2.5) include <think>thinking content in response, need to remove
        content = re.sub(r'<think>[\s\S]*?</think>', '', content).strip()
        return content

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: int = 2048,
        repair_truncated_json: bool = False,
        json_schema: Optional[Dict[str, Any]] = None,
        enforce_benchmark_params: bool = True
    ) -> Dict[str, Any]:
        """
        Send chat request and return JSON, optionally with a strict schema.
        """
        response_format = {"type": "json_object"}
        use_schema = False
        if json_schema:
            response_format = {
                "type": "json_schema",
                "json_schema": json_schema
            }
            use_schema = True

        try:
            response = self.chat(
                messages=messages,
                temperature=0.3 if temperature is None else temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                enforce_benchmark_params=enforce_benchmark_params
            )
        except APIStatusError as error:
            # If the model does not support json_schema (Structured Outputs),
            # fall back to standard json_object mode.
            if use_schema and error.status_code == 400:
                logger.warning(
                    "Model %s does not support json_schema, falling back to json_object. Error: %s",
                    self.model,
                    error,
                )
                return self.chat_json(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    repair_truncated_json=repair_truncated_json,
                    json_schema=None,  # Fallback: disable schema
                    enforce_benchmark_params=enforce_benchmark_params
                )
            raise

        # Clean markdown code block markers
        cleaned_response = response.strip()
        cleaned_response = re.sub(r'^```(?:json)?\s*\n?', '', cleaned_response, flags=re.IGNORECASE)
        cleaned_response = re.sub(r'\n?```\s*$', '', cleaned_response)
        cleaned_response = cleaned_response.strip()

        try:
            return json.loads(cleaned_response)
        except json.JSONDecodeError as error:
            if repair_truncated_json and self._looks_like_truncated_json(cleaned_response, error):
                repaired_response = self._repair_truncated_json(cleaned_response)
                if repaired_response:
                    try:
                        return json.loads(repaired_response)
                    except json.JSONDecodeError:
                        pass
            raise ValueError(f"Invalid JSON format from LLM: {cleaned_response}")
