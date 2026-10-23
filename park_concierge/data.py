"""Mock data for the Desert Peaks Park concierge (fictional theme park)."""

CURRENCY = "USD"

ATTRACTIONS = {
    "Sandstorm Coaster": {"category": "thrill", "park": "Thrill Mesa", "min_height_cm": 140, "price": 0},
    "Mirage Drop Tower": {"category": "thrill", "park": "Thrill Mesa", "min_height_cm": 122, "price": 0},
    "Oasis Lazy River": {"category": "family", "park": "Oasis Water Park", "min_height_cm": 0, "price": 0},
    "Dune Speedway Track Day": {"category": "motorsport", "park": "Dune Speedway", "min_height_cm": 150, "price": 120},
    "Pixel Arena Esports Hall": {"category": "gaming", "park": "Pixel Arena", "min_height_cm": 0, "price": 30},
}

PARK_TICKETS = {"Thrill Mesa": 90, "Oasis Water Park": 70, "Dune Speedway": 0, "Pixel Arena": 0}

# Remaining capacity per attraction per date (anything not listed = 50 slots).
CAPACITY = {
    ("Sandstorm Coaster", "2026-10-23"): 0,
    ("Dune Speedway Track Day", "2026-10-23"): 4,
}

PARK_POLICIES = {
    "opening hours": "Parks open 16:00-24:00 on weekdays and 12:00-24:00 on weekends.",
    "dress code": "Comfortable clothing is recommended; swimwear only inside Oasis Water Park.",
    "refunds": "Tickets are refundable up to 48 hours before the visit date.",
    "transport": "Free shuttle buses run from the city center every 30 minutes.",
}
