"""
电商图片生成 - 简化版 Prompt 系统
定位：TikTok Shop 跨境电商 AI 商品图生成
核心思路：LLM 参考图片填模板，直接作为 gpt-image-2 的 prompt
"""
import re

# ============================================================
# 安全防护
# ============================================================

INJECTION_BLOCKLIST = [
    "ignore previous", "ignore all", "ignore above",
    "override", "new instructions", "system prompt",
    "you are now", "act as", "pretend",
    "forget", "disregard", " disregard",
    "忽略之前的", "忽略以上", "忽略前面",
    "你是一个", "你扮演", "假装你是",
    "新的指令", "新指令", "系统提示",
    "覆盖", "不要管", "不要理会",
    "ignore instruction", "ignore above instruction",
    "disregard all", "disregard previous",
    "you must", "you shall", "do not follow",
    "DAN", "jailbreak", "developer mode",
]


class PromptValidationError(Exception):
    """Raised when prompt input fails security validation."""
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


def sanitize_prompt_input(value: str, field_name: str = "input") -> str:
    """消毒用户输入，防止 prompt 注入。拒绝（而非截断）恶意输入。"""
    if not isinstance(value, str):
        return ""
    s = value.strip()[:200]
    for ch in s:
        if ord(ch) < 32 and ch not in ("\n", "\t", "\r"):
            raise PromptValidationError(field_name, "输入包含不允许的控制字符")
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    lower = s.lower()
    for keyword in INJECTION_BLOCKLIST:
        if keyword in lower:
            raise PromptValidationError(field_name, "输入包含不允许的关键词，请修改后重试")
    return s[:200].strip()


# ============================================================
# 品类匹配（简化版，仅用于 LLM 参数传递）
# ============================================================

CATEGORY_TAXONOMY = {
    "fashion_tops": {"name": "上装", "parent": "fashion", "shot_type": "model",
        "keywords": ["衣", "t恤", "衬衫", "针织", "毛衣", "卫衣", "外套", "棉服", "羽绒服", "西装", "马甲",
                     "top", "shirt", "blouse", "jacket", "coat", "hoodie", "sweater", "cardigan", "vest"]},
    "fashion_bottoms": {"name": "下装", "parent": "fashion", "shot_type": "model",
        "keywords": ["裤", "裙", "牛仔裤", "短裙", "长裙", "阔腿裤", "运动裤", "休闲裤", "短裤", "百褶裙",
                     "pant", "jean", "skirt", "short", "legging", "trouser"]},
    "fashion_dress": {"name": "连衣裙/套装", "parent": "fashion", "shot_type": "model",
        "keywords": ["连衣裙", "套装", "连体裤", "旗袍", "礼服", "婚纱",
                     "dress", "gown", "suit", "jumpsuit", "romper", "qipao"]},
    "fashion_shoes": {"name": "鞋履", "parent": "fashion", "shot_type": "product",
        "keywords": ["鞋", "靴", "运动鞋", "高跟鞋", "帆布鞋", "凉鞋", "拖鞋", "皮鞋", "板鞋",
                     "shoe", "boot", "sneaker", "heel", "sandal", "loafer", "slipper"]},
    "fashion_bags": {"name": "箱包", "parent": "fashion", "shot_type": "model",
        "keywords": ["包", "背包", "手提包", "单肩包", "钱包", "挎包", "胸包", "行李箱",
                     "bag", "purse", "wallet", "backpack", "suitcase", "tote", "clutch"]},
    "fashion_accessories": {"name": "配饰", "parent": "fashion", "shot_type": "model",
        "keywords": ["配饰", "帽子", "围巾", "腰带", "手套", "墨镜", "发饰",
                     "hat", "scarf", "belt", "glove", "sunglass", "accessory"]},
    "beauty_makeup": {"name": "彩妆", "parent": "beauty", "shot_type": "product",
        "keywords": ["口红", "眼影", "腮红", "粉底", "遮瑕", "眉笔", "睫毛膏",
                     "lipstick", "eyeshadow", "blush", "foundation", "mascara", "makeup"]},
    "beauty_skincare": {"name": "护肤", "parent": "beauty", "shot_type": "product",
        "keywords": ["护肤", "面霜", "精华", "爽肤水", "乳液", "防晒", "面膜",
                     "skincare", "cream", "serum", "toner", "lotion", "sunscreen", "mask"]},
    "jewelry_rings": {"name": "戒指/手饰", "parent": "jewelry", "shot_type": "product",
        "keywords": ["戒指", "手链", "手镯", "指环", "ring", "bracelet", "bangle"]},
    "jewelry_necklace": {"name": "项链/吊坠", "parent": "jewelry", "shot_type": "model",
        "keywords": ["项链", "吊坠", "链子", "锁骨链", "necklace", "pendant", "chain", "choker"]},
    "jewelry_watch": {"name": "手表", "parent": "jewelry", "shot_type": "model",
        "keywords": ["手表", "腕表", "watch", "timepiece"]},
    "electronics_phone": {"name": "手机/平板", "parent": "electronics", "shot_type": "product",
        "keywords": ["手机", "平板", "iphone", "phone", "tablet", "ipad"]},
    "electronics_audio": {"name": "音频设备", "parent": "electronics", "shot_type": "product",
        "keywords": ["耳机", "音响", "音箱", "麦克风", "headphone", "earphone", "speaker", "microphone", "airpods"]},
    "home_furniture": {"name": "家具", "parent": "home", "shot_type": "product",
        "keywords": ["沙发", "椅子", "桌", "柜", "床", "茶几", "书架",
                     "sofa", "chair", "table", "bed", "desk", "cabinet", "shelf"]},
    "home_lighting": {"name": "灯具", "parent": "home", "shot_type": "product",
        "keywords": ["灯", "台灯", "吊灯", "落地灯", "壁灯", "lamp", "light", "chandelier"]},
    "food_snacks": {"name": "食品/零食", "parent": "food", "shot_type": "product",
        "keywords": ["食品", "零食", "糖果", "巧克力", "饼干", "蛋糕", "面包",
                     "food", "snack", "candy", "chocolate", "cookie", "cake", "bread"]},
    "baby_products": {"name": "母婴用品", "parent": "baby", "shot_type": "product",
        "keywords": ["婴儿", "奶瓶", "童装", "儿童", "母婴", "尿布", "奶嘴",
                     "baby", "kids", "bottle", "diaper"]},
    "pet_products": {"name": "宠物用品", "parent": "pet", "shot_type": "product",
        "keywords": ["宠物", "猫粮", "狗粮", "宠物窝", "猫砂", "宠物玩具",
                     "pet", "cat", "dog", "litter"]},
    "sports_equipment": {"name": "运动器材", "parent": "sports", "shot_type": "product",
        "keywords": ["瑜伽", "健身", "跑步机", "哑铃", "蛋白粉", "运动",
                     "yoga", "gym", "dumbbell", "fitness", "sport"]},
}

