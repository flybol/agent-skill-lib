"""
AI 乒乓球教练 - FastAPI 后端
提供视频上传、分析任务管理、结果查询等 API
"""

import os
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Optional, List
from pathlib import Path
from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    BackgroundTasks,
    Depends,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager

# 导入分析步骤和agent
from .steps import extract_frames, compute_features, run_full_analysis
from .agent import get_mock_report
from .player_detector import detect_target_player
from .constants import (
    AGENT_MODE_MOCK,
    AGENT_MODE_REAL,
    MAX_FRAMES,
    FRAMES_PER_SEGMENT,
    DEFAULT_NUM_SEGMENTS,
)
from .errors import AnalysisError

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载 .env 文件（从 backend 目录）
BACKEND_DIR = Path(__file__).resolve().parent.parent

print(f"Loading .env from {BACKEND_DIR.as_posix()}")
load_dotenv(BACKEND_DIR / ".env")

# 项目根目录
BASE_DIR = BACKEND_DIR
DATA_DIR = BASE_DIR / "data"
RUNS_DIR = DATA_DIR / "runs"

# 确保目录存在
RUNS_DIR.mkdir(parents=True, exist_ok=True)


# ============ 数据模型 ============


class TaskStatus(BaseModel):
    """任务状态"""

    pending: str = "pending"
    queued: str = "queued"
    processing: str = "processing"
    extracting: str = "extracting"
    computing: str = "computing"
    analyzing: str = "analyzing"
    completed: str = "completed"
    failed: str = "failed"


class TaskResponse(BaseModel):
    """任务响应"""

    task_id: str
    name: str
    status: str
    progress: int = 0
    stage: Optional[str] = None
    created_at: str
    updated_at: str
    error: Optional[str] = None
    summary: Optional[str] = None


class UploadResponse(BaseModel):
    """上传响应"""

    success: bool
    task_id: str
    message: str
    task: TaskResponse


class AnalysisRequest(BaseModel):
    """分析请求"""

    task_id: str


class AnalysisResponse(BaseModel):
    """分析响应"""

    success: bool
    message: str
    task_id: str


class TaskListResponse(BaseModel):
    """任务列表响应"""

    tasks: List[TaskResponse]
    total: int
    page: int
    limit: int
    has_more: bool


class AnalysisResult(BaseModel):
    """分析结果详情"""

    task_id: str
    status: str
    created_at: str
    summary: Optional[dict] = None
    key_frames: Optional[List[dict]] = None
    details: Optional[dict] = None
    suggestions: Optional[List[dict]] = None
    overall_score: Optional[int] = None


# ============ 任务管理器 ============


