/**
 * AI 乒乓球教练 - 主应用入口
 * 整合所有组件，处理完整交互流程
 */

import './styles/theme-dark.css';
import { VideoUploader, showToast } from './components/VideoUploader.js';
import { TaskQueue, TaskStatusIndicator } from './components/TaskQueue.js';
import { AnalysisResult } from './components/AnalysisResult.js';
import { AnalysisStatus } from './components/AnalysisStatus.js';
import { TaskHistory } from './components/TaskHistory.js';
import { Drawer } from './components/Drawer.js';
import { TargetPlayerConfirm } from './components/TargetPlayerConfirm.js';
import {
    uploadVideo,
    startAnalysis as startAnalysisAPI,
    getAnalysisResult,
    getHistoryTasks,
    getTaskQueue,
    deleteTask,
    shareTask,
    connectTaskWebSocket,
    API_BASE_URL,
} from './api/client.js';
import { formatTime, copyToClipboard } from './utils/helpers.js';
import { wechatShareManager } from './utils/wechatShare.js';
import { getOrCreateUserId } from './utils/userCookie.js';

// HTML 转义辅助函数，防止 XSS 和显示问题
function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

// 安全显示文本内容的辅助函数
function safeText(text) {
    if (text === null || text === undefined) return '';
    return String(text);
}

class App {
    constructor() {
        this.currentTask = null;
        this.wsConnection = null;
        this.drawer = new Drawer({ position: 'right' });
        this.userId = null; // 用户标识
        this.init();
    }

    init() {
        // 首先检查 cookie 支持并获取用户标识
        const cookieResult = getOrCreateUserId();
        if (cookieResult.error) {
            // Cookie 不支持，显示错误提示
            this.renderCookieError(cookieResult.error);
            return;
        }
        this.userId = cookieResult.userId;

        this.render();
        this.initComponents();
        this.bindEvents();
        this.loadInitialData();
    }

