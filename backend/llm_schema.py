"""
LLM 智能配置器 — 输出结构化 Schema
"""

from pydantic import BaseModel, Field


class LLMSceneConfig(BaseModel):
    scenes: list[str] = Field(default_factory=list, description="3-5 个场景描述，用于覆盖模板默认场景池")
    poses: list[str] = Field(default_factory=list, description="3-5 个模特姿势描述，用于覆盖模板默认姿势池")
    style_keywords: str = Field(default="", description="风格指引文本，如'日系清新自然风，注重层次搭配'")
    composition_guide: str = Field(default="", description="构图建议，如'上半身特写，重点展示领口和面料垂感'")
    suggested_shot_type: str | None = Field(default=None, description="LLM 建议的拍摄类型：'model' 需要模特展示 / 'product' 产品特写")


class LLMMetadata(BaseModel):
    titles: list[str] = Field(default_factory=list, description="3-5 条爆款标题，含 emoji 和本地化表达")
    tags: list[str] = Field(default_factory=list, description="10-15 个标签，需包含目标市场当地语言")
    description: str = Field(default="", description="商品描述文案")
    target_audience: str = Field(default="", description="目标人群描述")
    detail_focus: str = Field(default="", description="细节特写重点方向")


class LLMOutput(BaseModel):
    scene_config: LLMSceneConfig = Field(default_factory=LLMSceneConfig)
    metadata: LLMMetadata = Field(default_factory=LLMMetadata)