class TaskManager:
    """任务管理器 - 管理所有分析任务"""

    def __init__(self):
        self.tasks: dict = {}
        self.queue: List[str] = []
        self.websocket_connections: dict = {}

    def create_task(self, name: str, video_path: str) -> str:
        """创建新任务"""
        task_id = f"{name}_{uuid.uuid4().hex[:8]}"
        timestamp = datetime.now().isoformat()

        self.tasks[task_id] = {
            "task_id": task_id,
            "name": name,
            "status": "pending",
            "progress": 0,
            "stage": None,
            "video_path": video_path,
            "created_at": timestamp,
            "updated_at": timestamp,
            "error": None,
            "result": None,
        }

        return task_id

    def create_task_with_id(self, task_id: str, name: str, video_path: str):
        """使用指定的 ID 创建新任务"""
        timestamp = datetime.now().isoformat()

        self.tasks[task_id] = {
            "task_id": task_id,
            "name": name,
            "status": "pending",
            "progress": 0,
            "stage": None,
            "video_path": video_path,
            "created_at": timestamp,
            "updated_at": timestamp,
            "error": None,
            "result": None,
        }

        return task_id

    def get_task(self, task_id: str) -> Optional[dict]:
        """获取任务"""
        return self.tasks.get(task_id)

    def update_task(self, task_id: str, **updates):
        """更新任务"""
        if task_id in self.tasks:
            self.tasks[task_id].update(updates)
            self.tasks[task_id]["updated_at"] = datetime.now().isoformat()
            self._notify_websocket(task_id, self.tasks[task_id])

    def add_to_queue(self, task_id: str):
        """添加到队列"""
        if task_id not in self.queue:
            self.queue.append(task_id)
            self.update_task(task_id, status="queued")

    def get_next_task(self) -> Optional[str]:
        """获取下一个待处理任务"""
        if self.queue:
            task_id = self.queue.pop(0)
            return task_id
        return None

    def get_queue_tasks(self) -> List[dict]:
        """获取队列中的任务"""
        return [self.tasks[tid] for tid in self.queue if tid in self.tasks]

    def get_history_tasks(
        self, page: int = 1, limit: int = 20, status: Optional[str] = None
    ) -> dict:
        """获取历史任务"""
        tasks_list = list(self.tasks.values())

        # 过滤状态
        if status:
            tasks_list = [t for t in tasks_list if t["status"] == status]

        # 排序（最新在前）
        tasks_list.sort(key=lambda x: x["created_at"], reverse=True)

        # 分页
        total = len(tasks_list)
        start = (page - 1) * limit
        end = start + limit
        tasks = tasks_list[start:end]

        return {
            "tasks": tasks,
            "total": total,
            "page": page,
            "limit": limit,
            "has_more": end < total,
        }

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        if task_id in self.tasks:
            # 删除任务目录
            task_dir = RUNS_DIR / task_id
            if task_dir.exists():
                import shutil

                shutil.rmtree(task_dir)

            del self.tasks[task_id]
            if task_id in self.queue:
                self.queue.remove(task_id)
            return True
        return False

    def add_websocket(self, task_id: str, websocket: WebSocket):
        """添加 WebSocket 连接"""
        if task_id not in self.websocket_connections:
            self.websocket_connections[task_id] = []
        self.websocket_connections[task_id].append(websocket)

    def remove_websocket(self, task_id: str, websocket: WebSocket):
        """移除 WebSocket 连接"""
        if task_id in self.websocket_connections:
            if websocket in self.websocket_connections[task_id]:
                self.websocket_connections[task_id].remove(websocket)

    def _notify_websocket(self, task_id: str, task_data: dict):
        """通知 WebSocket 客户端"""
        if task_id in self.websocket_connections:
            dead_connections = []
            for ws in self.websocket_connections[task_id]:
                try:
                    asyncio.create_task(ws.send_json(task_data))
                except:
                    dead_connections.append(ws)

            # 清理断开的连接
            for ws in dead_connections:
                self.websocket_connections[task_id].remove(ws)


# 全局任务管理器
task_manager = TaskManager()


# ============ 真实分析流程 ============


