"""BYOK provider adapters using only Python's standard library."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .engine import ModelAnswer, VERIFIED_CITATIONS


def load_env_file(path: str) -> None:
    if not path or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _post_json(
    url: str,
    api_key: str,
    payload: dict,
    timeout: int = 180,
    *,
    headers: dict | None = None,
) -> dict:
    request_headers = {"Content-Type": "application/json"}
    if api_key:
        request_headers["Authorization"] = f"Bearer {api_key}"
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:600]
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def _walk_sources(data) -> list[str]:
    """Collect likely source URLs from heterogeneous provider responses."""
    found = []

    def walk(value, parent_key=""):
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = str(key).lower()
                if lowered in {"url", "link", "uri"} and isinstance(child, str) and child.startswith(("http://", "https://")):
                    if child not in found:
                        found.append(child)
                else:
                    walk(child, lowered)
        elif isinstance(value, list):
            for child in value:
                walk(child, parent_key)

    walk(data)
    return found[:20]


def _resolve_google_grounding_sources(sources: list[str]) -> list[str]:
    """Resolve only Google's grounding redirect URLs to their destination pages."""
    resolved = []
    for source in sources:
        host = (urllib.parse.urlsplit(source).hostname or "").lower()
        if host == "vertexaisearch.cloud.google.com":
            try:
                request = urllib.request.Request(source, headers={"User-Agent": "LumoraCite/0.2"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    source = response.geturl()
            except Exception:
                pass
        if source not in resolved:
            resolved.append(source)
    return resolved


def _find_text(data) -> str:
    if isinstance(data, dict):
        for path in (
            ("output_text",),
            ("choices", 0, "message", "content"),
            ("output", "choices", 0, "message", "content"),
        ):
            current = data
            try:
                for key in path:
                    current = current[key]
                if isinstance(current, str):
                    return current
            except (KeyError, IndexError, TypeError):
                pass
        output = data.get("output")
        if isinstance(output, list):
            texts = []
            for item in output:
                for content in item.get("content", []) if isinstance(item, dict) else []:
                    text = content.get("text") if isinstance(content, dict) else None
                    if text:
                        texts.append(text)
            if texts:
                return "\n".join(texts)
        content = data.get("content")
        if isinstance(content, list):
            texts = [item.get("text") for item in content if isinstance(item, dict) and item.get("type") == "text"]
            if texts:
                return "\n".join(texts)
        candidates = data.get("candidates")
        if isinstance(candidates, list):
            texts = []
            for candidate in candidates:
                parts = ((candidate or {}).get("content") or {}).get("parts", [])
                texts.extend(part.get("text") for part in parts if isinstance(part, dict) and part.get("text"))
            if texts:
                return "\n".join(texts)
    return ""


class RawHttpAdapter:
    capability = VERIFIED_CITATIONS

    def __init__(self, provider_id: str, name: str, model_id: str, api_key: str, url: str, payload_builder):
        self.provider_id = provider_id
        self.name = name
        self.model_id = model_id
        self.api_key = api_key
        self.url = url
        self.payload_builder = payload_builder

    def ask(self, question: str) -> ModelAnswer:
        if not self.api_key:
            return ModelAnswer(self.name, self.model_id, "", [], False, "API Key 未配置")
        data = _post_json(self.url, self.api_key, self.payload_builder(question))
        sources = _walk_sources(data)
        return ModelAnswer(
            self.name,
            self.model_id,
            _find_text(data),
            sources,
            bool(sources) or _search_used(data),
            None,
        )


class GeminiAdapter:
    capability = VERIFIED_CITATIONS
    name = "Gemini"
    provider_id = "gemini"

    def __init__(self, model_id: str, api_key: str):
        self.model_id = model_id
        self.api_key = api_key

    def ask(self, question: str) -> ModelAnswer:
        if not self.api_key:
            return ModelAnswer(self.name, self.model_id, "", [], False, "API Key 未配置")
        data = _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_id}:generateContent",
            "",
            {
                "contents": [{"parts": [{"text": question}]}],
                "tools": [{"google_search": {}}],
            },
            headers={"x-goog-api-key": self.api_key},
        )
        sources = _resolve_google_grounding_sources(_walk_sources(data))
        return ModelAnswer(self.name, self.model_id, _find_text(data), sources, bool(sources), None)


