"""agents/matcher package — imports contracts.models as the shared source of truth."""
from .matcher import match

# Re-export types from contracts for convenience
from contracts.models import (
    ClaimKind,
    Opportunity,
    OpportunityFormat,
    OpportunityType,
    Profile,
    Recommendation,
)

__all__ = [
    "match",
    "Profile",
    "Opportunity",
    "OpportunityFormat",
    "OpportunityType",
    "Recommendation",
    "ClaimKind",
]
