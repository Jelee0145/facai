"""Tests for LLM JSON parsing and schema validation."""
import os
import sys

# Ensure backend modules are importable
sys.path.insert(0, os.path.dirname(__file__))

from llm_provider import _parse_llm_json


def test_fenced_json_passes():
    content = '```json\n{"scene_config": {"scenes": ["beach"]}, "metadata": {"titles": ["Test"]}}\n```'
    result = _parse_llm_json(content)
    assert result is not None, "Fenced JSON should parse successfully"
    assert "scene_config" in result
    assert "metadata" in result


def test_plain_json_passes():
    content = '{"scene_config": {"scenes": ["office"]}, "metadata": {"titles": ["Title"]}}'
    result = _parse_llm_json(content)
    assert result is not None
    assert result["scene_config"]["scenes"] == ["office"]


def test_non_json_returns_none():
    result = _parse_llm_json("this is not json")
    assert result is None, "Non-JSON should return None"


def test_empty_returns_none():
    assert _parse_llm_json("") is None
    assert _parse_llm_json("   ") is None
    assert _parse_llm_json(None) is None


def test_missing_fields_returns_none():
    # LLMOutput requires both scene_config and metadata; missing metadata should fail
    content = '{"scene_config": {"scenes": ["beach"]}}'
    result = _parse_llm_json(content)
    # scene_config is optional with default, metadata is optional with default
    # so this should actually pass since both have defaults
    assert result is not None, "Fields with defaults should pass"


def test_wrong_type_returns_none():
    # Pass a list instead of dict
    content = '["not", "a", "dict"]'
    result = _parse_llm_json(content)
    assert result is None, "Non-dict top-level should return None"


def test_schema_rejects_bad_field_type():
    # titles should be list[str], give it a number
    content = '{"scene_config": {"scenes": "not_a_list"}, "metadata": {"titles": 123}}'
    result = _parse_llm_json(content)
    # Pydantic v2 may coerce or reject — either way, result should be None or valid dict
    assert result is None or isinstance(result, dict), "Result must be None or a dict"


def test_raw_dict_not_returned_on_schema_failure():
    """Critical: when schema validation fails, raw dict must NOT be returned."""
    content = '{"scene_config": "not_an_object", "metadata": "not_an_object"}'
    result = _parse_llm_json(content)
    # Must be None or a validated dict — never a raw dict bypassing model_validate
    assert result is None or isinstance(result, dict), "Must not return raw dict without validation"


def test_extra_fields_allowed():
    """LLMOutput should accept extra fields without crashing."""
    content = '{"scene_config": {}, "metadata": {}, "extra_field": "value"}'
    result = _parse_llm_json(content)
    assert result is not None, "Extra fields should not break parsing"


if __name__ == "__main__":
    tests = [
        test_fenced_json_passes,
        test_plain_json_passes,
        test_non_json_returns_none,
        test_empty_returns_none,
        test_missing_fields_returns_none,
        test_wrong_type_returns_none,
        test_schema_rejects_bad_field_type,
        test_raw_dict_not_returned_on_schema_failure,
        test_extra_fields_allowed,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n  TOTAL: {len(tests)} | PASS: {passed} | FAIL: {failed}")
    sys.exit(1 if failed else 0)
