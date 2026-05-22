"""
checkpoint_manager.py
---------------------
Persists the last-ingested Octopus event ID in Azure Blob Storage so
the function can resume from where it left off after a restart or
re-deployment.

Environment variables expected:
    CHECKPOINT_STORAGE_CONNECTION  – Azure Storage account connection string
    CHECKPOINT_CONTAINER           – Blob container name (default: octopus-checkpoints)
    CHECKPOINT_BLOB_NAME           – Blob name (default: last_event_id.txt)
"""

import logging
import os

from azure.storage.blob import BlobClient, BlobServiceClient

logger = logging.getLogger(__name__)

_DEFAULT_CONTAINER = "octopus-checkpoints"
_DEFAULT_BLOB = "last_event_id.txt"


class CheckpointManager:
    def __init__(self) -> None:
        conn_str = os.environ["CHECKPOINT_STORAGE_CONNECTION"]
        self._container = os.environ.get("CHECKPOINT_CONTAINER", _DEFAULT_CONTAINER)
        self._blob_name = os.environ.get("CHECKPOINT_BLOB_NAME", _DEFAULT_BLOB)

        service: BlobServiceClient = BlobServiceClient.from_connection_string(conn_str)
        # Ensure container exists
        container_client = service.get_container_client(self._container)
        try:
            container_client.create_container()
            logger.info("Created checkpoint container: %s", self._container)
        except Exception:
            pass  # Already exists

        self._client: BlobClient = service.get_blob_client(
            container=self._container, blob=self._blob_name
        )

    def read(self) -> str | None:
        """Return the stored event ID string, or None if no checkpoint exists."""
        try:
            data = self._client.download_blob().readall()
            event_id = data.decode("utf-8").strip()
            logger.info("Loaded checkpoint: %s", event_id)
            return event_id or None
        except Exception:
            logger.info("No existing checkpoint found — full backfill will run.")
            return None

    def write(self, event_id: str) -> None:
        """Persist *event_id* as the new checkpoint."""
        self._client.upload_blob(event_id.encode("utf-8"), overwrite=True)
        logger.info("Checkpoint updated to: %s", event_id)
