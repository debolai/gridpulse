"""EIA API v2 client: sorted pagination, self-imposed rate limit, retries, completeness check."""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

from gridpulse_ingestion.eia.models import EIA_HOURLY_FORMAT
from gridpulse_ingestion.eia.routes import Route
from gridpulse_ingestion.ratelimit import TokenBucket

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class EIAAPIError(RuntimeError):
    """The API rejected the request (bad parameters, bad key). Not retried."""


class RetryableStatusError(RuntimeError):
    """Throttled (429) or server error (5xx). Carries only the status, never the keyed URL."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class IncompleteExtractError(RuntimeError):
    """Rows received do not match the `total` the API reported."""


@dataclass(frozen=True)
class Page:
    number: int
    offset: int
    total: int
    rows: list[dict]
    raw: bytes
    api_version: str | None
    warnings: list = field(default_factory=list)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, RetryableStatusError | httpx.TransportError)


def check_window(start: datetime, end: datetime) -> None:
    for name, ts in (("start", start), ("end", end)):
        if ts.tzinfo is None or ts.utcoffset() != timedelta(0):
            raise ValueError(f"{name} must be timezone-aware UTC, got {ts!r}")
        if (ts.minute, ts.second, ts.microsecond) != (0, 0, 0):
            raise ValueError(f"{name} must be on the hour, got {ts!r}")
    if end <= start:
        raise ValueError("end must be after start")


class EIAClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.eia.gov/v2",
        page_size: int = 5000,
        limiter: TokenBucket | None = None,
        max_attempts: int = 5,
        timeout_seconds: float = 60.0,
        http: httpx.Client | None = None,
        wait=None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._page_size = page_size
        self._limiter = limiter or TokenBucket(rate_per_second=1.0)
        self._http = http or httpx.Client(timeout=timeout_seconds)
        self._retrying = Retrying(
            retry=retry_if_exception(_is_retryable),
            stop=stop_after_attempt(max_attempts),
            wait=wait or wait_random_exponential(multiplier=1, max=60),
            reraise=True,
        )

    def build_params(
        self,
        route: Route,
        start: datetime,
        end: datetime,
        offset: int,
        facets: Sequence[str] = (),
    ) -> list[tuple[str, str | int]]:
        """Query for the half-open window [start, end).

        EIA's `end` is inclusive, so the request sends end - 1h.
        """
        params: list[tuple[str, str | int]] = [
            ("frequency", "hourly"),
            ("data[0]", "value"),
            ("start", start.strftime(EIA_HOURLY_FORMAT)),
            ("end", (end - timedelta(hours=1)).strftime(EIA_HOURLY_FORMAT)),
        ]
        for i, column in enumerate(route.sort_columns):
            params += [(f"sort[{i}][column]", column), (f"sort[{i}][direction]", "asc")]
        params += [(f"facets[{route.facet}][]", f) for f in facets]
        params += [("offset", offset), ("length", self._page_size)]
        return params

    def fetch_window(
        self,
        route: Route,
        start: datetime,
        end: datetime,
        facets: Sequence[str] = (),
    ) -> Iterator[Page]:
        """Yield every page for the window, then verify the row count against `total`."""
        check_window(start, end)
        offset, number, total = 0, 0, None
        while True:
            number += 1
            params = self.build_params(route, start, end, offset, facets)
            page = self._get_page(route, params, number, offset)
            total = page.total
            yield page
            offset += len(page.rows)
            if offset >= total:
                break
            if not page.rows:
                raise IncompleteExtractError(
                    f"{route.name}: empty page at offset {offset}, API reported total {total}"
                )
        if offset != total:
            raise IncompleteExtractError(
                f"{route.name}: received {offset} rows, API reported total {total}"
            )

    def _get_page(self, route: Route, params: list, number: int, offset: int) -> Page:
        url = f"{self._base_url}/{route.path}"
        for attempt in self._retrying:
            with attempt:
                self._limiter.acquire()
                response = self._http.get(url, params=[("api_key", self._api_key), *params])
                if response.status_code in RETRYABLE_STATUS:
                    raise RetryableStatusError(response.status_code)
                body = self._parse(response)
        return Page(
            number=number,
            offset=offset,
            total=int(body["response"]["total"]),
            rows=body["response"]["data"],
            raw=response.content,
            api_version=body.get("apiVersion"),
            # Seen at the top level in API 2.1.x; older docs show it under `response`.
            warnings=body.get("warnings") or body["response"].get("warnings") or [],
        )

    @staticmethod
    def _parse(response: httpx.Response) -> dict:
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise EIAAPIError(f"non-JSON response (HTTP {response.status_code})") from exc
        if response.is_error or "error" in body:
            # Never include the request URL: it carries the API key.
            raise EIAAPIError(f"HTTP {response.status_code}: {body.get('error', body)}")
        return body
