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
from urllib.parse import quote, urlparse
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
    Request,
    Cookie,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager

# 导入分析步骤和agent
from .steps import extract_frames, compute_features, run_full_analysis
from .agent import get_mock_report
from .player_detector import detect_target_player
from .wechat import wechat_jsdk
from .pdf import generate_pdf_report
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


# ============ 用户标识管理 ============


def find_task_globally(task_id: str) -> Optional[dict]:
    """在所有用户目录下全局查找任务

    用于权限验证：先找到任务，再验证所有权

    Args:
        task_id: 任务 ID

    Returns:
        任务信息字典，包含 result、user_id、is_public，如果找不到返回 None
    """
    # 首先检查内存中的任务
    task = task_manager.get_task(task_id)
    if task:
        return task

    # 内存中没有，遍历所有用户目录查找
    if RUNS_DIR.exists():
        import json

        # 遍历所有用户目录
        for user_dir in RUNS_DIR.iterdir():
            if not user_dir.is_dir():
                continue

            task_dir = user_dir / task_id
            if task_dir.exists():
                report_path = task_dir / "report.json"
                if report_path.exists():
                    try:
                        with open(report_path, "r", encoding="utf-8") as f:
                            result = json.load(f)
                        # 从报告文件中提取 user_id 和 is_public
                        task_user_id = result.get("user_id")
                        return {
                            "result": result,
                            "user_id": task_user_id,
                            "task_id": task_id,
                            "name": result.get("name", f"训练视频_{task_id}"),
                            "status": "completed",
                            "created_at": result.get(
                                "created_at", datetime.now().isoformat()
                            ),
                            "is_public": result.get("is_public", False),  # 默认私有
                        }
                    except Exception as e:
                        logger.error(f"读取任务 {task_id} 失败: {e}")
                        continue

    return None


def get_user_id_from_cookie(request: Request) -> str:
    """从请求中获取用户 ID cookie

    Args:
        request: FastAPI 请求对象

    Returns:
        用户 ID (格式: user_xxxxxx)
    """
    user_id = request.cookies.get("user_id")

    # 如果没有 cookie，返回默认用户（向后兼容）
    if not user_id:
        logger.warning("[用户识别] 未找到 user_id cookie，使用默认用户")
        return "user_default"

    # 验证格式
    if not user_id.startswith("user_") or len(user_id) != 11:
        logger.warning(f"[用户识别] 无效的 user_id 格式: {user_id}，使用默认用户")
        return "user_default"

    return user_id


def get_user_run_dir(user_id: str) -> Path:
    """获取用户专属的运行目录

    Args:
        user_id: 用户 ID

    Returns:
        用户专属目录路径: data/runs/user_xxxxxx/
    """
    user_dir = RUNS_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


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
    target_player: Optional[str] = (
        None  # 用户选择的球员方向: 'left' | 'right' | 'single_player'
    )
    scene_type: Optional[str] = None  # 场景类型: 'single' | 'dual_practice'


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
    name: Optional[str] = None  # 任务名称
    target_player: Optional[dict] = None  # 目标球员配置
    # 三个必需字段
    coach_comment: Optional[dict] = None  # 教练评语（strengths, weaknesses, summary）
    problems: Optional[List[dict]] = None  # 训练问题（3点）
    suggestions: Optional[List[dict]] = None  # 训练建议（3点）
    overall_score: Optional[int] = None  # 综合评分
    # 其他字段（兼容旧版本）
    summary: Optional[dict] = None
    details: Optional[dict] = None


# ============ 任务管理器 ============


