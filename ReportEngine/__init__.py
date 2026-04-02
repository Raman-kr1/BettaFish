"""
Report Engine.

An intelligent report generation AI agent implementation that aggregates 
Markdown and forum discussions from three sub-engines (Query/Media/Insight),
ultimately producing structured HTML reports.
"""

from .agent import ReportAgent, create_agent

__version__ = "1.0.0"
__author__ = "Report Engine Team"

__all__ = ["ReportAgent", "create_agent"]
