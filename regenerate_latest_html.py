"""
Reassemble and render HTML report using the latest chapter JSON files.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from loguru import logger

# Ensure project modules can be found
sys.path.insert(0, str(Path(__file__).parent))

from ReportEngine.core import ChapterStorage, DocumentComposer
from ReportEngine.ir import IRValidator
from ReportEngine.renderers import HTMLRenderer
from ReportEngine.utils.config import settings


def find_latest_run_dir(chapter_root: Path):
    """
    Locate the latest run output directory under the chapter root.

    Scans all subdirectories under `chapter_root`, filters for those containing
    `manifest.json`, and selects the most recent one by modification time.
    Returns None and logs an error if the directory doesn't exist or no valid
    manifest is found.

    Args:
        chapter_root: Root directory for chapter output (usually settings.CHAPTER_OUTPUT_DIR)

    Returns:
        Path | None: Path to the latest run directory; None if not found.
    """
    if not chapter_root.exists():
        logger.error(f"Chapter directory does not exist: {chapter_root}")
        return None

    run_dirs = []
    for candidate in chapter_root.iterdir():
        if not candidate.is_dir():
            continue
        manifest_path = candidate / "manifest.json"
        if manifest_path.exists():
            run_dirs.append((candidate, manifest_path.stat().st_mtime))

    if not run_dirs:
        logger.error("No chapter directory with manifest.json found")
        return None

    latest_dir = sorted(run_dirs, key=lambda item: item[1], reverse=True)[0][0]
    logger.info(f"Found latest run directory: {latest_dir.name}")
    return latest_dir


def load_manifest(run_dir: Path):
    """
    Read the manifest.json from a single run directory.

    Returns the reportId and metadata dict on success; logs an error and
    returns (None, None) on read or parse failure to allow early termination.

    Args:
        run_dir: Chapter output directory containing manifest.json

    Returns:
        tuple[str | None, dict | None]: (report_id, metadata)
    """
    manifest_path = run_dir / "manifest.json"
    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
        report_id = manifest.get("reportId") or run_dir.name
        metadata = manifest.get("metadata") or {}
        logger.info(f"Report ID: {report_id}")
        if manifest.get("createdAt"):
            logger.info(f"Created at: {manifest['createdAt']}")
        return report_id, metadata
    except Exception as exc:
        logger.error(f"Failed to read manifest: {exc}")
        return None, None


def load_chapters(run_dir: Path):
    """
    Read all chapter JSON files from the specified run directory.

    Reuses ChapterStorage's load_chapters capability to auto-sort by order.
    Prints the chapter count after loading for completeness verification.

    Args:
        run_dir: Chapter directory for a single report

    Returns:
        list[dict]: List of chapter JSON objects (empty list if directory is empty)
    """
    storage = ChapterStorage(settings.CHAPTER_OUTPUT_DIR)
    chapters = storage.load_chapters(run_dir)
    logger.info(f"Loaded chapter count: {len(chapters)}")
    return chapters


def validate_chapters(chapters):
    """
    Perform quick validation of chapter structures using IRValidator.

    Only logs chapters that fail validation with their first three errors;
    does not interrupt the flow. Purpose is to detect potential structural
    issues before reassembly.

    Args:
        chapters: List of chapter JSON objects
    """
    validator = IRValidator()
    invalid = []
    for chapter in chapters:
        ok, errors = validator.validate_chapter(chapter)
        if not ok:
            invalid.append((chapter.get("chapterId") or "unknown", errors))

    if invalid:
        logger.warning(f"{len(invalid)} chapter(s) failed structure validation, continuing with assembly:")
        for chapter_id, errors in invalid:
            preview = "; ".join(errors[:3])
            logger.warning(f"  - {chapter_id}: {preview}")
    else:
        logger.info("Chapter structure validation passed")


def stitch_document(report_id, metadata, chapters):
    """
    Assemble chapters and metadata into a complete Document IR.

    Uses DocumentComposer to handle chapter ordering, global metadata, etc.,
    and prints the assembled chapter and chart counts.

    Args:
        report_id: Report ID (from manifest or directory name)
        metadata: Global metadata from manifest
        chapters: List of loaded chapters

    Returns:
        dict: Complete Document IR object
    """
    composer = DocumentComposer()
    document_ir = composer.build_document(report_id, metadata, chapters)
    logger.info(
        f"Assembly complete: {len(document_ir.get('chapters', []))} chapters, "
        f"{count_charts(document_ir)} charts"
    )
    return document_ir


def count_charts(document_ir):
    """
    Count the number of Chart.js charts in the entire Document IR.

    Iterates through each chapter's blocks, recursively searching for widget
    types starting with `chart.js` to quickly gauge chart scale.

    Args:
        document_ir: Complete Document IR

    Returns:
        int: Total chart count
    """
    chart_count = 0
    for chapter in document_ir.get("chapters", []):
        blocks = chapter.get("blocks", [])
        chart_count += _count_chart_blocks(blocks)
    return chart_count


def _count_chart_blocks(blocks):
    """
    Recursively count Chart.js components in a block list.

    Compatible with nested blocks/list/table structures, ensuring charts
    at all levels are counted.

    Args:
        blocks: Block list at any level

    Returns:
        int: Count of chart.js charts found
    """
    count = 0
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "widget" and str(block.get("widgetType", "")).startswith("chart.js"):
            count += 1
        nested = block.get("blocks")
        if isinstance(nested, list):
            count += _count_chart_blocks(nested)
        if block.get("type") == "list":
            for item in block.get("items", []):
                if isinstance(item, list):
                    count += _count_chart_blocks(item)
        if block.get("type") == "table":
            for row in block.get("rows", []):
                for cell in row.get("cells", []):
                    if isinstance(cell, dict):
                        cell_blocks = cell.get("blocks", [])
                        if isinstance(cell_blocks, list):
                            count += _count_chart_blocks(cell_blocks)
    return count


def save_document_ir(document_ir, base_name, timestamp):
    """
    Save the reassembled Document IR to disk.

    Named as `report_ir_{slug}_{timestamp}_regen.json` and written to
    `settings.DOCUMENT_IR_OUTPUT_DIR`. Ensures directory exists and returns
    the saved path.

    Args:
        document_ir: Fully assembled IR
        base_name: Safe filename segment derived from topic/title
        timestamp: Timestamp string to distinguish multiple regenerations

    Returns:
        Path: Path to the saved IR file
    """
    output_dir = Path(settings.DOCUMENT_IR_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    ir_filename = f"report_ir_{base_name}_{timestamp}_regen.json"
    ir_path = output_dir / ir_filename
    ir_path.write_text(json.dumps(document_ir, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"IR saved: {ir_path}")
    return ir_path


def render_html(document_ir, base_name, timestamp, ir_path=None):
    """
    Render Document IR to HTML using HTMLRenderer and save.

    Saves to `final_reports/html` and prints chart validation statistics
    to observe Chart.js data repair/failure status.

    Args:
        document_ir: Fully assembled IR
        base_name: Filename segment (from report topic/title)
        timestamp: Timestamp string
        ir_path: Optional IR file path; if provided, repairs are auto-saved

    Returns:
        Path: Path to the generated HTML file
    """
    renderer = HTMLRenderer()
    # Pass ir_file_path for auto-save after repairs
    html_content = renderer.render(document_ir, ir_file_path=str(ir_path) if ir_path else None)

    output_dir = Path(settings.OUTPUT_DIR) / "html"
    output_dir.mkdir(parents=True, exist_ok=True)
    html_filename = f"report_html_{base_name}_{timestamp}.html"
    html_path = output_dir / html_filename
    html_path.write_text(html_content, encoding="utf-8")

    file_size_mb = html_path.stat().st_size / (1024 * 1024)
    logger.info(f"HTML generated successfully: {html_path} ({file_size_mb:.2f} MB)")
    logger.info(
        "Chart validation stats: "
        f"total={renderer.chart_validation_stats.get('total', 0)}, "
        f"valid={renderer.chart_validation_stats.get('valid', 0)}, "
        f"repaired={renderer.chart_validation_stats.get('repaired_locally', 0) + renderer.chart_validation_stats.get('repaired_api', 0)}, "
        f"failed={renderer.chart_validation_stats.get('failed', 0)}"
    )
    return html_path


def build_slug(text):
    """
    Convert topic/title to a filesystem-safe segment.

    Keeps only letters/numbers/spaces/underscores/hyphens, converts spaces
    to underscores, and limits to 60 characters to avoid overly long filenames.

    Args:
        text: Original topic or title

    Returns:
        str: Sanitized safe string
    """
    text = str(text or "report")
    sanitized = "".join(c for c in text if c.isalnum() or c in (" ", "-", "_")).strip()
    sanitized = sanitized.replace(" ", "_")
    return sanitized[:60] or "report"


def main():
    """
    Main entry point: Read latest chapters, assemble IR, and render HTML.

    Flow:
        1) Find the latest chapter run directory and read manifest;
        2) Load chapters and perform structure validation (warnings only);
        3) Assemble complete IR and save IR copy;
        4) Render HTML and output path with statistics.

    Returns:
        int: 0 indicates success, other values indicate failure.
    """
    logger.info("🚀 Reassembling and rendering HTML using latest LLM chapters")

    chapter_root = Path(settings.CHAPTER_OUTPUT_DIR)
    latest_run = find_latest_run_dir(chapter_root)
    if not latest_run:
        return 1

    report_id, metadata = load_manifest(latest_run)
    if not report_id or metadata is None:
        return 1

    chapters = load_chapters(latest_run)
    if not chapters:
        logger.error("No chapter JSON found, cannot assemble")
        return 1

    validate_chapters(chapters)

    document_ir = stitch_document(report_id, metadata, chapters)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = build_slug(
        metadata.get("query") or metadata.get("title") or metadata.get("reportId") or report_id
    )

    ir_path = save_document_ir(document_ir, base_name, timestamp)
    # Pass ir_path so repaired charts are auto-saved to IR file
    html_path = render_html(document_ir, base_name, timestamp, ir_path=ir_path)

    logger.info("")
    logger.info("🎉 HTML assembly and rendering complete")
    logger.info(f"IR file: {ir_path.resolve()}")
    logger.info(f"HTML file: {html_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
