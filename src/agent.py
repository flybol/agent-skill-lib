"""
CoachAgent - Agent（智谱 zai-sdk 版）

- 模型：glm-4.7-flash（文本）
- SDK：zai-sdk（ZhipuAiClient）
- 输出：严格 JSON（由 Prompt 强约束 + 解析器兜底）
- 兼容旧接口：保留 analyze_video / analyze_images 及其 *_with_fallback 入口
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from zai import ZhipuAiClient

from constants import AGENT_MODE_MOCK, AGENT_MODE_REAL
from errors import AgentError, AgentInvocationError, OutputParsingError

logger = logging.getLogger(__name__)

# MODEL_NAME = "glm-4.7-flash"
MODEL_NAME = "glm-4v-flash"


# =============================================================================
# Data Classes（保持与旧版一致）
# =============================================================================


@dataclass
class Problem:
    title: str
    evidence: str
    impact: str


@dataclass
class Improvement:
    title: str
    drills: list[str]
    checkpoints: list[str]
    evidence: str = ""


@dataclass
class SegmentFeedback:
    segment_id: int
    comment: str


@dataclass
class AnalysisReport:
    summary: str
    problems: list[dict[str, Any]]
    improvements: list[dict[str, Any]]
    segment_feedback: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisReport":
        """dict -> AnalysisReport（容错：忽略多余字段，缺失字段给默认值）"""

        def _pick(d: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for k in allowed:
                if k in d:
                    out[k] = d.get(k)
            return out

        problems = [
            Problem(**_pick(p, {"title", "evidence", "impact"}))
            for p in (data.get("problems", []) or [])
            if isinstance(p, dict)
        ]
        improvements = [
            Improvement(**_pick(i, {"title", "drills", "checkpoints", "evidence"}))
            for i in (data.get("improvements", []) or [])
            if isinstance(i, dict)
        ]
        segment_feedback = [
            SegmentFeedback(**_pick(s, {"segment_id", "comment"}))
            for s in (data.get("segment_feedback", []) or [])
            if isinstance(s, dict)
        ]

        return cls(
            summary=str(data.get("summary", "") or ""),
            problems=[asdict(p) for p in problems],
            improvements=[asdict(i) for i in improvements],
            segment_feedback=[asdict(s) for s in segment_feedback],
        )


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """
你是一名世界级乒乓球教练（长期带国家队/省队与高水平业余选手），擅长把复杂动作拆成“可练的最小动作单元”，并用最短路径提升稳定性与得分率。

你的任务：基于用户训练视频的“关键帧摘要（含 Frame 序号与时间）”与“特征摘要（如重心、站位、挥拍轨迹、击球点、还原节奏等）”，给出一份结构化训练报告：
- 先给总体结论（2-3句，抓住最影响得分的核心）
- 再给 3 个“主要问题”（必须是最影响稳定性/质量/衔接的前三个，按优先级排序）
- 再给 3 个“改进方案”（每条必须能直接照做：练什么、怎么练、练到什么标准）
- 最后对每个分段给出逐段点评（segment_feedback 覆盖所有 segment_id）

硬性输出要求（必须全部遵守）：
1) 输出必须是【有效 JSON】且【只输出 JSON】（禁止任何解释文字、前后缀、Markdown、代码块标记）。
2) 所有内容必须使用【简体中文】。
3) problems 必须恰好 3 条；improvements 必须恰好 3 条；segment_feedback 必须覆盖每个分段。
4) 任何判断都必须“有证据”：优先引用关键帧证据与特征数字；不要编造看不出来的细节。
5) 如果信息不足，必须明确写： “从当前帧摘要无法确定”，并给出补拍建议（机位/角度/帧率/覆盖范围/光线）。

顶级教练的输出风格要求：
- 评价要“抓关键”：优先讲影响最大的问题（比如击球点、重心与还原、发力链顺序、拍型稳定）。
- 建议要“可执行”：给出具体 drills（训练方法）与 checkpoints（量化或可观察标准）。
- 术语适度：可以专业，但必须让业余选手听得懂；必要时用一句话解释。
- 训练优先级明确：先稳定性，再质量（旋转/速度/落点），最后才是花式变化。
""".strip()


def _clip(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + "\n...(内容过长已截断)"


def build_user_prompt(
    frames_summary: str,
    features_summary: str,
    num_segments: int,
) -> str:
    return f"""