class TaskManager:
    """任务管理器 - 管理所有分析任务"""

    def __init__(self):
        self.tasks: dict = {}
        self.queue: List[str] = []
        self.websocket_connections: dict = {}
        # 从环境变量读取 BASE_URL，如果没有则留空（将在运行时推断）
        self.base_url = os.getenv("BASE_URL", "")

    def set_base_url(self, base_url: str):
        """设置 base URL（用于 WebSocket 广播）"""
        self.base_url = base_url

    def _build_full_url(self, path: str) -> str:
        """构建完整 URL"""
        if not path.startswith("/"):
            return path
        if self.base_url:
            # 使用配置的 BASE_URL
            parsed = urlparse(self.base_url)
            return f"{parsed.scheme}://{parsed.netloc}{path}"
        # 如果没有配置 BASE_URL，返回相对路径（由 WebSocket 端点处理）
        return path

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
            "is_public": False,  # 默认私有
        }

        return task_id

    def create_task_with_id(
        self, task_id: str, name: str, video_path: str, user_id: str = None
    ):
        """使用指定的 ID 创建新任务

        Args:
            task_id: 任务 ID
            name: 任务名称
            video_path: 视频文件路径
            user_id: 用户 ID（可选）
        """
        timestamp = datetime.now().isoformat()

        task_data = {
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
            "is_public": False,  # 默认私有
        }

        # 如果提供了 user_id，标记任务所属用户
        if user_id:
            task_data["user_id"] = user_id

        self.tasks[task_id] = task_data
        return task_id

    def get_task(self, task_id: str) -> Optional[dict]:
        """获取任务"""
        return self.tasks.get(task_id)

    def update_task(self, task_id: str, **updates):
        """更新任务"""
        if task_id in self.tasks:
            self.tasks[task_id].update(updates)
            self.tasks[task_id]["updated_at"] = datetime.now().isoformat()

            # 立即发送 WebSocket 通知
            self._notify_websocket_sync(task_id, self.tasks[task_id])

    def _notify_websocket_sync(self, task_id: str, task_data: dict):
        """同步方式通知 WebSocket 客户端

        注意：这个方法在同步上下文中被调用，需要小心处理异步操作
        客户端断开连接是正常情况，应该静默处理
        """
        if task_id not in self.websocket_connections:
            return

        task_to_send = dict(task_data)

        # 清理可能不可序列化的字段
        if "result" in task_to_send and task_to_send["result"] is not None:
            result = task_to_send["result"]
            if not isinstance(result, dict):
                # 如果 result 不是字典，转换为字符串或移除
                task_to_send["result"] = str(result) if result else None

        dead_connections = []

        for ws in list(
            self.websocket_connections[task_id]
        ):  # 使用 list() 避免迭代时修改
            try:
                # 检查 WebSocket 连接状态
                # 检查 client 是否存在（连接已关闭时 client 会是 None）
                if ws.client is None:
                    dead_connections.append(ws)
                    continue

                # 尝试获取当前运行的事件循环并调度任务
                try:
                    loop = asyncio.get_running_loop()
                    # 使用 call_soon_threadsafe 在当前事件循环中调度任务
                    # 并添加回调来处理发送失败的情况
                    future = asyncio.ensure_future(
                        ws.send_json(task_to_send), loop=loop
                    )

                    # 添加错误回调
                    def on_error(fut):
                        try:
                            fut.exception()
                        except Exception:
                            # 发送失败，标记为死连接（将在下次清理）
                            pass

                    future.add_done_callback(on_error)

                except RuntimeError:
                    # 没有运行中的事件循环 - 静默跳过
                    logger.debug(f"[WebSocket] 没有运行中的事件循环，跳过发送")
                    pass

            except (WebSocketDisconnect, RuntimeError):
                # 客户端断开连接或运行时错误 - 正常情况，静默处理
                dead_connections.append(ws)
            except Exception as e:
                # 其他意外错误 - 记录但继续处理
                logger.debug(f"[WebSocket] 发送异常（非致命）: {type(e).__name__}")
                dead_connections.append(ws)

        # 清理断开的连接
        for ws in dead_connections:
            try:
                self.websocket_connections[task_id].remove(ws)
            except (ValueError, KeyError):
                # 连接可能已被其他地方移除
                pass

        # 如果该任务没有连接了，清理字典
        if (
            task_id in self.websocket_connections
            and not self.websocket_connections[task_id]
        ):
            del self.websocket_connections[task_id]

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
            try:
                self.websocket_connections[task_id].remove(websocket)
            except ValueError:
                pass  # 连接已被移除

            # 如果该任务没有连接了，清理字典
            if not self.websocket_connections[task_id]:
                del self.websocket_connections[task_id]

    def _notify_websocket(self, task_id: str, task_data: dict):
        """通知 WebSocket 客户端（异步上下文）

        注意：此方法当前未被使用，保留用于将来可能的异步上下文调用
        客户端断开连接是正常情况，应该静默处理
        """
        if task_id not in self.websocket_connections:
            return

        task_to_send = dict(task_data)
        dead_connections = []

        for ws in list(
            self.websocket_connections[task_id]
        ):  # 使用 list() 避免迭代时修改
            try:
                # 检查 WebSocket 连接状态
                if ws.client is None:
                    dead_connections.append(ws)
                    continue

                # 尝试获取当前运行的事件循环
                try:
                    loop = asyncio.get_running_loop()
                    # 在运行中的事件循环中安全地调度协程
                    future = asyncio.run_coroutine_threadsafe(
                        ws.send_json(task_to_send), loop
                    )

                    # 添加回调处理结果
                    def on_done(fut):
                        try:
                            fut.result()  # 检查是否有异常
                        except Exception:
                            # 发送失败，将在下次清理时移除
                            pass

                    future.add_done_callback(on_done)

                except RuntimeError:
                    # 没有运行中的事件循环 - 静默跳过
                    logger.debug(f"[WebSocket] 没有运行中的事件循环，跳过发送")
                    pass

            except (WebSocketDisconnect, RuntimeError):
                # 客户端断开连接或运行时错误 - 正常情况
                dead_connections.append(ws)
            except Exception:
                # 其他意外错误 - 记录但继续处理
                logger.debug(f"[WebSocket] 发送异常（非致命）")
                dead_connections.append(ws)

        # 清理断开的连接
        for ws in dead_connections:
            try:
                self.websocket_connections[task_id].remove(ws)
            except (ValueError, KeyError):
                pass  # 连接已被其他地方移除

        # 如果该任务没有连接了，清理字典
        if (
            task_id in self.websocket_connections
            and not self.websocket_connections[task_id]
        ):
            del self.websocket_connections[task_id]


# 全局任务管理器
task_manager = TaskManager()


# ============ 真实分析流程 ============


