"""Custom function tools for the Desert Peaks Park concierge.

Design rules (rubric section 1):
  * Specific names (`check_attraction_availability`, not `check`).
  * Full docstrings: ADK sends the name, type hints and docstring to Gemini.
  * Strict schemas: `Literal` enums for inputs, Pydantic models for outputs
    (see schemas.py).
  * Guided errors: every failure returns a ToolError with a `next_step` that
    tells the LLM how to recover, instead of raising.
"""

import uuid

from google.adk.tools.tool_context import ToolContext
from opentelemetry import trace
from pydantic import ValidationError

from . import data
from .schemas import (
    Attraction,
    AttractionList,
    AttractionName,
    Availability,
    BookingConfirmation,
    BookingList,
    BookingRequest,
    Category,
    Hour,
    PartySize,
    PolicyAnswer,
    PolicyTopic,
    ToolError,
    VisitDate,
    WaitTime,
)

tracer = trace.get_tracer(__name__)

_UNKNOWN_ATTRACTION_STEP = (
    "Call list_attractions_by_category with category='all' to get the exact "
    "attraction names, then retry with one of them."
)


def _unknown_attraction(name: str) -> dict:
    return ToolError(
        error_code="UNKNOWN_ATTRACTION",
        message=f"'{name}' is not a Desert Peaks Park attraction.",
        next_step=_UNKNOWN_ATTRACTION_STEP,
    ).model_dump()


def list_attractions_by_category(category: Category, tool_context: ToolContext) -> dict:
    """Lists Desert Peaks Park attractions that match a visitor interest.

    Args:
      category: The visitor's interest. One of "thrill", "family",
        "motorsport", "gaming", or "all" for every attraction.

    Returns:
      AttractionList (status, count, attractions with park, minimum height and
      price) or ToolError.
    """
    matches = [
        Attraction(name=name, currency=data.CURRENCY, **info)
        for name, info in data.ATTRACTIONS.items()
        if category == "all" or info["category"] == category
    ]
    # Day 3: remember the visitor's interest so other agents can use it.
    interests = list(tool_context.state.get("interests", []))
    if category != "all" and category not in interests:
        interests.append(category)
        tool_context.state["interests"] = interests
    if not matches:
        return ToolError(
            error_code="NO_MATCHES",
            message=f"No attractions in category '{category}'.",
            next_step="Retry with category='all' and suggest the closest options.",
        ).model_dump()
    return AttractionList(count=len(matches), attractions=matches).model_dump()


def check_attraction_availability(attraction: AttractionName, date: VisitDate) -> dict:
    """Checks how many booking slots are left for an attraction on a date.

    Always call this before book_attraction_ticket.

    Args:
      attraction: Exact attraction name as returned by list_attractions_by_category.
      date: Visit date in YYYY-MM-DD format, e.g. "2026-10-25".

    Returns:
      Availability (slots_left, bookable) or ToolError.
    """
    if attraction not in data.ATTRACTIONS:
        return _unknown_attraction(attraction)
    try:
        BookingRequest(attraction=attraction, date=date, party_size=1)
    except ValidationError:
        return ToolError(
            error_code="INVALID_DATE",
            message=f"'{date}' is not a valid date.",
            next_step="Ask the visitor for the date and convert it to YYYY-MM-DD.",
        ).model_dump()
    slots = data.CAPACITY.get((attraction, date), 50)
    return Availability(
        attraction=attraction, date=date, slots_left=slots, bookable=slots > 0
    ).model_dump()


