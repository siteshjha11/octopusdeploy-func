"""
Schema transformation: Octopus raw event → OctopusAuditEvents_CL record.

Normalises field names, extracts nested values, and ensures every record
has the columns declared in the DCR stream schema.  Missing fields default
to None so the table never receives unexpected columns.

Octopus event reference:
  https://octopus.com/docs/octopus-rest-api/examples/events/list-events
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _utc_iso(value: Optional[str]) -> Optional[str]:
    """Normalise an Octopus ISO-8601 timestamp to UTC ISO-8601 with Z suffix."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (ValueError, TypeError):
        logger.debug("Could not parse timestamp: %s", value)
        return value


def _extract_related(related_docs: list[dict], doc_type: str) -> Optional[str]:
    """Pull the first Id matching a given document type from RelatedDocuments."""
    for doc in related_docs or []:
        if doc.get("DocumentType") == doc_type:
            return doc.get("Id")
    return None


def _extract_related_name(related_docs: list[dict], doc_type: str) -> Optional[str]:
    for doc in related_docs or []:
        if doc.get("DocumentType") == doc_type:
            return doc.get("Name")
    return None


def transform_event(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Map a single Octopus audit event to the OctopusAuditEvents_CL schema.

    Returns a flat dict whose keys match the DCR stream column names exactly.
    """
    related = raw.get("RelatedDocuments") or []
    details = raw.get("Details") or {}

    # Prefer ChangeDetails JSON blob; fall back to raw details dict
    change_details_raw = raw.get("ChangeDetails") or details
    try:
        change_details_str = json.dumps(change_details_raw)
    except (TypeError, ValueError):
        change_details_str = str(change_details_raw)

    # Determine outcome from event category/type naming conventions
    event_type: str = raw.get("Category", "")
    outcome = _infer_outcome(event_type)

    return {
        # --- Timing ---
        "TimeGenerated":    _utc_iso(raw.get("Occurred")),
        "IngestionTime":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),

        # --- Identity ---
        "EventId":          raw.get("Id"),
        "AutoId":           raw.get("AutoId"),
        "EventCategory":    raw.get("EventAgentCategory") or _categorise(event_type),
        "EventType":        event_type,
        "UserId":           raw.get("UserId"),
        "Username":         raw.get("Username"),
        "UserDisplayName":  raw.get("UserDisplayName"),
        "IsService":        raw.get("IsService", False),

        # --- Source ---
        "IpAddress":        raw.get("IpAddress"),
        "UserAgent":        raw.get("UserAgent"),
        "SpaceId":          raw.get("SpaceId"),

        # --- Deployment / Project ---
        "ProjectId":        _extract_related(related, "Project"),
        "ProjectName":      _extract_related_name(related, "Project"),
        "EnvironmentId":    _extract_related(related, "Environment"),
        "EnvironmentName":  _extract_related_name(related, "Environment"),
        "ReleaseId":        _extract_related(related, "Release"),
        "ReleaseVersion":   _extract_related_name(related, "Release"),
        "DeploymentId":     _extract_related(related, "Deployment"),
        "TenantId":         _extract_related(related, "Tenant"),
        "TenantName":       _extract_related_name(related, "Tenant"),
        "ChannelId":        _extract_related(related, "Channel"),
        "MachineName":      _extract_related_name(related, "Machine"),

        # --- Result ---
        "Outcome":          outcome,
        "Message":          raw.get("Message"),
        "ChangeDetails":    change_details_str,

        # --- MITRE ATT&CK (pre-classified for Sentinel enrichment) ---
        "MitreTactic":      _mitre_tactic(event_type),
        "MitreTechnique":   _mitre_technique(event_type),
    }


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[str, str] = {
    "Deployment":  "Deployment",
    "Release":     "Release",
    "User":        "Identity",
    "ApiKey":      "ApiKey",
    "Environment": "Configuration",
    "Project":     "Configuration",
    "Variable":    "Configuration",
    "Lifecycle":   "Configuration",
    "Worker":      "Infrastructure",
    "Machine":     "Infrastructure",
    "Certificate": "Credential",
    "Account":     "Credential",
    "Subscription":"Configuration",
    "Runbook":     "Automation",
    "Space":       "Administration",
    "Team":        "Identity",
}

def _categorise(event_type: str) -> str:
    for prefix, category in _CATEGORY_MAP.items():
        if event_type.startswith(prefix):
            return category
    return "Other"


def _infer_outcome(event_type: str) -> str:
    lowered = event_type.lower()
    if any(w in lowered for w in ("failed", "error", "denied", "blocked", "rejected")):
        return "Failure"
    if any(w in lowered for w in ("succeeded", "completed", "created", "updated")):
        return "Success"
    return "Informational"


_MITRE_TACTIC_MAP: dict[str, str] = {
    "Deployment":        "Execution",
    "ApiKey":            "Credential Access",
    "User":              "Persistence",
    "Variable":          "Defense Evasion",
    "Machine":           "Lateral Movement",
    "Certificate":       "Credential Access",
    "Account":           "Privilege Escalation",
    "Team":              "Privilege Escalation",
    "Environment":       "Defense Evasion",
}

def _mitre_tactic(event_type: str) -> Optional[str]:
    for prefix, tactic in _MITRE_TACTIC_MAP.items():
        if event_type.startswith(prefix):
            return tactic
    return None


_MITRE_TECHNIQUE_MAP: dict[str, str] = {
    "Deployment":    "T1072 - Software Deployment Tools",
    "ApiKey":        "T1528 - Steal Application Access Token",
    "User":          "T1078 - Valid Accounts",
    "Variable":      "T1562 - Impair Defenses",
    "Machine":       "T1021 - Remote Services",
    "Certificate":   "T1552 - Unsecured Credentials",
    "Account":       "T1078 - Valid Accounts",
    "Team":          "T1098 - Account Manipulation",
}

def _mitre_technique(event_type: str) -> Optional[str]:
    for prefix, technique in _MITRE_TECHNIQUE_MAP.items():
        if event_type.startswith(prefix):
            return technique
    return None
