"""
LLM input construction + output parsing for CoachAgent.

Supports mock and real modes:
- Text: DeepSeek (deepseek-chat)
- Vision: Zhipu GLM-4.6V-Flash
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import random
import time
from requests import Response

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_deepseek import ChatDeepSeek

from constants import AGENT_MODE_MOCK, AGENT_MODE_REAL
from errors import AgentError, AgentInvocationError, OutputParsingError

logger = logging.getLogger(__name__)

ZHIPU_CHAT_COMPLETIONS_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


# ============================================================================
# Data Classes
# ============================================================================


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
    evidence: str = ""  # ✅ 允许 LLM 返回 evidence（修复崩溃点）


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
        """Parse dict -> AnalysisReport with field filtering to avoid crash on extra keys."""

        def _pick(d: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
            return {k: d.get(k) for k in allowed if k in d}

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


# ============================================================================
# Prompt Templates
# ============================================================================

SYSTEM_PROMPT = """
你是一名专业乒乓球教练，长期指导初学者与业余选手，擅长用清晰、可执行的方式指出问题并给出训练方法。

你将分析的是【一段训练视频片段】（可能是一个回合或一个失误片段），输入会提供：
- 关键帧摘要（按时间顺序/按分段聚合，含 Frame <数字> at <秒>s）
- 特征摘要（动作强度、稳定性、重心波动、躯干倾斜、手腕波动等统计）

你的任务：像真实教练一样输出一份【训练分析报告】，帮助学员“看清问题”和“知道怎么练”。

硬性输出要求（必须全部遵守）：
1) 输出必须是【有效 JSON】且【只输出 JSON】（禁止任何解释文字、前后缀、Markdown、代码块标记）。
2) 所有内容必须使用【简体中文】。
3) 风格要求：教练口吻、专业但不堆砌术语、建议必须可练习可执行。
4) problems 必须恰好 3 条；improvements 必须恰好 3 条；segment_feedback 必须覆盖每个分段。
5) evidence 与 segment_feedback.comment 必须尽量引用输入中的关键帧证据，若输入不足，必须写明“从当前帧摘要无法确定”，并给出补充拍摄建议（例如机位、角度、帧率）。
""".strip()


def build_user_prompt(
    frames_summary: str, features_summary: str, num_segments: int
) -> str:
    """Build strict JSON prompt for both text and vision branches."""
    if num_segments <= 0:
        num_segments = 1

    def _clip(text: str, max_chars: int) -> str:
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 20].rstrip() + "\n...(内容过长已截断)"

    frames_summary = _clip(frames_summary, 6000)
    features_summary = _clip(features_summary, 6000)

    required_json_schema = f"""
你必须输出【严格 JSON】对象（只输出 JSON，不要输出任何解释、前后缀、代码块标记）。

JSON 必须包含以下字段（字段名固定）：
{{
  "summary": "总体评价（2-3句，简体中文）",
  "problems": [
    {{"title": "问题标题", "evidence": "观察证据（引用帧/时间戳/特征）", "impact": "影响/后果"}}
  ],
  "improvements": [
    {{"title": "改进标题", "drills": ["训练方法1", "训练方法2"], "checkpoints": ["检查点1", "检查点2"], "evidence": "为什么建议这么练（引用帧/时间戳/特征）"}}
  ],
  "segment_feedback": [
    {{"segment_id": 0, "comment": "该分段的教练点评（简体中文，具体可执行）"}}
  ]
}}

硬性约束：
- 必须使用【简体中文】。
- problems 数组长度必须恰好为 3。
- improvements 数组长度必须恰好为 3。
- 每条 improvements 必须至少包含 2 条 drills 与 2 条 checkpoints（不足也要补齐）。
- segment_feedback 必须覆盖每个分段：segment_id 从 0 到 {num_segments - 1}，每段恰好 1 条。

