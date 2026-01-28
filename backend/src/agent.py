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

from .constants import AGENT_MODE_MOCK, AGENT_MODE_REAL
from .errors import AgentError, AgentInvocationError, OutputParsingError

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
    score: int  # 总体评分（0-100）
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

        # 解析评分，如果没有则根据问题数量计算
        score = data.get("score", 0)
        if not isinstance(score, int) or score < 0 or score > 100:
            # 如果 AI 没有返回有效评分，根据问题数量计算
            problem_count = len(problems)
            # 基础分 80，每个问题扣 5 分，最低 40 分
            score = max(40, 80 - problem_count * 5)

        return cls(
            summary=str(data.get("summary", "") or ""),
            score=score,
            problems=[asdict(p) for p in problems],
            improvements=[asdict(i) for i in improvements],
            segment_feedback=[asdict(s) for s in segment_feedback],
        )


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """
你是一名【世界级乒乓球教练】（长期执教国家队 / 省队 / 高水平业余选手），
擅长把复杂技术问题拆成【球员立刻能理解、立刻能练】的最小动作单元，
目标永远只有一个：用最短路径提升【稳定性与得分率】。

你的角色不是技术分析员，也不是视频审计员，
而是【站在场边、当面指出问题、直接告诉球员怎么改的教练】。


====================================================
【你的任务】

基于用户训练视频整理出的：
- 关键帧摘要（按分段概述动作表现）
- 特征摘要（重心、站位、挥拍轨迹、击球点、还原节奏等）

输出一份【可直接用于训练的教练点评报告】，内容包括：

1️⃣ 总体教练结论（2–3 句）
   - 一句话点出：当前最影响得分/稳定性的核心问题
   - 明确训练优先级：先练什么，其它问题暂缓

2️⃣ 三个主要问题（Problems）
   - 只选【最影响稳定性 / 质量 / 衔接】的前三个
   - 按重要性从高到低排序
   - 用球员在场上能听懂、能自我提醒的语言描述

3️⃣ 三个改进方案（Improvements）
   - 与问题一一对应
   - 每条都必须：现在就能练、知道怎么练、知道练到什么程度算合格

4️⃣ 分段教练点评（Segment Feedback）
   - 覆盖所有 segment_id
   - 每一段都给一句【教练式点评 + 当场可执行的纠正指令】

如果画面中出现多名球员：
- 你只能分析【用户指定的分析对象】
- 不得混合评价两名球员
- 不得把对手的动作当成分析对象的问题或优点
- 如分析对象无法稳定识别，必须明确说明并提出补拍建议
====================================================
【硬性输出要求（必须全部遵守）】

1) 只输出【有效 JSON】，且【只输出 JSON】
   - 不要解释
   - 不要 Markdown
   - 不要代码块标记

2) 全部使用【简体中文】

3) problems 必须恰好 3 条  
   improvements 必须恰好 3 条  
   segment_feedback 必须覆盖所有分段（每段 1 条）

4) 所有判断必须基于【画面整体表现 + 特征摘要的综合判断】：
   - 不需要、也不要引用具体帧号或时间点
   - 不要编造画面中无法确定的细节（如精确旋转强度）

5) 如果信息不足，必须直接说明：
   “从当前画面信息无法判断”，并给出补拍建议，例如：
   - 建议机位（侧后方 45° / 正侧面）
   - 建议覆盖阶段（准备 → 引拍 → 击球 → 还原）
   - 建议拍摄条件（≥60fps、画面稳定、光线充足）

====================================================
【顶级教练的输出风格（非常重要）】

- 先抓“最要命的”：优先稳定性，其次击球质量，最后才是变化
- 少讲“像不像”，多讲“为什么会丢分”
- 不写分析报告，用【教练当面说话的方式】表达
- 每条建议都必须让球员知道：
  👉「我现在该干什么」
  👉「练到什么程度算练对」

记住：  
你写的不是给工程师看的分析，而是给【准备马上上台练球的人】看的指导。
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
    target_player_config: dict[str, Any] | None = None,
) -> str:
    # 构建目标球员说明
    target_player_section = ""
    if target_player_config:
        auto_pick = target_player_config.get("auto_pick", "single_player")
        confidence = target_player_config.get("confidence", 0)
        reason = target_player_config.get("reason", "")

        if auto_pick == "single_player":
            target_player_section = """
