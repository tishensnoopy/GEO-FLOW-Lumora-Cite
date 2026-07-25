# index-monitor/tests/unit/test_pdf_export.py
"""PdfExportService 测试。

验证目标（设计文档第 12.1 节 + project_memory 硬约束）：
1. generate_pdf 返回文件路径，文件存在
2. PDF 文件非空（>1KB）
3. PDF 含水印文字（用 pypdf 提取文本验证）
4. 图表不跨页（检查 HTML 模板含 page-break-inside:avoid）
5. 生僻字渲染（龘靐龗，需 Noto CJK 字体）
"""
import os
import pytest

from app.services.pdf_export_service import PdfExportService


@pytest.mark.asyncio
async def test_generate_pdf_creates_file(tmp_path):
    """generate_pdf 生成 PDF 文件。"""
    service = PdfExportService(output_dir=str(tmp_path))

    # 模拟数据（client_name 含生僻字龘靐龗，验证 Noto CJK 字体渲染）
    report_data = {
        "client_name": "测试客户龘靐龗公司",
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
                "status": "completed",
            }
        ],
        "charts": {
            "trend": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
            "pie": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
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


@pytest.mark.asyncio
async def test_pdf_contains_watermark_text(tmp_path):
    """用 pypdf 提取 PDF 文本，验证含水印文字 + 生僻字龘渲染。

    pypdf 对部分 CJK 字形会做归一化（如 客户→客⼾），但水印文字
    `知氪AI监测` 与生僻字 `龘` 经实现者验证可正确提取。
    """
    from pypdf import PdfReader

    service = PdfExportService(output_dir=str(tmp_path))

    report_data = {
        "client_name": "测试客户龘靐龗公司",
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
                "status": "completed",
            }
        ],
        "charts": {
            "trend": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
            "pie": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
        },
    }

    file_path = await service.generate_pdf(report_data, filename="test_watermark.pdf")

    # 用 pypdf 提取全部文本
    reader = PdfReader(file_path)
    extracted_text = ""
    for page in reader.pages:
        extracted_text += page.extract_text() or ""

    # 断言水印文字
    assert "知氪AI监测" in extracted_text, f"PDF 文本缺水印文字 '知氪AI监测'；提取到：{extracted_text!r}"
    # 断言生僻字 龘 渲染（pypdf 归一化可能影响个别字，龘 经验证可提取）
    assert "龘" in extracted_text, f"PDF 文本缺生僻字 '龘'；提取到：{extracted_text!r}"
