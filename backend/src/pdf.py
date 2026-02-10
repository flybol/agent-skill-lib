"""
PDF 报告生成模块
为乒乓球技术分析结果生成专业的 PDF 报告
"""

import os
from io import BytesIO
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping

# 颜色定义
COLOR_PRIMARY = HexColor("#2563EB")  # 蓝色
COLOR_SECONDARY = HexColor("#10B981")  # 绿色
COLOR_WARNING = HexColor("#F59E0B")  # 橙色
COLOR_DANGER = HexColor("#EF4444")  # 红色
COLOR_BG_LIGHT = HexColor("#F3F4F6")  # 浅灰
COLOR_TEXT = HexColor("#1F2937")  # 深灰
COLOR_TEXT_LIGHT = HexColor("#6B7280")  # 浅灰文本


class PDFReportGenerator:
    """PDF 报告生成器"""

    def __init__(self, output_path: Optional[str] = None):
        """
        初始化 PDF 生成器

        Args:
            output_path: 输出文件路径，如果为 None 则返回字节流
        """
        self.output_path = output_path
        self.buffer = BytesIO() if output_path is None else None
        self.story = []

    def _register_fonts(self):
        """注册中文字体"""
        # 尝试注册常见的中文字体（按优先级排序）
        font_paths = [
            # Windows - 优先使用微软雅黑
            "C:/Windows/Fonts/msyh.ttc",  # 微软雅黑
            "C:/Windows/Fonts/msyhbd.ttc",  # 微软雅黑粗体
            "C:/Windows/Fonts/simsun.ttc",  # 宋体
            "C:/Windows/Fonts/simhei.ttf",  # 黑体
            "C:/Windows/Fonts/simkai.ttf",  # 楷体
            # Linux - 文泉驿字体
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            # macOS - 苹方字体
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/STHeiti.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
        ]

        self.has_chinese_font = False
        self.chinese_font_name = "Helvetica"  # 默认字体

        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    # 注册中文字体
                    pdfmetrics.registerFont(TTFont("ChineseFont", font_path))
                    addMapping("ChineseFont", 0, 0, "ChineseFont")
                    self.has_chinese_font = True
                    self.chinese_font_name = "ChineseFont"
                    print(f"[PDF] 成功注册中文字体: {font_path}")
                    break
                except Exception as e:
                    print(f"[PDF] 注册字体失败 {font_path}: {e}")
                    continue

        if not self.has_chinese_font:
            print("[PDF] 警告: 未找到中文字体，中文可能显示为乱码")

    def _get_styles(self):
        """获取文档样式"""
        styles = getSampleStyleSheet()

        # 使用已注册的字体名称
        font_name = self.chinese_font_name

        # 自定义样式
        styles.add(
            ParagraphStyle(
                name="CustomTitle",
                parent=styles["Title"],
                fontName=font_name,
                fontSize=24,
                textColor=COLOR_PRIMARY,
                spaceAfter=12 * mm,
                alignment=TA_LEFT,
            )
        )

        styles.add(
            ParagraphStyle(
                name="CustomHeading1",
                parent=styles["Heading1"],
                fontName=font_name,
                fontSize=18,
                textColor=COLOR_PRIMARY,
                spaceAfter=8 * mm,
                spaceBefore=12 * mm,
            )
        )

        styles.add(
            ParagraphStyle(
                name="CustomHeading2",
                parent=styles["Heading2"],
                fontName=font_name,
                fontSize=14,
                textColor=COLOR_TEXT,
                spaceAfter=6 * mm,
                spaceBefore=8 * mm,
            )
        )

        styles.add(
            ParagraphStyle(
                name="CustomBody",
                parent=styles["BodyText"],
                fontName=font_name,
                fontSize=11,
                textColor=COLOR_TEXT,
                spaceAfter=4 * mm,
                leading=16,
            )
        )

        styles.add(
            ParagraphStyle(
                name="CustomSmall",
                parent=styles["BodyText"],
                fontName=font_name,
                fontSize=9,
                textColor=COLOR_TEXT_LIGHT,
                spaceAfter=2 * mm,
            )
        )

        return styles

    def _create_header(self, result: Dict[str, Any]):
        """创建报告头部"""
        styles = self._get_styles()

        # 标题
        if self.has_chinese_font:
            title = "乒乓球技术分析报告"
        else:
            title = "Table Tennis Analysis Report"

        self.story.append(Paragraph(title, styles["CustomTitle"]))
        self.story.append(Spacer(1, 8 * mm))

    def _create_score_section(self, result: Dict[str, Any]):
        """创建评分部分"""
        overall_score = result.get("overall_score")

        if overall_score is None:
            return

        styles = self._get_styles()

        # 简化评分显示：综合评分：65分
        if self.has_chinese_font:
            score_text = f"综合评分：{overall_score}分"
        else:
            score_text = f"Overall Score: {overall_score}"

        self.story.append(Paragraph(score_text, styles["CustomBody"]))
        self.story.append(Spacer(1, 6 * mm))

    def _create_summary_section(self, result: Dict[str, Any]):
        """创建概要部分（支持新格式 coach_comment 和旧格式 summary）"""
        styles = self._get_styles()

        # 优先使用新格式 coach_comment
        coach_comment = result.get("coach_comment", {})
        summary = result.get("summary", {})

        # 确定使用哪种格式
        if coach_comment and (coach_comment.get("strengths") or coach_comment.get("weaknesses") or coach_comment.get("summary")):
            # 新格式：使用 coach_comment
            # 标题
            if self.has_chinese_font:
                title = "教练评语"
            else:
                title = "Coach's Comments"

            self.story.append(Paragraph(title, styles["CustomHeading1"]))

            # 优点
            strengths = coach_comment.get("strengths", "")
            if strengths:
                if self.has_chinese_font:
                    self.story.append(Paragraph("<b>优点:</b>", styles["CustomHeading2"]))
                self.story.append(Paragraph(str(strengths), styles["CustomBody"]))
                self.story.append(Spacer(1, 4 * mm))

            # 存在问题
            weaknesses = coach_comment.get("weaknesses", "")
            if weaknesses:
                if self.has_chinese_font:
                    self.story.append(Paragraph("<b>存在问题:</b>", styles["CustomHeading2"]))
                self.story.append(Paragraph(str(weaknesses), styles["CustomBody"]))
                self.story.append(Spacer(1, 4 * mm))

            # 总结
            summary_text = coach_comment.get("summary", "")
            if summary_text:
                if self.has_chinese_font:
                    self.story.append(Paragraph("<b>总结:</b>", styles["CustomHeading2"]))
                self.story.append(Paragraph(str(summary_text), styles["CustomBody"]))
                self.story.append(Spacer(1, 4 * mm))

        elif summary:
            # 旧格式：使用 summary
            if self.has_chinese_font:
                title = "总体评价"
            else:
                title = "Summary"

            self.story.append(Paragraph(title, styles["CustomHeading1"]))

            # 概要内容
            overview = summary.get("overview", "")
            if overview:
                self.story.append(Paragraph(overview, styles["CustomBody"]))
                self.story.append(Spacer(1, 6 * mm))

            # 优点列表
            strengths = summary.get("strengths", [])
            if strengths:
                if self.has_chinese_font:
                    self.story.append(Paragraph("<b>优点:</b>", styles["CustomHeading2"]))
                for strength in strengths:
                    self.story.append(Paragraph(f"• {strength}", styles["CustomBody"]))
                self.story.append(Spacer(1, 4 * mm))

            # 问题列表
            weaknesses = summary.get("weaknesses", [])
            if weaknesses:
                if self.has_chinese_font:
                    self.story.append(
                        Paragraph("<b>需要改进:</b>", styles["CustomHeading2"])
                    )
                for weakness in weaknesses:
                    text = (
                        weakness if isinstance(weakness, str) else weakness.get("title", "")
                    )
                    desc = (
                        weakness
                        if isinstance(weakness, str)
                        else weakness.get("description", "")
                    )
                    self.story.append(Paragraph(f"• {text}", styles["CustomBody"]))
                    if desc:
                        self.story.append(
                            Paragraph(f"  <i>{desc}</i>", styles["CustomSmall"])
                        )
                self.story.append(Spacer(1, 4 * mm))

    def _create_problems_section(self, result: Dict[str, Any]):
        """创建训练问题部分（新格式）"""
        problems = result.get("problems", [])

        if not problems:
            return

        styles = self._get_styles()

        # 标题
        if self.has_chinese_font:
            title = "训练问题"
        else:
            title = "Training Problems"

        self.story.append(Paragraph(title, styles["CustomHeading1"]))

        # 问题列表
        for i, problem in enumerate(problems, 1):
            title_text = problem.get("title", f"问题 {i}")
            description = problem.get("description", "")

            # 问题内容
            content = f"<b>{i}. {title_text}</b>"
            if description:
                content += f"<br/>{description}"

            self.story.append(Paragraph(content, styles["CustomBody"]))
            self.story.append(Spacer(1, 3 * mm))

    def _create_suggestions_section(self, result: Dict[str, Any]):
        """创建建议部分"""
        suggestions = result.get("suggestions", [])

        if not suggestions:
            return

        styles = self._get_styles()

        # 标题
        if self.has_chinese_font:
            title = "改进建议"
        else:
            title = "Suggestions"

        self.story.append(Paragraph(title, styles["CustomHeading1"]))

        # 建议列表
        for i, suggestion in enumerate(suggestions, 1):
            title_text = suggestion.get("title", f"建议 {i}")
            description = suggestion.get("description", "")
            priority = suggestion.get("priority", "")

            # 根据优先级选择颜色
            priority_colors = {
                "high": COLOR_DANGER,
                "medium": COLOR_WARNING,
                "low": COLOR_SECONDARY,
            }
            priority_color = priority_colors.get(priority, COLOR_BG_LIGHT)

            # 建议内容
            content = f"<b>{i}. {title_text}</b>"
            if description:
                content += f"<br/>{description}"

            self.story.append(Paragraph(content, styles["CustomBody"]))
            self.story.append(Spacer(1, 3 * mm))

    def _create_footer(self):
        """创建页脚"""
        styles = self._get_styles()

        # 添加分隔线（使用 Spacer 留出空间，而不是强制分页）
        self.story.append(Spacer(1, 20 * mm))

        # 落款信息表格
        footer_data = [
            ["乒乓数字教练 v1.0"],
            ["AI Pingpong Coach System"],
            [""],
            [f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
            ["本报告由 AI 教练系统自动生成，仅供参考"],
        ]

        footer_table = Table(footer_data, colWidths=[120 * mm])
        footer_table.setStyle(
            TableStyle(
                [
                    (
                        "FONTNAME",
                        (0, 0),
                        (-1, -1),
                        self.chinese_font_name,
                    ),
                    ("FONTSIZE", (0, 0), (0, 0), 16),
                    ("FONTSIZE", (0, 1), (-1, -1), 10),
                    ("TEXTCOLOR", (0, 0), (-1, -1), COLOR_TEXT_LIGHT),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
                ]
            )
        )

        # 居中显示落款
        footer_wrapper = Table([[footer_table]], colWidths=[170 * mm])
        footer_wrapper.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ]
            )
        )

        self.story.append(footer_wrapper)

    def generate(self, result: Dict[str, Any], runs_dir: Path) -> bytes:
        """
        生成 PDF 报告

        Args:
            result: 分析结果数据
            runs_dir: 运行数据目录（用于查找关键帧图片）

        Returns:
            PDF 字节数据（如果 output_path 为 None）
        """
        # 重置 story 和 buffer（防止重复调用时累积数据）
        self.story = []
        if self.output_path is None:
            self.buffer = BytesIO()

        # 注册字体
        self._register_fonts()

        # 创建文档
        if self.output_path:
            doc = SimpleDocTemplate(
                self.output_path,
                pagesize=A4,
                leftMargin=20 * mm,
                rightMargin=20 * mm,
                topMargin=20 * mm,
                bottomMargin=15 * mm,
            )
        else:
            doc = SimpleDocTemplate(
                self.buffer,
                pagesize=A4,
                leftMargin=20 * mm,
                rightMargin=20 * mm,
                topMargin=20 * mm,
                bottomMargin=15 * mm,
            )

        # 构建内容
        self._create_header(result)
        self._create_score_section(result)
        self._create_summary_section(result)
        self._create_problems_section(result)  # 训练问题（新格式）
        self._create_suggestions_section(result)  # 训练建议
        self._create_footer()

        # 生成 PDF
        doc.build(self.story)

        # 返回结果
        if self.output_path:
            with open(self.output_path, "rb") as f:
                return f.read()
        else:
            return self.buffer.getvalue()


def generate_pdf_report(
    result: Dict[str, Any],
    runs_dir: Path,
    output_path: Optional[str] = None,
) -> bytes:
    """
    生成 PDF 报告的便捷函数

    Args:
        result: 分析结果数据
        runs_dir: 运行数据目录
        output_path: 输出文件路径（可选）

    Returns:
        PDF 字节数据
    """
    generator = PDFReportGenerator(output_path)
    return generator.generate(result, runs_dir)
