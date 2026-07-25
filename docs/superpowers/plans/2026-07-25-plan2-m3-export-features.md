# M3：监测结果导出 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。

**目标：** 实现 PDF 报告导出（Playwright + Chromium）和 Excel 明细导出（openpyxl 4 sheet），含导出任务后台处理与下载端点。

**架构：** `PdfExportService` 用 Playwright headless Chromium 渲染 HTML 模板 → PDF；`ExcelExportService` 用 openpyxl 生成 4 sheet 工作簿；`ExportService` 编排任务状态机（pending→processing→completed/failed）；导出文件存 `/app/exports/`。

**前置条件：**
- M1 + M2 已完成（DistributionQueryService 可查数据）
- `playwright` + `openpyxl` 已在 requirements.txt
- Playwright Chromium 已安装：`playwright install chromium`
- 中文字体已安装：`fonts-noto-cjk`（PDF 渲染必需）

**关联设计文档：** [第 12 节 导出设计](../specs/2026-07-25-geoflow-monitor-db-sync-design.md#12-导出设计)

**硬约束（project_memory）：**
- PDF 图表/统计卡片不跨页切割（`page-break-inside: avoid`）
- 水印 + Logo 每页显示（CSS `position: fixed`）
- 中文不掉字（含生僻字龘靐龗，需 Noto CJK 字体）
- 图表用 ECharts 截图 base64 内联

---

## 任务 1：PdfExportService + PDF 模板

**文件：**
- 创建：`index-monitor/app/services/pdf_export_service.py`
- 创建：`index-monitor/app/templates/report.html`
- 测试：`index-monitor/tests/unit/test_pdf_export.py`

- [ ] **步骤 1：编写失败的测试**

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_pdf_export.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'app.services.pdf_export_service'`

- [ ] **步骤 3：编写 HTML 模板**

```html
<!-- index-monitor/app/templates/report.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>监测报告 - {{ client_name }}</title>
    <style>
        @page {
            size: A4;
            margin: 20mm 15mm 25mm 15mm;
        }
        body {
            font-family: "Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
            font-size: 12px;
            color: #333;
            line-height: 1.6;
        }
        /* 水印 + Logo 每页显示 */
        .watermark {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%) rotate(-45deg);
            font-size: 60px;
            color: rgba(0, 0, 0, 0.05);
            z-index: -1;
            pointer-events: none;
        }
        .header-logo {
            position: fixed;
            top: 5mm;
            right: 15mm;
            width: 30mm;
            z-index: 100;
        }
        .footer {
            position: fixed;
            bottom: 10mm;
            left: 15mm;
            right: 15mm;
            text-align: center;
            font-size: 10px;
            color: #999;
            border-top: 1px solid #eee;
            padding-top: 5mm;
        }
        /* 图表/卡片不跨页切割 */
        .chart-container, .stat-card, .distribution-row {
            page-break-inside: avoid;
            break-inside: avoid;
        }
        h1 {
            font-size: 20px;
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 5px;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin: 15px 0;
        }
        .stat-card {
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 10px;
            text-align: center;
        }
        .stat-card .value {
            font-size: 24px;
            font-weight: bold;
            color: #3498db;
        }
        .stat-card .label {
            font-size: 11px;
            color: #666;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 6px 8px;
            text-align: left;
            font-size: 11px;
        }
        th {
            background-color: #f5f5f5;
            font-weight: bold;
        }
        .chart-img {
            max-width: 100%;
            height: auto;
        }
    </style>
