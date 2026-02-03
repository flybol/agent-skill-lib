/**
 * 分析结果展示组件 - 分层展示 AI 分析结果
 * 使用 Accordion（手风琴）和 Tabs 组织内容
 */

import { formatTime, safeJsonParse } from '../utils/helpers.js';
import { wechatShareManager } from '../utils/wechatShare.js';

export class AnalysisResult {
    constructor(container, options = {}) {
        this.container = typeof container === 'string'
            ? document.querySelector(container)
            : container;
        this.options = {
            onShare: () => {},
            onDownload: () => {},
            onReanalyze: () => {},
            ...options,
        };
        this.result = null;
        this.init();
    }

    init() {
        this.render();
        this.bindEvents();
    }

    render() {
        this.container.innerHTML = `
            <div class="analysis-result">
                <!-- 结果头部 -->
                <div id="resultHeader" class="result-header hidden bg-gradient-to-r from-blue-600 to-blue-700 rounded-t-2xl p-6 text-white">
                    <div class="flex items-center justify-between">
                        <div>
                            <h2 class="text-xl font-bold mb-1">分析完成</h2>
                            <p id="resultTime" class="text-blue-100 text-sm"></p>
                        </div>
                        <div id="overallScore" class="overall-score hidden">
                            <div class="text-3xl font-bold"></div>
                            <div class="text-sm text-blue-100">综合评分</div>
                        </div>
                    </div>
                </div>

                <!-- 内容区域 -->
                <div id="resultContent" class="result-content hidden bg-white rounded-b-2xl border border-t-0 border-gray-200">
                    <!-- Tabs -->
                    <div class="tabs border-b border-gray-200">
                        <div class="flex">
                            <button class="tab-btn active px-6 py-4 text-sm font-medium text-blue-600 border-b-2 border-blue-600" data-tab="summary">
                                概览
                            </button>
                            <button class="tab-btn px-6 py-4 text-sm font-medium text-gray-500 hover:text-gray-700" data-tab="frames">
                                关键帧
                            </button>
                            <button class="tab-btn px-6 py-4 text-sm font-medium text-gray-500 hover:text-gray-700" data-tab="details">
                                详细分析
                            </button>
                            <button class="tab-btn px-6 py-4 text-sm font-medium text-gray-500 hover:text-gray-700" data-tab="suggestions">
                                建议
                            </button>
                        </div>
                    </div>

                    <!-- Tab 内容 -->
                    <div class="tab-content p-6">
                        <div id="summaryTab" class="tab-pane"></div>
                        <div id="framesTab" class="tab-pane hidden"></div>
                        <div id="detailsTab" class="tab-pane hidden"></div>
                        <div id="suggestionsTab" class="tab-pane hidden"></div>
                    </div>

                    <!-- 操作按钮 -->
                    <div class="actions border-t border-gray-200 p-4 flex space-x-3">
                        <button id="shareBtn" class="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium py-3 px-4 rounded-xl transition-colors flex items-center justify-center">
                            <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"/>
                            </svg>
                            分享
                        </button>
                        <button id="downloadBtn" class="flex-1 bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-4 rounded-xl transition-colors flex items-center justify-center">
                            <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                            </svg>
                            下载PDF报告
                        </button>
                    </div>
                </div>

                <!-- 加载状态 -->
                <div id="loadingState" class="loading-state bg-white rounded-2xl p-12 text-center">
                    <div class="inline-block">
                        <svg class="w-12 h-12 text-blue-600 animate-spin" fill="none" viewBox="0 0 24 24">
                            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                        </svg>
                    </div>
                    <p class="mt-4 text-gray-600">正在加载分析结果...</p>
                </div>

                <!-- 空状态 -->
                <div id="emptyState" class="empty-state bg-white rounded-2xl p-12 text-center">
                    <svg class="w-16 h-16 mx-auto text-gray-300 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                    </svg>
                    <p class="text-gray-400">暂无分析结果</p>
                </div>
            </div>
        `;
    }