class AnthropicAdapter:
    capability = VERIFIED_CITATIONS
    name = "Claude"
    provider_id = "claude"

    def __init__(self, model_id: str, api_key: str):
        self.model_id = model_id
        self.api_key = api_key

    def ask(self, question: str) -> ModelAnswer:
        if not self.api_key:
            return ModelAnswer(self.name, self.model_id, "", [], False, "API Key 未配置")
        data = _post_json(
            "https://api.anthropic.com/v1/messages",
            "",
            {
                "model": self.model_id,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": question}],
                "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            },
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        sources = _walk_sources(data)
        return ModelAnswer(self.name, self.model_id, _find_text(data), sources, bool(sources), None)


def _search_used(data) -> bool:
    serialized = json.dumps(data, ensure_ascii=False).lower()
    return any(marker in serialized for marker in (
        "web_search_call",
        "web_search_tool_result",
        "groundingmetadata",
        "search_results",
        "search_info",
    ))


def adapter_catalog() -> list[dict]:
    return [
        {"id": "doubao", "name": "豆包", "model_id": os.getenv("CITATION_DOUBAO_MODEL", "doubao-seed-2-0-lite-260428"), "configured": bool(os.getenv("ARK_API_KEY", ""))},
        {"id": "qwen", "name": "千问", "model_id": os.getenv("CITATION_QWEN_MODEL", "qwen3.6-plus"), "configured": bool(os.getenv("DASHSCOPE_API_KEY", ""))},
        {"id": "ernie", "name": "文心", "model_id": os.getenv("CITATION_ERNIE_MODEL", "ernie-5.0"), "configured": bool(os.getenv("BAIDU_API_KEY", ""))},
        {"id": "openai", "name": "ChatGPT / OpenAI", "model_id": os.getenv("CITATION_OPENAI_MODEL", "gpt-5"), "configured": bool(os.getenv("OPENAI_API_KEY", ""))},
        {"id": "gemini", "name": "Gemini", "model_id": os.getenv("CITATION_GEMINI_MODEL", "gemini-2.5-flash"), "configured": bool(os.getenv("GEMINI_API_KEY", ""))},
        {"id": "claude", "name": "Claude", "model_id": os.getenv("CITATION_CLAUDE_MODEL", "claude-sonnet-4-5"), "configured": bool(os.getenv("ANTHROPIC_API_KEY", ""))},
        # 阶段 3：网页端模拟平台（无公开 API）。元宝不需要 API Key，
        # configured 始终为 True——Playwright 不可用时在 ask() 内捕获并返回错误。
        {"id": "yuanbao", "name": "元宝", "model_id": "web-simulation", "configured": True},
    ]


def default_adapters(selected_ids: list[str] | None = None) -> list:
    ark_key = os.getenv("ARK_API_KEY", "")
    dashscope_key = os.getenv("DASHSCOPE_API_KEY", "")
    baidu_key = os.getenv("BAIDU_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    adapters = {
        "doubao": RawHttpAdapter(
            "doubao",
            "豆包",
            os.getenv("CITATION_DOUBAO_MODEL", "doubao-seed-2-0-lite-260428"),
            ark_key,
            "https://ark.cn-beijing.volces.com/api/v3/responses",
            lambda question: {
                "model": os.getenv("CITATION_DOUBAO_MODEL", "doubao-seed-2-0-lite-260428"),
                "input": question,
                "instructions": "正常回答问题。请优先联网搜索最新公开信息，并保留来源。",
                "tools": [{"type": "web_search"}],
            },
        ),
        "qwen": RawHttpAdapter(
            "qwen",
            "千问",
            os.getenv("CITATION_QWEN_MODEL", "qwen3.6-plus"),
            dashscope_key,
            "https://dashscope.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1/responses",
            lambda question: {
                "model": os.getenv("CITATION_QWEN_MODEL", "qwen3.6-plus"),
                "input": question,
                "instructions": "正常回答问题。请优先联网搜索最新公开信息，并保留来源。",
                "tools": [{"type": "web_search"}],
                "enable_thinking": False,
            },
        ),
        "ernie": RawHttpAdapter(
            "ernie",
            "文心",
            os.getenv("CITATION_ERNIE_MODEL", "ernie-5.0"),
            baidu_key,
            "https://qianfan.baidubce.com/v2/chat/completions",
            lambda question: {
                "model": os.getenv("CITATION_ERNIE_MODEL", "ernie-5.0"),
                "messages": [{"role": "user", "content": question}],
                "web_search": {"enable": True, "enable_citation": True, "enable_trace": True},
            },
        ),
        "openai": RawHttpAdapter(
            "openai",
            "ChatGPT / OpenAI",
            os.getenv("CITATION_OPENAI_MODEL", "gpt-5"),
            openai_key,
            "https://api.openai.com/v1/responses",
            lambda question: {
                "model": os.getenv("CITATION_OPENAI_MODEL", "gpt-5"),
                "input": question,
                "tools": [{"type": "web_search"}],
                "include": ["web_search_call.action.sources"],
            },
        ),
        "gemini": GeminiAdapter(os.getenv("CITATION_GEMINI_MODEL", "gemini-2.5-flash"), gemini_key),
        "claude": AnthropicAdapter(os.getenv("CITATION_CLAUDE_MODEL", "claude-sonnet-4-5"), anthropic_key),
        # 阶段 3：网页端模拟平台。元宝通过 Playwright 模拟，不需要 API Key。
        "yuanbao": WebSimulationAdapter("yuanbao"),
    }
    if selected_ids is None:
        selected_ids = [item["id"] for item in adapter_catalog() if item["configured"]]
    return [adapters[item] for item in selected_ids if item in adapters]


def _run_async(coro):
    """在同步上下文中安全运行异步协程。

    ask() 在 ThreadPoolExecutor 子线程中被调用（无运行中的事件循环），
    可直接用 asyncio.run。若意外处于事件循环中（不该发生），降级为新线程运行，
    避免 "asyncio.run() cannot be called from a running event loop"。
    """
    import asyncio
    import concurrent.futures
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # 已在事件循环中：用独立线程跑，避免嵌套事件循环报错
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


class WebSimulationAdapter:
    """将网页端模拟器包装成 CitationModelAdapter。

    让无公开 API 的 AI 平台（如元宝）通过 Playwright 网页端模拟接入
    lumora-cite 的引用检测流程（probe + run_citation_check）。

    设计：
    - ask(question) 是同步方法（满足 CitationModelAdapter Protocol），
      内部通过 _run_async 调用 WebSimulationManager.simulate（异步）。
    - target_urls 在此层不传入（命中判定由 engine.run_citation_check 统一完成，
      adapter 只负责返回 sources）。
    - 模拟失败时返回带 error 的 ModelAnswer，不抛异常——保证单个平台失败
      不阻塞其他平台的引用检测。
    - Playwright 不可用时（未安装/无浏览器）在 ask() 内捕获并返回错误。
    """

    capability = VERIFIED_CITATIONS

    def __init__(self, platform_id: str):
        # 延迟导入避免 Playwright 未安装时影响整个 providers 模块加载
        from app.services.web_simulation import get_web_simulation_manager
        self._manager = get_web_simulation_manager()
        self.provider_id = platform_id
        simulator = self._manager.get(platform_id)
        self.name = simulator.platform_name if simulator else platform_id
        self.model_id = "web-simulation"

    def ask(self, question: str) -> ModelAnswer:
        try:
            result = _run_async(
                self._manager.simulate(self.provider_id, question, [], timeout=60)
            )
        except Exception as exc:  # noqa: BLE001 - 网页端模拟易失败，统一兜底
            return ModelAnswer(self.name, self.model_id, "", [], None, str(exc))

        if not result.success:
            return ModelAnswer(self.name, self.model_id, result.answer, [], None, result.error)

        sources = [s.get("url", "") for s in result.sources if s.get("url")]
        return ModelAnswer(
            self.name,
            self.model_id,
            result.answer,
            sources,
            bool(sources),
            None,
        )
