"""
sentinel_client.py
------------------
Sends batches of normalised Octopus events to Microsoft Sentinel via
the Logs Ingestion API (DCR-based, replaces the legacy HTTP Data
Collector API).

Docs:
  https://learn.microsoft.com/azure/azure-monitor/logs/logs-ingestion-api-overview

Environment variables expected:
    DCE_ENDPOINT      – Data Collection Endpoint URI
                        e.g. https://<dce-name>.<region>.ingest.monitor.azure.com
    DCR_IMMUTABLE_ID  – Immutable ID of the Data Collection Rule
                        e.g. dcr-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    DCR_STREAM_NAME   – Stream name declared in the DCR
                        e.g. Custom-OctopusAuditEvents_CL
    AZURE_TENANT_ID   – AAD tenant (used by DefaultAzureCredential)
    AZURE_CLIENT_ID   – Service principal app ID
    AZURE_CLIENT_SECRET – Service principal secret
"""

import json
import logging
import os
from datetime import timezone
from typing import Iterable

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.monitor.ingestion import LogsIngestionClient

from octopus_client import OctopusEvent

logger = logging.getLogger(__name__)

# Sentinel / Log Analytics imposes a 1 MB compressed / 30 MB uncompressed
# limit per API call.  Batching at 500 events is a conservative safe default.
DEFAULT_BATCH_SIZE = 500


def _to_sentinel_record(evt: OctopusEvent) -> dict:
    """Map an OctopusEvent to the custom table column schema."""
    return {
        # TimeGenerated must be ISO-8601 UTC
        "TimeGenerated": evt.occurred.astimezone(timezone.utc).isoformat(),
        "EventId": evt.event_id,
        "EventCategory": evt.event_category,
        "EventType": evt.event_type,
        "UserId": evt.user_id,
        "Username": evt.username,
        "ProjectName": evt.project_name,
        "ProjectId": evt.project_id,
        "EnvironmentName": evt.environment_name,
        "EnvironmentId": evt.environment_id,
        "SpaceId": evt.space_id,
        "IpAddress": evt.ip_address,
        "Outcome": evt.outcome,
        # Serialise nested detail as a JSON string so it can be parsed with
        # parse_json() in KQL when needed.
        "ChangeDetails": json.dumps(evt.change_details),
        # Raw event for forensics / future enrichment
        "RawEvent": json.dumps(evt.raw),
    }


class SentinelClient:
    def __init__(self) -> None:
        credential = DefaultAzureCredential()
        self._dce = os.environ["DCE_ENDPOINT"]
        self._dcr_id = os.environ["DCR_IMMUTABLE_ID"]
        self._stream = os.environ["DCR_STREAM_NAME"]
        self._client = LogsIngestionClient(endpoint=self._dce, credential=credential)

    def send(
        self, events: Iterable[OctopusEvent], batch_size: int = DEFAULT_BATCH_SIZE
    ) -> int:
        """
        Send *events* to Sentinel in batches.
        Returns the total number of events successfully sent.
        """
        total_sent = 0
        batch: list[dict] = []

        def _flush(b: list[dict]) -> int:
            if not b:
                return 0
            try:
                self._client.upload(
                    rule_id=self._dcr_id,
                    stream_name=self._stream,
                    logs=b,
                )
                logger.info("Uploaded %d records to Sentinel.", len(b))
                return len(b)
            except HttpResponseError as exc:
                logger.error("Failed to upload batch: %s", exc)
                raise

        for evt in events:
            batch.append(_to_sentinel_record(evt))
            if len(batch) >= batch_size:
                total_sent += _flush(batch)
                batch = []

        # Flush remainder
        total_sent += _flush(batch)
        return total_sent
