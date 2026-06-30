#!/usr/bin/env python3
"""Send dummy call data to LeadSquared to verify credentials and API connectivity."""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

AGENT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(AGENT_DIR / ".env", override=True)

REQUEST_TIMEOUT = (5, 30)


def _cfg(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def base_url() -> str:
    return _cfg("LEADSQUARED_BASE_URL", "https://api-in21.leadsquared.com/v2").rstrip("/")


def auth_params() -> dict[str, str]:
    return {
        "accessKey": _cfg("LEADSQUARED_ACCESS_KEY"),
        "secretKey": _cfg("LEADSQUARED_SECRET_KEY"),
    }


def is_enabled() -> bool:
    if _cfg("LEADSQUARED_ENABLED", "0").lower() in ("0", "false", "no"):
        return False
    return bool(auth_params()["accessKey"] and auth_params()["secretKey"])


def activity_event_id() -> int:
    return int(_cfg("LEADSQUARED_PHONE_ACTIVITY_TYPE_ID", "103"))


def search_lead_by_phone(phone: str) -> str | None:
    url = f"{base_url()}/LeadManagement.svc/Leads.GetByPhoneNumber"
    for candidate in (phone, f"91{phone}"):
        response = requests.get(
            url,
            params={**auth_params(), "phone": candidate},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 404:
            continue
        response.raise_for_status()
        data = response.json()
        leads = data if isinstance(data, list) else data.get("Leads", [])
        if leads:
            lead = leads[0]
            return str(lead.get("ProspectID") or lead.get("Id") or "")
    return None


def create_lead(name: str, phone: str | None = None) -> str:
    parts = name.strip().split(" ", 1)
    payload: list[dict[str, str]] = [
        {"Attribute": "FirstName", "Value": parts[0]},
        {"Attribute": "LastName", "Value": parts[1] if len(parts) > 1 else ""},
    ]
    if phone:
        payload.append({"Attribute": "Phone", "Value": phone})

    response = requests.post(
        f"{base_url()}/LeadManagement.svc/Lead.Create",
        params=auth_params(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    prospect_id = data.get("Message", {}).get("Id") or data.get("ProspectId")
    if not prospect_id:
        raise ValueError(f"No prospect id in response: {data!r}")
    return str(prospect_id)


def resolve_or_create_lead(name: str, phone: str | None) -> str:
    if phone:
        existing = search_lead_by_phone(phone)
        if existing:
            print(f"  reusing existing lead {existing} for phone {phone}")
            return existing
    return create_lead(name, phone=phone)


def log_activity(prospect_id: str, *, call_type: str, medicine: str, note: str) -> None:
    payload = {
        "RelatedProspectId": prospect_id,
        "ActivityEvent": activity_event_id(),
        "ActivityNote": note,
        "ActivityDateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Fields": [
            {
                "SchemaName": _cfg("LEADSQUARED_FIELD_CALL_TYPE", "mx_Call_Type"),
                "Value": call_type,
            },
            {
                "SchemaName": _cfg("LEADSQUARED_FIELD_MEDICINE", "mx_Medicine_of_Interest"),
                "Value": medicine or "",
            },
        ],
    }
    response = requests.post(
        f"{base_url()}/ProspectActivity.svc/Create",
        params=auth_params(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


def run_test(label: str, *, name: str, phone: str | None, stamp: int) -> bool:
    print(f"\n--- {label} ---")
    try:
        prospect_id = resolve_or_create_lead(name, phone)
        note = (
            f"Call Type: Product Inquiry\n"
            f"Phone: {phone or 'N/A'}\n"
            f"Medicine of Interest: Test Medicine\n"
            f"City: Mumbai\n"
            f"Budget: 5000\n"
            f"Intent: MOFU\n"
            f"Call SID: TEST-SID-{stamp}\n"
            f"\nConversation Notes:\n"
            f"User: This is an automated LeadSquared connectivity test ({stamp}).\n"
            f"Agent: Confirmed — dummy data only."
        )
        log_activity(
            prospect_id,
            call_type="Product Inquiry",
            medicine="Test Medicine",
            note=note,
        )
        print(f"SUCCESS  prospect_id={prospect_id}")
        return True
    except requests.HTTPError as exc:
        body = ""
        if exc.response is not None:
            body = exc.response.text[:500]
        print(f"FAILED   HTTP {getattr(exc.response, 'status_code', '?')}: {body or exc}")
        return False
    except Exception as exc:
        print(f"FAILED   {exc}")
        return False


def main() -> int:
    print("LeadSquared integration test")
    print(f"Base URL:       {base_url()}")
    print(f"Enabled:        {is_enabled()}")
    print(f"Activity event: {activity_event_id()}")

    if not is_enabled():
        print("\nLeadSquared is disabled or credentials are missing in .env")
        return 1

    stamp = int(time.time())
    phone = f"99999{stamp % 100000:05d}"
    ok_with = run_test(
        "Test 1: lead with phone",
        name="Cursor Test Lead",
        phone=phone,
        stamp=stamp,
    )
    ok_without = run_test(
        "Test 2: lead without phone",
        name="Cursor Test No Phone",
        phone=None,
        stamp=stamp,
    )

    if ok_with and ok_without:
        print("\nAll LeadSquared tests passed.")
        return 0

    print("\nOne or more LeadSquared tests failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
