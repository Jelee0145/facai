"""
LLM 智能配置器 — 阿里云百炼 API 调用
"""

import json
import httpx
from database import get_config
from llm_prompts import (
    SYSTEM_PROMPT_VISION,
    SYSTEM_PROMPT_TEXT,
    build_user_prompt,
    build_user_prompt_with_image,
)

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_TIMEOUT = 30


def get_llm_config() -> tuple[str, str]:
    """从 system_config 读取 LLM 配置，返回 (api_key, model_name)"""
    api_key = get_config("llm_api_key") or ""
    model = get_config("llm_model") or "qwen3-vl-flash"
    return api_key, model


def build_llm_messages(
    image_url: str | None,
    product_type: str,
    country_name: str,
    platform: str,
    model_name: str,
    model_tagline: str,
    category_name: str,
    shot_type: str,
) -> list[dict]:
    """构建 LLM 请求消息（不发起 API 调用），用于日志记录"""
    if image_url:
        system = SYSTEM_PROMPT_VISION
        user_text = build_user_prompt_with_image(
            product_type, country_name, platform,
            model_name, model_tagline, category_name, shot_type,
        )
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": user_text},
                ],
            },
        ]
    else:
        system = SYSTEM_PROMPT_TEXT
        user_text = build_user_prompt(
            product_type, country_name, platform,
            model_name, model_tagline, category_name, shot_type,
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
    return messages


async def analyze(
    image_url: str | None,
    product_type: str,
    country_name: str,
    platform: str,
    model_name: str,
    model_tagline: str,
    category_name: str,
    shot_type: str,
) -> dict | None:
    """
    调用百炼 qwen-vl-flash 分析商品并生成配置
    返回结构化 dict，失败时返回 None（触发降级）
    """
    api_key, llm_model = get_llm_config()
    if not api_key:
        return None

    messages = build_llm_messages(
        image_url, product_type, country_name, platform,
        model_name, model_tagline, category_name, shot_type,
    )

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{DASHSCOPE_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": llm_model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                },
            )

        if resp.status_code != 200:
            print(f"[LLM] API 返回 {resp.status_code}: {resp.text[:200]}")
            return None

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        result = json.loads(content)
        return result

    except httpx.TimeoutException:
        print("[LLM] 请求超时")
        return None
    except httpx.ConnectError:
        print("[LLM] 连接失败")
        return None
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"[LLM] 解析失败: {e}")
        return None
    except Exception as e:
        print(f"[LLM] 未知错误: {e}")
        return None
