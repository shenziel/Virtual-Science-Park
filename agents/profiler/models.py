from datetime import date
from typing import Literal, List, Optional
from pydantic import BaseModel, Field, HttpUrl

ClaimKind = Literal["stated", "inferred", "user_confirmed"]
ProfileField = Literal[
    "products_services",
    "technologies_expertise",
    "markets_industries",
    "geographic_focus",
    "development_priorities",
    "topics_opportunities"
]

class Claim(BaseModel):
    field: ProfileField
    value: str
    kind: ClaimKind
    evidence_url: str
    snippet: str
    retrieved_at: str = Field(default_factory=lambda: date.today().isoformat())
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)

class CompanyProfile(BaseModel):
    company_id: str
    company_name: str
    website_url: str
    claims: List[Claim]
    is_cached: bool = False
    cache_note: Optional[str] = None
