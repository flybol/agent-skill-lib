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
     * 分享流程：初始化 + 设置内容 + 显示引导
     */
    async share(shareData) {
        // 设置分享内容
        this.setShareData(shareData);

        // 确保已初始化
        const initialized = await this.init();

        if (initialized) {
            // 显示引导层
            this.showShareGuide();
            return true;
        }

        return false;
    }
}

// 导出单例
export const wechatShareManager = new WeChatShareManager();
