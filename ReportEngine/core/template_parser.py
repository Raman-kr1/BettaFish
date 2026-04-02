"""
Markdown模板切片工具。

LLM需要“按章调用”，因此必须把Markdown模板解析为结构化章节队列。
这里通过轻量正则和缩进启发式，兼容“# 标题”与
“- **1.0 标题** /   - 1.1 子标题”等多种写法。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

SECTION_ORDER_STEP = 10


@dataclass
class TemplateSection:
    """
    Template section entity.

    Records title, slug, order, depth, raw title, chapter number, and outline,
    facilitating reference in prompts by subsequent nodes while maintaining anchor consistency.
    """

    title: str
    slug: str
    order: int
    depth: int
    raw_title: str
    number: str = ""
    chapter_id: str = ""
    outline: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """
        Serialize the section entity to a dictionary.

        This structure is widely used in prompt context and layout/word budget node inputs.
        """
        return {
            "title": self.title,
            "slug": self.slug,
            "order": self.order,
            "depth": self.depth,
            "number": self.number,
            "chapterId": self.chapter_id,
            "outline": self.outline,
        }


# Parsing expressions deliberately avoid `.*` to maintain matching determinism
# and mitigate regex DoS risks common in untrusted template text.
heading_pattern = re.compile(
    r"""
    (?P<marker>\#{1,6})       # Markdown heading marker
    [ \t]+                    # Required whitespace
    (?P<title>[^\r\n]+)       # Title text without newlines
    """,
    re.VERBOSE,
)
bullet_pattern = re.compile(
    r"""
    (?P<marker>[-*+])         # List item bullet
    [ \t]+
    (?P<title>[^\r\n]+)
    """,
    re.VERBOSE,
)
number_pattern = re.compile(
    r"""
    (?P<num>
        (?:0|[1-9]\d*)
        (?:\.(?:0|[1-9]\d*))*
    )
    (?:
        (?:[ \t\u00A0\u3000、:：-]+|\.(?!\d))+
        (?P<label>[^\r\n]*)
    )?
    """,
    re.VERBOSE,
)


def parse_template_sections(template_md: str) -> List[TemplateSection]:
    """
    将Markdown模板切分成章节列表（按大标题）。

    返回的每个TemplateSection都携带slug/order/章节号，
    方便后续分章调用与锚点生成。解析时会同时兼容
    “# 标题”“无符号编号”“列表提纲”等不同写法。

    参数:
        template_md: 模板Markdown全文。

    返回:
        list[TemplateSection]: 结构化的章节序列。
    """

    sections: List[TemplateSection] = []
    current: Optional[TemplateSection] = None
    order = SECTION_ORDER_STEP
    used_slugs = set()

    for raw_line in template_md.splitlines():
        if not raw_line.strip():
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        meta = _classify_line(stripped, indent)
        if not meta:
            continue

        if meta["is_section"]:
            slug = _ensure_unique_slug(meta["slug"], used_slugs)
            section = TemplateSection(
                title=meta["title"],
                slug=slug,
                order=order,
                depth=meta["depth"],
                raw_title=meta["raw"],
                number=meta["number"],
            )
            sections.append(section)
            current = section
            order += SECTION_ORDER_STEP
            continue

        # Outline entry
        if current:
            current.outline.append(meta["title"])

    for idx, section in enumerate(sections, start=1):
        # Generate a stable chapter_id for each section, facilitating subsequent references
        section.chapter_id = f"S{idx}"

    return sections


def _classify_line(stripped: str, indent: int) -> Optional[dict]:
    """
    Classify a line based on indentation and symbols.

    Uses regex to determine if the current line is a chapter title, outline,
    or regular list item, and derives depth/slug/number information.

    Args:
        stripped: Original line with leading/trailing whitespace removed.
        indent: Number of leading spaces, used to distinguish hierarchy levels.

    Returns:
        dict | None: Recognized metadata; returns None if unrecognizable.
    """

    heading_match = heading_pattern.fullmatch(stripped)
    if heading_match:
        level = len(heading_match.group("marker"))
        payload = _strip_markup(heading_match.group("title").strip())
        title_info = _split_number(payload)
        slug = _build_slug(title_info["number"], title_info["title"])
        return {
            "is_section": level <= 2,
            "depth": level,
            "title": title_info["display"],
            "raw": payload,
            "number": title_info["number"],
            "slug": slug,
        }

    bullet_match = bullet_pattern.fullmatch(stripped)
    if bullet_match:
        payload = _strip_markup(bullet_match.group("title").strip())
        title_info = _split_number(payload)
        slug = _build_slug(title_info["number"], title_info["title"])
        is_section = indent <= 1
        depth = 1 if indent <= 1 else 2
        return {
            "is_section": is_section,
            "depth": depth,
            "title": title_info["display"],
            "raw": payload,
            "number": title_info["number"],
            "slug": slug,
        }

    # 兼容“1.1 ...”没有前缀符号的行
    number_match = number_pattern.fullmatch(stripped)
    if number_match and number_match.group("label"):
        payload = stripped
        title = number_match.group("label").strip()
        number = number_match.group("num")
        slug = _build_slug(number, title)
        is_section = indent == 0 and number.count(".") <= 1
        depth = 1 if is_section else 2
        display = f"{number} {title}" if title else number
        return {
            "is_section": is_section,
            "depth": depth,
            "title": display,
            "raw": payload,
            "number": number,
            "slug": slug,
        }

    return None


def _strip_markup(text: str) -> str:
    """Remove wrapping emphasis markers like ** or __ to avoid interfering with title matching."""
    if text.startswith(("**", "__")) and text.endswith(("**", "__")) and len(text) > 4:
        return text[2:-2].strip()
    return text


def _split_number(payload: str) -> dict:
    """
    Split number and title.

    For example, `1.2 Market Trends` is split into number=1.2, label=Market Trends,
    and provides display for backfilling the title.

    Args:
        payload: Original title string.

    Returns:
        dict: Contains number/title/display.
    """
    match = number_pattern.fullmatch(payload)
    number = match.group("num") if match else ""
    label = match.group("label") if match else payload
    label = (label or "").strip()
    display = f"{number} {label}".strip() if number else label or payload
    title_core = label or payload
    return {
        "number": number,
        "title": title_core,
        "display": display,
    }


def _build_slug(number: str, title: str) -> str:
    """
    Generate anchor from number/title, preferring to reuse number, slugifying title when missing.

    Args:
        number: Chapter number.
        title: Title text.

    Returns:
        str: Slug in the form `section-1-0`.
    """
    if number:
        token = number.replace(".", "-")
    else:
        token = _slugify_text(title)
    token = token or "section"
    return f"section-{token}"


def _slugify_text(text: str) -> str:
    """
    Normalize and transliterate any text to get a URL-friendly slug fragment.

    Normalizes case, removes special symbols, and preserves Chinese characters for readable anchors.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("·", "-").replace(" ", "-")
    text = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-").lower()


def _ensure_unique_slug(slug: str, used: set) -> str:
    """
    Auto-append sequence number if slug is duplicate, until unique in the used set.

    Uses `-2/-3...` approach to ensure identical titles don't produce duplicate anchors.

    Args:
        slug: Initial slug.
        used: Set of already used slugs.

    Returns:
        str: Deduplicated slug.
    """
    if slug not in used:
        used.add(slug)
        return slug
    base = slug
    idx = 2
    while slug in used:
        slug = f"{base}-{idx}"
        idx += 1
    used.add(slug)
    return slug


__all__ = ["TemplateSection", "parse_template_sections"]
