/**
 * 分析状态组件 - 显示实时分析进度和状态
 * 独立组件，可复用
 */

export class AnalysisStatus {
    constructor(container, options = {}) {
        this.container = typeof container === 'string'
            ? document.querySelector(container)
            : container;
        this.options = {
            onComplete: () => {},
            onFailed: () => {},
            ...options,
        };
        this.currentStatus = null;
        this.init();
    }

    init() {
        this.render();
    }

    render() {
        this.container.innerHTML = `
            <div id="analysisStatus" class="analysis-status hidden" style="
                background: var(--bg-card);
                border-radius: var(--radius-xl);
                border: 1px solid var(--divider);
                overflow: hidden;
            ">
                <!-- 状态头部 -->
                <div class="status-header" style="
                    padding: 20px;
                    text-align: center;
                    border-bottom: 1px solid var(--divider);
                ">
                    <!-- 动画图标 -->
                    <div id="statusIcon" style="
                        width: 56px;
                        height: 56px;
                        margin: 0 auto 16px;
                        border: 4px solid var(--bg-elevated);
                        border-top-color: var(--primary);
                        border-radius: 50%;
                        animation: spin 0.8s linear infinite;
                    "></div>

                    <!-- 状态标题 -->
                    <h3 id="statusTitle" style="
                        font-size: 18px;
                        font-weight: 600;
                        color: var(--text-primary);
                        margin-bottom: 8px;
                    ">准备分析</h3>

                    <!-- 当前阶段 -->
                    <p id="statusStage" style="
                        font-size: 14px;
                        color: var(--text-secondary);
                        margin: 0;
                    "></p>
                </div>

                <!-- 进度区域 -->
                <div class="status-progress" style="padding: 20px;">
                    <!-- 进度条 -->
                    <div style="max-width: 300px; margin: 0 auto;">
                        <div style="
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                            margin-bottom: 10px;
                        ">
                            <span style="font-size: 12px; color: var(--text-tertiary);">分析进度</span>
                            <span id="statusPercent" style="
                                font-size: 16px;
                                font-weight: 600;
                                color: var(--primary);
                            ">0%</span>
                        </div>
                        <div style="
                            height: 8px;
                            background: var(--bg-elevated);
                            border-radius: 10px;
                            overflow: hidden;
                        ">
                            <div id="statusProgressBar" style="
                                height: 100%;
                                width: 0%;
                                background: linear-gradient(90deg, var(--primary), #60a5fa);
                                border-radius: 10px;
                                transition: width 0.3s ease;
                            "></div>
                        </div>
                    </div>

                    <!-- 阶段步骤指示器 -->
                    <div id="stepsIndicator" style="margin-top: 24px;">
                        <!-- 步骤将动态生成 -->
                    </div>
                </div>

                <!-- 提示信息 -->
                <div class="status-footer" style="
                    padding: 12px 20px;
                    background: var(--bg-elevated);
                    border-top: 1px solid var(--divider);
                    text-align: center;
                ">
                    <p id="statusHint" style="
                        font-size: 12px;
                        color: var(--text-tertiary);
                        margin: 0;
                    "></p>
                </div>
            </div>

            <style>
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
                .analysis-status .step-item {
                    display: flex;
                    align-items: center;
                    margin-bottom: 12px;
                }
                .analysis-status .step-item:last-child {
                    margin-bottom: 0;
                }
                .analysis-status .step-indicator {
                    width: 24px;
                    height: 24px;
                    border-radius: 50%;
                    background: var(--bg-elevated);
                    color: var(--text-tertiary);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 12px;
                    font-weight: 600;
                    flex-shrink: 0;
                    margin-right: 12px;
                }
                .analysis-status .step-item.active .step-indicator {
                    background: var(--primary);
                    color: white;
                }
                .analysis-status .step-item.completed .step-indicator {
                    background: var(--success-bg);
                    color: var(--success);
                }
                .analysis-status .step-item.active .step-text {
                    color: var(--primary);
                    font-weight: 500;
                }
                .analysis-status .step-item.completed .step-text {
                    color: #34D399 !important;
                    font-weight: 500;
                }
                .analysis-status .step-text {
                    font-size: 13px;
                    color: var(--text-secondary);
                }
            </style>
        `;
    }

    /**
     * 显示状态组件
     */
    show() {
        const statusEl = this.container.querySelector('#analysisStatus');
        if (statusEl) {
            statusEl.classList.remove('hidden');
        }
    }

    /**
     * 隐藏状态组件
     */
    hide() {
        const statusEl = this.container.querySelector('#analysisStatus');
        if (statusEl) {
            statusEl.classList.add('hidden');
        }
    }