    renderCookieError(errorMessage) {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div style="
                background: var(--bg-primary);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            ">
                <div style="
                    background: var(--bg-card);
                    border-radius: 16px;
                    padding: 32px 24px;
                    max-width: 400px;
                    text-align: center;
                    border: 1px solid var(--divider);
                ">
                    <div style="
                        width: 48px;
                        height: 48px;
                        margin: 0 auto 20px;
                        background: var(--error, #ef4444);
                        border-radius: 50%;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                    ">
                        <svg width="24" height="24" fill="none" stroke="white" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </div>
                    <h2 style="
                        font-size: 18px;
                        font-weight: 600;
                        color: var(--text-primary);
                        margin-bottom: 12px;
                    ">无法访问应用</h2>
                    <p style="
                        font-size: 14px;
                        color: var(--text-secondary);
                        line-height: 1.6;
                        margin-bottom: 8px;
                    ">${errorMessage}</p>
                    <p style="
                        font-size: 13px;
                        color: var(--text-tertiary);
                        line-height: 1.5;
                    ">请在浏览器设置中允许使用 cookie，然后刷新页面重试。</p>
                </div>
            </div>
        `;
    }

    render() {
        const app = document.getElementById('app');
        app.innerHTML = `
            <div style="background: var(--bg-primary); min-height: 100vh;">
                <!-- 顶部导航栏 - 毛玻璃效果 -->
                <header style="
                    position: sticky;
                    top: 0;
                    z-index: 50;
                    background: rgba(14, 17, 23, 0.85);
                    backdrop-filter: blur(20px);
                    -webkit-backdrop-filter: blur(20px);
                    border-bottom: 1px solid var(--divider);
                    padding: 12px 16px;
                ">
                    <div style="max-width: 480px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between;">
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
                        <button class="icon-btn" id="historyToggleBtn">
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
                    ">上传训练视频，生成 AI 教练报告</p>
                </header>

                <!-- 主内容区 -->
                <main style="max-width: 480px; margin: 0 auto; padding: 16px;">
                    <!-- 核心操作卡片 -->
                    <section class="card-dark fade-in" style="margin-bottom: 16px;">
                        <!-- 模块标题 -->
                        <div style="margin-bottom: 16px;">
                            <h2 style="font-size: 16px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px;">上传训练视频</h2>
                            <p style="font-size: 13px; color: var(--text-secondary);">支持 MP4、MOV 格式，最大 5 秒，最大 20MB</p>
                        </div>

                        <!-- 视频上传组件容器 -->
                        <div id="videoUploaderContainer"></div>

                        <!-- 当前任务状态 -->
                        <div id="currentTaskSection" class="hidden" style="margin-top: 20px;">
                            <h3 style="font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 12px;">当前任务</h3>
                            <div id="taskStatusContainer"></div>
                        </div>

                        <!-- 目标球员确认模块 -->
                        <div id="targetPlayerConfirmContainer" style="margin-top: 16px;"></div>

                        <!-- 主行动按钮 -->
                        <button id="analyzeBtn" class="btn-primary" style="width: 100%; margin-top: 16px; font-size: 17px;" disabled>
                            🚀 开始分析
                        </button>
                    </section>

                    <!-- 分析状态组件 -->
                    <section style="margin-top: 16px;">
                        <div id="analysisStatusContainer"></div>
                    </section>

                    <!-- 分析结果模块 -->
                    <section id="trainingResultSection" class="hidden fade-in" style="animation-delay: 0.1s;">
                        <h2 style="font-size: 16px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px;">训练结果</h2>
                        <p style="font-size: 13px; color: var(--text-secondary); margin-bottom: 16px;">AI 分析报告：为您列出 3 个问题与 3 个改进措施</p>

                        <!-- 分析结果容器 -->
                        <div id="analysisResultContainer" style="
                            background: var(--bg-card);
                            border-radius: var(--radius-xl);
                            border: 1px solid var(--divider);
                            overflow: hidden;
                        "></div>
                    </section>

                    <!-- 任务队列页面（隐藏） -->
                    <div id="queuePage" class="page hidden">
                        <h2 style="font-size: 16px; font-weight: 600; color: var(--text-primary); margin-bottom: 16px;">任务队列</h2>
                        <div id="taskQueueContainer"></div>
                    </div>
                </main>

                <!-- 底部安全区域 -->
                <div class="safe-bottom" style="height: 20px;"></div>
            </div>
        `;
    }

    initComponents() {
        // 视频上传组件
        this.videoUploader = new VideoUploader('#videoUploaderContainer', {
            onFileSelect: (file) => {
                this.handleFileSelect(file);
            },
            onUploadSuccess: (result) => {
                this.handleUploadSuccess(result);
            },
        });

        // 目标球员确认组件
        this.targetPlayerConfirm = new TargetPlayerConfirm('#targetPlayerConfirmContainer');

        // 任务状态指示器
        this.taskStatusIndicator = new TaskStatusIndicator('#taskStatusContainer');

        // 分析结果组件
        this.analysisResult = new AnalysisResult('#analysisResultContainer', {
            onShare: (result) => this.handleShare(result),
            onDownload: (result) => this.handleDownload(result),
            onReanalyze: () => this.handleReanalyze(),
        });

        // 分析状态组件
        this.analysisStatus = new AnalysisStatus('#analysisStatusContainer', {
            onComplete: (data) => {
                console.log('分析完成:', data);
                // 延迟隐藏状态组件，让用户看到完成状态
                setTimeout(() => {
                    this.analysisStatus.hide();
                }, 1500);
            },
            onFailed: (data) => {
                console.error('分析失败:', data);
                // 失败状态保持显示，不自动隐藏
            },
        });

        // 任务队列组件（禁用自动刷新，使用 WebSocket 实时更新）
        this.taskQueue = new TaskQueue('#taskQueueContainer', {
            autoRefresh: false,  // 已使用 WebSocket 实时推送，无需轮询
            onTaskClick: (taskId) => this.handleTaskClick(taskId),
        });

        // 历史任务（在 Drawer 中）
        this.taskHistory = null;

        // 初始化分析结果占位状态
        this.analysisResult.showEmpty();
    }

    bindEvents() {
        // 历史记录按钮
        const historyBtn = document.getElementById('historyToggleBtn');
        if (historyBtn) {
            historyBtn.addEventListener('click', async () => {
                await this.toggleHistoryDrawer();
            });
        }

        // 开始分析按钮 - 确保正确绑定，避免 iOS Safari 兼容性问题
        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn) {
            // 使用 touchstart 和 click 确保在 iOS 上也能触发
            analyzeBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (this.currentTask) {
                    await this.startAnalysis();
                }
            });
        } else {
            console.error('[bindEvents] analyzeBtn 没有找到，请检查 DOM 是否已渲染');
        }
    }

    handleFileSelect(file) {
        // 文件选择后会自动上传，此回调保留用于其他可能的扩展
        console.log('文件已选择，正在自动上传...');
    }

    async startAnalysis() {
        if (!this.currentTask) return;

        // 获取用户选择的球员位置
        const choice = this.targetPlayerConfirm.getChoice();
        this.selectedTargetPlayer = choice;

        // 更新按钮状态
        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn) {
            analyzeBtn.textContent = '分析中...';
            analyzeBtn.disabled = true;
        }

        // 清空分析结果容器
        const resultContainer = document.getElementById('analysisResultContainer');
        if (resultContainer) {
            resultContainer.innerHTML = '';
        }

        // 使用 AnalysisStatus 组件显示分析进度
        if (this.analysisStatus) {
            this.analysisStatus.update({
                status: 'queued',
                stage: '正在准备分析...',
                progress: 5
            });
        }

        // 连接 WebSocket 接收实时更新
        this.connectWebSocket(this.currentTask.task_id);

        // 开始分析，传递用户选择的目标球员
        try {
            await startAnalysisAPI(this.currentTask.task_id, choice);
        } catch (error) {
            console.error('启动分析失败:', error);
            // 分析失败，重置按钮和状态
            if (analyzeBtn) {
                analyzeBtn.textContent = '🚀 开始分析';
                analyzeBtn.disabled = false;
            }
            if (this.analysisStatus) {
                this.analysisStatus.update({
                    status: 'failed',
                    stage: error.message || '分析启动失败',
                    progress: 0
                });
            }
        }
    }

    switchPage(pageName) {
        // 深色版本不需要页面切换，保留兼容性
    }

    async loadInitialData() {
        try {
            // 初始化微信分享（如果在微信环境）
            if (typeof wx !== 'undefined') {
                try {
                    const initialized = await wechatShareManager.init();
                    if (initialized) {
                        console.log('微信 JS-SDK 初始化完成');
                        // 设置默认分享内容
                        wechatShareManager.setShareData({
                            title: '🏓 AI乒乓球教练 - 智能技术分析',
                            link: window.location.href.split('#')[0],
                            imgUrl: window.location.origin + '/share-cover.jpg',
                            desc: '上传训练视频，AI教练为您生成专业分析报告'
                        });
                    }
                } catch (error) {
                    console.error('微信 JS-SDK 初始化失败:', error);
                }
            }

            // 加载历史任务数据
            const historyData = await getHistoryTasks(1, 20);
            console.log('已加载历史任务:', historyData);

            // 检查 URL 中是否有 task_id 参数，如果有则自动加载该任务的分析结果
            const urlParams = new URLSearchParams(window.location.search);
            const taskId = urlParams.get('task_id');
            if (taskId) {
                console.log('检测到 URL 中的 task_id:', taskId);
                await this.loadSharedResult(taskId);
            }
        } catch (error) {
            console.error('加载初始数据失败:', error);
        }
    }

    /**
     * 加载分享的分析结果
     * 用于通过链接直接查看他人的分析报告
     */
    async loadSharedResult(taskId) {
        try {
            // 设置当前任务
            this.currentTask = { task_id: taskId };
            this.analysisResult.showLoading();
            const result = await getAnalysisResult(taskId);

            if (result && result.status === 'completed') {
                // 确保 result 有必要的字段
                if (!result.summary) result.summary = {};
                if (!result.suggestions) result.suggestions = [];
                if (!result.details) result.details = {};

                // 从 result 中提取目标球员信息并设置
                if (result.target_player) {
                    const autoPick = result.target_player.auto_pick || result.target_player;
                    this.selectedTargetPlayer = autoPick;
                    // 更新下拉选择器的值
                    this.targetPlayerConfirm.selectedChoice = autoPick;
                    const select = document.getElementById('playerPositionSelect');
                    if (select) {
                        select.value = autoPick;
                    }
                }

                // 恢复历史任务的视频
                const videoUrl = `${API_BASE_URL}/videos/${taskId}`;
                const fileName = result.name || `训练视频_${taskId}`;
                this.videoUploader.setVideoByUrl(videoUrl, fileName);

                // 显示分享的结果
                this.displayAnalysisResult(result);

                // 显示提示消息
                showToast('正在查看分享的分析结果', 'info');
            } else {
                this.analysisResult.showEmpty();
                this.hideTrainingResult();
                showToast('该分析结果不存在或未完成', 'error');
            }
        } catch (error) {
            console.error('加载分享结果失败:', error);
            this.analysisResult.showEmpty();
            this.hideTrainingResult();
            showToast('加载分享结果失败: ' + error.message, 'error');
        }
    }

    async handleUploadSuccess(result) {
        this.currentTask = result.task;

        // 清空之前的分析结果（防止分享旧结果）
        this.analysisResult.showEmpty();
        this.hideTrainingResult();

        // 清空 main.js 中直接渲染的结果容器
        const resultContainer = document.getElementById('analysisResultContainer');
        if (resultContainer) {
            resultContainer.innerHTML = '';
        }

        // 重置按钮状态
        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn) {
            analyzeBtn.textContent = '🚀 开始分析';
            analyzeBtn.disabled = false;
        }

        showToast('视频上传成功，请点击"开始分析"按钮', 'info');
    }

    showPreprocessProgress() {
        const resultContainer = document.getElementById('analysisResultContainer');
        if (!resultContainer) return;

        resultContainer.innerHTML = `
            <div style="padding: 32px 20px; text-align: center;">
                <div style="
                    width: 32px;
                    height: 32px;
                    margin: 0 auto 16px;
                    border: 3px solid var(--bg-elevated);
                    border-top-color: var(--primary);
                    border-radius: 50%;
                    animation: spin 0.8s linear infinite;
                "></div>
                <p style="font-size: 15px; color: var(--text-secondary);">正在检测运动员...</p>
                <p style="font-size: 12px; color: var(--text-tertiary); margin-top: 4px;">
                    分析视频中...
                </p>
            </div>
            <style>
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
            </style>
        `;
    }

    showAnalysisProgress() {
        const resultContainer = document.getElementById('analysisResultContainer');
        if (!resultContainer) return;

        resultContainer.innerHTML = `
            <div style="padding: 32px 20px; text-align: center;">
                <!-- 加载动画 -->
                <div style="
                    width: 48px;
                    height: 48px;
                    margin: 0 auto 20px;
                    border: 4px solid var(--bg-elevated);
                    border-top-color: var(--primary);
                    border-radius: 50%;
                    animation: spin 0.8s linear infinite;
                "></div>

                <!-- 状态标题 -->
                <p id="analysisStatus" style="font-size: 16px; font-weight: 500; color: var(--text-primary); margin-bottom: 8px;">
                    AI 正在分析中...
                </p>

                <!-- 当前阶段 -->
                <p id="analysisStage" style="font-size: 14px; color: var(--text-secondary); margin-bottom: 20px;">
                    视频抽帧中...
                </p>

                <!-- 进度条 -->
                <div style="max-width: 280px; margin: 0 auto;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span style="font-size: 12px; color: var(--text-tertiary);">分析进度</span>
                        <span id="analysisProgress" style="font-size: 14px; font-weight: 600; color: var(--primary);">0%</span>
                    </div>
                    <div style="
                        height: 8px;
                        background: var(--bg-elevated);
                        border-radius: 10px;
                        overflow: hidden;
                    ">
                        <div id="analysisProgressBar" style="
                            height: 100%;
                            width: 0%;
                            background: linear-gradient(90deg, var(--primary), #60a5fa);
                            border-radius: 10px;
                            transition: width 0.3s ease;
                        "></div>
                    </div>
                </div>

                <!-- 提示信息 -->
                <p style="font-size: 12px; color: var(--text-tertiary); margin-top: 16px;">
                    预计需要 10~15 秒
                </p>
            </div>
            <style>
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
            </style>
        `;
    }

    showMockResults() {
        // 模拟数据结构
        const mockResult = {
            task_id: 'mock-task',
            overall_score: 78,
            summary: {
                overview: '您的乒乓球动作整体表现良好，正手击球稳定性较高，但反手位需要加强练习。',
                weaknesses: [
                    { title: '反手击球力度不足', description: '手腕力量需要加强，建议每天进行专项练习' },
                    { title: '步伐移动不够灵活', description: '左右移动时重心偏高，影响反应速度' },
                    { title: '击球时机偏晚', description: '需要提高预判能力，提前做好击球准备' },
                ],
            },
            suggestions: [
                { title: '加强手腕力量训练', description: '使用握力器每天练习 3 组，每组 20 次' },
                { title: '练习低重心移动', description: '半蹲姿势左右滑步，保持膝盖微曲状态' },
                { title: '提高预判反应速度', description: '通过多球训练练习快速判断球的落点' },
            ],
        };

        // 使用通用的渲染方法
        this.displayAnalysisResult(mockResult);
        showToast('分析完成！', 'success');
    }

    getMockResult() {
        return {
            task_id: 'mock-task',
            overall_score: 78,
            summary: {
                overview: '您的乒乓球动作整体表现良好，正手击球稳定性较高，但反手位需要加强练习。',
                weaknesses: [
                    { title: '反手击球力度不足', description: '手腕力量需要加强，建议每天进行专项练习' },
                    { title: '步伐移动不够灵活', description: '左右移动时重心偏高，影响反应速度' },
                    { title: '击球时机偏晚', description: '需要提高预判能力，提前做好击球准备' },
                ],
            },
            suggestions: [
                { title: '加强手腕力量训练', description: '使用握力器每天练习 3 组，每组 20 次' },
                { title: '练习低重心移动', description: '半蹲姿势左右滑步，保持膝盖微曲状态' },
                { title: '提高预判反应速度', description: '通过多球训练练习快速判断球的落点' },
            ],
        };
    }

    connectWebSocket(taskId) {
        // 关闭之前的连接
        if (this.wsConnection) {
            this.wsConnection.close();
        }

        try {
            this.wsConnection = connectTaskWebSocket(
                taskId,
                (data) => this.handleWebSocketMessage(data),
                (error) => console.error('WebSocket 错误:', error)
            );
        } catch (error) {
            console.error('WebSocket 连接失败:', error);
        }
    }

    handleWebSocketMessage(data) {
        console.log('[WebSocket] 收到状态更新:', data);
        console.log('[WebSocket] analysisStatus 存在?', !!this.analysisStatus);

        // 使用 AnalysisStatus 组件显示状态
        if (this.analysisStatus) {
            console.log('[WebSocket] 调用 analysisStatus.update');
            this.analysisStatus.update(data);
        } else {
            console.warn('[WebSocket] analysisStatus 不存在!');
        }

        // 分析完成，获取结果
        if (data.status === 'completed') {
            this.loadAnalysisResult(data.task_id || this.currentTask?.task_id);
        }

        // 分析失败
        if (data.status === 'failed') {
            showToast('分析失败: ' + (data.error || '未知错误'), 'error');
            const analyzeBtn = document.getElementById('analyzeBtn');
            if (analyzeBtn) {
                analyzeBtn.textContent = '🚀 开始分析';
                analyzeBtn.disabled = false;
            }
        }

        // 更新当前任务状态
        if (this.currentTask && data.task_id === this.currentTask.task_id) {
            this.currentTask.status = data.status;
            this.currentTask.progress = data.progress;
            this.currentTask.stage = data.stage;
        }
    }

    async handleTaskClick(taskId) {
        try {
            this.currentTask = { task_id: taskId };
            this.analysisResult.showLoading();

            const result = await getAnalysisResult(taskId);

            if (result && result.status === 'completed') {
                // 确保 result 有必要的字段
                if (!result.summary) result.summary = {};
                if (!result.suggestions) result.suggestions = [];
                if (!result.details) result.details = {};

                // 从 result 中提取目标球员信息（用于显示标签）
                if (result.target_player) {
                    const autoPick = result.target_player.auto_pick || result.target_player;
                    this.selectedTargetPlayer = autoPick;
                }

                // 显示历史任务的视频
                const videoUrl = `${API_BASE_URL}/videos/${taskId}`;
                const fileName = result.name || `训练视频_${taskId}`;
                this.videoUploader.setVideoByUrl(videoUrl, fileName);

                // 使用深色主题的 displayAnalysisResult 方法显示结果
                this.displayAnalysisResult(result);

                // 更新 URL（便于分享）
                const newUrl = `${window.location.pathname}?task_id=${taskId}`;
                window.history.pushState({ taskId }, '', newUrl);

                // 关闭抽屉（如果在抽屉中）
                this.drawer.close();

                // 滚动到结果区域
                setTimeout(() => {
                    const resultContainer = document.getElementById('analysisResultContainer');
                    if (resultContainer) {
                        resultContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                }, 100);

                showToast('已加载历史任务详情', 'success');
            } else if (result && result.status === 'failed') {
                this.analysisResult.showEmpty();
                this.hideTrainingResult();
                showToast('该任务分析失败: ' + (result.error || '未知错误'), 'error');
            } else {
                this.analysisResult.showEmpty();
                this.hideTrainingResult();
                showToast('该任务尚未完成', 'info');
            }
        } catch (error) {
            console.error('获取任务结果失败:', error);
            this.analysisResult.showEmpty();
            this.hideTrainingResult();
            showToast('获取任务结果失败: ' + error.message, 'error');
        }
    }

    async loadAnalysisResult(taskId) {
        try {
            const result = await getAnalysisResult(taskId);
            if (result && result.status === 'completed') {
                this.displayAnalysisResult(result);
                showToast('分析完成！', 'success');
            }
        } catch (error) {
            console.error('获取分析结果失败:', error);
            showToast('获取分析结果失败', 'error');
        }
    }

    displayAnalysisResult(result) {
        const resultContainer = document.getElementById('analysisResultContainer');
        if (!resultContainer) return;

        // 显示训练结果部分
        const trainingResultSection = document.getElementById('trainingResultSection');
        if (trainingResultSection) {
            trainingResultSection.classList.remove('hidden');
        }

        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn) {
            analyzeBtn.textContent = '重新分析';
            analyzeBtn.disabled = false;
        }

        // 新数据格式：coach_comment + problems + suggestions
        const coachComment = result.coach_comment || {};
        const overallScore = result.overall_score || result.score || 0;
        const problems = result.problems || [];
        const suggestions = result.suggestions || [];

        // 更新微信分享内容（如果在微信环境）
        this.updateWeChatShare(result);

        // 获取球员方向显示文本
        const getPlayerLabel = () => {
            if (this.selectedTargetPlayer === 'left') return '左侧球员';
            if (this.selectedTargetPlayer === 'right') return '右侧球员';
            if (this.selectedTargetPlayer === 'single_player') return '';
            return '';
        };

        const playerLabel = getPlayerLabel();

        resultContainer.innerHTML = `
            <div style="padding: 20px;">
                <!-- 分析完成头部 -->
                <div style="padding-bottom: 12px; margin-bottom: 16px; border-bottom: 1px solid var(--divider);">
                    <p style="font-size: 13px; color: var(--success); font-weight: 500;">分析完成</p>
                    <p style="font-size: 16px; font-weight: 600; color: var(--text-primary); margin-top: 4px;">
                        ${playerLabel ? playerLabel + ' ' : ''}综合评分: <span style="color: var(--success); font-size: 24px; font-weight: 600;">${overallScore}</span>
                    </p>
                </div>

                <!-- 教练评语 -->
                ${coachComment.summary || coachComment.weaknesses || coachComment.strengths ? `
                <div style="margin-bottom: 24px; padding: 16px; background: var(--bg-elevated); border-radius: 12px; border: 1px solid var(--divider);">
                    <h3 style="font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 12px;">教练评语</h3>

                    ${safeText(coachComment.strengths) ? `
                    <div style="margin-bottom: 12px;">
                        <p style="font-size: 13px; color: var(--success); font-weight: 500; margin-bottom: 6px;">优点</p>
                        <p style="font-size: 14px; color: var(--text-secondary); line-height: 1.6;">${escapeHtml(coachComment.strengths)}</p>
                    </div>
                    ` : ''}

                    ${safeText(coachComment.weaknesses) ? `
                    <div style="margin-bottom: 12px;">
                        <p style="font-size: 13px; color: var(--warning); font-weight: 500; margin-bottom: 6px;">存在问题</p>
                        <p style="font-size: 14px; color: var(--text-secondary); line-height: 1.6;">${escapeHtml(coachComment.weaknesses)}</p>
                    </div>
                    ` : ''}

                    ${safeText(coachComment.summary) ? `
                    <div>
                        <p style="font-size: 13px; color: var(--primary); font-weight: 500; margin-bottom: 6px;">总结</p>
                        <p style="font-size: 14px; color: var(--text-secondary); line-height: 1.6;">${escapeHtml(coachComment.summary)}</p>
                    </div>
                    ` : ''}
                </div>
                ` : ''}

                <!-- 训练问题（3点） -->
                ${problems.length > 0 ? `
                <div style="margin-bottom: 24px;">
                    <h3 style="font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 12px;">训练问题（${problems.length}点）</h3>
                    ${problems.map((problem, index) => `
                        <div style="padding: 14px; background: var(--bg-elevated); border-radius: 12px; margin-bottom: 10px; border: 1px solid var(--divider);">
                            <p style="font-size: 15px; font-weight: 500; color: var(--text-primary); margin-bottom: 6px;">${index + 1}. ${escapeHtml(problem.title || '问题')}</p>
                            <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.5;">${escapeHtml(problem.description || '')}</p>
                        </div>
                    `).join('')}
                </div>
                ` : ''}

                <!-- 训练建议（3点） -->
                ${suggestions.length > 0 ? `
                <div style="margin-bottom: 24px;">
                    <h3 style="font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 12px;">训练建议（${suggestions.length}点）</h3>
                    ${suggestions.map((suggestion, index) => `
                        <div style="padding: 14px; background: var(--bg-elevated); border-radius: 12px; margin-bottom: 10px; border: 1px solid var(--divider);">
                            <p style="font-size: 15px; font-weight: 500; color: var(--text-primary); margin-bottom: 6px;">${index + 1}. ${escapeHtml(suggestion.title || `训练建议 ${index + 1}`)}</p>
                            <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.6; white-space: pre-wrap;">${escapeHtml(suggestion.description || '')}</p>
                        </div>
                    `).join('')}
                </div>
                ` : ''}

                <!-- 底部操作按钮 -->
                <div style="
                    margin-top: 20px;
                    padding-top: 16px;
                    border-top: 1px solid var(--divider);
                    display: flex;
                    gap: 12px;
                ">
                    <button id="shareBtn" style="flex: 1; padding: 12px; background: var(--bg-elevated); border: 1px solid var(--divider); border-radius: 12px; color: var(--text-primary); font-size: 14px; font-weight: 500; cursor: pointer; transition: all 0.15s ease;">
                        分享结果
                    </button>
                    <button id="downloadBtn" style="flex: 1; padding: 12px; background: var(--primary-gradient); border: none; border-radius: 12px; color: white; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.15s ease; box-shadow: 0 4px 12px rgba(47, 124, 246, 0.3);">
                        下载报告
                    </button>
                </div>
            </div>
        `;

        // 绑定按钮事件
        resultContainer.querySelector('#shareBtn')?.addEventListener('click', () => {
            this.handleShare(result);
        });

        resultContainer.querySelector('#downloadBtn')?.addEventListener('click', () => {
            this.handleDownload(result);
        });
    }

    switchTab(tabName) {
        const resultContainer = document.getElementById('analysisResultContainer');
        if (!resultContainer) return;

        // 更新按钮状态
        resultContainer.querySelectorAll('.tab-btn').forEach(btn => {
            if (btn.dataset.tab === tabName) {
                btn.style.borderBottomColor = 'var(--primary)';
                btn.style.color = 'var(--primary)';
            } else {
                btn.style.borderBottomColor = 'transparent';
                btn.style.color = 'var(--text-secondary)';
            }
        });

        // 更新内容显示
        resultContainer.querySelectorAll('.tab-pane').forEach(pane => {
            pane.classList.add('hidden');
        });
        const targetPane = resultContainer.querySelector(`#${tabName}Tab`);
        if (targetPane) {
            targetPane.classList.remove('hidden');
        }
    }

    hideTrainingResult() {
        const trainingResultSection = document.getElementById('trainingResultSection');
        if (trainingResultSection) {
            trainingResultSection.classList.add('hidden');
        }
    }

    async toggleHistoryDrawer() {
        if (!this.taskHistory) {
            // 创建临时容器用于渲染历史任务
            const tempContainer = document.createElement('div');
            this.taskHistory = new TaskHistory(tempContainer, {
                onTaskClick: (taskId) => {
                    console.log('onTaskClick 被调用:', taskId);
                    this.drawer.close();
                    this.handleTaskClick(taskId);
                },
                onTaskDelete: async (taskId) => {
                    await deleteTask(taskId);
                    // 刷新后重新打开抽屉显示更新后的列表
                    await this.taskHistory.refresh();
                    this.drawer.open('历史任务', tempContainer.innerHTML);
                    // 重新绑定事件到 drawer 中的元素
                    const drawerBody = this.drawer.drawer.querySelector('.drawer-body');
                    this.taskHistory.bindTaskEvents(drawerBody);
                },
            });
        }

        // 刷新数据并打开抽屉（等待刷新完成）
        await this.taskHistory.refresh();
        const tempContainer = this.taskHistory.container;
        this.drawer.open('历史任务', tempContainer.innerHTML);

        // 重要：重新绑定事件到 drawer 中的元素
        const drawerBody = this.drawer.drawer.querySelector('.drawer-body');
        this.taskHistory.bindTaskEvents(drawerBody);
    }

    async handleShare(result) {
        // 分享功能 - 使用新的数据格式
        const coachComment = result.coach_comment || {};
        const problems = result.problems || [];
        const suggestions = result.suggestions || [];
        const score = result.overall_score || result.score || 0;

        // 构建分享链接
        const taskId = result.task_id;
        const shareUrl = taskId
            ? `${window.location.origin}${window.location.pathname}?task_id=${taskId}`
            : window.location.href;

        // 先调用分享 API 设置任务为公开分享状态
        if (taskId) {
            try {
                await shareTask(taskId);
                console.log('[分享] 任务已设置为公开分享状态');
            } catch (error) {
                console.error('[分享] 设置分享状态失败:', error);
                // 即使失败也继续分享流程（可能是历史任务，已经是公开的）
            }
        }

        // 构建分享文本（完整内容）
        let shareText = `AI乒乓球教练分析结果\n\n综合评分: ${score}分\n\n`;

        // 教练评语（完整内容）
        if (coachComment.strengths) {
            shareText += `【优点】\n${coachComment.strengths}\n\n`;
        }
        if (coachComment.weaknesses) {
            shareText += `【存在问题】\n${coachComment.weaknesses}\n\n`;
        }
        if (coachComment.summary) {
            shareText += `【总结】\n${coachComment.summary}\n\n`;
        }

        // 训练问题（完整内容：标题 + 描述）
        if (problems.length > 0) {
            shareText += `【训练问题】\n`;
            problems.forEach((p, i) => {
                shareText += `${i + 1}. ${p.title || '问题'}\n`;
                if (p.description) {
                    shareText += `   ${p.description}\n`;
                }
            });
            shareText += '\n';
        }

        // 训练建议（完整内容：标题 + 描述）
        if (suggestions.length > 0) {
            shareText += `【训练建议】\n`;
            suggestions.forEach((s, i) => {
                shareText += `${i + 1}. ${s.title || '建议'}\n`;
                if (s.description) {
                    shareText += `   ${s.description}\n`;
                }
            });
            shareText += '\n';
        }

        shareText += `查看详细分析: ${shareUrl}\n\n乒乓数字教练 v1.0`;

        copyToClipboard(shareText).then(success => {
            if (success) {
                showToast('已复制到剪贴板，链接可公开访问', 'success');
            } else {
                showToast('复制失败', 'error');
            }
        });
    }

    async handleDownload(result) {
        // 下载PDF报告
        const taskId = result.task_id;
        if (!taskId) {
            showToast('任务ID不存在，无法下载报告', 'error');
            return;
        }

        try {
            showToast('正在生成PDF报告...', 'info');

            // 构造PDF下载URL（注意：后端路由是 /results/{task_id}/pdf，不是 /api/results/{task_id}/pdf）
            const pdfUrl = `${API_BASE_URL}/results/${taskId}/pdf`;

            // 下载PDF
            const response = await fetch(pdfUrl, {
                credentials: 'include',
            });

            if (!response.ok) {
                // 尝试解析后端返回的错误消息
                let errorMessage = `下载失败: ${response.status}`;
                try {
                    const errorData = await response.json();
                    errorMessage = errorData.detail || errorMessage;
                } catch {
                    errorMessage = `下载失败 (${response.status})`;
                }
                throw new Error(errorMessage);
            }

            // 获取文件名（优先使用 RFC 5987 编码的中文文件名 filename*）
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = '乒乓球训练分析报告.pdf';
            if (contentDisposition) {
                // 优先匹配 filename* (RFC 5987 编码)
                const starMatch = contentDisposition.match(/filename\*=UTF-8''([^;\s]+)/);
                if (starMatch && starMatch[1]) {
                    // 解码 URL 编码的中文文件名
                    filename = decodeURIComponent(starMatch[1]);
                } else {
                    // 降级到 filename (ASCII 文件名)
                    const match = contentDisposition.match(/filename="([^"]+)"/);
                    if (match && match[1]) {
                        filename = match[1];
                    }
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

            showToast('PDF报告下载成功', 'success');

        } catch (error) {
            console.error('下载PDF报告失败:', error);
            showToast('下载PDF报告失败，请稍后重试', 'error');
        }
    }

    handleReanalyze() {
        // 重置上传组件
        this.videoUploader.reset();

        // 隐藏结果
        document.getElementById('currentTaskSection')?.classList.add('hidden');
        this.analysisResult.showEmpty();
        this.hideTrainingResult();

        showToast('请重新上传视频', 'info');
    }

    /**
     * 更新微信分享内容
     * 当显示分析结果时，更新微信分享的标题、链接和描述
     */
    updateWeChatShare(result) {
        if (!result) return;

        // 异步更新，不阻塞UI渲染
        setTimeout(async () => {
            try {
                // 确保微信SDK已初始化
                if (wechatShareManager.isSupported()) {
                    await wechatShareManager.init();

                    // 使用新数据格式
                    const coachComment = result.coach_comment || {};
                    const problems = result.problems || [];
                    const overallScore = result.overall_score || result.score || 0;

                    // 构建分享标题（无表情符号）
                    let title = `${overallScore}分 - 我的乒乓球技术分析报告`;

                    // 构建分享描述（使用教练评语总结）
                    let desc = coachComment.summary || 'AI教练为您生成专业的技术分析报告';

                    // 添加问题数量信息
                    if (problems.length > 0) {
                        desc += `，发现${problems.length}个问题需要改进`;
                    }

                    // 构建分享链接
                    const baseUrl = window.location.href.split('?')[0];
                    const shareLink = `${baseUrl}?task_id=${result.task_id}`;

                    // 设置分享内容
                    wechatShareManager.setShareData({
                        title: title,
                        link: shareLink,
                        desc: desc,
                        imgUrl: window.location.origin + '/share-cover.jpg'
                    });

                    console.log('微信分享内容已更新:', { title, desc, shareLink });
                }
            } catch (error) {
                console.error('更新微信分享内容失败:', error);
            }
        }, 100);
    }

    destroy() {
        if (this.wsConnection) {
            this.wsConnection.close();
        }
        this.videoUploader?.destroy();
        this.taskQueue?.destroy();
        this.taskHistory?.destroy();
        this.analysisResult?.destroy();
        this.analysisStatus?.destroy();
        this.drawer?.destroy();
    }
}

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    window.app = new App();
});

// 导出供测试使用
export { App };
