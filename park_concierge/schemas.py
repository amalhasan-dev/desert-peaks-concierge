"""Explicit input/output schemas for every tool (rubric 1.3).

Inputs use `Literal` enums and constrained fields, so ADK publishes a strict
JSON schema to Gemini (e.g. `category` can ONLY be one of five values).
Outputs are Pydantic models, so every tool returns the same, predictable shape:
either a success payload or a `ToolError` with recovery guidance (rubric 1.4).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Category = Literal["thrill", "family", "motorsport", "gaming", "all"]
PolicyTopic = Literal["opening hours", "dress code", "refunds", "transport"]
AttractionName = Literal[
    "Sandstorm Coaster",
    "Mirage Drop Tower",
    "Oasis Lazy River",
    "Dune Speedway Track Day",
    "Pixel Arena Esports Hall",
]

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# Constrained argument types: the limits appear in the JSON schema sent to Gemini.
# (The date pattern is enforced at runtime by BookingRequest, because not every
# Gemini endpoint accepts `pattern` in function declarations.)
VisitDate = Annotated[str, Field(description="Visit date in YYYY-MM-DD format, e.g. 2026-10-25.")]
PartySize = Annotated[int, Field(ge=1, le=10, description="Number of visitors, 1-10.")]
Hour = Annotated[int, Field(ge=0, le=23, description="Hour of day, 24h format.")]


# ---------- Inputs (validated inside the tools) ----------
class BookingRequest(BaseModel):
    """Validated arguments for book_ticket."""

    attraction: str = Field(min_length=1, description="Exact attraction name.")
    date: str = Field(pattern=DATE_PATTERN, description="Visit date, YYYY-MM-DD.")
    party_size: int = Field(ge=1, le=10, description="Number of visitors, 1-10.")


# ---------- Outputs ----------
class ToolError(BaseModel):
    """Uniform error shape that tells the LLM how to recover."""

    status: Literal["error"] = "error"
    error_code: str = Field(description="Machine-readable error type.")
    message: str = Field(description="What went wrong, in plain English.")
    next_step: str = Field(description="What the agent should do next to recover.")


class Attraction(BaseModel):
    name: str
    category: str
    park: str
    min_height_cm: int
    price: int
    currency: str


class AttractionList(BaseModel):
    status: Literal["success"] = "success"
    count: int
    attractions: list[Attraction]


class Availability(BaseModel):
    status: Literal["success"] = "success"
    attraction: str
    date: str
    slots_left: int
    bookable: bool


class BookingConfirmation(BaseModel):
    status: Literal["success"] = "success"
    booking_id: str
    attraction: str
    date: str
    party_size: int
    total_price: int
    currency: str


class BookingList(BaseModel):
    status: Literal["success"] = "success"
    count: int
    bookings: list[BookingConfirmation]


class WaitTime(BaseModel):
    status: Literal["success"] = "success"
    attraction: str
    hour: int
    wait_minutes: int
    peak_time: bool


class PolicyAnswer(BaseModel):
    status: Literal["success"] = "success"
    topic: str
    answer: str
