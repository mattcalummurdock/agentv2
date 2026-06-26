from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import LLMService

from tools._announce import augment_schema
from tools.medicine_detail.handler import handler as get_medicine_detail_handler
from tools.medicine_detail.schema import SCHEMA as get_medicine_detail_schema

_TOOL_MODULES = [
    (get_medicine_detail_schema, get_medicine_detail_handler),
]


def build_tools_schema() -> ToolsSchema:
    return ToolsSchema(standard_tools=[augment_schema(schema) for schema, _ in _TOOL_MODULES])


def register_tools(llm: LLMService) -> None:
    for schema, handler in _TOOL_MODULES:
        llm.register_function(
            schema.name,
            handler,
        )
