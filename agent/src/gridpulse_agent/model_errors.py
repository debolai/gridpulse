"""Turn model-provider failures into a clear "assistant unavailable" response instead of a 500.

Providers raise different exception types (botocore ClientError for Bedrock, APIStatusError
subclasses for OpenAI and Anthropic), so classification reads their common shapes rather than
importing every SDK. Plain httpx errors are not classified here: the semantic API client raises
them too, and the API tells the two apart by URL.
"""

from dataclasses import dataclass
from typing import Literal

Reason = Literal["throttled", "access_denied", "unreachable"]

_MESSAGES: dict[Reason, str] = {
    "throttled": "The language model is rate-limited or out of quota right now. "
    "Try again in a minute.",
    "access_denied": "The assistant cannot use its language model (access or credentials "
    "problem on the server side). The metrics API is unaffected.",
    "unreachable": "The language model did not respond. Try again shortly.",
}

# Bedrock (botocore) error codes.
_THROTTLED_CODES = {"ThrottlingException", "ServiceQuotaExceededException", "TooManyRequests"}
_ACCESS_CODES = {
    "AccessDeniedException",
    "UnrecognizedClientException",
    "ExpiredTokenException",
    "ResourceNotFoundException",  # model not enabled for the account
}
_UNREACHABLE_CODES = {
    "ModelNotReadyException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
}
# Connection failures: openai/anthropic SDKs, and botocore (Bedrock).
_UNREACHABLE_CLASSES = {
    "APIConnectionError",
    "APITimeoutError",
    "EndpointConnectionError",
    "ReadTimeoutError",
    "ConnectTimeoutError",
}


@dataclass(frozen=True)
class ModelUnavailable:
    reason: Reason
    provider_error: str  # exception class and code, for logs and the response; no secrets

    @property
    def message(self) -> str:
        return _MESSAGES[self.reason]

    @property
    def retry_after_s(self) -> int | None:
        return 60 if self.reason == "throttled" else 30 if self.reason == "unreachable" else None


def classify(exc: BaseException) -> ModelUnavailable | None:
    """Return why the model is unavailable, or None if `exc` is not a provider failure."""
    name = type(exc).__name__

    code = getattr(exc, "response", None)
    if isinstance(code, dict):  # botocore ClientError
        code = code.get("Error", {}).get("Code", "")
        reason = (
            "throttled"
            if code in _THROTTLED_CODES
            else "access_denied"
            if code in _ACCESS_CODES
            else "unreachable"
            if code in _UNREACHABLE_CODES
            else None
        )
        return ModelUnavailable(reason, f"{name}: {code}") if reason else None

    status = getattr(exc, "status_code", None)
    if isinstance(status, int):  # openai / anthropic APIStatusError
        if status == 429:
            return ModelUnavailable("throttled", f"{name}: {status}")
        if status in (401, 403, 404):
            return ModelUnavailable("access_denied", f"{name}: {status}")
        if status >= 500:
            return ModelUnavailable("unreachable", f"{name}: {status}")
        return None

    if name in _UNREACHABLE_CLASSES:
        return ModelUnavailable("unreachable", name)
    return None