async def simulate_analysis(task_id: str):
    """真实的视频分析流程

    1. 视频抽帧（每段5帧，最多20帧）
    2. 特征计算
    3. AI 分析（智谱 glm-4v-flash）
    """
    task = task_manager.get_task(task_id)
    if not task:
        logger.error(f"Task {task_id} not found")
        return

    video_path = Path(task.get("video_path", ""))
    if not video_path.exists():
        logger.error(f"Video file not found: {video_path}")
        task_manager.update_task(task_id, status="failed", error="视频文件不存在")
        return

    # 创建输出目录
    run_dir = RUNS_DIR / task_id
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Stage 1: 视频抽帧 (30%)
        task_manager.update_task(
            task_id, status="extracting", stage="视频抽帧中", progress=10
        )
        logger.info(f"[{task_id}] 开始抽帧: {video_path}")

        frames_data = extract_frames(
            video_path,
            run_dir / "frames",
            max_frames=MAX_FRAMES,  # 最多20帧
            num_segments=DEFAULT_NUM_SEGMENTS,  # 4个分段
            frames_per_segment=FRAMES_PER_SEGMENT,  # 每段5帧
            strategy="per_segment",
        )
        logger.info(f"[{task_id}] 抽帧完成: {frames_data['frame_count']} 帧")

        # Stage 2: 特征计算 (60%)
        task_manager.update_task(
            task_id, status="computing", stage="计算特征中", progress=60
        )
        logger.info(f"[{task_id}] 开始计算特征")

        features_data = compute_features(frames_data, num_segments=DEFAULT_NUM_SEGMENTS)
        logger.info(
            f"[{task_id}] 特征计算完成: {features_data['segment_count']} 个分段"
        )

        # Stage 3: AI 分析 (90%)
        task_manager.update_task(
            task_id, status="analyzing", stage="AI 分析中", progress=90
        )
        logger.info(f"[{task_id}] 开始 AI 分析")

        # 检查是否配置了 API Key
        api_key = os.environ.get("ZHIPU_API_KEY", "").strip()
        agent_mode = AGENT_MODE_REAL if api_key else AGENT_MODE_MOCK

        if agent_mode == AGENT_MODE_MOCK:
            logger.info(f"[{task_id}] 使用 Mock 模式（未配置 ZHIPU_API_KEY）")
            # 使用模拟数据
            mock_report = get_mock_report(num_segments=DEFAULT_NUM_SEGMENTS)
            llm_result = mock_report.to_dict()
            # Mock 模式下的默认配置
            target_player_config = {
                "mode": "auto_with_override",
                "auto_pick": "single_player",
                "confidence": 0.0,
                "override": None,
                "reason": "Mock 模式，未进行目标球员检测",
            }
        else:
            logger.info(f"[{task_id}] 使用 Real 模式（调用智谱 AI）")
            # 调用真实分析流程
            report = run_full_analysis(
                video_path=video_path,
                output_dir=run_dir,
                max_frames=MAX_FRAMES,
                num_segments=DEFAULT_NUM_SEGMENTS,
                agent_mode=AGENT_MODE_REAL,
                llm_model="glm-4v-flash",
            )
            llm_result = report["analysis"]
            # 提取目标球员配置
            target_player_config = report.get("metadata", {}).get("target_player", {})

        # 构建最终结果
        result = {
            "task_id": task_id,
            "status": "completed",
            "created_at": task["created_at"],
            "target_player": target_player_config,  # 添加目标球员信息
            "summary": {
                "overview": llm_result.get("summary", ""),
                "strengths": [],  # 可以从 segment_feedback 中提取
                "weaknesses": [
                    {
                        "title": p.get("title", ""),
                        "description": f"{p.get('evidence', '')}\n影响: {p.get('impact', '')}",
                    }
                    for p in llm_result.get("problems", [])
                ],
            },
            "key_frames": [
                {
                    "frame_number": f["frame_index"],
                    "url": f"/api/frames/{task_id}/{Path(f['path']).name}",
                    "description": f"时间戳: {f['timestamp']}s",
                }
                for f in frames_data.get("frames", [])[:10]  # 最多显示10帧
            ],
            "details": {
                "technique": {
                    "分段数量": features_data.get("segment_count", 0),
                    "视频时长": f"{features_data.get('video_duration', 0):.2f}s",
                    "帧率": f"{features_data.get('frame_rate', 0):.1f} fps",
                },
                "metrics": {
                    "抽取帧数": frames_data.get("frame_count", 0),
                    "总帧数": frames_data.get("total_frames_in_video", 0),
                },
            },
            "suggestions": [
                {
                    "title": imp.get("title", ""),
                    "description": f"训练方法:\n" + "\n".join(imp.get("drills", [])),
                }
                for imp in llm_result.get("improvements", [])
            ],
            # 使用 AI 给出的评分，如果没有则根据问题数量计算
            "overall_score": llm_result.get("score", max(40, 80 - len(llm_result.get("problems", [])) * 5)),
        }

        # 保存完整报告到文件
        import json

        report_path = run_dir / "report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        task_manager.update_task(
            task_id, status="completed", progress=100, result=result
        )
        logger.info(f"[{task_id}] 分析完成")

    except AnalysisError as e:
        logger.error(f"[{task_id}] 分析失败: {e}")
        task_manager.update_task(task_id, status="failed", error=str(e))
    except Exception as e:
        logger.error(f"[{task_id}] 未预期的错误: {e}")
        task_manager.update_task(
            task_id, status="failed", error=f"分析过程出错: {str(e)}"
        )


