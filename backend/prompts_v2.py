"""
电商图片生成 - 优化版 Prompt 系统
定位：TikTok Shop 跨境电商 AI 商品图生成
"""
import re

INJECTION_BLOCKLIST = [
    "ignore previous", "ignore all", "ignore above",
    "override", "new instructions", "system prompt",
    "you are now", "act as", "pretend",
    "forget", "disregard", " disregard",
    # Chinese injection patterns
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
    """消毒用户输入，防止 prompt 注入。拒绝（而非截断）恶意输入。
    Raises PromptValidationError if injection is detected."""
    if not isinstance(value, str):
        return ""
    s = value.strip()[:200]
    # Reject control characters (except newline/tab which we normalize)
    for ch in s:
        if ord(ch) < 32 and ch not in ("\n", "\t", "\r"):
            raise PromptValidationError(field_name, "输入包含不允许的控制字符")
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    lower = s.lower()
    for keyword in INJECTION_BLOCKLIST:
        if keyword in lower:
            raise PromptValidationError(
                field_name,
                f"输入包含不允许的关键词，请修改后重试"
            )
    return s[:200].strip()


# ============================================================
# 一、商品品类结构化分类体系
# ============================================================

CATEGORY_TAXONOMY = {
    # —— 服装大类 ——
    "fashion_tops": {
        "name": "上装",
        "parent": "fashion",
        "keywords": ["衣", "t恤", "衬衫", "针织", "毛衣", "卫衣", "外套", "棉服", "羽绒服", "西装", "马甲",
                     "top", "shirt", "blouse", "jacket", "coat", "hoodie", "sweater", "cardigan", "vest"],
        "shot_type": "model",
        "composition": "上半身特写或七分身，重点展示领口、袖型、面料垂感和版型",
        "model_pose_pool": [
            "自然站立，双手自然垂放，微微侧身展示侧面版型",
            "单手插兜，另一只手轻撩发丝，展现领口和肩部设计",
            "双手交叉于胸前，展示袖口和衣长",
            "微微后仰，展现上衣的整体轮廓和垂感",
            "侧身45度，展示背部和侧面线条",
        ],
        "detail_focus": "领口做工、袖口收边、面料纹理、纽扣/拉链细节、图案印花清晰度",
        "scene_pool": [
            "现代简约公寓客厅，浅色墙面，柔光落地窗",
            "都市咖啡馆，自然光透过玻璃窗",
            "ins风白墙背景，极简构图",
            "城市天台，傍晚金色阳光",
            "品牌服装店试衣间，全身镜",
        ],
        "best_model": "flux",
    },

    "fashion_bottoms": {
        "name": "下装",
        "parent": "fashion",
        "keywords": ["裤", "裙", "牛仔裤", "短裙", "长裙", "阔腿裤", "运动裤", "休闲裤", "短裤", "百褶裙",
                     "pant", "jean", "skirt", "short", "legging", "trouser"],
        "shot_type": "model",
        "composition": "下半身或全身，突出腰型、裤型/裙型、长度和面料垂坠感",
        "model_pose_pool": [
            "正面站立，双腿微微错开，展示裤型轮廓",
            "侧身展示，一条腿微曲，展现面料垂感",
            "行走姿态抓拍，展示动态穿着效果",
            "坐姿展示，突出腰部和臀部版型",
        ],
        "detail_focus": "腰头做工、拉链/纽扣品质、裤缝对齐、口袋设计、面料纹理",
        "scene_pool": [
            "都市商业街，时尚街拍背景",
            "简约室内空间，白色墙壁",
            "户外公园步道，自然光线",
        ],
        "best_model": "flux",
    },

    "fashion_dress": {
        "name": "连衣裙/套装",
        "parent": "fashion",
        "keywords": ["连衣裙", "套装", "连体裤", "旗袍", "礼服", "婚纱",
                     "dress", "gown", "suit", "jumpsuit", "romper", "qipao"],
        "shot_type": "model",
        "composition": "全身拍摄，展现整体轮廓、裙摆效果和设计亮点",
        "model_pose_pool": [
            "优雅转身，裙摆微扬，展示裙型",
            "单手轻提裙摆，自信微笑",
            "侧身回眸，展现背部设计",
            "坐姿展示，裙摆自然散开",
        ],
        "detail_focus": "整体版型、接缝做工、裙摆层次、装饰细节、面料光泽",
        "scene_pool": [
            "高端酒店大堂，大理石地面",
            "花园草坪，自然光线",
            "法式阳台，复古栏杆",
            "艺术画廊，简约背景",
        ],
        "best_model": "midjourney",
    },

    "fashion_shoes": {
        "name": "鞋履",
        "parent": "fashion",
        "keywords": ["鞋", "靴", "运动鞋", "高跟鞋", "帆布鞋", "凉鞋", "拖鞋", "皮鞋", "板鞋",
                     "shoe", "boot", "sneaker", "heel", "sandal", "loafer", "slipper"],
        "shot_type": "product",
        "composition": "产品特写，多角度展示鞋型、鞋面和鞋底",
        "model_pose_pool": [],
        "detail_focus": "鞋面材质质感、缝线细节、鞋底纹路、鞋带/扣件、品牌标识",
        "scene_pool": [
            "纯白背景，专业产品摄影",
            "木质地板，自然光线",
            "大理石台面，高级感",
            "城市街道路面，户外场景",
        ],
        "best_model": "dalle",
    },

    "fashion_bags": {
        "name": "箱包",
        "parent": "fashion",
        "keywords": ["包", "背包", "手提包", "单肩包", "钱包", "挎包", "胸包", "行李箱",
                     "bag", "purse", "wallet", "backpack", "suitcase", "tote", "clutch"],
        "shot_type": "model",
        "composition": "模特手持或肩背，展示包型和搭配效果",
        "model_pose_pool": [
            "单肩背，自然行走姿态",
            "手持包袋，展示正面细节",
            "将包放在桌面上，展示立体结构",
        ],
        "detail_focus": "皮质纹理、五金配件光泽、缝线走线、肩带细节、内部结构",
        "scene_pool": [
            "高端商场走廊",
            "都市街头，时尚街拍",
            "简约咖啡厅桌面",
        ],
        "best_model": "dalle",
    },

    "fashion_accessories": {
        "name": "配饰",
        "parent": "fashion",
        "keywords": ["配饰", "帽子", "围巾", "腰带", "手套", "墨镜", "发饰", "帽子",
                     "hat", "scarf", "belt", "glove", "sunglass", "accessory"],
        "shot_type": "model",
        "composition": "模特佩戴展示，突出配饰的搭配效果和细节",
        "model_pose_pool": [
            "特写面部，展示帽子/墨镜细节",
            "半身展示，围巾/腰带自然搭配",
        ],
        "detail_focus": "材质做工、颜色饱和度、佩戴效果、搭配和谐度",
        "scene_pool": ["户外自然光", "室内柔光", "街拍风格"],
        "best_model": "flux",
    },

    # —— 美妆大类 ——
    "beauty_makeup": {
        "name": "彩妆",
        "parent": "beauty",
        "keywords": ["口红", "眼影", "腮红", "粉底", "遮瑕", "眉笔", "睫毛膏",
                     "lipstick", "eyeshadow", "blush", "foundation", "mascara", "makeup"],
        "shot_type": "product",
        "composition": "产品平铺或手持展示，突出包装质感和色号",
        "model_pose_pool": [],
        "detail_focus": "膏体质地、颜色饱和度、包装质感、刷头细节",
        "scene_pool": [
            "化妆台，柔光镜前灯",
            "纯白大理石台面，自然光",
            "ins风平铺，花瓣装饰",
        ],
        "best_model": "dalle",
    },

    "beauty_skincare": {
        "name": "护肤",
        "parent": "beauty",
        "keywords": ["护肤", "面霜", "精华", "爽肤水", "乳液", "防晒", "面膜",
                     "skincare", "cream", "serum", "toner", "lotion", "sunscreen", "mask"],
        "shot_type": "product",
        "composition": "产品洁净展示，突出包装设计和容量",
        "model_pose_pool": [],
        "detail_focus": "瓶身设计、泵头做工、质地展示、成分标注",
        "scene_pool": [
            "spa风格浴室，植物点缀",
            "极简白色台面",
            "自然光窗边，绿植",
        ],
        "best_model": "dalle",
    },

    # —— 珠宝手表大类 ——
    "jewelry_rings": {
        "name": "戒指/手饰",
        "parent": "jewelry",
        "keywords": ["戒指", "手链", "手镯", "指环",
                     "ring", "bracelet", "bangle"],
        "shot_type": "product",
        "composition": "微距拍摄，突出金属光泽和宝石火彩",
        "model_pose_pool": [],
        "detail_focus": "镶嵌工艺、金属质感、宝石切割、戒圈细节",
        "scene_pool": [
            "黑色丝绒背景，聚光灯",
            "大理石台面，自然光",
            "手持佩戴展示",
        ],
        "best_model": "dalle",
    },

    "jewelry_necklace": {
        "name": "项链/吊坠",
        "parent": "jewelry",
        "keywords": ["项链", "吊坠", "链子", "锁骨链",
                     "necklace", "pendant", "chain", "choker"],
        "shot_type": "model",
        "composition": "模特佩戴，展示项链长度和锁骨搭配效果",
        "model_pose_pool": [
            "侧脸微微低头，展示颈部线条和项链",
            "正面特写锁骨区域",
        ],
        "detail_focus": "链子接口、吊坠细节、金属光泽、长度展示",
        "scene_pool": [
            "柔光人像特写背景",
            "黑色背景珠宝展示",
        ],
        "best_model": "midjourney",
    },

    "jewelry_watch": {
        "name": "手表",
        "parent": "jewelry",
        "keywords": ["手表", "腕表", "watch", "timepiece"],
        "shot_type": "model",
        "composition": "手腕佩戴展示，突出表盘设计和表带材质",
        "model_pose_pool": [
            "手腕抬起，展示表盘正面",
            "侧腕展示表带和表扣",
        ],
        "detail_focus": "表盘细节、指针做工、表带材质、表扣设计",
        "scene_pool": [
            "商务办公桌面",
            "深色背景，聚光展示",
        ],
        "best_model": "dalle",
    },

    # —— 电子产品大类 ——
    "electronics_phone": {
        "name": "手机/平板",
        "parent": "electronics",
        "keywords": ["手机", "平板", "iphone", "phone", "tablet", "ipad"],
        "shot_type": "product",
        "composition": "产品多角度展示，屏幕点亮状态",
        "model_pose_pool": [],
        "detail_focus": "屏幕显示效果、边框做工、摄像头模组、接口细节",
        "scene_pool": [
            "现代简约桌面",
            "手持展示，自然场景",
            "纯色背景产品摄影",
        ],
        "best_model": "dalle",
    },

    "electronics_audio": {
        "name": "音频设备",
        "parent": "electronics",
        "keywords": ["耳机", "音响", "音箱", "麦克风",
                     "headphone", "earphone", "speaker", "microphone", "airpods"],
        "shot_type": "product",
        "composition": "产品展示，可搭配使用场景",
        "model_pose_pool": [],
        "detail_focus": "耳罩材质、线材接口、品牌标识、按键布局",
        "scene_pool": [
            "音乐工作室桌面",
            "简约生活场景",
        ],
        "best_model": "dalle",
    },

    # —— 家居大类 ——
    "home_furniture": {
        "name": "家具",
        "parent": "home",
        "keywords": ["沙发", "椅子", "桌", "柜", "床", "茶几", "书架",
                     "sofa", "chair", "table", "bed", "desk", "cabinet", "shelf"],
        "shot_type": "product",
        "composition": "场景化展示，展示家具在空间中的效果",
        "model_pose_pool": [],
        "detail_focus": "材质纹理、接缝做工、五金配件、表面处理",
        "scene_pool": [
            "北欧风客厅，充足自然光",
            "现代简约卧室",
            "工业loft空间",
        ],
        "best_model": "flux",
    },

    "home_lighting": {
        "name": "灯具",
        "parent": "home",
        "keywords": ["灯", "台灯", "吊灯", "落地灯", "壁灯",
                     "lamp", "light", "chandelier"],
        "shot_type": "product",
        "composition": "点亮状态展示灯光效果",
        "model_pose_pool": [],
        "detail_focus": "灯罩材质、光源色温、开关设计、底座做工",
        "scene_pool": [
            "温馨卧室角落",
            "现代客厅黄昏氛围",
        ],
        "best_model": "flux",
    },

    # —— 食品大类 ——
    "food_snacks": {
        "name": "食品/零食",
        "parent": "food",
        "keywords": ["食品", "零食", "糖果", "巧克力", "饼干", "蛋糕", "面包",
                     "food", "snack", "candy", "chocolate", "cookie", "cake", "bread"],
        "shot_type": "product",
        "composition": "美食摄影风格，突出食欲感和包装",
        "model_pose_pool": [],
        "detail_focus": "食材新鲜度、包装设计、配料可见、产品质感",
        "scene_pool": [
            "阳光餐桌，精致摆盘",
            "木质桌面，自然光",
            "美食摄影棚，暗色背景",
        ],
        "best_model": "dalle",
    },

    # —— 母婴大类 ——
    "baby_products": {
        "name": "母婴用品",
        "parent": "baby",
        "keywords": ["婴儿", "奶瓶", "童装", "儿童", "母婴", "尿布", "奶嘴",
                     "baby", "kids", "bottle", "diaper"],
        "shot_type": "product",
        "composition": "安全温馨展示，突出材质安全和使用场景",
        "model_pose_pool": [],
        "detail_focus": "材质安全标识、刻度清晰度、密封设计、柔软度",
        "scene_pool": [
            "温馨婴儿房，柔光",
            "浅色背景，安全展示",
        ],
        "best_model": "dalle",
    },

    # —— 宠物大类 ——
    "pet_products": {
        "name": "宠物用品",
        "parent": "pet",
        "keywords": ["宠物", "猫粮", "狗粮", "宠物窝", "猫砂", "宠物玩具",
                     "pet", "cat", "dog", "litter"],
        "shot_type": "product",
        "composition": "宠物友好场景展示",
        "model_pose_pool": [],
        "detail_focus": "材质安全、容量标注、实用性、包装密封",
        "scene_pool": [
            "温馨家庭宠物角",
            "户外草地自然光",
        ],
        "best_model": "dalle",
    },

    # —— 运动大类 ——
    "sports_equipment": {
        "name": "运动器材",
        "parent": "sports",
        "keywords": ["瑜伽", "健身", "跑步机", "哑铃", "蛋白粉", "运动",
                     "yoga", "gym", "dumbbell", "fitness", "sport"],
        "shot_type": "product",
        "composition": "运动场景展示，体现使用效果",
        "model_pose_pool": [],
        "detail_focus": "材质做工、握感设计、承重标识、防滑处理",
        "scene_pool": [
            "专业健身房",
            "户外运动场景",
            "家庭健身角落",
        ],
        "best_model": "flux",
    },
}

# 默认分类（兜底）
DEFAULT_CATEGORY = {
    "name": "通用商品",
    "parent": "general",
    "shot_type": "product",
    "composition": "专业商品展示",
    "model_pose_pool": [],
    "detail_focus": "商品外观、材质质感、设计细节",
    "scene_pool": [
        "纯白背景专业产品摄影",
        "简约场景展示",
    ],
    "best_model": "general",
}


def match_category(product_type: str) -> dict:
    """根据用户输入的商品类型匹配最佳品类"""
    t = product_type.lower().strip()

    # 按品类顺序匹配，优先匹配更具体的
    priority_order = [
        # 先匹配细分品类
        "fashion_dress", "fashion_shoes", "fashion_bags",
        "jewelry_rings", "jewelry_necklace", "jewelry_watch",
        "beauty_makeup", "beauty_skincare",
        "food_snacks",
        # 再匹配大类
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
# 二、AI 模型选择引擎
# ============================================================

AI_MODEL_PROFILES = {
    "midjourney": {
        "name": "Midjourney",
        "tagline": "艺术创意 · 时尚大片",
        "strengths": ["fashion", "jewelry", "artistic product"],
        "quality": "cinematic masterpiece, award-winning commercial photography, viral social media content",
        "style": "Midjourney aesthetic, editorial fashion, dramatic composition, creative storytelling",
        "lighting": "dramatic rim lighting, volumetric rays, golden hour warmth, cinematic shadows",
        "camera": "Hasselblad medium format, 85mm f/1.2 portrait lens, shallow depth of field",
        "color_grade": "film-like color grading, rich contrast, warm undertones",
    },
    "dalle": {
        "name": "DALL-E 3",
        "tagline": "真实细节 · 商业摄影",
        "strengths": ["product", "jewelry", "beauty", "food", "electronics", "baby", "pet"],
        "quality": "photorealistic commercial quality, hyper-detailed product texture, magazine advertising standard",
        "style": "DALL-E 3 precision, professional product photography, clean commercial aesthetic, Amazon/eBay listing ready",
        "lighting": "professional studio soft box, clean even illumination, product light tent quality",
        "camera": "Sony A7R V with 90mm macro lens, product photography setup, focus stacking sharpness",
        "color_grade": "accurate product colors, clean white balance, commercial color profile",
    },
    "flux": {
        "name": "FLUX",
        "tagline": "尖端画质 · 天花板品质",
        "strengths": ["fashion", "home", "sports", "all"],
        "quality": "cutting-edge AI quality, ultra-realistic textures, flawless rendering, professional excellence",
        "style": "FLUX state-of-the-art, luxury brand campaign, premium editorial, high fashion magazine cover",
        "lighting": "multi-point luxury studio setup, hair light + rim light + key light, fashion week quality",
        "camera": "Phase One medium format, premium fashion lenses, luxury brand photography standard",
        "color_grade": "luxury editorial color, premium tonal range, high-end fashion processing",
    },
    "general": {
        "name": "通用模型",
        "tagline": "综合均衡 · 适配全品类",
        "strengths": ["all"],
        "quality": "8K ultra realistic, sharp professional quality, e-commerce ready standard",
        "style": "professional commercial photography, versatile product showcase, social media optimized",
        "lighting": "professional studio lighting with soft shadows, balanced exposure, commercial quality",
        "camera": "professional DSLR/mirrorless camera, versatile focal lengths, product and fashion capable",
        "color_grade": "balanced commercial colors, natural skin tones, accurate product colors",
    },
}

# 品类 → 推荐模型映射
CATEGORY_MODEL_MAP = {
    "fashion": "flux",          # 服装 → FLUX（画质天花板）
    "beauty": "dalle",          # 美妆 → DALL-E（细节真实）
    "jewelry": "midjourney",    # 珠宝 → Midjourney（艺术质感）
    "electronics": "dalle",     # 电子 → DALL-E（产品细节）
    "home": "flux",             # 家居 → FLUX（空间场景）
    "food": "dalle",            # 食品 → DALL-E（食物真实感）
    "baby": "dalle",            # 母婴 → DALL-E（安全温馨）
    "pet": "dalle",             # 宠物 → DALL-E（生动活泼）
    "sports": "flux",           # 运动 → FLUX（动感品质）
    "general": "general",       # 通用 → general
}


FRONTEND_MODEL_MAP = {
    "portrait": "flux",
    "fashion": "flux",
    "product": "dalle",
    "artistic": "midjourney",
    "viral": "flux",
}

def select_model(user_model: str, category: dict) -> str:
    """智能模型选择 — 支持前端模型码，映射到对应 AI 模型"""
    if user_model in FRONTEND_MODEL_MAP:
        return FRONTEND_MODEL_MAP[user_model]

    if user_model and user_model in AI_MODEL_PROFILES and user_model != "general":
        return user_model

    parent = category.get("parent", "general")
    return CATEGORY_MODEL_MAP.get(parent, "general")


def get_model_profile(model_code: str) -> dict:
    return AI_MODEL_PROFILES.get(model_code, AI_MODEL_PROFILES["general"])


# ============================================================
# 三、国家市场本地化配置
# ============================================================

MODEL_STYLE_NAMES = [
    "时尚街拍风", "都市休闲风", "杂志大片风", "生活方式风",
    "自信站姿风", "活力户外风", "职业商务风", "海滩度假风",
    "艺术优雅风", "运动活力风", "奢华时尚风",
]

COUNTRY_CONFIG = {
    "japan": {
        "name": "日本", "flag": "🇯🇵", "language": "日语",
        "platform": "TikTok Shop Japan",
        "model_desc": "Japanese woman, 22-28 years old, fair porcelain skin, natural kawaii makeup, long silky black hair with subtle brown tint, height 158-165cm, slim build",
        "style_preference": "日系清透自然风，注重层次搭配和细节质感，强调'可爱'和'上品'感",
        "shopping_behavior": "注重品质和细节，偏好日系品牌风格，受KOL推荐影响大",
        "hashtags": ["#TikTokShop", "#新作", "#コーデ", "#プチプラ", "#大人女子", "#おしゃれ", "#骨格診断", "#着痩せ", "#トレンド", "#今日のコーデ"],
    },
    "china": {
        "name": "中国", "flag": "🇨🇳", "language": "中文",
        "platform": "抖音电商",
        "model_desc": "Chinese woman, 20-30 years old, fair skin, natural elegant makeup, long black hair, height 160-170cm, modern urban style, confident presence",
        "style_preference": "国潮新中式或现代都市风，注重显瘦显高效果，强调高级感和氛围感",
        "shopping_behavior": "小红书种草驱动，关注平替和性价比，追求精致生活方式",
        "hashtags": ["#穿搭", "#每日穿搭", "#显瘦", "#高级感", "#氛围感", "#好物推荐", "#种草", "#百搭", "#平价好物", "#时髦精"],
    },
    "korea": {
        "name": "韩国", "flag": "🇰🇷", "language": "韩语",
        "platform": "TikTok Shop Korea",
        "model_desc": "Korean woman, 20-28 years old, flawless glass skin, trendy K-beauty makeup, various hair colors/styles, height 160-168cm, slim and tall proportions",
        "style_preference": "韩系简约时尚，强调身材比例和色彩搭配，注重'氛围感'和'清冷感'",
        "shopping_behavior": "追求最新潮流，受明星和网红影响大，注重品牌和设计感",
        "hashtags": ["#데일리룩", "#코디", "#패션", "#오오티디", "#스타일", "#신상", "#옷스타그램", "#쇼핑", "#데일리", "#여름코디"],
    },
    "usa": {
        "name": "美国", "flag": "🇺🇸", "language": "英语",
        "platform": "TikTok Shop US",
        "model_desc": "American woman, 20-35 years old, diverse beauty, natural confident style, healthy glow, various body types represented, effortless chic",
        "style_preference": "美式休闲自信风，强调个性和真实感，注重穿搭的实用性和舒适度",
        "shopping_behavior": "冲动消费，TikTok趋势驱动，关注性价比和快速配送",
        "hashtags": ["#TikTokMadeMeBuyIt", "#AmazonFinds", "#OOTD", "#StyleInspo", "#WhatIWore", "#FashionFinds", "#Viral", "#Trending", "#CleanGirl", "#ThatGirl"],
    },
    "uk": {
        "name": "英国", "flag": "🇬🇧", "language": "英语",
        "platform": "TikTok Shop UK",
        "model_desc": "British woman, 22-35 years old, fair complexion, elegant and sophisticated style, natural subtle makeup, poised and refined presence",
        "style_preference": "英伦优雅风，强调质感和细节，偏好经典款和高质量面料",
        "shopping_behavior": "注重品质和品牌故事，偏好可持续时尚，受时尚博主影响",
        "hashtags": ["#TikTokUK", "#BritishStyle", "#OOTD", "#FashionFinds", "#StyleInspo", "#HighStreet", "#LuxuryForLess", "#SustainableFashion", "#UKFashion", "#WhatIWore"],
    },
    "thailand": {
        "name": "泰国", "flag": "🇹🇭", "language": "泰语",
        "platform": "TikTok Shop Thailand",
        "model_desc": "Thai woman, 20-30 years old, warm bronze skin, Southeast Asian beauty features, long natural black hair, friendly and bright smile, youthful energy",
        "style_preference": "东南亚清新甜美风，活泼色彩和印花，注重清凉透气面料",
        "shopping_behavior": "价格敏感，受直播带货影响大，偏好促销和折扣",
        "hashtags": ["#TikTokShopTH", "#รีวิว", "#ของดีบอกต่อ", "#ถูกและดี", "#แฟชั่น", "#แต่งตัว", "#ช้อปปิ้ง", "#สวยบอกต่อ", "#ของมันต้องมี", "#ป้ายยา"],
    },
    "vietnam": {
        "name": "越南", "flag": "🇻🇳", "language": "越南语",
        "platform": "TikTok Shop Vietnam",
        "model_desc": "Vietnamese woman, 18-28 years old, warm light-brown skin, youthful fresh appearance, long straight black hair, slim petite build, bright smile",
        "style_preference": "年轻活力风，受韩流影响，偏好修身款式和清新色调",
        "shopping_behavior": "年轻消费者主导，社交电商活跃，追求性价比和潮流",
        "hashtags": ["#TikTokShopVN", "#xuhuong", "#thoitrang", "#aodep", "#muanhanh", "#freeship", "#dangcap", "#sangchanh", "#giatricao", "#review"],
    },
    "indonesia": {
        "name": "印度尼西亚", "flag": "🇮🇩", "language": "印尼语",
        "platform": "TikTok Shop Indonesia",
        "model_desc": "Indonesian woman, 20-30 years old, warm medium skin tone, Javanese/Southeast Asian features, modest and elegant style, friendly approachable look",
        "style_preference": "东南亚穆斯林时尚，注重端庄和现代结合，偏好舒适面料",
        "shopping_behavior": "社交电商大国，关注价格和促销，受本地KOL影响",
        "hashtags": ["#TikTokShopID", "#fashion", "#ootdindonesia", "#hits", "#murah", "#berkualitas", "#diskongede", "#gratisongkir", "#viral", "#rekomendasi"],
    },
    "malaysia": {
        "name": "马来西亚", "flag": "🇲🇾", "language": "马来语",
        "platform": "TikTok Shop Malaysia",
        "model_desc": "Malaysian woman, 20-30 years old, warm golden-brown skin, Southeast Asian beauty with diverse ethnic features (Malay, Chinese, Indian), modern modest fashion with vibrant colors, friendly warm smile",
        "style_preference": "多元文化融合风，马来传统与现代结合，偏好舒适透气的棉麻面料和鲜艳色彩",
        "shopping_behavior": "年轻消费者活跃，受社交媒体和直播影响大，关注性价比和促销活动",
        "hashtags": ["#TikTokShopMY", "#fesyen", "#ootdmalaysia", "#cantik", "#murah", "#viral", "#trending", "#fashion", "#style", "#rekomendasi"],
    },
    "philippines": {
        "name": "菲律宾", "flag": "🇵🇭", "language": "他加禄语/英语",
        "platform": "TikTok Shop Philippines",
        "model_desc": "Filipina woman, 20-30 years old, warm tan skin, Southeast Asian features with Spanish influence, long dark hair, bright cheerful smile, slim to medium build, trendy confident style",
        "style_preference": "东南亚甜美时髦风，受韩流和美国潮流双重影响，偏好修身剪裁和清新色彩",
        "shopping_behavior": "社交媒体高度活跃，TikTok趋势驱动消费，注重性价比和快速配送",
        "hashtags": ["#TikTokShopPH", "#OOTD", "#fashion", "#style", "#trending", "#mura", "#ganda", "#viral", "#budol", "#rekomendado"],
    },
    "saudi": {
        "name": "沙特阿拉伯", "flag": "🇸🇦", "language": "阿拉伯语",
        "platform": "TikTok Shop Saudi",
        "model_desc": "Saudi woman, 22-35 years old, elegant abaya and modest fashion style, sophisticated Middle Eastern beauty, modern hijab styling, luxurious accessories",
        "style_preference": "中东海湾奢华风，注重面料品质和设计感，偏好优雅端庄款式",
        "shopping_behavior": "高消费力，追求品牌和品质，偏好奢华和独特设计",
        "hashtags": ["#تسوق", "#موضة", "#أناقة", "#تيك_توك", "#فاشن", "#خليجية", "#فخمه", "#جديد", "#تخفيضات", "#ستايل"],
    },
}


# ============================================================
# 四、Prompt 模板引擎
# ============================================================

def build_fashion_prompt(
    index: int,
    product_type: str,
    country: str,
    category: dict,
    scene_pool_override: list | None = None,
    pose_pool_override: list | None = None,
    style_keywords_override: str = "",
    composition_override: str = "",
    shot_type_override: str | None = None,
) -> dict:
    product_type = sanitize_prompt_input(product_type)
    country_cfg = COUNTRY_CONFIG.get(country, COUNTRY_CONFIG["usa"])
    shot_type = shot_type_override or category.get("shot_type", "product")
    composition_guide = composition_override or category.get("composition", "专业商品展示")

    scene_pool = scene_pool_override or category.get("scene_pool", ["专业产品摄影场景"])
    scene = scene_pool[index % len(scene_pool)]

    if shot_type == "model":
        pose_pool = pose_pool_override or category.get("model_pose_pool", ["自然站立展示商品正面"])
        if not pose_pool:
            pose_pool = ["自然站立展示商品正面"]
        pose = pose_pool[index % len(pose_pool)]
        style_extra = f"\n风格补充：{style_keywords_override}" if style_keywords_override else ""
        prompt = f"""拍摄一张用于{country_cfg['platform']}店铺的专业电商模特图。

商品：{product_type}（{category['name']}）

模特要求：{country_cfg['model_desc']}
模特姿势：{pose}
穿搭风格：{country_cfg['style_preference']}{style_extra}

场景：{scene}

拍摄要求：
- 商业摄影级别，商品在画面中心清晰可见
- 模特展示商品的实际使用/佩戴效果
- {composition_guide}

禁止元素：
- 禁止文字、水印、Logo、价格标签
- 禁止二维码、条形码、网址
- 禁止AI生成痕迹和图像失真
- 禁止低分辨率、模糊、噪点
- 禁止不适当的非商业内容"""
    else:
        prompt = f"""拍摄一张用于{country_cfg['platform']}店铺的专业电商商品图。

商品：{product_type}（{category['name']}）

场景：{scene}

拍摄要求：
- 产品专属展示，无人类模特
- 商品居中，背景干净简洁
- 商业摄影级别，高清晰度，细节清晰

禁止元素：
- 禁止文字、水印、Logo、价格标签
- 禁止二维码、条形码、网址
- 禁止人物出现，仅展示商品
- 禁止AI生成痕迹和图像失真
- 禁止低分辨率、模糊、噪点
- 禁止不适当的非商业内容"""

    return {
        "prompt": prompt,
        "category": category["name"],
        "shot_type": shot_type,
    }


def build_comparison_prompt(product_type: str, category: dict) -> str:
    """竞品对比图 prompt"""
    product_type = sanitize_prompt_input(product_type)
    return f"""拍摄一张{product_type}（{category['name']}）的竞品对比图。

左侧（劣质竞品）：
- 白色或杂乱背景，光线平淡，色彩暗淡
- 无造型，业余手机摄影风格

右侧（优质商品）：
- 专业造型展示，美丽场景背景
- 电影级灯光，高端商业风格

中间有细微分隔线。禁止文字、水印、标签。"""


def build_white_comparison_prompt(product_type: str, category: dict) -> str:
    """白底图 + 对比图合成 prompt"""
    product_type = sanitize_prompt_input(product_type)
    return f"""拍摄一张{product_type}（{category['name']}）的对比展示图。

左侧：纯白背景产品展示，居中，高光线
右侧：升级版电商展示，更丰富的灯光和角度

要求：
- 同一产品，保持一致的颜色、材质和设计
- 无人类模特，仅展示产品
- 干净的对比布局，无文字标签

禁止水印、Logo、二维码、边框。"""


def build_detail_prompt(product_type: str, category: dict, detail_focus_override: str | None = None) -> str:
    """细节放大图 prompt"""
    product_type = sanitize_prompt_input(product_type)
    detail_focus = detail_focus_override or category.get('detail_focus', '材质、做工、设计细节')
    return f"""拍摄一张{product_type}（{category['name']}）的细节特写图。

需要展示的细节：{detail_focus}

拍摄要求：
- 微距特写，清晰展示材质纹理和做工细节
- 专业微距摄影级别，边缘清晰
- 中性背景，不干扰商品展示

禁止文字、水印、Logo。"""


def build_white_bg_prompt(product_type: str, category: dict) -> str:
    """白底展示图 prompt"""
    product_type = sanitize_prompt_input(product_type)
    return f"""拍摄一张{product_type}（{category['name']}）的白底商品图。

要求：
- 纯白色背景（#FFFFFF），无限白色背景
- 产品居中，干净整洁，无阴影
- 高清晰度，商业摄影级别

禁止文字、水印、Logo、装饰元素。"""


# ============================================================
# 五、快速生成入口（兼容旧接口）
# ============================================================

def _normalize_tags(raw_tags: list[str]) -> list[str]:
    """将 LLM 可能返回的拼接标签拆分为独立标签"""
    result = []
    for tag in raw_tags:
        parts = re.split(r'[\s,]+', tag.strip())
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if not part.startswith('#'):
                part = '#' + part
            result.append(part)
    return result if result else raw_tags


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
    llm_config: dict | None = None,
    model_image_count: int = 9,
) -> dict:
    """
    一站式生成所有图片任务
    接收外部传入的 category/country_config/model_code 避免重复计算
    llm_config 为 LLM 分析结果，可覆盖场景/姿势/标题/标签/描述
    返回: {tasks, category, country_config, model_code}
    """
    category = category or match_category(product_type)
    model_code = model_code or select_model(model, category)
    country_config = country_config or COUNTRY_CONFIG.get(country, COUNTRY_CONFIG["usa"])
    model_profile = model_profile or get_model_profile(model_code)

    # LLM 覆盖场景/姿势池（非空时生效）
    scene_pool = category.get("scene_pool", ["专业产品摄影场景"])
    pose_pool = category.get("model_pose_pool", [])
    meta_titles = [
        f"{product_type} - {country_config['name']}爆款",
        "网红同款推荐",
        "限时热卖",
    ]
    meta_tags = country_config.get("hashtags", [])
    meta_desc = f"高品质{category['name']}，适合{country_config['name']}市场"
    meta_audience = "18-35岁追求时尚的消费者"
    meta_detail_focus = category.get("detail_focus", "商品外观、材质质感、设计细节")
    llm_style_keywords = ""
    llm_composition_guide = category.get("composition", "专业商品展示")

    # 标记哪些字段被 LLM 覆盖
    has_llm_scenes = False
    has_llm_poses = False
    has_llm_detail = False

    if llm_config:
        sc = llm_config.get("scene_config", {})
        if sc.get("scenes"):
            scene_pool = sc["scenes"]
            has_llm_scenes = True
        if sc.get("poses"):
            pose_pool = sc["poses"]
            has_llm_poses = True
        if sc.get("style_keywords"):
            llm_style_keywords = sc["style_keywords"]
        if sc.get("composition_guide"):
            llm_composition_guide = sc["composition_guide"]

        md = llm_config.get("metadata", {})
        if md.get("titles"):
            meta_titles = md["titles"]
        if md.get("tags"):
            meta_tags = _normalize_tags(md["tags"])
        if md.get("description"):
            meta_desc = md["description"]
        if md.get("target_audience"):
            meta_audience = md["target_audience"]
        if md.get("detail_focus"):
            meta_detail_focus = md["detail_focus"]
            has_llm_detail = True

        # LLM 建议 shot_type：仅当品类走默认分类（无关键词匹配）时应用
        # 已知品类模板已有合理的 shot_type，不需要改
        if category.get("parent") == "general":
            st = sc.get("suggested_shot_type")
            if st == "model":
                category = dict(category)
                category["shot_type"] = "model"
                category["composition"] = sc.get("composition_guide") or "商品展示，模特搭配"
                if not has_llm_poses:
                    pose_pool = ["自然站立展示商品正面", "侧身展示商品细节"]
                    has_llm_poses = True

    model_image_count = max(0, min(9, int(model_image_count)))

    # 9 张主图：前 N 张带模特，剩余为无模特商品图
    main_tasks = []
    for i in range(9):
        shot_type = "model" if i < model_image_count else "product"
        result = build_fashion_prompt(
            i, product_type, country, category,
            scene_pool_override=scene_pool if has_llm_scenes else None,
            pose_pool_override=pose_pool if has_llm_poses else None,
            style_keywords_override=llm_style_keywords,
            composition_override=llm_composition_guide,
            shot_type_override=shot_type,
        )
        main_tasks.append({
            "prompt": result["prompt"],
            "reference_url": image_url,
            "size": size,
            "resolution": resolution,
            "kind": shot_type,
        })

    # 1 张局部大图 + 1 张白底/对比合成图
    extra_tasks = [
        {"prompt": build_detail_prompt(product_type, category, detail_focus_override=meta_detail_focus if has_llm_detail else None), "reference_url": image_url, "size": size, "resolution": resolution, "kind": "detail"},
        {"prompt": build_white_comparison_prompt(product_type, category), "reference_url": image_url, "size": size, "resolution": resolution, "kind": "comparison"},
    ]

    return {
        "tasks": main_tasks + extra_tasks,
        "model_image_count": model_image_count,
        "category": category,
        "country_config": country_config,
        "model_code": model_code,
        "model_profile": model_profile,
        "titles": meta_titles,
        "tags": meta_tags,
        "description": meta_desc,
        "target_audience": meta_audience,
    }
