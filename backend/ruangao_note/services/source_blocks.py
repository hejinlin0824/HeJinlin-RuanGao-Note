"""Convert MinerU layout output into page-linked evidence blocks.

Raw MinerU artifacts are retained separately. Cleanup findings are review hints only;
this module never deletes OCR text or rewrites the original artifacts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ruangao_note.domain.models import ProcessingRun, SourceBlock

_WATERMARK_PATTERNS = (
    re.compile(r"\barxiv\s*:\s*\d{4}\.\d{4,5}\b", re.IGNORECASE),
    re.compile(r"\barxiv\.org/(?:abs|pdf)/", re.IGNORECASE),
    re.compile(r"\bdoi\s*:\s*10\.\d{4,9}/", re.IGNORECASE),
    re.compile(r"\bpreprint\b", re.IGNORECASE),
)
_FOOTNOTE_PREFIX = re.compile(
    r"^\s*(?:\[\d{1,3}\]|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|注\s*\d*[:：])\s*"
)

_AUXILIARY_TYPES = {
    "header": "header",
    "page_header": "header",
    "footer": "footer",
    "page_footer": "footer",
    "page_number": "page_number",
    "aside_text": "aside_text",
    "page_aside_text": "aside_text",
    "page_footnote": "footnote",
    "footnote": "footnote",
}


def _as_text(value: Any) -> str:
    """Flatten MinerU text spans without rendering metadata as user-visible text."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_as_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if not isinstance(value, dict):
        return ""

    # MinerU V2 spans commonly look like {"type": "text", "content": "..."}.
    # Prefer their explicit content field to avoid duplicating hyperlink children.
    for key in ("text", "latex", "content", "html", "value"):
        if key in value:
            rendered = _as_text(value[key])
            if rendered:
                return rendered

    # Structured V2 payloads store text in *_content, *_caption and *_items fields.
    text_fields = (
        "title_content",
        "paragraph_content",
        "math_content",
        "equation_content",
        "image_content",
        "image_caption",
        "image_footnote",
        "table_content",
        "table_body",
        "table_caption",
        "table_footnote",
        "chart_content",
        "chart_caption",
        "chart_footnote",
        "code_content",
        "code_caption",
        "code_footnote",
        "algorithm_content",
        "algorithm_caption",
        "algorithm_footnote",
        "list_items",
        "index_items",
        "page_header_content",
        "page_footer_content",
        "page_number_content",
        "page_aside_text_content",
        "page_footnote_content",
        "children",
        "lines",
        "body",
        "caption",
        # Some MinerU V2 exports wrap type-specific content in {"spans": [...]}.
        "spans",
    )
    parts = []
    for key in text_fields:
        if key in value:
            rendered = _as_text(value[key])
            if rendered:
                parts.append(rendered)
    return "\n".join(parts)



def _shape_summary(value: Any, depth: int = 0) -> dict[str, Any]:
    """Summarize OCR payload structure without copying recognized text into diagnostics."""
    if isinstance(value, str):
        return {
            "kind": "string",
            "length": len(value),
            "has_non_whitespace": bool(value.strip()),
        }
    if isinstance(value, list):
        item_kinds = sorted({_shape_kind(item) for item in value})
        summary: dict[str, Any] = {
            "kind": "list",
            "length": len(value),
            "item_kinds": item_kinds[:8],
        }
        if depth < 2 and value:
            summary["sample_items"] = [
                _shape_summary(item, depth + 1) for item in value[:3]
            ]
        return summary
    if isinstance(value, dict):
        keys = sorted(str(key) for key in value)
        summary = {"kind": "object", "keys": keys[:24]}
        if depth < 2:
            summary["fields"] = {
                str(key): _shape_summary(value[key], depth + 1)
                for key in list(value)[:16]
            }
        return summary
    if value is None:
        return {"kind": "null"}
    return {"kind": type(value).__name__}


