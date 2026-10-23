"""Security guardrails, implemented as an ADK plugin (rubric 3.3 + 4.4).

Why a plugin and not per-agent callbacks? A plugin is registered once on the
App and runs for EVERY agent. Per-agent callbacks only run for the agent they
are attached to, and after a transfer the next turn goes straight to the
specialist, so a guardrail on the concierge alone would be skipped.

Hooks used (input -> model -> tool -> output):
  on_user_message_callback -> redacts PII BEFORE the message is saved to the
                              session, so it never reaches Gemini, logs or memory.
  before_model_callback    -> blocks prompt injection and payment data.
                              Returning an LlmResponse skips the model call.
  before_tool_callback     -> validates high-stakes tool arguments.
                              Returning a dict skips the tool.
  after_model_callback     -> output guardrail: scrubs PII from model replies.

Production upgrade: add Model Armor (Google Cloud) for ML-based prompt-injection
and jailbreak detection in before_model_callback.
"""

import logging
import re
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from . import pii

logger = logging.getLogger(__name__)

INJECTION_PHRASES = [
    "ignore previous instructions",
    "ignore all previous",
    "ignore your instructions",
    "system prompt",
    "you are now",
    "developer mode",
    "jailbreak",
]
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HIGH_STAKES_TOOLS = {"book_attraction_ticket"}

REFUSALS = {
    "prompt_injection": (
        "Sorry, I can't help with that request. I'm happy to help you plan "
        "your Desert Peaks Park visit!"
    ),
    "payment_data": (
        "For your safety, please never share payment card details here. "
        "I've removed them from our conversation. How else can I help?"
    ),
}


def _last_user_text(llm_request: LlmRequest) -> str:
    """Returns the text of the most recent visitor message in the request."""
    for content in reversed(llm_request.contents or []):
        if content.role == "user" and content.parts:
            text = " ".join(p.text for p in content.parts if p.text)
            if text:
                return text
    return ""


def _refusal(reason: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=REFUSALS[reason])])
    )


class SecurityPlugin(BasePlugin):
    """Input, tool and output guardrails for every agent in the app."""

    def __init__(self) -> None:
        super().__init__(name="security_plugin")

    async def on_user_message_callback(
        self, *, invocation_context: Any, user_message: types.Content
    ) -> Optional[types.Content]:
        """Redacts PII BEFORE the message is stored in the session."""
        if not user_message or not user_message.parts:
            return None
        texts = [p.text or "" for p in user_message.parts]
        found = sorted({kind for t in texts for kind in pii.find_pii(t)})
        if not found:
            return None
        logger.warning("SECURITY REDACT pii_types=%s", found)
        return types.Content(
            role="user", parts=[types.Part(text=pii.redact_text(t)) for t in texts]
        )

    async def before_model_callback(
        self, *, callback_context: CallbackContext, llm_request: LlmRequest
    ) -> Optional[LlmResponse]:
        text = _last_user_text(llm_request)
        reason = None
        if any(phrase in text.lower() for phrase in INJECTION_PHRASES):
            reason = "prompt_injection"
        elif "[REDACTED_CARD_NUMBER]" in text or "CARD_NUMBER" in pii.find_pii(text):
            reason = "payment_data"
        if reason is None:
            return None  # None = safe, let the model run.
        logger.warning(
            "SECURITY BLOCK reason=%s agent=%s", reason, callback_context.agent_name
        )
        return _refusal(reason)

    async def before_tool_callback(
        self, *, tool: BaseTool, tool_args: dict[str, Any], tool_context: ToolContext
    ) -> Optional[dict]:
        if tool.name not in HIGH_STAKES_TOOLS:
            return None
        try:
            party_size = int(tool_args.get("party_size", 0))
        except (TypeError, ValueError):
            party_size = 0
        if not 1 <= party_size <= 10:
            logger.warning("SECURITY BLOCK reason=bad_party_size tool=%s", tool.name)
            return {
                "status": "error",
                "error_code": "POLICY_PARTY_SIZE",
                "message": "Party size must be between 1 and 10.",
                "next_step": "Ask the visitor for a party size between 1 and 10. For larger groups, suggest contacting group sales.",
            }
        if not DATE.match(str(tool_args.get("date", ""))):
            logger.warning("SECURITY BLOCK reason=bad_date tool=%s", tool.name)
            return {
                "status": "error",
                "error_code": "POLICY_DATE_FORMAT",
                "message": "Date must be in YYYY-MM-DD format.",
                "next_step": "Convert the visitor's date to YYYY-MM-DD and retry.",
            }
        return None  # Arguments are valid, run the real tool.

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> Optional[LlmResponse]:
        """Output guardrail: never echo PII back to the visitor."""
        content = llm_response.content
        if not content or not content.parts:
            return None
        if not any(p.text and pii.find_pii(p.text) for p in content.parts):
            return None
        logger.warning("SECURITY REDACT model_output agent=%s", callback_context.agent_name)
        for p in content.parts:
            if p.text:
                p.text = pii.redact_text(p.text)
        return llm_response
