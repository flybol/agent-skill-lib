/**
 * 目标球员位置选择组件
 * 下拉选择：左侧、右侧、前方、后方
 */

export class TargetPlayerConfirm {
    constructor(container, options = {}) {
        this.container = typeof container === 'string'
            ? document.querySelector(container)
            : container;
        this.options = {
            onConfirm: (choice) => { },
            ...options,
        };
        this.selectedChoice = 'single_player'; // 默认单人训练
        this.init();
    }

    init() {
        this.render();
    }

    show() {
        const wrapper = this.container.querySelector('.player-position-select-wrapper');
        if (wrapper) {
            wrapper.classList.remove('hidden');
        }
    }

    hide() {
        const wrapper = this.container.querySelector('.player-position-select-wrapper');
        if (wrapper) {
            wrapper.classList.add('hidden');
        }
    }

    getChoice() {
        return this.selectedChoice;
    }

    render() {
        this.container.innerHTML = `
            <div class="player-position-select-wrapper">
                <div style="display: flex; align-items: center; gap: 12px;">
                    <!-- 标签 -->
                    <span style="font-size: 14px; color: var(--text-secondary); white-space: nowrap;">球员位置</span>

                    <!-- 下拉选择器 -->
                    <div style="flex: 1; position: relative;">
                        <select id="playerPositionSelect" style="
                            width: 100%;
                            padding: 10px 32px 10px 12px;
                            font-size: 14px;
                            font-weight: 500;
                            color: var(--text-primary);
                            background: var(--bg-elevated);
                            border: 1px solid var(--divider);
                            border-radius: 10px;
                            cursor: pointer;
                            transition: all 0.15s ease;
                            appearance: none;
                            -webkit-appearance: none;
                            -moz-appearance: none;
                        ">
                            <option value="single_player" selected>单人训练</option>
                            <option value="left">左侧球员</option>
                            <option value="right">右侧球员</option>
                            <option value="front">前方球员</option>
                            <option value="back">后方球员</option>
                        </select>
                        <!-- 下拉箭头 -->
                        <svg style="position: absolute; right: 10px; top: 50%; transform: translateY(-50%); pointer-events: none;" width="12" height="12" fill="none" stroke="var(--text-secondary)" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </div>
                </div>
            </div>
        `;

        // 绑定事件
        const select = this.container.querySelector('#playerPositionSelect');

        select.addEventListener('change', (e) => {
            this.selectedChoice = e.target.value;
        });
    }
}