你将扮演「世界级乒乓球教练」（长期执教国家队/省队与高水平业余选手）。

你的目标不是描述动作，而是**像顶级教练一样提高得分率与稳定性**：
- 找出最影响训练质量的前三个关键问题（跨分段重复出现的优先）
- 给出最短训练路径：每条建议必须“立刻能练 + 有验收标准”
- 所有判断必须有证据；信息不足要明确指出并给出补拍建议

========================
【输入 1｜关键帧摘要（已按分段整理，包含 Frame 序号与时间）】
{frames_summary}

【输入 2｜特征摘要（站位、重心、挥拍轨迹、击球点、还原节奏等）】
{features_summary}

【分段数量】
视频被划分为 {num_segments} 个分段（segment_id 从 0 到 {num_segments - 1}）。
你必须对 **每一个分段** 给出点评。

========================
【必须输出的 JSON 结构（字段名固定，不得增删）】

{{
  "summary": "总体评价（2–3 句，必须点出：最影响得分/稳定性的一个核心问题 + 训练优先级）",
  "problems": [
    {{
      "title": "问题标题（短、准、可复述）",
      "evidence": "证据（必须引用 Frame <数字> at <数字>s，且至少来自 2 个不同分段）",
      "impact": "对稳定性 / 质量 / 衔接的直接影响"
    }}
  ],
  "improvements": [
    {{
      "title": "改进目标（与对应问题一一匹配）",
      "drills": [
        "训练方法 1（可直接照做）",
        "训练方法 2（可直接照做）"
      ],
      "checkpoints": [
        "检查点 1（可观察或可量化）",
        "检查点 2（可观察或可量化）"
      ],
      "evidence": "为什么这样练（引用帧或特征，说明与问题的因果关系）"
    }}
  ],
  "segment_feedback": [
    {{
      "segment_id": 0,
      "comment": "该分段的关键点评：指出本段最关键的问题或亮点 + 一条明确纠正/训练指令（必须引用 Frame 证据）"
    }}
  ]
}}

========================
【硬性约束（必须全部满足，否则视为失败）】

1️⃣ 只输出 **有效 JSON**，不得包含任何解释文字、Markdown、前后缀。
2️⃣ 全部使用【简体中文】。
3️⃣ problems 数组长度 **必须等于 3**，按“对得分率/稳定性的影响”从高到低排序。
4️⃣ improvements 数组长度 **必须等于 3**，并与 problems 一一对应：
   - 每条 improvements 至少包含 2 条 drills
   - 每条 improvements 至少包含 2 条 checkpoints
5️⃣ segment_feedback **必须覆盖所有分段**：
   - segment_id 从 0 到 {num_segments - 1}
   - 每个 segment_id 恰好 1 条

========================
【证据引用规则（极其重要）】

✅ segment_feedback.comment  
- 每一条都 **必须** 引用至少 1 个关键帧  
- 格式必须严格包含：  
  Frame <数字> at <数字>s  
  例如：Frame 128 at 4.12s

✅ problems.evidence  
- 必须引用 **至少 2 个不同分段** 的帧  
- 用来证明这是“跨分段反复出现”的核心问题

✅ improvements.evidence  
- 必须引用帧或特征摘要  
- 清楚说明：这个训练为什么能直接解决对应问题

❌ 禁止编造无法从输入推断的信息  
（例如：具体旋转强弱、精确落点、肉眼不可见的细节）

⚠️ 如果信息不足，必须明确写：
“从当前帧摘要无法确定”，并给出补拍建议，例如：
- 机位：侧后方 45° 优先，其次正侧面
- 覆盖：准备位 → 引拍 → 击球瞬间 → 还原
- 帧率：≥60fps，镜头稳定、光线充足

