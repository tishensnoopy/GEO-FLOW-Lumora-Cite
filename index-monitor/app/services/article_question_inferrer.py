# index-monitor/app/services/article_question_inferrer.py
"""文章→客户问题 AI 推断服务。

每篇发稿（ManualDistribution）通过 DeepSeek 分析文章内容后，自动关联 1-3 个
最相关的客户监测问题（ClientQuestion），写入 ArticleQuestionMapping。

后续引用检测仅检测关联的问题，避免对所有问题做组合爆炸式的检测。

降级策略：
- DeepSeek 调用失败 / 返回非 JSON / 未配置 API key → 返回空列表，不抛异常，
  让上游管道继续推进而非中断。
- 客户无 active 问题 → 直接返回空列表，跳过 LLM 调用。
"""
import asyncio
import json
import logging
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article_question_mapping import ArticleQuestionMapping
from app.models.client_question import ClientQuestion
from app.models.manual_distribution import ManualDistribution
from app.services.citation_check.fetcher import fetch_public_content
from app.services.deepseek_client import DeepSeekError, ask_deepseek
from app.services.llm_client import load_ai_configs

logger = logging.getLogger(__name__)

# system_config 中 DeepSeek API key 的配置键
DEEPSEEK_CONFIG_KEY = "ai_deepseek_api_key"

# 推断结果筛选阈值
MIN_RELEVANCE_SCORE = 0.3
MAX_RELATED_QUESTIONS = 3

# 抓取正文喂给 LLM 的字符数上限（与 prompt 模板 content[:500] 对齐）
CONTENT_SNIPPET_LENGTH = 500

INFER_SYSTEM_PROMPT = "你是内容分析专家，擅长判断文章内容与搜索意图的关联度。"

INFER_PROMPT_TEMPLATE = """你是内容分析专家，擅长判断文章内容与搜索意图的关联度。

请分析以下文章，从客户问题列表中选择最相关的 1-3 个问题。

文章标题：{title}
文章片段：{content}

客户问题列表（JSON 数组）：
{questions_json}

请只返回最相关的问题，格式为 JSON 数组：
[{{"question_id": "问题ID", "score": 0.0-1.0}}]

要求：
1. 只返回评分 >= 0.3 的问题
2. 最多返回 3 个
3. 只返回 JSON，不要其他文字
"""