# ============ FastAPI 应用 ============


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时创建队列处理任务
    queue_task = asyncio.create_task(process_queue())
    yield
    # 关闭时取消队列处理任务
    queue_task.cancel()
    try:
        await queue_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="AI 乒乓球教练 API",
    description="提供视频上传、分析任务管理、结果查询等功能",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,      # 关闭 Swagger UI
    redoc_url=None,     # 关闭 ReDoc
)

# CORS 中间件 - 必须在应用创建后添加
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源（开发环境）
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有方法
    allow_headers=["*"],  # 允许所有请求头
    expose_headers=["*"],  # 暴露响应头
)


async def process_queue():
    """处理任务队列"""
    while True:
        task_id = task_manager.get_next_task()
        if task_id:
            await simulate_analysis(task_id)
        else:
            await asyncio.sleep(1)


# ============ API 路由 ============


@app.get("/")
async def root():
    """API 根路径"""
    return {
        "name": "AI 乒乓球教练 API",
        "version": "1.0.0",
        "status": "running",
    }


@app.post("/api/upload", response_model=UploadResponse)
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    上传视频文件

    - 支持的格式: MP4, MOV, AVI
    - 最大文件大小: 500MB
    - 最大时长: 5 秒
    """
    # 验证文件类型
    allowed_types = ["video/mp4", "video/quicktime", "video/x-msvideo"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="不支持的文件格式")

    # 读取文件内容到内存（用于验证）
    content = await file.read()

    # 验证文件大小
    max_size = 500 * 1024 * 1024  # 500MB
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail="视频文件大小不能超过 500MB")

    # 创建任务目录
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    task_dir = RUNS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    # 保存文件
    video_path = task_dir / (file.filename or "video.mp4")
    try:
        with open(video_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")

    # 验证视频时长
    try:
        import imageio
        import imageio_ffmpeg

        # 使用 imageio 读取视频时长
        reader = imageio.get_reader(video_path)
        meta = reader.get_meta_data()

        # 获取帧率
        fps = meta.get('fps', None)
        if fps is None or fps <= 0:
            raise HTTPException(status_code=400, detail="无法读取视频帧率")

        # 获取帧数
        frame_count = reader.count_frames()
        reader.close()

        # 计算时长
        duration = frame_count / fps

        # 验证时长（最大5秒）
        max_duration = 5.0
        if duration > max_duration:
            raise HTTPException(
                status_code=400,
                detail=f"视频时长不能超过 {max_duration} 秒（当前视频：{duration:.1f} 秒）"
            )

        logger.info(f"视频验证通过: 时长 {duration:.1f} 秒, 帧数 {frame_count}, 帧率 {fps:.1f} fps")

    except HTTPException:
        # 重新抛出 HTTPException
        raise
    except Exception as e:
        logger.error(f"视频时长验证失败: {e}")
        # 如果无法验证时长，记录警告但继续处理（降级处理）
        logger.warning(f"无法验证视频时长，继续处理: {e}")

    # 创建任务
    task_manager.create_task_with_id(
        task_id,
        file.filename or "未命名任务",
        str(video_path)
    )
    task_manager.add_to_queue(task_id)

    return UploadResponse(
        success=True,
        task_id=task_id,
        message="视频上传成功",
        task=TaskResponse(**task_manager.get_task(task_id)),
    )


@app.get("/api/preprocess/{task_id}")
async def preprocess_video(task_id: str):
    """
    预处理视频：检测目标运动员

    - 先进行视频抽帧
    - 检测主要击球者（左侧/右侧球员）
    - 返回目标球员配置供用户确认
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    video_path = Path(task.get("video_path", ""))
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    # 创建临时目录用于预处理
    run_dir = RUNS_DIR / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    frames_output = run_dir / "frames"
    frames_output.mkdir(parents=True, exist_ok=True)

    try:
        # Step 1: 抽帧（只抽取少量帧用于检测）
        frames_data = extract_frames(
            video_path,
            frames_output,
            max_frames=10,  # 只需要10帧就能检测
            num_segments=2,  # 简单分段
            frames_per_segment=5,
            strategy="per_segment",
        )

        # Step 2: 检测目标球员
        target_player_config = detect_target_player(
            frames_data,
            run_dir,
            motion_threshold=0.05,
            confidence_threshold=0.65,
        )

        return {
            "success": True,
            "task_id": task_id,
            "target_player": target_player_config,
        }

    except Exception as e:
        logger.error(f"[{task_id}] 预处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"预处理失败: {str(e)}")


@app.post("/api/analyze", response_model=AnalysisResponse)
async def start_analysis(request: AnalysisRequest):
    """
    开始分析任务

    - 将任务添加到处理队列
    - 返回任务 ID 用于跟踪状态
    """
    task = task_manager.get_task(request.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task["status"] == "completed":
        return AnalysisResponse(
            success=True,
            message="任务已完成",
            task_id=request.task_id,
        )

    # 任务已在队列中或处理中
    return AnalysisResponse(
        success=True,
        message="分析任务已启动",
        task_id=request.task_id,
    )


@app.get("/api/results/{task_id}", response_model=AnalysisResult)
async def get_analysis_result(task_id: str):
    """
    获取分析结果

    - 返回完整的分析结果数据
    - 包含概览、关键帧、详细分析、建议等
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    result = task.get("result")
    if not result:
        return AnalysisResult(
            task_id=task_id,
            status=task["status"],
            created_at=task["created_at"],
        )

    return AnalysisResult(**result)


@app.get("/api/history", response_model=TaskListResponse)
async def get_history_tasks(
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
):
    """
    获取历史任务列表

    - 支持分页
    - 支持按状态筛选
    """
    data = task_manager.get_history_tasks(page, limit, status)
    return TaskListResponse(**data)


@app.get("/api/queue")
async def get_task_queue():
    """
    获取当前任务队列

    - 返回所有排队和处理中的任务
    """
    queue_tasks = task_manager.get_queue_tasks()
    # 还包括正在处理但不在队列中的任务
    processing_tasks = [
        t
        for t in task_manager.tasks.values()
        if t["status"] in ["processing", "extracting", "computing", "analyzing"]
        and t["task_id"] not in [q["task_id"] for q in queue_tasks]
    ]

    return {
        "tasks": queue_tasks + processing_tasks,
        "total": len(queue_tasks) + len(processing_tasks),
    }


@app.get("/api/tasks/{task_id}/status", response_model=TaskResponse)
async def get_task_status(task_id: str):
    """
    获取任务状态

    - 返回任务的当前状态和进度
    """
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    return TaskResponse(**task)


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """
    删除任务

    - 删除任务及其相关文件
    """
    success = task_manager.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {"success": True, "message": "任务已删除"}


@app.get("/api/frames/{task_id}/{frame_name}")
async def get_frame_image(task_id: str, frame_name: str):
    """
    获取关键帧图片

    - 返回抽帧后的图片文件
    """
    from fastapi.responses import FileResponse

    frame_path = RUNS_DIR / task_id / "frames" / frame_name
    if not frame_path.exists():
        raise HTTPException(status_code=404, detail="关键帧图片不存在")

    return FileResponse(frame_path)


@app.websocket("/ws/tasks/{task_id}")
async def websocket_task_updates(websocket: WebSocket, task_id: str):
    """
    WebSocket 连接 - 实时接收任务状态更新

    - 连接格式: ws://localhost:8000/ws/tasks/{task_id}
    - 接收实时状态更新消息
    """
    await websocket.accept()

    task = task_manager.get_task(task_id)
    if not task:
        await websocket.close(code=1008, reason="任务不存在")
        return

    # 添加连接
    task_manager.add_websocket(task_id, websocket)

    try:
        # 发送初始状态
        await websocket.send_json(task)

        # 保持连接，接收客户端消息（如果有）
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        task_manager.remove_websocket(task_id, websocket)


# ============ 启动命令 ============

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