证据引用规则（非常重要）：
1) ✅ 每条 segment_feedback.comment 必须至少引用 1 个“本段”的关键帧证据，格式必须严格包含：Frame <数字> at <数字>s
例如：Frame 120 at 4.10s
说明：你必须从【输入 1：关键帧摘要（按分段聚合）】中选取属于该 segment_id 的帧来引用，禁止引用其它分段的帧。

2) ✅ problems 的 evidence 必须至少引用 2 个不同分段的帧（至少 2 个不同 segment_id），用来证明这是“跨段重复出现”的主要问题。
例子（示意）：Segment 1: Frame 30 at 2.10s；Segment 4: Frame 120 at 7.95s
- 如果确实只有一个分段有明显证据，也必须写明：为何其它段无法判断（例如该段无可用帧/角度遮挡）。

3) ✅ improvements 的 evidence 必须引用 1~2 个 Frame 或关键特征数字，解释“为什么要练这个”（避免空泛口号）。

4) 不要编造无法从输入推出的细节；信息不足时写“从当前帧摘要无法确定”，并给出补拍建议（机位/角度/帧率）。

校验提醒（务必遵守）：
- 如果 segment_feedback.comment 中没有出现形如 “Frame 12 at 0.40s” 的引用，则视为不合格输出。
- 每个 segment_id 只能引用该段下面列出的 Frame，不允许跨段引用。
""".strip()

    prompt = f"""
你将扮演“乒乓球训练教练”。请根据下列输入信息，输出结构化的训练分析报告。

【输入 1：关键帧摘要（按分段聚合）】
{frames_summary}

【输入 2：特征摘要（分段/统计信息）】
{features_summary}

【分段数量】
视频已划分为 {num_segments} 段，请对每段分别给出点评（segment_id 从 0 到 {num_segments - 1}）。

