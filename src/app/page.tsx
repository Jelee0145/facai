"use client";

import { useState, useRef, useEffect } from "react";
import { Progress } from "@/components/ui/progress";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { toast } from "@/components/ui/toast";
import { fetchWithRetry } from "@/lib/fetch";
import { CountryPicker } from "@/components/country-picker";
import { ModelPicker } from "@/components/model-picker";
import { useSSE } from "@/lib/use-sse";
import { logger } from "@/lib/logger";
import { Modal } from "@/components/ui/modal";

const proxyImg = (url: string) => `/api/proxy-image?url=${encodeURIComponent(url)}`;

// AI模型列表
const MODELS = [
  { 
    code: "general", 
    name: "通用模型", 
    icon: "🎯",
    desc: "综合效果好，适合大多数商品",
    prompt: "high quality, professional photography, commercial ready"
  },
  { 
    code: "portrait", 
    name: "人像增强", 
    icon: "👤",
    desc: "人像效果最佳，肤色自然",
    prompt: "beautiful portrait photography, natural skin tone, soft lighting, fashion magazine quality"
  },
  { 
    code: "fashion", 
    name: "时尚专精", 
    icon: "👗",
    desc: "服装类效果专业，质感细腻",
    prompt: "professional fashion photography, fabric texture detail, runway quality, editorial style"
  },
  { 
    code: "product", 
    name: "产品专精", 
    icon: "📱",
    desc: "产品细节突出，清晰锐利",
    prompt: "product photography, crystal clear details, studio lighting, commercial advertising quality"
  },
  { 
    code: "artistic", 
    name: "艺术风格", 
    icon: "🎨",
    desc: "艺术感强，创意无限",
    prompt: "artistic photography, creative composition, dramatic lighting, conceptual art style"
  },
  { 
    code: "viral", 
    name: "病毒式传播", 
    icon: "🔥",
    desc: "TikTok风格，易病毒传播",
    prompt: "viral TikTok content, social media sensation, eye-catching, trending aesthetic"
  },
];

const COUNTRIES = [
  { code: "thailand", name: "泰国", flag: "🇹🇭", currency: "THB", shopUrl: "https://seller.tiktok.com/", platform: "TikTok Shop Thailand" },
  { code: "vietnam", name: "越南", flag: "🇻🇳", currency: "VND", shopUrl: "https://seller.tiktok.com/", platform: "TikTok Shop Vietnam" },
  { code: "malaysia", name: "马来西亚", flag: "🇲🇾", currency: "MYR", shopUrl: "https://seller.tiktok.com/", platform: "TikTok Shop Malaysia" },
  { code: "philippines", name: "菲律宾", flag: "🇵🇭", currency: "PHP", shopUrl: "https://seller.tiktok.com/", platform: "TikTok Shop Philippines" },
  { code: "indonesia", name: "印度尼西亚", flag: "🇮🇩", currency: "IDR", shopUrl: "https://seller.tiktok.com/", platform: "TikTok Shop Indonesia" },
  { code: "japan", name: "日本", flag: "🇯🇵", currency: "JPY", shopUrl: "https://seller.tiktok.com/", platform: "TikTok Shop Japan" },
  { code: "china", name: "中国", flag: "🇨🇳", currency: "CNY", shopUrl: "https://creator.douyin.com/", platform: "抖音电商" },
  { code: "korea", name: "韩国", flag: "🇰🇷", currency: "KRW", shopUrl: "https://seller.tiktok.com/", platform: "TikTok Shop Korea" },
  { code: "usa", name: "美国", flag: "🇺🇸", currency: "USD", shopUrl: "https://seller.tiktok.com/", platform: "TikTok Shop USA" },
];

