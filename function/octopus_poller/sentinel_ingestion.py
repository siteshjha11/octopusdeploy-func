"""
Microsoft Sentinel / Azure Monitor Logs Ingestion client.

Uses the azure-monitor-ingestion SDK with DefaultAzureCredential (Managed Identity
in production, env vars locally) to POST transformed events to a Data Collection
Rule (DCR) endpoint.

Required environment variables:
  SENTINEL_DCE_ENDPOINT     - Data Collection Endpoint URL
                              e.g. https://octopus-dce-<hash>.eastus-1.ingest.monitor.azure.com
  SENTINEL_DCR_IMMUTABLE_ID - DCR Immutable ID
                              e.g. dcr-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  SENTINEL_STREAM_NAME      - Stream name declared in DCR
                              e.g. Custom-OctopusAuditEvents_CL
"""

import os
import logging
from typing import Any

from azure.identity import DefaultAzureCredential
from azure.monitor.ingestion import LogsIngestionClient
from azure.core.exceptions import HttpResponseError

logger = logging.getLogger(__name__)

_DCE_ENDPOINT     = os.environ["SENTINEL_DCE_ENDPOINT"]
_DCR_IMMUTABLE_ID = os.environ["SENTINEL_DCR_IMMUTABLE_ID"]
_STREAM_NAME      = os.environ["SENTINEL_STREAM_NAME"]


class SentinelIngestionClient:
    """Thin wrapper around azure-monitor-ingestion for DCR-based log upload."""

    def __init__(self) -> None:
        credential = DefaultAzureCredential()
        self._client = LogsIngestionClient(
            endpoint=_DCE_ENDPOINT,
            credential=credential,
            logging_enable=False,
        )

    def send(self, records: list[dict[str, Any]]) -> None:
        """
        Upload a batch of records to Sentinel.

        The SDK handles chunking if the payload exceeds 1 MB, retries on
        transient failures, and surfaces HttpResponseError for permanent ones.
        """
        if not records:
            return

        try:
            self._client.upload(
                rule_id=_DCR_IMMUTABLE_ID,
                stream_name=_STREAM_NAME,
                logs=records,
            )
            logger.debug("Successfully uploaded %d records to Sentinel.", len(records))
        except HttpResponseError as exc:
            logger.error(
                "Sentinel ingestion failed [HTTP %s]: %s",
                exc.status_code,
                exc.message,
            )
            raise
