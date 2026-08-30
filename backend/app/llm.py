"""
Thin abstraction over the LLM provider so swapping providers is a one-file
change. Implemented against Gemini's free tier (see DECISION_LOG.md for why:
no Anthropic API key was available during development). Both Gemini and
Claude support the same OpenAI-style "tools" concept, so `agent.py` is
written against this neutral interface, not against Gemini's SDK directly.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

import google.generativeai as genai

from . import config

genai.configure(api_key=config.GEMINI_API_KEY)


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    text: Optional[str]
    tool_calls: list[ToolCall] = field(default_factory=list)


def _to_gemini_tools(tool_schemas: list[dict]) -> list[dict]:
    """Converts our neutral tool schema (OpenAI/Anthropic-style JSON schema)
    into Gemini's function-declaration format."""
    declarations = []
    for t in tool_schemas:
        declarations.append({
            "name": t["name"],
            "description": t["description"],
            "parameters": t["parameters"],
        })
    return [{"function_declarations": declarations}]


def call_llm(system_prompt: str, messages: list[dict], tool_schemas: list[dict]) -> LLMResponse:
    """
    messages: list of {"role": "user"|"model", "parts": [...]} in Gemini's
    chat format. agent.py owns the conversation state and history shape.
    """
    model = genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        system_instruction=system_prompt,
        tools=_to_gemini_tools(tool_schemas) if tool_schemas else None,
    )
    response = model.generate_content(messages)

    text_parts = []
    tool_calls = []
    for part in response.candidates[0].content.parts:
        if getattr(part, "text", None):
            text_parts.append(part.text)
        fn = getattr(part, "function_call", None)
        if fn and fn.name:
            tool_calls.append(ToolCall(name=fn.name, arguments=dict(fn.args)))

    return LLMResponse(text="\n".join(text_parts) if text_parts else None, tool_calls=tool_calls)
