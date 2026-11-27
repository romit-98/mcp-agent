"""The agent: a small LangGraph loop (model -> tools -> model ...) with a step limit.

Written as an explicit graph rather than a prebuilt agent so phase 6 can add an approval
interrupt between "model decided to call a write tool" and "tool runs".
"""

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent.identities import USERS, User
from agent.keycloak import tokens_for
from agent.prompts import system_prompt
from agent.settings import Settings, get_settings


@dataclass
class ToolStep:
    tool: str
    args: dict[str, Any]
    result: str
    is_error: bool


@dataclass
class AgentRun:
    user: str
    target: str
    prompt: str
    answer: str
    steps: list[ToolStep] = field(default_factory=list)
    stopped: str = "completed"  # or "step_limit"
    input_tokens: int = 0
    output_tokens: int = 0


SERVERS = {  # connection name -> (Keycloak audience, URL setting)
    "crm": ("mcp-crm", "crm_url"),
    "finance": ("mcp-finance", "finance_url"),
    "email": ("mcp-email", "email_url"),
    "knowledge": ("mcp-knowledge", "knowledge_url"),
}


async def connections(user: User, s: Settings) -> dict[str, dict[str, Any]]:
    """Which MCP servers to load tools from, for the configured target."""
    if s.target == "baseline":
        return {"baseline": {"transport": "streamable_http", "url": s.baseline_url}}
    tokens = await tokens_for(s, user.username, [aud for aud, _ in SERVERS.values()])
    return {
        name: {
            "transport": "streamable_http",
            "url": getattr(s, url_setting),
            "headers": {"Authorization": f"Bearer {tokens[audience]}"},
        }
        for name, (audience, url_setting) in SERVERS.items()
        if audience in tokens  # no token, no tools: Keycloak decided the user can't use it
    }


def build_graph(model: ChatAnthropic, tools: list[Any]) -> Any:
    bound = model.bind_tools(tools)

    async def call_model(state: MessagesState) -> dict[str, Any]:
        return {"messages": [await bound.ainvoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "model")
    return graph.compile()


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif isinstance(block, str):
            parts.append(block)
    return "".join(parts)


def summarise(user: str, target: str, prompt: str, messages: list[Any], stopped: str) -> AgentRun:
    run = AgentRun(user=user, target=target, prompt=prompt, answer="", stopped=stopped)
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                calls[tc["id"]] = (tc["name"], tc["args"])
            if m.usage_metadata:
                run.input_tokens += m.usage_metadata.get("input_tokens", 0)
                run.output_tokens += m.usage_metadata.get("output_tokens", 0)
            if not m.tool_calls:
                run.answer = _text(m.content)
        elif isinstance(m, ToolMessage):
            name, args = calls.get(m.tool_call_id, (m.name or "?", {}))
            run.steps.append(
                ToolStep(name, args, _text(m.content) or json.dumps(m.content), m.status == "error")
            )
    return run


async def run_agent(username: str, prompt: str, settings: Settings | None = None) -> AgentRun:
    s = settings or get_settings()
    user = USERS[username]
    client = MultiServerMCPClient(await connections(user, s))
    tools = await client.get_tools()
    model = ChatAnthropic(model=s.model, max_tokens=s.max_tokens, max_retries=3)
    graph = build_graph(model, tools)
    state: dict[str, Any] = {"messages": [SystemMessage(system_prompt(user)), HumanMessage(prompt)]}
    stopped = "completed"
    try:
        # Each round is a model step and a tools step, plus the first model call.
        state = await graph.ainvoke(state, config={"recursion_limit": 2 * s.max_steps + 1})
    except GraphRecursionError:
        stopped = "step_limit"
    return summarise(username, s.target, prompt, state["messages"], stopped)
