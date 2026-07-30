"""契约测试数据 seed + 清理。

插入固定数据（1 个作者 + 1 篇文章 + 2 条分发 + 1 个渠道），测完自动清理。

实现偏离简报说明：
- 简报原 SQL 用 ``author_id = 1``，但 GEOFlow 真实 DB 的 ``authors`` 表为空
  （FK ``articles_author_id_fkey`` 会拒绝插入）。改为插入固定测试作者
  ``TEST_AUTHOR_ID``，articles 引用之，测后清理。
- ``article_distributions.created_at`` 在真实表中无默认值（nullable，无 DEFAULT）。
  若不显式设置，``get_distribution_count_by_date`` 契约测试因 NULL created_at
  无法被 ``created_at >= start_date`` 命中而失败。显式插入 ``NOW()``。
"""
from sqlalchemy import text

# 固定测试数据 ID（避免与真实数据冲突）
TEST_AUTHOR_ID = 999900001
TEST_ARTICLE_ID = 999900001
TEST_CHANNEL_ID = 999900001
TEST_DIST_ID_1 = 999900001
TEST_DIST_ID_2 = 999900002
TEST_REMOTE_URL_1 = "https://contract-test.example.com/article-1"
TEST_REMOTE_URL_2 = "https://contract-test.example.com/article-2"


async def seed_contract_data(conn):
    """插入契约测试数据。调用方负责在测试后调用 cleanup_contract_data。"""
    # 作者（articles.author_id 有 FK 约束 → authors.id，真实库 authors 表为空，
    # 必须先插入测试作者，否则 articles 插入触发 ForeignKeyViolationError）
    await conn.execute(
        text("""
            INSERT INTO authors (id, name)
            VALUES (:id, :name)
        """),
        {"id": TEST_AUTHOR_ID, "name": "契约测试作者"},
    )
    await conn.execute(
        text("""
            INSERT INTO distribution_channels (id, name, domain, endpoint_url, channel_type, status)
            VALUES (:id, :name, :domain, :endpoint, :ctype, 'active')
        """),
        {
            "id": TEST_CHANNEL_ID,
            "name": "契约测试渠道",
            "domain": "contract-test.example.com",
            "endpoint": "https://contract-test.example.com/api",
            "ctype": "geoflow_agent",
        },
    )
    await conn.execute(
        text("""
            INSERT INTO articles (id, title, slug, content, category_id, author_id, status, review_status)
            VALUES (:id, :title, :slug, :content, 1, :author_id, 'published', 'approved')
        """),
        {
            "id": TEST_ARTICLE_ID,
            "title": "契约测试文章",
            "slug": "contract-test-article",
            "content": "契约测试正文",
            "author_id": TEST_AUTHOR_ID,
        },
    )
    await conn.execute(
        text("""
            INSERT INTO article_distributions
            (id, article_id, remote_url, status, action, distribution_channel_id, created_at)
            VALUES
            (:id1, :aid, :url1, 'synced', 'publish', :cid, NOW()),
            (:id2, :aid, :url2, 'synced', 'delete', :cid, NOW())
        """),
        {
            "id1": TEST_DIST_ID_1,
            "id2": TEST_DIST_ID_2,
            "aid": TEST_ARTICLE_ID,
            "url1": TEST_REMOTE_URL_1,
            "url2": TEST_REMOTE_URL_2,
            "cid": TEST_CHANNEL_ID,
        },
    )


async def cleanup_contract_data(conn):
    """清理契约测试数据（按固定 ID 删除）。"""
    await conn.execute(
        text("DELETE FROM article_distributions WHERE id IN (:id1, :id2)"),
        {"id1": TEST_DIST_ID_1, "id2": TEST_DIST_ID_2},
    )
    await conn.execute(
        text("DELETE FROM articles WHERE id = :id"),
        {"id": TEST_ARTICLE_ID},
    )
    await conn.execute(
        text("DELETE FROM distribution_channels WHERE id = :id"),
        {"id": TEST_CHANNEL_ID},
    )
    await conn.execute(
        text("DELETE FROM authors WHERE id = :id"),
        {"id": TEST_AUTHOR_ID},
    )
