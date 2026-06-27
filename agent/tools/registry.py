from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import LLMService

from tools.medicine_alternatives.handler import handler as get_medicine_alternatives_handler
from tools.medicine_alternatives.schema import SCHEMA as get_medicine_alternatives_schema
from tools.medicine_compare.handler import handler as compare_medicines_handler
from tools.medicine_compare.schema import SCHEMA as compare_medicines_schema
from tools.medicine_detail.handler import handler as get_medicine_detail_handler
from tools.medicine_detail.schema import SCHEMA as get_medicine_detail_schema

_TOOL_MODULES = [
    (get_medicine_alternatives_schema, get_medicine_alternatives_handler),
    (compare_medicines_schema, compare_medicines_handler),
    (get_medicine_detail_schema, get_medicine_detail_handler),
]


def build_tools_schema() -> ToolsSchema:
    return ToolsSchema(standard_tools=[schema for schema, _ in _TOOL_MODULES])


def register_tools(llm: LLMService) -> None:
    for schema, handler in _TOOL_MODULES:
        llm.register_function(
            schema.name,
            handler,
        )
