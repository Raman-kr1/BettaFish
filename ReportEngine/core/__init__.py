"""
Report Engine core toolkit collection.

This package encapsulates three fundamental capabilities: template slicing,
chapter storage, and chapter stitching. All upper-layer nodes reuse these
tools to ensure structural consistency.
"""

from .template_parser import TemplateSection, parse_template_sections
from .chapter_storage import ChapterStorage
from .stitcher import DocumentComposer

__all__ = [
    "TemplateSection",
    "parse_template_sections",
    "ChapterStorage",
    "DocumentComposer",
]
