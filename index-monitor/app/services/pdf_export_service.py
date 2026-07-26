# index-monitor/app/services/pdf_export_service.py
"""PDF 报告导出服务——Playwright headless Chromium 渲染。

设计文档第 12.1 节 + project_memory 硬约束：
- 中文字体 Noto CJK（防掉字）
- 图表不跨页（page-break-inside: avoid）
- 水印 + Logo 每页（position: fixed）
- 图表用 base64 内联（不依赖文件路径）
"""
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright


class PdfExportService:
    def __init__(self, output_dir: str = "/app/exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Jinja2 模板环境
        template_dir = Path(__file__).parent.parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html"]),
        )

    async def generate_pdf(
        self,
        report_data: dict,
        filename: str | None = None,
    ) -> str:
        """生成 PDF 报告。

        Parameters
        ----------
        report_data : dict
            报告数据（client_name/stats/distributions/charts 等）。
        filename : str | None
            输出文件名。None = 自动生成。

        Returns
        -------
        str
            PDF 文件绝对路径。
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{timestamp}.pdf"

        file_path = str(self.output_dir / filename)

        # 渲染 HTML
        template = self.env.get_template("report.html")
        # Logo base64（SVG 文字 Logo：知氪AI）
        logo_base64 = "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMDAiIGhlaWdodD0iMzYiIHZpZXdCb3g9IjAgMCAxMDAgMzYiPgo8cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjM2IiByeD0iNiIgZmlsbD0iIzJjM2U1MCIvPgo8dGV4dCB4PSI1MCIgeT0iMjQiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXNpemU9IjE2IiBmb250LXdlaWdodD0iYm9sZCIgZmlsbD0id2hpdGUiIHRleHQtYW5jaG9yPSJtaWRkbGUiPuifpeawqkFJPC90ZXh0Pgo8L3N2Zz4="
        html_content = template.render(
            client_name=report_data.get("client_name", ""),
            date_from=report_data.get("date_from", ""),
            date_to=report_data.get("date_to", ""),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            stats=report_data.get("stats", {}),
            distributions=report_data.get("distributions", []),
            charts=report_data.get("charts", {}),
            citation_details=report_data.get("citation_details", []),
            logo_base64=logo_base64,
        )

        # Playwright 渲染 PDF
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--font-render-hinting=none"],
            )
            page = await browser.new_page()
            await page.set_content(html_content, wait_until="networkidle")
            await page.pdf(
                path=file_path,
                format="A4",
                print_background=True,
                margin={"top": "20mm", "bottom": "25mm", "left": "15mm", "right": "15mm"},
                display_header_footer=True,
                header_template="<div></div>",
                footer_template='<div style="font-size:10px;color:#999;text-align:center;width:100%;">知氪AI全链路监测平台 | 第 <span class="pageNumber"></span> 页</div>',
            )
            await browser.close()

        return file_path
