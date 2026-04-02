"""
Report Engine Intermediate Representation (IR) definition and validation tools.

This module exposes a unified Schema definition and validator, shared by prompt
construction, chapter generation, and final assembly workflows, ensuring
consistent structure from LLM output to rendering.
"""

from .schema import (
    IR_VERSION,
    CHAPTER_JSON_SCHEMA,
    CHAPTER_JSON_SCHEMA_TEXT,
    ALLOWED_BLOCK_TYPES,
    ALLOWED_INLINE_MARKS,
    ENGINE_AGENT_TITLES,
)
from .validator import IRValidator

__all__ = [
    "IR_VERSION",
    "CHAPTER_JSON_SCHEMA",
    "CHAPTER_JSON_SCHEMA_TEXT",
    "ALLOWED_BLOCK_TYPES",
    "ALLOWED_INLINE_MARKS",
    "ENGINE_AGENT_TITLES",
    "IRValidator",
]
