import type { Metadata } from 'next';
import { Inspector } from 'react-dev-inspector';
import { ToastProvider } from '@/components/ui/toast-provider';
import './globals.css';

export const metadata: Metadata = {
  title: {
    default: '发财计划 | TikTok Shop 跨境电商 AI 作图工具',
    template: '%s | 发财计划',
  },
  description:
    'TikTok Shop 跨境电商 AI 图片生成工具。支持泰国、越南、马来西亚、菲律宾、印尼、日本、韩国、美国、中国九大市场，一键生成电商主图、爆款标题和热门标签。',
  keywords: [
    'TikTok Shop',
    '跨境电商',
    'AI 作图',
    '电商图片生成',
    '发财计划',
    '商品主图',
  ],
  openGraph: {
    title: '发财计划 | TikTok Shop 跨境电商 AI 作图工具',
    description:
      'TikTok Shop 九国跨境电商 AI 图片生成工具，一键生成电商主图、爆款标题和热门标签。',
    locale: 'zh_CN',
    type: 'website',
  },
  robots: {
    index: true,
    follow: true,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const isDev = process.env.NODE_ENV === 'development';

  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className={`antialiased`}>
        {isDev && <Inspector />}
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
