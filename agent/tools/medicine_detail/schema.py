from pipecat.adapters.schemas.function_schema import FunctionSchema

SCHEMA = FunctionSchema(
    name="get_medicine_detail",
    description=(
        "Fetch price, stock, Rx status, and bulk offers for ONE specific pharmaceutical product. "
        "ONLY call this function when BOTH of these are true in the caller's LATEST message: "
        "(1) they explicitly asked for medicine info — price, stock, availability, or 'look this up'; "
        "(2) they said an actual drug name (brand, generic, or pack letters). "
        "DO NOT call if they only expressed intent to search, said 'a medicine', or have not yet named a product. "
        "DO NOT call for greetings, company questions, or anything other than a named drug lookup."
    ),
    properties={
        "name": {
            "type": "string",
            "description": (
                "The exact drug name, brand, or clue the caller said — including garbled or misspelled. "
                "Must be a real pharmaceutical product name, not 'a medicine' or 'some medicine'."
            ),
        },
    },
    required=["name"],
)
