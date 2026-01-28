/**
 * API 客户端 - 处理所有后端 API 调用
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// 调试：输出 API 地址
console.log('API Base URL:', API_BASE_URL);

/**
 * 创建 API 请求
 */
async function apiRequest(endpoint, options = {}) {
    const url = `${API_BASE_URL}${endpoint}`;
    console.log('API Request:', url, options);

    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };

    const config = { ...defaultOptions, ...options };

    try {
        const response = await fetch(url, config);
        console.log('API Response status:', response.status);

        const data = await response.json();
        console.log('API Response data:', data);

        if (!response.ok) {
            throw new Error(data.message || '请求失败');
        }

        return data;
    } catch (error) {
        console.error('API 请求错误:', error);
        throw error;
    }
}

/**
 * 视频上传 API
 */
export async function uploadVideo(file, onProgress) {
    const url = `${API_BASE_URL}/api/upload`;
    console.log('上传视频开始:', url, '文件名:', file.name, '文件大小:', file.size);

    const formData = new FormData();
    formData.append('file', file);  // 后端参数名是 'file'

    // 创建超时控制器（30秒超时）
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);

    try {
        console.log('发起 fetch 请求...');
        const response = await fetch(url, {
            method: 'POST',
            body: formData,
            signal: controller.signal,
        });

        clearTimeout(timeoutId);

        console.log('上传响应状态:', response.status, response.statusText);
        console.log('上传响应头:', [...response.headers.entries()]);

        // 处理非 JSON 响应或错误响应
        const contentType = response.headers.get('content-type');
        console.log('响应 Content-Type:', contentType);

        let data;
        if (contentType && contentType.includes('application/json')) {
            data = await response.json();
            console.log('响应数据:', data);
        } else {
            const text = await response.text();
            console.log('非 JSON 响应内容:', text);
            data = { message: text || '上传失败' };
        }

        if (!response.ok) {
            console.error('上传失败:', data);
            throw new Error(data.message || data.detail || '上传失败');
        }

        console.log('上传成功:', data);
        return data;

    } catch (error) {
        clearTimeout(timeoutId);

        // 处理不同类型的错误
        if (error.name === 'AbortError') {
            console.error('上传超时:', error);
            throw new Error('上传超时，请检查网络连接或后端服务是否运行');
        } else if (error instanceof TypeError && error.message.includes('fetch')) {
            console.error('网络错误:', error);
            throw new Error('网络连接失败，请检查后端服务是否运行');
        } else {
            console.error('上传异常:', error);
            throw error;
        }
    }
}

/**
 * 开始分析 API
 */
export async function startAnalysis(taskId) {
    return apiRequest('/api/analyze', {
        method: 'POST',
        body: JSON.stringify({ task_id: taskId }),
    });
}

/**
 * 预处理视频 API - 检测目标运动员
 */
export async function preprocessVideo(taskId) {
    return apiRequest(`/api/preprocess/${taskId}`);
}

/**
 * 获取分析结果 API
 */
export async function getAnalysisResult(taskId) {
    return apiRequest(`/api/results/${taskId}`);
}

/**
 * 获取历史任务列表 API
 */
export async function getHistoryTasks(page = 1, limit = 20, status = null) {
    const params = new URLSearchParams({
        page: page.toString(),
        limit: limit.toString(),
    });
    if (status) {
        params.append('status', status);
    }
    return apiRequest(`/api/history?${params.toString()}`);
}

/**
 * 获取任务队列 API
 */
export async function getTaskQueue() {
    return apiRequest('/api/queue');
}

/**
 * 刷新任务状态 API
 */
export async function refreshTaskStatus(taskId) {
    return apiRequest(`/api/tasks/${taskId}/status`);
}

/**
 * 删除任务 API
 */
export async function deleteTask(taskId) {
    return apiRequest(`/api/tasks/${taskId}`, {
        method: 'DELETE',
    });
}

/**
 * WebSocket 连接 - 实时接收任务状态更新
 */
export function connectTaskWebSocket(taskId, onMessage, onError) {
    const wsUrl = `${API_BASE_URL.replace('http', 'ws')}/ws/tasks/${taskId}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket 连接已建立');
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            onMessage(data);
        } catch (error) {
            console.error('WebSocket 消息解析错误:', error);
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket 错误:', error);
        onError?.(error);
    };

    ws.onclose = () => {
        console.log('WebSocket 连接已关闭');
    };

    return ws;
}

export default {
    uploadVideo,
    preprocessVideo,
    startAnalysis,
    getAnalysisResult,
    getHistoryTasks,
    getTaskQueue,
    refreshTaskStatus,
    deleteTask,
    connectTaskWebSocket,
};
