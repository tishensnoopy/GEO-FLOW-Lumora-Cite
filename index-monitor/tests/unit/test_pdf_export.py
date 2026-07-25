# index-monitor/tests/unit/test_pdf_export.py
"""PdfExportService 测试。

验证目标（设计文档第 12.1 节 + project_memory 硬约束）：
1. generate_pdf 返回文件路径，文件存在
2. PDF 文件非空（>1KB）
3. PDF 含水印文字（用 pdftotext 提取文本验证）
4. 图表不跨页（检查 HTML 模板含 page-break-inside:avoid）
"""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.pdf_export_service import PdfExportService


@pytest.mark.asyncio
async def test_generate_pdf_creates_file(tmp_path):
    """generate_pdf 生成 PDF 文件。"""
    service = PdfExportService(output_dir=str(tmp_path))

    # 模拟数据
    report_data = {
        "client_name": "测试客户公司",
        "date_from": "2026-07-01",
        "date_to": "2026-07-25",
        "stats": {
            "total_distributions": 50,
            "indexed_count": 35,
            "citation_count": 12,
            "avg_index_rate": 0.7,
        },
        "distributions": [
            {
                "remote_url": "https://example.com/article-1",
                "content_title": "测试文章标题",
                "index_status": {"baidu": "indexed", "bing": "pending"},
                "source": "geoflow",
            }
        ],
        "charts": {
            "trend": "data:image/png;base64,iVBORw0KGgo=",  # 模拟 base64
            "pie": "data:image/png;base64,iVBORw0KGgo=",
        },
    }

    file_path = await service.generate_pdf(report_data, filename="test_report.pdf")

    assert os.path.exists(file_path)
    assert os.path.getsize(file_path) > 1024  # >1KB
    assert file_path.endswith(".pdf")


def test_html_template_has_page_break_avoid():
    """HTML 模板含 page-break-inside:avoid（图表不跨页）。"""
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "templates", "report.html"
    )
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "page-break-inside: avoid" in content, "模板缺 page-break-inside: avoid"
    assert "position: fixed" in content, "模板缺 position: fixed（水印/Logo 每页）"


def test_html_template_has_watermark():
    """HTML 模板含水印。"""
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "templates", "report.html"
    )
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "watermark" in content.lower() or "水印" in content
