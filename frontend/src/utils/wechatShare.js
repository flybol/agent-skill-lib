/**
 * 微信 JS-SDK 分享管理器
 * 处理微信环境检测、SDK 初始化、分享内容设置
 */

class WeChatShareManager {
    constructor() {
        this.isWeChat = this._detectWeChat();
        this.isConfigured = false;
        this.config = null;
        this.shareData = {};
    }

    /**
     * 检测是否在微信浏览器中
     */
    _detectWeChat() {
        const ua = navigator.userAgent.toLowerCase();
        return ua.indexOf('micromessenger') !== -1;
    }

    /**
     * 检查是否支持微信分享
     */
    isSupported() {
        return this.isWeChat && typeof wx !== 'undefined';
    }

    /**
     * 初始化微信 JS-SDK
     */
    async init() {
        if (!this.isSupported()) {
            console.log('非微信环境，跳过微信 SDK 初始化');
            return false;
        }

        if (this.isConfigured) {
            return true;
        }

        try {
            // 获取当前 URL（不含 hash）
            const url = window.location.href.split('#')[0];

            // 检查是否为 IP 地址（开发环境）
            // 微信 JS-SDK 只支持域名，不支持 IP 地址
            const isIpAddress = /^(https?:\/\/)?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?/.test(url);
            if (isIpAddress) {
                console.log('检测到 IP 地址（开发环境），跳过微信 SDK 初始化');
                return false;
            }

            // 检查是否为 localhost
            const isLocalhost = url.includes('localhost') || url.includes('127.0.0.1');
            if (isLocalhost) {
                console.log('检测到 localhost（开发环境），跳过微信 SDK 初始化');
                return false;
            }

            // 请求后端获取签名配置
            const response = await fetch(`/api/wechat/jssdk-config?url=${encodeURIComponent(url)}`);
            const result = await response.json();

            if (result.success && result.data) {
                this.config = result.data;

                // 配置微信 SDK
                return new Promise((resolve) => {
                    wx.config({
                        debug: false,
                        appId: this.config.appId,
                        timestamp: this.config.timestamp,
                        nonceStr: this.config.nonceStr,
                        signature: this.config.signature,
                        jsApiList: ['updateTimelineShareData', 'updateAppMessageShareData']
                    });

                    wx.ready(() => {
                        this.isConfigured = true;
                        console.log('微信 JS-SDK 初始化成功');
                        resolve(true);
                    });

                    wx.error((res) => {
                        console.error('微信 JS-SDK 配置失败:', res);
                        resolve(false);
                    });
                });
            }
        } catch (error) {
            console.error('获取微信配置失败:', error);
        }

        return false;
    }

    /**
     * 设置分享内容
     */
    setShareData({ title, link, imgUrl, desc }) {
        this.shareData = {
            title: title || '🏓 我的AI乒乓球技术分析报告',
            link: link || window.location.href.split('#')[0],
            imgUrl: imgUrl || 'https://your.domain/static/share.jpg', // TODO: 替换为实际图片地址
            desc: desc || '点击查看详细分析报告'
        };

        // 如果已配置，立即更新分享内容
        if (this.isConfigured) {
            this._updateShareData();
        }
    }

    /**
     * 更新微信分享内容
     */
    _updateShareData() {
        if (!this.isConfigured) return;

        // 更新朋友圈分享
        wx.updateTimelineShareData({
            title: this.shareData.title,
            link: this.shareData.link,
            imgUrl: this.shareData.imgUrl,
            success: () => {
                console.log('朋友圈分享内容设置成功');
            },
            fail: (err) => {
                console.error('朋友圈分享内容设置失败:', err);
            }
        });

        // 更新发送给朋友分享
        wx.updateAppMessageShareData({
            title: this.shareData.title,
            desc: this.shareData.desc,
            link: this.shareData.link,
            imgUrl: this.shareData.imgUrl,
            success: () => {
                console.log('发送给朋友分享内容设置成功');
            },
            fail: (err) => {
                console.error('发送给朋友分享内容设置失败:', err);
            }
        });
    }

    /**
     * 显示分享引导层
     */
    showShareGuide() {
        // 移除旧的引导层
        const oldGuide = document.getElementById('wxShareGuide');
        if (oldGuide) {
            document.body.removeChild(oldGuide);
        }

        // 创建引导层
        const guide = document.createElement('div');
        guide.id = 'wxShareGuide';
        guide.className = 'fixed inset-0 z-[9999] bg-black bg-opacity-75';
        guide.innerHTML = `
            <div class="relative w-full h-full">
                <!-- 箭头指向右上角 -->
                <svg class="absolute top-4 right-4 w-32 h-32 text-yellow-400" viewBox="0 0 100 100" fill="currentColor">
                    <path d="M20 80 L80 20 L90 20 L90 30 L30 90 L20 90 Z" opacity="0.9"/>
                    <circle cx="85" cy="15" r="20" fill="#fbbf24"/>
                </svg>

                <!-- 提示文字 -->
                <div class="absolute top-32 right-8 text-white text-right">
                    <div class="text-xl font-bold mb-2">点击右上角 <span class="text-yellow-400">···</span></div>
                    <div class="text-lg mb-2">选择 <span class="text-yellow-400">「分享给朋友」</span> 或 <span class="text-yellow-400">「分享到朋友圈」</span></div>
                    <div class="text-sm opacity-70">即可分享您的分析报告</div>
                </div>

                <!-- 关闭按钮 -->
                <button id="closeGuideBtn" class="absolute bottom-20 left-1/2 transform -translate-x-1/2 px-8 py-3 bg-white bg-opacity-20 rounded-full text-white font-medium">
                    我知道了
                </button>
            </div>
        `;

        document.body.appendChild(guide);

        // 点击关闭按钮
        guide.querySelector('#closeGuideBtn').addEventListener('click', () => {
            document.body.removeChild(guide);
        });

        // 点击背景关闭
        guide.addEventListener('click', (e) => {
            if (e.target === guide) {
                document.body.removeChild(guide);
            }
        });
    }

