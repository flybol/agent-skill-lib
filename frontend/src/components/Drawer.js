/**
 * Drawer 抽屉组件 - 深色主题
 * 用于从侧边滑出的面板，常用于显示详细信息或设置
 */

export class Drawer {
    constructor(options = {}) {
        this.options = {
            position: 'right', // 'left' | 'right' | 'top' | 'bottom'
            size: 'medium',    // 'small' | 'medium' | 'large' | 'full'
            overlay: true,
            closeOnOverlayClick: true,
            closeOnEsc: true,
            onClose: () => {},
            ...options,
        };

        this.isOpen = false;
        this.content = '';
        this.init();
    }

    init() {
        this.createDrawer();
    }

    createDrawer() {
        // 创建抽屉容器
        this.drawer = document.createElement('div');
        this.drawer.className = 'drawer fixed inset-0 z-50 pointer-events-none';
        this.drawer.innerHTML = `
            <div class="drawer-overlay absolute inset-0 opacity-0 transition-opacity duration-300" style="
                background: rgba(0, 0, 0, 0.6);
                backdrop-filter: blur(4px);
            "></div>
            <div class="drawer-content absolute ${this.getPositionClasses()} transition-transform duration-300 pointer-events-auto" style="
                background: var(--bg-card);
                box-shadow: -8px 0 32px rgba(0, 0, 0, 0.4);
            ">
                <div class="drawer-header" style="
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 16px;
                    border-bottom: 1px solid var(--divider);
                ">
                    <h3 id="drawerTitle" style="
                        font-size: 16px;
                        font-weight: 600;
                        color: var(--text-primary);
                    "></h3>
                    <button id="drawerCloseBtn" style="
                        padding: 8px;
                        background: transparent;
                        border: none;
                        border-radius: 10px;
                        cursor: pointer;
                        transition: all 0.15s ease;
                    ">
                        <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="color: var(--text-secondary);">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>
                <div id="drawerBody" class="drawer-body" style="
                    overflow-y: auto;
                    max-height: calc(100vh - 60px);
                "></div>
            </div>
        `;

        document.body.appendChild(this.drawer);
        this.bindEvents();
    }

    getPositionClasses() {
        const positionMap = {
            'left': 'top-0 left-0 h-full w-full max-w-md transform -translate-x-full',
            'right': 'top-0 right-0 h-full w-full max-w-md transform translate-x-full',
            'top': 'top-0 left-0 right-0 w-full max-h-96 transform -translate-y-full',
            'bottom': 'bottom-0 left-0 right-0 w-full max-h-96 transform translate-y-full safe-bottom',
        };

        const sizeMap = {
            'small': 'max-w-sm',
            'medium': 'max-w-md',
            'large': 'max-w-lg',
            'full': 'max-w-full',
        };

        let classes = positionMap[this.options.position] || positionMap['right'];

        if (this.options.position === 'left' || this.options.position === 'right') {
            classes = classes.replace('max-w-md', sizeMap[this.options.size] || sizeMap['medium']);
        }

        return classes;
    }

    bindEvents() {
        // 关闭按钮
        const closeBtn = this.drawer.querySelector('#drawerCloseBtn');
        closeBtn.addEventListener('click', () => {
            this.close();
        });

        // 添加悬停效果
        closeBtn.addEventListener('mouseenter', () => {
            closeBtn.style.background = 'var(--bg-elevated)';
        });
        closeBtn.addEventListener('mouseleave', () => {
            closeBtn.style.background = 'transparent';
        });

        // 遮罩点击关闭
        if (this.options.closeOnOverlayClick) {
            this.drawer.querySelector('.drawer-overlay').addEventListener('click', () => {
                this.close();
            });
        }

        // ESC 键关闭
        if (this.options.closeOnEsc) {
            this.handleEsc = (e) => {
                if (e.key === 'Escape' && this.isOpen) {
                    this.close();
                }
            };
            document.addEventListener('keydown', this.handleEsc);
        }
    }