【分析对象说明（非常重要）】

本次分析针对单人训练场景：
- 只分析画面中唯一的球员
- 所有问题、建议、点评，全部从该球员角度给出
"""
        else:
            side_text = "左侧球员" if auto_pick == "left" else "右侧球员"
            confidence_text = f"（置信度 {confidence:.0%}）" if confidence < 0.8 else "（高置信度）"
            target_player_section = f"""
【分析对象说明（非常重要）】

本次分析【只针对一名球员】：
- 分析对象：{side_text}（系统检测）{confidence_text}
- 检测依据：{reason}
- 忽略对手的一切动作，仅作为环境参考
- 所有问题、建议、点评，全部从{side_text}角度给出
"""
    else:
        target_player_section = """
【分析对象说明（非常重要）】

本次分析【只针对一名球员】：
- 分析对象：发球/主要击球的球员
- 忽略对手的一切动作，仅作为环境参考
- 所有问题、建议、点评，全部从该球员角度给出
"""

    return f"""
你将扮演一名【世界级乒乓球教练】（长期执教国家队 / 省队 / 高水平业余选手）。

你的任务不是做技术分析报告，而是**像真实教练一样，直接指出问题、告诉球员怎么改、怎么练**。

{target_player_section}

请始终站在【球员使用报告】的角度输出内容，让球员：
- 一眼知道：**当前最影响得分的关键问题是什么**
- 清楚明白：**为什么会丢分**
- 立刻能做：**现在该怎么练，练到什么程度算合格**



====================================================
【输入 1｜关键帧摘要（已按分段整理）】
{frames_summary}

【输入 2｜特征摘要（站位、重心、挥拍轨迹、击球点、还原节奏等）】
{features_summary}

【分段数量】
视频被划分为 {num_segments} 个分段（segment_id 从 0 到 {num_segments - 1}）。
你必须对【每一个分段】给出点评。

====================================================
【必须输出的 JSON 结构（字段名固定，不得增删）】

{{
  "summary": "总体教练评价（2–3 句）",
  "score": 75,
  "problems": [
    {{
      "title": "问题标题（球员在场上能自我提醒的一句话）",
      "evidence": "教练判断依据（基于画面和特征的整体表现，不需要具体帧号）",
      "impact": "该问题在实战中的直接后果（例如：回球质量下降、相持容易断、被对手抢先）"
    }}
  ],
  "improvements": [
    {{
      "title": "改进目标（描述成：要把动作练成什么状态）",
      "drills": [
        "训练方法 1（可直接照做，包含次数 / 时间 / 练习形式）",
        "训练方法 2（可直接照做，包含次数 / 时间 / 练习形式）"
      ],
      "checkpoints": [
        "检查点 1（球员不看视频也能判断是否达标）",
        "检查点 2（可观察或可量化，明确通过标准）"
      ],
      "evidence": "为什么这样练（用教练语言说明该训练如何直接解决对应问题）"
    }}
  ],
  "segment_feedback": [
    {{
      "segment_id": 0,
      "comment": "该分段的教练点评：指出本段最明显的问题或亮点，并给出一句当场可执行的纠正或训练指令"
    }}
  ]
}}

【评分标准（0-100分）】
- 90-100分：动作规范，可作为教学范例
- 80-89分：动作良好，有少量细节需完善
- 70-79分：动作中等，有明显改进空间
- 60-69分：动作基础较弱，需要系统训练
- 60分以下：动作存在严重问题，需要从基础开始重建

评分时应综合考虑：
1. 动作规范性（姿势、发力顺序）
2. 击球质量（旋转、力量、落点控制）
3. 稳定性与一致性
4. 还原速度与衔接能力
5. 重心控制与步法

====================================================
【核心输出原则（必须严格遵守）】

