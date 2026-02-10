/**
 * 工具函数
 */

/**
 * 格式化文件大小
 */
export function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * 格式化时间
 */
export function formatTime(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now - date;

    if (diff < 60000) return '刚刚';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)}天前`;

    return date.toLocaleDateString('zh-CN');
}

/**
 * 格式化持续时间
 */
export function formatDuration(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

/**
 * 获取状态文本
 */
export function getStatusText(status) {
    const statusMap = {
        pending: '等待中',
        queued: '排队中',
        processing: '处理中',
        extracting: '抽帧中',
        computing: '计算特征',
        analyzing: 'AI 分析中',
        completed: '已完成',
        failed: '失败',
    };
    return statusMap[status] || status;
}

/**
 * 获取状态颜色类
 */
export function getStatusColorClass(status) {
    const colorMap = {
        pending: 'status-pending',
        queued: 'status-pending',
        processing: 'status-processing',
        extracting: 'status-processing',
        computing: 'status-processing',
        analyzing: 'status-processing',
        completed: 'status-completed',
        failed: 'status-failed',
    };
    return colorMap[status] || '';
}

/**
 * 防抖函数
 */
export function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * 节流函数
 */
export function throttle(func, limit) {
    let inThrottle;
    return function (...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

/**
 * 生成唯一 ID
 */
export function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2);
}

/**
 * 下载文件
 */
export function downloadFile(url, filename) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

/**
 * 复制到剪贴板（支持多种浏览器的降级方案）
 */
export async function copyToClipboard(text) {
    // 方法1：使用 Clipboard API（需要 HTTPS 或 localhost）
    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(text);
            return true;
        } catch (err) {
            console.log('Clipboard API 失败，尝试降级方案:', err);
        }
    }

    // 方法2：使用传统的 execCommand（兼容性更好）
    try {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();

        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);

        if (successful) {
            return true;
        }
    } catch (err) {
        console.error('execCommand 复制失败:', err);
    }

    // 所有方法都失败
    console.error('复制失败：所有方法均不可用');
    return false;
}

/**
 * 验证视频文件
 */
export function validateVideoFile(file, duration = null) {
    const validTypes = ['video/mp4', 'video/quicktime', 'video/x-msvideo'];
    const maxSize = 20 * 1024 * 1024; // 20MB

    if (!validTypes.includes(file.type)) {
        throw new Error('仅支持 MP4、MOV、AVI 格式的视频');
    }

    if (file.size > maxSize) {
        throw new Error('视频文件大小不能超过 20MB');
    }

    // 验证视频时长（如果提供了时长信息）
    // 实际校验使用 6 秒，容错处理边界情况
    // 错误提示仍显示 5 秒，给用户更好的体验
    if (duration !== null && duration > 6.0) {
        throw new Error(`视频时长不能超过 5 秒（当前视频：${duration.toFixed(1)} 秒）`);
    }

    return true;
}

/**
 * 获取视频时长
 * @param {File} file - 视频文件
 * @returns {Promise<number>} 视频时长（秒）
 */
export function getVideoDuration(file) {
    return new Promise((resolve, reject) => {
        const video = document.createElement('video');
        video.preload = 'metadata';

        video.onloadedmetadata = () => {
            URL.revokeObjectURL(video.src);
            resolve(video.duration);
        };

        video.onerror = () => {
            URL.revokeObjectURL(video.src);
            reject(new Error('无法读取视频时长'));
        };

        video.src = URL.createObjectURL(file);
    });
}

/**
 * 解析 JSON 安全包装
 */
export function safeJsonParse(str, defaultValue = null) {
    try {
        return JSON.parse(str);
    } catch {
        return defaultValue;
    }
}