DEFAULT_CATEGORY = {"name": "通用商品", "parent": "general", "shot_type": "product"}


def match_category(product_type: str) -> dict:
    """根据用户输入的商品类型匹配最佳品类"""
    t = product_type.lower().strip()
    priority_order = [
        "fashion_dress", "fashion_shoes", "fashion_bags",
        "jewelry_rings", "jewelry_necklace", "jewelry_watch",
        "beauty_makeup", "beauty_skincare", "food_snacks",
        "fashion_tops", "fashion_bottoms", "fashion_accessories",
        "electronics_phone", "electronics_audio",
        "home_furniture", "home_lighting",
        "baby_products", "pet_products", "sports_equipment",
    ]
    for key in priority_order:
        cat = CATEGORY_TAXONOMY[key]
        if any(kw.lower() in t for kw in cat["keywords"]):
            return cat
    return DEFAULT_CATEGORY


# ============================================================
# AI 模型选择（简化版）
# ============================================================

AI_MODEL_PROFILES = {
    "midjourney": {"name": "Midjourney", "tagline": "艺术创意 · 时尚大片"},
    "dalle": {"name": "DALL-E 3", "tagline": "真实细节 · 商业摄影"},
    "flux": {"name": "FLUX", "tagline": "尖端画质 · 天花板品质"},
    "general": {"name": "通用模型", "tagline": "综合均衡 · 适配全品类"},
}

CATEGORY_MODEL_MAP = {
    "fashion": "flux", "beauty": "dalle", "jewelry": "midjourney",
    "electronics": "dalle", "home": "flux", "food": "dalle",
    "baby": "dalle", "pet": "dalle", "sports": "flux", "general": "general",
}

FRONTEND_MODEL_MAP = {
    "portrait": "flux", "fashion": "flux", "product": "dalle",
    "artistic": "midjourney", "viral": "flux",
}


def select_model(user_model: str, category: dict) -> str:
    if user_model in FRONTEND_MODEL_MAP:
        return FRONTEND_MODEL_MAP[user_model]
    if user_model and user_model in AI_MODEL_PROFILES and user_model != "general":
        return user_model
    parent = category.get("parent", "general")
    return CATEGORY_MODEL_MAP.get(parent, "general")