def _shape_kind(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "list"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    return type(value).__name__

def _flatten_layout_payload(payload: Any) -> list[dict[str, Any]]:
    """Read flat Content List V1 and page-grouped Content List V2 structures."""
    entries: list[dict[str, Any]] = []
    if isinstance(payload, list):
        for page_index, value in enumerate(payload):
            if isinstance(value, dict):
                entries.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        entry = dict(item)
                        entry.setdefault("page_idx", page_index)
                        entries.append(entry)
        return entries

    if not isinstance(payload, dict):
        return entries

    for key in ("content_list", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return _flatten_layout_payload(value)

    pages = payload.get("pages")
    if isinstance(pages, list):
        for page_index, page in enumerate(pages):
            if not isinstance(page, dict):
                continue
            page_idx = page.get("page_idx", page_index)
            children = page.get("blocks") or page.get("content") or page.get("items")
            if isinstance(children, list):
                for item in children:
                    if isinstance(item, dict):
                        entry = dict(item)
                        entry.setdefault("page_idx", page_idx)
                        entries.append(entry)
    return entries


def _alternate_content_lists(
    artifacts: dict[str, Any], selected_layout_file: str | None
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Return non-selected Content List artifacts for conservative text recovery."""
    json_files = artifacts.get("json")
    if not isinstance(json_files, dict):
        return []

    alternatives = []
    for name, payload in json_files.items():
        name = str(name)
        basename = PurePosixPath(name).name.lower()
        if "content_list" not in basename or name == selected_layout_file:
            continue
        entries = _flatten_layout_payload(payload)
        if entries:
            alternatives.append((name, entries))
    return alternatives


def _model_json_pages(
    artifacts: dict[str, Any],
) -> tuple[str | None, list[list[dict[str, Any]]] | None]:
    """Read page-grouped raw VLM model output without guessing page order."""
    json_files = artifacts.get("json")
    if not isinstance(json_files, dict):
        return None, None

    for name, payload in json_files.items():
        basename = PurePosixPath(str(name)).name.lower()
        if basename != "model.json" and not basename.endswith("_model.json"):
            continue
        if isinstance(payload, list) and payload and all(
            isinstance(page, list) for page in payload
        ):
            pages = [
                [item for item in page if isinstance(item, dict)] for page in payload
            ]
            return str(name), pages
        if isinstance(payload, dict):
            raw_pages = payload.get("pages") or payload.get("page_groups")
            if isinstance(raw_pages, list):
                pages = []
                for page in raw_pages:
                    if isinstance(page, list):
                        pages.append([item for item in page if isinstance(item, dict)])
                    elif isinstance(page, dict):
                        blocks = page.get("blocks") or page.get("items") or []
                        pages.append(
                            [item for item in blocks if isinstance(item, dict)]
                            if isinstance(blocks, list)
                            else []
                        )
                    else:
                        pages.append([])
                return str(name), pages
    return None, None


def _model_bbox_in_content_units(
    value: Any,
) -> tuple[list[float] | None, str | None]:
    """Convert VLM normalized page coordinates to Content List's 0-1000 space."""
    bbox = _bbox(value)
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None, None
    maximum = max(abs(part) for part in bbox)
    if maximum <= 1.5:
        return [part * 1000.0 for part in bbox], "normalized_0_1_to_0_1000"
    if maximum <= 1000:
        return bbox, "already_0_1000"
    # Pixel coordinates require page dimensions and are deliberately not guessed.
    return None, "unsupported_pixel_coordinates"


def _bbox_overlap(
    first: list[float], second: list[float]
) -> tuple[float, float, float]:
    """Return IoU, first-box coverage, and second-box coverage."""
    ax0, ay0, ax1, ay1 = first
    bx0, by0, bx1, by1 = second
    first_area = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    second_area = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    if first_area <= 0 or second_area <= 0:
        return 0.0, 0.0, 0.0
    width = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    height = max(0.0, min(ay1, by1) - max(ay0, by0))
    intersection = width * height
    union = first_area + second_area - intersection
    return (
        intersection / union if union else 0.0,
        intersection / first_area,
        intersection / second_area,
    )


def _recover_text_from_model_json(
    artifacts: dict[str, Any],
    page_idx: int,
    target_bbox: list[float] | dict[str, float] | None,
) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    """Recover an empty paragraph only from text blocks spatially matching its page box."""
    model_file, pages = _model_json_pages(artifacts)
    diagnostic: dict[str, Any] = {
        "source_file": model_file,
        "page_idx": page_idx,
        "recovered": False,
    }
    if pages is None:
        diagnostic["reason"] = "model_json_page_groups_not_found"
        return "", None, diagnostic
    diagnostic["page_group_count"] = len(pages)
    if page_idx < 0 or page_idx >= len(pages):
        diagnostic["reason"] = "page_idx_out_of_model_json_range"
        return "", None, diagnostic

    page_entries = pages[page_idx]
    diagnostic["page_block_count"] = len(page_entries)
    normalized_target = _bbox(target_bbox)
    if not isinstance(normalized_target, list) or len(normalized_target) != 4:
        diagnostic["reason"] = "target_bbox_unavailable"
        return "", None, diagnostic

    candidates: list[dict[str, Any]] = []
    unsupported_bbox_count = 0
    for entry_index, item in enumerate(page_entries):
        raw_type = str(item.get("type") or item.get("label") or "").lower()
        # A paragraph can only be recovered from raw text blocks, never titles,
        # captions, headers, or arbitrary nearby layout detections.
        if raw_type not in {"text", "paragraph"}:
            continue
        content = item.get("content", item.get("text"))
        text = _as_text(content)
        if not text:
            continue
        bbox, coordinate_unit = _model_bbox_in_content_units(item.get("bbox"))
        if bbox is None:
            unsupported_bbox_count += 1
            continue
        iou, target_coverage, candidate_coverage = _bbox_overlap(
            normalized_target, bbox
        )
        candidates.append(
            {
                "entry_index": entry_index,
                "text": text,
                "bbox": bbox,
                "coordinate_unit": coordinate_unit,
                "iou": iou,
                "target_coverage": target_coverage,
                "candidate_coverage": candidate_coverage,
            }
        )

    diagnostic["text_candidate_count"] = sum(
        1
        for item in page_entries
        if str(item.get("type") or item.get("label") or "").lower()
        in {"text", "paragraph"}
        and _as_text(item.get("content", item.get("text")))
    )
    diagnostic["text_candidates_with_usable_bbox"] = len(candidates)
    diagnostic["unsupported_bbox_count"] = unsupported_bbox_count
    diagnostic["nearest_candidates"] = [
        {
            "entry_index": item["entry_index"],
            "bbox": [round(value, 3) for value in item["bbox"]],
            "iou": round(item["iou"], 4),
            "target_coverage": round(item["target_coverage"], 4),
            "candidate_coverage": round(item["candidate_coverage"], 4),
        }
        for item in sorted(candidates, key=lambda candidate: candidate["iou"], reverse=True)[:5]
    ]
    if not candidates:
        diagnostic["reason"] = "no_text_candidates_with_usable_bbox"
        return "", None, diagnostic

    exact = [
        item
        for item in candidates
        if all(
            abs(left - right) <= 1.0
            for left, right in zip(item["bbox"], normalized_target, strict=True)
        )
    ]
    selected: list[dict[str, Any]] = []
    match_method = ""
    if len(exact) == 1:
        selected = exact
        match_method = "model_json_page+normalized_bbox_exact"
    elif len(exact) > 1:
        diagnostic["reason"] = "multiple_exact_model_json_matches"
        return "", None, diagnostic
    else:
        high_overlap = [
            item
            for item in candidates
            if item["iou"] >= 0.90
            and item["target_coverage"] >= 0.90
            and item["candidate_coverage"] >= 0.90
        ]
        if len(high_overlap) == 1:
            selected = high_overlap
            match_method = "model_json_page+bbox_iou"
        elif len(high_overlap) > 1:
            diagnostic["reason"] = "multiple_high_overlap_model_json_matches"
            return "", None, diagnostic
        else:
            # A paragraph may be split into multiple raw text blocks. Accept those
            # only when every candidate is contained by the target and their union
            # bbox closely reconstructs the target region.
            contained = [
                item
                for item in candidates
                if item["bbox"][0] >= normalized_target[0] - 2.0
                and item["bbox"][1] >= normalized_target[1] - 2.0
                and item["bbox"][2] <= normalized_target[2] + 2.0
                and item["bbox"][3] <= normalized_target[3] + 2.0
            ]
            if len(contained) >= 2:
                union_bbox = [
                    min(item["bbox"][0] for item in contained),
                    min(item["bbox"][1] for item in contained),
                    max(item["bbox"][2] for item in contained),
                    max(item["bbox"][3] for item in contained),
                ]
                union_iou, target_coverage, _ = _bbox_overlap(
                    normalized_target, union_bbox
                )
                has_overlapping_fragments = any(
                    _bbox_overlap(first["bbox"], second["bbox"])[0] > 0.25
                    for index, first in enumerate(contained)
                    for second in contained[index + 1 :]
                )
                if (
                    union_iou >= 0.90
                    and target_coverage >= 0.90
                    and not has_overlapping_fragments
                ):
                    selected = contained
                    match_method = "model_json_contained_text_fragments"
                else:
                    diagnostic["reason"] = "model_json_fragments_do_not_cover_target"
            else:
                diagnostic["reason"] = "no_unique_spatial_model_json_match"
            if not selected:
                return "", None, diagnostic

    selected.sort(
        key=lambda item: (
            (item["bbox"][1] + item["bbox"][3]) / 2,
            item["bbox"][0],
            item["entry_index"],
        )
    )
    centers = [
        (item["bbox"][1] + item["bbox"][3]) / 2 for item in selected
    ]
    max_height = max(item["bbox"][3] - item["bbox"][1] for item in selected)
    separator = " " if max(centers) - min(centers) <= max(1.0, max_height * 0.5) else "\n"
    recovered_text = separator.join(item["text"].strip() for item in selected).strip()
    if not recovered_text:
        diagnostic["reason"] = "matched_model_json_blocks_have_no_renderable_text"
        return "", None, diagnostic

    recovery = {
        "source_file": model_file,
        "source_entry_indices": [item["entry_index"] for item in selected],
        "source_bboxes_0_1000": [
            [round(value, 3) for value in item["bbox"]] for item in selected
        ],
        "coordinate_transform": selected[0]["coordinate_unit"],
        "match_method": match_method,
        "page_idx": page_idx,
        "target_bbox": normalized_target,
        "recovered": True,
    }
    return recovered_text, recovery, diagnostic



def _content_list(artifacts: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Prefer V2's explicit semantic content, falling back to the legacy flat list."""
    json_files = artifacts.get("json")
    if not isinstance(json_files, dict):
        return [], None

    candidates = []
    for name, payload in json_files.items():
        basename = PurePosixPath(str(name)).name.lower()
        if "content_list" in basename:
            is_v2 = "content_list_v2" in basename
            candidates.append((not is_v2, str(name), payload))

    for _legacy, name, payload in sorted(candidates, key=lambda item: item[0]):
        entries = _flatten_layout_payload(payload)
        if entries:
            return entries, name
    return [], None


def _artifact_diagnostics(
    artifacts: dict[str, Any], selected_layout_file: str | None = None
) -> dict[str, Any]:
    """Describe saved OCR files without exposing their potentially sensitive content."""
    json_files = artifacts.get("json")
    markdown_files = artifacts.get("markdown")
    file_names = artifacts.get("files")
    json_files = json_files if isinstance(json_files, dict) else {}
    markdown_files = markdown_files if isinstance(markdown_files, dict) else {}
    candidates = [
        str(name)
        for name in json_files
        if "content_list" in PurePosixPath(str(name)).name.lower()
    ]
    shapes = {}
    for name, payload in json_files.items():
        if isinstance(payload, list):
            if payload and isinstance(payload[0], list):
                shapes[str(name)] = (
                    f"page_groups[{len(payload)}], "
                    f"{sum(len(page) for page in payload if isinstance(page, list))} blocks"
                )
            else:
                shapes[str(name)] = f"list[{len(payload)}]"
        elif isinstance(payload, dict):
            shapes[str(name)] = "object keys: " + ", ".join(
                str(key) for key in list(payload)[:12]
            )
        else:
            shapes[str(name)] = type(payload).__name__
    return {
        "archive_file_count": len(file_names) if isinstance(file_names, list) else None,
        "markdown_files": sorted(str(name) for name in markdown_files),
        "json_files": sorted(str(name) for name in json_files),
        "content_list_candidates": candidates,
        "selected_layout_file": selected_layout_file,
        "json_shapes": shapes,
    }


def _kind(item: dict[str, Any]) -> str:
    value = str(item.get("type") or item.get("block_type") or "text").lower()
    if value in _AUXILIARY_TYPES:
        return _AUXILIARY_TYPES[value]
    if value in {"text", "paragraph"} and item.get("text_level", 0):
        return "heading"
    aliases = {
        "text": "paragraph",
        "paragraph": "paragraph",
        "plain_text": "paragraph",
        "title": "heading",
        "heading": "heading",
        "table": "table",
        "image": "image",
        "chart": "chart",
        "equation": "equation",
        "interline_equation": "equation",
        "equation_interline": "equation",
        "list": "list",
        "index": "list",
        "code": "code",
        "algorithm": "algorithm",
    }
    return aliases.get(value, "unknown")


def _block_text(item: dict[str, Any], block_type: str) -> str:
    """Extract V1 direct fields or V2 type-specific structured content."""
    content = item.get("content")
    nested_fields = {
        "heading": ("title_content",),
        "paragraph": ("paragraph_content", "text_content"),
        "equation": ("math_content", "equation_content"),
        "table": (
            "table_content",
            "table_body",
            "table_caption",
            "table_footnote",
        ),
        "image": ("image_content", "image_caption", "image_footnote"),
        "chart": ("chart_content", "chart_caption", "chart_footnote"),
        "code": ("code_content", "code_caption", "code_footnote"),
        "algorithm": (
            "algorithm_content",
            "algorithm_caption",
            "algorithm_footnote",
        ),
        "list": ("list_items", "index_items"),
        "header": ("page_header_content", "header_content"),
        "footer": ("page_footer_content", "footer_content"),
        "page_number": ("page_number_content",),
        "aside_text": ("page_aside_text_content", "aside_text_content"),
        "footnote": ("page_footnote_content", "footnote_content"),
    }
    fields_by_type = {
        "heading": ("text", "title_content"),
        "paragraph": ("text", "paragraph_content"),
        "equation": ("text", "latex", "math_content", "equation_content"),
        "table": ("text", "table_body", "table_caption", "table_footnote"),
        "image": ("text", "image_caption", "image_footnote"),
        "chart": ("text", "chart_caption", "chart_footnote"),
        "code": ("text", "code_body", "code_caption", "code_footnote"),
        "algorithm": (
            "text",
            "algorithm_content",
            "algorithm_caption",
            "algorithm_footnote",
        ),
        "list": ("text", "list_items", "index_items"),
        "header": ("text",),
        "footer": ("text",),
        "page_number": ("text",),
        "aside_text": ("text",),
        "footnote": ("text", "footnote"),
    }
    fields = fields_by_type.get(block_type, ("text",))
    direct = []
    for field in fields:
        if field in item:
            rendered = _as_text(item[field])
            if rendered:
                direct.append(rendered)
    if direct:
        return "\n".join(direct).strip()

    if isinstance(content, dict):
        nested = nested_fields.get(block_type, ())
        values = [_as_text(content[field]) for field in nested if field in content]
        values = [value for value in values if value]
        if values:
            return "\n".join(values).strip()
    elif content is not None:
        rendered = _as_text(content)
        if rendered:
            return rendered

    # Last resort supports a provider adding a new text-like field without losing it.
    return _as_text(item.get("list_items")) or _as_text(item.get("content"))


def _bbox(value: Any) -> list[float] | dict[str, float] | None:
    if isinstance(value, list) and all(
        isinstance(part, (int, float)) and not isinstance(part, bool) for part in value
    ):
        return [float(part) for part in value]
    if isinstance(value, dict) and all(
        isinstance(part, (int, float)) and not isinstance(part, bool)
        for part in value.values()
    ):
        return {str(key): float(part) for key, part in value.items()}
    return None


def _candidate_reasons(block_type: str, text: str) -> list[str]:
    reasons = []
    if any(pattern.search(text) for pattern in _WATERMARK_PATTERNS):
        reasons.append("possible_watermark_or_publication_metadata")
    if block_type == "footnote" or _FOOTNOTE_PREFIX.match(text):
        reasons.append("possible_footnote")
    if block_type in {"header", "footer", "page_number", "aside_text"}:
        reasons.append("possible_page_auxiliary_text")
    return reasons


def build_source_block_payloads(
    artifacts: dict[str, Any],
    page_references: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Map MinerU layout entries to original pages and produce review hints."""
    entries, selected_layout_file = _content_list(artifacts)
    diagnostics = _artifact_diagnostics(artifacts, selected_layout_file)
    page_reference_count = len(
        [
            reference
            for reference in page_references
            if reference.get("pdf_page_index") is not None
            and reference.get("chapter_page_id")
        ]
    )
    if not entries:
        if diagnostics["content_list_candidates"]:
            warning = (
                "A content_list JSON file exists, but no supported block entries "
                "could be read from its structure."
            )
        else:
            available = diagnostics["json_files"] or diagnostics["markdown_files"]
            suffix = (
                " Available result files: " + ", ".join(available[:20])
                if available
                else " No Markdown or JSON artifacts were found."
            )
            warning = (
                "No content_list*.json artifact was found. full.md is preserved, "
                "but page-level SourceBlocks are not guessed from Markdown."
                + suffix
            )
        return [], {
            "layout_source": None,
            "layout_entry_count": 0,
            "mapped_entries": 0,
            "page_reference_count": page_reference_count,
            "blocks_created": 0,
            "empty_text_entries": 0,
            "unmapped_entries": 0,
            "cleanup_candidate_count": 0,
            "alternate_layout_recoveries": [],
            "artifact_diagnostics": diagnostics,
            "warnings": [warning],
        }

    page_by_pdf_index = {
        int(reference["pdf_page_index"]): reference
        for reference in page_references
        if reference.get("pdf_page_index") is not None
        and reference.get("chapter_page_id")
    }
    payloads: list[dict[str, Any]] = []
    alternate_layouts = _alternate_content_lists(artifacts, selected_layout_file)
    unmapped = 0
    repeated_pages: dict[tuple[str, str], set[str]] = defaultdict(set)
    candidate_reasons: dict[str, list[str]] = {}

    for entry_index, item in enumerate(entries):
        page_idx = item.get("page_idx")
        if not isinstance(page_idx, int) or isinstance(page_idx, bool):
            unmapped += 1
            continue
        reference = page_by_pdf_index.get(page_idx + 1)
        if reference is None:
            unmapped += 1
            continue
        block_type = _kind(item)
        text = _block_text(item, block_type)
        recovery_diagnostic = None
        model_recovery_diagnostic = None
        target_bbox = _bbox(item.get("bbox"))
        if not text and alternate_layouts:
            matches = []
            for alternate_name, alternate_entries in alternate_layouts:
                for alternate_index, alternate_item in enumerate(alternate_entries):
                    if alternate_item.get("page_idx") != page_idx:
                        continue
                    if _kind(alternate_item) != block_type:
                        continue
                    if _bbox(alternate_item.get("bbox")) != target_bbox:
                        continue
                    alternate_text = _block_text(alternate_item, block_type)
                    if alternate_text:
                        matches.append(
                            (alternate_name, alternate_index, alternate_text)
                        )
            # Never guess when multiple alternate entries could fit this block.
            if len(matches) == 1:
                alternate_name, alternate_index, text = matches[0]
                recovery_diagnostic = {
                    "entry_index": entry_index,
                    "block_type": block_type,
                    "page_idx": page_idx,
                    "bbox": target_bbox,
                    "source_layout": alternate_name,
                    "source_entry_index": alternate_index,
                    "match_method": "page_idx+block_type+exact_bbox",
                }
        if not text and block_type == "paragraph":
            recovered_text, model_recovery, model_probe = _recover_text_from_model_json(
                artifacts, page_idx, target_bbox
            )
            model_recovery_diagnostic = model_recovery or model_probe
            if recovered_text:
                text = recovered_text
        canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        text_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        occurrence_key = (
            f"{reference['chapter_page_id']}:{block_type}:{text_digest[:16]}"
        )
        payload = {
            "page_id": str(reference["chapter_page_id"]),
            "block_type": block_type,
            "text": text,
            "bbox": _bbox(item.get("bbox")),
            "confidence": None,
            "content_hash": text_digest,
            "source_digest": digest,
            "entry_index": entry_index,
            "block_key_base": occurrence_key,
        }
        if recovery_diagnostic is not None:
            payload["recovery_diagnostic"] = recovery_diagnostic
        if model_recovery_diagnostic is not None:
            payload["model_json_recovery_diagnostic"] = model_recovery_diagnostic
        if not text:
            content = item.get("content")
            content_keys = (
                sorted(str(key) for key in content)
                if isinstance(content, dict)
                else []
            )
            media_path = item.get("img_path") or item.get("image_path")
            if not media_path and isinstance(content, dict):
                media_path = content.get("img_path") or content.get("image_path")
                image_source = content.get("image_source")
                if not media_path and isinstance(image_source, dict):
                    media_path = image_source.get("path")
            payload["empty_diagnostic"] = {
                "entry_index": entry_index,
                "raw_type": str(
                    item.get("type") or item.get("block_type") or "unknown"
                ),
                "top_level_keys": sorted(str(key) for key in item),
                "content_keys": content_keys,
                "content_value_shapes": {
                    str(key): _shape_summary(value)
                    for key, value in content.items()
                }
                if isinstance(content, dict)
                else {},
                "bbox": payload["bbox"],
                "media_path": str(media_path) if media_path else None,
                "visual_only": block_type in {"image", "chart", "table"},
            }
        payloads.append(payload)
        normalized_line = " ".join(text.split()).casefold()
        if text and len(normalized_line) <= 140:
            repeated_pages[(block_type, normalized_line)].add(
                str(reference["chapter_page_id"])
            )
        reasons = _candidate_reasons(block_type, text)
        if reasons:
            candidate_reasons[occurrence_key] = reasons

    repeated_lines = {
        key for key, page_ids in repeated_pages.items() if len(page_ids) >= 2
    }
    occurrence_counts: dict[str, int] = defaultdict(int)
    candidates = []
    empty_block_diagnostics = []
    alternate_layout_recoveries = []
    model_json_recoveries = []
    model_json_recovery_diagnostics = []
    for order, payload in enumerate(payloads):
        base = payload.pop("block_key_base")
        occurrence_counts[base] += 1
        payload["block_key"] = f"{base}:{occurrence_counts[base]}"
        payload["sort_order"] = order
        recovery_diagnostic = payload.pop("recovery_diagnostic", None)
        if recovery_diagnostic is not None:
            alternate_layout_recoveries.append(
                {
                    **recovery_diagnostic,
                    "block_key": payload["block_key"],
                }
            )
        model_diagnostic = payload.pop("model_json_recovery_diagnostic", None)
        if model_diagnostic is not None:
            collection = (
                model_json_recoveries if model_diagnostic.get("recovered")
                else model_json_recovery_diagnostics
            )
            collection.append({**model_diagnostic, "block_key": payload["block_key"]})
        empty_diagnostic = payload.pop("empty_diagnostic", None)
        if empty_diagnostic is not None:
            empty_block_diagnostics.append(
                {
                    **empty_diagnostic,
                    "block_key": payload["block_key"],
                    "page_id": payload["page_id"],
                    "block_type": payload["block_type"],
                }
            )
        normalized_line = " ".join(payload["text"].split()).casefold()
        reasons = list(candidate_reasons.get(base, []))
        if (payload["block_type"], normalized_line) in repeated_lines:
            reasons.append("repeated_short_text_across_pages")
        if reasons:
            candidates.append(
                {
                    "block_key": payload["block_key"],
                    "page_id": payload["page_id"],
                    "reasons": sorted(set(reasons)),
                    "text_preview": payload["text"][:180],
                    "action": "review_only",
                }
            )

    mapped_count = len(payloads)
    empty_text_count = sum(not payload["text"] for payload in payloads)
    visual_only_empty_count = sum(
        1 for item in empty_block_diagnostics if item["visual_only"]
    )
    unexpected_empty_count = empty_text_count - visual_only_empty_count
    warnings = []
    if unmapped:
        warnings.append("Some layout entries could not be mapped to a source page.")
    if not mapped_count:
        warnings.append(
            "Layout entries were found, but none matched the saved PDF page references."
        )
    # Visual blocks can be valid evidence even when no caption text was recognized.
    if unexpected_empty_count:
        warnings.append(
            f"{unexpected_empty_count} non-visual layout blocks contain no extractable text. "
            "Inspect empty_block_diagnostics before treating them as valid."
        )
    return payloads, {
        "layout_source": selected_layout_file or "content_list",
        "layout_entry_count": len(entries),
        "mapped_entries": mapped_count,
        "page_reference_count": page_reference_count,
        "blocks_created": len(payloads),
        "empty_text_entries": empty_text_count,
        "visual_only_empty_entries": visual_only_empty_count,
        "unexpected_empty_text_entries": unexpected_empty_count,
        "empty_block_diagnostics": empty_block_diagnostics,
        "alternate_layout_recoveries": alternate_layout_recoveries,
        "model_json_recoveries": model_json_recoveries,
        "model_json_recovery_diagnostics": model_json_recovery_diagnostics,
        "unmapped_entries": unmapped,
        "cleanup_candidate_count": len(candidates),
        "cleanup_candidates": candidates,
        "artifact_diagnostics": diagnostics,
        "warnings": warnings,
    }


def materialize_source_blocks(
    session: Session, run: ProcessingRun
) -> tuple[list[SourceBlock], dict[str, Any]]:
    """Reconcile SourceBlocks with parsed artifacts while preserving existing IDs."""
    existing = session.scalars(
        select(SourceBlock)
        .where(SourceBlock.processing_run_id == run.id)
        .order_by(SourceBlock.sort_order, SourceBlock.id)
    ).all()

    normalized = run.normalized_result if isinstance(run.normalized_result, dict) else {}
    artifacts = normalized.get("artifacts")
    references = normalized.get("page_references")
    if not isinstance(artifacts, dict) or not isinstance(references, list):
        report = {
            "layout_source": None,
            "layout_entry_count": 0,
            "mapped_entries": 0,
            "page_reference_count": 0,
            "blocks_created": 0,
            "empty_text_entries": 0,
            "unmapped_entries": 0,
            "cleanup_candidate_count": 0,
            "warnings": [
                "OCR run does not contain normalized MinerU artifacts/page references."
            ],
        }
        if existing:
            report["warnings"].append(
                "Existing SourceBlocks were preserved because no replacement layout "
                "was available."
            )
            return [block for block in existing if block.is_active], report
        return [], report

    payloads, report = build_source_block_payloads(artifacts, references)
    if not payloads:
        if existing:
            report["warnings"].append(
                "Existing SourceBlocks were preserved because no usable layout entries "
                "were extracted."
            )
            return [block for block in existing if block.is_active], report
        return [], report

    # The old parser could create one empty-text row per layout item. Repair those rows
    # in place, preserving IDs and any existing evidence relations that reference them.
    # Temporary keys prevent uniqueness conflicts while deterministic keys are replaced.
    for block in existing:
        block.block_key = f"rebuild:{block.id}"
    if existing:
        session.flush()

    active_blocks: list[SourceBlock] = []
    for index, payload in enumerate(payloads):
        if index < len(existing):
            block = existing[index]
            changed = (
                block.text != payload["text"]
                or block.block_type != payload["block_type"]
                or block.page_id != payload["page_id"]
                or block.content_hash != payload["content_hash"]
            )
            block.chapter_id = run.chapter_id
            block.page_id = payload["page_id"]
            block.block_type = payload["block_type"]
            block.text = payload["text"]
            block.bbox = payload["bbox"]
            block.confidence = payload["confidence"]
            block.content_hash = payload["content_hash"]
            block.block_key = payload["block_key"]
            block.sort_order = payload["sort_order"]
            block.is_active = True
            if changed:
                block.version += 1
        else:
            block = SourceBlock(
                chapter_id=run.chapter_id,
                page_id=payload["page_id"],
                processing_run_id=run.id,
                block_key=payload["block_key"],
                block_type=payload["block_type"],
                text=payload["text"],
                bbox=payload["bbox"],
                confidence=payload["confidence"],
                content_hash=payload["content_hash"],
                version=1,
                sort_order=payload["sort_order"],
                is_active=True,
            )
            session.add(block)
        active_blocks.append(block)

    for block in existing[len(payloads):]:
        block.block_key = f"inactive:{block.id}"
        block.is_active = False
        block.version += 1

    session.flush()
    return active_blocks, report


def render_anchored_markdown(
    blocks: list[SourceBlock], report: dict[str, Any] | None = None
) -> str:
    """Render Markdown with stable anchors and non-destructive cleanup review markers."""
    candidates = (report or {}).get("cleanup_candidates", [])
    reasons_by_key = {
        item.get("block_key"): item.get("reasons", [])
        for item in candidates
        if isinstance(item, dict)
    }
    rendered = []
    for block in blocks:
        rendered.append(f"<!-- source:{block.block_key} -->")
        reasons = reasons_by_key.get(block.block_key, [])
        if reasons:
            rendered.append(
                f"<!-- cleanup-review: {', '.join(reasons)}; not removed -->"
            )
        text = block.text.strip()
        if not text:
            rendered.append(f"<!-- {block.block_type} block; inspect original page -->")
        elif block.block_type == "heading":
            rendered.append(f"## {text}")
        elif block.block_type == "equation":
            rendered.append(f"$$\n{text}\n$$")
        elif block.block_type == "table":
            rendered.append(text)
        elif block.block_type == "image":
            rendered.append(f"> 图片/图注：{text}")
        elif block.block_type == "footnote":
            rendered.append(f"> 脚注候选：{text}")
        else:
            rendered.append(text)
        rendered.append("")
    return "\n".join(rendered).strip()
