"""
function_app.py
---------------
Azure Function v2 (Python) — timer-triggered Octopus → Sentinel ingestion.

Schedule: every 5 minutes by default (CRON_SCHEDULE env var overrides).

Required environment variables — see octopus_client.py, sentinel_client.py,
and checkpoint_manager.py for the full list.  All are surfaced in
local.settings.json.template and the ARM parameter file.
"""

import logging
import os

import azure.functions as func

from checkpoint_manager import CheckpointManager
from octopus_client import OctopusClient
from sentinel_client import SentinelClient

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Function App
# ---------------------------------------------------------------------------
app = func.FunctionApp()

CRON_SCHEDULE = os.environ.get("CRON_SCHEDULE", "0 */5 * * * *")  # every 5 min


@app.function_name(name="OctopusIngest")
@app.timer_trigger(
    schedule=CRON_SCHEDULE,
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def octopus_ingest(timer: func.TimerRequest) -> None:
    """
    Main entry point.

    Flow:
      1. Load last-seen event ID from checkpoint store.
      2. Fetch all newer events from Octopus API (paginated).
      3. Stream events to Sentinel via DCR Logs Ingestion API.
      4. Persist the highest event ID as the new checkpoint.
    """
    if timer.past_due:
        logger.warning("Timer is running late — previous execution may have timed out.")

    logger.info("OctopusIngest triggered.")

    checkpoint_mgr = CheckpointManager()
    octopus = OctopusClient()
    sentinel = SentinelClient()

    # Step 1 — read checkpoint
    last_event_id = checkpoint_mgr.read()
    logger.info("Starting from checkpoint: %s", last_event_id or "NONE (full backfill)")

    # Step 2 + 3 — fetch and send, tracking the highest (newest) event ID
    highest_id: str | None = None
    events_iter = octopus.get_events_since(last_event_id)

    # We collect into a list here so we can capture the highest ID before
    # streaming to Sentinel.  For very large backlogs consider streaming
    # in chunks (see _chunked_send below).
    events = list(events_iter)

    if not events:
        logger.info("No new events to process.")
        return

    # Events come back newest-first; the first item is the highest ID.
    highest_id = events[0].event_id
    logger.info("Fetched %d new event(s). Highest ID: %s", len(events), highest_id)

    total_sent = sentinel.send(iter(events))
    logger.info("Successfully sent %d event(s) to Sentinel.", total_sent)

    # Step 4 — persist checkpoint only after successful send
    if highest_id:
        checkpoint_mgr.write(highest_id)

    logger.info("OctopusIngest complete.")