    bindEvents() {
        // Tab 切换
        this.container.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tabName = btn.dataset.tab;
                this.switchTab(tabName);
            });
        });

        // 操作按钮 - 分享
        this.container.querySelector('#shareBtn')?.addEventListener('click', async () => {
            await this.handleShare();
        });

        // 操作按钮 - 下载PDF
        this.container.querySelector('#downloadBtn')?.addEventListener('click', async () => {
            await this.handleDownloadPDF();
        });
    }

    /**
     * 处理PDF下载功能
     */
    async handleDownloadPDF() {
        if (!this.result) return;

        const taskId = this.result.task_id;
        if (!taskId) {
            this.showToast('任务ID不存在，无法下载报告', 'error');
            return;
        }

        try {
            // 显示加载提示
            const loadingToast = this.showLoadingToast('正在生成PDF报告...');

            // 构造PDF下载URL
            const pdfUrl = `/api/results/${taskId}/pdf`;

            // 下载PDF
            const response = await fetch(pdfUrl);

            loadingToast.remove();

            if (!response.ok) {
                throw new Error(`下载失败: ${response.status} ${response.statusText}`);
            }

            // 获取文件名
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = `乒乓分析报告_${taskId}.pdf`;
            if (contentDisposition) {
                const match = contentDisposition.match(/filename="(.+)"/);
                if (match && match[1]) {
                    filename = match[1];
                }
            }

            // 获取PDF数据
            const blob = await response.blob();

            // 创建下载链接
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);

            this.showToast('PDF报告下载成功');

        } catch (error) {
            console.error('下载PDF报告失败:', error);
            this.showToast('下载PDF报告失败，请稍后重试', 'error');
        }
    }

    /**
     * 处理分享功能
     * 微信环境：使用微信 JS-SDK + 引导层
     * 普通浏览器：生成图片并分享/下载
     */
    async handleShare() {
        if (!this.result) return;

        // 生成分享数据
        const shareData = this._generateShareData();

        // 检查是否在微信环境
        if (wechatShareManager.isSupported()) {
            // 微信环境：使用微信 JS-SDK
            const success = await wechatShareManager.share(shareData);
            if (!success) {
                // SDK 初始化失败，降级到图片分享
                await this._fallbackToImageShare();
            }
        } else {
            // 普通浏览器：生成图片并分享
            await this._fallbackToImageShare();
        }
    }

    /**
     * 生成分享数据
     */
    _generateShareData() {
        const { overall_score, summary } = this.result || {};
        const weaknesses = summary?.weaknesses || [];

        // 构建标题
        let title = '🏓 我的AI乒乓球技术分析报告';
        if (overall_score !== undefined) {
            title = `⭐ ${overall_score}分 - 我的乒乓球技术分析报告`;
        }

        // 构建描述
        let desc = 'AI教练为您生成专业的技术分析报告';
        if (summary?.overview) {
            desc = summary.overview.substring(0, 50);
        }
        if (weaknesses.length > 0) {
            desc += `\n发现${weaknesses.length}个问题需要改进`;
        }

        // 生成分享链接
        const link = this.generateShareUrl();

        // 分享图片：使用 emoji 构成的卡片式预览图
        // 注意：实际部署时建议替换为真实的专业分享图片（500x400 px）
        // 图片需要支持 HTTPS 访问
        const imgUrl = window.location.origin + '/share-cover.jpg'; // TODO: 替换为实际的分享封面图

        return { title, link, imgUrl, desc };
    }

    /**
     * 降级方案：直接复制分享内容
     */
    async _fallbackToImageShare() {
        // 生成分享链接和文案
        const shareUrl = this.generateShareUrl();
        const shareText = this.generateShareText();
        const fullContent = `${shareText}\n\n${shareUrl}`;

        // 检查是否是微信环境
        const isWeChat = /micromessenger/i.test(navigator.userAgent);

        if (isWeChat) {
            // 微信环境：直接显示手动复制界面（因为剪贴板 API 不可靠）
            this.showCopyFallback(fullContent);
            return;
        }

        // 非微信环境：尝试系统分享或复制
        const loadingToast = this.showLoadingToast('正在准备分享...');

        try {
            loadingToast.remove();

            // 尝试使用系统分享 API
            if (navigator.share) {
                try {
                    await navigator.share({
                        title: '🏓 我的AI乒乓球技术分析报告',
                        text: shareText,
                        url: shareUrl
                    });
                    this.showToast('分享成功');
                    return;
                } catch (err) {
                    if (err.name === 'AbortError') {
                        return; // 用户取消
                    }
                    // 继续尝试复制方案
                }
            }

            // 复制分享内容到剪贴板
            const copied = await this.copyToClipboard(fullContent);
            if (copied) {
                // 复制成功，显示确认界面（让用户知道已复制）
                this.showCopySuccessFallback(shareUrl, shareText);
            } else {
                // 复制失败，显示手动复制界面
                this.showCopyFallback(fullContent);
            }

        } catch (err) {
            loadingToast.remove();
            console.error('分享失败:', err);
            // 最后的降级方案
            this.showCopyFallback(fullContent);
        }
    }

    /**
     * 复制文本到剪贴板（带兼容处理）
     * 失败时返回 false，让调用方处理降级方案
     */
    async copyToClipboard(text) {
        // 方法1：使用 Clipboard API
        if (navigator.clipboard && window.isSecureContext) {
            try {
                await navigator.clipboard.writeText(text);
                this.showToast('分享内容已复制，可粘贴发送');
                return true;
            } catch (err) {
                console.log('Clipboard API 失败，尝试降级方案:', err);
            }
        }

        // 方法2：使用传统 execCommand
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.top = '0';
        textArea.style.left = '0';
        textArea.style.width = '2em';
        textArea.style.height = '2em';
        textArea.style.padding = '0';
        textArea.style.border = 'none';
        textArea.style.outline = 'none';
        textArea.style.boxShadow = 'none';
        textArea.style.background = 'transparent';
        textArea.readOnly = true; // 防止 iOS 弹出键盘
        document.body.appendChild(textArea);

        // iOS 兼容：先聚焦再选中
        if (navigator.userAgent.match(/ipad|iphone/i)) {
            const range = document.createRange();
            range.selectNodeContents(textArea);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            textArea.setSelectionRange(0, text.length);
        } else {
            textArea.select();
        }

        try {
            const successful = document.execCommand('copy');
            document.body.removeChild(textArea);
            if (successful) {
                this.showToast('分享内容已复制，可粘贴发送');
                return true;
            }
        } catch (err) {
            document.body.removeChild(textArea);
            console.error('复制失败:', err);
        }

        // 所有方法都失败，返回 false
        return false;
    }

    /**
     * 显示复制失败的降级界面
     */
    showCopyFallback(text) {
        const modal = document.createElement('div');
        modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:9999;';
        modal.innerHTML = `
            <div style="background:white;border-radius:16px;padding:24px;margin:20px;max-width:400px;">
                <h3 style="font-size:18px;font-weight:600;color:#1f2937;margin-bottom:12px;">请手动复制</h3>
                <p style="font-size:14px;color:#6b7280;margin-bottom:16px;">长按下方内容复制分享链接：</p>
                <textarea readonly style="width:100%;height:120px;border:1px solid #e5e7eb;border-radius:8px;padding:12px;font-size:13px;color:#374151;background:#f9fafb;resize:none;">${text}</textarea>
                <button id="closeModal" style="width:100%;margin-top:16px;padding:12px;background:#2563eb;color:white;border:none;border-radius:8px;font-size:15px;font-weight:500;cursor:pointer;">关闭</button>
            </div>
        `;
        document.body.appendChild(modal);
        modal.querySelector('#closeModal').addEventListener('click', () => {
            document.body.removeChild(modal);
        });
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                document.body.removeChild(modal);
            }
        });
    }

    /**
     * 显示复制成功的确认界面
     */
    showCopySuccessFallback(shareUrl, shareText) {
        const modal = document.createElement('div');
        modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;';
        modal.innerHTML = `
            <div style="background:white;border-radius:16px;padding:32px 24px;margin:20px;max-width:360px;text-align:center;">
                <div style="width:64px;height:64px;background:#10b981;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 16px;">
                    <svg width="32" height="32" fill="none" stroke="white" viewBox="0 0 24 24" style="stroke-width:3;">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
                    </svg>
                </div>
                <h3 style="font-size:20px;font-weight:600;color:#1f2937;margin-bottom:8px;">链接已复制！</h3>
                <p style="font-size:14px;color:#6b7280;margin-bottom:20px;line-height:1.5;">
                    分享链接已复制到剪贴板，<br>您可以粘贴发送给好友
                </p>
                <div style="background:#f3f4f6;border-radius:8px;padding:12px;margin-bottom:16px;text-align:left;">
                    <p style="font-size:12px;color:#6b7280;margin-bottom:4px;">分享链接：</p>
                    <p style="font-size:13px;color:#374151;word-break:break-all;">${shareUrl}</p>
                </div>
                <button id="closeModal" style="width:100%;padding:14px;background:#2563eb;color:white;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;">知道了</button>
            </div>
        `;
        document.body.appendChild(modal);
        modal.querySelector('#closeModal').addEventListener('click', () => {
            document.body.removeChild(modal);
        });
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                document.body.removeChild(modal);
            }
        });
    }

    /**
     * 生成分享链接
     */
    generateShareUrl() {
        if (!this.result) return window.location.href;

        // 使用当前域名 + 任务 ID 参数
        const url = new URL(window.location.origin);
        url.searchParams.set('task_id', this.result.task_id || '');
        return url.toString();
    }

    /**
     * 生成分享文案（微信朋友圈格式）
     */
    generateShareText() {
        if (!this.result || !this.result.summary) {
            return '🏓 我的AI乒乓球技术分析报告\n点击查看详情';
        }

        const { overall_score, summary, suggestions } = this.result;
        const weaknesses = summary.weaknesses || [];

        // 构建微信朋友圈分享文案
        let text = '🏓 AI乒乓球技术分析报告\n';

        // 评分
        if (overall_score !== undefined) {
            text += `\n⭐ 综合评分：${overall_score}分`;
        }

        // 概要（截取前60字）
        if (summary.overview) {
            text += `\n📝 ${summary.overview.substring(0, 60)}${summary.overview.length > 60 ? '...' : ''}`;
        }

        // 主要问题（最多2个）
        if (weaknesses.length > 0) {
            text += `\n\n🔸 发现问题：`;
            weaknesses.slice(0, 2).forEach((w, i) => {
                const title = typeof w === 'string' ? w : w.title;
                text += `\n  ${i + 1}. ${title}`;
            });
        }

        // 改进建议（最多2个）
        if (suggestions && suggestions.length > 0) {
            text += `\n\n💡 改进建议：`;
            suggestions.slice(0, 2).forEach((s, i) => {
                text += `\n  ${i + 1}. ${s.title}`;
            });
        }

        text += '\n\n👇 点击链接查看完整分析报告';

        return text;
    }

    /**
     * 生成分享图片卡片
     * 使用 Canvas 绘制精美的分享卡片
     */
    async generateShareImage() {
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');

        // 图片尺寸（适合朋友圈分享）
        const width = 1080;
        const height = 1920;
        canvas.width = width;
        canvas.height = height;

        const { overall_score, summary, suggestions } = this.result || {};
        const weaknesses = summary?.weaknesses || [];

        // 背景渐变
        const gradient = ctx.createLinearGradient(0, 0, 0, height);
        gradient.addColorStop(0, '#1e3a5f');
        gradient.addColorStop(1, '#0f1f33');
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, width, height);

        // 装饰圆圈
        ctx.fillStyle = 'rgba(47, 124, 246, 0.1)';
        ctx.beginPath();
        ctx.arc(width * 0.9, height * 0.15, 120, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = 'rgba(47, 124, 246, 0.05)';
        ctx.beginPath();
        ctx.arc(width * 0.1, height * 0.85, 150, 0, Math.PI * 2);
        ctx.fill();

        // 标题区域
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 72px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('🏓 乒乓球技术分析', width / 2, 140);

        ctx.font = '36px sans-serif';
        ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
        ctx.fillText('AI 教练专业评估报告', width / 2, 200);

        // 分隔线
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(100, 240);
        ctx.lineTo(width - 100, 240);
        ctx.stroke();

        let currentY = 340;

        // 综合评分
        if (overall_score !== undefined) {
            // 评分背景
            ctx.fillStyle = 'rgba(47, 124, 246, 0.3)';
            this.roundRect(ctx, 80, currentY - 80, width - 160, 180, 30);
            ctx.fill();

            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 120px sans-serif';
            ctx.fillText(overall_score, width / 2, currentY + 30);

            ctx.font = '42px sans-serif';
            ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
            ctx.fillText('综合评分', width / 2, currentY + 80);

            currentY += 160;
        }

        // 总体评价
        if (summary?.overview) {
            const overviewText = this.truncateText(summary.overview, 50);
            this.drawSection(ctx, '📝 总体评价', overviewText, width, currentY, '#4ade80');
            currentY += this.getSectionHeight(ctx, '📝 总体评价', overviewText) + 60;
        }

        // 发现问题
        if (weaknesses.length > 0) {
            const problemText = weaknesses.slice(0, 3).map((w, i) => {
                const title = typeof w === 'string' ? w : w.title;
                return `${i + 1}. ${title}`;
            }).join('\n');
            this.drawSection(ctx, '🔸 发现问题', problemText, width, currentY, '#fbbf24');
            currentY += this.getSectionHeight(ctx, '🔸 发现问题', problemText) + 60;
        }

        // 改进建议
        if (suggestions && suggestions.length > 0) {
            const suggestionText = suggestions.slice(0, 3).map((s, i) => {
                return `${i + 1}. ${s.title}`;
            }).join('\n');
            this.drawSection(ctx, '💡 改进建议', suggestionText, width, currentY, '#60a5fa');
            currentY += this.getSectionHeight(ctx, '💡 改进建议', suggestionText) + 60;
        }

        // 底部区域
        const bottomY = height - 200;
        ctx.fillStyle = 'rgba(255, 255, 255, 0.1)';
        ctx.fillRect(0, bottomY, width, 200);

        // Logo/品牌
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 48px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('乒乓数字教练', 80, bottomY + 80);

        ctx.font = '32px sans-serif';
        ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
        ctx.fillText('v1.0', 80, bottomY + 140);

        // 二维码提示
        ctx.textAlign = 'right';
        ctx.font = '32px sans-serif';
        ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
        ctx.fillText('长按保存图片分享到朋友圈', width - 80, bottomY + 110);

        // 转换为 Blob
        return new Promise((resolve) => {
            canvas.toBlob((blob) => {
                resolve(blob);
            }, 'image/png', 0.95);
        });
    }

    /**
     * 绘制圆角矩形
     */
    roundRect(ctx, x, y, width, height, radius) {
        ctx.beginPath();
        ctx.moveTo(x + radius, y);
        ctx.lineTo(x + width - radius, y);
        ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
        ctx.lineTo(x + width, y + height - radius);
        ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
        ctx.lineTo(x + radius, y + height);
        ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
        ctx.lineTo(x, y + radius);
        ctx.quadraticCurveTo(x, y, x + radius, y);
        ctx.closePath();
    }

    /**
     * 绘制分享卡片的一个区块
     */
    drawSection(ctx, title, text, width, y, color) {
        const padding = 80;
        const contentWidth = width - padding * 2;

        // 标题
        ctx.fillStyle = color;
        ctx.font = 'bold 44px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(title, padding, y + 50);

        // 先计算文字行数以确定背景高度
        ctx.font = '36px sans-serif';
        const lines = this.wrapText(ctx, text, contentWidth - 40);
        const contentHeight = Math.max(160, 100 + lines.length * 55);

        // 内容背景
        ctx.fillStyle = 'rgba(255, 255, 255, 0.08)';
        this.roundRect(ctx, padding, y + 80, contentWidth, contentHeight, 20);
        ctx.fill();

        // 内容文字
        ctx.fillStyle = '#ffffff';
        lines.forEach((line, index) => {
            ctx.fillText(line, padding + 20, y + 130 + index * 55);
        });

        // 返回区块高度
        return 80 + contentHeight + 20;
    }

    /**
     * 计算区块高度
     */
    getSectionHeight(ctx, title, text) {
        const width = 1080 - 160;
        const lines = this.wrapText(ctx, text, width - 40);
        return 130 + lines.length * 55 + 40;
    }

    /**
     * 文字换行
     */
    wrapText(ctx, text, maxWidth) {
        const paragraphs = text.split('\n');
        const lines = [];

        paragraphs.forEach(paragraph => {
            const words = paragraph.split('');
            let currentLine = '';

            for (let i = 0; i < words.length; i++) {
                const testLine = currentLine + words[i];
                const metrics = ctx.measureText(testLine);
                if (metrics.width > maxWidth && i > 0) {
                    lines.push(currentLine);
                    currentLine = words[i];
                } else {
                    currentLine = testLine;
                }
            }
            if (currentLine) {
                lines.push(currentLine);
            }
        });

        return lines;
    }

    /**
     * 截断文字
     */
    truncateText(text, maxLength) {
        if (text.length <= maxLength) return text;
        return text.substring(0, maxLength) + '...';
    }

    /**
     * 显示加载提示
     */
    showLoadingToast(message) {
        const toast = document.createElement('div');
        toast.className = 'fixed top-4 left-1/2 transform -translate-x-1/2 px-6 py-3 rounded-xl shadow-lg z-50 bg-gray-800 text-white font-medium flex items-center';
        toast.innerHTML = `
            <svg class="animate-spin h-5 w-5 mr-3" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            ${message}
        `;
        document.body.appendChild(toast);
        toast.remove = () => document.body.removeChild(toast);
        return toast;
    }

    /**
     * 备用方案：复制分享内容到剪贴板（文案+链接）
     */
    async fallbackToCopyLink(url) {
        const shareText = this.generateShareText();
        const fullContent = `${shareText}\n\n${url}`;
        await this.copyToClipboard(fullContent);
    }

    /**
     * 显示提示消息
     */
    showToast(message, type = 'success') {
        const toast = document.createElement('div');
        toast.className = `fixed top-4 left-1/2 transform -translate-x-1/2 px-6 py-3 rounded-xl shadow-lg z-50 ${
            type === 'success' ? 'bg-green-600' : 'bg-red-600'
        } text-white font-medium transition-opacity duration-300`;
        toast.textContent = message;
        document.body.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => document.body.removeChild(toast), 300);
        }, 2000);
    }

    switchTab(tabName) {
        // 更新按钮状态
        this.container.querySelectorAll('.tab-btn').forEach(btn => {
            if (btn.dataset.tab === tabName) {
                btn.classList.add('active', 'text-blue-600', 'border-b-2', 'border-blue-600');
                btn.classList.remove('text-gray-500');
            } else {
                btn.classList.remove('active', 'text-blue-600', 'border-b-2', 'border-blue-600');
                btn.classList.add('text-gray-500');
            }
        });

        // 更新内容显示
        this.container.querySelectorAll('.tab-pane').forEach(pane => {
            pane.classList.add('hidden');
        });
        this.container.querySelector(`#${tabName}Tab`)?.classList.remove('hidden');
    }

    setResult(result) {
        this.result = result;

        // 隐藏加载和空状态
        this.container.querySelector('#loadingState')?.classList.add('hidden');
        this.container.querySelector('#emptyState')?.classList.add('hidden');

        // 显示结果
        const header = this.container.querySelector('#resultHeader');
        const content = this.container.querySelector('#resultContent');
        header?.classList.remove('hidden');
        content?.classList.remove('hidden');

        // 填充数据
        this.renderHeader(result);
        this.renderSummary(result);
        this.renderFrames(result);
        this.renderDetails(result);
        this.renderSuggestions(result);

        // 默认切换到概览 tab
        this.switchTab('summary');
    }

    renderHeader(result) {
        const timeEl = this.container.querySelector('#resultTime');
        const scoreEl = this.container.querySelector('#overallScore');

        if (timeEl) {
            timeEl.textContent = `分析时间: ${formatTime(result.created_at)}`;
        }

        if (scoreEl && result.overall_score !== undefined) {
            scoreEl.classList.remove('hidden');
            scoreEl.querySelector('.text-3xl').textContent = result.overall_score;

            // 更新评分标签，添加球员方向
            const scoreLabel = scoreEl.querySelector('.text-sm');
            if (scoreLabel) {
                const playerLabel = this._getPlayerLabel(result.target_player);
                scoreLabel.textContent = playerLabel ? `${playerLabel}综合评分` : '综合评分';
            }
        }
    }

    /**
     * 获取球员方向显示文本
     */
    _getPlayerLabel(targetPlayer) {
        if (!targetPlayer) return '';
        const autoPick = targetPlayer.auto_pick || targetPlayer;
        if (autoPick === 'left') return '左侧球员';
        if (autoPick === 'right') return '右侧球员';
        if (autoPick === 'single_player') return '';
        return '';
    }

    renderSummary(result) {
        const container = this.container.querySelector('#summaryTab');
        if (!container) return;

        // 确保 summary 对象存在
        const summary = result.summary || {};
        const playerLabel = this._getPlayerLabel(result.target_player);

        // 渲染目标球员选择器
        const targetPlayerHtml = this.renderTargetPlayerSelector(result.target_player);

        container.innerHTML = `
            <div class="space-y-4">
                ${targetPlayerHtml}

                ${summary.overview ? `
                    <div class="bg-blue-50 rounded-xl p-4">
                        <h4 class="font-semibold text-blue-900 mb-2">总体评价</h4>
                        <p class="text-blue-800 text-sm">${summary.overview}</p>
                    </div>
                ` : ''}

                ${summary.strengths && summary.strengths.length > 0 ? `
                    <div>
                        <h4 class="font-semibold text-gray-800 mb-3 flex items-center">
                            <svg class="w-5 h-5 mr-2 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                            优点 (${summary.strengths.length})
                        </h4>
                        <ul class="space-y-2">
                            ${summary.strengths.map(s => `
                                <li class="flex items-start">
                                    <span class="text-green-500 mr-2 mt-1">•</span>
                                    <span class="text-gray-700 text-sm">${s}</span>
                                </li>
                            `).join('')}
                        </ul>
                    </div>
                ` : ''}

                ${summary.weaknesses && summary.weaknesses.length > 0 ? `
                    <div>
                        <h4 class="font-semibold text-gray-800 mb-3 flex items-center">
                            <svg class="w-5 h-5 mr-2 text-orange-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                            </svg>
                            ${playerLabel ? playerLabel + ' ' : ''}需要改进 (${summary.weaknesses.length})
                        </h4>
                        <ul class="space-y-2">
                            ${summary.weaknesses.map(w => {
                                const text = typeof w === 'string' ? w : (w.title || w.description || '问题');
                                const desc = typeof w === 'object' && w.description ? `<p class="text-xs text-gray-500 mt-1">${w.description}</p>` : '';
                                return `
                                <li class="flex items-start">
                                    <span class="text-orange-500 mr-2">•</span>
                                    <span class="text-gray-700 text-sm leading-tight">${text}</span>
                                </li>
                                ${desc}
                            `}).join('')}
                        </ul>
                    </div>
                ` : ''}

                ${!summary.overview && (!summary.strengths || summary.strengths.length === 0) && (!summary.weaknesses || summary.weaknesses.length === 0) ? `
                    <div class="text-center py-8">
                        <p class="text-gray-400 text-sm">暂无概要信息</p>
                    </div>
                ` : ''}
            </div>
        `;

        // 绑定目标球员选择器事件
        this.bindTargetPlayerEvents(result);
    }

    renderTargetPlayerSelector(targetPlayer) {
        // 如果没有目标球员配置或置信度很高，不显示选择器
        if (!targetPlayer || targetPlayer.auto_pick === 'single_player' || (targetPlayer.confidence || 0) >= 0.8) {
            return '';
        }

        const autoPick = targetPlayer.auto_pick || 'single_player';
        const confidence = targetPlayer.confidence || 0;
        const reason = targetPlayer.reason || '';

        const sideText = autoPick === 'left' ? '左侧球员' : '右侧球员';
        const confidencePercent = Math.round(confidence * 100);

        return `
            <div id="targetPlayerSelector" class="bg-gradient-to-r from-purple-50 to-pink-50 rounded-xl p-4 border border-purple-200">
                <div class="flex items-start">
                    <svg class="w-5 h-5 mr-2 text-purple-600 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                    </svg>
                    <div class="flex-1">
                        <h4 class="font-semibold text-purple-900 mb-1">系统判断：主要击球者 = ${sideText}</h4>
                        <p class="text-xs text-purple-700 mb-3">置信度 ${confidencePercent}% | ${reason}</p>
                        <div class="flex space-x-2">
                            <button class="target-player-btn flex-1 bg-purple-600 hover:bg-purple-700 text-white text-sm font-medium py-2 px-3 rounded-lg transition-colors" data-choice="${autoPick}">
                                <svg class="w-4 h-4 mr-1 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                                </svg>
                                就分析${sideText}
                            </button>
                            <button class="target-player-btn flex-1 bg-white hover:bg-gray-50 text-gray-700 text-sm font-medium py-2 px-3 rounded-lg border border-gray-300 transition-colors" data-choice="${autoPick === 'left' ? 'right' : 'left'}">
                                <svg class="w-4 h-4 mr-1 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/>
                                </svg>
                                不是，分析${autoPick === 'left' ? '右侧' : '左侧'}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    bindTargetPlayerEvents(result) {
        const selector = this.container.querySelector('#targetPlayerSelector');
        if (!selector) return;

        const buttons = selector.querySelectorAll('.target-player-btn');
        buttons.forEach(btn => {
            btn.addEventListener('click', () => {
                const choice = btn.dataset.choice;
                // 禁用所有按钮
                buttons.forEach(b => {
                    b.disabled = true;
                    b.classList.add('opacity-50', 'cursor-not-allowed');
                });
                // 显示确认提示
                selector.innerHTML = `
                    <div class="flex items-center text-purple-700">
                        <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                        </svg>
                        <span class="font-medium">已确认：分析${choice === 'left' ? '左侧' : '右侧'}球员</span>
                    </div>
                `;
                // TODO: 可以在这里调用 API 更新后端配置
                console.log('Target player selected:', choice);
            });
        });
    }

    renderFrames(result) {
        const container = this.container.querySelector('#framesTab');
        if (!container) return;

        const keyFrames = result.key_frames || [];

        if (keyFrames.length === 0) {
            container.innerHTML = `
                <div class="text-center py-8">
                    <p class="text-gray-400 text-sm">暂无关键帧</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="grid grid-cols-2 gap-4">
                ${keyFrames.map((frame, index) => `
                    <div class="bg-gray-50 rounded-xl overflow-hidden">
                        <img src="${frame.url}" alt="关键帧 ${index + 1}" class="w-full aspect-video object-cover">
                        <div class="p-3">
                            <p class="text-xs text-gray-500 mb-1">帧 #${frame.frame_number || index + 1}</p>
                            ${frame.description ? `<p class="text-sm text-gray-700">${frame.description}</p>` : ''}
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    renderDetails(result) {
        const container = this.container.querySelector('#detailsTab');
        if (!container) return;

        const details = result.details || {};
        const hasTechnique = details.technique && Object.keys(details.technique).length > 0;
        const hasMetrics = details.metrics && Object.keys(details.metrics).length > 0;

        if (!hasTechnique && !hasMetrics) {
            container.innerHTML = `
                <div class="text-center py-8">
                    <p class="text-gray-400 text-sm">暂无详细分析</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="space-y-6">
                ${hasTechnique ? `
                    <div class="accordion-item">
                        <button class="accordion-btn w-full flex items-center justify-between p-4 bg-gray-50 rounded-xl hover:bg-gray-100 transition-colors">
                            <span class="font-medium text-gray-800">技术动作分析</span>
                            <svg class="w-5 h-5 text-gray-500 accordion-icon transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                            </svg>
                        </button>
                        <div class="accordion-content hidden mt-2 px-4">
                            <div class="pb-4 text-sm text-gray-700 space-y-2">
                                ${Object.entries(details.technique).map(([key, value]) => `
                                    <div class="flex justify-between">
                                        <span class="text-gray-500">${key}</span>
                                        <span class="font-medium">${value}</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                ` : ''}

                ${hasMetrics ? `
                    <div class="accordion-item">
                        <button class="accordion-btn w-full flex items-center justify-between p-4 bg-gray-50 rounded-xl hover:bg-gray-100 transition-colors">
                            <span class="font-medium text-gray-800">技术指标</span>
                            <svg class="w-5 h-5 text-gray-500 accordion-icon transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                            </svg>
                        </button>
                        <div class="accordion-content hidden mt-2 px-4">
                            <div class="pb-4 text-sm text-gray-700 space-y-2">
                                ${Object.entries(details.metrics).map(([key, value]) => `
                                    <div class="flex justify-between">
                                        <span class="text-gray-500">${key}</span>
                                        <span class="font-medium">${value}</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                ` : ''}
            </div>
        `;

        // 绑定手风琴事件
        this.bindAccordionEvents(container);
    }

    renderSuggestions(result) {
        const container = this.container.querySelector('#suggestionsTab');
        if (!container) return;

        const suggestions = result.suggestions || [];

        if (suggestions.length === 0) {
            container.innerHTML = `
                <div class="text-center py-8">
                    <p class="text-gray-400 text-sm">暂无改进建议</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="space-y-4">
                <h4 class="font-semibold text-gray-800 mb-3">改进建议 (${suggestions.length})</h4>
                ${suggestions.map((suggestion, index) => `
                    <div class="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-xl p-4">
                        <div class="flex items-start">
                            <div class="w-8 h-8 bg-blue-600 text-white rounded-lg flex items-center justify-center font-bold mr-3 flex-shrink-0">
                                ${index + 1}
                            </div>
                            <div>
                                <h4 class="font-semibold text-gray-800 mb-1">${suggestion.title || `改进建议 ${index + 1}`}</h4>
                                <p class="text-sm text-gray-600">${suggestion.description || ''}</p>
                                ${suggestion.priority ? `
                                    <span class="inline-block mt-2 px-2 py-1 text-xs font-medium rounded-full ${
                                        suggestion.priority === 'high' ? 'bg-red-100 text-red-700' :
                                        suggestion.priority === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                                        'bg-gray-100 text-gray-700'
                                    }">
                                        优先级: ${suggestion.priority === 'high' ? '高' : suggestion.priority === 'medium' ? '中' : '低'}
                                    </span>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    bindAccordionEvents(container) {
        container.querySelectorAll('.accordion-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const content = btn.nextElementSibling;
                const icon = btn.querySelector('.accordion-icon');

                content.classList.toggle('hidden');
                icon.classList.toggle('rotate-180');
            });
        });
    }

    showLoading() {
        this.container.querySelector('#loadingState')?.classList.remove('hidden');
        this.container.querySelector('#emptyState')?.classList.add('hidden');
        this.container.querySelector('#resultHeader')?.classList.add('hidden');
        this.container.querySelector('#resultContent')?.classList.add('hidden');
    }

    showEmpty() {
        this.container.querySelector('#loadingState')?.classList.add('hidden');
        this.container.querySelector('#emptyState')?.classList.remove('hidden');
        this.container.querySelector('#resultHeader')?.classList.add('hidden');
        this.container.querySelector('#resultContent')?.classList.add('hidden');
    }

    destroy() {
        this.container.innerHTML = '';
    }
}
