# 模块审查提示词：前端 UI 主页

## 模块概述

"发财计划"主页面是 TikTok Shop 九国跨境电商 AI 图片生成工具的核心用户界面。采用 client component 架构，包含国家选择、模型选择、商品类型、图片上传、生成流程、SSE 进度追踪、用户系统和结果展示等完整功能。

## 涉及文件

| 文件 | 职责 | 行数 |
|------|------|------|
| `src/app/page.tsx` | 主页面（核心生成器 UI） | ~1400 |
| `src/components/country-picker.tsx` | 9 国市场选择器 | ~80 |
| `src/components/model-picker.tsx` | 6 种 AI 模型选择器 | ~80 |
| `src/components/image-gallery.tsx` | 生成结果图片画廊 | ~100 |

## 审查提示词

请对前端 UI 主页进行全面代码审查，重点检查以下方面：

### 1. 组件设计与拆分（High）

- **单文件过大**：
  - `page.tsx` 约 1400 行，是否应拆分为多个子组件
  - 建议拆分方向：CountryPicker、ModelPicker、ProductTypeSelector、ImageUploader、GenerationFlow、ResultDisplay、UserAuth（登录/注册/钱包）
  - 哪些状态可以下沉到子组件

- **状态管理**：
  - 是否存在 prop drilling 过深的问题
  - 是否应该引入状态管理库（如 Zustand）或 Context
  - 哪些状态是全局共享的（如用户信息、生成状态）

- **自定义 Hook**：
  - 生成流程逻辑是否应抽取为 `useGeneration` Hook
  - SSE 连接逻辑是否应抽取为 `useGenerationSSE` Hook
  - 用户认证逻辑是否应抽取为 `useAuth` Hook

### 2. 性能（High）

- **不必要的重渲染**：
  - `useEffect` 依赖数组是否正确，是否存在缺失或多余的依赖
  - 大型 state 对象（如图片列表）是否会导致不必要的组件更新
  - 是否应该使用 `useMemo` / `useCallback` 优化

- **图片处理**：
  - base64 编码的图片是否会导致内存膨胀
  - 大量图片的懒加载策略
  - 图片预览的内存管理（是否需要 revoke object URL）

- **事件监听**：
  - paste 事件、drag-drop 事件的清理是否正确
  - resize/scroll 事件是否需要 debounce

### 3. 用户体验（Medium）

- **加载与错误状态**：
  - 生成过程中的 loading 状态是否清晰
  - 错误消息是否用户友好（不暴露技术细节）
  - 网络断开时的降级体验

- **SSE 连接**：
  - 断线重连时用户是否能看到状态
  - 进度条的更新是否平滑
  - 超时后的用户引导

- **图片操作**：
  - 复制到剪贴板（image blob）的兼容性
  - 下载功能的浏览器兼容性
  - 图片查看器（lightbox）的性能

### 4. 代码质量（Medium）

- **Magic Numbers/Strings**：
  - 硬编码的数字（如 14 张图、11 种风格）是否应该提取为常量
  - 状态字符串（如 'pending', 'completed'）是否应该使用枚举

- **条件渲染**：
  - 嵌套的三元表达式是否可读
  - 复杂条件是否应该提取为具名变量

- **未使用代码**：
  - 是否有未使用的 import、变量、函数
  - 死代码分支

### 5. 无障碍性（Low）

- 表单元素是否有正确的 aria-label
- 键盘导航是否完整
- 颜色对比度是否符合 WCAG 标准

## 审查输出格式

请按以下格式输出审查结果：

```
### [严重程度] 问题标题

**文件**: `path/to/file.tsx:行号`
**问题**: 问题描述
**建议**: 改进方案
**影响**: 不修改的潜在风险
```

严重程度分级：
- **Critical**: 功能缺陷或数据丢失风险
- **High**: 性能瓶颈或严重用户体验问题
- **Medium**: 代码质量或可维护性问题
- **Low**: 最佳实践建议
