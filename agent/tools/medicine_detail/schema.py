from pipecat.adapters.schemas.function_schema import FunctionSchema

SCHEMA = FunctionSchema(
    name="get_medicine_detail",
    description=(
        "Look up medicine price, stock, Rx status, and bulk offers. "
        "Call only when the caller asked for price/stock/info and named a product. "
        "Do not call for greetings, small talk, or Mr. Med company questions. "
        "Pass the name exactly as spoken, even if misspelled. "
        "Confirm with the caller before quoting if match_method is semantic or pack_letters."
    ),
    properties={
        "name": {
            "type": "string",
            "description": "Medicine name or clue as the caller said it. Not Mr. Med or company names.",
        },
    },
    required=["name"],
)
