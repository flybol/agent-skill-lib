"""
CoachAgent - Agent（智谱 zai-sdk 版）

- 模型：glm-4v-flash
- SDK：zai-sdk（ZhipuAiClient）
- 输出：严格 JSON（教练口语化风格）
- 报告格式：教练实战版训练报告
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from zai import ZhipuAiClient

from constants import AGENT_MODE_MOCK, AGENT_MODE_REAL
from errors import AgentError, AgentInvocationError, OutputParsingError

logger = logging.getLogger(__name__)

MODEL_NAME = "glm-4v-flash"


# =============================================================================
# Data Classes - 教练实战版报告格式
# =============================================================================


@dataclass
class TopProblem:
    """核心问题（教练口语化）"""
    id: str  # P1, P2, P3
    title: str  # 问题标题（口语化）
    key_features: list[str]  # 关键表现（你现在在做什么）
    direct_consequences: list[str]  # 直接后果（比赛会发生什么）
    coach_judgment: str  # 教练判断（一句话点出本质）
    priority_rank: int  # 优先级排序


@dataclass
class ImprovementPlan:
    """改进方案（可直接训练）"""
    title: str  # 改进重点
    training_methods: list[str]  # 训练方法
    self_check_criteria: list[str]  # 自检标准


@dataclass
class SegmentNote:
    """分段点评"""
    segment_id: int  # 段落ID
    title: str  # 段落标题
    coach_comment: str  # 教练点评
    evidence: list[dict[str, Any]]  # 证据列表（帧号、时间、备注）


@dataclass
class CoachReport:
    """教练实战版训练报告"""
    one_sentence: str  # 一句话总结（教练视角）
    top_problems: list[dict[str, Any]]  # 核心问题（3条）
    training_plan: dict[str, Any]  # 训练计划
    segment_notes: list[dict[str, Any]]  # 分段点评

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CoachReport":
        """dict -> CoachReport（容错解析）"""

        # 解析 top_problems
        problems_data = data.get("top_problems", []) or []
        problems = []
        for p in problems_data:
            if isinstance(p, dict):
                problems.append(TopProblem(
                    id=p.get("id", "P1"),
                    title=p.get("title", ""),
                    key_features=p.get("key_features", []),
                    direct_consequences=p.get("direct_consequences", []),
                    coach_judgment=p.get("coach_judgment", ""),
                    priority_rank=p.get("priority_rank", 1)
                ))

        # 解析 segment_notes
        notes_data = data.get("segment_notes", []) or []
        notes = []
        for n in notes_data:
            if isinstance(n, dict):
                notes.append(SegmentNote(
                    segment_id=n.get("segment_id", 0),
                    title=n.get("title", ""),
                    coach_comment=n.get("coach_comment", ""),
                    evidence=n.get("evidence", [])
                ))

        return cls(
            one_sentence=str(data.get("one_sentence", "") or ""),
            top_problems=[asdict(p) for p in problems],
            training_plan=data.get("training_plan", {}),
            segment_notes=[asdict(n) for n in notes]
        )


# =============================================================================
# Mock - 教练实战版示例报告
# =============================================================================


def get_mock_report(num_segments: int = 2) -> CoachReport:
    """生成教练实战版 mock 报告"""
    n = max(1, int(num_segments))

    problems = [
        TopProblem(
            id="P1",
            title='下盘不稳，击球时重心"飘"',
            key_features=[
                "击球瞬间身体上下起伏",
                "脚没完全踩实就出手"
            ],
            direct_consequences=[
                "球速和落点不稳定",
                "一加力就容易失误"
            ],
            coach_judgment="下盘没站住，上肢只能靠手补，稳定性必然下降。",
            priority_rank=1
        ),
        TopProblem(
            id="P2",
            title="挥拍节奏断，力量传递不顺",
            key_features=[
                "挥拍过程中有停顿",
                "手先动，身体慢半拍"
            ],
            direct_consequences=[
                "发力不集中",
                '球"有动作没质量"'
            ],
            coach_judgment='身体没参与完整发力，挥拍是"分段式"的。',
            priority_rank=2
        ),
        TopProblem(
            id="P3",
            title="击球点不固定",
            key_features=[
                "击球高度和时机变化大",
                "同样来球，处理不一致"
            ],
            direct_consequences=[
                "命中率下降",
                "不敢连续进攻"
            ],
            coach_judgment="这是前两个问题的必然结果。",
            priority_rank=3
        )
    ]

    training_plan = {
        "session_goal": "先稳住下盘与节奏，再提升击球质量",
        "improvements": [
            {
                "title": "改进重点 1：先稳住下盘，再谈发力",
                "training_methods": [
                    "原地连续击球，刻意降低重心",
                    "击球后停 1 秒，感受脚是否踩实"
                ],
                "self_check_criteria": [
                    "击完球身体不晃",
                    "能连续击球不慌"
                ]
            },
            {
                "title": '改进重点 2：挥拍"一口气"完成',
                "training_methods": [
                    "慢动作完整挥拍（身体→手→收拍）",
                    "禁止中途停顿"
                ],
                "self_check_criteria": [
                    "挥拍过程中没有卡顿感",
                    '发力感觉是"顺着出去的"'
                ]
            },
            {
                "title": "改进重点 3：固定击球点训练",
                "training_methods": [
                    "多球定点练习",
                    "只允许在最佳击球区出手"
                ],
                "self_check_criteria": [
                    "连续击中同一区域",
                    "出手时机稳定"
                ]
            }
        ]
    }

    notes = []
    for i in range(n):
        if i == 0:
            notes.append(SegmentNote(
                segment_id=i,
                title="下盘与稳定性",
                coach_comment="这一段主要问题是重心没落稳，先把脚下踩住。",
                evidence=[
                    {"frame_index": 5, "time_s": 0.17, "note": "击球瞬间身体起伏/支撑不稳"},
                    {"frame_index": 22, "time_s": 0.73, "note": "击球后回位慢/重心漂"}
                ]
            ))
        else:
            notes.append(SegmentNote(
                segment_id=i,
                title="挥拍连贯性与发力顺序",
                coach_comment="挥拍有断点，注意一口气做完，髋先走手跟上。",
                evidence=[
                    {"frame_index": 9, "time_s": 0.3, "note": "挥拍节奏断/发力不顺"},
                    {"frame_index": 26, "time_s": 0.87, "note": "收拍不完整/力量传递中断"}
                ]
            ))

    return CoachReport(
        one_sentence="这段视频里，你的问题不在手，而在脚下没踩住、身体发力断。重心不稳 → 挥拍不连 → 击球点漂，这是一条完整的问题链。",
        top_problems=[asdict(p) for p in problems],
        training_plan=training_plan,
        segment_notes=[asdict(n) for n in notes]
    )


# =============================================================================
# Prompt - 教练口语化风格
# =============================================================================

SYSTEM_PROMPT = """
你是一名世界级乒乓球教练（长期带国家队/省队与高水平业余选手）。

