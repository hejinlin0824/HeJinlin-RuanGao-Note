"""Regression tests for MinerU source-block edge cases."""

from ruangao_note.services.source_blocks import build_source_block_payloads


def test_running_header_does_not_make_same_text_heading_a_cleanup_candidate():
    artifacts = {
        "json": {
            "chapter_content_list_v2.json": [
                [
                    {
                        "type": "title",
                        "content": {
                            "title_content": [
                                {"type": "text", "content": "第1章 信息化发展"}
                            ]
                        },
                    }
                ],
                [
                    {
                        "type": "page_header",
                        "content": {
                            "page_header_content": [
                                {"type": "text", "content": "第1章 信息化发展"}
                            ]
                        },
                    }
                ],
            ]
        }
    }
    references = [
        {"pdf_page_index": 1, "chapter_page_id": "page-a"},
        {"pdf_page_index": 2, "chapter_page_id": "page-b"},
    ]

    blocks, report = build_source_block_payloads(artifacts, references)

    assert len(blocks) == 2
    candidates = {
        item["block_key"]: item["reasons"] for item in report["cleanup_candidates"]
    }
    assert blocks[0]["block_key"] not in candidates
    assert candidates[blocks[1]["block_key"]] == ["possible_page_auxiliary_text"]


def test_visual_empty_block_is_distinguished_from_empty_paragraph():
    artifacts = {
        "json": {
            "chapter_content_list_v2.json": [
                [
                    {
                        "type": "image",
                        "img_path": "images/figure-1.jpg",
                        "content": {"image_content": [], "image_caption": []},
                        "bbox": [0, 498, 55, 662],
                    },
                    {
                        "type": "paragraph",
                        "content": {"paragraph_content": []},
                        "bbox": [10, 700, 900, 740],
                    },
                ]
            ]
        },
        "files": ["images/figure-1.jpg", "chapter_content_list_v2.json"],
    }
    references = [{"pdf_page_index": 1, "chapter_page_id": "page-a"}]

    blocks, report = build_source_block_payloads(artifacts, references)

    assert len(blocks) == 2
    assert report["empty_text_entries"] == 2
    assert report["visual_only_empty_entries"] == 1
    assert report["unexpected_empty_text_entries"] == 1
    diagnostics = report["empty_block_diagnostics"]
    assert diagnostics[0]["visual_only"] is True
    assert diagnostics[0]["media_path"] == "images/figure-1.jpg"
    assert diagnostics[1]["visual_only"] is False
    assert diagnostics[1]["content_keys"] == ["paragraph_content"]
    assert "1 non-visual layout blocks" in report["warnings"][0]



def test_paragraph_content_with_nested_spans_is_extracted():
    artifacts = {
        "json": {
            "chapter_content_list_v2.json": [
                [
                    {
                        "type": "paragraph",
                        "content": {
                            "paragraph_content": {
                                "spans": [
                                    {"type": "text", "text": "段落正文被正确提取"},
                                    {"type": "equation_inline", "latex": "x+y"},
                                ]
                            }
                        },
                        "bbox": [10, 20, 900, 80],
                    }
                ]
            ]
        }
    }
    references = [{"pdf_page_index": 1, "chapter_page_id": "page-a"}]

    blocks, report = build_source_block_payloads(artifacts, references)

    assert len(blocks) == 1
    assert blocks[0]["text"] == "段落正文被正确提取\nx+y"
    assert report["empty_text_entries"] == 0
    assert report["unexpected_empty_text_entries"] == 0
    assert report["warnings"] == []
