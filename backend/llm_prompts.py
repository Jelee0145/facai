"""
LLM 智能配置器 — 阿里云百炼 qwen-vl-flash 提示词模板
"""

SYSTEM_PROMPT_VISION = """你是一个 TikTok Shop 跨境电商商品拍摄专家。
你将收到一张商品参考图，以及用户选择的商品类型、目标市场和拍摄风格。

请完成以下任务：
1. 分析参考图中的商品类型、颜色、材质、设计特点
2. 根据商品特点推荐适合的拍摄场景、构图和模特姿势
3. 为目标市场生成本地化的爆款标题、商品描述和标签
4. 生成适合该商品的目标人群描述和细节特写重点
5. 判断该商品是否需要模特展示：服装、箱包、配饰、珠宝等穿戴类需要模特（model）；电子产品、食品、家居、运动器材等不需要（product）

输出要求：
- 输出严格的 JSON 格式，不包含任何其他内容
- 场景描述要具体、可执行（如"白色极简客厅，自然光从落地窗洒入"）
- 姿势描述仅当商品适合模特展示时提供，否则返回空列表
- 标题要包含 emoji 和本地化表达，符合目标市场爆款风格
- 标签需包含目标市场当地语言的热门标签"""

SYSTEM_PROMPT_TEXT = """你是一个 TikTok Shop 跨境电商商品拍摄专家。
你将收到用户的商品类型、目标市场和拍摄风格信息，请提供专业的商品拍摄方案。

请完成以下任务：
1. 根据商品类型推荐适合的拍摄场景、构图和模特姿势
2. 为目标市场生成本地化的爆款标题、商品描述和标签
3. 生成适合该商品的目标人群描述和细节特写重点
4. 判断该商品是否需要模特展示：服装、箱包、配饰、珠宝等穿戴类需要模特（model）；电子产品、食品、家居、运动器材等不需要（product）

输出要求：
- 输出严格的 JSON 格式，不包含任何其他内容
- 场景描述要具体、可执行
- 姿势描述仅当商品适合模特展示时提供，否则返回空列表
- 标题要包含 emoji 和本地化表达，符合目标市场爆款风格
- 标签需包含目标市场当地语言的热门标签"""


def build_user_prompt(
    product_type: str,
    country_name: str,
    platform: str,
    model_name: str,
    model_tagline: str,
    category_name: str,
    shot_type: str,
) -> str:
    """构建用户消息（无图版）"""
    shot_type_label = "模特展示" if shot_type == "model" else "产品特写"
    return f"""商品类型: {product_type}
目标市场: {country_name} ({platform})
拍摄风格: {model_name} - {model_tagline}
品类: {category_name}
拍摄方式（模板判定）: {shot_type_label}

输出 JSON，格式如下：
{{
  "scene_config": {{
    "scenes": ["场景1", "场景2", "场景3"],
    "poses": ["姿势1", "姿势2"],
    "style_keywords": "风格指引文本",
    "composition_guide": "构图建议",
    "suggested_shot_type": "model 或 product（根据商品判断是否需要模特）"
  }},
  "metadata": {{
    "titles": ["标题1", "标题2", "标题3"],
    "tags": ["#标签1", "#标签2"],
    "description": "商品描述",
    "target_audience": "目标人群",
    "detail_focus": "细节特写重点"
  }}
}}"""


def build_user_prompt_with_image(
    product_type: str,
    country_name: str,
    platform: str,
    model_name: str,
    model_tagline: str,
    category_name: str,
    shot_type: str,
) -> str:
    """构建用户消息（有图版）"""
    shot_type_label = "模特展示" if shot_type == "model" else "产品特写"
    return f"""请参考上方的商品图片，结合以下信息进行分析：

商品类型: {product_type}
目标市场: {country_name} ({platform})
拍摄风格: {model_name} - {model_tagline}
品类: {category_name}
拍摄方式（模板判定）: {shot_type_label}

输出 JSON，格式如下：
{{
  "scene_config": {{
    "scenes": ["场景1", "场景2", "场景3"],
    "poses": ["姿势1", "姿势2"],
    "style_keywords": "风格指引文本",
    "composition_guide": "构图建议",
    "suggested_shot_type": "model 或 product（根据商品判断是否需要模特）"
  }},
  "metadata": {{
    "titles": ["标题1", "标题2", "title3"],
    "tags": ["#标签1", "#标签2"],
    "description": "商品描述",
    "target_audience": "目标人群",
    "detail_focus": "细节特写重点"
  }}
}}"""