{required_json_schema}
""".strip()

    return prompt


# ============================================================================
# Mock Agent
# ============================================================================


def get_mock_report(num_segments: int = 8) -> AnalysisReport:
    """稳定的中文 Mock 报告（用于 UI/流程调试）。"""
    n = max(1, int(num_segments))

    problems = [
        {
            "title": "击球后还原不及时",
            "evidence": "从多帧节奏看，击球后手臂与重心停留时间偏长，下一拍启动略慢。",
            "impact": "会导致连续回合中衔接变慢，来球稍快时容易被压制或出现二次失误。",
        },
        {
            "title": "重心前后转移过早或过大",
            "evidence": "在准备—出手阶段的时间段内，身体重心移动幅度偏大，稳定性不足。",
            "impact": "影响击球点稳定与发力顺序，容易出现“抢点/追球”，导致落点和旋转不稳定。",
        },
        {
            "title": "上肢发力占比过高，躯干参与不足",
            "evidence": "从分段表现来看，出手主要依赖手臂摆动，躯干带动和髋肩联动不明显。",
            "impact": "力量上限受限且一致性差，长时间训练更易疲劳，也更难控制线路与质量。",
        },
    ]

    improvements = [
        {
            "title": "击球后快速还原训练（小动作、高频衔接）",
            "drills": [
                "对墙/多球：每次击球后立刻把拍面回到准备位，连续 30 球为一组，做 3 组。",
                "二点跑位（近台）：正手位—中路交替，小幅移动，强调还原速度与脚下节奏。",
            ],
            "checkpoints": [
                "击球后 0.3~0.5 秒内回到准备位（拍在身前、肘部自然下垂）。",
                "重心回到双脚之间，不停在前脚或后脚。",
                "下一拍启动前拍形稳定，不出现大幅甩臂。",
            ],
            "evidence": "该类问题会在多段中反复出现，需用节奏与还原训练建立稳定动作链。",
        },
        {
            "title": "重心控制与步法节奏训练（稳住下盘）",
            "drills": [
                "“半蹲准备位”定点拉球：保持膝微屈、髋稳定，连续 20 球，做 3 组。",
                "节拍器步法：用 60~80 BPM 节拍做小碎步，击球点前后不跳、不扑。",
            ],
            "checkpoints": [
                "准备位时头部高度波动小（不明显起跳）。",
                "移动以“先到位后出手”为原则，身体不前冲抢球。",
                "击球瞬间脚下有支撑感，动作收敛不散。",
            ],
            "evidence": "重心稳定是击球点与拍型稳定的前提。",
        },
        {
            "title": "躯干带动发力训练（髋—肩—臂顺序）",
            "drills": [
                "徒手分解：先转髋、再带肩、最后出手（慢动作 10 次 × 3 组）。",
                "轻球拉冲：先用躯干带动，手臂只做“传导”，每组 20 球 × 3 组。",
            ],
            "checkpoints": [
                "启动顺序：髋先动 → 肩跟上 → 手臂最后加速。",
                "击球后躯干仍保持稳定，不出现大幅耸肩或侧倾。",
                "发力感觉来自“转体”，不是单纯甩手。",
            ],
            "evidence": "躯干参与能提高一致性与力量上限。",
        },
    ]

    segment_feedback = [
        {
            "segment_id": i,
            "comment": f"分段 {i}：整体节奏尚可，注意准备位稳定、击球后及时还原到身前（示例：Frame 0 at 0.00s）。",
        }
        for i in range(n)
    ]

    return AnalysisReport(
        summary=(
            "整体动作基础不错，但在连续回合的衔接与稳定性上仍有提升空间。"
            "主要问题集中在击球后还原偏慢、重心波动较大以及躯干带动不足。"
        ),
        problems=problems,
        improvements=improvements,
        segment_feedback=segment_feedback,
    )


# ============================================================================
# Parsers / Callers
# ============================================================================


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """Extract the first JSON object from raw model output and parse."""
    s = (raw or "").strip()
    if not s:
        raise OutputParsingError("LLM response is empty.")

    # fenced code block
    if "```" in s:
        m = re.search(r"```json\s*(\{.*?\})\s*```", s, flags=re.DOTALL | re.IGNORECASE)
        if m:
            s = m.group(1).strip()
        else:
            m = re.search(r"```\s*(\{.*?\})\s*```", s, flags=re.DOTALL)
            if m:
                s = m.group(1).strip()

    # slice { ... }
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


def call_deepseek_llm(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise AgentInvocationError("DEEPSEEK_API_KEY environment variable not set.")

    llm = ChatDeepSeek(
        model="deepseek-chat",
        temperature=0.0,
        api_key=api_key,
    )

    prompt_tpl = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", "{input}")]
    )
    chain = prompt_tpl | llm | StrOutputParser()
    return chain.invoke({"input": prompt})


def _file_to_data_url(p: Path) -> str:
    b = p.read_bytes()
    b64 = base64.b64encode(b).decode("utf-8")
    # 抽帧一般是 png/jpg；这里统一用 png 的 data url（服务端通常可接受）
    return f"data:image/png;base64,{b64}"


def _post_with_retry(
    url: str, headers: dict[str, str], payload: dict[str, Any], *, timeout: int = 90
) -> Response:
    """
    对 429 / 5xx 做有限重试，优先读取 Retry-After。
    最小改动：只用于 GLM 这条链路，避免 UI 一抖就打爆限流。
    """
    max_attempts = 5
    base_sleep = 1.0

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)

            # 429: Too Many Requests
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After", "").strip()
                if retry_after.isdigit():
                    sleep_s = float(retry_after)
                else:
                    # 指数退避 + 抖动
                    sleep_s = base_sleep * (2 ** (attempt - 1)) + random.uniform(0, 0.5)

                logger.warning(
                    f"Zhipu 429 rate limited. attempt={attempt}/{max_attempts}, sleep={sleep_s:.2f}s"
                )
                time.sleep(sleep_s)
                continue

            # 5xx: 也做退避（服务端波动）
            if 500 <= resp.status_code < 600:
                sleep_s = base_sleep * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                logger.warning(
                    f"Zhipu {resp.status_code} server error. attempt={attempt}/{max_attempts}, sleep={sleep_s:.2f}s"
                )
                time.sleep(sleep_s)
                continue

            resp.raise_for_status()
            return resp

        except Exception as e:
            last_exc = e
            sleep_s = base_sleep * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(
                f"Zhipu request failed. attempt={attempt}/{max_attempts}, sleep={sleep_s:.2f}s, err={e}"
            )
            time.sleep(sleep_s)

    # 重试用尽
    if last_exc:
        raise last_exc
    raise RuntimeError("Zhipu request failed after retries.")


def call_glm4v_flash(prompt: str, image_paths: list[str]) -> str:
    api_key = os.environ.get("ZHIPU_API_KEY", "").strip()
    if not api_key:
        raise AgentInvocationError("ZHIPU_API_KEY environment variable not set.")

    contents: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for p in image_paths:
        if not p:
            continue
        pp = Path(p)
        if not pp.exists():
            continue
        contents.append(
            {"type": "image_url", "image_url": {"url": _file_to_data_url(pp)}}
        )

    payload = {
        "model": "glm-4.7-flash",
        "messages": [{"role": "user", "content": contents}],
        "tinking": "enabled",
        "max_tokens": 65536,
        "temperature": 1.0,  # JSON 稳定性优先
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    resp = _post_with_retry(ZHIPU_CHAT_COMPLETIONS_URL, headers, payload, timeout=90)
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ============================================================================
# Main Agent Interface
# ============================================================================


def analyze_video(
    frames_summary: str,
    features_summary: str,
    num_segments: int,
    mode: str = AGENT_MODE_REAL,
) -> AnalysisReport:
    """Text agent (DeepSeek)."""
    if mode == AGENT_MODE_MOCK:
        logger.info("Using mock agent mode (text)")
        return get_mock_report(num_segments)

    if mode != AGENT_MODE_REAL:
        raise AgentError(f"Unknown agent mode: {mode}")

    logger.info("Using real agent mode (text: deepseek)")
    prompt = build_user_prompt(frames_summary, features_summary, num_segments)
    raw = call_deepseek_llm(prompt)
    parsed = _parse_llm_json(raw)
    return AnalysisReport.from_dict(parsed)


def analyze_video_with_fallback(
    frames_summary: str,
    features_summary: str,
    num_segments: int,
    mode: str = AGENT_MODE_MOCK,
) -> AnalysisReport:
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
    mode: str = AGENT_MODE_MOCK,
) -> AnalysisReport:
    """Vision agent (GLM-4.6V-Flash)."""
    if mode == AGENT_MODE_MOCK:
        logger.info("Using mock agent mode (vision)")
        return get_mock_report(num_segments)

    if mode != AGENT_MODE_REAL:
        raise AgentError(f"Unknown agent mode: {mode}")

    logger.info("Using real agent mode (vision: glm-4.6v-flash)")
    features_summary = (
        "图像理解模式：请主要依据关键截图内容判断动作问题；"
        "如特征信息不足，请在 evidence 中说明“从当前帧摘要无法确定”，并给出补拍建议。"
    )
    prompt = build_user_prompt(frames_summary, features_summary, num_segments)
    raw = call_glm4v_flash(prompt, image_paths)
    parsed = _parse_llm_json(raw)
    return AnalysisReport.from_dict(parsed)


def analyze_images_with_fallback(
    frames_summary: str,
    num_segments: int,
    image_paths: list[str],
    mode: str = AGENT_MODE_MOCK,
) -> AnalysisReport:
    try:
        return analyze_images(frames_summary, num_segments, image_paths, mode)
    except AgentError as e:
        logger.warning(f"Vision agent failed, falling back to mock: {e}")
        return get_mock_report(num_segments)
    except Exception as e:
        logger.error(f"Unexpected error in vision agent: {e}")
        logger.warning("Falling back to mock due to unexpected error.")
        return get_mock_report(num_segments)
