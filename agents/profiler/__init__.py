"""Profiler agent. Owner: Backend 2.

Public surface:

    from agents.profiler import ProfilerAgent

    agent = ProfilerAgent()                  # model runtime from env, cache on disk
    profile = agent.profile_company("acme", "Acme AB", "https://acme.se")
    agent.save(profile)                      # validated Profile, ready for the API

Every shape comes from ``contracts.models`` — this package defines no schema of
its own.
"""

from .extract import ExtractionError, ExtractionResult, Extractor
from .fetch import CachedFetcher, FetchError, RobotsDenied, SourcePage
from .llm import LLMClient, LLMUnavailable, default_client
from .profiler import ProfilerAgent

__all__ = [
    "CachedFetcher",
    "ExtractionError",
    "ExtractionResult",
    "Extractor",
    "FetchError",
    "LLMClient",
    "LLMUnavailable",
    "ProfilerAgent",
    "RobotsDenied",
    "SourcePage",
    "default_client",
]
