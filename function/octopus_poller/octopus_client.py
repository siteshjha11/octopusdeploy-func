"""
Octopus Deploy REST API client.

Handles paginated retrieval of Audit Events using the AutoId cursor pattern,
which is immune to timestamp collisions and guarantees no duplicate/missed events.

Auth: X-Octopus-ApiKey header (API key stored in Key Vault, injected via
      Function App application settings as OCTOPUS_API_KEY).

Ref: https://octopus.com/docs/octopus-rest-api/api-examples/events
"""

import os
import time
import logging
from typing import Generator, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_OCTOPUS_URL     = os.environ["OCTOPUS_SERVER_URL"].rstrip("/")
_OCTOPUS_API_KEY = os.environ["OCTOPUS_API_KEY"]
_PAGE_SIZE       = int(os.environ.get("OCTOPUS_PAGE_SIZE", "200"))
_REQUEST_TIMEOUT = int(os.environ.get("OCTOPUS_REQUEST_TIMEOUT_SEC", "30"))
_MAX_PAGES       = int(os.environ.get("OCTOPUS_MAX_PAGES_PER_RUN", "100"))


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "X-Octopus-ApiKey": _OCTOPUS_API_KEY,
        "Accept":           "application/json",
        "User-Agent":       "OctopusSentinelPoller/1.0",
    })
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://",  HTTPAdapter(max_retries=retry))
    return session


class OctopusClient:
    """Paginated reader for Octopus Deploy /api/events."""

    def __init__(self) -> None:
        self._session = _build_session()
        self._base    = _OCTOPUS_URL

    def iter_events(
        self, from_auto_id: Optional[int] = None
    ) -> Generator[list[dict], None, None]:
        """
        Yield pages of raw Octopus audit event dicts, ordered oldest-first.

        Uses fromAutoId for safe cursor-based pagination. The Octopus API
        returns events newest-first, so we walk pages and reverse each page
        before yielding so callers always process events chronologically.
        """
        pages_fetched = 0
        skip = 0

        while pages_fetched < _MAX_PAGES:
            params: dict = {
                "spaces": "all",
                "includeSystem": "true",
                "skip":  skip,
                "take":  _PAGE_SIZE,
            }
            if from_auto_id is not None:
                # fromAutoId is exclusive — returns events with AutoId > value
                params["fromAutoId"] = from_auto_id

            try:
                resp = self._session.get(
                    f"{self._base}/api/events",
                    params=params,
                    timeout=_REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
            except requests.exceptions.RequestException as exc:
                logger.error("Octopus API request failed: %s", exc)
                raise

            data  = resp.json()
            items = data.get("Items", [])

            if not items:
                logger.debug("No more events to fetch (skip=%d).", skip)
                break

            # Reverse so we yield oldest events first within each page
            yield list(reversed(items))

            pages_fetched += 1
            skip += len(items)

            total_results = data.get("TotalResults", 0)
            if skip >= total_results:
                break

            # Respect Octopus rate limits
            time.sleep(0.25)

        if pages_fetched >= _MAX_PAGES:
            logger.warning(
                "Hit MAX_PAGES_PER_RUN (%d). Next run will continue from checkpoint.",
                _MAX_PAGES,
            )
