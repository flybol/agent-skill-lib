/**
 * 视频上传组件 - shadcn/ui 风格
 * 支持拖拽上传、点击上传、视频预览
 */

import { uploadVideo } from '../api/client.js';
import { validateVideoFile, formatFileSize, getVideoDuration } from '../utils/helpers.js';

export class VideoUploader {
    constructor(container, options = {}) {
        this.container = typeof container === 'string'
            ? document.querySelector(container)
            : container;
        this.options = {
            accept: 'video/mp4,video/quicktime,video/x-msvideo',
            maxSize: 500 * 1024 * 1024,
            onUploadStart: () => {},
            onUploadProgress: () => {},
            onUploadSuccess: () => {},
            onUploadError: () => {},
            ...options,
        };
        this.file = null;
        this.previewUrl = null;
        this.init();
    }

    init() {
        this.render();
        this.bindEvents();
    }

    render() {
        this.container.innerHTML = `
            <div class="video-uploader fade-in">
                <!-- 上传区域 - 深色主题 -->
                <div id="uploadArea" class="upload-area" style="
                    background: var(--bg-secondary);
                    border: 2px dashed var(--divider-thick);
                    border-radius: 14px;
                    padding: 24px;
                    text-align: center;
                    cursor: pointer;
                    transition: all 0.2s ease;
                ">
                    <div id="uploadPrompt" class="upload-prompt">
                        <!-- 云上传图标 -->
                        <div style="margin-bottom: 12px;">
                            <svg width="48" height="48" fill="none" style="color: var(--primary);" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
                            </svg>
                        </div>
                        <p style="font-size: 15px; font-weight: 500; color: var(--text-primary); margin-bottom: 4px;">点击或拖拽上传视频</p>
                        <p style="font-size: 13px; color: var(--text-secondary);">支持 MP4、MOV 格式，最大 5 秒，最大 10MB</p>
                    </div>

                    <!-- 预览区域（初始隐藏） -->
                    <div id="previewArea" class="preview-area hidden">
                        <video id="videoPreview" style="width: 100%; border-radius: 12px; margin-bottom: 12px;" controls></video>
                        <div id="fileInfo" style="font-size: 13px; color: var(--text-secondary); margin-bottom: 12px;"></div>
                        <button id="reuploadBtn" style="font-size: 14px; font-weight: 500; color: var(--primary); background: transparent; border: none; cursor: pointer;">
                            重新选择
                        </button>
                    </div>
                </div>

                <!-- 隐藏的文件输入 -->
                <input type="file" id="fileInput" class="hidden" accept="${this.options.accept}">

                <!-- 选择文件按钮 -->
                <div style="display: flex; gap: 12px; margin-top: 16px;">
                    <button id="selectFileBtn" class="btn-secondary" style="flex: 1;">
                        选择文件
                    </button>
                </div>

                <!-- 上传进度 -->
                <div id="uploadProgress" class="upload-progress hidden" style="margin-top: 16px;">
                    <div style="display: flex; justify-between; font-size: 13px; color: var(--text-secondary); margin-bottom: 8px;">
                        <span>上传中...</span>
                        <span id="progressPercent">0%</span>
                    </div>
                    <div class="progress-bar">
                        <div id="progressBar" class="progress-bar-fill" style="width: 0%"></div>
                    </div>
                </div>
            </div>
        `;
    }