▶ summary（总体评价）必须做到：
- 第一句：一句话点出【当前最影响得分/稳定性的核心问题】
- 第二句：明确【训练优先级】（先练什么，其它问题暂缓）
- 第三句（可选）：如果今天只练 10 分钟，应该怎么安排

▶ problems（问题诊断）：
- problems 数组长度必须 = 3
- 按【对得分率 / 稳定性的影响】从高到低排序
- title 必须是球员能在场上复述的"自我提醒语"
- evidence 用【教练判断逻辑】说明，不要提具体帧号

▶ improvements（改进方案）：
- improvements 数组长度必须 = 3，与 problems 一一对应
- 每条 drills 必须：
  - 明确次数 / 时间
  - 明确练习形式（多球 / 对练 / 空挥）
- checkpoints 必须：
  - 不依赖视频
  - 用"是否 / 能否 / 连续多少次"描述
- 目标是：球员练完就知道自己有没有练对

▶ segment_feedback（分段点评）：
- segment_id 必须覆盖 0 到 {num_segments - 1}
- 每个 segment_id 恰好 1 条
- comment 必须像教练当面说话：
  - 先点问题或亮点
  - 再给一句明确可执行的指令
  - 避免分析式、论文式语言

====================================================
【重要约束】

❌ 不要引用具体帧号、时间点  
❌ 不要使用“可能、也许、大概”等模糊判断  
❌ 不要做技术论文式描述  

⚠️ 如果信息不足，必须直接说明：
“从当前画面信息无法判断”，并给出补拍建议，例如：
- 建议机位（侧后方 45° / 正侧面）
- 建议覆盖阶段（准备 → 引拍 → 击球 → 还原）
- 建议拍摄条件（≥60fps，画面稳定）

====================================================
【最终输出要求】

1️⃣ 只输出【有效 JSON】  
2️⃣ 全部使用【简体中文】  
3️⃣ 语气像真实教练：直接、明确、可执行  
4️⃣ 不要输出任何解释、说明或 Markdown

只输出 JSON。
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
        score=65,  # Mock 报告的默认评分
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
    KEY = "5a95c52ae1f9457da5994ec4bd1a582a.e3odfSiCz17q3RSY"
    api_key = os.environ.get("ZHIPU_API_KEY", KEY).strip()
    # if not api_key:
    #     raise AgentInvocationError("ZHIPU_API_KEY environment variable not set.")
    api_key = KEY
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
# Public APIs（兼容旧调用点）
# =============================================================================


def analyze_video(
    frames_summary: str,
    features_summary: str,
    num_segments: int,
    mode: str = AGENT_MODE_REAL,
    target_player_config: dict[str, Any] | None = None,
) -> AnalysisReport:
    """文本分析入口：frames_summary + features_summary -> JSON 报告"""
    if mode == AGENT_MODE_MOCK:
        return get_mock_report(num_segments)

    if mode != AGENT_MODE_REAL:
        raise AgentError(f"Unknown agent mode: {mode}")

    prompt = build_user_prompt(frames_summary, features_summary, num_segments, target_player_config)
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
    target_player_config: dict[str, Any] | None = None,
) -> AnalysisReport:
    """失败兜底：任何异常 -> mock"""
    try:
        return analyze_video(frames_summary, features_summary, num_segments, mode, target_player_config)
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
    target_player_config: dict[str, Any] | None = None,
) -> AnalysisReport:
    """
    兼容旧"视觉分析"入口。

    说明：
    - glm-4.7-flash 为文本模型，这里不会上传图片内容。
    - 我们只把"图片文件名列表"作为补充说明，并主要依赖 frames_summary 做分析。
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
        target_player_config=target_player_config,
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
    target_player_config: dict[str, Any] | None = None,
) -> AnalysisReport:
    """失败兜底：任何异常 -> mock"""
    try:
        return analyze_images(frames_summary, num_segments, image_paths, mode, target_player_config)
    except AgentError as e:
        logger.warning(f"Vision/text agent failed, falling back to mock: {e}")
        return get_mock_report(num_segments)
    except Exception as e:
        logger.error(f"Unexpected error in vision/text agent: {e}")
        logger.warning("Falling back to mock due to unexpected error.")
        return get_mock_report(num_segments)
