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
        this.currentFilter = 'completed';  // 只显示已完成的任务
        this.init();
    }

    init() {
        this.render();
        this.bindEvents();
        this.selectedTaskId = null;  // 当前选中的任务 ID
    }

    render() {
        this.container.innerHTML = `
            <div class="task-history" style="padding: 16px;">
                <!-- 统计信息卡片 -->
                <div id="statsCard" style="
                    display: flex;
                    align-items: center;
                    justify-content: space-around;
                    padding: 16px;
                    margin-bottom: 16px;
                    background: var(--bg-elevated);
                    border-radius: 14px;
                    border: 1px solid var(--divider);
                ">
                    <div style="text-align: center;">
                        <p id="totalCount" style="font-size: 24px; font-weight: 600; color: var(--primary);">-</p>
                        <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">总任务</p>
                    </div>
                    <div style="width: 1px; height: 32px; background: var(--divider);"></div>
                    <div style="text-align: center;">
                        <p id="completedCount" style="font-size: 24px; font-weight: 600; color: var(--success);">-</p>
                        <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">已完成</p>
                    </div>
                    <div style="width: 1px; height: 32px; background: var(--divider);"></div>
                    <div style="text-align: center;">
                        <p id="failedCount" style="font-size: 24px; font-weight: 600; color: var(--error);">-</p>
                        <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px;">失败</p>
                    </div>
                </div>

                <!-- 标题区域 -->
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;">
                    <h3 style="font-size: 16px; font-weight: 600; color: var(--text-primary);">已完成任务</h3>
                    <span id="taskCount" style="font-size: 13px; color: var(--text-secondary);"></span>
                </div>

                <!-- 确认按钮（选中任务后显示） -->
                <button id="confirmViewBtn" class="hidden" style="
                    width: 100%;
                    padding: 14px;
                    background: var(--primary-gradient);
                    color: white;
                    border: none;
                    border-radius: 12px;
                    font-size: 15px;
                    font-weight: 600;
                    cursor: pointer;
                    margin-bottom: 16px;
                    box-shadow: 0 4px 12px rgba(47, 124, 246, 0.3);
                    transition: all 0.15s ease;
                ">查看选中任务</button>

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
                    <p style="font-size: 14px; color: var(--text-tertiary);">暂无已完成的分析</p>
                </div>
            </div>
        `;
    }

    bindEvents() {
        // 加载更多
        this.container.querySelector('#loadMore button')?.addEventListener('click', () => {
            this.loadMore();
        });
    }

    setFilter(filter) {
        // 内部使用：设置筛选状态（只支持 completed）
        this.currentFilter = filter;
        this.page = 1;
        this.refresh();
    }

    async refresh() {
        try {
            const { getHistoryTasks } = await import('../api/client.js');

            // 首先加载所有任务（不限状态）用于统计
            try {
                const allTasksData = await getHistoryTasks(1, 1000, null); // 获取大量任务用于统计
                this.updateStats(allTasksData.tasks || []);
            } catch (statsError) {
                console.error('加载统计数据失败:', statsError);
            }

            // 然后根据筛选状态加载要显示的任务
            const status = this.currentFilter === 'all' ? null : this.currentFilter;
            const data = await getHistoryTasks(this.page, this.options.pageSize, status);

            this.setTasks(data.tasks || [], data.has_more || false);
        } catch (error) {
            console.error('加载历史任务失败:', error);
            // API 调用失败时使用空列表
            this.setTasks([], false);
        }
    }

    updateStats(tasks) {
        const totalCount = tasks.length;
        const completedCount = tasks.filter(t => t.status === 'completed').length;
        const failedCount = tasks.filter(t => t.status === 'failed').length;

        const totalCountEl = this.container.querySelector('#totalCount');
        const completedCountEl = this.container.querySelector('#completedCount');
        const failedCountEl = this.container.querySelector('#failedCount');

        if (totalCountEl) totalCountEl.textContent = totalCount;
        if (completedCountEl) completedCountEl.textContent = completedCount;
        if (failedCountEl) failedCountEl.textContent = failedCount;
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
        this.bindTaskEvents(historyList);
    }

    /**
     * 在指定父元素上绑定任务项事件
     * 用于 drawer 内容更新后重新绑定事件
     */
    bindTaskEvents(parentElement) {
        if (!parentElement) return;

        // 绑定确认查看按钮
        const confirmBtn = parentElement.querySelector('#confirmViewBtn');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', () => {
                if (this.selectedTaskId) {
                    this.options.onTaskClick(this.selectedTaskId);
                }
            });
        }

        parentElement.querySelectorAll('.task-item').forEach(item => {
            // 移除旧的事件监听器（如果有）
            item.cloneNode(true);

            // 点击任务 - 选中高亮（不立即加载详情）
            const handleTaskClick = (e) => {
                // 阻止默认行为防止双重触发
                if (e.type === 'touchend') {
                    e.preventDefault();
                }
                if (!e.target.closest('.delete-btn')) {
                    const taskId = item.dataset.taskId;
                    this.selectTask(taskId, parentElement);
                }
            };

            item.addEventListener('click', handleTaskClick);
            item.addEventListener('touchend', handleTaskClick, { passive: false });

            // 悬停效果（仅桌面端）- 只在未选中时应用
            item.addEventListener('mouseenter', () => {
                if (this.selectedTaskId !== item.dataset.taskId) {
                    item.style.background = 'var(--bg-elevated)';
                    item.style.borderColor = 'var(--primary)';
                }
            });
            item.addEventListener('mouseleave', () => {
                if (this.selectedTaskId !== item.dataset.taskId) {
                    item.style.background = 'var(--bg-card)';
                    item.style.borderColor = 'var(--divider)';
                }
            });

            // 删除按钮
            const deleteBtn = item.querySelector('.delete-btn');
            if (deleteBtn) {
                const handleDeleteClick = (e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    const taskId = item.dataset.taskId;
                    this.handleDelete(taskId);
                };

                deleteBtn.addEventListener('click', handleDeleteClick);
                deleteBtn.addEventListener('touchend', handleDeleteClick, { passive: false });

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

        // 绑定加载更多按钮
        const loadMoreBtn = parentElement.querySelector('#loadMore button');
        if (loadMoreBtn) {
            loadMoreBtn.addEventListener('click', () => this.loadMore());
        }
    }

    /**
     * 选中任务（高亮显示）
     */
    selectTask(taskId, parentElement) {
        this.selectedTaskId = taskId;

        // 更新所有任务项的样式
        parentElement.querySelectorAll('.task-item').forEach(item => {
            if (item.dataset.taskId === taskId) {
                // 选中的任务项
                item.style.background = 'var(--primary-bg)';
                item.style.borderColor = 'var(--primary)';
                // 让文字变为白色
                item.querySelectorAll('h4, p, span').forEach(el => {
                    el.style.color = 'var(--primary)';
                });
            } else {
                // 其他任务项恢复默认样式
                item.style.background = 'var(--bg-card)';
                item.style.borderColor = 'var(--divider)';
                item.querySelectorAll('h4, p, span').forEach(el => {
                    el.style.color = '';
                });
            }
        });

        // 显示确认按钮
        const confirmBtn = parentElement.querySelector('#confirmViewBtn');
        if (confirmBtn) {
            confirmBtn.classList.remove('hidden');
        }
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
                    <div style="display: flex; align-items: center; margin-left: 8px;">
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
            // 刷新统计数据
            await this.refresh();
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
