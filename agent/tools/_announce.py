"""Speak a brief hold line in the same turn before every tool call."""

from pipecat.adapters.schemas.function_schema import FunctionSchema

ANNOUNCE_SUFFIX = (
    " SAME TURN: say one brief hold line in the user's language (vary wording), "
    "then call this function immediately. Do not wait for okay."
)


def augment_schema(schema: FunctionSchema) -> FunctionSchema:
    return FunctionSchema(
        name=schema.name,
        description=(schema.description or "") + ANNOUNCE_SUFFIX,
        properties=schema.properties,
        required=schema.required,
    )
