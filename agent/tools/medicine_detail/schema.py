from pipecat.adapters.schemas.function_schema import FunctionSchema

SCHEMA = FunctionSchema(
    name="get_medicine_detail",
    description=(
        "Fetch price, stock, Rx status, bulk offers, and catalog side effects for ONE product "
        "when the caller wants product details only — not substitutes. "
        "Also use when the caller read a medicine name from a prescription but may have garbled, "
        "misspelled, or partially remembered it — pass their exact wording; the server resolves "
        "the closest catalog product and returns the resolved name with details. "
        "Also use for side-effect questions; side effects are returned in the same response. "
        "NEVER call this for alternatives, substitutes, cheaper options, similar medicines, "
        "or 'something else like X'. Use get_medicine_alternatives for those requests. "
        "NEVER call this when the caller explicitly asked to compare two named medicines — "
        "use compare_medicines instead. "
        "Only call when the caller named a specific drug (not generic words like 'medicine' or "
        "'specific medicine') and asked for price, stock, availability, side effects, or "
        "to look up garbled wording from a prescription."
    ),
    properties={
        "name": {
            "type": "string",
            "description": (
                "The specific drug name or name-like clue the caller said — e.g. 'Oxy ELG', "
                "'Dolo 650', 'Metformin'. Pass exact garbled wording from their prescription "
                "or pack. NEVER pass generic placeholders such as 'medicine', 'drug', "
                "'specific medicine', 'a tablet', or any phrase with no actual product name. "
                "If the caller did not name a drug yet, do not call this tool — ask them first."
            ),
        },
    },
    required=["name"],
)
