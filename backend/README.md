# AI 乒乓球教练 - FastAPI 后端

基于 FastAPI 的后端服务，提供视频上传、分析任务管理、结果查询等 API。

## 技术栈

- **框架**: FastAPI 0.115+
- **服务器**: Uvicorn
- **通信**: WebSocket

## 安装依赖

```bash
pip install -r requirements.txt
```

## 启动服务

```bash
# 开发模式（自动重载）
cd backend/src
python main.py

# 或使用 uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## API 文档

启动服务后访问：

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API 端点

### 1. 上传视频

```
POST /api/upload
```

上传视频文件，创建分析任务。

**请求**:
- Content-Type: `multipart/form-data`
- Body: `file` (视频文件)

**响应**:
```json
{
  "success": true,
  "task_id": "video_abc123",
  "message": "视频上传成功",
  "task": {
    "task_id": "video_abc123",
    "name": "video.mp4",
    "status": "queued",
    "progress": 0,
    "created_at": "2025-01-28T12:00:00"
  }
}
```

### 2. 开始分析

```
POST /api/analyze
```

启动指定任务的分析流程。

**请求**:
```json
{
  "task_id": "video_abc123"
}
```

**响应**:
```json
{
  "success": true,
  "message": "分析任务已启动",
  "task_id": "video_abc123"
}
```

### 3. 获取分析结果

```
GET /api/results/{task_id}
```

获取任务的完整分析结果。

**响应**:
```json
{
  "task_id": "video_abc123",
  "status": "completed",
  "created_at": "2025-01-28T12:00:00",
  "summary": {
    "overview": "整体评价...",
    "strengths": ["优点1", "优点2"],
    "weaknesses": ["缺点1", "缺点2"]
  },
  "key_frames": [
    {
      "frame_number": 1,
      "url": "/api/frames/xxx.jpg",
      "description": "动作描述"
    }
  ],
  "overall_score": 78
}
```

### 4. 获取历史任务

```
GET /api/history?page=1&limit=20&status=completed
```

获取历史任务列表，支持分页和状态筛选。

**响应**:
```json
{
  "tasks": [...],
  "total": 100,
  "page": 1,
  "limit": 20,
  "has_more": true
}
```

### 5. 获取任务队列

```
GET /api/queue
```

获取当前排队和处理中的任务。

**响应**:
```json
{
  "tasks": [...],
  "total": 5
}
```

### 6. 获取任务状态

```
GET /api/tasks/{task_id}/status
```

获取任务的当前状态和进度。

**响应**:
```json
{
  "task_id": "video_abc123",
  "name": "video.mp4",
  "status": "processing",
  "progress": 60,
  "stage": "AI 分析中",
  "created_at": "2025-01-28T12:00:00",
  "updated_at": "2025-01-28T12:05:00"
}
```

### 7. 删除任务

```
DELETE /api/tasks/{task_id}
```

删除指定任务及其相关文件。

**响应**:
```json
{
  "success": true,
  "message": "任务已删除"
}
```

### 8. WebSocket 实时更新

```
WS /ws/tasks/{task_id}
```

建立 WebSocket 连接，实时接收任务状态更新。

**消息格式**:
```json
{
  "id": "video_abc123",
  "status": "processing",
  "progress": 45,
  "stage": "计算特征中"
}
```

## 任务状态

- `pending`: 等待中
- `queued`: 排队中
- `processing`: 处理中
- `extracting`: 视频抽帧中
- `computing`: 计算特征中
- `analyzing`: AI 分析中
- `completed`: 已完成
- `failed`: 失败

## 数据存储

任务数据存储在 `data/runs/` 目录下：

```
data/runs/
└── {task_id}/
    ├── input.mp4         # 上传的视频
    ├── status.json       # 任务状态
    ├── frames/           # 抽取的帧
    ├── features.json     # 计算的特征
    └── analysis.json     # AI 分析结果
```

## 扩展说明

当前后端使用模拟分析流程用于演示。要接入真实分析，需要：

1. 实现视频抽帧逻辑
2. 实现特征计算逻辑
3. 接入大模型进行 AI 分析

修改 `simulate_analysis()` 函数即可。
