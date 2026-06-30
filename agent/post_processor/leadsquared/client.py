from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from post_processor.config import pp_logger
from post_processor.leadsquared.config import (
    MAX_ACTIVITY_NOTE_CHARS,
    auth_params,
    get_base_url,
    get_field_call_type,
    get_field_medicine,
    get_phone_activity_type_id,
)

REQUEST_TIMEOUT = (5, 30)


def _response_error_snippet(response: requests.Response) -> str:
    try:
        body = response.text[:500]
    except Exception:
        body = ""
    return f"HTTP {response.status_code}" + (f": {body}" if body else "")


def format_http_error(exc: requests.HTTPError) -> str:
    resp = exc.response
    if resp is None:
        return str(exc)
    return _response_error_snippet(resp)


def _truncate_note(note: str) -> str:
    if len(note) <= MAX_ACTIVITY_NOTE_CHARS:
        return note
    marker = "\n... [truncated]"
    return note[: MAX_ACTIVITY_NOTE_CHARS - len(marker)] + marker


def search_lead_by_phone(phone: str) -> dict[str, Any] | None:
    """Return the first matching lead dict, or None if not found."""
    url = f"{get_base_url()}/LeadManagement.svc/Leads.GetByPhoneNumber"
    for candidate in (phone, f"91{phone}"):
        response = requests.get(
            url,
            params={**auth_params(), "phone": candidate},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        leads = data if isinstance(data, list) else data.get("Leads", [])
        if leads:
            lead = leads[0]
            prospect_id = lead.get("ProspectID") or lead.get("Id")
            pp_logger.info(
                f"LeadSquared: found existing lead {prospect_id} "
                f"for phone {candidate!r}"
            )
            return lead
    return None


def create_lead(name: str, phone: str | None = None) -> str:
    """Create a new lead and return the ProspectID."""
    url = f"{get_base_url()}/LeadManagement.svc/Lead.Create"
    parts = name.strip().split(" ", 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""

    payload: list[dict[str, str]] = [
        {"Attribute": "FirstName", "Value": first_name},
        {"Attribute": "LastName", "Value": last_name},
    ]
    if phone:
        payload.append({"Attribute": "Phone", "Value": phone})

    response = requests.post(
        url,
        params=auth_params(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()

    prospect_id = data.get("Message", {}).get("Id") or data.get("ProspectId")
    if not prospect_id:
        raise ValueError(f"LeadSquared create lead returned no prospect id: {data!r}")
    pp_logger.info(
        f"LeadSquared: created lead {prospect_id} name={name!r} phone={phone!r}"
    )
    return str(prospect_id)


def log_activity(
    prospect_id: str,
    *,
    call_type: str,
    medicine: str,
    activity_note: str,
) -> None:
    """Log a phone call activity under the lead."""
    url = f"{get_base_url()}/ProspectActivity.svc/Activity.Create"
    note_body = _truncate_note(activity_note)

    payload: dict[str, Any] = {
        "RelatedProspectId": prospect_id,
        "ActivityEvent": get_phone_activity_type_id(),
        "ActivityNote": note_body,
        "ActivityDateTime": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "Fields": [
            {"SchemaName": get_field_call_type(), "Value": call_type},
            {"SchemaName": get_field_medicine(), "Value": medicine or ""},
        ],
    }

    response = requests.post(
        url,
        params=auth_params(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    pp_logger.info(f"LeadSquared: activity logged under lead {prospect_id}")
