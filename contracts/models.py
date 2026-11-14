"""Pydantic models for every shared data shape. Owner: Backend 1.

These models are the source of truth. The JSON Schemas next to this file are
generated from them (`python -m contracts.export_schemas`), and a test fails
if the two drift apart.

Everyone imports from here (`from contracts.models import Claim`) and
validates output before saving. Nobody except Backend 1 edits this file.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Url = Annotated[str, StringConstraints(pattern=r"^https?://\S+$")]
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]*$")]

ELIGIBILITY_CAVEAT = "eligibility not confirmed"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------- claims


class ProfileField(str, Enum):
    """The profile areas from AGENTS.md §1. Every one must be covered or listed in `missing_fields`."""

    what_it_does = "what_it_does"
    products_services = "products_services"
    technologies = "technologies"
    expertise = "expertise"
    application_areas = "application_areas"
    markets = "markets"
    industries = "industries"
    customer_groups = "customer_groups"
    geographic_focus = "geographic_focus"  # only if stated
    development_priorities = "development_priorities"
    projects = "projects"
    collaborations = "collaborations"
    topics = "topics"


class ClaimKind(str, Enum):
    stated = "stated"  # on the company's own website; snippet quotes it
    inferred = "inferred"  # interpreted, summarised, or from an external source
    user_confirmed = "user_confirmed"  # written/approved in the editor; agents never overwrite


class Claim(_Strict):
    id: Slug = Field(description="Unique within the company profile, e.g. 'tech-3'.")
    field: ProfileField
    value: NonEmpty
    kind: ClaimKind
    evidence_url: Url | None = Field(None, description="Required unless kind is user_confirmed.")
    snippet: str | None = Field(None, description="Required (verbatim quote) when kind is stated.")
    retrieved_at: date
    confidence: float = Field(ge=0.0, le=1.0)
    cached_snapshot: bool = Field(False, description="True if the source page was saved by hand.")

    @model_validator(mode="after")
    def _evidence_rules(self) -> Claim:
        if self.kind != ClaimKind.user_confirmed and not self.evidence_url:
            raise ValueError(f"{self.kind.value} claim needs evidence_url")
        if self.kind == ClaimKind.stated and not (self.snippet and self.snippet.strip()):
            raise ValueError("stated claim needs a snippet quoting the source")
        return self


# -------------------------------------------------------------------- profile


class Visibility(str, Enum):
    private = "private"  # owner + BSP admins only
    published = "published"  # everyone


class Profile(_Strict):
    company_id: Slug
    name: NonEmpty
    website: Url
    visibility: Visibility = Visibility.private  # agent output always starts private
    is_simulated: bool = False
    updated_at: datetime
    claims: list[Claim]
    missing_fields: list[ProfileField] = Field(
        default_factory=list, description="Areas the profiler searched for and could not support."
    )

    @model_validator(mode="after")
    def _consistency(self) -> Profile:
        ids = [c.id for c in self.claims]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate claim ids: {sorted(dupes)}")
        covered = {c.field for c in self.claims}
        both = covered & set(self.missing_fields)
        if both:
            raise ValueError(f"fields both covered and missing: {sorted(f.value for f in both)}")
        return self


# --------------------------------------------------------------- opportunity


class OpportunityType(str, Enum):
    funding = "funding"
    event = "event"
    testbed = "testbed"


class OpportunityFormat(str, Enum):
    online = "online"
    in_person = "in_person"


class Opportunity(_Strict):
    id: Slug
    type: OpportunityType
    title: NonEmpty
    url: Url
    source: NonEmpty = Field(description="e.g. 'Vinnova', 'Blue Science Park events'.")
    published: date | None = None
    deadline: date | None = None
    event_date: date | None = None
    format: OpportunityFormat | None = None
    audience: str | None = None
    eligibility_text: str | None = None
    topics: list[NonEmpty] = Field(default_factory=list)
    retrieved_at: date
    is_simulated: bool = False
    cached_snapshot: bool = False

    @model_validator(mode="after")
    def _needs_a_date(self) -> Opportunity:
        if not (self.published or self.deadline or self.event_date):
            raise ValueError("opportunity needs at least one of published, deadline, event_date")
        return self


# ------------------------------------------------------------ recommendation


class Recommendation(_Strict):
    company_id: Slug
    opportunity_id: Slug
    score: float = Field(ge=0.0, le=1.0)
    why: NonEmpty = Field(description="Must reference the matched claims.")
    matched_claims: list[Slug] = Field(min_length=1, description="Claim ids from the company profile.")
    caveats: NonEmpty = Field(description=f"Always contains '{ELIGIBILITY_CAVEAT}'.")

    @model_validator(mode="after")
    def _eligibility_caveat(self) -> Recommendation:
        if ELIGIBILITY_CAVEAT not in self.caveats.lower():
            raise ValueError(f"caveats must contain '{ELIGIBILITY_CAVEAT}'")
        return self


# ------------------------------------------------------------ API payloads
# company_id never appears in request bodies: it comes from the path (checked
# against the session) or from the session itself.


class ClaimCreate(_Strict):
    """POST /companies/{id}/claims. Server sets id, kind=user_confirmed, retrieved_at, confidence=1."""

    field: ProfileField
    value: NonEmpty


class ClaimPatch(_Strict):
    """PATCH /companies/{id}/claims/{claim_id}. Any edit makes the claim user_confirmed."""

    value: NonEmpty


class VisibilityPatch(_Strict):
    """PATCH /companies/{id}/visibility."""

    visibility: Visibility


class FeedbackVerdict(str, Enum):
    save = "save"
    relevant = "relevant"
    not_relevant = "not_relevant"


class FeedbackIn(_Strict):
    """POST /feedback. company_id comes from the session."""

    opportunity_id: Slug
    verdict: FeedbackVerdict


class ChatRequest(_Strict):
    """POST /chat. company_id comes from the session, never from here or the model."""

    message: NonEmpty


class ChatAction(str, Enum):
    answer = "answer"
    redirect = "redirect"  # unrelated request
    clarify = "clarify"  # unclear request
    refuse = "refuse"  # override, role-play, other company's data


class ChatResponse(_Strict):
    reply: NonEmpty
    action: ChatAction


class Role(str, Enum):
    company = "company"
    admin = "admin"
    # Visitors are simply not logged in; they have no account.


class LoginRequest(_Strict):
    email: NonEmpty
    password: NonEmpty


class LoginResponse(_Strict):
    """POST /auth/login. Send `Authorization: Bearer <access_token>` on every other request."""

    access_token: NonEmpty
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: User


class User(_Strict):
    """GET /auth/me. Never contains a password or hash."""

    id: Slug
    email: NonEmpty
    role: Role
    company_id: Slug | None = None

    @model_validator(mode="after")
    def _company_link(self) -> User:
        if (self.role == Role.company) != (self.company_id is not None):
            raise ValueError("company users need a company_id; admins must not have one")
        return self


# Models exported as JSON Schema files in contracts/.
SCHEMAS: dict[str, type[BaseModel]] = {
    "claim": Claim,
    "profile": Profile,
    "opportunity": Opportunity,
    "recommendation": Recommendation,
}