    /**
     * 简化的分享方案：直接显示分享卡片弹窗
     * 不依赖微信SDK，适用于所有环境
     */
    showShareCard(shareData) {
        // 移除旧的引导层
        const oldGuide = document.getElementById('wxShareCard');
        if (oldGuide) {
            document.body.removeChild(oldGuide);
        }

        const { title, link, desc } = shareData;

        // 创建分享卡片弹窗
        const card = document.createElement('div');
        card.id = 'wxShareCard';
        card.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;z-index:9999;padding:20px;';

        card.innerHTML = `
            <div style="background:white;border-radius:20px;padding:0;margin:20px;max-width:380px;overflow:hidden;box-shadow:0 10px 40px rgba(0,0,0,0.2);">
                <!-- 顶部标题 -->
                <div style="background:linear-gradient(135deg, #667eea 0%, #764ba2 100%);padding:24px 20px;text-align:center;">
                    <div style="width:50px;height:50px;background:rgba(255,255,255,0.2);border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 12px;">
                        <svg width="24" height="24" fill="none" stroke="white" viewBox="0 0 24 24" style="stroke-width:2;">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"/>
                        </svg>
                    </div>
                    <h2 style="font-size:18px;font-weight:600;color:white;margin:0;">分享到微信</h2>
                    <p style="font-size:13px;color:rgba(255,255,255,0.8);margin:4px 0 0;">截图或复制链接分享到朋友圈</p>
                </div>

                <!-- 分享内容预览 -->
                <div style="padding:20px;background:#f9fafb;">
                    <div style="background:white;border-radius:12px;padding:16px;border:1px solid #e5e7eb;">
                        <h3 style="font-size:16px;font-weight:600;color:#111827;margin:0 0 8px;">${title}</h3>
                        <p style="font-size:13px;color:#6b7280;margin:0 0 12px;line-height:1.5;">${desc}</p>
                        <div style="background:#f3f4f6;border-radius:8px;padding:10px;">
                            <p style="font-size:11px;color:#6b7280;margin:0 0 4px;">分享链接：</p>
                            <p style="font-size:12px;color:#374151;word-break:break-all;margin:0;font-family:monospace;">${link}</p>
                        </div>
                    </div>
                </div>

                <!-- 操作按钮 -->
                <div style="padding:16px 20px;display:flex;gap:10px;">
                    <button id="copyLinkBtn" style="flex:1;padding:14px;background:#2563eb;color:white;border:none;border-radius:10px;font-size:15px;font-weight:600;cursor:pointer;">
                        复制链接
                    </button>
                    <button id="closeCardBtn" style="flex:1;padding:14px;background:#f3f4f6;color:#374151;border:none;border-radius:10px;font-size:15px;font-weight:500;cursor:pointer;">
                        关闭
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(card);

        // 绑定复制按钮
        const copyBtn = card.querySelector('#copyLinkBtn');
        copyBtn.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(link);
                copyBtn.textContent = '已复制！';
                copyBtn.style.background = '#10b981';
                setTimeout(() => {
                    copyBtn.textContent = '复制链接';
                    copyBtn.style.background = '#2563eb';
                }, 2000);
            } catch (err) {
                // 降级方案
                const textArea = document.createElement('textarea');
                textArea.value = link;
                textArea.style.position = 'fixed';
                textArea.style.opacity = '0';
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
                copyBtn.textContent = '已复制！';
                copyBtn.style.background = '#10b981';
                setTimeout(() => {
                    copyBtn.textContent = '复制链接';
                    copyBtn.style.background = '#2563eb';
                }, 2000);
            }
        });

        // 绑定关闭按钮
        card.querySelector('#closeCardBtn').addEventListener('click', () => {
            document.body.removeChild(card);
        });

        // 点击背景关闭
        card.addEventListener('click', (e) => {
            if (e.target === card) {
                document.body.removeChild(card);
            }
        });
    }

    /**
     * 分享流程：初始化 + 设置内容 + 显示引导（保留兼容性）
     */
    async share(shareData) {
        // 直接使用简化的分享卡片方案
        this.showShareCard(shareData);
        return true;
    }
}

// 导出单例
export const wechatShareManager = new WeChatShareManager();
