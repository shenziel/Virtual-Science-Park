"""
Pydantic models for the matcher — mirrors contracts/claim.json,
contracts/opportunity.json and contracts/recommendation.json exactly.

These models are used ONLY for validation inside agents/matcher/.
The canonical schema lives in contracts/; if they ever diverge, contracts/ wins.
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

class ClaimKind(str, Enum):
    stated = "stated"
    inferred = "inferred"
    user_confirmed = "user_confirmed"


class Claim(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    field: str
    value: str
    kind: ClaimKind
    evidence_url: Optional[str] = None   # HttpUrl would reject some fixture URLs
    snippet: Optional[str] = None
    retrieved_at: Optional[date] = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return v


# ---------------------------------------------------------------------------
# Profile (a company's collection of claims, used as matcher input)
# ---------------------------------------------------------------------------

class CompanyProfile(BaseModel):
    company_id: str
    company_name: str
    claims: List[Claim] = Field(default_factory=list)

    def claims_by_field(self, field: str) -> List[Claim]:
        return [c for c in self.claims if c.field == field]

    def topics(self) -> List[str]:
        """Return all topic/technology/expertise values as a flat list."""
        relevant_fields = {
            "technologies", "expertise", "topics",
            "products_services", "application_areas",
            "markets", "industries", "priorities", "projects",
        }
        values: List[str] = []
        for c in self.claims:
            if c.field in relevant_fields:
                values.append(c.value.lower())
        return values

    def geographic_focus(self) -> List[str]:
        return [c.value.lower() for c in self.claims if c.field == "geographic_focus"]


# ---------------------------------------------------------------------------
# Opportunity
# ---------------------------------------------------------------------------

class OpportunityType(str, Enum):
    funding = "funding"
    event = "event"
    testbed = "testbed"


class OpportunityFormat(str, Enum):
    online = "online"
    in_person = "in_person"


class Opportunity(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: OpportunityType
    title: str
    url: str
    source: str
    published: Optional[date] = None
    deadline: Optional[date] = None
    event_date: Optional[date] = None
    format: Optional[OpportunityFormat] = None
    audience: Optional[str] = None
    eligibility_text: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    is_simulated: bool = False

    @model_validator(mode="after")
    def _requires_url_and_date(self) -> "Opportunity":
        if not self.url:
            raise ValueError("Opportunity must have a url")
        if self.deadline is None and self.event_date is None and self.published is None:
            raise ValueError("Opportunity must have at least one date field")
        return self

    def relevant_date(self) -> Optional[date]:
        """Return the most action-relevant date: deadline > event_date > published."""
        return self.deadline or self.event_date or self.published


# ---------------------------------------------------------------------------
# Recommendation (matcher output)
# ---------------------------------------------------------------------------

class Recommendation(BaseModel):
    company_id: str
    opportunity_id: str
    score: float = Field(ge=0.0, le=1.0)
    why: str
    matched_claims: List[str] = Field(default_factory=list)   # claim IDs
    caveats: str = "Potential match — eligibility not confirmed."

    @field_validator("score")
    @classmethod
    def _score_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("score must be between 0 and 1")
        return v
