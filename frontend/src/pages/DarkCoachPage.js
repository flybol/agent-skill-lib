/**
 * 深色系高端移动端页面 - 乒乓球 AI 教练分析
 * 专业训练工具风格
 */

import { showToast } from '../components/VideoUploader.js';

export class DarkCoachPage {
    constructor(container) {
        this.container = typeof container === 'string'
            ? document.querySelector(container)
            : container;
        this.selectedFile = null;
        this.isAnalyzing = false;
        this.init();
    }

    init() {
        this.render();
        this.bindEvents();
    }

    render() {
        this.container.innerHTML = `
            <div class="dark-coach-page" style="background: var(--bg-primary); min-height: 100vh;">
                <!-- 顶部导航栏 -->
                <header class="dark-header" style="
                    position: sticky;
                    top: 0;
                    z-index: 50;
                    background: rgba(14, 17, 23, 0.85);
                    backdrop-filter: blur(20px);
                    -webkit-backdrop-filter: blur(20px);
                    border-bottom: 1px solid var(--divider);
                    padding: 12px 16px;
                ">
                    <div style="display: flex; align-items: center; justify-content: space-between;">
                        <!-- 返回按钮 -->
                        <button class="icon-btn" onclick="history.back()">
                            <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
                            </svg>
                        </button>

                        <!-- 标题 -->
                        <h1 style="
                            font-size: 16px;
                            font-weight: 600;
                            color: var(--text-primary);
                            letter-spacing: -0.02em;
                        ">乒乓数字教练 v1.0</h1>

                        <!-- 更多操作 -->
                        <button class="icon-btn">
                            <svg width="20" height="20" fill="currentColor" viewBox="0 0 24 24">
                                <circle cx="12" cy="5" r="2"/>
                                <circle cx="12" cy="12" r="2"/>
                                <circle cx="12" cy="19" r="2"/>
                            </svg>
                        </button>
                    </div>

                    <!-- 说明文字 -->
                    <p style="
                        text-align: center;
                        font-size: 13px;
                        color: var(--text-secondary);
                        margin-top: 8px;
                        padding: 0 20px;
                    ">上传训练视频，生成 AI 教练报告</p>
                </header>

                <!-- 主内容区 -->
                <main style="padding: 16px;">
                    <!-- 核心操作卡片 -->
                    <section class="card-dark fade-in" style="margin-bottom: 16px;">
                        <!-- 模块标题 -->
                        <div style="margin-bottom: 16px;">
                            <h2 class="text-heading" style="margin-bottom: 4px;">上传训练视频</h2>
                            <p class="text-caption">支持 MP4、MOV 格式，最大 5.5 秒，最大 20MB</p>
                        </div>

                        <!-- 上传区域 -->
                        <div id="uploadArea" class="upload-area" style="margin-bottom: 16px;">
                            <!-- 云上传图标 -->
                            <div style="margin-bottom: 12px;">
                                <svg width="48" height="48" fill="none" style="color: var(--primary);" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
                                </svg>
                            </div>
                            <p class="text-caption" style="margin-bottom: 4px;">点击或拖拽上传视频文件</p>
                            <p class="text-small">支持 MP4、MOV 格式</p>

                            <!-- 预览区域（初始隐藏） -->
                            <div id="previewArea" style="display: none; margin-top: 16px;">
                                <video id="videoPreview" style="width: 100%; border-radius: 12px; margin-bottom: 12px;" controls></video>
                                <p id="fileInfo" class="text-caption"></p>
                            </div>
                        </div>

                        <!-- 选择文件按钮 -->
                        <div style="display: flex; gap: 12px; margin-bottom: 20px;">
                            <button id="selectFileBtn" class="btn-secondary" style="flex: 1;">
                                选择文件
                            </button>
                            <input type="file" id="fileInput" accept="video/mp4,video/quicktime" style="display: none;">
                        </div>

                        <!-- 主行动按钮 -->
                        <button id="analyzeBtn" class="btn-primary" style="width: 100%; font-size: 17px;" disabled>
                            🚀 开始分析
                        </button>
                    </section>

                    <!-- 分割线 -->
                    <div class="divider"></div>

                    <!-- 分析结果模块 -->
                    <section class="fade-in" style="animation-delay: 0.1s;">
                        <h2 class="text-heading" style="margin-bottom: 8px;">训练结果</h2>
                        <p class="text-caption" style="margin-bottom: 16px;">AI 分析报告：为您列出 3 个问题与 3 个改进措施</p>

                        <!-- 结果列表 -->
                        <div id="resultList" style="
                            background: var(--bg-card);
                            border-radius: var(--radius-xl);
                            border: 1px solid var(--divider);
                            overflow: hidden;
                        ">
                            <!-- 占位状态 -->
                            <div id="resultPlaceholder" style="padding: 40px 20px; text-align: center;">
                                <svg width="48" height="48" fill="none" style="color: var(--text-muted); margin: 0 auto 12px;" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                                </svg>
                                <p class="text-caption" style="color: var(--text-tertiary);">等待分析完成...</p>
                            </div>

                            <!-- 分析进度（初始隐藏） -->
                            <div id="analyzingState" style="display: none; padding: 32px 20px; text-align: center;">
                                <div style="width: 32px; height: 32px; margin: 0 auto 16px; border: 3px solid var(--bg-elevated); border-top-color: var(--primary); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
                                <p class="text-body" style="color: var(--text-secondary);">AI 正在分析中...</p>
                                <p class="text-small" style="margin-top: 4px; color: var(--text-tertiary);">预计需要 10~15 秒</p>
                            </div>

                            <!-- 结果内容（初始隐藏） -->
                            <div id="resultContent" style="display: none;">
                                <!-- 动态填充 -->
                            </div>
                        </div>
                    </section>
                </main>

                <!-- 底部安全区域 -->
                <div class="safe-bottom" style="height: 20px;"></div>
            </div>

            <style>
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
            </style>
        `;
    }