def get_model_profile(model_code: str) -> dict:
    return AI_MODEL_PROFILES.get(model_code, AI_MODEL_PROFILES["general"])


# ============================================================
# 国家市场配置
# ============================================================

MODEL_STYLE_NAMES = [
    "时尚街拍风", "都市休闲风", "杂志大片风", "生活方式风",
    "自信站姿风", "活力户外风", "职业商务风", "海滩度假风",
    "艺术优雅风", "运动活力风", "奢华时尚风",
]

COUNTRY_CONFIG = {
    "japan": {"name": "日本", "flag": "🇯🇵", "language": "日语", "platform": "TikTok Shop Japan",
        "hashtags": ["#TikTokShop", "#新作", "#コーデ", "#プチプラ", "#大人女子", "#おしゃれ", "#骨格診断", "#着痩せ", "#トレンド", "#今日のコーデ"]},
    "china": {"name": "中国", "flag": "🇨🇳", "language": "中文", "platform": "抖音电商",
        "hashtags": ["#穿搭", "#每日穿搭", "#显瘦", "#高级感", "#氛围感", "#好物推荐", "#种草", "#百搭", "#平价好物", "#时髦精"]},
    "korea": {"name": "韩国", "flag": "🇰🇷", "language": "韩语", "platform": "TikTok Shop Korea",
        "hashtags": ["#데일리룩", "#코디", "#패션", "#오오티디", "#스타일", "#신상", "#옷스타그램", "#쇼핑", "#데일리", "#여름코디"]},
    "usa": {"name": "美国", "flag": "🇺🇸", "language": "英语", "platform": "TikTok Shop US",
        "hashtags": ["#TikTokMadeMeBuyIt", "#AmazonFinds", "#OOTD", "#StyleInspo", "#WhatIWore", "#FashionFinds", "#Viral", "#Trending", "#CleanGirl", "#ThatGirl"]},
    "uk": {"name": "英国", "flag": "🇬🇧", "language": "英语", "platform": "TikTok Shop UK",
        "hashtags": ["#TikTokUK", "#BritishStyle", "#OOTD", "#FashionFinds", "#StyleInspo", "#HighStreet", "#LuxuryForLess", "#SustainableFashion", "#UKFashion", "#WhatIWore"]},
    "thailand": {"name": "泰国", "flag": "🇹🇭", "language": "泰语", "platform": "TikTok Shop Thailand",
        "hashtags": ["#TikTokShopTH", "#รีวิว", "#ของดีบอกต่อ", "#ถูกและดี", "#แฟชั่น", "#แต่งตัว", "#ช้อปปิ้ง", "#สวยบอกต่อ", "#ของมันต้องมี", "#ป้ายยา"]},
    "vietnam": {"name": "越南", "flag": "🇻🇳", "language": "越南语", "platform": "TikTok Shop Vietnam",
        "hashtags": ["#TikTokShopVN", "#xuhuong", "#thoitrang", "#aodep", "#muanhanh", "#freeship", "#dangcap", "#sangchanh", "#giatricao", "#review"]},
    "indonesia": {"name": "印度尼西亚", "flag": "🇮🇩", "language": "印尼语", "platform": "TikTok Shop Indonesia",
        "hashtags": ["#TikTokShopID", "#fashion", "#ootdindonesia", "#hits", "#murah", "#berkualitas", "#diskongede", "#gratisongkir", "#viral", "#rekomendasi"]},
    "malaysia": {"name": "马来西亚", "flag": "🇲🇾", "language": "马来语", "platform": "TikTok Shop Malaysia",
        "hashtags": ["#TikTokShopMY", "#fesyen", "#ootdmalaysia", "#cantik", "#murah", "#viral", "#trending", "#fashion", "#style", "#rekomendasi"]},
    "philippines": {"name": "菲律宾", "flag": "🇵🇭", "language": "他加禄语/英语", "platform": "TikTok Shop Philippines",
        "hashtags": ["#TikTokShopPH", "#OOTD", "#fashion", "#style", "#trending", "#mura", "#ganda", "#viral", "#budol", "#rekomendado"]},
    "saudi": {"name": "沙特阿拉伯", "flag": "🇸🇦", "language": "阿拉伯语", "platform": "TikTok Shop Saudi",
        "hashtags": ["#تسوق", "#موضة", "#أناقة", "#تيك_توك", "#فاشن", "#خليجية", "#فخمه", "#جديد", "#تخفيضات", "#ستايل"]},
}


# ============================================================
# 辅助图 prompt（简单模板，不依赖 LLM）
# ============================================================

