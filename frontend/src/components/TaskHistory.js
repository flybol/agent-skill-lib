/**
 * 历史任务列表组件 - 深色主题
 * 显示已完成和失败的任务
 */

import { getStatusText, getStatusColorClass, formatTime } from '../utils/helpers.js';

export class TaskHistory {
    constructor(container, options = {}) {
        this.container = typeof container === 'string'
            ? document.querySelector(container)
            : container;
        this.options = {
            pageSize: 20,
            onLoadMore: () => {},
            onTaskClick: () => {},
            onTaskDelete: () => {},
            ...options,
        };
        this.tasks = [];
        this.page = 1;
        this.hasMore = true;
        this.currentFilter = 'all';
        this.init();
    }

    init() {
        this.render();
        this.bindEvents();
    }

    render() {
        this.container.innerHTML = `
            <div class="task-history" style="padding: 16px;">
                <!-- 标题区域 -->
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
                    <h3 style="font-size: 16px; font-weight: 600; color: var(--text-primary);">历史任务</h3>
                    <span id="taskCount" style="font-size: 13px; color: var(--text-secondary);"></span>
                </div>

                <!-- 筛选器 -->
                <div style="display: flex; gap: 8px; margin-bottom: 16px; overflow-x: auto; padding-bottom: 4px;">
                    <button class="filter-btn active" data-filter="all" style="
                        padding: 8px 16px;
                        border-radius: 10px;
                        font-size: 13px;
                        font-weight: 500;
                        background: var(--primary);
                        color: white;
                        border: none;
                        cursor: pointer;
                        white-space: nowrap;
                        transition: all 0.15s ease;
                    ">全部</button>
                    <button class="filter-btn" data-filter="completed" style="
                        padding: 8px 16px;
                        border-radius: 10px;
                        font-size: 13px;
                        font-weight: 500;
                        background: var(--bg-elevated);
                        color: var(--text-secondary);
                        border: 1px solid var(--divider);
                        cursor: pointer;
                        white-space: nowrap;
                        transition: all 0.15s ease;
                    ">已完成</button>
                    <button class="filter-btn" data-filter="failed" style="
                        padding: 8px 16px;
                        border-radius: 10px;
                        font-size: 13px;
                        font-weight: 500;
                        background: var(--bg-elevated);
                        color: var(--text-secondary);
                        border: 1px solid var(--divider);
                        cursor: pointer;
                        white-space: nowrap;
                        transition: all 0.15s ease;
                    ">失败</button>
                </div>

                <!-- 任务列表 -->
                <div id="historyList" style="display: flex; flex-direction: column; gap: 12px;">
                    <!-- 任务将在这里动态渲染 -->
                </div>

                <!-- 加载更多 -->
                <div id="loadMore" class="load-more hidden" style="margin-top: 16px; text-align: center;">
                    <button style="
                        padding: 12px 24px;
                        background: var(--bg-elevated);
                        color: var(--text-primary);
                        border: 1px solid var(--divider);
                        border-radius: 12px;
                        font-size: 14px;
                        font-weight: 500;
                        cursor: pointer;
                        transition: all 0.15s ease;
                    ">加载更多</button>
                </div>

                <!-- 空状态 -->
                <div id="emptyHistory" class="empty-history hidden" style="text-align: center; padding: 40px 20px;">
                    <svg width="48" height="48" fill="none" style="color: var(--text-muted); margin: 0 auto 12px;" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                    </svg>
                    <p style="font-size: 14px; color: var(--text-tertiary);">暂无历史任务</p>
                </div>
            </div>
        `;
    }