    bindEvents() {
        const uploadArea = this.container.querySelector('#uploadArea');
        const fileInput = this.container.querySelector('#fileInput');
        const selectFileBtn = this.container.querySelector('#selectFileBtn');
        const analyzeBtn = this.container.querySelector('#analyzeBtn');

        // 点击上传区域
        uploadArea.addEventListener('click', () => {
            fileInput.click();
        });

        // 点击选择文件按钮
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

        // 开始分析
        analyzeBtn.addEventListener('click', () => {
            this.startAnalysis();
        });
    }

    handleFileSelect(file) {
        // 验证文件
        const validTypes = ['video/mp4', 'video/quicktime'];
        if (!validTypes.includes(file.type)) {
            showToast('请选择 MP4 或 MOV 格式的视频', 'error');
            return;
        }

        if (file.size > 10 * 1024 * 1024) {
            showToast('视频文件不能超过 10MB', 'error');
            return;
        }

        this.selectedFile = file;

        // 显示预览
        const previewArea = this.container.querySelector('#previewArea');
        const videoPreview = this.container.querySelector('#videoPreview');
        const fileInfo = this.container.querySelector('#fileInfo');
        const analyzeBtn = this.container.querySelector('#analyzeBtn');

        videoPreview.src = URL.createObjectURL(file);
        fileInfo.textContent = `${file.name} (${this.formatFileSize(file.size)})`;
        previewArea.style.display = 'block';
        analyzeBtn.disabled = false;

        showToast('视频已选择', 'success');
    }

    async startAnalysis() {
        if (!this.selectedFile || this.isAnalyzing) return;

        this.isAnalyzing = true;

        // 显示分析状态
        this.container.querySelector('#resultPlaceholder').style.display = 'none';
        this.container.querySelector('#analyzingState').style.display = 'block';
        this.container.querySelector('#analyzeBtn').disabled = true;
        this.container.querySelector('#analyzeBtn').textContent = '分析中...';

        // 模拟分析过程
        await this.simulateAnalysis();

        // 显示结果
        this.showResults();
    }

    async simulateAnalysis() {
        return new Promise(resolve => {
            setTimeout(() => {
                resolve();
            }, 3000);
        });
    }

    showResults() {
        const resultContent = this.container.querySelector('#resultContent');
        const analyzingState = this.container.querySelector('#analyzingState');

        analyzingState.style.display = 'none';
        resultContent.style.display = 'block';

        resultContent.innerHTML = `
            <div style="padding: 20px;">
                <div style="padding-bottom: 12px; margin-bottom: 12px; border-bottom: 1px solid var(--divider);">
                    <p class="text-caption" style="color: var(--primary); font-weight: 500;">分析完成</p>
                    <p class="text-heading" style="margin-top: 4px;">综合评分: <span style="color: var(--success); font-size: 24px; font-weight: 600;">78</span></p>
                </div>

                <!-- 发现的问题 -->
                <div style="margin-bottom: 20px;">
                    <p class="text-caption" style="margin-bottom: 12px; color: var(--warning);">发现 3 个问题</p>

                    <div class="checklist-item">
                        <div class="checklist-icon" style="background: var(--warning-bg);">
                            <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                            </svg>
                        </div>
                        <div class="checklist-text">
                            <p class="checklist-title">反手击球力度不足</p>
                            <p class="checklist-desc">手腕力量需要加强，建议每天进行专项练习</p>
                        </div>
                    </div>

                    <div class="checklist-item">
                        <div class="checklist-icon" style="background: var(--warning-bg);">
                            <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                            </svg>
                        </div>
                        <div class="checklist-text">
                            <p class="checklist-title">步伐移动不够灵活</p>
                            <p class="checklist-desc">左右移动时重心偏高，影响反应速度</p>
                        </div>
                    </div>

                    <div class="checklist-item">
                        <div class="checklist-icon" style="background: var(--warning-bg);">
                            <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                            </svg>
                        </div>
                        <div class="checklist-text">
                            <p class="checklist-title">击球时机偏晚</p>
                            <p class="checklist-desc">需要提高预判能力，提前做好击球准备</p>
                        </div>
                    </div>
                </div>

                <!-- 改进建议 -->
                <div>
                    <p class="text-caption" style="margin-bottom: 12px; color: var(--success);">改进措施</p>

                    <div class="checklist-item">
                        <div class="checklist-icon">
                            <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                            </svg>
                        </div>
                        <div class="checklist-text">
                            <p class="checklist-title">加强手腕力量训练</p>
                            <p class="checklist-desc">使用握力器每天练习 3 组，每组 20 次</p>
                        </div>
                    </div>

                    <div class="checklist-item">
                        <div class="checklist-icon">
                            <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                            </svg>
                        </div>
                        <div class="checklist-text">
                            <p class="checklist-title">练习低重心移动</p>
                            <p class="checklist-desc">半蹲姿势左右滑步，保持膝盖微曲状态</p>
                        </div>
                    </div>

                    <div class="checklist-item">
                        <div class="checklist-icon">
                            <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                            </svg>
                        </div>
                        <div class="checklist-text">
                            <p class="checklist-title">提高预判反应速度</p>
                            <p class="checklist-desc">通过多球训练练习快速判断球的落点</p>
                        </div>
                    </div>
                </div>
            </div>
        `;

        this.isAnalyzing = false;
        this.container.querySelector('#analyzeBtn').textContent = '🚀 重新分析';
        this.container.querySelector('#analyzeBtn').disabled = false;

        showToast('分析完成', 'success');
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    destroy() {
        this.container.innerHTML = '';
    }
}