def build_comparison_prompt(product_type: str, category: dict) -> str:
    product_type = sanitize_prompt_input(product_type)
    name = category.get("name", "通用商品")
    return f"为{product_type}（{name}）生成一张电商对比展示图，左侧纯白底展示，右侧场景化高级展示，同一产品保持一致，干净布局，禁止文字水印"


def build_detail_prompt(product_type: str, category: dict) -> str:
    product_type = sanitize_prompt_input(product_type)
    name = category.get("name", "通用商品")
    return f"为{product_type}（{name}）生成一张细节特写图，微距拍摄展示材质纹理和做工细节，中性背景，禁止文字水印"


# ============================================================
# 降级 prompt（LLM 不可用时）
# ============================================================

def build_fallback_model_prompt(product_type: str) -> str:
    product_type = sanitize_prompt_input(product_type)
    return f"为{product_type}生成一张合适的模特展示图"


def build_fallback_product_prompt(product_type: str) -> str:
    product_type = sanitize_prompt_input(product_type)
    return f"为{product_type}生成一张合适的电商商品图"


# ============================================================
# 标签规范化
# ============================================================

def _normalize_tags(raw_tags) -> list[str]:
    """将 LLM 可能返回的拼接标签拆分为独立标签"""
    if isinstance(raw_tags, str):
        candidates = [raw_tags]
    elif isinstance(raw_tags, list):
        candidates = [str(tag) for tag in raw_tags if tag is not None]
    else:
        return []
    result = []
    seen = set()
    for tag in candidates:
        parts = re.split(r'[\s,，、;；]+', tag.strip())
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if not part.startswith('#'):
                part = '#' + part
            if part not in seen:
                result.append(part)
                seen.add(part)
    return result


# ============================================================
# 任务组装
# ============================================================

def generate_all_tasks(
    product_type: str,
    image_url: str,
    country: str,
    model: str,
    size: str = "auto",
    resolution: str = "1k",
    *,
    category: dict | None = None,
    country_config: dict | None = None,
    model_code: str | None = None,
    model_profile: dict | None = None,
    model_prompts: list[str] | None = None,
    product_prompts: list[str] | None = None,
    metadata: dict | None = None,
    model_image_count: int = 9,
) -> dict:
    """
    组装所有图片任务。
    model_prompts/product_prompts 由 LLM 生成，直接使用。
    未提供时使用降级 prompt。
    """
    category = category or match_category(product_type)
    model_code = model_code or select_model(model, category)
    country_config = country_config or COUNTRY_CONFIG.get(country, COUNTRY_CONFIG["usa"])
    model_profile = model_profile or get_model_profile(model_code)
    model_image_count = max(0, min(9, int(model_image_count)))

    # 模特图 prompt
    model_tasks = []
    for i in range(model_image_count):
        if model_prompts and i < len(model_prompts):
            prompt = model_prompts[i]
        else:
            prompt = build_fallback_model_prompt(product_type)
        model_tasks.append({
            "prompt": prompt,
            "reference_url": image_url,
            "size": size,
            "resolution": resolution,
            "kind": "model",
        })

    # 商品图 prompt
    product_tasks = []
    product_count = 9 - model_image_count
    for i in range(product_count):
        if product_prompts and i < len(product_prompts):
            prompt = product_prompts[i]
        else:
            prompt = build_fallback_product_prompt(product_type)
        product_tasks.append({
            "prompt": prompt,
            "reference_url": image_url,
            "size": size,
            "resolution": resolution,
            "kind": "product",
        })

    # 辅助图
    extra_tasks = [
        {"prompt": build_detail_prompt(product_type, category), "reference_url": image_url, "size": size, "resolution": resolution, "kind": "detail"},
        {"prompt": build_comparison_prompt(product_type, category), "reference_url": image_url, "size": size, "resolution": resolution, "kind": "comparison"},
    ]

    # 元数据
    meta = metadata or {}
    meta_titles = meta.get("titles", [
        f"{product_type} - {country_config['name']}爆款",
        "网红同款推荐",
        "限时热卖",
    ])
    meta_tags = meta.get("tags", country_config.get("hashtags", []))
    meta_desc = meta.get("description", f"高品质{category['name']}，适合{country_config['name']}市场")
    meta_audience = meta.get("target_audience", "18-35岁追求时尚的消费者")

    return {
        "tasks": model_tasks + product_tasks + extra_tasks,
        "model_image_count": model_image_count,
        "category": category,
        "country_config": country_config,
        "model_code": model_code,
        "model_profile": model_profile,
        "titles": meta_titles,
        "tags": _normalize_tags(meta_tags),
        "description": meta_desc,
        "target_audience": meta_audience,
    }
