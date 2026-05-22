"""
Checkpoint store backed by Azure Table Storage.

Persists the highest AutoId successfully ingested so the poller
can resume exactly where it left off after restarts or failures.

Uses AutoId (integer) rather than timestamp to avoid:
  - Duplicate ingestion when multiple events share the same second
  - Missed events if the Octopus server clock drifts

Table: OctopusCheckpoints
Partition key: "poller"
Row key:       "lastAutoId"
"""

import os
import logging
from typing import Optional

from azure.data.tables import TableServiceClient, TableClient
from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError
from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)

_STORAGE_ACCOUNT_URL = os.environ.get("CHECKPOINT_STORAGE_ACCOUNT_URL")
_STORAGE_CONNECTION  = os.environ.get("AzureWebJobsStorage")
_TABLE_NAME          = "OctopusCheckpoints"
_PARTITION_KEY       = "poller"
_ROW_KEY             = "lastAutoId"


class CheckpointStore:
    """Read/write the ingestion cursor from Azure Table Storage."""

    def __init__(self) -> None:
        self._table: TableClient = self._get_table_client()
        self._ensure_table()

    def _get_table_client(self) -> TableClient:
        if _STORAGE_ACCOUNT_URL:
            # Use Managed Identity (preferred in production)
            svc = TableServiceClient(
                endpoint=_STORAGE_ACCOUNT_URL,
                credential=DefaultAzureCredential(),
            )
        else:
            # Fallback to connection string (local dev / legacy)
            svc = TableServiceClient.from_connection_string(_STORAGE_CONNECTION)
        return svc.get_table_client(_TABLE_NAME)

    def _ensure_table(self) -> None:
        try:
            self._table.create_table()
            logger.info("Created checkpoint table '%s'.", _TABLE_NAME)
        except ResourceExistsError:
            pass  # Already exists — normal path

    def get_last_auto_id(self) -> Optional[int]:
        """Return the last successfully ingested AutoId, or None if first run."""
        try:
            entity = self._table.get_entity(
                partition_key=_PARTITION_KEY,
                row_key=_ROW_KEY,
            )
            return int(entity["Value"])
        except ResourceNotFoundError:
            return None

    def set_last_auto_id(self, auto_id: int) -> None:
        """Upsert the checkpoint to the given AutoId."""
        entity = {
            "PartitionKey": _PARTITION_KEY,
            "RowKey":       _ROW_KEY,
            "Value":        str(auto_id),
        }
        self._table.upsert_entity(entity)
        logger.debug("Checkpoint updated to AutoId %d.", auto_id)