    open(title, content) {
        this.isOpen = true;
        this.content = content;

        // 设置内容
        this.drawer.querySelector('#drawerTitle').textContent = title;
        this.drawer.querySelector('#drawerBody').innerHTML = content;

        // 显示遮罩
        if (this.options.overlay) {
            this.drawer.querySelector('.drawer-overlay').classList.remove('opacity-0');
        }

        // 滑入内容
        const contentEl = this.drawer.querySelector('.drawer-content');
        contentEl.classList.remove('-translate-x-full', 'translate-x-full', '-translate-y-full', 'translate-y-full');

        // 启用指针事件
        this.drawer.classList.remove('pointer-events-none');

        // 防止背景滚动
        document.body.style.overflow = 'hidden';
    }

    close() {
        this.isOpen = false;

        // 隐藏遮罩
        if (this.options.overlay) {
            this.drawer.querySelector('.drawer-overlay').classList.add('opacity-0');
        }

        // 滑出内容
        const contentEl = this.drawer.querySelector('.drawer-content');
        const position = this.options.position;
        if (position === 'left') {
            contentEl.classList.add('-translate-x-full');
        } else if (position === 'right') {
            contentEl.classList.add('translate-x-full');
        } else if (position === 'top') {
            contentEl.classList.add('-translate-y-full');
        } else if (position === 'bottom') {
            contentEl.classList.add('translate-y-full');
        }

        // 禁用指针事件
        this.drawer.classList.add('pointer-events-none');

        // 恢复背景滚动
        document.body.style.overflow = '';

        // 触发回调
        this.options.onClose();
    }

    setContent(content) {
        this.content = content;
        this.drawer.querySelector('#drawerBody').innerHTML = content;
    }

    setTitle(title) {
        this.drawer.querySelector('#drawerTitle').textContent = title;
    }

    destroy() {
        if (this.handleEsc) {
            document.removeEventListener('keydown', this.handleEsc);
        }
        this.drawer.remove();
    }
}

/**
 * 确认对话框 Drawer - 深色主题
 */
export class ConfirmDrawer {
    constructor(options = {}) {
        this.options = {
            title: '确认',
            message: '',
            confirmText: '确认',
            cancelText: '取消',
            onConfirm: () => {},
            onCancel: () => {},
            ...options,
        };

        this.drawer = new Drawer({
            position: 'bottom',
            size: 'small',
            onClose: () => this.options.onCancel(),
        });
    }

    show(message) {
        this.options.message = message;

        const content = `
            <div style="padding: 24px;">
                <p style="color: var(--text-primary); font-size: 15px; line-height: 1.5; margin-bottom: 24px;">${message}</p>
                <div style="display: flex; gap: 12px;">
                    <button id="cancelBtn" style="
                        flex: 1;
                        padding: 14px 16px;
                        background: var(--bg-elevated);
                        color: var(--text-primary);
                        border: 1px solid var(--divider);
                        border-radius: 12px;
                        font-size: 15px;
                        font-weight: 500;
                        cursor: pointer;
                        transition: all 0.15s ease;
                    ">${this.options.cancelText}</button>
                    <button id="confirmBtn" style="
                        flex: 1;
                        padding: 14px 16px;
                        background: var(--primary-gradient);
                        color: white;
                        border: none;
                        border-radius: 12px;
                        font-size: 15px;
                        font-weight: 600;
                        cursor: pointer;
                        transition: all 0.15s ease;
                        box-shadow: 0 4px 12px rgba(47, 124, 246, 0.3);
                    ">${this.options.confirmText}</button>
                </div>
            </div>
        `;

        this.drawer.open(this.options.title, content);

        // 绑定按钮事件
        const drawerEl = this.drawer.drawer;
        drawerEl.querySelector('#confirmBtn').addEventListener('click', () => {
            this.drawer.close();
            this.options.onConfirm();
        });

        drawerEl.querySelector('#cancelBtn').addEventListener('click', () => {
            this.drawer.close();
        });
    }

    destroy() {
        this.drawer.destroy();
    }
}
