"""Tests for generated image URL selection and hashtag normalization."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("API_AUTH_TOKEN", "test-token")

import main
from llm_provider import _parse_llm_json
from prompts_v2 import _normalize_tags


REFERENCE_URL = "https://upload.apimart.ai/f/image/original-image.jpg"
GENERATED_URL = "https://upload.apimart.ai/f/image/generated-gpt_image_2_backup_task.png"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_query_single_task_prefers_generated_url_over_reference():
    original_request = main._apimart_request

    async def fake_request(*args, **kwargs):
        return {
            "data": {
                "status": "completed",
                "result": {
                    "images": [
                        {"url": [REFERENCE_URL, GENERATED_URL]},
                    ],
                },
            },
        }

    main._apimart_request = fake_request
    try:
        result = _run(main._query_single_task("task-ok", REFERENCE_URL))
        assert result == GENERATED_URL
    finally:
        main._apimart_request = original_request


def test_query_single_task_fails_when_only_reference_is_returned():
    original_request = main._apimart_request

    async def fake_request(*args, **kwargs):
        return {
            "data": {
                "status": "completed",
                "result": {
                    "images": [
                        {"url": [REFERENCE_URL]},
                    ],
                },
            },
        }

    main._apimart_request = fake_request
    try:
        result = _run(main._query_single_task("task-reference-only", REFERENCE_URL))
        assert result == "failed"
    finally:
        main._apimart_request = original_request


def test_normalize_tags_splits_string_and_single_item_list():
    expected = ["#A", "#B", "#C"]
    assert _normalize_tags("#A #B #C") == expected
    assert _normalize_tags(["#A #B #C"]) == expected
    assert _normalize_tags(["A，B、C"]) == expected


def test_llm_schema_accepts_string_tags_for_normalization():
    parsed = _parse_llm_json(
        '{"metadata":{"tags":"#A #B #C"},"scene_config":{}}'
    )
    assert parsed is not None
    assert parsed["metadata"]["tags"] == "#A #B #C"


if __name__ == "__main__":
    tests = [
        test_query_single_task_prefers_generated_url_over_reference,
        test_query_single_task_fails_when_only_reference_is_returned,
        test_normalize_tags_splits_string_and_single_item_list,
        test_llm_schema_accepts_string_tags_for_normalization,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test.__name__}: {exc}")
            failed += 1
    print(f"\n  TOTAL: {len(tests)} | PASS: {passed} | FAIL: {failed}")
    sys.exit(1 if failed else 0)