// 预定义商品类型 - 全品类
const PRODUCT_TYPES = [
  // 服装类
  { code: "top", label: "👕 上装", category: "服装" },
  { code: "dress", label: "👗 连衣裙", category: "服装" },
  { code: "pants", label: "👖 裤子", category: "服装" },
  { code: "skirt", label: "👗 裙子", category: "服装" },
  { code: "jacket", label: "🧥 外套", category: "服装" },
  { code: "shoes", label: "👟 鞋子", category: "服装" },
  { code: "bag", label: "👜 包包", category: "服装" },
  { code: "accessory", label: "⌚ 配饰", category: "服装" },
  { code: "lingerie", label: "🩱 内衣泳装", category: "服装" },
  { code: "hanfu", label: "👘 中式服装", category: "服装" },
  // 家居类
  { code: "lamp", label: "💡 灯具", category: "家居" },
  { code: "furniture", label: "🛋️ 家具", category: "家居" },
  { code: "homedecor", label: "🏠 家居装饰", category: "家居" },
  { code: "textile", label: "🛏️ 家居软装", category: "家居" },
  // 电子类
  { code: "phone", label: "📱 手机平板", category: "电子" },
  { code: "computer", label: "💻 电脑配件", category: "电子" },
  { code: "audio", label: "🎧 耳机音响", category: "电子" },
  { code: "camera", label: "📷 摄影器材", category: "电子" },
  { code: "smart", label: "⌚ 智能设备", category: "电子" },
  // 玩具模型
  { code: "toy", label: "🧸 玩具", category: "玩具" },
  { code: "car", label: "🚗 汽车模型", category: "玩具" },
  { code: "figure", label: "🎭 手办", category: "玩具" },
  // 美食
  { code: "food", label: "🍫 食品零食", category: "美食" },
  { code: "drink", label: "🥤 饮料", category: "美食" },
  // 美妆
  { code: "makeup", label: "💄 化妆品", category: "美妆" },
  { code: "skincare", label: "🧴 护肤品", category: "美妆" },
  // 珠宝
  { code: "jewelry", label: "💎 珠宝首饰", category: "珠宝" },
  { code: "watch", label: "⌚ 手表", category: "珠宝" },
  // 母婴
  { code: "baby", label: "👶 母婴用品", category: "母婴" },
  { code: "kids", label: "👧 儿童用品", category: "母婴" },
  // 运动
  { code: "sportswear", label: "👟 运动服装", category: "运动" },
  { code: "equipment", label: "⚽ 运动器材", category: "运动" },
  // 宠物
  { code: "pet", label: "🐱 宠物用品", category: "宠物" },
  // 其他
  { code: "other", label: "📦 其他商品", category: "其他" },
];

