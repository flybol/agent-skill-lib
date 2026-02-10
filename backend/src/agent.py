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


def _clean_coach_comment_prefix(text: str) -> str:
    """清理教练评语中的前缀标签（优点：、存在问题：、总结：）"""
    if not text:
        return ""

    # 定义需要移除的前缀列表
    prefixes = ["优点：", "存在问题：", "总结："]

    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix):].strip()

    return text


def _normalize_coach_comment_field(value: Any) -> str:
    """规范化教练评语字段，确保返回字符串

    如果是数组，转换为逗号分隔的字符串
    如果是其他类型，转换为字符串
    """
    if not value:
        return ""

    # 如果是数组或列表，转换为逗号分隔的字符串
    if isinstance(value, (list, tuple)):
        return "，".join(str(item) for item in value if item)

    # 如果是字典，尝试提取内容
    if isinstance(value, dict):
        if "text" in value:
            value = value["text"]
        elif "content" in value:
            value = value["content"]

    return str(value)


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
class TrainingProblem:
    """训练问题"""
    title: str  # 问题标题
    description: str  # 问题描述


@dataclass
class TrainingSuggestion:
    """训练建议"""
    title: str  # 建议标题
    description: str  # 建议描述


@dataclass
class CoachComment:
    """教练评语"""
    strengths: str  # 优点
    weaknesses: str  # 存在问题
    summary: str  # 总结


