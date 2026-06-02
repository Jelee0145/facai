"use client";

import { useState, useRef, useEffect } from "react";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { toast } from "@/components/ui/toast";
import { fetchWithRetry } from "@/lib/fetch";
import { CountryPicker } from "@/components/country-picker";
import { ModelPicker } from "@/components/model-picker";
import { useSSE } from "@/lib/use-sse";
import { logger } from "@/lib/logger";
import { Modal } from "@/components/ui/modal";

const proxyImg = (url: string) => `/api/proxy-image?url=${encodeURIComponent(url)}`;

const isNonEmptyImageUrl = (value: unknown): value is string =>
  typeof value === "string" && value.trim().length > 0;

const normalizeImageSlots = (value: unknown): string[] =>
  Array.isArray(value) ? value.map((item) => (isNonEmptyImageUrl(item) ? item : "")) : [];

const normalizeImageUrls = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter(isNonEmptyImageUrl) : [];

const normalizeTags = (value: unknown): string[] => {
  const candidates = typeof value === "string" ? [value] : Array.isArray(value) ? value : [];
  const seen = new Set<string>();
  const tags: string[] = [];

  for (const candidate of candidates) {
    if (typeof candidate !== "string") continue;
    for (const rawPart of candidate.split(/[\s,，、;；]+/)) {
      const part = rawPart.trim();
      if (!part) continue;
      const tag = part.startsWith("#") ? part : `#${part.replace(/^#+/, "")}`;
      if (!seen.has(tag)) {
        seen.add(tag);
        tags.push(tag);
      }
    }
  }

  return tags;
};

interface UserProfile {
  id: number;
  username: string;
  phone?: string;
  email?: string;
}

interface Wallet {
  balance: number;
  total_recharged?: number;
  total_spent?: number;
}

interface CreditPackage {
  id: number;
  name: string;
  price_fen: number;
  points: number;
  bonus_points: number;
}

interface UserHistoryItem {
  id: number;
  created_at: string;
  product_type: string;
  description_snapshot: string;
  preview_images: string[];
  charge_points: number;
  status: string;
}

interface HistoryDetailItem {
  id: number;
  created_at: string;
  product_type: string;
  description_snapshot: string;
  preview_images: string[];
  all_images_json: string[];
  titles_json: string[];
  tags_json: string[];
  target_audience: string;
  status: string;
  charge_points: number;
}

interface LedgerItem {
  id: number;
  type: string;
  direction: string;
  points: number;
  balance_after: number;
  order_no?: string;
  amount_fen?: number;
  order_status?: string;
  package_name?: string;
  remark?: string;
  created_at: string;
}

interface Order {
  id: number;
  order_no: string;
  user_id: number;
  package_id: number;
  amount_fen: number;
  points: number;
  status: string;
  payment_remark?: string;
  proof_image?: string;
  submitted_at?: string;
  reject_reason?: string;
  package_name?: string;
  created_at: string;
}

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