export default function HomePage() {
  const [selectedCountry, setSelectedCountry] = useState<string>("thailand");
  const [selectedModel, setSelectedModel] = useState<string>("general");
  const [selectedProduct, setSelectedProduct] = useState<string>("top");
  const [description, setDescription] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [selectedCategory, setSelectedCategory] = useState<string>("服装");
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [showSuccess, setShowSuccess] = useState<boolean>(false);

  // 爆款标题相关（一次性生成）
  const [generatedTitles, setGeneratedTitles] = useState<string[]>([]);
  const [generatedTags, setGeneratedTags] = useState<string[]>([]);
  const [applicableCrowd, setApplicableCrowd] = useState<string>("");
  const [showTrending, setShowTrending] = useState<boolean>(false);

  // 上传图片相关
  const [uploadedImage, setUploadedImage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 自定义类型相关
  const [customTypes, setCustomTypes] = useState<Array<{ code: string; label: string; category: string }>>([]);
  const [showCustomTypeModal, setShowCustomTypeModal] = useState<boolean>(false);
  const [newCustomTypeName, setNewCustomTypeName] = useState<string>("");
  const [newCustomTypeCategory, setNewCustomTypeCategory] = useState<string>("");
  const [editingCustomTypes, setEditingCustomTypes] = useState<boolean>(false);

  // 获取实际发送给后端的 product_type
  const getEffectiveProductType = () => {
    if (description) return description;
    const customProduct = customTypes.find((p) => p.code === selectedProduct);
    return customProduct ? customProduct.label : selectedProduct;
  };

  // 爆款标题相关
  const [copiedTitleIndex, setCopiedTitleIndex] = useState<number | null>(null);

  // 生成结果
  const [generatedImages, setGeneratedImages] = useState<string[]>([]);

  // 对比图和细节图
  const [comparisonImage, setComparisonImage] = useState<string | null>(null);
  const [detailImage, setDetailImage] = useState<string | null>(null);

  // 测试模式
  const [isTesting, setIsTesting] = useState<boolean>(false);
  const [testImage, setTestImage] = useState<string | null>(null);
  const [testStyleName, setTestStyleName] = useState<string>("");
  const [testTitles, setTestTitles] = useState<string[]>([]);
  const [testTags, setTestTags] = useState<string[]>([]);

  // 点击放大
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

  // 进度追踪
  const [progressPercent, setProgressPercent] = useState(0);
  const [completedCount, setCompletedCount] = useState(0);
  const [totalCount, setTotalCount] = useState(14);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [generationStatus, setGenerationStatus] = useState<string>("idle");
  const [latestImage, setLatestImage] = useState<string | null>(null);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/custom-types")
      .then((r) => r.json())
      .then((data) => {
        if (data.types) {
          setCustomTypes(
            data.types.map((t: { id: number; label: string; category: string }) => ({
              code: `db_${t.id}`,
              label: t.label,
              category: t.category,
            }))
          );
        }
      })
      .catch((e) => logger.error("Failed to load custom types:", e));
  }, []);

  useSSE(currentTaskId, {
    onProgress: (data: unknown) => {
      const d = data as Record<string, unknown>;
      const completed = typeof d.completed === "number" ? d.completed : 0;
      const total = typeof d.total === "number" ? d.total : 14;
      setCompletedCount(completed);
      setProgressPercent(Math.round((completed / total) * 100));
      const images = Array.isArray(d.images) ? d.images as Array<Record<string, unknown>> : null;
      if (images) {
        const lastCompleted = images.findLast(
          (img) => img.status === "completed" && img.url
        );
        if (lastCompleted) {
          setLatestImage(String(lastCompleted.url));
        }
      }
    },
    onComplete: (data: unknown) => {
      const d = data as Record<string, unknown>;
      const result = d.result as Record<string, unknown> | undefined;
      const r = result?.data as Record<string, unknown> | undefined;
      if (r) {
        if (Array.isArray(r.modelImages)) setGeneratedImages(r.modelImages as string[]);
        if (Array.isArray(r.titles)) setGeneratedTitles(r.titles as string[]);
        if (Array.isArray(r.tags)) setGeneratedTags(r.tags as string[]);
        if (typeof r.targetAudience === "string") setApplicableCrowd(r.targetAudience);
        setShowTrending(true);
        if (typeof r.comparisonImage === "string") setComparisonImage(r.comparisonImage);
        if (typeof r.detailImage === "string") setDetailImage(r.detailImage);
      }
      setGenerationStatus("completed");
      setProgressPercent(100);
      setIsLoading(false);
      setCurrentTaskId(null);
    },
    onError: (error: string) => {
      setGenerationStatus("error");
      setIsLoading(false);
      setCurrentTaskId(null);
      toast.error("生成失败: " + error);
    },
  });

  const filteredProducts = [...PRODUCT_TYPES, ...customTypes].filter(
    (p) => p.category === selectedCategory
  );

  const currentCountry = COUNTRIES.find((c) => c.code === selectedCountry);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // 预览图片
    const reader = new FileReader();
    reader.onload = (event) => {
      setUploadedImage(event.target?.result as string);
    };
    reader.readAsDataURL(file);
  };

  const handleRemoveImage = () => {
    setUploadedImage(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleGenerate = async () => {
    if (!uploadedImage) {
      toast.warning("请先上传商品图片");
      return;
    }

    // 清空旧结果并初始化进度
    setGeneratedImages([]);
    setGeneratedTitles([]);
    setGeneratedTags([]);
    setComparisonImage(null);
    setDetailImage(null);
    setTestImage(null);
    setTestStyleName("");
    setTestTitles([]);
    setTestTags([]);
    setProgressPercent(0);
    setCompletedCount(0);
    setTotalCount(14);
    setElapsedSeconds(0);
    setLatestImage(null);
    setGenerationStatus("submitting");
    setIsLoading(true);

    try {
      // 1. 提交异步任务
      const startRes = await fetchWithRetry("/api/generate/async", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_url: uploadedImage,
          product_type: getEffectiveProductType(),
          country: selectedCountry,
          model: selectedModel,
        }),
      });

      if (!startRes.ok) {
        throw new Error("启动生成失败");
      }

      const { task_id } = await startRes.json();
      setGenerationStatus("generating");
      setCurrentTaskId(task_id);
    } catch (error) {
      logger.error("生成失败:", error);
      toast.error("生成失败，请重试");
      setGenerationStatus("error");
      setIsLoading(false);
    }
  };

  const handleQuickTest = async () => {
    if (!uploadedImage) {
      toast.warning("请先上传商品图片");
      return;
    }

    setTestImage(null);
    setTestStyleName("");
    setTestTitles([]);
    setTestTags([]);
    setIsTesting(true);

    try {
      const res = await fetchWithRetry("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_url: uploadedImage,
          product_type: getEffectiveProductType(),
          country: selectedCountry,
          model: selectedModel,
          generate_type: "test",
        }),
      });

      const data = await res.json();
      if (res.ok && data.success && data.data?.modelImages?.length > 0) {
        setTestImage(data.data.modelImages[0]);
        setTestStyleName(data.data.modelStyles?.[0] || "测试风格");
        if (data.data.titles) setTestTitles(data.data.titles);
        if (data.data.tags) setTestTags(data.data.tags);
      } else {
        alert("测试生成失败: " + (data.error || "未知错误"));
      }
    } catch (error) {
      logger.error("测试失败:", error);
      alert("测试生成失败，请重试");
    } finally {
      setIsTesting(false);
    }
  };

  const handleSingleImageTest = async (styleIndex: number) => {
    if (!uploadedImage) return;

    setGeneratedImages((prev) => {
      const next = [...prev];
      next[styleIndex] = "";
      return next;
    });
    setIsLoading(true);

    try {
      const res = await fetchWithRetry("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_url: uploadedImage,
          product_type: getEffectiveProductType(),
          country: selectedCountry,
          model: selectedModel,
          generate_type: "test",
          style_index: styleIndex,
        }),
      });

      const data = await res.json();
      if (res.ok && data.success && data.data?.modelImages?.length > 0) {
        setGeneratedImages((prev) => {
          const next = [...prev];
          next[styleIndex] = data.data.modelImages[0];
          return next;
        });
      } else {
        alert(`单图生成失败: ${data.error || "未知错误"}`);
      }
    } catch (error) {
      logger.error("单图生成失败:", error);
      alert("单图生成失败，请重试");
    } finally {
      setIsLoading(false);
    }
  };

  const handleAddCustomType = async () => {
    if (!newCustomTypeName.trim()) {
      alert("请输入自定义类型名称");
      return;
    }

    const category = newCustomTypeCategory.trim() || "自定义";

    try {
      const res = await fetchWithRetry("/api/custom-types", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: newCustomTypeName.trim(), category }),
      });
      if (!res.ok) throw new Error("保存失败");
      const data = await res.json();

      const newType = {
        code: `db_${data.id}`,
        label: data.label,
        category: data.category,
      };

      setCustomTypes([...customTypes, newType]);

      // 如果当前分类不是新增类型的分类，切换过去
      if (selectedCategory !== category) {
        setSelectedCategory(category);
      }
      setSelectedProduct(newType.code);
    } catch (e) {
      logger.error("添加自定义类型失败:", e);
      alert("添加失败，请检查后端服务是否运行");
      return;
    }

    setNewCustomTypeName("");
    setNewCustomTypeCategory("");
    setShowCustomTypeModal(false);
  };

  const handleDeleteCustomType = async (code: string) => {
    const idMatch = code.match(/^db_(\d+)$/);
    if (!idMatch) return;

    try {
      const res = await fetchWithRetry(`/api/custom-types?id=${idMatch[1]}`, { method: "DELETE" });
      if (!res.ok) throw new Error("删除失败");
    } catch (e) {
      logger.error("删除自定义类型失败:", e);
      return;
    }

    setCustomTypes(customTypes.filter((t) => t.code !== code));
    if (selectedProduct === code) {
      setSelectedProduct(PRODUCT_TYPES[0].code);
    }
  };

  const copyToClipboard = async (text: string, index: number) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      setCopiedTitleIndex(index);
      setShowSuccess(true);
      setTimeout(() => {
        setCopiedIndex(null);
        setCopiedTitleIndex(null);
        setShowSuccess(false);
      }, 2000);
    } catch (err) {
      logger.error("复制失败:", err);
    }
  };

  const downloadImage = (imageUrl: string, filename: string) => {
    const link = document.createElement('a');
    link.href = proxyImg(imageUrl);
    link.download = filename;
    link.click();
  };

  const copyImageToClipboard = async (imageUrl: string, index: number) => {
    try {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.src = proxyImg(imageUrl);
      
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
      });
      
      // 绘制到canvas并转换为PNG blob
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('无法获取canvas上下文');
      ctx.drawImage(img, 0, 0);
      
      canvas.toBlob(async (blob) => {
        if (!blob) {
          logger.error("无法创建图片blob");
          downloadImage(imageUrl, `product_${index + 1}.png`);
          return;
        }
        
        try {
          // 转换为PNG格式后复制到剪贴板
          const pngBlob = new Blob([blob], { type: 'image/png' });
          await navigator.clipboard.write([
            new ClipboardItem({
              'image/png': pngBlob,
            }),
          ]);
          setCopiedIndex(index);
          setTimeout(() => setCopiedIndex(null), 2000);
        } catch (err) {
          logger.error("复制失败，改为下载:", err);
          downloadImage(imageUrl, `product_${index + 1}.png`);
          setCopiedIndex(index);
          setTimeout(() => setCopiedIndex(null), 2000);
        }
      }, 'image/png');
      
    } catch (err) {
      logger.error("复制图片失败:", err);
      downloadImage(imageUrl, `product_${index + 1}.png`);
    }
  };

  const categories = [...new Set([...PRODUCT_TYPES, ...customTypes].map((p) => p.category))];

  return (
    <ErrorBoundary>
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
      {/* 头部 */}
      <header className="border-b border-white/20 bg-white/5 backdrop-blur-lg sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-4xl">💰</span>
              <div>
                <h1 className="text-2xl font-bold text-white">发财计划</h1>
                <p className="text-sm text-purple-300">TikTok Shop 跨境电商 AI 作图工具</p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <span className="text-sm text-purple-300">九国市场</span>
              <a
                href={currentCountry?.shopUrl || "https://seller.tiktok.com/"}
                className="px-4 py-2 bg-gradient-to-r from-purple-500 to-pink-500 text-white rounded-lg font-medium hover:opacity-90 transition-opacity"
              >
                前往卖家后台
              </a>
            </div>
          </div>
        </div>
      </header>

      {/* 主内容 */}
      <main className="max-w-7xl mx-auto px-4 py-8">
        {/* 市场选择 */}
        <CountryPicker countries={COUNTRIES} selected={selectedCountry} onSelect={setSelectedCountry} />

        {/* AI模型选择 */}
        <ModelPicker models={MODELS} selected={selectedModel} onSelect={setSelectedModel} />

        {/* 商品类型选择 */}
        <section className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <span>📦</span> 选择商品类型
            </h2>
            <div className="flex items-center gap-2">
              {editingCustomTypes ? (
                <button
                  onClick={() => setEditingCustomTypes(false)}
                  className="px-4 py-2 bg-blue-500/80 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition-all"
                >
                  完成
                </button>
              ) : (
                <>
                  <button
                    onClick={() => setShowCustomTypeModal(true)}
                    className="px-4 py-2 bg-green-500/80 hover:bg-green-500 text-white rounded-lg text-sm font-medium transition-all flex items-center gap-2"
                  >
                    <span>+</span> 添加自定义类型
                  </button>
                  {customTypes.length > 0 && (
                    <button
                      onClick={() => setEditingCustomTypes(true)}
                      className="px-4 py-2 bg-orange-500/80 hover:bg-orange-500 text-white rounded-lg text-sm font-medium transition-all"
                    >
                      管理
                    </button>
                  )}
                </>
              )}
            </div>
          </div>

          {/* 分类标签 */}
          <div className="flex flex-wrap gap-2 mb-4">
            {categories.map((category) => (
              <button
                key={category}
                onClick={() => {
                  setSelectedCategory(category);
                  const firstInCategory = [...PRODUCT_TYPES, ...customTypes].find(
                    (p) => p.category === category
                  );
                  if (firstInCategory) {
                    setSelectedProduct(firstInCategory.code);
                  }
                }}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  selectedCategory === category
                    ? "bg-pink-500 text-white"
                    : "bg-white/10 text-white/80 hover:bg-white/20"
                }`}
              >
                {category}
              </button>
            ))}
          </div>

          {/* 商品选项 */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
            {filteredProducts.map((product) => (
              <div key={product.code} className="relative">
                <button
                  onClick={() => setSelectedProduct(product.code)}
                  className={`w-full p-4 rounded-xl text-left transition-all ${
                    selectedProduct === product.code
                      ? "bg-gradient-to-br from-pink-500 to-purple-500 text-white shadow-lg shadow-pink-500/30"
                      : "bg-white/10 text-white/80 hover:bg-white/20"
                  }`}
                >
                  <div className="text-lg font-medium">{product.label}</div>
                </button>
                {product.code.startsWith("db_") && editingCustomTypes && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteCustomType(product.code);
                    }}
                    className="absolute -top-2 -right-2 w-6 h-6 bg-red-500 hover:bg-red-600 text-white rounded-full text-xs font-bold flex items-center justify-center"
                    title="删除自定义类型"
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* 商品描述（可选） */}
        <section className="mb-8">
          <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
            <span>✍️</span> 商品描述（可选）
          </h2>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="描述你的商品特点，如：2024新款、显瘦、百搭、透气...（不填则AI自动识别）"
            className="w-full h-32 p-4 bg-white/10 border border-white/20 rounded-xl text-white placeholder-white/50 focus:outline-none focus:border-purple-500 resize-none"
          />
          <p className="text-white/60 text-sm mt-2">💡 不填写时，AI会自动根据图片识别产品类型并生成</p>
        </section>

        {/* 上传参考图 */}
        <section className="mb-8">
          <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
            <span>🖼️</span> 上传参考图（可选）
          </h2>
          <div className="border-2 border-dashed border-white/20 rounded-xl p-6 text-center bg-white/5">
            {uploadedImage ? (
              <div className="relative inline-block">
                <img
                  src={uploadedImage}
                  alt="参考图预览"
                  className="max-h-48 rounded-lg mx-auto"
                  loading="lazy"
                  decoding="async"
                />
                <button
                  onClick={handleRemoveImage}
                  className="absolute -top-2 -right-2 w-8 h-8 bg-red-500 hover:bg-red-600 text-white rounded-full flex items-center justify-center"
                >
                  ×
                </button>
                <p className="text-white/60 text-sm mt-2">已上传参考图，将用于图生图</p>
              </div>
            ) : (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleFileUpload}
                  className="hidden"
                  id="file-upload"
                />
                <label
                  htmlFor="file-upload"
                  className="cursor-pointer flex flex-col items-center"
                >
                  <div className="text-4xl mb-2">📤</div>
                  <p className="text-white/80">点击上传图片</p>
                  <p className="text-white/50 text-sm mt-1">支持 JPG、PNG 格式</p>
                </label>
              </>
            )}
          </div>
        </section>

        {/* 快速测试 */}
        <section className="mb-6">
          <div className="flex gap-3 items-stretch">
            <button
              onClick={handleQuickTest}
              disabled={isTesting || isLoading}
              className={`flex-1 py-4 rounded-xl font-bold text-lg transition-all ${
                isTesting
                  ? "bg-gray-500 cursor-not-allowed"
                  : "bg-cyan-600 hover:bg-cyan-500 hover:shadow-lg hover:shadow-cyan-500/40"
              } text-white`}
            >
              {isTesting ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="animate-spin inline-block">⚡</span> 测试中...
                </span>
              ) : (
                "⚡ 快速测试（仅1张）"
              )}
            </button>
          </div>
          {testImage && (
            <div className="mt-4 flex items-center gap-4">
              <span className="text-cyan-300 text-sm font-medium">🧪 测试结果 — {testStyleName}</span>
              <div
                className="w-24 h-24 rounded-lg overflow-hidden cursor-pointer ring-2 ring-cyan-500/50 hover:ring-cyan-400 transition-all flex-shrink-0"
                onClick={() => setLightboxUrl(testImage)}
              >
                <img
                  src={proxyImg(testImage)}
                  alt="测试生成"
                  className="w-full h-full object-cover hover:scale-105 transition-transform duration-300"
                  loading="lazy"
                  decoding="async"
                />
              </div>
              <span className="text-white/40 text-xs cursor-pointer hover:text-white/70 transition-colors" onClick={() => setLightboxUrl(testImage)}>
                点击放大
              </span>
            </div>
          )}
          {testTitles.length > 0 && (
            <div className="mt-4 bg-white/5 rounded-xl p-4 border border-white/10">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-yellow-400 text-sm">🔥</span>
                <span className="text-white text-sm font-medium">爆款标题</span>
              </div>
              <div className="space-y-1.5 mb-3">
                {testTitles.map((t, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm text-white/80">
                    <span className="text-white/40">{i + 1}.</span>
                    <span>{t}</span>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-pink-400 text-sm">🏷️</span>
                <span className="text-white text-sm font-medium">爆款标签</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {testTags.map((t, i) => (
                  <span key={i} className="px-2.5 py-1 bg-pink-600/40 text-white/90 text-xs rounded-full">#{t}</span>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* 一键生成按钮 */}
        <section className="mb-8">
          <button
            onClick={handleGenerate}
            disabled={isLoading}
            className={`w-full py-5 rounded-xl font-bold text-xl transition-all ${
              isLoading
                ? "bg-gray-500 cursor-not-allowed"
                : "bg-gradient-to-r from-purple-500 via-pink-500 to-red-500 hover:shadow-lg hover:shadow-purple-500/50 animate-pulse"
            } text-white`}
          >
            {isLoading ? (
              <div className="w-full space-y-4">
                {/* 进度条 */}
                <div className="space-y-2">
                  <div className="flex justify-between text-sm text-white/80">
                    <span>
                      {generationStatus === "submitting" ? "正在提交任务..." : "AI 正在生成图片..."}
                    </span>
                    <span>{completedCount}/{totalCount} 张</span>
                  </div>
                  <Progress value={progressPercent} className="h-3 bg-white/20 [&>div]:bg-gradient-to-r [&>div]:from-purple-400 [&>div]:via-pink-400 [&>div]:to-red-400" />
                </div>
                {/* 计时器 */}
                <div className="flex items-center justify-center gap-6 text-sm text-white/70">
                  <span className="flex items-center gap-1">
                    <span className="animate-spin inline-block">⏱</span>
                    {elapsedSeconds}秒
                  </span>
                  <span>{progressPercent}%</span>
                </div>
                {/* 最新完成的图片缩略图 */}
                {latestImage && (
                  <div className="flex justify-center">
                    <div className="relative w-16 h-16 rounded-lg overflow-hidden border-2 border-purple-400/50 animate-in fade-in zoom-in">
                      <img
                        src={proxyImg(latestImage)}
                        alt="最新生成"
                        className="w-full h-full object-cover"
                        loading="lazy"
                        decoding="async"
                      />
                      <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent flex items-end justify-center">
                        <span className="text-[8px] text-white pb-0.5">完成!</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              "🚀 一键生成：11张图 + 爆款标题 + 热门标签"
            )}
          </button>
          <p className="text-center text-white/60 text-sm mt-3">
            系统将根据商品类型自动匹配风格和拍摄角度，生成多样化电商主图
          </p>
        </section>

        {/* 生成结果 */}
        {generatedImages.length > 0 && (
          <section className="mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <span>✨</span> 生成的图片（含模特展示）
              </h2>
              <span className="text-white/50 text-sm">{generatedImages.length} 张</span>
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-3">
              {generatedImages.map((imgUrl, index) => (
                <div
                  key={index}
                  className="bg-white/10 rounded-lg overflow-hidden group relative cursor-pointer"
                  onClick={() => setLightboxUrl(imgUrl)}
                >
                  <img
                    src={proxyImg(imgUrl)}
                    alt={`生成的图片 ${index + 1}`}
                    className="w-full aspect-square object-cover group-hover:scale-105 transition-transform duration-300"
                    loading="lazy"
                    decoding="async"
                  />
                  {/* 风格编号 */}
                  <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent p-1.5">
                    <span className="text-white text-[10px] leading-none">风格 {index + 1}</span>
                  </div>
                  {/* 复制按钮 */}
                  <div className="absolute top-1 right-1 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => { e.stopPropagation(); copyImageToClipboard(imgUrl, index); }}
                      className="p-1.5 bg-black/60 hover:bg-black/80 backdrop-blur-sm rounded-md text-white text-xs transition-all"
                      title="复制图片"
                    >
                      {copiedIndex === index ? "✓" : "📷"}
                    </button>
                  </div>
                  {/* 单图测试按钮 */}
                  <div className="absolute top-1 left-1 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleSingleImageTest(index); }}
                      disabled={isLoading || !imgUrl}
                      className="p-1.5 bg-orange-500/70 hover:bg-orange-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-md text-white text-xs transition-all"
                      title="单图测试"
                    >
                      🔬
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* ========== 完整的爆款标题和标签列表 ========== */}
            {generatedTitles.length > 0 && (
              <div className="mt-8 bg-white/5 rounded-xl p-6 border border-white/10">
                <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                  <span>📋</span> 爆款标题和标签完整列表
                </h2>

                {/* 适用人群 */}
                {applicableCrowd && (
                  <div className="mb-6 p-4 bg-gradient-to-r from-green-500/20 to-blue-500/20 rounded-lg border border-green-500/30">
                    <h3 className="text-white font-medium mb-2 flex items-center gap-2">
                      <span>👥</span> 适用人群
                    </h3>
                    <p className="text-green-300 text-lg font-medium">{applicableCrowd}</p>
                  </div>
                )}

                {/* 爆款标题列表 */}
                <div className="mb-6">
                  <h3 className="text-white font-medium mb-3 flex items-center gap-2">
                    <span>🔥</span> 爆款标题
                  </h3>
                  <div className="space-y-2">
                    {generatedTitles.map((title, index) => (
                      <div
                        key={index}
                        className="flex items-center gap-3 p-3 bg-slate-700/50 rounded-lg hover:bg-slate-700 transition-colors"
                      >
                        <span className="text-white/50 text-sm font-medium min-w-[24px]">#{index + 1}</span>
                        <span className="flex-1 text-white text-sm">{title}</span>
                        <button
                          onClick={() => copyToClipboard(title, index)}
                          className="px-3 py-1.5 bg-purple-500/70 hover:bg-purple-500 text-white text-xs rounded-lg transition-all flex items-center gap-1"
                        >
                          {copiedTitleIndex === index ? "✓ 已复制" : "📋 复制"}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                {/* 爆款标签列表 */}
                <div>
                  <h3 className="text-white font-medium mb-3 flex items-center gap-2">
                    <span>🏷️</span> 爆款标签
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {generatedTags.map((tag, index) => (
                      <button
                        key={index}
                        onClick={() => copyToClipboard(`#${tag}`, index + 10)}
                        className={`group relative px-4 py-2 rounded-full text-sm font-medium transition-all ${
                          copiedTitleIndex === index + 10
                            ? "bg-green-500/80 text-white"
                            : "bg-gradient-to-r from-pink-600/60 to-purple-600/60 hover:from-pink-500 hover:to-purple-500 text-white shadow-lg shadow-pink-500/20"
                        }`}
                      >
                        <span className="font-bold text-amber-300">#</span>
                        <span>{tag}</span>
                        <span className={`ml-2 text-xs ${copiedTitleIndex === index + 10 ? "text-green-200" : "text-white/40 group-hover:text-white/70"}`}>
                          {copiedTitleIndex === index + 10 ? "✓" : "📋"}
                        </span>
                      </button>
                    ))}
                  </div>
                  <p className="text-white/50 text-xs mt-3">
                    💡 点击标签即可复制（包含 # 符号）
                  </p>
                </div>
              </div>
            )}

            {/* 对比图 */}
            {comparisonImage && (
              <div className="mt-8">
                <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                  <span>🔄</span> 产品对比图
                </h2>
                <div className="bg-white/10 rounded-xl overflow-hidden max-w-md">
                  <img
                    src={proxyImg(comparisonImage)}
                    alt="产品对比图"
                    className="w-full"
                    loading="lazy"
                    decoding="async"
                  />
                  <div className="p-4 flex gap-2">
                    <button
                      onClick={() => copyImageToClipboard(comparisonImage, 100)}
                      className="flex-1 py-2 bg-purple-500/80 hover:bg-purple-500 rounded-lg text-white text-sm transition-all"
                    >
                      📋 复制图片
                    </button>
                    <a
                      href={proxyImg(comparisonImage)}
                      download="product_comparison.png"
                      className="flex-1 py-2 bg-white/20 hover:bg-white/30 rounded-lg text-white text-sm text-center transition-all"
                    >
                      ⬇️ 下载
                    </a>
                  </div>
                </div>
              </div>
            )}

            {/* 细节放大图 */}
            {detailImage && (
              <div className="mt-8">
                <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                  <span>🔍</span> 细节放大图
                </h2>
                <div className="bg-white/10 rounded-xl overflow-hidden max-w-md">
                  <img
                    src={proxyImg(detailImage)}
                    alt="细节放大图"
                    className="w-full"
                    loading="lazy"
                    decoding="async"
                  />
                  <div className="p-4 flex gap-2">
                    <button
                      onClick={() => copyImageToClipboard(detailImage, 101)}
                      className="flex-1 py-2 bg-purple-500/80 hover:bg-purple-500 rounded-lg text-white text-sm transition-all"
                    >
                      📋 复制图片
                    </button>
                    <a
                      href={proxyImg(detailImage)}
                      download="product_detail.png"
                      className="flex-1 py-2 bg-white/20 hover:bg-white/30 rounded-lg text-white text-sm text-center transition-all"
                    >
                      ⬇️ 下载
                    </a>
                  </div>
                </div>
              </div>
            )}
          </section>
        )}
      </main>

      {/* 自定义类型弹窗 */}
      <Modal open={showCustomTypeModal} title="添加自定义类型" onClose={() => setShowCustomTypeModal(false)} containerClassName="w-full max-w-md">
        <div className="space-y-4">
          <div>
            <label className="block text-white/80 text-sm mb-2">类型名称</label>
            <input
              type="text"
              value={newCustomTypeName}
              onChange={(e) => setNewCustomTypeName(e.target.value)}
              placeholder="如：瑜伽垫、运动水壶"
              className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:border-purple-500"
            />
          </div>
          <div>
            <label className="block text-white/80 text-sm mb-2">所属分类（可选）</label>
            <input
              type="text"
              value={newCustomTypeCategory}
              onChange={(e) => setNewCustomTypeCategory(e.target.value)}
              placeholder="如：运动、户外（新分类会自动创建）"
              className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:border-purple-500"
            />
          </div>
        </div>
        <div className="flex gap-3 mt-6">
          <button
            onClick={() => setShowCustomTypeModal(false)}
            className="flex-1 py-3 bg-white/10 hover:bg-white/20 text-white rounded-lg font-medium transition-all"
          >
            取消
          </button>
          <button
            onClick={handleAddCustomType}
            className="flex-1 py-3 bg-gradient-to-r from-green-500 to-emerald-500 hover:opacity-90 text-white rounded-lg font-medium transition-all"
          >
            添加
          </button>
        </div>
      </Modal>

      {/* 爆款标题弹窗 */}
      <Modal open={showTrending} onClose={() => setShowTrending(false)} containerClassName="w-full max-w-2xl" noHeader>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xl font-bold text-white">
            📝 {currentCountry?.name}市场爆款标题
          </h3>
          <button
            onClick={() => setShowTrending(false)}
            className="text-white/60 hover:text-white text-2xl"
          >
            ×
          </button>
        </div>

        <div className="mb-6">
          <h4 className="text-white font-medium mb-3">🔥 爆款标题</h4>
          <div className="space-y-2">
            {generatedTitles.map((title, index) => (
              <div
                key={index}
                className="flex items-center gap-2 p-3 bg-white/5 rounded-lg"
              >
                <span className="text-white/60 text-sm">{index + 1}.</span>
                <span className="flex-1 text-white">{title}</span>
                <button
                  onClick={() => copyToClipboard(title, index)}
                  className="px-3 py-1 bg-purple-500/50 hover:bg-purple-500 text-white text-sm rounded transition-all"
                >
                  {copiedTitleIndex === index ? "已复制" : "复制"}
                </button>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h4 className="text-white font-medium mb-3">🏷️ 爆款标签</h4>
          <div className="flex flex-wrap gap-2">
            {generatedTags.map((tag, index) => (
              <button
                key={index}
                onClick={() => copyToClipboard(`#${tag}`, index + 10)}
                className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${
                  copiedTitleIndex === index + 10
                    ? "bg-green-500 text-white"
                    : "bg-gradient-to-r from-pink-600/60 to-purple-600/60 hover:from-pink-500 hover:to-purple-500 text-white shadow-lg shadow-pink-500/20"
                }`}
              >
                <span className="font-bold text-amber-300">#</span>
                {tag}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={() => setShowTrending(false)}
          className="w-full mt-6 py-3 bg-white/10 hover:bg-white/20 text-white rounded-lg font-medium transition-all"
        >
          关闭
        </button>
      </Modal>

      {/* 成功提示 */}
      {showSuccess && (
        <div className="fixed top-20 left-1/2 -translate-x-1/2 px-6 py-3 bg-green-500 text-white rounded-lg shadow-lg animate-bounce">
          复制成功
        </div>
      )}

      {/* 图片放大查看 */}
      {lightboxUrl && (
        <div
          className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 cursor-pointer"
          onClick={() => setLightboxUrl(null)}
        >
          <button
            onClick={() => setLightboxUrl(null)}
            className="absolute top-4 right-4 text-white/80 hover:text-white text-3xl z-10"
          >
            ×
          </button>
          <img
            src={proxyImg(lightboxUrl)}
            alt="放大查看"
            className="max-w-full max-h-full object-contain rounded-lg cursor-default"
            onClick={(e) => e.stopPropagation()}
            loading="lazy"
            decoding="async"
          />
        </div>
      )}

      {/* 页脚 */}
      <footer className="border-t border-white/20 bg-white/5 py-6 mt-12">
        <div className="max-w-7xl mx-auto px-4 text-center text-white/60">
          <p>发财计划 - 让跨境电商更简单</p>
          <p className="text-sm mt-2">支持泰国、越南、马来西亚、菲律宾、印尼、日本、韩国、美国、中国九大市场</p>
        </div>
      </footer>
    </div>
    </ErrorBoundary>
  );
}