@dataclass
class AnalysisReport:
    """分析报告"""
    coach_comment: CoachComment  # 教练评语
    score: int  # 总体评分（0-100）
    problems: list[dict[str, Any]]  # 训练问题（3点）
    suggestions: list[dict[str, Any]]  # 训练建议（3点）
    segment_feedback: list[dict[str, Any]]  # 分段反馈

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        # 将 coach_comment 从 dataclass 转为 dict
        if isinstance(result.get('coach_comment'), CoachComment):
            result['coach_comment'] = asdict(result['coach_comment'])
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisReport":
        """dict -> AnalysisReport（容错：忽略多余字段，缺失字段给默认值）"""

        def _pick(d: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for k in allowed:
                if k in d:
                    out[k] = d.get(k)
            return out

        # 解析教练评语（兼容数组和字符串格式）
        coach_comment_data = data.get("coach_comment", {})
        if isinstance(coach_comment_data, dict):
            # 使用规范化函数处理 strengths 和 weaknesses
            strengths_raw = coach_comment_data.get("strengths", "")
            weaknesses_raw = coach_comment_data.get("weaknesses", "")
            summary_raw = coach_comment_data.get("summary", "")

            coach_comment = CoachComment(
                strengths=_clean_coach_comment_prefix(_normalize_coach_comment_field(strengths_raw)),
                weaknesses=_clean_coach_comment_prefix(_normalize_coach_comment_field(weaknesses_raw)),
                summary=_clean_coach_comment_prefix(_normalize_coach_comment_field(summary_raw)),
            )
        else:
            # 兼容旧格式：如果没有 coach_comment，从 summary 中生成
            summary_text = str(data.get("summary", "") or "")
            coach_comment = CoachComment(
                strengths="整体动作基础不错",
                weaknesses=summary_text,
                summary="建议继续加强练习",
            )

        # 解析训练问题（兼容旧格式）
        problems_data = data.get("problems", [])
        problems = []
        for p in (problems_data or []):
            if isinstance(p, dict):
                # 新格式：title + description
                if "description" in p:
                    problems.append(TrainingProblem(
                        title=str(p.get("title", "")),
                        description=str(p.get("description", ""))
                    ))
                else:
                    # 旧格式：title + evidence + impact
                    problems.append(TrainingProblem(
                        title=str(p.get("title", "")),
                        description=f"依据：{p.get('evidence', '')}\n影响：{p.get('impact', '')}"
                    ))

        # 确保恰好3个问题
        while len(problems) < 3:
            problems.append(TrainingProblem(
                title="需要加强练习",
                description="请继续训练以提升动作稳定性"
            ))

        # 解析训练建议（兼容旧格式）
        suggestions_data = data.get("suggestions", []) or data.get("improvements", [])
        suggestions = []
        for s in (suggestions_data or []):
            if isinstance(s, dict):
                # 新格式：title + description
                if "description" in s:
                    suggestions.append(TrainingSuggestion(
                        title=str(s.get("title", "")),
                        description=str(s.get("description", ""))
                    ))
                else:
                    # 旧格式：title + drills + checkpoints
                    drills = s.get("drills", [])
                    drills_text = "\n".join(drills) if drills else ""
                    suggestions.append(TrainingSuggestion(
                        title=str(s.get("title", "")),
                        description=drills_text or s.get("evidence", "")
                    ))

        # 确保恰好3个建议
        while len(suggestions) < 3:
            suggestions.append(TrainingSuggestion(
                title="加强基础训练",
                description="建议多加练习，提升动作规范性"
            ))

        # 解析分段反馈
        segment_feedback = [
            SegmentFeedback(**_pick(s, {"segment_id", "comment"}))
            for s in (data.get("segment_feedback", []) or [])
            if isinstance(s, dict)
        ]

        # 解析评分
        score = data.get("score", 0)
        if not isinstance(score, int) or score < 0 or score > 100:
            problem_count = len(problems)
            score = max(40, 80 - problem_count * 5)

        return cls(
            coach_comment=coach_comment,
            score=score,
            problems=[asdict(p) for p in problems[:3]],  # 只取前3个
            suggestions=[asdict(s) for s in suggestions[:3]],  # 只取前3个
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
        scene_type = target_player_config.get("scene_type", "single")
        confidence = target_player_config.get("confidence", 0)
        reason = target_player_config.get("reason", "")

        if auto_pick == "single_player":
            # 根据场景类型生成不同的说明
            if scene_type == "dual_practice":
                target_player_section = """
【分析对象说明（非常重要）】

本次分析针对双人对练场景：
- 画面中有两名球员同时训练
- 只分析用户指定的目标球员
- 所有问题、建议、点评，全部从该目标球员角度给出
"""
            else:
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
  "coach_comment": {{
    "strengths": "站位较为稳定，挥拍轨迹基本顺畅，还原及时。注意：这里是字符串格式，多个优点用逗号或句号连接，不要使用数组。",
    "weaknesses": "击球点偏后导致回球不稳定，还原节奏较慢影响连续性。注意：这里是字符串格式，多个问题用逗号或句号连接，不要使用数组。",
    "summary": "整体动作基础良好，需要重点改进击球点和还原速度。"
  }},
  "score": 75,
  "problems": [
    {{
      "title": "问题标题（简短明确）",
      "description": "详细描述该问题的具体表现和影响"
    }}
  ],
  "suggestions": [
    {{
      "title": "建议标题（训练目标）",
      "description": "具体的训练方法和练习内容（包含练习形式、次数、时间等）"
    }}
  ],
  "segment_feedback": [
    {{
      "segment_id": 0,
      "comment": "该分段的教练点评"
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

▶ coach_comment（教练评语）必须包含三部分：
- strengths（优点）：字符串格式，2-3个具体优点用逗号或句号连接
- weaknesses（存在问题）：字符串格式，2-3个主要问题用逗号或句号连接
- summary（总结）：总体评价和训练方向
- ⚠️ 重要：strengths 和 weaknesses 必须是字符串，不要使用数组格式

▶ problems（训练问题）：
- 数组长度必须 = 3
- 按【对得分率 / 稳定性的影响】从高到低排序
- title：简短明确的问题标题
- description：详细描述该问题的具体表现和实战影响

▶ suggestions（训练建议）：
- 数组长度必须 = 3
- 与 problems 问题一一对应
- title：训练目标（要把动作练成什么状态）
- description：具体训练方法，包含：
  - 练习形式（多球/对练/空挥）
  - 次数/时间要求
  - 练习要点

▶ segment_feedback（分段点评）：
- segment_id 必须覆盖 0 到 {num_segments - 1}
- 每个 segment_id 恰好 1 条
- comment：该分段的教练点评

====================================================
【重要约束】

❌ 不要引用具体帧号、时间点
❌ 不要使用"可能、也许、大概"等模糊判断
❌ 不要做技术论文式描述
❌ 严禁使用任何表情符号或特殊图标（如 ✓、⚠、🎯 等）
❌ 输出必须是完整的句子，不要使用列表格式
❌ 不要在文本中使用引号包围字符串

⚠️ 如果信息不足，必须直接说明：
"从当前画面信息无法判断"，并给出补拍建议，例如：
- 建议机位（侧后方 45° / 正侧面）
- 建议覆盖阶段（准备 → 引拍 → 击球 → 还原）
- 建议拍摄条件（≥60fps，画面稳定）

====================================================
【文本格式要求】

1. 所有文本必须使用完整句子表达
2. 禁止使用列表格式（如 "1. xxx 2. xxx"）
3. 禁止使用特殊符号装饰（如 -、*、• 等作为列表标记）
4. 禁止使用引号包围标题或短语
5. 文本应该像教练口述一样自然流畅

====================================================
【最终输出要求】

1️⃣ 只输出【有效 JSON】
2️⃣ 全部使用【简体中文】
3️⃣ 语气像真实教练：直接、明确、可执行
4️⃣ 不要输出任何解释、说明或 Markdown
5️⃣ coach_comment.strengths 和 coach_comment.weaknesses 必须是字符串，不要用数组

⚠️ 格式检查清单：
- coach_comment.strengths 是字符串（如："站位稳定，挥拍顺畅"）
- coach_comment.weaknesses 是字符串（如："击球点偏后，还原较慢"）
- problems 是数组（3个元素）
- suggestions 是数组（3个元素）

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

    # 创建教练评语
    coach_comment = CoachComment(
        strengths="动作基础扎实，挥拍轨迹顺畅，击球点相对稳定。还原意识较好，能够保持基本的准备姿势。",
        weaknesses="击球后还原速度偏慢，导致连续相持中容易错过最佳击球时机。重心控制不够稳定，身体起伏较大影响击球一致性。躯干带动发力不足，过度依赖手臂发力。",
        summary="整体动作水平中等偏上，但在稳定性和衔接能力上仍有提升空间。建议优先训练还原速度和重心控制，这将显著提升连续回合的稳定性。"
    )

    # 转换为新格式
    new_problems = []
    for p in problems:
        new_problems.append({
            "title": p["title"],
            "description": f"依据：{p['evidence']}\n影响：{p['impact']}"
        })

    new_suggestions = []
    for imp in improvements:
        drills_text = "\n".join(imp["drills"])
        checkpoints_text = "\n".join(imp["checkpoints"])
        new_suggestions.append({
            "title": imp["title"],
            "description": f"{drills_text}\n\n检查点：\n{checkpoints_text}\n\n{imp['evidence']}"
        })

    return AnalysisReport(
        coach_comment=coach_comment,
        score=65,
        problems=new_problems[:3],
        suggestions=new_suggestions[:3],
        segment_feedback=segment_feedback,
    )


# =============================================================================
# JSON 解析（兜底：从输出中提取第一个 JSON 对象）
# =============================================================================


def _extract_json_by_brace_counting(text: str) -> str | None:
    """通过大括号计数提取完整的 JSON 对象

    这比简单的正则表达式更可靠，可以正确处理嵌套对象
    """
    first_brace = text.find("{")
    if first_brace == -1:
        return None

    brace_count = 0
    in_string = False
    escape_next = False

    for i, char in enumerate(text[first_brace:], start=first_brace):
        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if not in_string:
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    # 找到匹配的闭合大括号
                    return text[first_brace : i + 1]

    return None


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """解析 LLM 返回的 JSON，具有强容错能力

    解析策略：
    1. 尝试直接解析
    2. 尝试从 markdown 代码块中提取
    3. 使用大括号计数法提取
    4. 清理常见问题字符后重试
    """
    s = (raw or "").strip()
    if not s:
        raise OutputParsingError("LLM response is empty.")

    # 记录原始响应用于调试（截断过长的内容）
    debug_preview = s[:500] if len(s) > 500 else s
    logger.debug(f"[JSON Parse] 原始响应预览: {debug_preview}...")

    # 策略 1: 尝试直接解析
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 策略 2: 尝试从 markdown 代码块中提取
    if "```" in s:
        # 尝试 ```json ... ```
        m = re.search(r"```json\s*\n(.*?)\n```", s, flags=re.DOTALL | re.IGNORECASE)
        if not m:
            # 尝试 ``` ... ```
            m = re.search(r"```\s*\n(.*?)\n```", s, flags=re.DOTALL)

        if m:
            extracted = m.group(1).strip()
            try:
                obj = json.loads(extracted)
                if isinstance(obj, dict):
                    logger.debug("[JSON Parse] 从 markdown 代码块提取成功")
                    return obj
            except json.JSONDecodeError:
                pass

    # 策略 3: 使用大括号计数法提取（最可靠）
    extracted = _extract_json_by_brace_counting(s)
    if extracted:
        try:
            obj = json.loads(extracted)
            if isinstance(obj, dict):
                logger.debug("[JSON Parse] 使用大括号计数法提取成功")
                return obj
        except json.JSONDecodeError as e:
            logger.debug(f"[JSON Parse] 大括号计数法提取后仍失败: {e}")

    # 策略 4: 清理常见问题后重试
    # 移除可能导致问题的控制字符
    cleaned = s
    # 移除 BOM
    cleaned = cleaned.replace("\ufeff", "")
    # 移除其他控制字符（保留换行和制表符）
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)

    if cleaned != s:
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict):
                logger.debug("[JSON Parse] 清理控制字符后解析成功")
                return obj
        except json.JSONDecodeError:
            pass

    # 所有策略都失败，抛出详细错误
    # 截取原始响应的一部分用于错误信息
    error_context = s[:200] if len(s) > 200 else s
    raise OutputParsingError(
        f"LLM response was not valid JSON. "
        f"Tried 4 parsing strategies. "
        f"Response preview: {error_context}..."
    )


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
    """文本分析入口：frames_summary + features_summary -> JSON 报告

    如果 mode 是 MOCK，抛出错误而不是返回 mock 数据
    """
    if mode == AGENT_MODE_MOCK:
        raise AgentError(
            "Mock 模式已禁用。请配置 ZHIPU_API_KEY 或 DEEPSEEK_API_KEY 环境变量 "
            "以使用真实的 AI 分析功能。"
        )

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
    """分析视频并返回报告

    如果 LLM 返回无效 JSON 或调用失败，直接抛出错误而不降级到 mock
    """
    return analyze_video(frames_summary, features_summary, num_segments, mode, target_player_config)


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

    如果 mode 是 MOCK，抛出错误而不是返回 mock 数据
    """
    if mode == AGENT_MODE_MOCK:
        raise AgentError(
            "Mock 模式已禁用。请配置 ZHIPU_API_KEY 或 DEEPSEEK_API_KEY 环境变量 "
            "以使用真实的 AI 分析功能。"
        )

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
    """分析图片并返回报告

    如果 LLM 返回无效 JSON 或调用失败，直接抛出错误而不降级到 mock
    """
    return analyze_images(frames_summary, num_segments, image_paths, mode, target_player_config)
