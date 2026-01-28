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
    startAnalysis,
    getAnalysisResult,
    getHistoryTasks,
    getTaskQueue,
    deleteTask,
    connectTaskWebSocket,
} from './api/client.js';
import { formatTime, copyToClipboard } from './utils/helpers.js';

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
                    <section class="fade-in" style="animation-delay: 0.1s;">
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
            // 加载历史任务数据
            const historyData = await getHistoryTasks(1, 20);
            console.log('已加载历史任务:', historyData);
        } catch (error) {
            console.error('加载初始数据失败:', error);
            // 使用模拟数据作为后备
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

        // 开始分析
        try {
            await startAnalysis(this.currentTask.task_id);
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
            const result = await startAnalysis(taskId);
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
                this.analysisResult.setResult(result);
                this.switchPage('upload');
            } else {
                this.analysisResult.showEmpty();
            }
        } catch (error) {
            console.error('获取任务结果失败:', error);
            showToast('获取任务结果失败', 'error');
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

        const analyzeBtn = document.getElementById('analyzeBtn');
        if (analyzeBtn) {
            analyzeBtn.textContent = '🚀 重新分析';
            analyzeBtn.disabled = false;
        }

        const summary = result.summary || {};
        const suggestions = result.suggestions || [];
        const overallScore = result.overall_score || 0;
        const weaknesses = summary.weaknesses || [];
        const strengths = summary.strengths || [];

        resultContainer.innerHTML = `
            <div style="padding: 20px;">
                <!-- 分析完成头部 -->
                <div style="padding-bottom: 12px; margin-bottom: 16px; border-bottom: 1px solid var(--divider);">
                    <p style="font-size: 13px; color: var(--success); font-weight: 500;">分析完成</p>
                    <p style="font-size: 16px; font-weight: 600; color: var(--text-primary); margin-top: 4px;">
                        综合评分: <span style="color: var(--success); font-size: 24px; font-weight: 600;">${overallScore}</span>
                    </p>
                    ${summary.overview ? `<p style="font-size: 13px; color: var(--text-secondary); margin-top: 8px; line-height: 1.5;">${summary.overview}</p>` : ''}
                </div>

                ${weaknesses.length > 0 ? `
                <!-- 发现的问题 -->
                <div style="margin-bottom: 20px;">
                    <p style="font-size: 13px; color: var(--warning); margin-bottom: 12px;">发现 ${weaknesses.length} 个问题</p>
                    ${weaknesses.map(issue => `
                        <div class="checklist-item">
                            <div class="checklist-icon" style="background: var(--warning-bg); color: var(--warning);">
                                <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                                </svg>
                            </div>
                            <div class="checklist-text">
                                <p style="font-size: 15px; font-weight: 500; color: var(--text-primary);">${typeof issue === 'string' ? issue : issue.title || '问题'}</p>
                                ${issue.description ? `<p style="font-size: 13px; color: var(--text-secondary); line-height: 1.4;">${issue.description}</p>` : ''}
                            </div>
                        </div>
                    `).join('')}
                </div>
                ` : ''}

                ${suggestions.length > 0 ? `
                <!-- 改进建议 -->
                <div>
                    <p style="font-size: 13px; color: var(--success); margin-bottom: 12px;">改进措施</p>
                    ${suggestions.map((suggestion, index) => `
                        <div class="checklist-item">
                            <div class="checklist-icon">
                                <svg width="12" height="12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                                </svg>
                            </div>
                            <div class="checklist-text">
                                <p style="font-size: 15px; font-weight: 500; color: var(--text-primary);">${suggestion.title || `改进建议 ${index + 1}`}</p>
                                <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.4;">${suggestion.description}</p>
                            </div>
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

    async toggleHistoryDrawer() {
        if (!this.taskHistory) {
            // 创建临时容器用于渲染历史任务
            const tempContainer = document.createElement('div');
            this.taskHistory = new TaskHistory(tempContainer, {
                onTaskClick: (taskId) => {
                    this.drawer.close();
                    this.handleTaskClick(taskId);
                },
                onTaskDelete: async (taskId) => {
                    await deleteTask(taskId);
                    // 刷新后重新打开抽屉显示更新后的列表
                    await this.taskHistory.refresh();
                    this.drawer.open('历史任务', tempContainer.innerHTML);
                },
            });
        }

        // 刷新数据并打开抽屉（等待刷新完成）
        await this.taskHistory.refresh();
        const tempContainer = this.taskHistory.container;
        this.drawer.open('历史任务', tempContainer.innerHTML);
    }

    handleShare(result) {
        // 分享功能
        const summary = result.summary || {};
        const overview = summary.overview || '无概要信息';
        const score = result.overall_score || 0;

        const shareText = `🏓 AI 乒乓球教练分析结果

综合评分: ${score}分

${overview}

${summary.weaknesses?.length ? '发现问题:\n' + summary.weaknesses.map((w, i) => `${i + 1}. ${typeof w === 'string' ? w : w.title}`).join('\n') : ''}

${result.suggestions?.length ? '改进建议:\n' + result.suggestions.map((s, i) => `${i + 1}. ${s.title}`).join('\n') : ''}

—— 乒乓数字教练 v1.0`;

        copyToClipboard(shareText).then(success => {
            if (success) {
                showToast('已复制到剪贴板', 'success');
            } else {
                showToast('复制失败', 'error');
            }
        });
    }

    handleDownload(result) {
        // 下载功能 - 生成 JSON 文件
        const dataStr = JSON.stringify(result, null, 2);
        const blob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `pingpong-analysis-${result.task_id || Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
        showToast('下载已开始', 'success');
    }

    handleReanalyze() {
        // 重置上传组件
        this.videoUploader.reset();

        // 隐藏结果
        document.getElementById('currentTaskSection')?.classList.add('hidden');
        this.analysisResult.showEmpty();

        showToast('请重新上传视频', 'info');
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
