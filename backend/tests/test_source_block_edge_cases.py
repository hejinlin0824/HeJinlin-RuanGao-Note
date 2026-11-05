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
                        "content": {
                            "image_content": [],
                            "image_caption": [],
                            "image_source": {"path": "images/figure-1.jpg"},
                        },
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
    assert diagnostics[1]["bbox"] == [10.0, 700.0, 900.0, 740.0]
    assert diagnostics[1]["content_value_shapes"] == {
        "paragraph_content": {
            "kind": "list",
            "length": 0,
            "item_kinds": [],
        }
    }
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



def test_empty_block_diagnostics_summarize_unknown_payload_without_copying_text():
    hidden_text = "这段识别结果不能丢失"
    artifacts = {
        "json": {
            "chapter_content_list_v2.json": [
                [
                    {
                        "type": "paragraph",
                        "content": {
                            "paragraph_content": {
                                "provider_specific_nodes": [{"recognized_text": hidden_text}]
                            }
                        },
                        "bbox": [1, 2, 300, 40],
                    }
                ]
            ]
        }
    }
    references = [{"pdf_page_index": 1, "chapter_page_id": "page-a"}]

    blocks, report = build_source_block_payloads(artifacts, references)

    assert blocks[0]["text"] == ""
    diagnostic = report["empty_block_diagnostics"][0]
    shape = diagnostic["content_value_shapes"]["paragraph_content"]
    assert shape["kind"] == "object"
    assert shape["keys"] == ["provider_specific_nodes"]
    assert shape["fields"]["provider_specific_nodes"]["sample_items"][0]["keys"] == [
        "recognized_text"
    ]
    assert hidden_text not in str(report)



def test_empty_v2_paragraph_recovers_text_from_unique_exact_v1_match():
    bbox = [81, 54, 745, 76]
    artifacts = {
        "json": {
            "chapter_content_list_v2.json": [
                [
                    {
                        "type": "paragraph",
                        "content": {"paragraph_content": []},
                        "bbox": bbox,
                    }
                ]
            ],
            "chapter_content_list.json": [
                {
                    "type": "text",
                    "page_idx": 0,
                    "text": "正文来自同一 OCR 的 V1 输出",
                    "bbox": bbox,
                }
            ],
        }
    }
    references = [{"pdf_page_index": 1, "chapter_page_id": "page-a"}]

    blocks, report = build_source_block_payloads(artifacts, references)

    assert len(blocks) == 1
    assert blocks[0]["text"] == "正文来自同一 OCR 的 V1 输出"
    assert report["empty_text_entries"] == 0
    assert report["alternate_layout_recoveries"] == [
        {
            "entry_index": 0,
            "block_type": "paragraph",
            "page_idx": 0,
            "bbox": [81.0, 54.0, 745.0, 76.0],
            "source_layout": "chapter_content_list.json",
            "source_entry_index": 0,
            "match_method": "page_idx+block_type+exact_bbox",
            "block_key": blocks[0]["block_key"],
        }
    ]


def test_empty_v2_paragraph_does_not_recover_from_v1_bbox_mismatch():
    artifacts = {
        "json": {
            "chapter_content_list_v2.json": [
                [
                    {
                        "type": "paragraph",
                        "content": {"paragraph_content": []},
                        "bbox": [81, 54, 745, 76],
                    }
                ]
            ],
            "chapter_content_list.json": [
                {
                    "type": "text",
                    "page_idx": 0,
                    "text": "不能错误拼接的其他段落",
                    "bbox": [81, 80, 745, 102],
                }
            ],
        }
    }
    references = [{"pdf_page_index": 1, "chapter_page_id": "page-a"}]

    blocks, report = build_source_block_payloads(artifacts, references)

    assert blocks[0]["text"] == ""
    assert report["empty_text_entries"] == 1
    assert report["alternate_layout_recoveries"] == []



def test_empty_v2_paragraph_recovers_from_vlm_model_json_normalized_bbox():
    bbox = [81, 54, 745, 76]
    artifacts = {
        "json": {
            "chapter_content_list_v2.json": [
                [
                    {
                        "type": "paragraph",
                        "content": {"paragraph_content": []},
                        "bbox": bbox,
                    }
                ]
            ],
            "chapter_model.json": [
                [
                    {
                        "type": "text",
                        "bbox": [0.081, 0.054, 0.745, 0.076],
                        "content": "正文来自同一页的 MinerU 原始模型输出",
                    }
                ]
            ],
        }
    }
    references = [{"pdf_page_index": 1, "chapter_page_id": "page-a"}]

    blocks, report = build_source_block_payloads(artifacts, references)

    assert blocks[0]["text"] == "正文来自同一页的 MinerU 原始模型输出"
    assert report["empty_text_entries"] == 0
    assert report["model_json_recoveries"][0]["source_file"] == "chapter_model.json"
    assert report["model_json_recoveries"][0]["source_entry_indices"] == [0]
    assert report["model_json_recoveries"][0]["coordinate_transform"] == (
        "normalized_0_1_to_0_1000"
    )
    assert report["model_json_recoveries"][0]["match_method"] == (
        "model_json_page+normalized_bbox_exact"
    )


def test_model_json_recovery_rejects_a_nearby_but_nonmatching_text_block():
    bbox = [81, 54, 745, 76]
    artifacts = {
        "json": {
            "chapter_content_list_v2.json": [
                [
                    {
                        "type": "paragraph",
                        "content": {"paragraph_content": []},
                        "bbox": bbox,
                    }
                ]
            ],
            "chapter_model.json": [
                [
                    {
                        "type": "text",
                        "bbox": [0.081, 0.08, 0.745, 0.102],
                        "content": "这是下方相邻段落，不能被错误回填",
                    }
                ]
            ],
        }
    }
    references = [{"pdf_page_index": 1, "chapter_page_id": "page-a"}]

    blocks, report = build_source_block_payloads(artifacts, references)

    assert blocks[0]["text"] == ""
    assert report["empty_text_entries"] == 1
    assert report["model_json_recoveries"] == []
    diagnostic = report["model_json_recovery_diagnostics"][0]
    assert diagnostic["reason"] == "no_unique_spatial_model_json_match"
    assert diagnostic["nearest_candidates"][0]["iou"] == 0.0


def test_model_json_recovery_combines_nonoverlapping_text_fragments_inside_bbox():
    bbox = [81, 54, 745, 76]
    artifacts = {
        "json": {
            "chapter_content_list_v2.json": [
                [
                    {
                        "type": "paragraph",
                        "content": {"paragraph_content": []},
                        "bbox": bbox,
                    }
                ]
            ],
            "chapter_model.json": [
                [
                    {
                        "type": "text",
                        "bbox": [0.081, 0.054, 0.40, 0.076],
                        "content": "由同一段落拆分出的前半句",
                    },
                    {
                        "type": "text",
                        "bbox": [0.405, 0.054, 0.745, 0.076],
                        "content": "以及后半句",
                    },
                ]
            ],
        }
    }
    references = [{"pdf_page_index": 1, "chapter_page_id": "page-a"}]

    blocks, report = build_source_block_payloads(artifacts, references)

    assert blocks[0]["text"] == "由同一段落拆分出的前半句 以及后半句"
    assert report["empty_text_entries"] == 0
    assert report["model_json_recoveries"][0]["source_entry_indices"] == [0, 1]
    assert report["model_json_recoveries"][0]["match_method"] == (
        "model_json_contained_text_fragments"
    )
