/**
 * 分析结果展示组件 - 分层展示 AI 分析结果
 * 使用 Accordion（手风琴）和 Tabs 组织内容
 */

import { formatTime, safeJsonParse } from '../utils/helpers.js';

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
                        <button id="downloadBtn" class="flex-1 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium py-3 px-4 rounded-xl transition-colors flex items-center justify-center">
                            <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
                            </svg>
                            下载
                        </button>
                        <button id="reanalyzeBtn" class="flex-1 bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 px-4 rounded-xl transition-colors flex items-center justify-center">
                            <svg class="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                            </svg>
                            再次分析
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

        // 操作按钮
        this.container.querySelector('#shareBtn')?.addEventListener('click', () => {
            this.options.onShare(this.result);
        });

        this.container.querySelector('#downloadBtn')?.addEventListener('click', () => {
            this.options.onDownload(this.result);
        });

        this.container.querySelector('#reanalyzeBtn')?.addEventListener('click', () => {
            this.options.onReanalyze();
        });
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
        }
    }

    renderSummary(result) {
        const container = this.container.querySelector('#summaryTab');
        if (!container || !result.summary) return;

        // 渲染目标球员选择器
        const targetPlayerHtml = this.renderTargetPlayerSelector(result.target_player);

        container.innerHTML = `
            <div class="space-y-4">
                ${targetPlayerHtml}

                ${result.summary.overview ? `
                    <div class="bg-blue-50 rounded-xl p-4">
                        <h4 class="font-semibold text-blue-900 mb-2">总体评价</h4>
                        <p class="text-blue-800 text-sm">${result.summary.overview}</p>
                    </div>
                ` : ''}

                ${result.summary.strengths && result.summary.strengths.length > 0 ? `
                    <div>
                        <h4 class="font-semibold text-gray-800 mb-3 flex items-center">
                            <svg class="w-5 h-5 mr-2 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                            优点 (${result.summary.strengths.length})
                        </h4>
                        <ul class="space-y-2">
                            ${result.summary.strengths.map(s => `
                                <li class="flex items-start">
                                    <span class="text-green-500 mr-2 mt-1">•</span>
                                    <span class="text-gray-700 text-sm">${s}</span>
                                </li>
                            `).join('')}
                        </ul>
                    </div>
                ` : ''}

                ${result.summary.weaknesses && result.summary.weaknesses.length > 0 ? `
                    <div>
                        <h4 class="font-semibold text-gray-800 mb-3 flex items-center">
                            <svg class="w-5 h-5 mr-2 text-orange-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                            </svg>
                            需要改进 (${result.summary.weaknesses.length})
                        </h4>
                        <ul class="space-y-2">
                            ${result.summary.weaknesses.map(w => {
                                const text = typeof w === 'string' ? w : (w.title || w.description || '问题');
                                const desc = typeof w === 'object' && w.description ? `<p class="text-xs text-gray-500 mt-1">${w.description}</p>` : '';
                                return `
                                <li class="flex items-start">
                                    <span class="text-orange-500 mr-2 mt-1">•</span>
                                    <span class="text-gray-700 text-sm">${text}</span>
                                </li>
                                ${desc}
                            `}).join('')}
                        </ul>
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
        if (!container || !result.key_frames) return;

        container.innerHTML = `
            <div class="grid grid-cols-2 gap-4">
                ${result.key_frames.map((frame, index) => `
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
        if (!container || !result.details) return;

        container.innerHTML = `
            <div class="space-y-6">
                ${result.details.technique ? `
                    <div class="accordion-item">
                        <button class="accordion-btn w-full flex items-center justify-between p-4 bg-gray-50 rounded-xl hover:bg-gray-100 transition-colors">
                            <span class="font-medium text-gray-800">技术动作分析</span>
                            <svg class="w-5 h-5 text-gray-500 accordion-icon transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                            </svg>
                        </button>
                        <div class="accordion-content hidden mt-2 px-4">
                            <div class="pb-4 text-sm text-gray-700 space-y-2">
                                ${Object.entries(result.details.technique).map(([key, value]) => `
                                    <div class="flex justify-between">
                                        <span class="text-gray-500">${key}</span>
                                        <span class="font-medium">${value}</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                ` : ''}

                ${result.details.metrics ? `
                    <div class="accordion-item">
                        <button class="accordion-btn w-full flex items-center justify-between p-4 bg-gray-50 rounded-xl hover:bg-gray-100 transition-colors">
                            <span class="font-medium text-gray-800">技术指标</span>
                            <svg class="w-5 h-5 text-gray-500 accordion-icon transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                            </svg>
                        </button>
                        <div class="accordion-content hidden mt-2 px-4">
                            <div class="pb-4 text-sm text-gray-700 space-y-2">
                                ${Object.entries(result.details.metrics).map(([key, value]) => `
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
        if (!container || !result.suggestions) return;

        container.innerHTML = `
            <div class="space-y-4">
                <h4 class="font-semibold text-gray-800 mb-3">改进建议 (${result.suggestions.length})</h4>
                ${result.suggestions.map((suggestion, index) => `
                    <div class="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-xl p-4">
                        <div class="flex items-start">
                            <div class="w-8 h-8 bg-blue-600 text-white rounded-lg flex items-center justify-center font-bold mr-3 flex-shrink-0">
                                ${index + 1}
                            </div>
                            <div>
                                <h4 class="font-semibold text-gray-800 mb-1">${suggestion.title}</h4>
                                <p class="text-sm text-gray-600">${suggestion.description}</p>
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
