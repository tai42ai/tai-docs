"""A minimal fictional agent plugin: a greeter.

Each agent implements the ``Agent`` ABC; the runtime derives two faces from it —
a JSON ``run`` tool for LLM, MCP, and flow callers, and an in-process ``astream``
method for API and SSE callers. You write only the ``Agent`` class and its three
class attributes; the base class provides a free ``astream`` for a non-streaming
agent like this one.
"""

from typing import Any

from pydantic import BaseModel
from tai_contract.agent import Agent
from tai_contract.app import tai_app


class GreeterInput(BaseModel):
    name: str


@tai_app.agents.agent("greeter")
class GreeterAgent(Agent):
    tool_name = "greeter"
    tool_description = "Greet the named person."
    ToolInput = GreeterInput

    async def run(self, *, user_message: str = "", **kwargs: Any) -> str:
        name = user_message or "world"
        return f"Hello, {name}!"
