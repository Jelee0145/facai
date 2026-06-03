"""
LLM 调用层 — 3 个独立函数：模特图 prompt、商品图 prompt、爆款内容
"""

import json
import logging
import re
import httpx
from database import get_config
from llm_schema import LLMPromptsOutput, LLMMetadata
from llm_prompts import (
    SYSTEM_PROMPT_MODEL,
    SYSTEM_PROMPT_PRODUCT,
    SYSTEM_PROMPT_METADATA,
    build_model_user_prompt,
    build_product_user_prompt,
    build_metadata_user_prompt,
)
from prompts_v2 import _normalize_tags

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_TIMEOUT = 60

logger = logging.getLogger("ecommerce-gen.llm")

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def get_llm_config() -> tuple[str, str]:
    """从 system_config 读取 LLM 配置，返回 (api_key, model_name)"""
    api_key = get_config("llm_api_key") or ""
    model = get_config("llm_model") or "qwen3-vl-flash"
    return api_key, model


def _parse_llm_json(content: str, schema_cls=None) -> dict | None:
    """Parse LLM JSON response, stripping markdown code fences if present."""
    if not content or not content.strip():
        return None
    raw = content.strip()
    fence = _CODE_FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if schema_cls:
        try:
            validated = schema_cls.model_validate(parsed)
            return validated.model_dump()
        except Exception as e:
            logger.warning(f"[LLM] Schema validation failed: {e}")
            return None
    return parsed


async def _call_llm(
    api_key: str,
    model: str,
    messages: list[dict],
) -> str | None:
    """调用 LLM API，返回原始 content 字符串"""
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{DASHSCOPE_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                },
            )
        if resp.status_code != 200:
            logger.warning(f"[LLM] API 返回 {resp.status_code}: {resp.text[:200]}")
            return None
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.warning(f"[LLM] 网络错误: {e}")
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning(f"[LLM] 解析错误: {e}")
        return None
    except Exception as e:
        logger.warning(f"[LLM] 未知错误: {e}")
        return None


async def generate_model_prompts(
    image_url: str | None,
    product_type: str,
    country_name: str,
    platform: str,
    model_name: str,
    model_tagline: str,
    count: int,
    user_description: str = "",
) -> list[str] | None:
    """生成模特图 prompt 列表，失败返回 None"""
    api_key, llm_model = get_llm_config()
    if not api_key:
        return None

    user_text = build_model_user_prompt(
        product_type, country_name, platform,
        model_name, model_tagline, count, user_description,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_MODEL},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": user_text},
            ],
        },
    ]

    content = await _call_llm(api_key, llm_model, messages)
    if not content:
        return None

    result = _parse_llm_json(content, LLMPromptsOutput)
    if result and result.get("prompts"):
        return result["prompts"]
    return None


async def generate_product_prompts(
    image_url: str | None,
    product_type: str,
    country_name: str,
    platform: str,
    model_name: str,
    model_tagline: str,
    count: int,
    user_description: str = "",
) -> list[str] | None:
    """生成商品图 prompt 列表，失败返回 None"""
    api_key, llm_model = get_llm_config()
    if not api_key:
        return None

    user_text = build_product_user_prompt(
        product_type, country_name, platform,
        model_name, model_tagline, count, user_description,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_PRODUCT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": user_text},
            ],
        },
    ]

    content = await _call_llm(api_key, llm_model, messages)
    if not content:
        return None

    result = _parse_llm_json(content, LLMPromptsOutput)
    if result and result.get("prompts"):
        return result["prompts"]
    return None


async def generate_metadata(
    product_type: str,
    country_name: str,
    platform: str,
    user_description: str = "",
) -> dict | None:
    """生成爆款标题/标签/描述，失败返回 None"""
    api_key, llm_model = get_llm_config()
    if not api_key:
        return None

    user_text = build_metadata_user_prompt(
        product_type, country_name, platform, user_description,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_METADATA},
        {"role": "user", "content": user_text},
    ]

    content = await _call_llm(api_key, llm_model, messages)
    if not content:
        return None

    result = _parse_llm_json(content, LLMMetadata)
    if result:
        if result.get("tags"):
            result["tags"] = _normalize_tags(result["tags"])
        return result
    return None