def book_attraction_ticket(
    attraction: AttractionName,
    date: VisitDate,
    party_size: PartySize,
    tool_context: ToolContext,
) -> dict:
    """Books tickets for an attraction. HIGH-STAKES: requires visitor confirmation.

    Only call after check_attraction_availability shows enough slots, and after
    the visitor has confirmed attraction, date and party size.

    Args:
      attraction: Exact attraction name.
      date: Visit date in YYYY-MM-DD format.
      party_size: Number of visitors, between 1 and 10.

    Returns:
      BookingConfirmation (booking_id, total_price) or ToolError.
    """
    with tracer.start_as_current_span("book_attraction_ticket.validate") as span:
        span.set_attribute("attraction", attraction)
        span.set_attribute("party_size", party_size)
        try:
            request = BookingRequest(attraction=attraction, date=date, party_size=party_size)
        except ValidationError as e:
            fields = ", ".join(str(err["loc"][0]) for err in e.errors())
            return ToolError(
                error_code="INVALID_BOOKING_REQUEST",
                message=f"Invalid value(s) for: {fields}.",
                next_step="Ask the visitor to correct these values (party size 1-10, date YYYY-MM-DD), then retry.",
            ).model_dump()

    if request.attraction not in data.ATTRACTIONS:
        return _unknown_attraction(request.attraction)

    availability = check_attraction_availability(request.attraction, request.date)
    if availability["status"] != "success":
        return availability
    if availability["slots_left"] < request.party_size:
        return ToolError(
            error_code="NOT_ENOUGH_SLOTS",
            message=f"Only {availability['slots_left']} slots left on {request.date}.",
            next_step="Offer the visitor a different date or a smaller party size.",
        ).model_dump()

    # Idempotency: don't create the same booking twice.
    bookings = list(tool_context.state.get("user:bookings", []))
    for existing in bookings:
        if (existing["attraction"], existing["date"], existing["party_size"]) == (
            request.attraction, request.date, request.party_size
        ):
            return ToolError(
                error_code="DUPLICATE_BOOKING",
                message=f"This booking already exists (id {existing['booking_id']}).",
                next_step="Tell the visitor they are already booked; do not book again.",
            ).model_dump()

    info = data.ATTRACTIONS[request.attraction]
    unit_price = info["price"] + data.PARK_TICKETS.get(info["park"], 0)
    booking = BookingConfirmation(
        booking_id=uuid.uuid4().hex[:8].upper(),
        attraction=request.attraction,
        date=request.date,
        party_size=request.party_size,
        total_price=unit_price * request.party_size,
        currency=data.CURRENCY,
    )
    # "user:" prefix = persists across sessions for this user (Day 3).
    bookings.append(booking.model_dump())
    tool_context.state["user:bookings"] = bookings
    return booking.model_dump()


def list_my_bookings(tool_context: ToolContext) -> dict:
    """Lists every booking this visitor has made, including in earlier sessions.

    Returns:
      BookingList (count and bookings; may be empty).
    """
    raw = tool_context.state.get("user:bookings", [])
    bookings = [BookingConfirmation(**b) for b in raw]
    return BookingList(count=len(bookings), bookings=bookings).model_dump()


def estimate_queue_wait_time(attraction: AttractionName, hour: Hour) -> dict:
    """Estimates the queue wait time for an attraction at a given hour.

    Args:
      attraction: Exact attraction name as returned by list_attractions_by_category.
      hour: Hour of day in 24h format (0-23), e.g. 20 for 8 pm.

    Returns:
      WaitTime (wait_minutes, peak_time) or ToolError.
    """
    if attraction not in data.ATTRACTIONS:
        return _unknown_attraction(attraction)
    if not 0 <= hour <= 23:
        return ToolError(
            error_code="INVALID_HOUR",
            message=f"{hour} is not a valid hour.",
            next_step="Convert the visitor's time to a 24h hour between 0 and 23 and retry.",
        ).model_dump()
    peak = 19 <= hour <= 21  # evenings are busiest
    base = 45 if data.ATTRACTIONS[attraction]["category"] == "thrill" else 15
    return WaitTime(
        attraction=attraction, hour=hour, wait_minutes=base * (2 if peak else 1), peak_time=peak
    ).model_dump()


def get_park_policy(topic: PolicyTopic) -> dict:
    """Returns the official Desert Peaks Park policy for a topic.

    Args:
      topic: One of "opening hours", "dress code", "refunds", "transport".

    Returns:
      PolicyAnswer or ToolError.
    """
    answer = data.PARK_POLICIES.get(topic)
    if answer is None:
        return ToolError(
            error_code="UNKNOWN_POLICY_TOPIC",
            message=f"No official policy for '{topic}'.",
            next_step="Call search_agent to look it up on the web, and say the answer is unofficial.",
        ).model_dump()
    return PolicyAnswer(topic=topic, answer=answer).model_dump()