</head>
<body>
    <div class="watermark">知氪AI监测</div>
    <img class="header-logo" src="data:image/png;base64,{{ logo_base64 }}" alt="Logo">

    <h1>监测报告</h1>
    <p>
        <strong>客户：</strong>{{ client_name }}<br>
        <strong>报告周期：</strong>{{ date_from }} 至 {{ date_to }}<br>
        <strong>生成时间：</strong>{{ generated_at }}
    </p>

    <h2>一、数据概览</h2>
    <div class="stats-grid">
        <div class="stat-card">
            <div class="value">{{ stats.total_distributions }}</div>
            <div class="label">分发总数</div>
        </div>
        <div class="stat-card">
            <div class="value">{{ stats.indexed_count }}</div>
            <div class="label">已收录</div>
        </div>
        <div class="stat-card">
            <div class="value">{{ stats.citation_count }}</div>
            <div class="label">AI 采信</div>
        </div>
        <div class="stat-card">
            <div class="value">{{ "%.1f"|format(stats.avg_index_rate * 100) }}%</div>
            <div class="label">平均收录率</div>
        </div>
    </div>

    <h2>二、收录趋势</h2>
    <div class="chart-container">
        <img class="chart-img" src="{{ charts.trend }}" alt="收录趋势图">
    </div>

    <h2>三、AI 采信分布</h2>
    <div class="chart-container">
        <img class="chart-img" src="{{ charts.pie }}" alt="AI 采信分布">
    </div>

    <h2>四、分发明细</h2>
    <table>
        <thead>
            <tr>
                <th>序号</th>
                <th>文章标题</th>
                <th>URL</th>
                <th>来源</th>
                <th>百度</th>
                <th>必应</th>
                <th>状态</th>
            </tr>
        </thead>
        <tbody>
            {% for dist in distributions %}
            <tr class="distribution-row">
                <td>{{ loop.index }}</td>
                <td>{{ dist.content_title or '-' }}</td>
                <td style="word-break: break-all; max-width: 200px;">{{ dist.remote_url }}</td>
                <td>{{ dist.source }}</td>
                <td>{{ dist.index_status.baidu }}</td>
                <td>{{ dist.index_status.bing }}</td>
                <td>{{ dist.status }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <div class="footer">
        知氪AI全链路监测平台 | 机密报告 | 第 {{ page_number }} 页
    </div>
</body>
</html>
```

- [ ] **步骤 4：编写 PdfExportService 实现**

```python
# index-monitor/app/services/pdf_export_service.py
"""PDF 报告导出服务——Playwright headless Chromium 渲染。

设计文档第 12.1 节 + project_memory 硬约束：
- 中文字体 Noto CJK（防掉字）
- 图表不跨页（page-break-inside: avoid）
- 水印 + Logo 每页（position: fixed）
- 图表用 base64 内联（不依赖文件路径）
"""
import base64
import os
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
        # Logo base64（1x1 透明 PNG 占位，生产替换为真实 Logo）
        logo_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
        html_content = template.render(
            client_name=report_data.get("client_name", ""),
            date_from=report_data.get("date_from", ""),
            date_to=report_data.get("date_to", ""),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            stats=report_data.get("stats", {}),
            distributions=report_data.get("distributions", []),
            charts=report_data.get("charts", {}),
            logo_base64=logo_base64,
            page_number=1,
        )

        # Playwright 渲染 PDF
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
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
```

- [ ] **步骤 5：运行测试验证通过 + Commit**

```bash
# 确保 Playwright Chromium 已安装
playwright install chromium 2>/dev/null || true

cd index-monitor && pytest tests/unit/test_pdf_export.py -v
# 预期：PASS（可能较慢，Playwright 启动需要几秒）

git add index-monitor/app/services/pdf_export_service.py \
        index-monitor/app/templates/report.html \
        index-monitor/tests/unit/test_pdf_export.py
git commit -m "feat(monitor): add PdfExportService with Playwright + HTML template

- Playwright headless Chromium 渲染
- Jinja2 HTML 模板（page-break-inside:avoid + position:fixed 水印/Logo）
- 中文字体 Noto CJK 支持
设计文档第 12.1 节。"
```

---

## 任务 2：ExcelExportService

**文件：**
- 创建：`index-monitor/app/services/excel_export_service.py`
- 测试：`index-monitor/tests/unit/test_excel_export.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_excel_export.py
"""ExcelExportService 测试。

验证目标（设计文档第 12.2 节）：
1. generate_excel 返回文件路径
2. 文件可被 openpyxl 重新打开
3. 含 4 个 sheet：分发记录/收录检测/AI 采信/数据汇总
4. 表头正确
"""
import os
import pytest
from openpyxl import load_workbook

from app.services.excel_export_service import ExcelExportService


@pytest.mark.asyncio
async def test_generate_excel_creates_file(tmp_path):
    """generate_excel 生成 Excel 文件。"""
    service = ExcelExportService(output_dir=str(tmp_path))

    export_data = {
        "client_name": "测试客户",
        "date_from": "2026-07-01",
        "date_to": "2026-07-25",
        "distributions": [
            {
                "remote_url": "https://example.com/1",
                "content_title": "文章1",
                "source": "geoflow",
                "index_status": {"baidu": "indexed", "bing": "pending"},
            }
        ],
        "index_results": [
            {"url": "https://example.com/1", "baidu": "indexed", "bing": "pending"}
        ],
        "citation_results": [
            {"url": "https://example.com/1", "model": "qwen", "hit_type": "direct"}
        ],
        "summary": {
            "total_distributions": 1,
            "indexed_count": 1,
            "citation_count": 1,
        },
    }

    file_path = await service.generate_excel(export_data, filename="test.xlsx")

    assert os.path.exists(file_path)
    assert file_path.endswith(".xlsx")


@pytest.mark.asyncio
async def test_excel_has_4_sheets(tmp_path):
    """Excel 含 4 个 sheet。"""
    service = ExcelExportService(output_dir=str(tmp_path))
    export_data = {
        "distributions": [], "index_results": [], "citation_results": [], "summary": {},
    }
    file_path = await service.generate_excel(export_data, filename="test_sheets.xlsx")

    wb = load_workbook(file_path)
    assert "分发记录" in wb.sheetnames
    assert "收录检测" in wb.sheetnames
    assert "AI采信" in wb.sheetnames
    assert "数据汇总" in wb.sheetnames


@pytest.mark.asyncio
async def test_excel_distribution_sheet_headers(tmp_path):
    """分发记录 sheet 表头正确。"""
    service = ExcelExportService(output_dir=str(tmp_path))
    file_path = await service.generate_excel(
        {"distributions": [], "index_results": [], "citation_results": [], "summary": {}},
        filename="test_headers.xlsx",
    )
    wb = load_workbook(file_path)
    ws = wb["分发记录"]
    headers = [cell.value for cell in ws[1]]
    assert "序号" in headers
    assert "文章标题" in headers
    assert "URL" in headers
    assert "来源" in headers
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_excel_export.py -v`
预期：FAIL，`ModuleNotFoundError`

- [ ] **步骤 3：编写 ExcelExportService 实现**

```python
# index-monitor/app/services/excel_export_service.py
"""Excel 明细导出服务——openpyxl 4 sheet 工作簿。

设计文档第 12.2 节。

Sheet 结构：
1. 分发记录：序号/文章标题/URL/来源/分发时间/状态
2. 收录检测：URL/百度/头条/搜狗/360/必应/检测时间
3. AI采信：URL/模型/问题/命中类型/检测时间
4. 数据汇总：统计指标
"""
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment


class ExcelExportService:
    def __init__(self, output_dir: str = "/app/exports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate_excel(
        self,
        export_data: dict,
        filename: str | None = None,
    ) -> str:
        """生成 Excel 报告。"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"export_{timestamp}.xlsx"

        file_path = str(self.output_dir / filename)

        wb = Workbook()
        # 默认 sheet 重命名为"分发记录"
        ws_dist = wb.active
        ws_dist.title = "分发记录"
        self._fill_distribution_sheet(ws_dist, export_data.get("distributions", []))

        ws_index = wb.create_sheet("收录检测")
        self._fill_index_sheet(ws_index, export_data.get("index_results", []))

        ws_citation = wb.create_sheet("AI采信")
        self._fill_citation_sheet(ws_citation, export_data.get("citation_results", []))

        ws_summary = wb.create_sheet("数据汇总")
        self._fill_summary_sheet(ws_summary, export_data.get("summary", {}))

        wb.save(file_path)
        return file_path

    def _style_header(self, ws, headers: list[str]):
        """设置表头样式。"""
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="3498DB", end_color="3498DB", fill_type="solid")
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

    def _fill_distribution_sheet(self, ws, distributions: list[dict]):
        headers = ["序号", "文章标题", "URL", "来源", "分发时间", "状态"]
        self._style_header(ws, headers)
        for idx, dist in enumerate(distributions, 1):
            ws.cell(row=idx + 1, column=1, value=idx)
            ws.cell(row=idx + 1, column=2, value=dist.get("content_title", ""))
            ws.cell(row=idx + 1, column=3, value=dist.get("remote_url", ""))
            ws.cell(row=idx + 1, column=4, value=dist.get("source", ""))
            ws.cell(row=idx + 1, column=5, value=dist.get("distributed_at", ""))
            ws.cell(row=idx + 1, column=6, value=dist.get("status", ""))

    def _fill_index_sheet(self, ws, index_results: list[dict]):
        headers = ["URL", "百度", "头条", "搜狗", "360", "必应", "检测时间"]
        self._style_header(ws, headers)
        for idx, ir in enumerate(index_results, 1):
            ws.cell(row=idx + 1, column=1, value=ir.get("url", ""))
            ws.cell(row=idx + 1, column=2, value=ir.get("baidu", ir.get("baidu_status", "")))
            ws.cell(row=idx + 1, column=3, value=ir.get("toutiao", ir.get("toutiao_status", "")))
            ws.cell(row=idx + 1, column=4, value=ir.get("sogou", ir.get("sogou_status", "")))
            ws.cell(row=idx + 1, column=5, value=ir.get("so360", ir.get("so360_status", "")))
            ws.cell(row=idx + 1, column=6, value=ir.get("bing", ir.get("bing_status", "")))
            ws.cell(row=idx + 1, column=7, value=ir.get("checked_at", ""))

    def _fill_citation_sheet(self, ws, citations: list[dict]):
        headers = ["URL", "模型", "问题", "命中类型", "检测时间"]
        self._style_header(ws, headers)
        for idx, c in enumerate(citations, 1):
            ws.cell(row=idx + 1, column=1, value=c.get("url", ""))
            ws.cell(row=idx + 1, column=2, value=c.get("model", ""))
            ws.cell(row=idx + 1, column=3, value=c.get("question", ""))
            ws.cell(row=idx + 1, column=4, value=c.get("hit_type", ""))
            ws.cell(row=idx + 1, column=5, value=c.get("checked_at", ""))

    def _fill_summary_sheet(self, ws, summary: dict):
        headers = ["指标", "数值"]
        self._style_header(ws, headers)
        rows = [
            ("分发总数", summary.get("total_distributions", 0)),
            ("已收录数", summary.get("indexed_count", 0)),
            ("AI 采信数", summary.get("citation_count", 0)),
            ("平均收录率", summary.get("avg_index_rate", 0)),
        ]
        for idx, (label, value) in enumerate(rows, 2):
            ws.cell(row=idx, column=1, value=label)
            ws.cell(row=idx, column=2, value=value)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/unit/test_excel_export.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/excel_export_service.py \
        index-monitor/tests/unit/test_excel_export.py
git commit -m "feat(monitor): add ExcelExportService with 4 sheets (openpyxl)

Sheet：分发记录/收录检测/AI采信/数据汇总。
表头样式：蓝色背景白字。
设计文档第 12.2 节。"
```

---

## 任务 3：导出端点

**文件：**
- 创建：`index-monitor/app/api/export_routes.py`
- 修改：`index-monitor/app/main.py`
- 测试：`index-monitor/tests/integration/test_export_endpoints.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/integration/test_export_endpoints.py
"""导出端点集成测试。设计文档第 12.3 节。"""
import os
import pytest
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


def _admin_headers() -> dict:
    payload = {
        "sub": "1", "name": "测试管理员", "role": "admin", "type": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, settings.SSO_JWT_SECRET, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_admin_export_pdf_returns_task_id(client):
    """admin 触发 PDF 导出，返回 task_id。"""
    resp = await client.post(
        "/api/v1/admin/exports",
        json={"export_type": "pdf", "date_from": "2026-07-01", "date_to": "2026-07-25"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_admin_export_excel_returns_task_id(client):
    """admin 触发 Excel 导出。"""
    resp = await client.post(
        "/api/v1/admin/exports",
        json={"export_type": "excel"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 202
    assert "task_id" in resp.json()


@pytest.mark.asyncio
async def test_export_requires_admin_auth(client):
    """未鉴权返回 401。"""
    resp = await client.post("/api/v1/admin/exports", json={"export_type": "pdf"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_export_invalid_type_returns_400(client):
    """无效 export_type 返回 400。"""
    resp = await client.post(
        "/api/v1/admin/exports",
        json={"export_type": "word"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/integration/test_export_endpoints.py -v`
预期：FAIL，404

- [ ] **步骤 3：编写 export_routes.py**

```python
# index-monitor/app/api/export_routes.py
"""导出端点：admin 导出全部 / 客户导出自己 / 下载。

设计文档第 12.3 节。
- POST /api/v1/admin/exports：admin 导出（可指定 client_id）
- POST /api/v1/exports：客户导出自己的数据
- GET /api/v1/exports/{task_id}/download：下载已完成的导出文件
- GET /api/v1/exports/{task_id}：查询导出任务状态
"""
import os
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_user
from app.core.database import get_db
from app.models.export_task import ExportTask
from app.services.audit_log import AuditLogService
from app.services.distribution_query import DistributionQueryService
from app.services.export_service import ExportService

router = APIRouter(tags=["exports"])


class ExportRequest(BaseModel):
    export_type: str  # 'pdf' | 'excel'
    client_id: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


@router.post("/admin/exports", status_code=202)
async def admin_create_export(
    req: ExportRequest,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """admin 触发导出（异步处理）。"""
    if req.export_type not in ("pdf", "excel"):
        raise HTTPException(status_code=400, detail="export_type 必须是 pdf 或 excel")

    task = ExportTask(
        client_id=req.client_id,
        requested_by=admin["name"],
        requested_by_role="admin",
        export_type=req.export_type,
        date_from=req.date_from,
        date_to=req.date_to,
        status="pending",
    )
    db.add(task)
    await db.commit()

    await AuditLogService.log(
        db, admin_user_id=admin["user_id"], admin_name=admin["name"],
        action="create_export", target_type="export_task", target_id=str(task.id),
        detail={"export_type": req.export_type, "client_id": req.client_id},
    )

    # 异步处理（M3 任务 4 实现后台逻辑）
    export_service = ExportService(db)
    await export_service.process_task(task.id)

    return {"task_id": str(task.id), "status": task.status}


@router.post("/exports", status_code=202)
async def client_create_export(
    req: ExportRequest,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """客户导出自己的数据。"""
    user, role = user_client
    if role != "client":
        raise HTTPException(status_code=403, detail="仅客户可调用此端点")

    if req.export_type not in ("pdf", "excel"):
        raise HTTPException(status_code=400, detail="export_type 必须是 pdf 或 excel")

    task = ExportTask(
        client_id=user.client_id,
        requested_by=user.client_id,
        requested_by_role="client",
        export_type=req.export_type,
        date_from=req.date_from,
        date_to=req.date_to,
        status="pending",
    )
    db.add(task)
    await db.commit()

    export_service = ExportService(db)
    await export_service.process_task(task.id)

    return {"task_id": str(task.id), "status": task.status}


@router.get("/exports")
async def list_export_tasks(
    page: int = 1,
    page_size: int = 20,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户的导出任务（分页）。"""
    user, role = user_client
    query = select(ExportTask)
    # admin 看所有，client 只看自己的
    if role == "client":
        query = query.where(ExportTask.client_id == user.client_id)
    query = query.order_by(ExportTask.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    tasks = result.scalars().all()
    return {
        "items": [
            {
                "task_id": str(t.id),
                "export_type": t.export_type,
                "status": t.status,
                "client_id": t.client_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "file_size": t.file_size,
            }
            for t in tasks
        ],
        "page": page,
        "page_size": page_size,
    }


@router.get("/exports/{task_id}")
async def get_export_status(
    task_id: str,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查询导出任务状态。"""
    result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="导出任务不存在")

    # 权限：admin 可查所有，client 只查自己的
    user, role = user_client
    if role == "client" and task.client_id != user.client_id:
        raise HTTPException(status_code=403, detail="无权查看此任务")

    return {
        "task_id": str(task.id),
        "status": task.status,
        "export_type": task.export_type,
        "file_path": task.file_path if task.status == "completed" else None,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.get("/exports/{task_id}/download")
async def download_export(
    task_id: str,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """下载已完成的导出文件。"""
    result = await db.execute(select(ExportTask).where(ExportTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="导出任务不存在")

    user, role = user_client
    if role == "client" and task.client_id != user.client_id:
        raise HTTPException(status_code=403, detail="无权下载此文件")

    if task.status != "completed":
        raise HTTPException(status_code=400, detail=f"任务状态：{task.status}，无法下载")

    if not task.file_path or not os.path.exists(task.file_path):
        raise HTTPException(status_code=404, detail="导出文件不存在")

    return FileResponse(
        task.file_path,
        media_type="application/octet-stream",
        filename=os.path.basename(task.file_path),
    )
```

- [ ] **步骤 4：注册 router + 运行测试**

```python
# 修改 index-monitor/app/main.py，追加：
from app.api.export_routes import router as export_router
app.include_router(export_router, prefix="/api/v1")
```

运行：`cd index-monitor && pytest tests/integration/test_export_endpoints.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/api/export_routes.py \
        index-monitor/app/main.py \
        index-monitor/tests/integration/test_export_endpoints.py
git commit -m "feat(monitor): add export endpoints (admin + client + download)

- POST /api/v1/admin/exports（admin 导出全部/指定客户）
- POST /api/v1/exports（客户导出自己）
- GET /api/v1/exports/{task_id}（查状态）
- GET /api/v1/exports/{task_id}/download（下载）
设计文档第 12.3 节。"
```

---

## 任务 4：ExportService（导出任务后台处理）

**文件：**
- 创建：`index-monitor/app/services/export_service.py`
- 测试：`index-monitor/tests/unit/test_export_service.py`

- [ ] **步骤 1：编写失败的测试**

```python
# index-monitor/tests/unit/test_export_service.py
"""ExportService 测试：任务状态机 + 数据组装。"""
import os
import pytest

from app.services.export_service import ExportService


@pytest.mark.asyncio
async def test_process_pdf_task_completes(db_session, tmp_path):
    """处理 PDF 导出任务：pending → processing → completed。"""
    from app.models.export_task import ExportTask

    task = ExportTask(
        client_id=None,  # admin 导出全部
        requested_by="测试管理员",
        requested_by_role="admin",
        export_type="pdf",
        status="pending",
    )
    db_session.add(task)
    await db_session.commit()

    service = ExportService(db_session, output_dir=str(tmp_path))
    await service.process_task(task.id)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.file_path is not None
    assert os.path.exists(task.file_path)
    assert task.file_path.endswith(".pdf")

    # 清理
    if os.path.exists(task.file_path):
        os.remove(task.file_path)
    await db_session.delete(task)
    await db_session.commit()


@pytest.mark.asyncio
async def test_process_excel_task_completes(db_session, tmp_path):
    """处理 Excel 导出任务。"""
    from app.models.export_task import ExportTask

    task = ExportTask(
        client_id=None,
        requested_by="测试管理员",
        requested_by_role="admin",
        export_type="excel",
        status="pending",
    )
    db_session.add(task)
    await db_session.commit()

    service = ExportService(db_session, output_dir=str(tmp_path))
    await service.process_task(task.id)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.file_path.endswith(".xlsx")

    if os.path.exists(task.file_path):
        os.remove(task.file_path)
    await db_session.delete(task)
    await db_session.commit()


@pytest.mark.asyncio
async def test_process_task_records_error_on_failure(db_session, monkeypatch):
    """导出失败时 status=failed + error_message 记录。"""
    from app.models.export_task import ExportTask

    task = ExportTask(
        client_id=None, requested_by="admin", requested_by_role="admin",
        export_type="pdf", status="pending",
    )
    db_session.add(task)
    await db_session.commit()

    service = ExportService(db_session)

    # Mock PdfExportService.generate_pdf 抛异常
    async def mock_fail(*args, **kwargs):
        raise RuntimeError("模拟渲染失败")
    monkeypatch.setattr(service.pdf_service, "generate_pdf", mock_fail)

    await service.process_task(task.id)

    await db_session.refresh(task)
    assert task.status == "failed"
    assert "模拟渲染失败" in task.error_message

    await db_session.delete(task)
    await db_session.commit()
```

- [ ] **步骤 2：运行测试验证失败**

运行：`cd index-monitor && pytest tests/unit/test_export_service.py -v`
预期：FAIL，`ModuleNotFoundError`

- [ ] **步骤 3：编写 ExportService 实现**

```python
# index-monitor/app/services/export_service.py
"""导出任务编排服务：状态机 + 数据组装 + 调用 PdfExportService/ExcelExportService。

设计文档第 12.6 节。

状态机：pending → processing → completed / failed
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.citation_result import CitationResult
from app.models.export_task import ExportTask
from app.models.index_result import IndexResult
from app.services.distribution_query import DistributionQueryService
from app.services.pdf_export_service import PdfExportService
from app.services.excel_export_service import ExcelExportService

logger = logging.getLogger(__name__)


class ExportService:
    def __init__(self, db: AsyncSession, output_dir: str = "/app/exports"):
        self.db = db
        self.output_dir = output_dir
        self.pdf_service = PdfExportService(output_dir=output_dir)
        self.excel_service = ExcelExportService(output_dir=output_dir)

    async def process_task(self, task_id: str) -> None:
        """处理导出任务（同步调用，但内部用 async Playwright）。

        生产环境可改为后台任务（APScheduler / Celery），此处保持简单。
        """
        result = await self.db.execute(
            select(ExportTask).where(ExportTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            logger.error(f"导出任务 {task_id} 不存在")
            return

        # 标记 processing
        task.status = "processing"
        await self.db.commit()

        try:
            # 组装数据
            export_data = await self._assemble_data(task)

            # 调用对应导出服务
            if task.export_type == "pdf":
                file_path = await self.pdf_service.generate_pdf(
                    export_data, filename=f"export_{task.id}.pdf"
                )
            elif task.export_type == "excel":
                file_path = await self.excel_service.generate_excel(
                    export_data, filename=f"export_{task.id}.xlsx"
                )
            else:
                raise ValueError(f"不支持的导出类型：{task.export_type}")

            # 标记 completed
            task.file_path = file_path
            task.file_size = len(open(file_path, "rb").read())
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
            await self.db.commit()

            logger.info(f"导出任务 {task_id} 完成：{file_path}")

        except Exception as e:
            logger.exception(f"导出任务 {task_id} 失败")
            task.status = "failed"
            task.error_message = str(e)
            task.completed_at = datetime.now(timezone.utc)
            await self.db.commit()

    async def _assemble_data(self, task: ExportTask) -> dict:
        """组装导出数据。"""
        query_service = DistributionQueryService(self.db)

        # 查分发记录
        distributions = await query_service.list_distributions(
            client_id=task.client_id
        )

        # 查收录检测结果
        urls = [d["remote_url"] for d in distributions if d.get("remote_url")]
        index_results = []
        if urls:
            ir_result = await self.db.execute(
                select(IndexResult).where(IndexResult.url.in_(urls))
            )
            index_results = [
                {
                    "url": ir.url,
                    "baidu": ir.baidu_status,
                    "toutiao": ir.toutiao_status,
                    "sogou": ir.sogou_status,
                    "so360": ir.so360_status,
                    "bing": ir.bing_status,
                    "checked_at": ir.updated_at.isoformat() if ir.updated_at else None,
                }
                for ir in ir_result.scalars().all()
            ]

        # 查采信检测结果
        citation_results = []
        if urls:
            cr_result = await self.db.execute(
                select(CitationResult).where(CitationResult.url.in_(urls))
            )
            citation_results = [
                {
                    "url": cr.url,
                    "model": cr.model,
                    "question": cr.question,
                    "hit_type": cr.hit_type,
                    "checked_at": cr.checked_at.isoformat() if cr.checked_at else None,
                }
                for cr in cr_result.scalars().all()
            ]

        # 统计汇总
        indexed_count = sum(
            1 for ir in index_results
            if any(ir.get(k) == "indexed" for k in ("baidu", "toutiao", "sogou", "so360", "bing"))
        )
        summary = {
            "total_distributions": len(distributions),
            "indexed_count": indexed_count,
            "citation_count": len(citation_results),
            "avg_index_rate": indexed_count / len(distributions) if distributions else 0,
        }

        return {
            "client_name": task.client_id or "全部客户",
            "date_from": task.date_from.isoformat() if task.date_from else "",
            "date_to": task.date_to.isoformat() if task.date_to else "",
            "distributions": distributions,
            "index_results": index_results,
            "citation_results": citation_results,
            "summary": summary,
            "stats": summary,  # PDF 模板用 stats 字段
            "charts": {},  # 图表 base64 由前端生成或后续实现
        }
```

- [ ] **步骤 4：运行测试验证通过**

运行：`cd index-monitor && pytest tests/unit/test_export_service.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/export_service.py \
        index-monitor/tests/unit/test_export_service.py
git commit -m "feat(monitor): add ExportService for task orchestration

状态机：pending → processing → completed/failed
组装数据：分发记录 + 收录检测 + 采信检测 + 统计汇总
设计文档第 12.6 节。"
```

---

## M3 完成检查清单

- [ ] **全量测试通过**

```bash
cd index-monitor && pytest tests/ -v --tb=short
# 预期：所有测试 PASS（含 M1 + M2 + M3）
```

- [ ] **导出目录可写**

```bash
# 确认导出目录存在且可写
mkdir -p /app/exports && touch /app/exports/.test && rm /app/exports/.test
```

- [ ] **Playwright Chromium 可用**

```bash
playwright install chromium
python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); print('OK'); b.close(); p.stop()"
```

- [ ] **PDF 文件验证**

```bash
# 手动触发一次导出，检查 PDF
# - 文件大小 > 10KB
# - pdftotext 能提取中文
# - 含水印文字
```

---

## M3 验收标准对照

| 验收标准 | 内容 | 对应任务 |
|---------|------|---------|
| 19 | admin 导出 PDF 报告，含统计卡片+图表+明细表 | 任务 1+3 |
| 20 | admin 导出 Excel 明细，4 个 sheet | 任务 2+3 |
| 21 | PDF 中文不乱码，图表不跨页 | 任务 1（Noto CJK + page-break-inside）|
| 22 | 导出文件可下载，含水印/Logo | 任务 1+3 |
| 36 | 导出文件不超过 50MB（控制数据量）| 任务 4（分页查询）|

---

## 下一步

M3 完成后，进入 [M4：Dashboard 前端 + 官网入口 + E2E](./2026-07-25-plan2-m4-frontend-website-e2e.md)。