class ArticleQuestionInferrer:
    """文章→客户问题推断服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def infer_for_distribution(
        self, distribution_id: str, client_id: str
    ) -> list[ArticleQuestionMapping]:
        """对单篇发稿推断最相关的客户问题并写入关联表。

        Parameters
        ----------
        distribution_id : str
            ManualDistribution.id（UUID 字符串）
        client_id : str
            客户 ID，用于筛选该客户的 active 问题

        Returns
        -------
        list[ArticleQuestionMapping]
            新写入的关联记录。降级场景返回空列表。

        Raises
        ------
        ValueError
            发稿记录不存在时抛出。
        """
        # 1. 获取发稿记录
        try:
            dist_uuid = uuid.UUID(str(distribution_id))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"发稿记录 ID 格式无效: {distribution_id}") from exc

        dist_result = await self.db.execute(
            select(ManualDistribution).where(ManualDistribution.id == dist_uuid)
        )
        distribution = dist_result.scalars().first()
        if distribution is None:
            raise ValueError(f"发稿记录不存在: {distribution_id}")

        # 2. 获取客户 active 问题
        q_result = await self.db.execute(
            select(ClientQuestion)
            .where(
                ClientQuestion.client_id == client_id,
                ClientQuestion.status == "active",
            )
            .order_by(ClientQuestion.sort_order)
        )
        questions = list(q_result.scalars().all())
        if not questions:
            logger.info(
                "客户 %s 无 active 问题，跳过推断 (distribution=%s)",
                client_id, distribution_id,
            )
            return []

        # 3. 加载 DeepSeek API key 配置
        configs = await load_ai_configs(self.db, [DEEPSEEK_CONFIG_KEY])
        api_key = configs.get(DEEPSEEK_CONFIG_KEY)
        if not api_key:
            logger.warning(
                "未配置 %s，跳过推断 (distribution=%s)",
                DEEPSEEK_CONFIG_KEY, distribution_id,
            )
            return []

        # 4. 抓取文章内容（同步函数，通过 to_thread 不阻塞事件循环）
        try:
            fetched = await asyncio.to_thread(
                fetch_public_content, distribution.remote_url
            )
        except Exception as exc:
            # fetch_public_content 内部已捕获大多数异常；此处兜底防 SSRF 校验等抛出
            logger.warning(
                "抓取文章内容失败，跳过推断 (distribution=%s, url=%s): %s",
                distribution_id, distribution.remote_url, exc,
            )
            return []

        title = fetched.title or distribution.content_title or ""
        content_snippet = (fetched.text or "")[:CONTENT_SNIPPET_LENGTH]

        # 5. 构造问题列表 JSON
        questions_json = json.dumps(
            [
                {"question_id": str(q.id), "question": q.question}
                for q in questions
            ],
            ensure_ascii=False,
        )
        prompt = INFER_PROMPT_TEMPLATE.format(
            title=title,
            content=content_snippet,
            questions_json=questions_json,
        )

        # 6. 调用 DeepSeek 推断
        try:
            response_text = await ask_deepseek(
                api_key=api_key,
                prompt=prompt,
                system_prompt=INFER_SYSTEM_PROMPT,
            )
        except DeepSeekError as exc:
            logger.warning(
                "DeepSeek 调用失败，降级返回空列表 (distribution=%s): %s",
                distribution_id, exc,
            )
            return []
        except Exception as exc:
            # 兜底：任何非预期异常都不应中断上游管道
            logger.exception(
                "DeepSeek 调用抛出非预期异常，降级返回空列表 (distribution=%s): %s",
                distribution_id, exc,
            )
            return []

        # 7. 解析 JSON
        try:
            parsed = json.loads(response_text)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "DeepSeek 返回非 JSON 文本，降级返回空列表 (distribution=%s): %s",
                distribution_id, exc,
            )
            return []

        if not isinstance(parsed, list):
            logger.warning(
                "DeepSeek 返回非数组 JSON，降级返回空列表 (distribution=%s): %r",
                distribution_id, parsed,
            )
            return []

        # 8. 过滤低分 + 按分数降序 + 截断到 MAX_RELATED_QUESTIONS
        valid_qids = {str(q.id) for q in questions}
        candidates: list[dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            qid = item.get("question_id")
            if qid is None or str(qid) not in valid_qids:
                # 过滤掉不属于该客户的问题 ID，防脏数据
                continue
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                continue
            if score < MIN_RELEVANCE_SCORE:
                continue
            candidates.append({"question_id": str(qid), "score": score})

        candidates.sort(key=lambda x: x["score"], reverse=True)
        top = candidates[:MAX_RELATED_QUESTIONS]

        if not top:
            logger.info(
                "DeepSeek 推断无符合阈值的问题 (distribution=%s)", distribution_id,
            )
            return []

        # 9. 清除旧关联，避免残留
        await self.db.execute(
            delete(ArticleQuestionMapping).where(
                ArticleQuestionMapping.distribution_id == dist_uuid
            )
        )

        # 10. 写入新关联
        new_mappings: list[ArticleQuestionMapping] = []
        for item in top:
            mapping = ArticleQuestionMapping(
                distribution_id=dist_uuid,
                client_question_id=uuid.UUID(item["question_id"]),
                relevance_score=item["score"],
            )
            self.db.add(mapping)
            new_mappings.append(mapping)

        await self.db.commit()
        for m in new_mappings:
            await self.db.refresh(m)

        logger.info(
            "推断完成 (distribution=%s, client=%s): 关联 %d 个问题",
            distribution_id, client_id, len(new_mappings),
        )
        return new_mappings

    async def get_related_questions(
        self, distribution_id: str
    ) -> list[ClientQuestion]:
        """查询某发稿已关联的客户问题列表。

        Parameters
        ----------
        distribution_id : str
            ManualDistribution.id（UUID 字符串）

        Returns
        -------
        list[ClientQuestion]
            关联的客户问题列表，按 sort_order 排序。无关联时返回空列表。
        """
        try:
            dist_uuid = uuid.UUID(str(distribution_id))
        except (ValueError, AttributeError):
            return []

        result = await self.db.execute(
            select(ClientQuestion)
            .join(
                ArticleQuestionMapping,
                ArticleQuestionMapping.client_question_id == ClientQuestion.id,
            )
            .where(ArticleQuestionMapping.distribution_id == dist_uuid)
            .order_by(ClientQuestion.sort_order)
        )
        return list(result.scalars().all())