**你的说话风格**：
- 像在训练场跟运动员说话，不是写分析报告
- 用词简洁有力，直击要害
- 多用短句、口语化表达
- 避免"泛运动学"术语，用乒乓球教练常用语

**你的任务**：
基于用户训练视频的关键帧摘要与特征摘要，输出一份**教练实战版训练报告**。

**核心原则**：
1. 抓核心问题（3个）：按对得分率/稳定性的影响排序
2. 每个问题包含：关键表现 + 直接后果 + 教练判断（一句话点出本质）
3. 改进方案要"立刻能练 + 有验收标准"
4. 用教练的语言，不是算法的语言

**教练用语示例**：
- ❌ "挥拍轨迹不连贯" → ✅ "挥拍有断点"
- ❌ "发力传递效率低" → ✅ "发力不顺"
- ❌ "击球点不稳定" → ✅ "击球点漂"
- ❌ "重心控制不足" → ✅ "下盘不稳"

**输出格式**：
只输出 JSON，不要有任何解释文字、Markdown 标记。
""".strip()


def build_user_prompt(
    frames_summary: str,
    features_summary: str,
    num_segments: int,
) -> str:
    return f"""
你将扮演「乒乓球教练」（长期执教国家队/省队）。

你的输出风格要求：
- **像教练说话，不是像算法写报告**
- 短句、口语化、直击要害
- 让运动员一听就懂

========================
【输入数据】

**关键帧摘要（已按分段整理）**
{frames_summary}

