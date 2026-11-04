"""Roteia transport for ai_work_delegate (HML only).

Fail-closed by construction: without an API key, an approved Claude model id and a
tariff, no request is built and nothing leaves the process.

Rules enforced here:
* exactly one POST per delegated call, never retried;
* redirects are not followed, so the Bearer token cannot leave api.roteia.ai;
* the worst-case cost of the call (input upper bound + max output tokens, at the
  configured tariff) must fit inside the amount reserved in the ledger. The check
  runs BEFORE the reservation (see ai_work_delegate.ai_work_delegate);
* the API key never appears in results, errors or repr().

The endpoint, Bearer auth and Chat Completions payload follow the contract reported
for the Roteia gateway. Model id, tariff and the evidence used to reconcile real
charges are NOT confirmed yet and are therefore configuration, not defaults.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from ai_work_delegate import DelegateBlocked, DelegateRequest

DEFAULT_URL = "https://api.roteia.ai/v1/chat/completions"
APPROVED_HOST = "api.roteia.ai"
# provider/model, e.g. "<provider>/<claude-model>"; the exact Claude id is configuration.
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*$")
DEFAULT_MAX_OUTPUT_TOKENS = 1024
MAX_OUTPUT_TOKENS_CEILING = 4096
# Chat template/system overhead allowance added on top of the prompt upper bound.
PROMPT_OVERHEAD_TOKENS = 64
TIMEOUT_SECONDS = 120.0
MILLION = Decimal(1_000_000)


class RoteiaHttpError(RuntimeError):
    """Provider answered with a non-200 status. Message carries only the status code."""


@dataclass(frozen=True)
class RoteiaConfig:
    api_key: str = field(repr=False)
    url: str
    model_id: str
    input_cents_per_mtok: Decimal
    output_cents_per_mtok: Decimal
    max_output_tokens: int


def _positive_decimal(raw: str | None) -> Decimal | None:
    try:
        value = Decimal((raw or "").strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() and value > 0 else None


def inspect_config(env: Mapping[str, str] | None = None) -> tuple[RoteiaConfig | None, list[str]]:
    """Return (config, problems). Problems are stable codes, never values."""
    env = os.environ if env is None else env
    problems: list[str] = []

    api_key = (env.get("ROTEIA_API_KEY") or "").strip()
    if not api_key:
        problems.append("roteia_api_key_missing")

    url = (env.get("ROTEIA_API_URL") or DEFAULT_URL).strip()
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != APPROVED_HOST
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        problems.append("roteia_url_not_approved")

    model_id = (env.get("ROTEIA_MODEL_ID") or "").strip()
    if not MODEL_ID_RE.match(model_id) or "claude" not in model_id.lower():
        problems.append("roteia_model_not_configured")

    input_price = _positive_decimal(env.get("ROTEIA_PRICE_INPUT_CENTS_PER_MTOK"))
    output_price = _positive_decimal(env.get("ROTEIA_PRICE_OUTPUT_CENTS_PER_MTOK"))
    if input_price is None or output_price is None:
        problems.append("roteia_tariff_not_configured")

    raw_tokens = (env.get("ROTEIA_MAX_OUTPUT_TOKENS") or "").strip()
    max_output = DEFAULT_MAX_OUTPUT_TOKENS
    if raw_tokens:
        try:
            max_output = int(raw_tokens)
        except ValueError:
            max_output = 0
        if not 1 <= max_output <= MAX_OUTPUT_TOKENS_CEILING:
            problems.append("roteia_max_output_tokens_invalid")

    if problems:
        return None, problems
    assert input_price is not None and output_price is not None
    return RoteiaConfig(api_key, url, model_id, input_price, output_price, max_output), []


def load_config(env: Mapping[str, str] | None = None) -> RoteiaConfig:
    config, problems = inspect_config(env)
    if config is None:
        raise DelegateBlocked(problems[0])
    return config


def worst_case_cents(config: RoteiaConfig, prompt: str) -> int:
    """Upper bound of the call cost in BRL cents (rounded up, never below 1).

    Assumes a token is never shorter than one byte, so the UTF-8 byte length bounds
    the input token count; the output is bounded by max_tokens.
    """
    input_tokens = len(prompt.encode("utf-8")) + PROMPT_OVERHEAD_TOKENS
    cost = (
        Decimal(input_tokens) * config.input_cents_per_mtok
        + Decimal(config.max_output_tokens) * config.output_cents_per_mtok
    ) / MILLION
    return max(1, int(cost.to_integral_value(rounding=ROUND_CEILING)))


def _default_client_factory() -> Any:
    import httpx  # imported lazily so offline tests do not need httpx

    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)


class RoteiaTransport:
    def __init__(self, config: RoteiaConfig, client_factory: Callable[[], Any] | None = None):
        self._config = config
        self._client_factory = client_factory or _default_client_factory

    def check(self, request: DelegateRequest) -> None:
        """Pre-flight: runs before the ledger reservation, so a refusal costs nothing."""
        if worst_case_cents(self._config, request.prompt) > request.max_charge_cents:
            raise DelegateBlocked("cost_bound_exceeds_reservation")

    def __call__(self, request: DelegateRequest) -> dict[str, Any]:
        self.check(request)
        config = self._config
        body = {
            "model": config.model_id,
            "messages": [{"role": "user", "content": request.prompt}],
            "max_tokens": config.max_output_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        with self._client_factory() as client:
            response = client.post(config.url, headers=headers, json=body)
        if response.status_code != 200:
            raise RoteiaHttpError(f"status_{response.status_code}")
        data = response.json()
        choice = data["choices"][0]
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        return {
            "text": choice["message"]["content"],
            "finish_reason": choice.get("finish_reason"),
            "response_id": data.get("id"),
            "model": data.get("model"),
            "usage": usage,
            "cost_bound_cents": worst_case_cents(config, request.prompt),
            "estimated_cost_cents": self._estimate(usage),
        }

    def _estimate(self, usage: dict[str, Any] | None) -> str | None:
        """Estimate from reported usage at the configured tariff. NOT billing evidence."""
        if not usage:
            return None
        prompt_tokens, completion_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
        if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
            return None
        cost = (
            Decimal(prompt_tokens) * self._config.input_cents_per_mtok
            + Decimal(completion_tokens) * self._config.output_cents_per_mtok
        ) / MILLION
        return str(cost.quantize(Decimal("0.0001")))
