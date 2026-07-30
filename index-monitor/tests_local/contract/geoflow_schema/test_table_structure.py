"""结构契约：表/字段/类型校验。

只读 information_schema，不依赖业务数据，可对空库运行。
失败时打印"哪个字段缺失/类型不匹配"，直接指向问题。
"""
import pytest
from sqlalchemy import text

# 防腐层实际消费的字段清单——这是 LumoraCite 与 GEOFlow 的 schema 契约。
# GEOFlow 加字段不触发失败；删/改这里的字段才失败。
EXPECTED_FIELDS = {
    "article_distributions": {
        "id": ("integer", "bigint"),
        "article_id": ("integer", "bigint"),
        "remote_url": ("character varying", "text"),
        "status": ("character varying", "text"),
        "action": ("character varying", "text"),
        "distribution_channel_id": ("integer", "bigint"),
        "created_at": ("timestamp with time zone", "timestamp without time zone"),
    },
    "articles": {
        "id": ("integer", "bigint"),
        "title": ("character varying", "text"),
        "slug": ("character varying", "text"),
        "excerpt": ("text",),
        "content": ("text",),
        "keywords": ("text", "character varying"),
        "meta_description": ("text", "character varying"),
        "original_keyword": ("character varying", "text"),
        "published_at": ("timestamp with time zone", "timestamp without time zone"),
    },
    "distribution_channels": {
        "id": ("integer", "bigint"),
        "name": ("character varying", "text"),
        "domain": ("character varying", "text"),
        "channel_type": ("character varying", "text"),
    },
}


@pytest.mark.asyncio
async def test_tables_exist(geoflow_session):
    """三张表必须存在。"""
    result = await geoflow_session.execute(
        text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('article_distributions', 'articles', 'distribution_channels')
        """)
    )
    tables = {row[0] for row in result.fetchall()}
    expected = {"article_distributions", "articles", "distribution_channels"}
    missing = expected - tables
    assert not missing, f"GEOFlow 缺失表: {missing}"


@pytest.mark.asyncio
async def test_fields_exist_and_type_compatible(geoflow_session):
    """每个 DTO 消费的字段必须存在且类型兼容。"""
    for table_name, expected_fields in EXPECTED_FIELDS.items():
        result = await geoflow_session.execute(
            text("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table
            """),
            {"table": table_name},
        )
        actual = {row[0]: row[1] for row in result.fetchall()}
        assert actual, f"表 {table_name} 不存在或无字段"

        for field_name, acceptable_types in expected_fields.items():
            assert field_name in actual, (
                f"表 {table_name} 缺失字段 {field_name}（DTO 消费此字段）"
            )
            actual_type = actual[field_name]
            assert actual_type in acceptable_types, (
                f"表 {table_name}.{field_name} 类型不兼容: "
                f"期望 {acceptable_types}, 实际 {actual_type}"
            )
