/**
 * AI 乒乓球教练 - 主应用入口
 * 整合所有组件，处理完整交互流程
 */

import './styles/theme-dark.css';
import { VideoUploader, showToast } from './components/VideoUploader.js';
import { TaskQueue, TaskStatusIndicator } from './components/TaskQueue.js';
import { AnalysisResult } from './components/AnalysisResult.js';
import { TaskHistory } from './components/TaskHistory.js';
import { Drawer } from './components/Drawer.js';
import { TargetPlayerConfirm } from './components/TargetPlayerConfirm.js';
import {
    uploadVideo,
    preprocessVideo,
    startAnalysis as startAnalysisAPI,
    getAnalysisResult,
    getHistoryTasks,
    getTaskQueue,
    deleteTask,
    connectTaskWebSocket,
} from './api/client.js';
import { formatTime, copyToClipboard } from './utils/helpers.js';
import { wechatShareManager } from './utils/wechatShare.js';

class App {
    constructor() {
        this.currentTask = null;
        this.wsConnection = null;
        this.drawer = new Drawer({ position: 'right' });
        this.init();
    }

    init() {
        this.render();
        this.initComponents();
        this.bindEvents();
        this.loadInitialData();
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
                            <p style="font-size: 13px; color: var(--text-secondary);">选择 1~3 秒内的乒乓球训练视频（最大 10MB）</p>
                        </div>

                        <!-- 视频上传组件容器 -->
                        <div id="videoUploaderContainer"></div>

                        <!-- 当前任务状态 -->
                        <div id="currentTaskSection" class="hidden" style="margin-top: 20px;">
                            <h3 style="font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 12px;">当前任务</h3>
                            <div id="taskStatusContainer"></div>
                        </div>

                        <!-- 主行动按钮 -->
                        <button id="analyzeBtn" class="btn-primary" style="width: 100%; margin-top: 16px; font-size: 17px;" disabled>
                            🚀 开始分析
                        </button>
                    </section>

                    <!-- 分割线 -->
                    <div style="height: 1px; background: var(--divider); margin: 16px 0;"></div>

                    <!-- 目标球员确认模块 -->
                    <div id="targetPlayerConfirmContainer"></div>

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
            onUploadSuccess: (result) => {
                this.handleUploadSuccess(result);
            },
        });

        // 目标球员确认组件
        this.targetPlayerConfirm = new TargetPlayerConfirm('#targetPlayerConfirmContainer', {
            onConfirm: (choice) => {
                this.handleTargetPlayerConfirmed(choice);
            },
        });

        // 任务状态指示器
        this.taskStatusIndicator = new TaskStatusIndicator('#taskStatusContainer');

        // 分析结果组件
        this.analysisResult = new AnalysisResult('#analysisResultContainer', {
            onShare: (result) => this.handleShare(result),
            onDownload: (result) => this.handleDownload(result),
            onReanalyze: () => this.handleReanalyze(),
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
        document.getElementById('historyToggleBtn')?.addEventListener('click', async () => {
            await this.toggleHistoryDrawer();
        });

        // 开始分析按钮
        document.getElementById('analyzeBtn')?.addEventListener('click', async () => {
            if (this.videoUploader.file) {
                // 禁用按钮，上传视频
                const analyzeBtn = document.getElementById('analyzeBtn');
                analyzeBtn.disabled = true;
                analyzeBtn.textContent = '上传中...';

                try {
                    await this.videoUploader.upload();
                    // upload 成功后会触发 handleUploadSuccess
                } catch (error) {
                    console.error('上传失败:', error);
                    analyzeBtn.textContent = '🚀 开始分析';
                    analyzeBtn.disabled = false;
                }
            }
        });
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

            // 检查 URL 参数，支持分享链接直接打开分析结果
            const urlParams = new URLSearchParams(window.location.search);
            const sharedTaskId = urlParams.get('task_id');

            if (sharedTaskId) {
                // 有分享的任务 ID，加载并显示该分析结果
                console.log('检测到分享链接，加载任务:', sharedTaskId);
                await this.loadSharedResult(sharedTaskId);
            } else {
                // 正常加载历史任务数据
                const historyData = await getHistoryTasks(1, 20);
                console.log('已加载历史任务:', historyData);
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
            this.analysisResult.showLoading();
            const result = await getAnalysisResult(taskId);

            if (result && result.status === 'completed') {
                // 显示分享的结果
                this.displayAnalysisResult(result);

                // 显示提示消息
                showToast('正在查看分享的分析结果', 'info');

                // 隐藏上传区域，只显示结果
                const uploadSection = document.querySelector('.card-dark');
                if (uploadSection) {
                    uploadSection.style.display = 'none';
                }

                // 隐藏目标球员确认模块
                const targetPlayerContainer = document.getElementById('targetPlayerConfirmContainer');
                if (targetPlayerContainer) {
                    targetPlayerContainer.style.display = 'none';
                }

                // 修改标题为"分享的分析结果"
                const titleElement = document.querySelector('h2');
                if (titleElement) {
                    titleElement.textContent = '分享的分析结果';
                }
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

        // 更新按钮状态为"检测中..."
        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn) {
            analyzeBtn.textContent = '检测中...';
            analyzeBtn.disabled = true;
        }

        // 显示预处理进度
        this.showPreprocessProgress();

        try {
            // 调用预处理接口，检测目标运动员
            const preprocessResult = await preprocessVideo(result.task_id);

            // 显示目标运动员确认界面
            this.targetPlayerConfirm.setTargetPlayer(preprocessResult.target_player);

            // 隐藏预处理进度
            const resultContainer = document.getElementById('analysisResultContainer');
            if (resultContainer) {
                resultContainer.innerHTML = '';
            }

            // 检测完成，如果是单人场景，按钮保持"检测中..."等待分析开始
            // 如果是多人场景，保持"检测中..."状态
        } catch (error) {
            console.error('预处理失败:', error);
            // 预处理失败时，直接显示分析进度（降级处理）
            this.connectWebSocket(result.task_id);
            this.showAnalysisProgress();
        }
    }

    async handleTargetPlayerConfirmed(choice) {
        // 保存用户选择
        this.selectedTargetPlayer = choice;

        // 隐藏确认界面
        this.targetPlayerConfirm.hide();

        // 更新按钮状态为"分析中..."
        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn) {
            analyzeBtn.textContent = '分析中...';
            analyzeBtn.disabled = true;
        }

        // 显示分析进度
        this.showAnalysisProgress();

        // 连接 WebSocket 接收实时更新
        this.connectWebSocket(this.currentTask.task_id);

        // 开始分析，传递用户选择的目标球员
        try {
            await startAnalysisAPI(this.currentTask.task_id, choice);
        } catch (error) {
            console.error('启动分析失败:', error);
            // 分析失败，重置按钮
            if (analyzeBtn) {
                analyzeBtn.textContent = '🚀 开始分析';
                analyzeBtn.disabled = false;
            }
        }
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
                <div style="
                    width: 32px;
                    height: 32px;
                    margin: 0 auto 16px;
                    border: 3px solid var(--bg-elevated);
                    border-top-color: var(--primary);
                    border-radius: 50%;
                    animation: spin 0.8s linear infinite;
                "></div>
                <p style="font-size: 15px; color: var(--text-secondary);">AI 正在分析中...</p>
                <p style="font-size: 12px; color: var(--text-tertiary); margin-top: 4px;">
                    <span id="analysisStage">视频抽帧中...</span>
                </p>
            </div>
            <style>
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
            </style>
        `;

        // 模拟进度更新
        const stages = [
            { text: '视频抽帧中...', delay: 800 },
            { text: '计算动作特征...', delay: 1600 },
            { text: 'AI 生成分析报告...', delay: 2400 },
        ];

        stages.forEach((stage, index) => {
            setTimeout(() => {
                const stageEl = document.getElementById('analysisStage');
                if (stageEl) stageEl.textContent = stage.text;
            }, stage.delay);
        });
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

    async startAnalysis(taskId) {
        try {
            const result = await startAnalysisAPI(taskId);
            showToast(result.message, 'success');
        } catch (error) {
            showToast('启动分析失败: ' + error.message, 'error');
        }
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
        // 更新进度显示
        const stageEl = document.getElementById('analysisStage');
        if (stageEl && data.stage) {
            stageEl.textContent = data.stage + '...';
        }

        // 更新进度条（如果有）
        if (data.progress !== undefined) {
            // 可以添加进度条显示
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
                if (!result.key_frames) result.key_frames = [];

                // 从 result 中提取目标球员信息（用于显示标签）
                if (result.target_player) {
                    const autoPick = result.target_player.auto_pick || result.target_player;
                    this.selectedTargetPlayer = autoPick;
                }

                // 设置视频上传区域显示该任务的视频
                const videoUrl = result.video_url || result.input_video;
                if (videoUrl) {
                    const fileName = result.input_video_name || result.task_id || '历史视频';
                    const fileSize = result.file_size || 0;
                    this.videoUploader.setVideoByUrl(videoUrl, fileName, fileSize);
                }

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
            analyzeBtn.textContent = '🚀 重新分析';
            analyzeBtn.disabled = false;
        }

        const summary = result.summary || {};
        const keyFrames = result.key_frames || [];
        const overallScore = result.overall_score || 0;
        const weaknesses = summary.weaknesses || [];
        const strengths = summary.strengths || [];
        const suggestions = result.suggestions || summary.suggestions || [];

        // 更新微信分享内容（如果在微信环境）
        this.updateWeChatShare(result);

        // 获取视频URL（如果有）
        const videoUrl = result.video_url || result.input_video || '';

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
                    ${summary.overview ? `<p style="font-size: 13px; color: var(--text-secondary); margin-top: 8px; line-height: 1.5;">${summary.overview}</p>` : ''}
                </div>

                <!-- Tab 切换按钮 -->
                <div style="display: flex; gap: 8px; margin-bottom: 16px; border-bottom: 1px solid var(--divider);">
                    <button class="tab-btn active" data-tab="summary" style="flex: 1; padding: 10px; background: transparent; border: none; border-bottom: 2px solid var(--primary); color: var(--primary); font-size: 14px; font-weight: 500; cursor: pointer;">
                        分析结果
                    </button>
                    ${videoUrl ? `
                    <button class="tab-btn" data-tab="video" style="flex: 1; padding: 10px; background: transparent; border: none; border-bottom: 2px solid transparent; color: var(--text-secondary); font-size: 14px; font-weight: 500; cursor: pointer;">
                        原始视频
                    </button>
                    ` : ''}
                    ${keyFrames.length > 0 ? `
                    <button class="tab-btn" data-tab="frames" style="flex: 1; padding: 10px; background: transparent; border: none; border-bottom: 2px solid transparent; color: var(--text-secondary); font-size: 14px; font-weight: 500; cursor: pointer;">
                        关键帧 (${keyFrames.length})
                    </button>
                    ` : ''}
                </div>

                <!-- Tab 内容区域 -->
                <div id="tabContent">
                    <!-- 分析结果 Tab -->
                    <div id="summaryTab" class="tab-pane">
                        ${weaknesses.length > 0 ? `
                        <div style="margin-bottom: 20px;">
                            <p style="font-size: 13px; color: var(--warning); margin-bottom: 12px;">${playerLabel ? playerLabel + ' ' : ''}发现 ${weaknesses.length} 个问题</p>
                            ${weaknesses.map(issue => `
                                <div style="padding: 12px; background: var(--bg-elevated); border-radius: 10px; margin-bottom: 8px;">
                                    <p style="font-size: 14px; font-weight: 500; color: var(--text-primary); margin-bottom: 4px;">${typeof issue === 'string' ? issue : issue.title || '问题'}</p>
                                    ${issue.description ? `<p style="font-size: 13px; color: var(--text-secondary);">${issue.description}</p>` : ''}
                                </div>
                            `).join('')}
                        </div>
                        ` : ''}

                        ${suggestions.length > 0 ? `
                        <div>
                            <p style="font-size: 13px; color: var(--success); margin-bottom: 12px;">改进措施</p>
                            ${suggestions.map((suggestion, index) => `
                                <div style="padding: 14px; background: var(--bg-elevated); border-radius: 12px; margin-bottom: 12px; border: 1px solid var(--divider);">
                                    <div style="display: flex; align-items: start;">
                                        <div style="width: 24px; height: 24px; background: var(--success-bg); border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-right: 12px; flex-shrink: 0;">
                                            <svg width="12" height="12" fill="none" stroke="var(--success)" viewBox="0 0 24 24">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/>
                                            </svg>
                                        </div>
                                        <div style="flex: 1;">
                                            <p style="font-size: 15px; font-weight: 500; color: var(--text-primary); margin-bottom: 4px;">${suggestion.title || `改进建议 ${index + 1}`}</p>
                                            <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.5;">${suggestion.description}</p>
                                        </div>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                        ` : ''}

                        ${!summary.overview && weaknesses.length === 0 && suggestions.length === 0 ? `
                        <div style="text-align: center; padding: 40px 20px;">
                            <p style="font-size: 14px; color: var(--text-tertiary);">暂无分析结果</p>
                        </div>
                        ` : ''}
                    </div>

                    <!-- 原始视频 Tab -->
                    ${videoUrl ? `
                    <div id="videoTab" class="tab-pane hidden">
                        <div style="background: var(--bg-elevated); border-radius: 12px; overflow: hidden; border: 1px solid var(--divider);">
                            <video src="${videoUrl}" controls style="width: 100%; max-height: 400px;" preload="metadata">
                                您的浏览器不支持视频播放
                            </video>
                            <div style="padding: 12px;">
                                <p style="font-size: 13px; color: var(--text-secondary);">原始训练视频</p>
                            </div>
                        </div>
                    </div>
                    ` : ''}

                    <!-- 关键帧 Tab -->
                    ${keyFrames.length > 0 ? `
                    <div id="framesTab" class="tab-pane hidden">
                        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px;">
                            ${keyFrames.map((frame, index) => `
                                <div style="background: var(--bg-elevated); border-radius: 12px; overflow: hidden; border: 1px solid var(--divider);">
                                    <img src="${frame.url}" alt="关键帧 ${index + 1}" style="width: 100%; aspect-ratio: 16/9; object-fit: cover;">
                                    <div style="padding: 12px;">
                                        <p style="font-size: 11px; color: var(--text-tertiary); margin-bottom: 4px;">帧 #${frame.frame_number || index + 1}</p>
                                        ${frame.description ? `<p style="font-size: 13px; color: var(--text-secondary);">${frame.description}</p>` : ''}
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                    ` : ''}
                </div>

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

        // 绑定 Tab 切换事件
        const tabButtons = resultContainer.querySelectorAll('.tab-btn');
        tabButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                const tabName = btn.dataset.tab;
                this.switchTab(tabName);
            });
        });

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

    handleShare(result) {
        // 分享功能
        const summary = result.summary || {};
        const overview = summary.overview || '无概要信息';
        const score = result.overall_score || 0;
        // 构建分享链接（优先使用任务ID构建，确保分享链接有效）
        const taskId = result.task_id;
        const shareUrl = taskId
            ? `${window.location.origin}${window.location.pathname}?task_id=${taskId}`
            : window.location.href;

        const shareText = `🏓 AI 乒乓球教练分析结果

综合评分: ${score}分

${overview}

${summary.weaknesses?.length ? '发现问题:\n' + summary.weaknesses.map((w, i) => `${i + 1}. ${typeof w === 'string' ? w : w.title}`).join('\n') : ''}

${result.suggestions?.length ? '改进建议:\n' + result.suggestions.map((s, i) => `${i + 1}. ${s.title}`).join('\n') : ''}

查看详细分析: ${shareUrl}

—— 乒乓数字教练 v1.0`;

        copyToClipboard(shareText).then(success => {
            if (success) {
                showToast('已复制到剪贴板', 'success');
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

            // 构造PDF下载URL
            const pdfUrl = `/api/results/${taskId}/pdf`;

            // 下载PDF
            const response = await fetch(pdfUrl);

            if (!response.ok) {
                throw new Error(`下载失败: ${response.status} ${response.statusText}`);
            }

            // 获取文件名
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = `pingpong_analysis_${taskId}.pdf`;
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

                    // 构建分享标题
                    const overallScore = result.overall_score || 0;
                    let title = `⭐ ${overallScore}分 - 我的乒乓球技术分析报告`;

                    // 构建分享描述
                    const summary = result.summary || {};
                    let desc = 'AI教练为您生成专业的技术分析报告';
                    if (summary.overview) {
                        desc = summary.overview.substring(0, 50);
                    }
                    const weaknesses = summary.weaknesses || [];
                    if (weaknesses.length > 0) {
                        desc += `\n发现${weaknesses.length}个问题需要改进`;
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
        this.drawer?.destroy();
    }
}

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    window.app = new App();
});

// 导出供测试使用
export { App };