**特征摘要（站位、重心、挥拍轨迹、击球点、还原节奏等）**
{features_summary}

**分段数量**
视频被划分为 {num_segments} 个分段（segment_id 从 0 到 {num_segments - 1}）。

========================
【必须输出的 JSON 结构】

{{
  "one_sentence": "一句话总结（教练视角）",
  "top_problems": [
    {{
      "id": "P1",
      "title": "问题标题（口语化，4-8字）",
      "key_features": [
        "你现在在做什么 1",
        "你现在在做什么 2"
      ],
      "direct_consequences": [
        "比赛会发生什么 1",
        "比赛会发生什么 2"
      ],
      "coach_judgment": "教练判断（一句话点出本质）",
      "priority_rank": 1
    }}
  ],
  "training_plan": {{
    "session_goal": "本次训练目标（一句话）",
    "improvements": [
      {{
        "title": "改进重点 X：简短标题",
        "training_methods": [
          "具体训练方法 1",
          "具体训练方法 2"
        ],
        "self_check_criteria": [
          "自检标准 1",
          "自检标准 2"
        ]
      }}
    ]
  }},
  "segment_notes": [
    {{
      "segment_id": 0,
      "title": "段落标题",
      "coach_comment": "教练点评（必须引用 Frame 证据）",
      "evidence": [
        {{"frame_index": 5, "time_s": 0.17, "note": "观察到什么"}}
      ]
    }}
  ]
}}

========================
【硬性约束】

1️⃣ 只输出 JSON，无任何其他内容
2️⃣ 全部使用【简体中文】
3️⃣ top_problems 恰好 3 条，按影响排序
4️⃣ improvements 恰好 3 条
5️⃣ segment_notes 覆盖所有分段（segment_id 0 到 {num_segments - 1}）

========================
【教练用语指南】

**问题命名示例**：
- "下盘不稳，击球时重心'飘'"
- "挥拍节奏断，力量传递不顺"
- "击球点不固定"
- "还原不及时"
- "发力链不顺"

**教练判断示例**：
- "下盘没站住，上肢只能靠手补"
- "身体没参与完整发力，挥拍是分段式的"
- "这是前两个问题的必然结果"
- "核心问题没解决，这是表象不是原因"

**避免使用**：
- ❌ "轨迹"、"矢量"、"角度"、"加速度"
- ❌ "传递效率"、"运动链"
- ❌ "稳定性不足"、"一致性差"

**推荐使用**：
- ✅ "挥拍有断点"、"发力不顺"
- ✅ "下盘不稳"、"重心飘"
- ✅ "击球点漂"、"出手慢"
- ✅ "还原不及时"、"回位慢"

========================
【证据引用规则】

segment_notes.coach_comment 必须引用 Frame 证据：
- 格式：Frame <数字> at <数字>s
- 示例：Frame 128 at 4.12s

如果信息不足，明确写：
"从当前帧摘要无法确定"，并给出补拍建议：
- 机位：侧后方 45°
- 帧率：≥60fps
- 覆盖：准备位 → 引拍 → 击球 → 还原

========================
【输出要求】
只输出 JSON。不要输出任何其他内容。
""".strip()


# =============================================================================
# JSON 解析（兜底）
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
# 智谱 SDK 调用
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
# Public APIs
# =============================================================================


def analyze_video(
    frames_summary: str,
    features_summary: str,
    num_segments: int,
    mode: str = AGENT_MODE_REAL,
) -> CoachReport:
    """文本分析入口：frames_summary + features_summary -> 教练报告"""
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
    return CoachReport.from_dict(data)


def analyze_video_with_fallback(
    frames_summary: str,
    features_summary: str,
    num_segments: int,
    mode: str = AGENT_MODE_MOCK,
) -> CoachReport:
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
) -> CoachReport:
    """兼容旧"视觉分析"入口"""
    if mode == AGENT_MODE_MOCK:
        return get_mock_report(num_segments)

    if mode != AGENT_MODE_REAL:
        raise AgentError(f"Unknown agent mode: {mode}")

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
    return CoachReport.from_dict(data)


def analyze_images_with_fallback(
    frames_summary: str,
    num_segments: int,
    image_paths: list[str],
    mode: str = AGENT_MODE_MOCK,
) -> CoachReport:
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
