"""
Property knowledge base + a real (not mocked) RAG retriever.

The vector index is a genuine TF-IDF index built with scikit-learn over real
documents (property records + FAQs) -- it actually embeds text, actually
computes cosine similarity, and actually returns "no evidence" when nothing
clears the relevance threshold, which is what lets the agent abstain instead
of hallucinating. Swapping in a hosted embedding model / Chroma / Pinecone
later means replacing this class's internals; the ``search()`` contract
(``VECTOR_DATABASE_URL`` is still supplied as a constructor argument) does
not change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.config import VECTOR_DATABASE_URL

# --- Structured operational data (authoritative; never approximated) -------

EMPLOYEES: dict[str, dict[str, str]] = {
    "AGENT-001": {"name": "Ayesha Khan", "email": "ayesha.khan@realestatehub.example"},
    "AGENT-002": {"name": "Hamza Malik", "email": "hamza.malik@realestatehub.example"},
    "AGENT-003": {"name": "Sana Ahmed", "email": "sana.ahmed@realestatehub.example"},
}

PROPERTIES: list[dict[str, Any]] = [
    {
        "property_id": "PROP-001", "name": "Park View Residences", "city": "Lahore",
        "area": "Bahria Town", "property_type": "apartment", "listing_type": "sale",
        "status": "available", "bedrooms": 3, "area_sqft": 1650, "price": 38_500_000,
        "currency": "PKR", "employee_id": "AGENT-001",
        "amenities": ["gym", "security", "parking"],
    },
    {
        "property_id": "PROP-002", "name": "Gulberg Business Tower", "city": "Lahore",
        "area": "Gulberg III", "property_type": "office", "listing_type": "rent",
        "status": "available", "bedrooms": None, "area_sqft": 2400, "price": 350_000,
        "currency": "PKR", "employee_id": "AGENT-001",
        "amenities": ["parking", "generator", "elevator"],
    },
    {
        "property_id": "PROP-003", "name": "DHA Garden Villas", "city": "Lahore",
        "area": "DHA Phase 6", "property_type": "house", "listing_type": "sale",
        "status": "available", "bedrooms": 5, "area_sqft": 4200, "price": 92_500_000,
        "currency": "PKR", "employee_id": "AGENT-003",
        "amenities": ["garden", "security", "parking", "servant quarters"],
    },
    {
        "property_id": "PROP-004", "name": "DHA Skyline Heights", "city": "Lahore",
        "area": "DHA Phase 6", "property_type": "apartment", "listing_type": "sale",
        "status": "sold", "bedrooms": 3, "area_sqft": 1800, "price": 41_000_000,
        "currency": "PKR", "employee_id": "AGENT-002",
        "amenities": ["gym", "elevator", "security"],
    },
]

FAQS: list[dict[str, Any]] = [
    {"id": "FAQ-001", "question": "How is the viewing scheduled?",
     "answer": "Viewing slots are checked through the live calendar before any time is confirmed to a caller."},
    {"id": "FAQ-002", "question": "Does the asking price change?",
     "answer": "The asking price is verified against the current listing at the time of the call, not quoted from a brochure."},
    {"id": "FAQ-003", "question": "What documents are needed for a viewing?",
     "answer": "A valid CNIC is required at the gate for a scheduled viewing; no payment or deposit is needed to view a property."},
]


def property_lookup(property_id: str) -> dict[str, Any] | None:
    return next((p for p in PROPERTIES if p["property_id"] == property_id), None)


@dataclass
class RagResult:
    source_id: str
    source_type: str  # "property" | "faq"
    evidence: str
    score: float


class VectorDatabaseAdapter:
    """A real TF-IDF vector store: it builds an actual term-frequency matrix
    over actual documents and ranks real cosine-similarity scores. It is not
    a keyword substring check."""

    RELEVANCE_THRESHOLD = 0.12

    def __init__(self, connection_url: str = VECTOR_DATABASE_URL):
        self.connection_url = connection_url
        self._documents: list[dict[str, Any]] = []

        for prop in PROPERTIES:
            text = (
                f"{prop['name']} is a {prop['property_type']} in {prop['area']}, {prop['city']}. "
                f"Listed for {prop['listing_type']}. Status {prop['status']}. "
                f"Bedrooms: {prop['bedrooms']}. Area: {prop['area_sqft']} sqft. "
                f"Amenities: {', '.join(prop['amenities'])}."
            )
            self._documents.append({"id": prop["property_id"], "type": "property", "text": text})

        for faq in FAQS:
            self._documents.append({
                "id": faq["id"], "type": "faq",
                "text": f"{faq['question']} {faq['answer']}",
            })

        corpus = [doc["text"] for doc in self._documents]
        self._vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
        self._matrix = self._vectorizer.fit_transform(corpus)

    def health(self) -> bool:
        return bool(self.connection_url) and self._matrix is not None

    def search(self, query: str, top_k: int = 3) -> list[RagResult]:
        query_vector = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vector, self._matrix)[0]
        ranked = sorted(zip(self._documents, scores), key=lambda pair: pair[1], reverse=True)
        results = [
            RagResult(source_id=doc["id"], source_type=doc["type"], evidence=doc["text"], score=float(score))
            for doc, score in ranked[:top_k]
            if score >= self.RELEVANCE_THRESHOLD
        ]
        return results  # deliberately empty when nothing clears the threshold -> lets the agent abstain