    /**
     * 更新状态
     * @param {Object} data - 包含 status, stage, progress 的状态数据
     */
    update(data) {
        console.log('[AnalysisStatus] 更新状态:', data);
        this.currentStatus = data;
        this.show();

        const { status = 'pending', stage = '', progress = 0 } = data;

        // 状态映射
        const statusMap = {
            'pending': { title: '等待开始', hint: '点击"开始分析"按钮开始', icon: 'clock' },
            'queued': { title: '排队中', hint: '任务已加入队列，请等待...', icon: 'queue' },
            'processing': { title: '处理中', hint: '正在处理您的视频...', icon: 'processing' },
            'extracting': { title: '视频抽帧中', hint: '正在从视频中提取关键帧...', icon: 'extracting' },
            'computing': { title: '计算特征中', hint: '正在计算动作特征...', icon: 'computing' },
            'analyzing': { title: 'AI 分析中', hint: 'AI 正在分析您的动作，请稍候...', icon: 'analyzing' },
            'assembling_report': { title: '生成报告中', hint: '正在生成分析报告...', icon: 'report' },
            'completed': { title: '分析完成', hint: '分析已成功完成！', icon: 'completed' },
            'failed': { title: '分析失败', hint: '分析过程中出现错误', icon: 'failed' }
        };

        const statusInfo = statusMap[status] || statusMap.pending;

        // 更新标题
        const titleEl = this.container.querySelector('#statusTitle');
        if (titleEl) {
            titleEl.textContent = statusInfo.title;
        }

        // 更新阶段
        const stageEl = this.container.querySelector('#statusStage');
        if (stageEl) {
            stageEl.textContent = stage || statusInfo.hint;
        }

        // 更新进度
        const progressPercent = Math.min(100, Math.max(0, progress));
        const percentEl = this.container.querySelector('#statusPercent');
        const progressBarEl = this.container.querySelector('#statusProgressBar');

        if (percentEl) {
            percentEl.textContent = `${progressPercent}%`;
        }
        if (progressBarEl) {
            progressBarEl.style.width = `${progressPercent}%`;
        }

        // 更新提示
        const hintEl = this.container.querySelector('#statusHint');
        if (hintEl) {
            hintEl.textContent = statusInfo.hint;
        }

        // 更新图标样式
        const iconEl = this.container.querySelector('#statusIcon');
        if (iconEl) {
            if (status === 'completed') {
                // 强制停止动画
                iconEl.style.animation = 'none';
                iconEl.style.webkitAnimation = 'none';
                iconEl.style.borderTopColor = 'var(--success)';
                iconEl.innerHTML = `
                    <svg style="width: 24px; height: 24px; color: var(--success);" fill="none" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/>
                    </svg>
                `;
                console.log('[AnalysisStatus] 状态已完成，动画已停止');
            } else if (status === 'failed') {
                iconEl.style.animation = 'none';
                iconEl.style.webkitAnimation = 'none';
                iconEl.style.borderTopColor = 'var(--error)';
                iconEl.innerHTML = `
                    <svg style="width: 24px; height: 24px; color: var(--error);" fill="none" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                `;
                console.log('[AnalysisStatus] 状态失败，动画已停止');
            } else {
                iconEl.innerHTML = '';
                iconEl.style.animation = 'spin 0.8s linear infinite';
                iconEl.style.webkitAnimation = 'spin 0.8s linear infinite';
            }
        }

        // 更新步骤指示器
        this.updateSteps(status);

        // 触发回调
        if (status === 'completed') {
            this.options.onComplete(data);
        } else if (status === 'failed') {
            this.options.onFailed(data);
        }
    }

    /**
     * 更新步骤指示器
     */
    updateSteps(status) {
        const stepsEl = this.container.querySelector('#stepsIndicator');
        if (!stepsEl) {
            console.log('[AnalysisStatus] 步骤指示器元素不存在');
            return;
        }

        console.log('[AnalysisStatus] 更新步骤指示器, status:', status);

        const steps = [
            { id: 'extracting', name: '抽取关键帧', status: 'pending' },
            { id: 'computing', name: '计算特征参数', status: 'pending' },
            { id: 'analyzing', name: 'AI分析', status: 'pending' },
            { id: 'assembling_report', name: '分析完成', status: 'pending' }
        ];

        // 根据当前状态更新步骤状态
        const statusOrder = ['extracting', 'computing', 'analyzing', 'assembling_report', 'completed'];
        const currentIndex = statusOrder.indexOf(status);

        console.log('[AnalysisStatus] 当前步骤索引:', currentIndex);

        steps.forEach((step, index) => {
            if (currentIndex === -1) return;

            if (index < currentIndex) {
                step.status = 'completed';
            } else if (index === currentIndex) {
                step.status = 'active';
            } else {
                step.status = 'pending';
            }
        });

        console.log('[AnalysisStatus] 步骤状态:', steps.map(s => `${s.name}:${s.status}`).join(', '));

        // 渲染步骤（使用内联样式增强样式应用）
        stepsEl.innerHTML = steps.map((step, index) => {
            const isCompleted = step.status === 'completed';
            const isActive = step.status === 'active';
            const isPending = step.status === 'pending';

            // 完成状态：绿色；激活状态：蓝色；待处理：灰色
            // 灰白色使用 --text-secondary 确保更好的可见性
            let textStyle = 'color: var(--text-secondary);';
            let indicatorStyle = 'background: var(--bg-elevated); color: var(--text-tertiary);';

            if (isCompleted) {
                textStyle = 'color: #34D399 !important; font-weight: 500;';
                indicatorStyle = 'background: var(--success-bg); color: #34D399;';
            } else if (isActive) {
                textStyle = 'color: var(--primary); font-weight: 500;';
                indicatorStyle = 'background: var(--primary); color: white;';
            }

            return `
                <div class="step-item ${step.status}">
                    <div class="step-indicator" style="${indicatorStyle}">
                        ${isCompleted ? '✓' : index + 1}
                    </div>
                    <span class="step-text" style="${textStyle}">${step.name}</span>
                </div>
            `;
        }).join('');

        console.log('[AnalysisStatus] 步骤 HTML 已更新，最终颜色：',
            steps.map(s => {
                if (s.status === 'completed') return '绿色';
                if (s.status === 'active') return '蓝色';
                return '灰白色';
            }).join(' → ')
        );
    }

    /**
     * 设置为加载状态
     */
    setLoading() {
        this.update({ status: 'queued', stage: '正在初始化...', progress: 0 });
    }

    /**
     * 重置组件
     */
    reset() {
        this.hide();
        this.currentStatus = null;
    }

    /**
     * 销毁组件
     */
    destroy() {
        this.container.innerHTML = '';
    }
}

export default AnalysisStatus;
