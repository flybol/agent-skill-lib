/**
 * 任务队列组件 - 显示排队和处理中的任务
 */

import { getStatusText, getStatusColorClass, formatTime } from '../utils/helpers.js';

export class TaskQueue {
    constructor(container, options = {}) {
        this.container = typeof container === 'string'
            ? document.querySelector(container)
            : container;
        this.options = {
            autoRefresh: true,
            refreshInterval: 3000,
            onTaskClick: () => {},
            ...options,
        };
        this.tasks = [];
        this.refreshTimer = null;
        this.init();
    }

    init() {
        this.render();
        if (this.options.autoRefresh) {
            this.startAutoRefresh();
        }
    }

    render() {
        this.container.innerHTML = `
            <div class="task-queue">
                <div class="flex items-center justify-between mb-4">
                    <h3 class="text-lg font-semibold text-gray-800">任务队列</h3>
                    <button id="refreshQueueBtn" class="p-2 hover:bg-gray-100 rounded-lg transition-colors">
                        <svg class="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                        </svg>
                    </button>
                </div>

                <div id="queueList" class="space-y-3">
                    <!-- 任务列表将在这里动态渲染 -->
                </div>

                <div id="emptyQueue" class="empty-queue hidden text-center py-8">
                    <svg class="w-12 h-12 mx-auto text-gray-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                    </svg>
                    <p class="text-gray-400">暂无任务</p>
                </div>
            </div>
        `;

        this.bindEvents();
    }

    bindEvents() {
        const refreshBtn = this.container.querySelector('#refreshQueueBtn');
        refreshBtn.addEventListener('click', () => this.refresh());
    }

    updateTasks(tasks) {
        this.tasks = tasks.filter(t =>
            t.status === 'pending' ||
            t.status === 'queued' ||
            t.status === 'processing' ||
            t.status === 'extracting' ||
            t.status === 'computing' ||
            t.status === 'analyzing'
        );
        this.renderTasks();
    }

    renderTasks() {
        const queueList = this.container.querySelector('#queueList');
        const emptyQueue = this.container.querySelector('#emptyQueue');

        if (this.tasks.length === 0) {
            queueList.innerHTML = '';
            emptyQueue.classList.remove('hidden');
            return;
        }

        emptyQueue.classList.add('hidden');
        queueList.innerHTML = this.tasks.map(task => this.renderTaskItem(task)).join('');

        // 绑定点击事件
        queueList.querySelectorAll('.task-item').forEach(item => {
            item.addEventListener('click', () => {
                const taskId = item.dataset.taskId;
                this.options.onTaskClick(taskId);
            });
        });
    }

    renderTaskItem(task) {
        const statusText = getStatusText(task.status);
        const statusClass = getStatusColorClass(task.status);
        const progress = task.progress || 0;

        return `
            <div class="task-item card-hover bg-white rounded-xl p-4 cursor-pointer border border-gray-100"
                 data-task-id="${task.task_id}">
                <div class="flex items-start justify-between mb-2">
                    <div class="flex-1 min-w-0">
                        <h4 class="font-medium text-gray-800 truncate">${task.name || '未命名任务'}</h4>
                        <p class="text-sm text-gray-400 mt-1">${formatTime(task.created_at)}</p>
                    </div>
                    <span class="status-badge ${statusClass} px-3 py-1 rounded-full text-xs font-medium whitespace-nowrap ml-2">
                        ${statusText}
                    </span>
                </div>

                ${task.status !== 'pending' && task.status !== 'queued' ? `
                    <div class="mt-3">
                        <div class="flex justify-between text-xs text-gray-500 mb-1">
                            <span>处理进度</span>
                            <span>${progress}%</span>
                        </div>
                        <div class="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div class="progress-bar h-full bg-blue-600 rounded-full transition-all" style="width: ${progress}%"></div>
                        </div>
                    </div>
                ` : ''}

                ${task.stage ? `
                    <div class="mt-2 text-xs text-gray-500">
                        <span class="inline-flex items-center">
                            <svg class="w-3 h-3 mr-1 animate-spin" fill="none" viewBox="0 0 24 24">
                                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                            </svg>
                            ${task.stage}
                        </span>
                    </div>
                ` : ''}
            </div>
        `;
    }

    async refresh() {
        try {
            const { getTaskQueue } = await import('../api/client.js');
            const data = await getTaskQueue();
            this.updateTasks(data.tasks || []);
        } catch (error) {
            console.error('刷新任务队列失败:', error);
        }
    }

    startAutoRefresh() {
        this.stopAutoRefresh();
        this.refreshTimer = setInterval(() => {
            this.refresh();
        }, this.options.refreshInterval);
    }

    stopAutoRefresh() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
            this.refreshTimer = null;
        }
    }

    destroy() {
        this.stopAutoRefresh();
        this.container.innerHTML = '';
    }
}

/**
 * 任务状态指示器组件
 */
export class TaskStatusIndicator {
    constructor(container) {
        this.container = typeof container === 'string'
            ? document.querySelector(container)
            : container;
    }

    render(status, stage = null, progress = 0) {
        const statusConfig = {
            pending: {
                icon: '<circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="2"/>',
                color: 'text-orange-500',
                bg: 'bg-orange-100',
            },
            processing: {
                icon: '<path class="opacity-25" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>',
                color: 'text-blue-500',
                bg: 'bg-blue-100',
            },
            completed: {
                icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>',
                color: 'text-green-500',
                bg: 'bg-green-100',
            },
            failed: {
                icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>',
                color: 'text-red-500',
                bg: 'bg-red-100',
            },
        };

        const config = statusConfig[status] || statusConfig.pending;

        this.container.innerHTML = `
            <div class="flex items-center space-x-3">
                <div class="w-10 h-10 rounded-full ${config.bg} flex items-center justify-center">
                    <svg class="w-5 h-5 ${config.color} ${status === 'processing' ? 'animate-spin' : ''}" fill="none" viewBox="0 0 24 24">
                        ${config.icon}
                    </svg>
                </div>
                <div class="flex-1">
                    <p class="text-sm font-medium text-gray-800">${getStatusText(status)}</p>
                    ${stage ? `<p class="text-xs text-gray-500">${stage}</p>` : ''}
                    ${progress > 0 && progress < 100 ? `
                        <div class="mt-1 h-1 bg-gray-200 rounded-full overflow-hidden">
                            <div class="h-full bg-blue-600 rounded-full transition-all" style="width: ${progress}%"></div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }
}