    bindEvents() {
        const uploadArea = this.container.querySelector('#uploadArea');
        const fileInput = this.container.querySelector('#fileInput');
        const selectFileBtn = this.container.querySelector('#selectFileBtn');
        const reuploadBtn = this.container.querySelector('#reuploadBtn');

        // 点击上传区域
        uploadArea.addEventListener('click', (e) => {
            if (e.target !== reuploadBtn) {
                fileInput.click();
            }
        });

        // 选择文件按钮
        selectFileBtn.addEventListener('click', () => {
            fileInput.click();
        });

        // 文件选择
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                this.handleFileSelect(e.target.files[0]);
            }
        });

        // 拖拽上传
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragging');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragging');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragging');
            if (e.dataTransfer.files.length > 0) {
                this.handleFileSelect(e.dataTransfer.files[0]);
            }
        });

        // 重新选择
        reuploadBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.reset();
        });
    }

    async handleFileSelect(file) {
        try {
            // 先验证文件类型和大小
            validateVideoFile(file);

            // 获取并验证视频时长
            const duration = await getVideoDuration(file);
            validateVideoFile(file, duration);

            this.file = file;
            this.duration = duration;

            // 创建预览
            this.previewUrl = URL.createObjectURL(file);
            const videoPreview = this.container.querySelector('#videoPreview');
            videoPreview.src = this.previewUrl;

            // 显示文件信息（包含时长）
            const fileInfo = this.container.querySelector('#fileInfo');
            const durationText = duration < 60
                ? `${duration.toFixed(1)} 秒`
                : `${Math.floor(duration / 60)} 分 ${Math.floor(duration % 60)} 秒`;
            fileInfo.textContent = `${file.name} (${formatFileSize(file.size)}, ${durationText})`;

            // 切换显示
            this.container.querySelector('#uploadPrompt').classList.add('hidden');
            this.container.querySelector('#previewArea').classList.remove('hidden');

            // 启用主应用的分析按钮
            const analyzeBtn = document.getElementById('analyzeBtn');
            if (analyzeBtn) {
                analyzeBtn.disabled = false;
            }

            showToast('视频已选择，请点击"开始分析"按钮', 'info');

        } catch (error) {
            showToast(error.message, 'error');
        }
    }

    async upload() {
        if (!this.file) return;

        // 显示上传进度
        const progressContainer = this.container.querySelector('#uploadProgress');
        const progressBar = this.container.querySelector('#progressBar');
        const progressPercent = this.container.querySelector('#progressPercent');

        if (progressContainer) {
            progressContainer.classList.remove('hidden');
        }

        try {
            const { uploadVideo: apiUploadVideo } = await import('../api/client.js');

            // 模拟上传进度
            let progress = 0;
            const progressInterval = setInterval(() => {
                progress += 10;
                if (progress > 90) {
                    clearInterval(progressInterval);
                }
                if (progressBar) progressBar.style.width = `${progress}%`;
                if (progressPercent) progressPercent.textContent = `${progress}%`;
            }, 200);

            const result = await apiUploadVideo(this.file);

            clearInterval(progressInterval);

            // 完成上传
            if (progressBar) progressBar.style.width = '100%';
            if (progressPercent) progressPercent.textContent = '100%';

            setTimeout(() => {
                if (progressContainer) progressContainer.classList.add('hidden');
                this.options.onUploadSuccess(result);
            }, 500);

        } catch (error) {
            console.error('上传失败:', error);
            if (progressContainer) progressContainer.classList.add('hidden');

            // 重置进度条
            if (progressBar) progressBar.style.width = '0%';
            if (progressPercent) progressPercent.textContent = '0%';

            // 显示错误提示
            showToast(error.message || '上传失败', 'error');

            // 重新抛出错误，让调用方处理
            throw error;
        }
    }

    reset() {
        this.file = null;
        if (this.previewUrl) {
            URL.revokeObjectURL(this.previewUrl);
            this.previewUrl = null;
        }

        this.container.querySelector('#fileInput').value = '';
        this.container.querySelector('#uploadPrompt').classList.remove('hidden');
        this.container.querySelector('#previewArea').classList.add('hidden');

        // 禁用主应用的分析按钮
        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn) {
            analyzeBtn.disabled = true;
        }
    }

    destroy() {
        if (this.previewUrl) {
            URL.revokeObjectURL(this.previewUrl);
        }
        this.container.innerHTML = '';
    }
}

/**
 * Toast 提示 - 深色主题风格
 */
export function showToast(message, type = 'info', duration = 3000) {
    // 移除现有 toast
    const existingToast = document.querySelector('.toast-container');
    if (existingToast) {
        existingToast.remove();
    }

    const container = document.createElement('div');
    container.className = 'toast-container';
    container.style.cssText = `
        position: fixed;
        top: 16px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 100;
        display: flex;
        justify-content: center;
    `;

    const toast = document.createElement('div');
    const bgColors = {
        success: 'linear-gradient(135deg, #34D399 0%, #10B981 100%)',
        error: 'linear-gradient(135deg, #F87171 0%, #EF4444 100%)',
        warning: 'linear-gradient(135deg, #FBBF24 0%, #F59E0B 100%)',
        info: 'linear-gradient(135deg, #2F7CF6 0%, #5B9FFF 100%)',
    };
    toast.style.cssText = `
        padding: 14px 20px;
        border-radius: 14px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
        color: white;
        font-size: 15px;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 10px;
        background: ${bgColors[type] || bgColors.info};
        animation: slideIn 0.3s ease-out;
    `;

    // 添加图标
    const icons = {
        success: '<svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>',
        error: '<svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>',
        warning: '<svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>',
        info: '<svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
    };

    toast.innerHTML = `${icons[type] || icons.info}<span>${message}</span>`;
    container.appendChild(toast);
    document.body.appendChild(container);

    // 添加动画样式
    if (!document.getElementById('toast-animation-style')) {
        const style = document.createElement('style');
        style.id = 'toast-animation-style';
        style.textContent = `
            @keyframes toastSlideIn {
                from { transform: translateY(-12px); opacity: 0; }
                to{ transform: translateY(0); opacity: 1; }
            }
            @keyframes toastSlideOut {
                from{ transform: translateY(0); opacity: 1; }
                to{ transform: translateY(-12px); opacity: 0; }
            }
            .toast-enter { animation: toastSlideIn 0.3s ease-out; }
            .toast-exit { animation: toastSlideOut 0.3s ease-in forwards; }
        `;
        document.head.appendChild(style);
    }

    toast.classList.add('toast-enter');

    setTimeout(() => {
        toast.classList.remove('toast-enter');
        toast.classList.add('toast-exit');
        setTimeout(() => container.remove(), 300);
    }, duration);
}
