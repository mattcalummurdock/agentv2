from pipecat.adapters.schemas.function_schema import FunctionSchema

SCHEMA = FunctionSchema(
    name="compare_medicines",
    description=(
        "Compare two PHARMACEUTICAL PRODUCTS the user named side by side. "
        "DO NOT CALL unless the user named two specific drugs to compare. "
        "NEVER pass generic placeholders like 'medicine' or 'specific medicine' as name_a or name_b. "
        "Never use for Mr. Med/MrMed or company names. "
        "Never use get_medicine_detail or get_medicine_alternatives for compare requests — use this tool."
    ),
    properties={
        "name_a": {
            "type": "string",
            "description": (
                "First specific drug name the caller said — never a generic placeholder."
            ),
        },
        "name_b": {
            "type": "string",
            "description": (
                "Second specific drug name the caller said — never a generic placeholder."
            ),
        },
    },
    required=["name_a", "name_b"],
)
