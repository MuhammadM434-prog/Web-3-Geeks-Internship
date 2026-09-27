"""Recommendation engine: hard eligibility filters, then transparent scoring.
A high score can never rescue a property that failed a hard filter (unavailable,
over budget, wrong area, missing required bedrooms)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.knowledge_base import PROPERTIES


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


@dataclass
class RecommendationRequest:
    budget: int | None = None
    city: str | None = None
    area: str | None = None
    bedrooms: int | None = None
    purpose: str = "buyer"  # buyer | rental | commercial | investment
    amenities: list[str] = field(default_factory=list)


_PURPOSE_TO_LISTING = {
    "buyer": {"sale"}, "rental": {"rent"}, "investment": {"sale", "rent"},
    "commercial": {"sale", "rent"},
}


def search_properties(request: RecommendationRequest) -> list[dict[str, Any]]:
    """Hard-filtered candidate matches -- may still include unavailable
    properties (search can be fuzzy); the availability check that actually
    gates a recommendation happens separately in ``availability_checker``."""
    candidates = []
    allowed_listing_types = _PURPOSE_TO_LISTING.get(_norm(request.purpose), {"sale", "rent"})
    for prop in PROPERTIES:
        if prop["listing_type"] not in allowed_listing_types:
            continue
        if request.city and _norm(prop["city"]) != _norm(request.city):
            continue
        if request.area and _norm(request.area) not in _norm(prop["area"]):
            continue
        if request.bedrooms and (prop["bedrooms"] or 0) < request.bedrooms:
            continue
        if request.budget and prop["price"] > request.budget:
            continue
        if request.amenities:
            have = {_norm(a) for a in prop["amenities"]}
            if not all(_norm(a) in have for a in request.amenities):
                continue
        candidates.append(prop)
    return candidates


def rank(request: RecommendationRequest, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for prop in candidates:
        score = 0.0
        reasons = []
        if request.budget:
            headroom = (request.budget - prop["price"]) / request.budget
            score += max(0.0, 35 * (1 - abs(headroom)))
            reasons.append("within budget")
        if request.bedrooms and prop["bedrooms"] == request.bedrooms:
            score += 20
            reasons.append(f"exact {request.bedrooms}-bedroom match")
        if request.amenities:
            score += 20
            reasons.append("has requested amenities")
        scored.append({**prop, "match_score": round(score, 2), "match_reasons": reasons})
    return sorted(scored, key=lambda p: p["match_score"], reverse=True)


def recommend(request: RecommendationRequest, only_available: bool = True) -> list[dict[str, Any]]:
    candidates = search_properties(request)
    if only_available:
        candidates = [p for p in candidates if p["status"] == "available"]
    return rank(request, candidates)
