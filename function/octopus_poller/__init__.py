"""
Octopus Deploy → Microsoft Sentinel Log Ingestion
Azure Function: Timer-triggered poller

Polls the Octopus Deploy Audit Events REST API, transforms events to the
OctopusAuditEvents_CL schema, and forwards them to Sentinel via the
DCR-based Logs Ingestion API (azure-monitor-ingestion SDK).

Checkpoint (last ingested event AutoId) is persisted in Azure Table Storage
so restarts never re-ingest or skip events.
"""

import logging
import azure.functions as func

from .octopus_client import OctopusClient
from .sentinel_ingestion import SentinelIngestionClient
from .checkpoint import CheckpointStore
from .schema import transform_event

app = func.FunctionApp()

logger = logging.getLogger(__name__)


@app.timer_trigger(
    schedule="0 */5 * * * *",       # Every 5 minutes
    arg_name="timer",
    run_on_startup=True,
    use_monitor=True,
)
def octopus_sentinel_poller(timer: func.TimerRequest) -> None:
    """Main timer-triggered entry point."""

    if timer.past_due:
        logger.warning("Timer is past due — previous execution may have stalled.")

    logger.info("Octopus → Sentinel poller starting.")

    checkpoint = CheckpointStore()
    octopus   = OctopusClient()
    sentinel  = SentinelIngestionClient()

    last_auto_id = checkpoint.get_last_auto_id()
    logger.info("Resuming from AutoId: %s", last_auto_id or "(beginning)")

    batch: list[dict] = []
    highest_auto_id   = last_auto_id
    total_events      = 0

    for page in octopus.iter_events(from_auto_id=last_auto_id):
        for raw_event in page:
            transformed = transform_event(raw_event)
            batch.append(transformed)

            event_auto_id = raw_event.get("AutoId")
            if event_auto_id and (
                highest_auto_id is None or event_auto_id > highest_auto_id
            ):
                highest_auto_id = event_auto_id

            # Flush in 500-record batches (DCR API limit is 1 MB / request)
            if len(batch) >= 500:
                sentinel.send(batch)
                total_events += len(batch)
                logger.info("Flushed %d events to Sentinel.", len(batch))
                batch = []

    # Flush remaining
    if batch:
        sentinel.send(batch)
        total_events += len(batch)
        logger.info("Flushed final %d events to Sentinel.", len(batch))

    if highest_auto_id and highest_auto_id != last_auto_id:
        checkpoint.set_last_auto_id(highest_auto_id)
        logger.info("Checkpoint advanced to AutoId: %s", highest_auto_id)

    logger.info("Poller complete. Total events ingested: %d", total_events)