async def simulate_analysis(task_id: str, user_id: str = None):
    """真实的视频分析流程

    1. 视频抽帧（每段5帧，最多20帧）
    2. 特征计算
    3. AI 分析（智谱 glm-4v-flash）

    Args:
        task_id: 任务 ID
        user_id: 用户 ID（用于用户数据隔离）
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

    # 创建输出目录（使用用户专属目录）
    if user_id:
        run_dir = get_user_run_dir(user_id) / task_id
    else:
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

        # 构建最终结果（确保包含三个必需字段：coach_comment, problems, suggestions）
        # 获取 LLM 返回的数据，确保非空
        llm_coach_comment = llm_result.get("coach_comment", {})
        llm_problems = llm_result.get("problems", [])
        llm_improvements = llm_result.get("improvements", [])
        llm_score = llm_result.get("score")

        # 教练评语：确保包含所有必需字段
        if not llm_coach_comment or not isinstance(llm_coach_comment, dict):
            llm_coach_comment = {
                "strengths": "动作基础扎实，建议继续加强练习",
                "weaknesses": "需要进一步规范化动作细节",
                "summary": "整体表现良好，继续保持训练",
            }
        else:
            # 确保每个字段都有值
            if not llm_coach_comment.get("strengths"):
                llm_coach_comment["strengths"] = "动作基础扎实，建议继续加强练习"
            if not llm_coach_comment.get("weaknesses"):
                llm_coach_comment["weaknesses"] = "需要进一步规范化动作细节"
            if not llm_coach_comment.get("summary"):
                llm_coach_comment["summary"] = "整体表现良好，继续保持训练"

        # 训练问题：确保至少有3个问题
        if not llm_problems or len(llm_problems) == 0:
            llm_problems = [
                {"title": "动作规范性", "evidence": "需观察", "impact": "影响稳定性"},
                {"title": "击球稳定性", "evidence": "需观察", "impact": "影响得分率"},
                {"title": "还原速度", "evidence": "需观察", "impact": "影响衔接"},
            ]

        # 训练建议：从 improvements 转换，确保至少有3个建议
        if not llm_improvements or len(llm_improvements) == 0:
            llm_improvements = [
                {"title": "加强基本动作", "drills": ["多球练习", "空挥练习"]},
                {"title": "提升击球稳定性", "drills": ["定点训练", "节奏控制"]},
                {"title": "改善还原速度", "drills": ["快速还原", "步法训练"]},
            ]

        # 转换 problems 格式（从旧格式到新格式）
        formatted_problems = []
        for p in llm_problems[:3]:
            if isinstance(p, dict):
                # 新格式：直接使用 title + description
                if "description" in p:
                    formatted_problems.append(
                        {
                            "title": p.get("title", ""),
                            "description": p.get("description", ""),
                        }
                    )
                else:
                    # 旧格式：title + evidence + impact
                    formatted_problems.append(
                        {
                            "title": p.get("title", ""),
                            "description": f"依据：{p.get('evidence', '')}\n影响：{p.get('impact', '')}",
                        }
                    )

        # 转换 suggestions 格式（从 improvements 到 suggestions）
        formatted_suggestions = []
        for imp in llm_improvements[:3]:
            if isinstance(imp, dict):
                formatted_suggestions.append(
                    {
                        "title": imp.get("title", "训练建议"),
                        "description": "训练方法：\n"
                        + "\n".join(imp.get("drills", [])),
                        "priority": "medium",
                    }
                )

        result = {
            "task_id": task_id,
            "name": task.get("name", f"训练视频_{task_id}"),
            "status": "completed",
            "created_at": task["created_at"],
            "target_player": target_player_config,
            "coach_comment": llm_coach_comment,
            "problems": formatted_problems[:3],
            "suggestions": formatted_suggestions,
            "overall_score": llm_score
            if llm_score is not None
            else max(40, 80 - len(llm_problems) * 5),
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
            # 保留旧字段以兼容
            "summary": {
                "overview": llm_result.get("summary", ""),
                "strengths": [],
                "weaknesses": [],
            },
        }

        # 保存完整报告到文件（包含 user_id 用于权限验证）
        import json

        # 如果有 user_id，保存到报告中以便后续权限验证
        if user_id:
            result["user_id"] = user_id

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
    docs_url=None,  # 关闭 Swagger UI
    redoc_url=None,  # 关闭 ReDoc
)

# CORS 中间件 - 必须在应用创建后添加
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源（开发环境）
    allow_credentials=True,  # 允许发送凭证（cookie）
    allow_methods=["*"],  # 允许所有方法
    allow_headers=["*"],  # 允许所有请求头
    expose_headers=["*"],  # 暴露响应头
)


# 中间件：自动推断并设置 BASE_URL
@app.middleware("http")
async def auto_detect_base_url(request: Request, call_next):
    """自动从请求头中推断 BASE_URL 并设置到 TaskManager"""
    # 只在没有配置 BASE_URL 环境变量时才自动推断
    if not task_manager.base_url:
        # 获取请求的协议和主机
        scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)
        host = request.headers.get(
            "X-Forwarded-Host", request.headers.get("Host", "localhost:8000")
        )
        # 构建并设置 base_url
        inferred_base_url = f"{scheme}://{host}"
        task_manager.set_base_url(inferred_base_url)
        logger.info(f"自动推断 BASE_URL: {inferred_base_url}")

    response = await call_next(request)
    return response


async def process_queue():
    """处理任务队列"""
    while True:
        task_id = task_manager.get_next_task()
        if task_id:
            # 获取任务的 user_id（如果有）
            task = task_manager.get_task(task_id)
            user_id = task.get("user_id") if task else None
            await simulate_analysis(task_id, user_id)
        else:
            await asyncio.sleep(1)


# ============ API 路由 ============


def build_full_url(request: Request, path: str) -> str:
    """
    构建完整的 URL（包含协议和域名）

    Args:
        request: FastAPI Request 对象
        path: 相对路径，如 /api/videos/xxx

    Returns:
        完整 URL，如 https://example.com/api/videos/xxx
    """
    # 获取请求的协议（http 或 https）
    # 优先检查 X-Forwarded-Proto 头（反向代理场景）
    scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme)

    # 获取请求的 host
    # 优先检查 X-Forwarded-Host 头（反向代理场景）
    host = request.headers.get(
        "X-Forwarded-Host", request.headers.get("Host", request.url.netloc)
    )

    # 构建完整 URL
    return f"{scheme}://{host}{path}"


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
    request: Request = None,
):
    """
    上传视频文件

    - 支持的格式: MP4, MOV, AVI
    - 最大文件大小: 20MB
    - 最大时长: 5 秒
    """
    # 验证文件类型
    allowed_types = ["video/mp4", "video/quicktime", "video/x-msvideo"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="不支持的文件格式")

    # 读取文件内容到内存（用于验证）
    content = await file.read()

    # 验证文件大小
    max_size = 20 * 1024 * 1024  # 20MB
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail="视频文件大小不能超过 20MB")

    # 获取用户标识
    user_id = get_user_id_from_cookie(request)
    user_run_dir = get_user_run_dir(user_id)

    # 创建任务目录（在用户专属目录下）
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    task_dir = user_run_dir / task_id
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
        fps = meta.get("fps", None)
        if fps is None or fps <= 0:
            raise HTTPException(status_code=400, detail="无法读取视频帧率")

        # 获取帧数
        frame_count = reader.count_frames()
        reader.close()

        # 计算时长
        duration = frame_count / fps

        # 验证时长（后端校验使用 6 秒，容错处理边界情况）
        # 前端提示仍显示 5 秒，给用户更好的体验
        max_duration = 6.0
        if duration > max_duration:
            raise HTTPException(
                status_code=400,
                detail=f"视频时长不能超过 5 秒（当前视频：{duration:.1f} 秒）",
            )

        logger.info(
            f"视频验证通过: 时长 {duration:.1f} 秒, 帧数 {frame_count}, 帧率 {fps:.1f} fps"
        )

    except HTTPException:
        # 重新抛出 HTTPException
        raise
    except Exception as e:
        logger.error(f"视频时长验证失败: {e}")
        # 如果无法验证时长，记录警告但继续处理（降级处理）
        logger.warning(f"无法验证视频时长，继续处理: {e}")

    # 生成友好的任务名称
    from datetime import datetime

    date_str = datetime.now().strftime("%Y%m%d")
    random_str = uuid.uuid4().hex[:6]
    task_name = f"训练视频_{date_str}_{random_str}"

    # 创建任务（不自动加入队列，等待用户点击开始分析）
    # 传递 user_id 以标记任务所属用户
    task_manager.create_task_with_id(task_id, task_name, str(video_path), user_id)

    return UploadResponse(
        success=True,
        task_id=task_id,
        message="视频上传成功",
        task=TaskResponse(**task_manager.get_task(task_id)),
    )


@app.get("/api/preprocess/{task_id}")
async def preprocess_video(task_id: str, request: Request):
    """
    预处理视频：检测目标运动员

    - 先进行视频抽帧
    - 检测主要击球者（左侧/右侧球员）
    - 返回目标球员配置供用户确认
    - 使用用户专属目录
    """
    # 获取用户标识
    user_id = get_user_id_from_cookie(request)
    user_run_dir = get_user_run_dir(user_id)

    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 验证任务所有权
    if task.get("user_id") and task.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    video_path = Path(task.get("video_path", ""))
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    # 创建临时目录用于预处理（使用用户专属目录）
    run_dir = user_run_dir / task_id
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
async def start_analysis(request_data: AnalysisRequest, http_request: Request):
    """
    开始分析任务

    - 使用用户选择的 target_player 运行完整分析
    - 如果任务已完成则直接返回
    """
    # 获取用户标识
    user_id = get_user_id_from_cookie(http_request)

    logger.info(
        f"[API] 收到分析请求: task_id={request_data.task_id}, user_id={user_id}"
    )
    logger.info(f"[API] 目标球员参数: target_player={request_data.target_player}")

    task = task_manager.get_task(request_data.task_id)

    # 验证任务所有权
    if task.get("user_id") and task.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="无权访问此任务")

    if task["status"] == "completed":
        return AnalysisResponse(
            success=True,
            message="任务已完成",
            task_id=request_data.task_id,
        )

    # 更新任务状态为处理中
    task_manager.update_task(
        request_data.task_id, status="queued", stage="正在准备分析...", progress=10
    )
    # 让事件循环有机会处理 WebSocket 发送
    await asyncio.sleep(0.01)

    # 标记任务所属用户
    task_manager.update_task(request_data.task_id, user_id=user_id)

    video_path = Path(task.get("video_path", ""))
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")

    # 创建运行目录（使用用户专属目录）
    user_run_dir = get_user_run_dir(user_id)
    run_dir = user_run_dir / request_data.task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    frames_output = run_dir / "frames"
    frames_output.mkdir(parents=True, exist_ok=True)

    try:
        # 构建目标球员配置（使用用户选择）
        target_player_config = None
        if request_data.target_player:
            target_player_config = {
                "mode": "user_choice",
                "auto_pick": request_data.target_player,
                "confidence": 1.0,  # 用户选择，置信度为100%
                "reason": "用户手动选择",
                "override": None,
                "scene_type": request_data.scene_type
                or "single",  # 场景类型：single 或 dual_practice
            }
            logger.info(f"[API] 构建目标球员配置: {target_player_config}")
        else:
            logger.info(f"[API] 未指定目标球员，将使用自动检测")

        # Step 1: 完整抽帧（比预处理的10帧更多）
        from .steps import (
            extract_frames,
            compute_features,
            run_llm_analysis,
            assemble_report,
        )

        # 抽帧阶段
        task_manager.update_task(
            request_data.task_id,
            status="extracting",
            progress=30,
            stage="正在从视频中提取关键帧...",
        )
        # 让事件循环有机会处理 WebSocket 发送
        await asyncio.sleep(0.01)

        frames_data = extract_frames(
            video_path,
            frames_output,
            max_frames=100,
            num_segments=8,
            frames_per_segment=12,
            strategy="per_segment",
        )

        # 特征计算阶段
        task_manager.update_task(
            request_data.task_id,
            status="computing",
            progress=50,
            stage="正在计算动作特征...",
        )
        # 让事件循环有机会处理 WebSocket 发送
        await asyncio.sleep(0.01)

        # Step 2: 计算特征
        features_data = compute_features(frames_data, num_segments=8)

        # AI 分析阶段
        task_manager.update_task(
            request_data.task_id,
            status="analyzing",
            progress=60,
            stage="AI 正在分析动作...",
        )
        # 让事件循环有机会处理 WebSocket 发送
        await asyncio.sleep(0.01)

        # Step 3: 运行 LLM 分析（使用用户选择的球员配置）
        # 检查是否配置了 API Key 决定使用真实模式还是模拟模式
        api_key = (
            os.environ.get("ZHIPU_API_KEY", "").strip()
            or os.environ.get("DEEPSEEK_API_KEY", "").strip()
        )
        agent_mode = AGENT_MODE_REAL if api_key else AGENT_MODE_MOCK

        llm_result = run_llm_analysis(
            frames_data,
            features_data,
            agent_mode,  # 必需的位置参数
            llm_model="deepseek-chat",
            run_dir=run_dir,
            target_player_config=target_player_config,  # 传递用户选择
        )

        # 生成报告阶段
        task_manager.update_task(
            request_data.task_id,
            status="assembling_report",
            progress=90,
            stage="正在生成分析报告...",
        )
        # 让事件循环有机会处理 WebSocket 发送
        await asyncio.sleep(0.01)

        # Step 4: 组装报告
        report = assemble_report(
            frames_data, features_data, llm_result, target_player_config
        )

        # 构建最终结果（确保包含三个必需字段：coach_comment, problems, suggestions）
        # 获取 LLM 返回的数据，确保非空
        llm_coach_comment = llm_result.get("coach_comment", {})
        llm_problems = llm_result.get("problems", [])
        llm_suggestions = llm_result.get("suggestions", [])
        llm_score = llm_result.get("score")

        # 教练评语：确保包含所有必需字段
        if not llm_coach_comment or not isinstance(llm_coach_comment, dict):
            llm_coach_comment = {
                "strengths": "动作基础扎实，建议继续加强练习",
                "weaknesses": "需要进一步规范化动作细节",
                "summary": "整体表现良好，继续保持训练",
            }
        else:
            # 确保每个字段都有值
            if not llm_coach_comment.get("strengths"):
                llm_coach_comment["strengths"] = "动作基础扎实，建议继续加强练习"
            if not llm_coach_comment.get("weaknesses"):
                llm_coach_comment["weaknesses"] = "需要进一步规范化动作细节"
            if not llm_coach_comment.get("summary"):
                llm_coach_comment["summary"] = "整体表现良好，继续保持训练"

        # 训练问题：确保至少有3个问题
        if not llm_problems or len(llm_problems) == 0:
            llm_problems = [
                {"title": "动作规范性", "description": "建议加强基本动作的规范性训练"},
                {"title": "击球稳定性", "description": "通过多球练习提升击球稳定性"},
                {"title": "还原速度", "description": "加强击球后的快速还原训练"},
            ]

        # 训练建议：确保至少有3个建议
        if not llm_suggestions or len(llm_suggestions) == 0:
            llm_suggestions = [
                {
                    "title": "加强基本动作",
                    "description": "训练方法：\n多球练习\n空挥练习",
                    "priority": "high",
                },
                {
                    "title": "提升击球稳定性",
                    "description": "训练方法：\n定点训练\n节奏控制",
                    "priority": "medium",
                },
                {
                    "title": "改善还原速度",
                    "description": "训练方法：\n快速还原\n步法训练",
                    "priority": "medium",
                },
            ]

        # 规范化 suggestions 格式
        formatted_suggestions = []
        for s in llm_suggestions[:3]:  # 最多取3个
            if isinstance(s, dict):
                formatted_suggestions.append(
                    {
                        "title": s.get("title", "训练建议"),
                        "description": s.get("description", ""),
                        "priority": s.get("priority", "medium"),
                    }
                )

        result = {
            "task_id": request_data.task_id,
            "name": task.get("name", f"训练视频_{request_data.task_id}"),
            "status": "completed",
            "created_at": task["created_at"],
            "target_player": target_player_config or {},
            "coach_comment": llm_coach_comment,
            "problems": llm_problems[:3],  # 确保最多3个
            "suggestions": formatted_suggestions,
            "overall_score": llm_score if llm_score is not None else 70,
            "details": {},
            "user_id": user_id,  # 保存 user_id 用于权限验证
        }

        # 保存 result 到文件（而不是 report）
        import json

        report_path = run_dir / "report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # 更新任务为完成状态
        task_manager.update_task(
            request_data.task_id,
            status="completed",
            progress=100,
            stage=None,
            result=result,
        )

        return AnalysisResponse(
            success=True,
            message="分析完成",
            task_id=request_data.task_id,
        )

    except Exception as e:
        logger.error(f"[{request_data.task_id}] 分析失败: {e}")
        task_manager.update_task(
            request_data.task_id,
            status="failed",
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


def _ensure_new_format(data: dict, task_id: str = None) -> dict:
    """
    确保结果数据包含新格式的三个必需字段

    处理两种旧格式：
    1. report 格式（assemble_report 返回）：{metadata, frames, features, analysis}
    2. 旧 result 格式：{summary, improvements, details}
    转换为新格式：{task_id, status, created_at, coach_comment, problems, suggestions}

    Args:
        data: 原始数据（可能是 report 或旧 result）
        task_id: 任务 ID（用于从 report 转换时）

    Returns:
        包含三个必需字段的结果数据
    """
    # 如果已经是正确的新格式（有 task_id 和 coach_comment），直接返回
    if data.get("task_id") and data.get("coach_comment"):
        return data

    # 情况1：处理 report 格式（有 metadata, analysis 字段）
    if "metadata" in data and "analysis" in data:
        metadata = data.get("metadata", {})
        analysis = data.get("analysis", {})

        # 从 analysis 提取并规范化数据
        # 确保suggestions不为空
        analysis_suggestions = analysis.get("suggestions", [])
        if not analysis_suggestions or len(analysis_suggestions) == 0:
            analysis_suggestions = [
                {
                    "title": "加强基本动作",
                    "description": "训练方法：\n多球练习\n空挥练习",
                    "priority": "high",
                },
                {
                    "title": "提升击球稳定性",
                    "description": "训练方法：\n定点训练\n节奏控制",
                    "priority": "medium",
                },
                {
                    "title": "改善还原速度",
                    "description": "训练方法：\n快速还原\n步法训练",
                    "priority": "medium",
                },
            ]

        # 格式化suggestions
        formatted_suggestions = [
            {
                "title": s.get("title", "训练建议"),
                "description": s.get("description", ""),
                "priority": s.get("priority", "medium"),
            }
            for s in analysis_suggestions[:3]
        ]

        return {
            "task_id": task_id or metadata.get("task_id", ""),
            "name": metadata.get(
                "name", f"训练视频_{task_id}" if task_id else "训练视频"
            ),
            "status": "completed",
            "created_at": metadata.get("created_at", datetime.now().isoformat()),
            "target_player": metadata.get("target_player", {}),
            # 从 analysis 提取
            "coach_comment": analysis.get(
                "coach_comment",
                {
                    "strengths": "动作基础扎实，建议继续加强练习",
                    "weaknesses": "需要进一步规范化动作细节",
                    "summary": "整体表现良好，继续保持训练",
                },
            ),
            "problems": analysis.get(
                "problems",
                [
                    {
                        "title": "动作规范性",
                        "description": "建议加强基本动作的规范性训练",
                    },
                    {
                        "title": "击球稳定性",
                        "description": "通过多球练习提升击球稳定性",
                    },
                    {"title": "还原速度", "description": "加强击球后的快速还原训练"},
                ],
            ),
            "suggestions": formatted_suggestions,
            "overall_score": analysis.get("score", 70),
            "details": {},
        }

    # 情况2：处理旧 result 格式（已有 coach_comment 但可能缺少其他字段）
    if data.get("coach_comment"):
        # 确保所有必需字段都有默认值
        if not data.get("problems") or len(data.get("problems", [])) == 0:
            data["problems"] = [
                {"title": "动作规范性", "description": "建议加强基本动作的规范性训练"},
                {"title": "击球稳定性", "description": "通过多球练习提升击球稳定性"},
                {"title": "还原速度", "description": "加强击球后的快速还原训练"},
            ]
        if not data.get("suggestions") or len(data.get("suggestions", [])) == 0:
            data["suggestions"] = [
                {
                    "title": "加强基本动作",
                    "description": "训练方法：\n多球练习\n空挥练习",
                    "priority": "high",
                },
                {
                    "title": "提升击球稳定性",
                    "description": "训练方法：\n定点训练\n节奏控制",
                    "priority": "medium",
                },
                {
                    "title": "改善还原速度",
                    "description": "训练方法：\n快速还原\n步法训练",
                    "priority": "medium",
                },
            ]
        if "overall_score" not in data or data["overall_score"] is None:
            data["overall_score"] = 70
        if "details" not in data:
            data["details"] = {}
        return data

    # 旧格式转换
    summary = data.get("summary", {})
    improvements = data.get("improvements", [])
    details = data.get("details", {})

    # 从旧格式构建 coach_comment
    coach_comment = {
        "strengths": summary.get("overview", "动作基础扎实，建议继续加强练习"),
        "weaknesses": "",
        "summary": summary.get("overview", "整体表现良好，继续保持训练"),
    }

    # 从旧的 weaknesses 构建
    old_weaknesses = summary.get("weaknesses", [])
    if old_weaknesses:
        coach_comment["weaknesses"] = (
            "、".join(old_weaknesses)
            if isinstance(old_weaknesses, list)
            else str(old_weaknesses)
        )
    else:
        coach_comment["weaknesses"] = "需要进一步规范化动作细节"

    # 从旧格式转换 problems（从 details 或 summary.weaknesses）
    problems = []
    if isinstance(details, dict):
        technique = details.get("technique", {})
        if isinstance(technique, dict):
            for key, value in technique.items():
                problems.append({"title": key, "description": str(value)})

    # 如果没有足够的 problems，使用默认值
    while len(problems) < 3:
        problems.append(
            {"title": "动作规范性", "description": "建议加强基本动作的规范性训练"}
        )

    # 从旧格式转换 suggestions（从 improvements）
    suggestions = []
    for imp in improvements[:3]:
        if isinstance(imp, dict):
            suggestions.append(
                {
                    "title": imp.get("title", "训练建议"),
                    "description": "训练方法：\n" + "\n".join(imp.get("drills", [])),
                }
            )

    # 如果没有足够的 suggestions，使用默认值
    while len(suggestions) < 3:
        default_suggestions = [
            {"title": "加强基本动作", "description": "训练方法：\n多球练习\n空挥练习"},
            {
                "title": "提升击球稳定性",
                "description": "训练方法：\n定点训练\n节奏控制",
            },
            {"title": "改善还原速度", "description": "训练方法：\n快速还原\n步法训练"},
        ]
        suggestions.append(default_suggestions[len(suggestions)])

    # 更新结果
    data["coach_comment"] = coach_comment
    data["problems"] = problems[:3]
    data["suggestions"] = suggestions[:3]

    # 确保必需字段存在（使用 task_id 参数或默认值）
    if "task_id" not in data:
        data["task_id"] = task_id or ""
    if "status" not in data:
        data["status"] = "completed"
    if "created_at" not in data:
        data["created_at"] = datetime.now().isoformat()
    if "name" not in data:
        data["name"] = f"训练视频_{task_id}" if task_id else "训练视频"
    if "target_player" not in data:
        data["target_player"] = {}
    if "overall_score" not in data:
        data["overall_score"] = 70
    if "details" not in data:
        data["details"] = {}

    return data


@app.get("/api/results/{task_id}", response_model=AnalysisResult)
async def get_analysis_result(task_id: str, request: Request):
    """
    获取分析结果

    - 返回完整的分析结果数据
    - 包含概览、关键帧、详细分析、建议等
    - 优先从内存获取，服务重启后从文件恢复
    - 如果任务已设为公开（is_public=True），任何人都可以访问
    - 否则仅允许访问任务创建者的数据
    - 支持历史任务（不在内存中）
    """
    # 获取当前请求用户的标识
    user_id = get_user_id_from_cookie(request)

    # 全局查找任务（遍历所有用户目录）
    task = find_task_globally(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 验证任务所有权：is_public=True 时允许任何人访问
    task_user_id = task.get("user_id")
    is_public = task.get("is_public", False)

    if not is_public and task_user_id and task_user_id != user_id:
        logger.warning(
            f"[分析结果] 权限拒绝: user_id={user_id} 尝试访问 task_user_id={task_user_id} 的私有任务"
        )
        raise HTTPException(status_code=403, detail="无权访问此任务")

    result = task.get("result")
    if not result:
        return AnalysisResult(
            task_id=task_id,
            status=task.get("status", "unknown"),
            created_at=task.get("created_at", datetime.now().isoformat()),
        )

    # 数据格式转换：确保包含新格式的三个必需字段
    result = _ensure_new_format(result, task_id)

    return AnalysisResult(**result)


@app.get("/api/history", response_model=TaskListResponse)
async def get_history_tasks(
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    request: Request = None,
):
    """
    获取历史任务列表

    - 支持分页
    - 支持按状态筛选
    - 服务重启后从文件系统恢复任务列表
    - 仅返回当前用户的任务
    - 支持历史任务（不在内存中）
    """
    # 获取当前请求用户的标识
    user_id = get_user_id_from_cookie(request)
    user_run_dir = get_user_run_dir(user_id)

    logger.info(f"[历史任务] 获取用户 {user_id} 的任务列表")

    # 首先尝试从内存获取（仅获取当前用户的任务）
    tasks_list = [
        t
        for t in task_manager.tasks.values()
        if t.get("user_id") == user_id or t.get("user_id") is None
    ]

    # 如果内存中没有任务（服务刚重启），从文件系统恢复
    if not tasks_list:
        import json

        # 只扫描当前用户的目录
        if user_run_dir.exists():
            for task_dir in sorted(user_run_dir.iterdir(), reverse=True):
                if not task_dir.is_dir():
                    continue

                task_id = task_dir.name
                report_path = task_dir / "report.json"

                if report_path.exists():
                    try:
                        with open(report_path, "r", encoding="utf-8") as f:
                            result = json.load(f)

                        # 验证任务所有权（report.json 中的 user_id 必须匹配）
                        task_user_id = result.get("user_id")
                        if task_user_id and task_user_id != user_id:
                            # 跳过不属于当前用户的任务
                            continue

                        # 重建任务信息
                        task_manager.tasks[task_id] = {
                            "task_id": task_id,
                            "name": result.get("name", f"训练视频_{task_id}"),
                            "status": "completed",
                            "progress": 100,
                            "stage": None,
                            "video_path": str(task_dir / "input.mp4"),
                            "created_at": result.get(
                                "created_at", datetime.now().isoformat()
                            ),
                            "updated_at": result.get(
                                "created_at", datetime.now().isoformat()
                            ),
                            "error": None,
                            "result": result,
                            "user_id": user_id,  # 标记用户
                        }
                    except Exception as e:
                        logger.error(f"恢复任务 {task_id} 失败: {e}")

            # 重新获取任务列表
            tasks_list = [
                t for t in task_manager.tasks.values() if t.get("user_id") == user_id
            ]

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


@app.post("/api/tasks/{task_id}/share")
async def share_task(task_id: str, request: Request):
    """
    设置任务为公开分享状态

    - 将任务的 is_public 设置为 True
    - 只有任务创建者可以设置分享状态
    - 分享后，任何人都可以通过 task_id 访问该任务
    - 同时更新内存和文件系统
    """
    import json

    # 获取当前请求用户的标识
    user_id = get_user_id_from_cookie(request)

    # 全局查找任务（遍历所有用户目录）
    task = find_task_globally(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 验证任务所有权：只有创建者可以设置分享
    task_user_id = task.get("user_id")
    if task_user_id and task_user_id != user_id:
        logger.warning(
            f"[分享任务] 权限拒绝: user_id={user_id} 尝试分享 task_user_id={task_user_id} 的任务"
        )
        raise HTTPException(status_code=403, detail="只有任务创建者才能设置分享状态")

    # 获取任务所属用户的目录
    task_user_id = task_user_id or user_id
    user_run_dir = get_user_run_dir(task_user_id)
    report_path = user_run_dir / task_id / "report.json"

    # 更新文件系统中的 report.json
    if report_path.exists():
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            report["is_public"] = True
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[分享任务] 更新 report.json 失败: {e}")
            # 继续执行，至少更新内存中的状态

    # 更新内存中的任务状态
    if task_id in task_manager.tasks:
        task_manager.update_task(task_id, is_public=True)

    logger.info(f"[分享任务] task_id={task_id} 已设置为公开分享")

    return {
        "success": True,
        "message": "任务已设置为公开分享",
        "task_id": task_id,
        "is_public": True,
    }


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, request: Request):
    """
    删除任务

    - 删除任务及其相关文件
    - 仅允许删除当前用户的任务
    - 支持删除历史任务（不在内存中）
    """
    # 获取当前请求用户的标识
    user_id = get_user_id_from_cookie(request)

    # 全局查找任务（遍历所有用户目录）
    task = find_task_globally(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 验证任务所有权
    task_user_id = task.get("user_id")
    if task_user_id and task_user_id != user_id:
        logger.warning(
            f"[删除任务] 权限拒绝: user_id={user_id} 尝试删除 task_user_id={task_user_id} 的任务"
        )
        raise HTTPException(status_code=403, detail="无权删除此任务")

    # 使用任务所属用户的目录删除
    task_user_id = task_user_id or user_id
    user_run_dir = get_user_run_dir(task_user_id)
    task_dir = user_run_dir / task_id
    if task_dir.exists():
        import shutil

        shutil.rmtree(task_dir)

    # 从内存中删除
    if task_id in task_manager.tasks:
        del task_manager.tasks[task_id]
    if task_id in task_manager.queue:
        task_manager.queue.remove(task_id)

    return {"success": True, "message": "任务已删除"}


@app.get("/frames/{task_id}/{frame_name}")
async def get_frame_image(task_id: str, frame_name: str, request: Request):
    """
    获取关键帧图片

    - 返回抽帧后的图片文件
    - 如果任务已设为公开（is_public=True），任何人都可以访问
    - 否则仅允许访问任务创建者的数据
    - 支持历史任务（不在内存中）
    """
    from fastapi.responses import FileResponse

    # 获取当前请求用户的标识
    user_id = get_user_id_from_cookie(request)

    # 全局查找任务（遍历所有用户目录）
    task = find_task_globally(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 验证任务所有权：is_public=True 时允许任何人访问
    task_user_id = task.get("user_id")
    is_public = task.get("is_public", False)

    if not is_public and task_user_id and task_user_id != user_id:
        logger.warning(
            f"[关键帧图片] 权限拒绝: user_id={user_id} 尝试访问 task_user_id={task_user_id} 的私有任务"
        )
        raise HTTPException(status_code=403, detail="无权访问此任务")

    # 使用任务所属用户的目录获取关键帧图片
    task_user_id = task_user_id or user_id
    user_run_dir = get_user_run_dir(task_user_id)
    frame_path = user_run_dir / task_id / "frames" / frame_name

    # 兼容旧任务：如果用户隔离目录找不到，尝试旧目录结构 data/runs/task_id/frames/
    if not frame_path.exists():
        legacy_frames_dir = RUNS_DIR / task_id / "frames"
        legacy_frame_path = legacy_frames_dir / frame_name
        if legacy_frame_path.exists():
            frame_path = legacy_frame_path

    if not frame_path.exists():
        # 提供详细的调试信息
        frames_dir = user_run_dir / task_id / "frames"
        available_frames = []
        if frames_dir.exists():
            available_frames = sorted(
                [f.name for f in frames_dir.iterdir() if f.is_file()]
            )

        # 尝试检查旧目录
        legacy_frames_dir = RUNS_DIR / task_id / "frames"
        if legacy_frames_dir.exists():
            legacy_frames = sorted(
                [f.name for f in legacy_frames_dir.iterdir() if f.is_file()]
            )
            if legacy_frames:
                available_frames.extend(legacy_frames)

        error_detail = f"关键帧图片不存在: {frame_name}"
        if available_frames:
            error_detail += f"\n可用的帧文件: {', '.join(available_frames[:10])}"
        else:
            error_detail += "\n帧目录不存在或为空"

        raise HTTPException(status_code=404, detail=error_detail)

    return FileResponse(frame_path)


@app.get("/api/wechat/jssdk-config")
async def get_wechat_jsdk_config(url: str):
    """
    获取微信 JS-SDK 配置

    - 返回用于 wx.config 的签名参数
    - url 参数：当前页面的完整 URL（不含 #hash 部分）
    - 返回：appId, timestamp, nonceStr, signature
    """
    try:
        config = await wechat_jsdk.get_jsdk_config(url)
        return {
            "success": True,
            "data": config,
        }
    except Exception as e:
        logger.error(f"获取微信 JS-SDK 配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@app.get("/results/{task_id}/pdf")
async def download_pdf_report(task_id: str, request: Request):
    """
    下载 PDF 报告

    - 如果任务已设为公开（is_public=True），任何人都可以下载
    - 否则仅允许任务创建者下载
    - 支持从历史任务（不在内存中）下载
    """
    # 获取当前请求用户的标识
    user_id = get_user_id_from_cookie(request)

    # 全局查找任务（遍历所有用户目录）
    task = find_task_globally(task_id)

    if not task:
        logger.warning(f"[PDF 下载] 任务不存在: task_id={task_id}, user_id={user_id}")
        raise HTTPException(status_code=404, detail="任务不存在")

    # 验证任务所有权：is_public=True 时允许任何人下载
    task_user_id = task.get("user_id")
    is_public = task.get("is_public", False)

    if not is_public and task_user_id and task_user_id != user_id:
        logger.warning(
            f"[PDF 下载] 权限拒绝: user_id={user_id} 尝试下载 task_user_id={task_user_id} 的私有任务"
        )
        raise HTTPException(status_code=403, detail="只有任务创建者才能下载 PDF 报告")

    # 获取任务结果
    result = task.get("result")
    if not result:
        raise HTTPException(status_code=404, detail="分析结果不存在")

    # 确保数据是新格式（包含 coach_comment, problems, suggestions）
    result = _ensure_new_format(result, task_id)

    # 使用任务所属用户的目录获取关键帧图片
    task_user_id = task_user_id or user_id
    task_run_dir = get_user_run_dir(task_user_id) / task_id  # 修复：需要包含 task_id
    logger.info(f"[PDF 下载] task_user_id={task_user_id}, task_run_dir={task_run_dir}")

    try:
        logger.info(
            f"[PDF 下载] 开始生成 PDF: task_id={task_id}, task_run_dir={task_run_dir}"
        )
        pdf_data = generate_pdf_report(result, task_run_dir)
        logger.info(
            f"[PDF 下载] PDF 生成成功: task_id={task_id}, size={len(pdf_data)} bytes"
        )

        # 文件名：使用 ASCII 文件名 + RFC 5987 编码的中文文件名
        # 确保跨浏览器兼容性
        filename_zh = "乒乓球训练分析报告.pdf"
        filename_ascii = "pingpong_training_analysis_report.pdf"
        # 使用 RFC 5987 标准编码中文文件名
        filename_encoded = quote(filename_zh, safe="")

        # 返回 PDF 文件（使用 Response 直接返回 bytes）
        return Response(
            content=pdf_data,
            media_type="application/pdf",
            headers={
                # 同时提供 ASCII 和编码的中文文件名，确保兼容性
                "Content-Disposition": f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{filename_encoded}",
            },
        )

    except Exception as e:
        import traceback

        logger.error(f"[PDF 下载] 生成 PDF 失败: task_id={task_id}, error={e}")
        logger.error(f"[PDF 下载] 错误堆栈:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"生成 PDF 失败: {str(e)}")


@app.get("/videos/{task_id}")
async def get_task_video(task_id: str, request: Request):
    """
    获取任务的原始视频

    - 返回任务上传的原始视频文件
    - 支持视频流式播放
    - 如果任务已设为公开（is_public=True），任何人都可以访问
    - 否则仅允许访问任务创建者的数据
    - 支持历史任务（不在内存中）
    """
    # 获取当前请求用户的标识
    user_id = get_user_id_from_cookie(request)

    # 全局查找任务（遍历所有用户目录）
    task = find_task_globally(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 验证任务所有权：is_public=True 时允许任何人访问
    task_user_id = task.get("user_id")
    is_public = task.get("is_public", False)

    if not is_public and task_user_id and task_user_id != user_id:
        logger.warning(
            f"[视频访问] 权限拒绝: user_id={user_id} 尝试访问 task_user_id={task_user_id} 的私有任务"
        )
        raise HTTPException(status_code=403, detail="无权访问此任务")

    # 使用任务所属用户的目录获取视频文件
    task_user_id = task_user_id or user_id
    user_run_dir = get_user_run_dir(task_user_id)
    task_dir = user_run_dir / task_id

    # 查找视频文件（支持多种格式和命名）
    video_extensions = [".mp4", ".mov", ".avi", ".mkv"]
    video_path = None

    # 首先尝试查找 input.mp4（标准化命名）
    input_video = task_dir / "input.mp4"
    if input_video.exists():
        video_path = input_video
    else:
        # 查找任务目录下的任何视频文件
        for file in task_dir.iterdir():
            if file.is_file() and file.suffix.lower() in video_extensions:
                video_path = file
                break

    # 兼容旧任务：如果用户隔离目录找不到，尝试旧目录结构 data/runs/task_id/
    if not video_path:
        legacy_task_dir = RUNS_DIR / task_id
        if legacy_task_dir.exists():
            input_video = legacy_task_dir / "input.mp4"
            if input_video.exists():
                video_path = input_video
            else:
                for file in legacy_task_dir.iterdir():
                    if file.is_file() and file.suffix.lower() in video_extensions:
                        video_path = file
                        break

    if not video_path:
        raise HTTPException(status_code=404, detail="视频文件不存在")

    def iter_file():
        with open(video_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    # 根据文件扩展名确定 MIME 类型
    media_type = "video/mp4"
    if video_path.suffix.lower() == ".mov":
        media_type = "video/quicktime"
    elif video_path.suffix.lower() == ".avi":
        media_type = "video/x-msvideo"
    elif video_path.suffix.lower() == ".mkv":
        media_type = "video/x-matroska"

    return StreamingResponse(
        iter_file(),
        media_type=media_type,
        headers={
            # 使用 ASCII 文件名，避免中文编码问题
            "Content-Disposition": f'inline; filename="video{video_path.suffix}"',
            "Accept-Ranges": "bytes",
        },
    )


@app.websocket("/ws/tasks/{task_id}")
async def websocket_task_updates(websocket: WebSocket, task_id: str):
    """
    WebSocket 连接 - 实时接收任务状态更新

    - 连接格式: ws://localhost:8000/ws/tasks/{task_id}
    - 接收实时状态更新消息
    """
    await websocket.accept()
    logger.info(f"[WebSocket] 连接已建立: task_id={task_id}, client={websocket.client}")

    task = task_manager.get_task(task_id)
    if not task:
        logger.warning(f"[WebSocket] 任务不存在: task_id={task_id}")
        await websocket.close(code=1008, reason="任务不存在")
        return

    # 添加连接
    task_manager.add_websocket(task_id, websocket)

    # 获取请求信息用于构建完整 URL
    # WebSocket 可能没有 scheme，从 Host 推断或使用配置
    host = websocket.headers.get(
        "X-Forwarded-Host", websocket.headers.get("Host", "localhost:8000")
    )

    # 优先使用环境变量配置的 BASE_URL
    base_url = os.getenv("BASE_URL", "")
    if base_url:
        scheme = urlparse(base_url).scheme
    else:
        # 从 host 推断 scheme（如果是 443 端口或包含 https，则用 https）
        if ":443" in host or "https" in websocket.headers.get("X-Forwarded-Proto", ""):
            scheme = "https"
        else:
            scheme = "http"

    def build_url(path: str) -> str:
        """构建完整 URL"""
        if not path.startswith("/"):
            return path
        return f"{scheme}://{host}{path}"

    try:
        # 修复任务中的 URL 为完整路径
        task_to_send = dict(task)

        # 清理可能不可序列化的字段（如 result 中的复杂对象）
        if "result" in task_to_send and task_to_send["result"] is not None:
            # 确保 result 是可序列化的字典
            result = task_to_send["result"]
            if not isinstance(result, dict):
                # 如果 result 不是字典，转换为字符串或移除
                task_to_send["result"] = str(result) if result else None

        # 发送初始状态
        logger.debug(
            f"[WebSocket] 发送初始状态: task_id={task_id}, status={task_to_send.get('status')}"
        )
        await websocket.send_json(task_to_send)

        # 保持连接，接收客户端消息（如果有）
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info(f"[WebSocket] 客户端断开连接: task_id={task_id}")
        task_manager.remove_websocket(task_id, websocket)
    except Exception as e:
        logger.error(f"[WebSocket] 连接异常: task_id={task_id}, error={e}")
        task_manager.remove_websocket(task_id, websocket)
    finally:
        # 确保连接被清理
        task_manager.remove_websocket(task_id, websocket)
        logger.debug(f"[WebSocket] 连接已清理: task_id={task_id}")


# ============ 启动命令 ============

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
