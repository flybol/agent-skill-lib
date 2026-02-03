/**
 * 目标运动员确认组件
 * 在分析前显示系统检测的结果，让用户确认要分析哪个运动员
 */

export class TargetPlayerConfirm {
    constructor(container, options = {}) {
        this.container = typeof container === 'string'
            ? document.querySelector(container)
            : container;
        this.options = {
            onConfirm: (choice) => {},
            ...options,
        };
        this.init();
    }

    init() {
        this.render();
    }

    show(targetPlayer) {
        const wrapper = this.container.querySelector('.target-player-confirm-wrapper');
        if (wrapper) {
            wrapper.classList.remove('hidden');
        }
    }

    hide() {
        const wrapper = this.container.querySelector('.target-player-confirm-wrapper');
        if (wrapper) {
            wrapper.classList.add('hidden');
        }
    }

    render() {
        this.container.innerHTML = `
            <div class="target-player-confirm-wrapper hidden">
                <div class="card-dark fade-in" style="margin-bottom: 16px;">
                    <!-- 模块标题 -->
                    <div style="margin-bottom: 16px;">
                        <h2 style="font-size: 16px; font-weight: 600; color: var(--text-primary); margin-bottom: 4px;">确认分析对象</h2>
                        <p style="font-size: 13px; color: var(--text-secondary);">系统已检测到视频中的运动员，请确认要分析哪一位</p>
                    </div>

                    <!-- 目标球员选择器 -->
                    <div id="targetPlayerSelector"></div>

                    <!-- 确认按钮 -->
                    <button id="confirmAnalysisBtn" class="btn-primary" style="width: 100%; margin-top: 16px;" disabled>
                        <span style="display: flex; align-items: center; justify-content: center;">
                            <svg style="width: 20px; height: 20px; margin-right: 8px;" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                            已确认，开始分析
                        </span>
                    </button>
                </div>
            </div>
        `;
    }

    setTargetPlayer(targetPlayer) {
        const selector = this.container.querySelector('#targetPlayerSelector');
        if (!selector) return;

        const autoPick = targetPlayer?.auto_pick || 'single_player';
        const confidence = targetPlayer?.confidence || 0;
        const reason = targetPlayer?.reason || '';

        // 单人场景直接隐藏
        if (autoPick === 'single_player') {
            this.hide();
            this.options.onConfirm('single_player');
            return;
        }

        const sideText = autoPick === 'left' ? '左侧球员' : '右侧球员';
        const confidencePercent = Math.round(confidence * 100);

        // 显示置信度颜色
        let confidenceColor;
        let confidenceText;
        if (confidence >= 0.8) {
            confidenceColor = 'var(--success)';
            confidenceText = '高置信度';
        } else if (confidence >= 0.6) {
            confidenceColor = 'var(--warning)';
            confidenceText = '中等置信度';
        } else {
            confidenceColor = 'var(--error)';
            confidenceText = '低置信度，建议确认';
        }

        selector.innerHTML = `
            <div class="detection-panel">
                <div class="detection-header">
                    <div class="detection-icon">
                        <svg width="20" height="20" fill="none" stroke="var(--primary)" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                    </div>
                    <div class="detection-info">
                        <h4 class="detection-title">系统判断：主要击球者 = ${sideText}</h4>
                        <p class="detection-reason">${reason}</p>
                    </div>
                </div>

                <div class="detection-confidence">
                    <span class="confidence-value" style="color: ${confidenceColor}">${confidencePercent}%</span>
                    <span class="confidence-label">${confidenceText}</span>
                </div>

                <div class="player-options">
                    <button class="player-option-btn selected" data-choice="${autoPick}">
                        <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                        </svg>
                        分析${sideText}
                    </button>
                    <button class="player-option-btn" data-choice="${autoPick === 'left' ? 'right' : 'left'}">
                        <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/>
                        </svg>
                        分析${autoPick === 'left' ? '右侧' : '左侧'}
                    </button>
                </div>
            </div>

            <style>
                .detection-panel {
                    background: rgba(47, 124, 246, 0.08);
                    border-radius: var(--radius-lg);
                    padding: var(--space-lg);
                    border: 1px solid rgba(47, 124, 246, 0.2);
                }

                .detection-header {
                    display: flex;
                    align-items: flex-start;
                    gap: var(--space-md);
                    margin-bottom: var(--space-md);
                }

                .detection-icon {
                    width: 20px;
                    height: 20px;
                    flex-shrink: 0;
                    margin-top: 2px;
                }

                .detection-info {
                    flex: 1;
                }

                .detection-title {
                    font-size: 14px;
                    font-weight: 600;
                    color: var(--text-primary);
                    margin-bottom: var(--space-xs);
                }

                .detection-reason {
                    font-size: 12px;
                    color: var(--text-secondary);
                }

                .detection-confidence {
                    display: flex;
                    align-items: center;
                    gap: var(--space-sm);
                    margin-bottom: var(--space-md);
                    padding: var(--space-sm) 0;
                }

                .confidence-value {
                    font-size: 14px;
                    font-weight: 600;
                }

                .confidence-label {
                    font-size: 12px;
                    color: var(--text-tertiary);
                }

                .player-options {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: var(--space-sm);
                }

                .player-option-btn {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 4px;
                    padding: 10px 12px;
                    border-radius: var(--radius-md);
                    font-size: 13px;
                    font-weight: 500;
                    transition: all 0.2s ease;
                    background: var(--bg-elevated);
                    color: var(--text-secondary);
                    border: 2px solid var(--divider);
                    cursor: pointer;
                }

                .player-option-btn:hover {
                    background: var(--bg-card);
                    border-color: var(--divider-thick);
                }

                .player-option-btn.selected {
                    background: var(--primary-gradient);
                    color: white;
                    border-color: transparent;
                    box-shadow: 0 4px 12px rgba(47, 124, 246, 0.3);
                }

                .player-option-btn svg {
                    flex-shrink: 0;
                }
            </style>
        `;

        this.selectedChoice = autoPick;

        // 绑定选项按钮事件
        const buttons = selector.querySelectorAll('.player-option-btn');
        const confirmBtn = this.container.querySelector('#confirmAnalysisBtn');

        // 默认选择已设置，启用确认按钮
        confirmBtn.disabled = false;

        buttons.forEach(btn => {
            btn.addEventListener('click', () => {
                // 移除所有选中状态
                buttons.forEach(b => b.classList.remove('selected'));
                // 添加选中状态
                btn.classList.add('selected');
                // 更新选择
                this.selectedChoice = btn.dataset.choice;
                // 启用确认按钮
                confirmBtn.disabled = false;
            });
        });

        // 绑定确认按钮事件
        confirmBtn.addEventListener('click', () => {
            if (this.selectedChoice) {
                this.options.onConfirm(this.selectedChoice);
            }
        });

        // 显示组件
        this.show();
    }
}
