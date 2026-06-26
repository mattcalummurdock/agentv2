import re

_NON_MEDICINE_PATTERNS = (
    r"^(hi|hello|hey|thanks|thank you|yes|no|ok|okay|sure|bye|goodbye)\.?$",
    r"^(mr\.?\s*med|mister\s*med|mrmed|mr\.?\s*v)\.?$",
    r"^sarah$",
    r"^(what is mr\.?\s*med|who are you|what do you do)\??$",
)

_NON_MEDICINE_RE = re.compile("|".join(_NON_MEDICINE_PATTERNS), re.IGNORECASE)


def is_non_medicine_lookup(name: str) -> bool:
    cleaned = name.strip()
    if not cleaned:
        return True
    if _NON_MEDICINE_RE.fullmatch(cleaned):
        return True
    if len(cleaned.split()) == 1 and cleaned.lower() in {
        "med",
        "medicine",
        "medicines",
        "pharmacy",
        "mrmed",
        "mr",
        "meds",
    }:
        return True
    return False