========================
【输出要求】
只输出 JSON。不要输出任何其他内容。
""".strip()


# =============================================================================
# Mock（用于 UI/流程调试）
# =============================================================================


def get_mock_report(num_segments: int = 8) -> AnalysisReport:
    n = max(1, int(num_segments))

    problems = [
        {
            "title": "击球后还原不及时",
            "evidence": "从多段节奏看，击球后准备位回收偏慢（从当前帧摘要无法确定具体拍形细节）。",
            "impact": "连续回合衔接变慢，来球稍快时容易被压制或出现二次失误。",
        },
        {
            "title": "重心波动偏大",
            "evidence": "准备—出手阶段身体重心起伏较大（从当前帧摘要无法确定脚下细节）。",
            "impact": "影响击球点稳定，导致落点与旋转一致性下降。",
        },
        {
            "title": "躯干带动不足、手臂主导发力",
            "evidence": "动作链更像“手臂摆动”而非“髋—肩—臂联动”（从当前帧摘要无法确定转髋幅度）。",
            "impact": "力量与控制上限受限，长时间训练更易疲劳。",
        },
    ]

    improvements = [
        {
            "title": "击球后快速还原训练（高频衔接）",
            "drills": [
                "对墙/多球：每次击球后立刻把拍面回到准备位，连续 30 球为一组，做 3 组。",
                "二点跑位（近台）：正手位—中路交替，小幅移动，强调还原速度与脚下节奏。",
            ],
            "checkpoints": [
                "击球后 0.3~0.5 秒内回到准备位（拍在身前）。",
                "重心回到双脚之间，不停在前脚或后脚。",
            ],
            "evidence": "建议通过节奏与还原训练建立稳定动作链。",
        },
        {
            "title": "重心控制与步法节奏训练（稳住下盘）",
            "drills": [
                "“半蹲准备位”定点拉球：保持膝微屈、髋稳定，连续 20 球，做 3 组。",
                "节拍器步法：用 60~80 BPM 节拍做小碎步，强调先到位再出手。",
            ],
            "checkpoints": [
                "准备位头部高度波动小（不明显起跳）。",
                "击球瞬间脚下有支撑感，不前冲抢球。",
            ],
            "evidence": "重心稳定是击球点与拍型稳定的前提。",
        },
        {
            "title": "躯干带动发力训练（髋—肩—臂顺序）",
            "drills": [
                "徒手分解：先转髋、再带肩、最后出手（慢动作 10 次 × 3 组）。",
                "轻球拉冲：先用躯干带动，手臂做“传导”，每组 20 球 × 3 组。",
            ],
            "checkpoints": [
                "启动顺序：髋先动 → 肩跟上 → 手臂最后加速。",
                "击球后躯干保持稳定，不耸肩、不侧倾。",
            ],
            "evidence": "躯干参与能提高一致性与力量上限。",
        },
    ]

    segment_feedback = [
        {
            "segment_id": i,
            "comment": "从当前帧摘要无法确定该段细节，请补拍：侧后方机位、60fps、覆盖全身与球台；示例引用：Frame 0 at 0.00s。",
        }
        for i in range(n)
    ]

    return AnalysisReport(
        summary="整体动作基础不错，但在稳定性与衔接上仍有提升空间。建议先把还原、重心与发力顺序练扎实。",
        problems=problems,
        improvements=improvements,
        segment_feedback=segment_feedback,
    )


# =============================================================================
# JSON 解析（兜底：从输出中提取第一个 JSON 对象）
# =============================================================================


def _parse_llm_json(raw: str) -> dict[str, Any]:
    s = (raw or "").strip()
    if not s:
        raise OutputParsingError("LLM response is empty.")

    # 兼容 ```json ... ``` 或 ``` ... ```
    if "```" in s:
        m = re.search(r"```json\s*(\{.*?\})\s*```", s, flags=re.DOTALL | re.IGNORECASE)
        if m:
            s = m.group(1).strip()
        else:
            m = re.search(r"```\s*(\{.*?\})\s*```", s, flags=re.DOTALL)
            if m:
                s = m.group(1).strip()

    # 兼容前后有废话：截取最外层 { ... }
    if not s.startswith("{"):
        first = s.find("{")
        last = s.rfind("}")
        if first != -1 and last != -1 and last > first:
            s = s[first : last + 1].strip()

    try:
        obj = json.loads(s)
    except json.JSONDecodeError as e:
        raise OutputParsingError(f"LLM response was not valid JSON: {e}") from e

    if not isinstance(obj, dict):
        raise OutputParsingError("LLM JSON root is not an object (dict).")
    return obj


# =============================================================================
# 智谱 SDK 调用（glm-4.7-flash）
# =============================================================================


def _get_client() -> ZhipuAiClient:
    api_key = os.environ.get("ZHIPU_API_KEY", "").strip()
    if not api_key:
        raise AgentInvocationError("ZHIPU_API_KEY environment variable not set.")
    return ZhipuAiClient(api_key=api_key)


def _call_glm4v_flash(messages: list[dict[str, Any]]) -> str | None:
    client = _get_client()

    max_attempts = int(os.environ.get("COACHAGENT_ZHIPU_RETRY_MAX", "3"))
    base_sleep = float(os.environ.get("COACHAGENT_ZHIPU_RETRY_BASE", "1.0"))

    temperature = float(os.environ.get("COACHAGENT_GLM_TEMPERATURE", "0.2"))
    top_p = float(os.environ.get("COACHAGENT_GLM_TOP_P", "0.6"))
    max_tokens = int(os.environ.get("COACHAGENT_GLM_MAX_TOKENS", "8192"))
    thinking_type = (
        os.environ.get("COACHAGENT_GLM_THINKING", "enabled").strip() or "enabled"
    )

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
            )
            return resp.choices[0].message.content
        except Exception as e:
            last_exc = e
            sleep_s = base_sleep * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(
                f"Zhipu {MODEL_NAME} call failed. attempt={attempt}/{max_attempts}, sleep={sleep_s:.2f}s, err={e}"
            )
            time.sleep(sleep_s)

    raise AgentInvocationError(
        f"Zhipu {MODEL_NAME} request failed after retries: {last_exc}"
    )


# =============================================================================
# Public APIs（兼容旧调用点）
# =============================================================================


def analyze_video(
    frames_summary: str,
    features_summary: str,
    num_segments: int,
    mode: str = AGENT_MODE_REAL,
) -> AnalysisReport:
    """文本分析入口：frames_summary + features_summary -> JSON 报告"""
    if mode == AGENT_MODE_MOCK:
        return get_mock_report(num_segments)

    if mode != AGENT_MODE_REAL:
        raise AgentError(f"Unknown agent mode: {mode}")

    prompt = build_user_prompt(frames_summary, features_summary, num_segments)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    raw = _call_glm4v_flash(messages)
    data = _parse_llm_json(raw)
    return AnalysisReport.from_dict(data)


def analyze_video_with_fallback(
    frames_summary: str,
    features_summary: str,
    num_segments: int,
    mode: str = AGENT_MODE_MOCK,
) -> AnalysisReport:
    """失败兜底：任何异常 -> mock"""
    try:
        return analyze_video(frames_summary, features_summary, num_segments, mode)
    except AgentError as e:
        logger.warning(f"Agent failed, falling back to mock: {e}")
        return get_mock_report(num_segments)
    except Exception as e:
        logger.error(f"Unexpected error in agent: {e}")
        logger.warning("Falling back to mock due to unexpected error.")
        return get_mock_report(num_segments)


def analyze_images(
    frames_summary: str,
    num_segments: int,
    image_paths: list[str],
    mode: str = AGENT_MODE_REAL,
) -> AnalysisReport:
    """
    兼容旧“视觉分析”入口。

    说明：
    - glm-4.7-flash 为文本模型，这里不会上传图片内容。
    - 我们只把“图片文件名列表”作为补充说明，并主要依赖 frames_summary 做分析。
    """
    if mode == AGENT_MODE_MOCK:
        return get_mock_report(num_segments)

    if mode != AGENT_MODE_REAL:
        raise AgentError(f"Unknown agent mode: {mode}")

    # 只保留文件名，避免泄露路径；并限制数量，避免提示词过长
    names = [Path(p).name for p in (image_paths or []) if p]
    names = names[:20]

    prompt = build_user_prompt(
        frames_summary,
        features_summary="",
        num_segments=num_segments,
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    raw = _call_glm4v_flash(messages)
    data = _parse_llm_json(raw)
    return AnalysisReport.from_dict(data)


def analyze_images_with_fallback(
    frames_summary: str,
    num_segments: int,
    image_paths: list[str],
    mode: str = AGENT_MODE_MOCK,
) -> AnalysisReport:
    """失败兜底：任何异常 -> mock"""
    try:
        return analyze_images(frames_summary, num_segments, image_paths, mode)
    except AgentError as e:
        logger.warning(f"Vision/text agent failed, falling back to mock: {e}")
        return get_mock_report(num_segments)
    except Exception as e:
        logger.error(f"Unexpected error in vision/text agent: {e}")
        logger.warning("Falling back to mock due to unexpected error.")
        return get_mock_report(num_segments)
