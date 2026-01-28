# AI 乒乓球教练 - 前端

深色高端移动端风格的乒乓球 AI 教练分析应用。

## 技术栈

- **构建工具**: Vite
- **语言**: 原生 JavaScript (ES6 Modules)
- **样式**: Tailwind CSS (CDN) + 深色主题
- **通信**: Fetch API + WebSocket

## 开发环境启动

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

访问: http://localhost:5173

## 环境配置

创建 `.env` 文件:

```env
VITE_API_URL=http://localhost:8000
```

## 项目结构

```
src/
├── api/
│   └── client.js          # API 客户端
├── components/
│   ├── VideoUploader.js   # 视频上传组件
│   ├── TaskHistory.js     # 历史任务组件
│   ├── Drawer.js          # 抽屉组件
│   ├── TaskQueue.js       # 任务队列组件
│   └── AnalysisResult.js  # 分析结果组件
├── styles/
│   └── theme-dark.css     # 深色主题样式
├── utils/
│   └── helpers.js         # 工具函数
└── main.js                # 应用入口
```

## API 接口

- `POST /api/upload` - 上传视频
- `POST /api/analyze` - 开始分析
- `GET /api/results/{task_id}` - 获取分析结果
- `GET /api/history` - 获取历史任务
- `GET /api/queue` - 获取任务队列
- `DELETE /api/tasks/{task_id}` - 删除任务
- `WS /ws/tasks/{task_id}` - WebSocket 实时更新

## 构建生产版本

```bash
npm run build
```

构建产物输出到 `dist/` 目录。

## 设计风格

### 深色主题配色

- 主背景: `#0E1117`
- 卡片背景: `#1A1E27`
- 主色调: `#2F7CF6` (科技蓝)
- 成功: `#34D399`
- 警告: `#FBBF24`
- 错误: `#F87171`

### 交互流程

1. 上传视频 → 预览
2. 点击"开始分析" → 上传到服务器
3. 连接 WebSocket → 实时接收进度
4. 分析完成 → 展示结果
5. 分享/下载结果