    bindEvents() {
        // 筛选器
        this.container.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const filter = btn.dataset.filter;
                this.setFilter(filter);
            });
            // 添加悬停效果
            btn.addEventListener('mouseenter', () => {
                if (!btn.classList.contains('active')) {
                    btn.style.background = 'var(--bg-card)';
                }
            });
            btn.addEventListener('mouseleave', () => {
                if (!btn.classList.contains('active')) {
                    btn.style.background = 'var(--bg-elevated)';
                }
            });
        });

        // 加载更多
        this.container.querySelector('#loadMore button')?.addEventListener('click', () => {
            this.loadMore();
        });
    }

    setFilter(filter) {
        // 更新按钮状态 - 深色主题
        this.container.querySelectorAll('.filter-btn').forEach(btn => {
            if (btn.dataset.filter === filter) {
                btn.classList.add('active');
                btn.style.background = 'var(--primary)';
                btn.style.color = 'white';
                btn.style.border = 'none';
            } else {
                btn.classList.remove('active');
                btn.style.background = 'var(--bg-elevated)';
                btn.style.color = 'var(--text-secondary)';
                btn.style.border = '1px solid var(--divider)';
            }
        });

        this.currentFilter = filter;
        this.page = 1;
        this.refresh();
    }

    async refresh() {
        try {
            const { getHistoryTasks } = await import('../api/client.js');

            // 根据筛选状态传递参数
            const status = this.currentFilter === 'all' ? null : this.currentFilter;
            const data = await getHistoryTasks(this.page, this.options.pageSize, status);

            this.setTasks(data.tasks || [], data.has_more || false);
        } catch (error) {
            console.error('加载历史任务失败:', error);
            // API 调用失败时使用空列表
            this.setTasks([], false);
        }
    }

    setTasks(tasks, hasMore = false) {
        this.tasks = tasks;
        this.hasMore = hasMore;
        this.renderTasks();
    }

    renderTasks() {
        const historyList = this.container.querySelector('#historyList');
        const emptyHistory = this.container.querySelector('#emptyHistory');
        const loadMore = this.container.querySelector('#loadMore');
        const taskCount = this.container.querySelector('#taskCount');

        // 更新计数
        if (taskCount) {
            taskCount.textContent = `共 ${this.tasks.length} 项`;
        }

        if (this.tasks.length === 0) {
            historyList.innerHTML = '';
            emptyHistory?.classList.remove('hidden');
            loadMore?.classList.add('hidden');
            return;
        }

        emptyHistory?.classList.add('hidden');

        // 渲染任务列表
        historyList.innerHTML = this.tasks.map(task => this.renderTaskItem(task)).join('');

        // 显示/隐藏加载更多
        if (this.hasMore) {
            loadMore?.classList.remove('hidden');
        } else {
            loadMore?.classList.add('hidden');
        }

        // 绑定任务点击和删除事件
        historyList.querySelectorAll('.task-item').forEach(item => {
            // 点击任务
            item.addEventListener('click', (e) => {
                if (!e.target.closest('.delete-btn')) {
                    const taskId = item.dataset.taskId;
                    this.options.onTaskClick(taskId);
                }
            });

            // 悬停效果
            item.addEventListener('mouseenter', () => {
                item.style.background = 'var(--bg-elevated)';
                item.style.borderColor = 'var(--primary)';
            });
            item.addEventListener('mouseleave', () => {
                item.style.background = 'var(--bg-card)';
                item.style.borderColor = 'var(--divider)';
            });

            // 删除按钮
            const deleteBtn = item.querySelector('.delete-btn');
            if (deleteBtn) {
                deleteBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const taskId = item.dataset.taskId;
                    this.handleDelete(taskId);
                });
                deleteBtn.addEventListener('mouseenter', () => {
                    deleteBtn.style.background = 'var(--error-bg)';
                    deleteBtn.querySelector('svg').style.color = 'var(--error)';
                });
                deleteBtn.addEventListener('mouseleave', () => {
                    deleteBtn.style.background = 'transparent';
                    deleteBtn.querySelector('svg').style.color = 'var(--text-tertiary)';
                });
            }
        });
    }

    renderTaskItem(task) {
        const statusText = getStatusText(task.status);
        const statusClass = getStatusColorClass(task.status);

        // 深色主题状态颜色
        const statusColors = {
            completed: 'var(--success)',
            failed: 'var(--error)',
            pending: 'var(--warning)',
            processing: 'var(--primary)',
        };

        const statusColor = statusColors[task.status] || 'var(--text-secondary)';

        return `
            <div class="task-item" data-task-id="${task.task_id}" style="
                background: var(--bg-card);
                border-radius: 14px;
                padding: 14px;
                cursor: pointer;
                border: 1px solid var(--divider);
                transition: all 0.15s ease;
            ">
                <div style="display: flex; align-items: flex-start; justify-content: space-between;">
                    <div style="flex: 1; min-width: 0;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <h4 style="font-size: 15px; font-weight: 500; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${task.name || '未命名任务'}</h4>
                            ${task.status === 'completed' ? `
                                <span style="
                                    display: inline-flex;
                                    align-items: center;
                                    padding: 2px 8px;
                                    border-radius: 6px;
                                    font-size: 11px;
                                    font-weight: 500;
                                    background: var(--success-bg);
                                    color: var(--success);
                                ">
                                    <svg width="10" height="10" fill="currentColor" viewBox="0 0 20 20" style="margin-right: 4px;">
                                        <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
                                    </svg>
                                    已完成
                                </span>
                            ` : ''}
                        </div>
                        <p style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">${formatTime(task.created_at)}</p>
                        ${task.duration ? `
                            <p style="font-size: 12px; color: var(--text-tertiary); margin-top: 4px;">时长: ${task.duration}</p>
                        ` : ''}
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px; margin-left: 8px;">
                        <span style="
                            padding: 4px 10px;
                            border-radius: 8px;
                            font-size: 12px;
                            font-weight: 500;
                            background: ${statusColor}20;
                            color: ${statusColor};
                        ">${statusText}</span>
                        <button class="delete-btn" style="
                            padding: 6px;
                            background: transparent;
                            border: none;
                            border-radius: 8px;
                            cursor: pointer;
                            transition: all 0.15s ease;
                        ">
                            <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="color: var(--text-tertiary);">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                            </svg>
                        </button>
                    </div>
                </div>

                ${task.error ? `
                    <div style="
                        margin-top: 12px;
                        padding: 10px;
                        background: var(--error-bg);
                        border-radius: 10px;
                    ">
                        <p style="font-size: 12px; color: var(--error);">${task.error}</p>
                    </div>
                ` : ''}

                ${task.summary ? `
                    <div style="
                        margin-top: 12px;
                        padding: 12px;
                        background: var(--bg-secondary);
                        border-radius: 10px;
                    ">
                        <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.5; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;">${task.summary}</p>
                    </div>
                ` : ''}
            </div>
        `;
    }

    async handleDelete(taskId) {
        // 确认对话框
        const confirmed = confirm('确定要删除这个任务吗？');
        if (!confirmed) return;

        try {
            await this.options.onTaskDelete(taskId);
            this.tasks = this.tasks.filter(t => t.task_id !== taskId);
            this.renderTasks();
        } catch (error) {
            console.error('删除任务失败:', error);
        }
    }

    async loadMore() {
        this.page += 1;
        try {
            const { getHistoryTasks } = await import('../api/client.js');
            const status = this.currentFilter === 'all' ? null : this.currentFilter;
            const data = await getHistoryTasks(this.page, this.options.pageSize, status);
            this.tasks = [...this.tasks, ...(data.tasks || [])];
            this.hasMore = data.has_more || false;
            this.renderTasks();
        } catch (error) {
            console.error('加载更多任务失败:', error);
        }
    }

    destroy() {
        this.container.innerHTML = '';
    }
}
