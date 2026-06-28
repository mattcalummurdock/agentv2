import os

DEFAULT_BASE_URL = "https://api.in21.leadsquared.com/v2"
DEFAULT_PHONE_ACTIVITY_TYPE_ID = 9
DEFAULT_FIELD_CALL_TYPE = "mx_Call_Type"
DEFAULT_FIELD_MEDICINE = "mx_Medicine_of_Interest"
MAX_ACTIVITY_NOTE_CHARS = 30_000


def is_leadsquared_enabled() -> bool:
    if os.getenv("LEADSQUARED_ENABLED", "0").strip().lower() in ("0", "false", "no"):
        return False
    return bool(
        os.getenv("LEADSQUARED_ACCESS_KEY", "").strip()
        and os.getenv("LEADSQUARED_SECRET_KEY", "").strip()
    )


def get_access_key() -> str:
    return os.getenv("LEADSQUARED_ACCESS_KEY", "").strip()


def get_secret_key() -> str:
    return os.getenv("LEADSQUARED_SECRET_KEY", "").strip()


def get_base_url() -> str:
    return os.getenv("LEADSQUARED_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")


def get_phone_activity_type_id() -> int:
    raw = os.getenv(
        "LEADSQUARED_PHONE_ACTIVITY_TYPE_ID", str(DEFAULT_PHONE_ACTIVITY_TYPE_ID)
    ).strip()
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_PHONE_ACTIVITY_TYPE_ID


def get_field_call_type() -> str:
    return os.getenv("LEADSQUARED_FIELD_CALL_TYPE", DEFAULT_FIELD_CALL_TYPE).strip()


def get_field_medicine() -> str:
    return os.getenv("LEADSQUARED_FIELD_MEDICINE", DEFAULT_FIELD_MEDICINE).strip()


def auth_params() -> dict[str, str]:
    return {
        "accessKey": get_access_key(),
        "secretKey": get_secret_key(),
    }
