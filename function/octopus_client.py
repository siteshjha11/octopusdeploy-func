"""
octopus_client.py
-----------------
Paginates the Octopus Deploy /api/events endpoint and returns only
events newer than the stored checkpoint.  The checkpoint is the
highest numeric event ID seen so far (stored as a string in Azure
Blob Storage via checkpoint_manager.py).
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Generator

import requests

logger = logging.getLogger(__name__)


@dataclass
class OctopusEvent:
    """Normalised representation of a single Octopus audit event."""

    event_id: str
    occurred: datetime
    event_category: str
    event_type: str
    user_id: str
    username: str
    project_name: str
    project_id: str
    environment_name: str
    environment_id: str
    space_id: str
    ip_address: str
    outcome: str
    change_details: dict
    raw: dict = field(repr=False)

    @classmethod
    def from_api(cls, raw: dict) -> "OctopusEvent":
        occurred_str = raw.get("Occurred", "")
        try:
            occurred = datetime.fromisoformat(occurred_str.replace("Z", "+00:00"))
        except ValueError:
            occurred = datetime.now(timezone.utc)

        # Derive category from the event Category field or the first segment of EventType
        event_type = raw.get("Category", "")
        category = event_type.split(" ")[0] if event_type else "Unknown"

        related_docs = raw.get("RelatedDocumentIds", [])

        def _first_of_type(prefix: str) -> str:
            return next((d for d in related_docs if d.startswith(prefix)), "")

        return cls(
            event_id=raw.get("Id", ""),
            occurred=occurred,
            event_category=category,
            event_type=event_type,
            user_id=raw.get("UserId", ""),
            username=raw.get("Username", ""),
            project_name=raw.get("ProjectName", ""),
            project_id=_first_of_type("Projects-"),
            environment_name=raw.get("EnvironmentName", ""),
            environment_id=_first_of_type("Environments-"),
            space_id=raw.get("SpaceId", "Spaces-1"),
            ip_address=raw.get("IpAddress", ""),
            outcome=raw.get("IsService", False) and "Service" or "Interactive",
            change_details=raw.get("ChangeDetails", {}),
            raw=raw,
        )


class OctopusClient:
    """
    Pulls audit events from the Octopus Deploy REST API.

    Environment variables expected:
        OCTOPUS_URL      – e.g. https://your-instance.octopus.app
        OCTOPUS_API_KEY  – starts with API-
        OCTOPUS_SPACE_ID – e.g. Spaces-1  (defaults to Spaces-1)
    """

    DEFAULT_PAGE_SIZE = 200

    def __init__(self) -> None:
        self.base_url = os.environ["OCTOPUS_URL"].rstrip("/")
        self.api_key = os.environ["OCTOPUS_API_KEY"]
        self.space_id = os.environ.get("OCTOPUS_SPACE_ID", "Spaces-1")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Octopus-ApiKey": self.api_key,
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_events_since(
        self, last_event_id: str | None, page_size: int = DEFAULT_PAGE_SIZE
    ) -> Generator[OctopusEvent, None, None]:
        """
        Yield OctopusEvent objects newer than *last_event_id*.

        Octopus returns events in descending order (newest first).
        We page through until we find an event whose ID matches or is
        older than last_event_id, then stop.
        """
        url = f"{self.base_url}/api/{self.space_id}/events"
        skip = 0
        found_checkpoint = False

        while not found_checkpoint:
            params = {"take": page_size, "skip": skip}
            response = self._get(url, params)
            items = response.get("Items", [])

            if not items:
                logger.info("No more events returned from Octopus API.")
                break

            for raw in items:
                event_id = raw.get("Id", "")
                if last_event_id and self._id_lte(event_id, last_event_id):
                    # We've reached events we've already ingested
                    found_checkpoint = True
                    break
                yield OctopusEvent.from_api(raw)

            # Check paging links
            links = response.get("Links", {})
            if "Page.Next" not in links:
                break

            skip += page_size

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get(self, url: str, params: dict) -> dict:
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _id_lte(event_id: str, checkpoint_id: str) -> bool:
        """
        Compare Octopus event IDs like 'Events-12345'.
        Returns True when event_id is <= checkpoint_id numerically.
        """
        try:
            return int(event_id.split("-")[-1]) <= int(checkpoint_id.split("-")[-1])
        except (ValueError, IndexError):
            return False
