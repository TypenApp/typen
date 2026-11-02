"""
Pro Edition Productivity Suite:
- Custom text expansion snippets (`snippet_engine.py`)
- Application-specific typing profiles (`app_profiles.py`)
- Opt-in local aggregate typing insights (`local_insights.py`)
"""

from autocorrect.productivity.app_profiles import ApplicationProfile, ApplicationProfileManager
from autocorrect.productivity.local_insights import LocalInsightsStore, TypingInsightsSummary
from autocorrect.productivity.snippet_engine import Snippet, SnippetEngine

__all__ = [
    "ApplicationProfile",
    "ApplicationProfileManager",
    "LocalInsightsStore",
    "Snippet",
    "SnippetEngine",
    "TypingInsightsSummary",
]
