"""
LLM 输出结构化 Schema — 简化版
"""

from pydantic import BaseModel, Field


class LLMPromptsOutput(BaseModel):
    """模特图/商品图 prompt 列表输出"""
    prompts: list[str] = Field(default_factory=list, description="填好的生图提示词列表，每条对应一张图")


class LLMMetadata(BaseModel):
    """爆款内容输出"""
    titles: list[str] = Field(default_factory=list, description="3-5 条爆款标题，含 emoji")
    tags: list[str] | str = Field(default_factory=list, description="10-15 个标签")
    description: str = Field(default="", description="商品描述文案")
    target_audience: str = Field(default="", description="目标人群描述")
