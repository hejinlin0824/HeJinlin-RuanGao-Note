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
_FOOTNOTE_PREFIX = re.compile(r"^\s*(?:\[\d{1,3}\]|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|注\s*\d*[:：])\s*")


def _content_list(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    json_files = artifacts.get("json")
    if not isinstance(json_files, dict):
        return []
    for name, payload in json_files.items():
        if "content_list" not in PurePosixPath(str(name)).name.lower():
            continue
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("content_list", "data", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
    return []


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_as_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "content", "caption"):
            if key in value:
                return _as_text(value[key])
    return ""


def _block_text(item: dict[str, Any], block_type: str) -> str:
    fields = (
        ("text", "latex")
        if block_type == "equation"
        else ("text", "table_body", "table_caption", "table_footnote")
        if block_type == "table"
        else ("text", "image_caption", "image_footnote")
        if block_type == "image"
        else ("text", "footnote")
    )
    values = [_as_text(item.get(field)) for field in fields]
    return "\n".join(value for value in values if value).strip()


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


def _kind(item: dict[str, Any]) -> str:
    value = str(item.get("type") or item.get("block_type") or "text").lower()
    aliases = {
        "text": "paragraph",
        "plain_text": "paragraph",
        "title": "heading",
        "table": "table",
        "image": "image",
        "equation": "equation",
        "interline_equation": "equation",
        "footnote": "footnote",
        "list": "list",
        "code": "code",
    }
    return aliases.get(value, value if value in {"paragraph", "heading", "table", "image",
                                                  "equation", "footnote", "list", "code"}
                       else "unknown")


def _candidate_reasons(block_type: str, text: str) -> list[str]:
    reasons = []
    if any(pattern.search(text) for pattern in _WATERMARK_PATTERNS):
        reasons.append("possible_watermark_or_publication_metadata")
    if block_type == "footnote" or _FOOTNOTE_PREFIX.match(text):
        reasons.append("possible_footnote")
    return reasons


def build_source_block_payloads(
    artifacts: dict[str, Any],
    page_references: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Map MinerU content_list entries to original pages and produce review hints."""
    entries = _content_list(artifacts)
    if not entries:
        return [], {
            "layout_source": None,
            "blocks_created": 0,
            "unmapped_entries": 0,
            "cleanup_candidate_count": 0,
            "warnings": [
                "MinerU content_list.json was not present; page-level SourceBlocks were not guessed from full.md."
            ],
        }

    page_by_pdf_index = {
        int(reference["pdf_page_index"]): reference
        for reference in page_references
        if reference.get("pdf_page_index") is not None
        and reference.get("chapter_page_id")
    }
    payloads: list[dict[str, Any]] = []
    unmapped = 0
    repeated_pages: dict[str, set[str]] = defaultdict(set)
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
        canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        text_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        occurrence_key = f"{reference['chapter_page_id']}:{block_type}:{text_digest[:16]}"
        payload = {
            "page_id": str(reference["chapter_page_id"]),
            "block_type": block_type,
            "text": text,
            "bbox": _bbox(item.get("bbox")),
            "confidence": None,
            "content_hash": text_digest,
            "source_digest": digest,
            "entry_index": entry_index,
        }
        payloads.append(payload)
        normalized_line = " ".join(text.split()).casefold()
        if text and len(normalized_line) <= 140:
            repeated_pages[normalized_line].add(str(reference["chapter_page_id"]))
        reasons = _candidate_reasons(block_type, text)
        if reasons:
            candidate_reasons[occurrence_key] = reasons
        payload["block_key_base"] = occurrence_key

    repeated_lines = {
        line for line, page_ids in repeated_pages.items() if len(page_ids) >= 2
    }
    occurrence_counts: dict[str, int] = defaultdict(int)
    candidates = []
    for order, payload in enumerate(payloads):
        base = payload.pop("block_key_base")
        occurrence_counts[base] += 1
        payload["block_key"] = f"{base}:{occurrence_counts[base]}"
        payload["sort_order"] = order
        normalized_line = " ".join(payload["text"].split()).casefold()
        reasons = list(candidate_reasons.get(base, []))
        if normalized_line in repeated_lines:
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
    return payloads, {
        "layout_source": "content_list.json",
        "blocks_created": len(payloads),
        "unmapped_entries": unmapped,
        "cleanup_candidate_count": len(candidates),
        "cleanup_candidates": candidates,
        "warnings": (
            ["Some layout entries could not be mapped to a source page."]
            if unmapped
            else []
        ),
    }


def materialize_source_blocks(
    session: Session, run: ProcessingRun
) -> tuple[list[SourceBlock], dict[str, Any]]:
    """Persist page-linked blocks once for a successful chapter OCR run."""
    existing = session.scalars(
        select(SourceBlock)
        .where(SourceBlock.processing_run_id == run.id)
        .order_by(SourceBlock.sort_order, SourceBlock.id)
    ).all()
    if existing:
        report = (run.quality_report or {}).get("source_blocks", {})
        return existing, report

    normalized = run.normalized_result if isinstance(run.normalized_result, dict) else {}
    artifacts = normalized.get("artifacts")
    references = normalized.get("page_references")
    if not isinstance(artifacts, dict) or not isinstance(references, list):
        return [], {
            "layout_source": None,
            "blocks_created": 0,
            "unmapped_entries": 0,
            "cleanup_candidate_count": 0,
            "warnings": ["OCR run does not contain normalized MinerU artifacts/page references."],
        }

    payloads, report = build_source_block_payloads(artifacts, references)
    for payload in payloads:
        payload.pop("source_digest", None)
        payload.pop("entry_index", None)
        session.add(
            SourceBlock(
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
        )
    session.flush()
    return (
        session.scalars(
            select(SourceBlock)
            .where(SourceBlock.processing_run_id == run.id)
            .order_by(SourceBlock.sort_order, SourceBlock.id)
        ).all(),
        report,
    )


def render_anchored_markdown(blocks: list[SourceBlock]) -> str:
    """Render a conservative Markdown view with stable, reviewable block anchors."""
    rendered = []
    for block in blocks:
        rendered.append(f"<!-- source:{block.block_key} -->")
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
