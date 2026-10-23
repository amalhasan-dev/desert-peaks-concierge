"""Observability: structured JSON logs + trace correlation (rubric 4.1-4.3).

* Every log line is ONE JSON object (stdout). On Cloud Run, Cloud Logging
  parses these automatically into `jsonPayload`, so you can filter by
  `jsonPayload.event="tool_outcome"` or `jsonPayload.tool="book_attraction_ticket"`.
* Intent vs outcome: `tool_intent` is logged BEFORE a tool runs (what the agent
  wants to do, with which args); `tool_outcome` AFTER (status, error code,
  latency). Same for model calls (`model_request` / `model_response`).
* Distributed tracing: ADK emits OpenTelemetry spans for every agent, LLM and
  tool call. Each log line carries the current OTel trace/span id
  (`logging.googleapis.com/trace`), so Cloud Logging links logs to the trace in
  Cloud Trace. Enable export with `adk web --trace_to_cloud` /
  `adk deploy cloud_run --trace_to_cloud`.
* PII: every payload passes through pii.redact() before it is logged.
"""

import json
import logging
import os
import sys
import time
from typing import Any, Optional

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from opentelemetry import trace

from . import pii

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON understood by Cloud Logging."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        payload.update(getattr(record, "fields", {}))
        span_ctx = trace.get_current_span().get_span_context()
        if span_ctx.is_valid:
            trace_id = format(span_ctx.trace_id, "032x")
            payload["logging.googleapis.com/trace"] = (
                f"projects/{PROJECT_ID}/traces/{trace_id}" if PROJECT_ID else trace_id
            )
            payload["logging.googleapis.com/spanId"] = format(span_ctx.span_id, "016x")
        return json.dumps(payload, default=str)


def get_json_logger(name: str = "park_concierge.events") -> logging.Logger:
    """Returns a logger that writes JSON lines to stdout (once)."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


class ObservabilityPlugin(BasePlugin):
    """Logs structured intent/outcome events for every agent, model and tool."""

    def __init__(self) -> None:
        super().__init__(name="observability_plugin")
        self.log = get_json_logger()
        self._starts: dict[str, float] = {}

    def _emit(self, event: str, severity: int = logging.INFO, **fields: Any) -> None:
        self.log.log(severity, event, extra={"fields": {"event": event, **pii.redact(fields)}})

    @staticmethod
    def _ids(ctx: Any) -> dict:
        return {
            "invocation_id": getattr(ctx, "invocation_id", None),
            "session_id": getattr(getattr(ctx, "session", None), "id", None),
        }

    # ---- agents ----
    async def before_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> None:
        self._starts[f"agent:{callback_context.invocation_id}:{agent.name}"] = time.monotonic()
        self._emit("agent_start", agent=agent.name, **self._ids(callback_context))

    async def after_agent_callback(
        self, *, agent: BaseAgent, callback_context: CallbackContext
    ) -> None:
        start = self._starts.pop(f"agent:{callback_context.invocation_id}:{agent.name}", None)
        self._emit(
            "agent_end",
            agent=agent.name,
            latency_ms=round((time.monotonic() - start) * 1000) if start else None,
            **self._ids(callback_context),
        )

    # ---- model calls ----
    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> Optional[LlmResponse]:
        self._starts[f"model:{callback_context.invocation_id}:{callback_context.agent_name}"] = time.monotonic()
        self._emit(
            "model_request",
            agent=callback_context.agent_name,
            model=llm_request.model,
            tools=list((llm_request.tools_dict or {}).keys()),
            **self._ids(callback_context),
        )
        return None

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> Optional[LlmResponse]:
        start = self._starts.pop(
            f"model:{callback_context.invocation_id}:{callback_context.agent_name}", None
        )
        usage = llm_response.usage_metadata
        calls = [
            p.function_call.name
            for p in (llm_response.content.parts if llm_response.content else []) or []
            if p.function_call
        ]
        self._emit(
            "model_response",
            agent=callback_context.agent_name,
            latency_ms=round((time.monotonic() - start) * 1000) if start else None,
            prompt_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            cached_tokens=getattr(usage, "cached_content_token_count", None),
            requested_tool_calls=calls,
            **self._ids(callback_context),
        )
        return None

    # ---- tools: intent BEFORE, outcome AFTER ----
    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ) -> Optional[dict]:
        self._starts[f"tool:{tool_context.function_call_id}"] = time.monotonic()
        self._emit(
            "tool_intent",
            agent=tool_context.agent_name,
            tool=tool.name,
            args=tool_args,
            **self._ids(tool_context),
        )
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict,
    ) -> Optional[dict]:
        start = self._starts.pop(f"tool:{tool_context.function_call_id}", None)
        status = result.get("status") if isinstance(result, dict) else None
        self._emit(
            "tool_outcome",
            logging.WARNING if status == "error" else logging.INFO,
            agent=tool_context.agent_name,
            tool=tool.name,
            status=status,
            error_code=result.get("error_code") if isinstance(result, dict) else None,
            latency_ms=round((time.monotonic() - start) * 1000) if start else None,
            **self._ids(tool_context),
        )
        return None

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> Optional[dict]:
        self._emit(
            "tool_exception",
            logging.ERROR,
            agent=tool_context.agent_name,
            tool=tool.name,
            error=repr(error),
            **self._ids(tool_context),
        )
        return None