const MAIN_IMAGE_COUNT = 9;
const TOTAL_GENERATION_IMAGES = 11;

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
  const [modelImageCount, setModelImageCount] = useState<number>(4);
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
  const [isDraggingUpload, setIsDraggingUpload] = useState<boolean>(false);
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
  const [generatedProductImages, setGeneratedProductImages] = useState<string[]>([]);
  const [generatedModelImageCount, setGeneratedModelImageCount] = useState<number>(4);

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
  const [totalCount, setTotalCount] = useState(TOTAL_GENERATION_IMAGES);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [generationStatus, setGenerationStatus] = useState<string>("idle");
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const [simulatedProgressActive, setSimulatedProgressActive] = useState<boolean>(false);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [csrfToken, setCsrfToken] = useState("");
  const [generationCostPoints, setGenerationCostPoints] = useState(10);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [showAuthModal, setShowAuthModal] = useState(false);
  const [authForm, setAuthForm] = useState({ username: "", password: "", phone: "", email: "" });
  const [authLoading, setAuthLoading] = useState(false);
  const [showHistoryModal, setShowHistoryModal] = useState(false);
  const [historyItems, setHistoryItems] = useState<UserHistoryItem[]>([]);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [detailItem, setDetailItem] = useState<HistoryDetailItem | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [showBillingModal, setShowBillingModal] = useState(false);
  const [packages, setPackages] = useState<CreditPackage[]>([]);
  const [ledgerItems, setLedgerItems] = useState<LedgerItem[]>([]);
  const [billingLoading, setBillingLoading] = useState(false);
  const [userOrders, setUserOrders] = useState<Order[]>([]);
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [payingOrder, setPayingOrder] = useState<Order | null>(null);
  const [paymentRemark, setPaymentRemark] = useState("");
  const [paymentFile, setPaymentFile] = useState<File | null>(null);
  const [paymentSubmitting, setPaymentSubmitting] = useState(false);

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

  useEffect(() => {
    fetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!data) return;
        setUser(data.user);
        setWallet(data.wallet);
        setCsrfToken(data.csrf_token || "");
        if (typeof data.generation_cost_points === "number") {
          setGenerationCostPoints(data.generation_cost_points);
        }
      })
      .catch((e) => logger.error("Failed to load user session:", e));

    fetch("/api/user/packages")
      .then((r) => (r.ok ? r.json() : { packages: [] }))
      .then((data) => setPackages(data.packages || []))
      .catch((e) => logger.error("Failed to load credit packages:", e));
  }, []);

  // 计时器 - 生成期间每秒递增
  useEffect(() => {
    if (generationStatus !== "generating" && generationStatus !== "submitting") return;
    const interval = setInterval(() => setElapsedSeconds((p) => p + 1), 1000);
    return () => clearInterval(interval);
  }, [generationStatus]);

  // 模拟进度 - 每3-5秒递增1-5%，上限90%
  useEffect(() => {
    if (!simulatedProgressActive || generationStatus !== "generating") return;
    let timeoutId: ReturnType<typeof setTimeout>;
    const tick = () => {
      setProgressPercent((prev) => {
        if (prev >= 90) return prev;
        return Math.min(prev + Math.floor(Math.random() * 5) + 1, 90);
      });
      timeoutId = setTimeout(tick, Math.floor(Math.random() * 2000) + 3000);
    };
    timeoutId = setTimeout(tick, 2000);
    return () => clearTimeout(timeoutId);
  }, [simulatedProgressActive, generationStatus]);

  useSSE(currentTaskId, {
    onProgress: (data: unknown) => {
      const d = data as Record<string, unknown>;
      const completed = typeof d.completed === "number" ? d.completed : 0;
      const total = typeof d.total === "number" ? d.total : TOTAL_GENERATION_IMAGES;
      setCompletedCount(completed);
      const realPercent = Math.round((completed / total) * 100);
      setProgressPercent((prev) => Math.max(prev, realPercent));

      // 心跳事件：后端仍在工作，记录日志
      if (d.heartbeat === true) {
        const processingCount = typeof d.processing_count === "number" ? d.processing_count : 0;
        const waitingCount = typeof d.waiting_count === "number" ? d.waiting_count : 0;
        logger.log(`[SSE] Heartbeat: ${processingCount} processing, ${waitingCount} waiting`);
      }
    },
    onComplete: (data: unknown) => {
      const d = data as Record<string, unknown>;
      const result = d.result as Record<string, unknown> | undefined;
      const r = result?.data as Record<string, unknown> | undefined;
      const isPartial = d.partial === true;
      const successCount = typeof d.success_count === "number" ? d.success_count : 0;
      const totalCount = typeof d.total_count === "number" ? d.total_count : TOTAL_GENERATION_IMAGES;

      if (r) {
        const mainImages = normalizeImageSlots(r.mainImages);
        const modelImages = normalizeImageUrls(r.modelImages);
        const productImages = normalizeImageUrls(r.productImages);
        if (mainImages.some(isNonEmptyImageUrl)) {
          setGeneratedImages(mainImages);
        } else if (modelImages.length > 0) {
          setGeneratedImages(modelImages);
        } else {
          setGeneratedImages([]);
          toast.error("生成完成，但没有返回可展示的生成图");
        }
        setGeneratedProductImages(productImages);
        if (typeof r.modelImageCount === "number") setGeneratedModelImageCount(r.modelImageCount);
        else if (modelImages.length > 0) setGeneratedModelImageCount(modelImages.length);
        if (Array.isArray(r.titles)) setGeneratedTitles(r.titles as string[]);
        setGeneratedTags(normalizeTags(r.tags));
        if (typeof r.targetAudience === "string") setApplicableCrowd(r.targetAudience);
        setShowTrending(true);
        if (isNonEmptyImageUrl(r.comparisonImage)) setComparisonImage(r.comparisonImage);
        if (isNonEmptyImageUrl(r.detailImage)) setDetailImage(r.detailImage);
      }

      // 部分完成时显示警告提示
      if (isPartial) {
        toast.warning(
          `部分生成完成：${successCount}/${totalCount} 张图片成功，其余重试可恢复`
        );
      }

      setGenerationStatus("completed");
      setSimulatedProgressActive(false);
      setProgressPercent(100);
      setIsLoading(false);
      setCurrentTaskId(null);
      refreshWallet().catch((e) => logger.error("Failed to refresh wallet:", e));
    },
    onError: (error: string) => {
      setGenerationStatus("error");
      setSimulatedProgressActive(false);
      setIsLoading(false);
      setCurrentTaskId(null);
      toast.error("生成失败: " + error);
    },
  });

  const filteredProducts = [...PRODUCT_TYPES, ...customTypes].filter(
    (p) => p.category === selectedCategory
  );

  const currentCountry = COUNTRIES.find((c) => c.code === selectedCountry);
  const productImageCount = MAIN_IMAGE_COUNT - modelImageCount;
  const sliderProgress = (modelImageCount / MAIN_IMAGE_COUNT) * 100;

  const refreshWallet = async () => {
    const res = await fetch("/api/user/wallet");
    if (!res.ok) return;
    const data = await res.json();
    setWallet(data.wallet);
    if (typeof data.generation_cost_points === "number") {
      setGenerationCostPoints(data.generation_cost_points);
    }
  };

  const handleAuthSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthLoading(true);
    try {
      const endpoint = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
      const body = authMode === "login"
        ? { username: authForm.username, password: authForm.password }
        : authForm;
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail;
        let msg = "登录失败";
        if (Array.isArray(detail)) {
          msg = detail.map((e: Record<string, unknown>) => e.msg || JSON.stringify(e)).join("; ");
        } else if (typeof detail === "string") {
          msg = detail;
        }
        toast.error(msg);
        return;
      }
      setUser(data.user);
      setWallet(data.wallet);
      setCsrfToken(data.csrf_token || "");
      setShowAuthModal(false);
      setAuthForm({ username: "", password: "", phone: "", email: "" });
    } finally {
      setAuthLoading(false);
    }
  };

  const handleLogout = async () => {
    try {
      const currentCsrfToken = await refreshCsrfToken();
      await fetch("/api/auth/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": currentCsrfToken },
      });
    } catch (e) {
      logger.error("Logout request failed:", e);
    }
    setUser(null);
    setWallet(null);
    setCsrfToken("");
  };

  const loadHistory = async () => {
    if (!user) {
      setShowAuthModal(true);
      return;
    }
    const res = await fetch("/api/user/history");
    if (!res.ok) return;
    const data = await res.json();
    setHistoryItems(data.items || []);
    setShowHistoryModal(true);
  };

  const loadHistoryDetail = async (historyId: number) => {
    setDetailLoading(true);
    try {
      const res = await fetch(`/api/user/history/${historyId}`);
      if (!res.ok) {
        toast.error("加载详情失败");
        return;
      }
      const data = await res.json();
      setDetailItem(data.item);
      setShowDetailModal(true);
    } finally {
      setDetailLoading(false);
    }
  };

  const loadBilling = async () => {
    if (!user) {
      setShowAuthModal(true);
      return;
    }
    setBillingLoading(true);
    try {
      const [ledgerRes, packagesRes, ordersRes] = await Promise.all([
        fetch("/api/user/ledger"),
        fetch("/api/user/packages"),
        fetch("/api/user/orders"),
      ]);
      if (ledgerRes.ok) {
        const ledgerData = await ledgerRes.json();
        setLedgerItems(ledgerData.items || []);
      }
      if (packagesRes.ok) {
        const packagesData = await packagesRes.json();
        setPackages(packagesData.packages || []);
      }
      if (ordersRes.ok) {
        const ordersData = await ordersRes.json();
        setUserOrders(ordersData.orders || []);
      }
      setShowBillingModal(true);
    } finally {
      setBillingLoading(false);
    }
  };

  const createRechargeOrder = async (packageId: number) => {
    if (!csrfToken) return;
    try {
      const currentCsrfToken = await refreshCsrfToken();
      const res = await fetch("/api/user/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": currentCsrfToken },
        body: JSON.stringify({ package_id: packageId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast.error(String(data.detail || "创建订单失败"));
        return;
      }
      setPayingOrder(data.order as Order);
      setPaymentRemark("");
      setPaymentFile(null);
      setShowBillingModal(false);
      setShowPaymentModal(true);
      await loadBilling();
    } catch (error) {
      logger.error("Create order failed:", error);
      toast.error("创建订单失败，请重试");
    }
  };

  const submitPaymentProof = async () => {
    if (!payingOrder || !csrfToken) return;
    setPaymentSubmitting(true);
    try {
      const currentCsrfToken = await refreshCsrfToken();
      const formData = new FormData();
      formData.append("payment_remark", paymentRemark);
      if (paymentFile) {
        formData.append("proof_image", paymentFile);
      }
      const res = await fetch(`/api/user/orders/${payingOrder.order_no}/submit-proof`, {
        method: "POST",
        headers: { "X-CSRF-Token": currentCsrfToken },
        body: formData,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        toast.error(String(data.detail || "提交失败"));
        return;
      }
      setPayingOrder(data.order as Order);
      toast.success("凭证已提交，等待管理员审核");
      await loadBilling();
    } catch (error) {
      logger.error("Submit proof failed:", error);
      toast.error("提交失败，请重试");
    } finally {
      setPaymentSubmitting(false);
    }
  };

  const refreshPayingOrder = async () => {
    if (!payingOrder) return;
    try {
      const res = await fetch("/api/user/orders");
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.orders) {
        const updated = data.orders.find((o: Order) => o.order_no === payingOrder.order_no);
        if (updated) {
          setPayingOrder(updated);
        }
      }
    } catch { /* ignore */ }
  };

  const readImageFile = (file: File | null) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast.warning("请选择图片文件");
      return;
    }

    // 预览图片
    const reader = new FileReader();
    reader.onload = (event) => {
      setUploadedImage(event.target?.result as string);
    };
    reader.readAsDataURL(file);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    readImageFile(e.target.files?.[0] || null);
  };

  const handleUploadDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDraggingUpload(false);
    readImageFile(e.dataTransfer.files?.[0] || null);
  };

  const handleUploadPaste = (e: React.ClipboardEvent<HTMLDivElement>) => {
    const file = Array.from(e.clipboardData.files).find((item) => item.type.startsWith("image/"));
    if (!file) return;
    e.preventDefault();
    readImageFile(file);
  };

  const handleRemoveImage = () => {
    setUploadedImage(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const refreshCsrfToken = async (): Promise<string> => {
    try {
      const res = await fetch("/api/auth/me");
      if (res.ok) {
        const data = await res.json();
        const newToken = data.csrf_token || "";
        setCsrfToken(newToken);
        return newToken;
      }
    } catch (e) {
      logger.error("Failed to refresh CSRF token:", e);
    }
    return csrfToken;
  };

  const handleGenerate = async () => {
    if (!user) {
      setAuthMode("login");
      setShowAuthModal(true);
      toast.warning("请先登录");
      return;
    }
    if ((wallet?.balance || 0) < generationCostPoints) {
      loadBilling().catch((e) => logger.error("Failed to load billing:", e));
      toast.warning("积分不足，请先充值");
      return;
    }
    if (!uploadedImage) {
      toast.warning("请先上传商品图片");
      return;
    }

    // 清空旧结果并初始化进度
    setGeneratedImages([]);
    setGeneratedProductImages([]);
    setGeneratedModelImageCount(modelImageCount);
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
    setTotalCount(TOTAL_GENERATION_IMAGES);
    setElapsedSeconds(0);
    setGenerationStatus("submitting");
    setIsLoading(true);

    try {
      // 刷新 CSRF token 确保有效性
      const currentCsrfToken = await refreshCsrfToken();

      // 1. 提交异步任务
      const startRes = await fetchWithRetry("/api/generate/async", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": currentCsrfToken },
        body: JSON.stringify({
          image_url: uploadedImage,
          product_type: getEffectiveProductType(),
          country: selectedCountry,
          model: selectedModel,
          model_image_count: modelImageCount,
        }),
      });

      if (!startRes.ok) {
        const data = await startRes.json().catch(() => ({}));
        throw new Error(String(data.detail || data.error || "启动生成失败"));
      }

      const { task_id } = await startRes.json();
      setGenerationStatus("generating");
      setSimulatedProgressActive(true);
      setCurrentTaskId(task_id);
    } catch (error) {
      logger.warn("生成失败:", error);
      toast.error(error instanceof Error ? error.message : "生成失败，请重试");
      setGenerationStatus("error");
      setIsLoading(false);
    }
  };

  const handleQuickTest = async () => {
    if (!user) {
      setAuthMode("login");
      setShowAuthModal(true);
      toast.warning("请先登录");
      return;
    }
    if ((wallet?.balance || 0) < generationCostPoints) {
      loadBilling().catch((e) => logger.error("Failed to load billing:", e));
      toast.warning("积分不足，请先充值");
      return;
    }
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
      const currentCsrfToken = await refreshCsrfToken();
      const res = await fetchWithRetry("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": currentCsrfToken },
        body: JSON.stringify({
          image_url: uploadedImage,
          product_type: getEffectiveProductType(),
          country: selectedCountry,
          model: selectedModel,
          model_image_count: modelImageCount,
          generate_type: "test",
        }),
      });

      const data = await res.json();
      const testImages = normalizeImageUrls(data.data?.modelImages);
      if (res.ok && data.success && testImages.length > 0) {
        setTestImage(testImages[0]);
        setTestStyleName(data.data.modelStyles?.[0] || "测试风格");
        if (data.data.titles) setTestTitles(data.data.titles);
        setTestTags(normalizeTags(data.data.tags));
        refreshWallet().catch((e) => logger.error("Failed to refresh wallet:", e));
      } else {
        toast.error("测试生成失败: " + (data.detail || data.error || "未知错误"));
        refreshWallet().catch((e) => logger.error("Failed to refresh wallet:", e));
      }
    } catch (error) {
      logger.error("测试失败:", error);
      toast.error("测试生成失败，请重试");
    } finally {
      setIsTesting(false);
    }
  };

  const handleSingleImageTest = async (styleIndex: number) => {
    if (!user) {
      setAuthMode("login");
      setShowAuthModal(true);
      toast.warning("请先登录");
      return;
    }
    if (!uploadedImage) return;

    if ((wallet?.balance || 0) < 2) {
      loadBilling().catch((e) => logger.error("Failed to load billing:", e));
      toast.warning("积分不足，请先充值");
      return;
    }

    setGeneratedImages((prev) => {
      const next = [...prev];
      next[styleIndex] = "";
      return next;
    });
    setIsLoading(true);

    try {
      const currentCsrfToken = await refreshCsrfToken();
      const res = await fetchWithRetry("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": currentCsrfToken },
        body: JSON.stringify({
          image_url: uploadedImage,
          product_type: getEffectiveProductType(),
          country: selectedCountry,
          model: selectedModel,
          model_image_count: generatedModelImageCount,
          generate_type: "test",
          style_index: styleIndex,
          charge_points: 2,
        }),
      });

      const data = await res.json();
      const retryImages = normalizeImageUrls(data.data?.modelImages);
      if (res.ok && data.success && retryImages.length > 0) {
        setGeneratedImages((prev) => {
          const next = [...prev];
          next[styleIndex] = retryImages[0];
          return next;
        });
        refreshWallet().catch((e) => logger.error("Failed to refresh wallet:", e));
      } else {
        toast.error(`单图重试失败: ${data.detail || data.error || "未知错误"}`);
        refreshWallet().catch((e) => logger.error("Failed to refresh wallet:", e));
      }
    } catch (error) {
      logger.error("单图重试失败:", error);
      toast.error("单图重试失败，请重试");
      refreshWallet().catch((e) => logger.error("Failed to refresh wallet:", e));
    } finally {
      setIsLoading(false);
    }
  };

  const handleAddCustomType = async () => {
    if (!newCustomTypeName.trim()) {
      toast.warning("请输入自定义类型名称");
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
      toast.error("添加失败，请检查后端服务是否运行");
      return;
    }

    setNewCustomTypeName("");
    setNewCustomTypeCategory("");
    setShowCustomTypeModal(false);
  };

  const handleDeleteCustomType = async (code: string) => {
    const idMatch = code.match(/^db_(\d+)$/);
    if (!idMatch) return;
    if (!confirm("确定删除此自定义类型？")) return;

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
              {user ? (
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-white/80">{user.username}</span>
                  <button onClick={loadBilling} className="px-3 py-2 bg-white/10 hover:bg-white/15 border border-white/15 text-white rounded-lg transition-colors">
                    {wallet?.balance ?? 0} 积分
                  </button>
                  <button onClick={loadHistory} className="px-3 py-2 bg-white/10 hover:bg-white/15 border border-white/15 text-white rounded-lg transition-colors">
                    历史记录
                  </button>
                  <button onClick={handleLogout} className="px-3 py-2 text-white/70 hover:text-white transition-colors">
                    退出
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => {
                    setAuthMode("login");
                    setShowAuthModal(true);
                  }}
                  className="px-3 py-2 bg-white/10 hover:bg-white/15 border border-white/15 text-white rounded-lg transition-colors"
                >
                  登录 / 注册
                </button>
              )}
              <span className="text-sm text-purple-300">九国市场</span>

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
            <span>🖼️</span> 上传参考图
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
              <div
                tabIndex={0}
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDraggingUpload(true);
                }}
                onDragLeave={() => setIsDraggingUpload(false)}
                onDrop={handleUploadDrop}
                onPaste={handleUploadPaste}
                className={`relative min-h-40 cursor-pointer rounded-xl border border-white/15 px-4 py-5 text-center transition-colors ${
                  isDraggingUpload ? "border-cyan-300 bg-cyan-400/10" : "bg-white/5"
                }`}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleFileUpload}
                  aria-label="上传参考图"
                  className="absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0"
                  id="file-upload"
                />
                <div className="pointer-events-none flex flex-col items-center">
                  <div className="text-4xl mb-2">📤</div>
                  <p className="text-white/80">点击上传图片</p>
                  <p className="text-white/50 text-sm mt-1">支持 JPG、PNG 格式</p>
                  <p className="mt-3 text-xs text-white/45">支持拖拽或粘贴图片</p>
                </div>
              </div>
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
                  <button
                    key={i}
                    onClick={() => copyToClipboard(t, i + 100)}
                    className={`px-2.5 py-1 text-white/90 text-xs rounded-full transition-all ${
                      copiedTitleIndex === i + 100 ? "bg-green-500/80" : "bg-pink-600/40 hover:bg-pink-500/60"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* 模特图数量 */}
        <section className="mb-6">
          <div className="flex flex-col gap-3 rounded-xl border border-white/10 bg-white/5 p-4 sm:flex-row sm:items-center">
            <div className="min-w-32">
              <div className="text-sm font-medium text-white">模特图数量</div>
              <div className="text-xs text-white/55">9张主图内分配</div>
            </div>
            <div className="flex flex-1 items-center gap-4">
              <input
                type="range"
                min={0}
                max={MAIN_IMAGE_COUNT}
                step={1}
                value={modelImageCount}
                disabled={isLoading}
                onChange={(e) => setModelImageCount(Number(e.target.value))}
                aria-label="选择模特图数量"
                className="h-4 min-w-0 flex-1 cursor-pointer appearance-none rounded-full border border-white/35 outline-none transition disabled:cursor-not-allowed disabled:opacity-60 [&::-moz-range-thumb]:h-6 [&::-moz-range-thumb]:w-6 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-white [&::-moz-range-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:h-6 [&::-webkit-slider-thumb]:w-6 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white [&::-webkit-slider-thumb]:bg-blue-500"
                style={{
                  background: `linear-gradient(to right, #2563eb 0%, #2563eb ${sliderProgress}%, #050505 ${sliderProgress}%, #050505 100%)`,
                }}
              />
              <div className="w-32 shrink-0 rounded-lg bg-blue-500 px-3 py-2 text-center text-sm font-semibold text-white">
                已选 {modelImageCount} 张
              </div>
            </div>
            <div className="text-xs text-white/55 sm:w-28 sm:text-right">
              商品图 {productImageCount} 张
            </div>
          </div>
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
              <div className="w-full px-6 space-y-4">
                {/* 进度条 */}
                <div className="space-y-2">
                  <div className="text-center text-sm text-white/80">
                    <span>
                      {generationStatus === "submitting"
                        ? "正在提交任务..."
                        : "AI 正在生成图片，请耐心等待..."}
                    </span>
                  </div>
                  <div className="text-right text-sm text-white/80">
                    <span>{completedCount}/{totalCount} 张</span>
                  </div>
                  <div className="relative h-3 bg-white/20 rounded-full overflow-hidden">
                    {/* Shimmer 动画叠加层 */}
                    <div
                      className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent"
                      style={{
                        backgroundSize: "200% 100%",
                        animation: "shimmer 2s infinite linear",
                      }}
                    />
                    {/* 实际进度填充 */}
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-purple-400 via-pink-400 to-red-400"
                      style={{
                        width: `${progressPercent}%`,
                        transition: "width 0.5s ease-out",
                      }}
                    />
                  </div>
                </div>
                {/* 计时器 */}
                <div className="flex items-center justify-center gap-6 text-sm text-white/70">
                  <span className="flex items-center gap-1">
                    <span className="animate-spin inline-block">⏱</span>
                    {elapsedSeconds}秒
                  </span>
                  <span>{progressPercent}%</span>
                </div>
              </div>
            ) : (
              `🚀 一键生成：9张主图 + 2张辅助图`
            )}
          </button>
          <p className="text-center text-white/60 text-sm mt-3">
            当前将生成 {modelImageCount} 张模特图、{productImageCount} 张商品图，并附带局部放大图和白底对比图
          </p>
        </section>

        {/* 生成结果 */}
        {generatedImages.some(isNonEmptyImageUrl) && (
          <section className="mb-8">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                <span>✨</span> 生成的主图
              </h2>
              <span className="text-white/50 text-sm">
                模特图 {generatedModelImageCount} 张 / 商品图 {generatedProductImages.length} 张
              </span>
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 gap-3">
              {generatedImages.map((imgUrl, index) => (
                isNonEmptyImageUrl(imgUrl) ? (
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
                    <span className="text-white text-[10px] leading-none">
                      {index < generatedModelImageCount ? `模特图 ${index + 1}` : `商品图 ${index - generatedModelImageCount + 1}`}
                    </span>
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
                  {/* 单图重试按钮 */}
                  <div className="absolute top-1 left-1 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleSingleImageTest(index); }}
                      disabled={isLoading || !imgUrl}
                      className="p-1.5 bg-orange-500/70 hover:bg-orange-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-md text-white text-xs transition-all"
                      title="单图重试"
                    >
                      🔄
                    </button>
                  </div>
                  </div>
                ) : null
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
                        onClick={() => copyToClipboard(`${tag}`, index + 10)}
                        className={`group relative px-4 py-2 rounded-full text-sm font-medium transition-all ${
                          copiedTitleIndex === index + 10
                            ? "bg-green-500/80 text-white"
                            : "bg-gradient-to-r from-pink-600/60 to-purple-600/60 hover:from-pink-500 hover:to-purple-500 text-white shadow-lg shadow-pink-500/20"
                        }`}
                      >
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
                onClick={() => copyToClipboard(`${tag}`, index + 10)}
                className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${
                  copiedTitleIndex === index + 10
                    ? "bg-green-500 text-white"
                    : "bg-gradient-to-r from-pink-600/60 to-purple-600/60 hover:from-pink-500 hover:to-purple-500 text-white shadow-lg shadow-pink-500/20"
                }`}
              >
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
      <Modal
        open={showAuthModal}
        title={authMode === "login" ? "用户登录" : "用户注册"}
        onClose={() => setShowAuthModal(false)}
        containerClassName="w-full max-w-md"
      >
        <form onSubmit={handleAuthSubmit} className="space-y-4">
          <input
            type="text"
            placeholder="用户名"
            value={authForm.username}
            onChange={(e) => setAuthForm({ ...authForm, username: e.target.value })}
            className="w-full px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:border-purple-500"
            required
            minLength={3}
            maxLength={50}
          />
          <input
            type="password"
            placeholder="密码"
            value={authForm.password}
            onChange={(e) => setAuthForm({ ...authForm, password: e.target.value })}
            className={`w-full px-4 py-3 bg-white/10 border rounded-lg text-white placeholder-white/50 focus:outline-none focus:border-purple-500 ${
              authMode === "register" && authForm.password.length > 0 && !(
                authForm.password.length >= 12 &&
                /[a-z]/.test(authForm.password) &&
                /[A-Z]/.test(authForm.password) &&
                /[0-9]/.test(authForm.password) &&
                /[^a-zA-Z0-9]/.test(authForm.password)
              )
                ? "border-red-500"
                : "border-white/20"
            }`}
            required
            minLength={authMode === "register" ? 12 : 6}
            maxLength={128}
          />
          {authMode === "register" && authForm.password.length > 0 && (() => {
            const pw = authForm.password;
            const rules = [
              { ok: pw.length >= 12, text: "至少12位" },
              { ok: /[a-z]/.test(pw), text: "包含小写字母" },
              { ok: /[A-Z]/.test(pw), text: "包含大写字母" },
              { ok: /[0-9]/.test(pw), text: "包含数字" },
              { ok: /[^a-zA-Z0-9]/.test(pw), text: "包含特殊字符" },
            ];
            return (
              <ul className="space-y-0.5">
                {rules.map((r) => (
                  <li key={r.text} className={`text-xs ${r.ok ? "text-green-400" : "text-red-400"}`}>
                    {r.ok ? "✓" : "✗"} {r.text}
                  </li>
                ))}
              </ul>
            );
          })()}
          {authMode === "register" && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <input
                type="text"
                placeholder="手机号（可选）"
                value={authForm.phone}
                onChange={(e) => setAuthForm({ ...authForm, phone: e.target.value })}
                className="px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:border-purple-500"
                maxLength={30}
              />
              <input
                type="email"
                placeholder="邮箱（可选）"
                value={authForm.email}
                onChange={(e) => setAuthForm({ ...authForm, email: e.target.value })}
                className="px-4 py-3 bg-white/10 border border-white/20 rounded-lg text-white placeholder-white/50 focus:outline-none focus:border-purple-500"
                maxLength={120}
              />
            </div>
          )}
          <button
            type="submit"
            disabled={authLoading}
            className="w-full py-3 bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 rounded-lg font-semibold text-white transition-colors"
          >
            {authLoading ? "处理中..." : authMode === "login" ? "登录" : "注册并登录"}
          </button>
          <button
            type="button"
            onClick={() => setAuthMode(authMode === "login" ? "register" : "login")}
            className="w-full py-2 text-white/70 hover:text-white text-sm"
          >
            {authMode === "login" ? "没有账号？去注册" : "已有账号？去登录"}
          </button>
        </form>
      </Modal>

      <Modal
        open={showHistoryModal}
        title="我的生成历史"
        onClose={() => setShowHistoryModal(false)}
        containerClassName="w-full max-w-5xl"
      >
        <div className="space-y-3">
          {historyItems.map((item) => (
            <div key={item.id} className="grid grid-cols-1 md:grid-cols-[1.1fr_1fr_1.6fr_1.4fr_auto] gap-4 items-center bg-white/5 border border-white/10 rounded-lg p-4">
              <div className="text-white/80 text-sm">{item.created_at?.replace("T", " ").slice(0, 19)}</div>
              <div className="text-white font-medium">{item.product_type || "-"}</div>
              <div className="text-white/70 text-sm line-clamp-2">{item.description_snapshot || ""}</div>
              <div className="flex gap-2">
                {item.preview_images.slice(0, 3).map((url, index) => (
                  <img
                    key={`${item.id}-${index}`}
                    src={proxyImg(url)}
                    alt="历史缩略图"
                    className="h-16 w-16 rounded-lg object-cover border border-white/10"
                    loading="lazy"
                    decoding="async"
                  />
                ))}
              </div>
              <button
                onClick={() => loadHistoryDetail(item.id)}
                disabled={detailLoading}
                className="px-3 py-1.5 bg-purple-500/70 hover:bg-purple-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white text-xs rounded-lg transition-all whitespace-nowrap"
              >
                详情
              </button>
            </div>
          ))}
          {historyItems.length === 0 && (
            <div className="py-10 text-center text-white/50">暂无生成历史</div>
          )}
        </div>
      </Modal>

      {/* 历史记录详情弹窗 */}
      <Modal
        open={showDetailModal}
        title="生成详情"
        onClose={() => { setShowDetailModal(false); setDetailItem(null); }}
        containerClassName="w-full max-w-3xl"
      >
        {detailLoading ? (
          <div className="py-10 text-center text-white/50">加载中...</div>
        ) : detailItem ? (
          <div className="space-y-6">
            {/* 元信息 */}
            <div className="flex flex-wrap gap-4 text-sm text-white/60">
              <span>{detailItem.created_at?.replace("T", " ").slice(0, 19)}</span>
              <span>{detailItem.product_type || "-"}</span>
              <span className={detailItem.status === "completed" ? "text-green-400" : "text-red-400"}>
                {detailItem.status === "completed" ? "已完成" : "失败"}
              </span>
            </div>

            {/* 描述 */}
            {detailItem.description_snapshot && (
              <div>
                <h4 className="text-white font-medium mb-2 flex items-center gap-2">
                  <span>📝</span> 描述
                </h4>
                <p className="text-white/70 text-sm bg-white/5 rounded-lg p-3">{detailItem.description_snapshot}</p>
              </div>
            )}

            {/* 适用人群 */}
            {detailItem.target_audience && (
              <div className="p-4 bg-gradient-to-r from-green-500/20 to-blue-500/20 rounded-lg border border-green-500/30">
                <h4 className="text-white font-medium mb-1 flex items-center gap-2">
                  <span>👥</span> 适用人群
                </h4>
                <p className="text-green-300 font-medium">{detailItem.target_audience}</p>
              </div>
            )}

            {/* 生成图片 */}
            {(() => {
              const detailImages = (detailItem.all_images_json || []).length > 0
                ? detailItem.all_images_json
                : (detailItem.preview_images || []);
              return detailImages.length > 0 && (
                <div>
                  <h4 className="text-white font-medium mb-3 flex items-center gap-2">
                    <span>🖼️</span> 生成图片
                  </h4>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    {detailImages.map((url: string, i: number) => (
                      <img
                        key={i}
                        src={proxyImg(url)}
                        alt={`图片 ${i + 1}`}
                        className="w-full h-40 object-cover rounded-lg border border-white/10 cursor-pointer hover:border-purple-500 transition-all"
                        onClick={() => setLightboxUrl(url)}
                        loading="lazy"
                        decoding="async"
                      />
                    ))}
                  </div>
                </div>
              );
            })()}

            {/* 爆款标题 */}
            {(detailItem.titles_json || []).length > 0 && (
              <div>
                <h4 className="text-white font-medium mb-3 flex items-center gap-2">
                  <span>🔥</span> 爆款标题
                </h4>
                <div className="space-y-2">
                  {detailItem.titles_json.map((title: string, index: number) => (
                    <div key={index} className="flex items-center gap-2 p-3 bg-white/5 rounded-lg">
                      <span className="text-white/60 text-sm">{index + 1}.</span>
                      <span className="flex-1 text-white text-sm">{title}</span>
                      <button
                        onClick={() => copyToClipboard(title, index)}
                        className="px-3 py-1 bg-purple-500/50 hover:bg-purple-500 text-white text-sm rounded transition-all"
                      >
                        复制
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 标签 */}
            {(detailItem.tags_json || []).length > 0 && (
              <div>
                <h4 className="text-white font-medium mb-3 flex items-center gap-2">
                  <span>🏷️</span> 标签
                </h4>
                <div className="flex flex-wrap gap-2">
                  {detailItem.tags_json.map((tag: string, index: number) => (
                    <button
                      key={index}
                      onClick={() => copyToClipboard(tag, index + 50)}
                      className="px-4 py-2 rounded-full text-sm font-medium bg-gradient-to-r from-pink-600/60 to-purple-600/60 hover:from-pink-500 hover:to-purple-500 text-white transition-all"
                    >
                      {tag}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* 关闭按钮 */}
            <button
              onClick={() => { setShowDetailModal(false); setDetailItem(null); }}
              className="w-full py-3 bg-white/10 hover:bg-white/20 text-white rounded-lg font-medium transition-all"
            >
              关闭
            </button>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={showBillingModal}
        title="积分充值与消费明细"
        onClose={() => setShowBillingModal(false)}
        containerClassName="w-full max-w-5xl"
      >
        <div className="space-y-6">
          <div className="flex items-center justify-between bg-white/5 border border-white/10 rounded-lg p-4">
            <div>
              <div className="text-white/60 text-sm">当前余额</div>
              <div className="text-2xl font-bold text-white">{wallet?.balance ?? 0} 积分</div>
            </div>
            <div className="text-white/60 text-sm">每次生成扣 {generationCostPoints} 积分</div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {packages.map((pkg) => (
              <div key={pkg.id} className="bg-white/5 border border-white/10 rounded-lg p-4">
                <div className="text-white font-semibold">{pkg.name}</div>
                <div className="text-white/60 text-sm mt-1">¥{(pkg.price_fen / 100).toFixed(2)}</div>
                <div className="text-2xl font-bold text-white mt-3">{pkg.points + pkg.bonus_points} 积分</div>
                <button
                  onClick={() => createRechargeOrder(pkg.id)}
                  className="w-full mt-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-white text-sm font-medium"
                >
                  创建充值订单
                </button>
              </div>
            ))}
          </div>
          {/* 待处理订单 */}
          {userOrders.filter(o => ["pending", "submitted", "rejected"].includes(o.status)).length > 0 && (
            <div className="space-y-2">
              <div className="text-white/60 text-sm font-medium">待处理订单</div>
              {userOrders.filter(o => ["pending", "submitted", "rejected"].includes(o.status)).map((order) => {
                const statusMap: Record<string, { label: string; color: string }> = {
                  pending: { label: "待支付", color: "text-blue-300" },
                  submitted: { label: "待审核", color: "text-yellow-300" },
                  rejected: { label: "已驳回", color: "text-red-300" },
                };
                const st = statusMap[order.status] || { label: order.status, color: "text-white/60" };
                return (
                  <div key={order.order_no} className="flex items-center justify-between bg-white/5 border border-white/10 rounded-lg p-3">
                    <div>
                      <div className="text-white text-sm">{order.package_name || "充值"} · ¥{(order.amount_fen / 100).toFixed(2)}</div>
                      <div className="text-white/40 text-xs font-mono">{order.order_no}</div>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className={`text-xs font-medium ${st.color}`}>{st.label}</span>
                      <button
                        onClick={() => {
                          setPayingOrder(order);
                          setPaymentRemark(order.payment_remark || "");
                          setPaymentFile(null);
                          setShowBillingModal(false);
                          setShowPaymentModal(true);
                        }}
                        className="px-3 py-1.5 bg-purple-600 hover:bg-purple-700 rounded text-white text-xs"
                      >
                        {order.status === "rejected" ? "重新提交" : "去支付"}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          <div className="bg-white/5 border border-white/10 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-white/5 text-white/60">
                <tr>
                  <th className="text-left px-4 py-3">时间</th>
                  <th className="text-left px-4 py-3">类型</th>
                  <th className="text-left px-4 py-3">订单</th>
                  <th className="text-left px-4 py-3">积分</th>
                  <th className="text-left px-4 py-3">余额</th>
                </tr>
              </thead>
              <tbody>
                {ledgerItems.map((item) => (
                  <tr key={item.id} className="border-t border-white/10 text-white/80">
                    <td className="px-4 py-3">{item.created_at?.replace("T", " ").slice(0, 19)}</td>
                    <td className="px-4 py-3">{item.type}</td>
                    <td className="px-4 py-3">{item.order_no || item.remark || "-"}</td>
                    <td className="px-4 py-3">{item.direction === "out" ? "-" : "+"}{item.points}</td>
                    <td className="px-4 py-3">{item.balance_after}</td>
                  </tr>
                ))}
                {!billingLoading && ledgerItems.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-white/50">暂无消费明细</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </Modal>

      {/* 支付弹窗 */}
      <Modal
        open={showPaymentModal}
        title="扫码支付"
        onClose={() => { setShowPaymentModal(false); setPayingOrder(null); }}
        containerClassName="w-full max-w-lg"
      >
        {payingOrder && (
          <div className="space-y-5">
            {/* 订单信息 */}
            <div className="flex items-center justify-between bg-white/5 border border-white/10 rounded-lg p-4">
              <div>
                <div className="text-white/60 text-sm">订单号</div>
                <div className="text-white font-mono text-sm">{payingOrder.order_no}</div>
              </div>
              <div className="text-right">
                <div className="text-white/60 text-sm">{payingOrder.package_name || "充值"}</div>
                <div className="text-2xl font-bold text-green-400">¥{(payingOrder.amount_fen / 100).toFixed(2)}</div>
              </div>
            </div>

            {/* 状态：已到账 */}
            {payingOrder.status === "credited" && (
              <div className="text-center py-6">
                <div className="text-4xl mb-3">✅</div>
                <div className="text-xl font-bold text-green-400">充值成功</div>
                <div className="text-white/60 text-sm mt-1">{payingOrder.points} 积分已到账</div>
                <button
                  onClick={() => { setShowPaymentModal(false); setPayingOrder(null); }}
                  className="mt-4 px-6 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-white text-sm"
                >
                  完成
                </button>
              </div>
            )}

            {/* 状态：已提交待审核 */}
            {payingOrder.status === "submitted" && (
              <div className="text-center py-4">
                <div className="text-3xl mb-3">⏳</div>
                <div className="text-lg font-semibold text-yellow-300">凭证已提交，等待管理员审核</div>
                <div className="text-white/60 text-sm mt-2">请耐心等待，审核通过后积分将自动到账</div>
                {payingOrder.payment_remark && (
                  <div className="text-white/40 text-xs mt-2">备注: {payingOrder.payment_remark}</div>
                )}
                {payingOrder.proof_image && (
                  <div className="mt-3">
                    <img src={`/api/proof-image?path=${encodeURIComponent(payingOrder.proof_image)}`} alt="付款凭证" className="max-h-40 mx-auto rounded border border-white/20" />
                  </div>
                )}
                <button
                  onClick={refreshPayingOrder}
                  className="mt-4 px-6 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-white text-sm"
                >
                  刷新状态
                </button>
              </div>
            )}

            {/* 状态：待支付/已驳回 → 显示二维码和提交表单 */}
            {(payingOrder.status === "pending" || payingOrder.status === "rejected") && (
              <>
                {payingOrder.status === "rejected" && payingOrder.reject_reason && (
                  <div className="bg-red-500/20 border border-red-500/30 rounded-lg p-3 text-red-300 text-sm">
                    驳回原因: {payingOrder.reject_reason}
                    <div className="text-white/40 text-xs mt-1">请修改后重新提交</div>
                  </div>
                )}

                {/* 二维码 */}
                <div className="flex flex-col items-center bg-white rounded-xl p-4">
                  <img src="/wechatpay.png" alt="微信收款码" className="w-56 h-56 object-contain" />
                  <div className="text-gray-500 text-xs mt-2">微信扫码支付</div>
                </div>

                {/* 付款提示 */}
                <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3 text-yellow-200 text-sm space-y-1">
                  <div>1. 请使用微信扫描上方二维码</div>
                  <div>2. 支付金额: <span className="font-bold">¥{(payingOrder.amount_fen / 100).toFixed(2)}</span></div>
                  <div>3. <span className="font-semibold">转账备注填写: {payingOrder.order_no}</span></div>
                  <div>4. 支付完成后填写下方信息并提交</div>
                </div>

                {/* 备注输入 */}
                <div>
                  <label className="block text-white/60 text-sm mb-1">付款备注 <span className="text-white/40">(微信昵称/转账附言)</span></label>
                  <input
                    type="text"
                    value={paymentRemark}
                    onChange={(e) => setPaymentRemark(e.target.value)}
                    placeholder="请输入微信昵称或转账附言"
                    className="w-full px-3 py-2 bg-white/5 border border-white/20 rounded-lg text-white placeholder-white/30 text-sm focus:outline-none focus:border-purple-500"
                  />
                </div>

                {/* 截图上传 */}
                <div>
                  <label className="block text-white/60 text-sm mb-1">付款截图 <span className="text-white/40">(可选)</span></label>
                  <div className="border-2 border-dashed border-white/20 rounded-lg p-4 text-center hover:border-purple-500/50 transition-colors">
                    {paymentFile ? (
                      <div className="space-y-2">
                        <img src={URL.createObjectURL(paymentFile)} alt="预览" className="max-h-32 mx-auto rounded" />
                        <button onClick={() => setPaymentFile(null)} className="text-red-400 text-xs hover:underline">移除</button>
                      </div>
                    ) : (
                      <label className="cursor-pointer block">
                        <div className="text-white/40 text-sm">点击上传截图</div>
                        <div className="text-white/30 text-xs mt-1">支持 JPG/PNG/WebP，最大 5MB</div>
                        <input
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          className="hidden"
                          onChange={(e) => {
                            const f = e.target.files?.[0];
                            if (f) {
                              if (f.size > 5 * 1024 * 1024) {
                                toast.error("图片大小不能超过 5MB");
                                return;
                              }
                              setPaymentFile(f);
                            }
                          }}
                        />
                      </label>
                    )}
                  </div>
                </div>

                {/* 提交按钮 */}
                <button
                  onClick={submitPaymentProof}
                  disabled={paymentSubmitting || (!paymentRemark.trim() && !paymentFile)}
                  className="w-full py-3 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed rounded-lg text-white font-medium"
                >
                  {paymentSubmitting ? "提交中..." : "我已付款，提交凭证"}
                </button>
              </>
            )}
          </div>
        )}
      </Modal>

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
          <p className="text-sm mt-2">联系管理员/问题反馈：邱忠祥 13543825114</p>
        </div>
      </footer>
    </div>
    </ErrorBoundary>
  );
}
