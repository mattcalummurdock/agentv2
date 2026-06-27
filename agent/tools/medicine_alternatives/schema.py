from pipecat.adapters.schemas.function_schema import FunctionSchema

SCHEMA = FunctionSchema(
    name="get_medicine_alternatives",
    description=(
        "Find in-stock substitute medicines when the caller wants alternatives, substitutes, "
        "cheaper options, or something similar to a named product. "
        "Use this tool — not get_medicine_detail — whenever the caller's intent is substitutes, "
        "even if they also mention price. "
        "Pass their spoken drug name as-is (misspellings OK) only when they named a real product. "
        "NEVER pass generic placeholders like 'medicine', 'drug', or 'specific medicine'. "
        "If no drug name was given, do not call — ask which medicine first. "
        "this tool resolves the closest catalog match and returns ranked substitutes in one call. "
        "Never call get_medicine_detail before or instead of this tool for substitute requests. "
        "Never call this when the caller explicitly asked to compare two named medicines — "
        "use compare_medicines instead."
    ),
    properties={
        "name": {
            "type": "string",
            "description": (
                "The specific drug name the caller said — pass exact wording including misspellings. "
                "NEVER pass generic placeholders like 'medicine', 'drug', or 'specific medicine'. "
                "If the caller did not name a drug, do not call this tool."
            ),
        },
        "cheaper_only": {
            "type": "boolean",
            "description": "If true, return only alternatives cheaper than the source product. Default true.",
        },
    },
    required=["name"],
)
