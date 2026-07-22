"""Permanent-provider-error classification and the audit circuit breaker.

Billing/credit exhaustion and auth failures are not transient: every retry
against the same account fails identically. :func:`classify_permanent_error`
turns the raw SDK error into a typed :class:`ProviderPermanentError`;
:class:`ProviderCircuitBreaker` is the shared latch the audit orchestrator trips
on the first one so the remaining LLM work short-circuits instead of burning
wall-clock on doomed calls (osoji issue #160).

Detection prefers structured type/code/status fields the SDKs expose. The one
place string matching is unavoidable is the anthropic billing 400: it shares
its status code (400) and error type (``invalid_request_error``) with ordinary
malformed requests, so the only reliable signal is the message. That matching
is scoped narrowly — a small set of billing-specific phrases, and only on
client (4xx) errors — so transient failures keep their existing retry path.
"""

from __future__ import annotations

from .types import ProviderPermanentError

# Billing-specific phrases. Deliberately narrow: each is a settled billing
# phrase that does not appear in transient or rate-limit error text.
_BILLING_MARKERS: tuple[str, ...] = (
    "credit balance",
    "too low to access",
    "purchase credits",
    "plan and billing",
    "billing details",
    "insufficient_quota",
    "insufficient funds",
)

# SDK exception type names that are always permanent regardless of status.
_AUTH_TYPE_NAMES: frozenset[str] = frozenset({
    "AuthenticationError",
    "PermissionDeniedError",
})


def _status_code(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def _error_code(exc: BaseException) -> str | None:
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("code"), str):
            return err["code"]
    return None


def _detail(exc: BaseException) -> str:
    """Cleanest single-line human detail available for the error."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str) and err["message"].strip():
            return err["message"].strip().splitlines()[0]
    message = getattr(exc, "message", None)
    if isinstance(message, str) and message.strip():
        return message.strip().splitlines()[0]
    text = str(exc).strip()
    return text.splitlines()[0] if text else exc.__class__.__name__


def _search_text(exc: BaseException) -> str:
    parts = [str(exc)]
    message = getattr(exc, "message", None)
    if isinstance(message, str):
        parts.append(message)
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            parts.append(err["message"])
    return " ".join(parts).lower()


def _provider_hint(exc: BaseException) -> str | None:
    module = (exc.__class__.__module__ or "").split(".")[0]
    if module in {"anthropic", "openai", "google"}:
        return module
    return None


def _message(exc: BaseException, kind: str) -> str:
    provider = _provider_hint(exc)
    prefix = f"{provider} " if provider else ""
    return (
        f"{prefix}permanent {kind} failure — remaining LLM calls will fail "
        f"identically: {_detail(exc)[:200]}"
    )


def classify_permanent_error(exc: BaseException) -> ProviderPermanentError | None:
    """Classify ``exc`` as a permanent provider failure, or ``None``.

    Returns a :class:`ProviderPermanentError` for billing/credit exhaustion and
    auth/permission failures (which every retry reproduces); returns ``None``
    for everything else — transient errors, malformed requests, rate limits —
    so their existing type and handling are preserved.
    """
    if isinstance(exc, ProviderPermanentError):
        return exc

    status = _status_code(exc)
    type_name = type(exc).__name__

    # Auth / permission: never transient.
    if status in (401, 403) or type_name in _AUTH_TYPE_NAMES:
        return ProviderPermanentError(
            _message(exc, "auth"),
            reason="auth",
            provider=_provider_hint(exc),
            status_code=status,
        )

    # Billing / quota exhaustion. Structured code first (openai), then the
    # narrow anthropic message markers — but only for client (4xx) errors so a
    # stray marker on a 5xx keeps its transient retry path.
    is_billing = _error_code(exc) == "insufficient_quota" or any(
        marker in _search_text(exc) for marker in _BILLING_MARKERS
    )
    if is_billing and (status is None or 400 <= status < 500):
        return ProviderPermanentError(
            _message(exc, "billing"),
            reason="billing",
            provider=_provider_hint(exc),
            status_code=status,
        )

    return None


class ProviderCircuitBreaker:
    """First-permanent-error latch shared by every phase of one audit run.

    Async use here is single-threaded and cooperative: ``trip`` and ``tripped``
    never ``await``, so the read-modify-write is atomic between suspension
    points — no lock is needed. First writer wins (idempotent): the recorded
    error is the one surfaced to the CLI as the run's cause of death.
    """

    def __init__(self) -> None:
        self._error: ProviderPermanentError | None = None

    @property
    def tripped(self) -> bool:
        return self._error is not None

    @property
    def error(self) -> ProviderPermanentError | None:
        return self._error

    def trip(self, error: ProviderPermanentError) -> None:
        if self._error is None:
            self._error = error
