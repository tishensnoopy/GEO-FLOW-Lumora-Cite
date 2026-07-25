# index-monitor/tests/integration/test_db_role_isolation.py
"""改进 2：跨 schema DB 层权限隔离集成测试（TDD RED 阶段先写）。

验证目标（规格要求 #42）
========================
监测系统 DB 用户 ``monitor_user`` 对 ``public`` schema 只读（SELECT），
对 ``monitor`` schema 读写（ALL ON TABLES）。

权限矩阵
========
| Schema  | USAGE | CREATE | 表权限         | 序列权限 |
|---------|-------|--------|----------------|----------|
| public  | ✅    | ❌     | SELECT（只读） | —        |
| monitor | ✅    | ❌     | ALL（读写）    | ALL      |

- 无 CREATE：DDL 留给 ``geo_user``（alembic / Laravel migration 以 geo_user 运行）。
- ``ALTER DEFAULT PRIVILEGES FOR ROLE geo_user``：geo_user 未来新建表自动继承权限。

前置条件
========
``deploy/scripts/setup-db-roles.sh`` 已对目标 PG 执行（创建 monitor_user + 授权）。
未执行时 ``monitor_user`` 不存在，``has_*_privilege`` 返回 NULL，测试 FAIL（RED）。

设计说明
========
- 用 ``db_session`` fixture（连接为 geo_user，超级用户可查任意角色权限）。
- ``has_table_privilege`` / ``has_schema_privilege`` 是 PG 内置函数，返回 boolean；
  monitor_user 不存在时返回 NULL（非报错）。
- ``public.alembic_version`` 在测试环境真实存在（init-db.sh / alembic 留下），
  生产环境同理作用于 ``public.articles`` 等所有 GEOFlow 表。
- DEFAULT PRIVILEGES 测试：创建临时 ``public._test_default_priv`` 表验证自动授权，
  finally 中 DROP 清理。
"""
import pytest
from sqlalchemy import text


# --------------------------------------------------------------------------- #
# 1. monitor_user 角色存在且可登录                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_monitor_user_role_exists(db_session):
    """monitor_user 角色已创建。"""
    result = await db_session.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = 'monitor_user'")
    )
    assert result.scalar() == 1, "monitor_user 角色不存在（setup-db-roles.sh 未执行？）"


@pytest.mark.asyncio
async def test_monitor_user_is_login_role(db_session):
    """monitor_user 可登录（rolcanlogin=True），供应用连接。"""
    result = await db_session.execute(
        text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'monitor_user'")
    )
    assert result.scalar() is True, "monitor_user 必须是 LOGIN 角色"


# --------------------------------------------------------------------------- #
# 2. public schema：USAGE（可访问）+ 无 CREATE（不能改 schema）                #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_monitor_user_has_usage_on_public_schema(db_session):
    """monitor_user 对 public schema 有 USAGE（可访问 GEOFlow 表做只读 JOIN）。"""
    result = await db_session.execute(
        text("SELECT has_schema_privilege('monitor_user', 'public', 'USAGE')")
    )
    assert result.scalar() is True


@pytest.mark.asyncio
async def test_monitor_user_cannot_create_in_public_schema(db_session):
    """monitor_user 对 public schema 无 CREATE（不能建表/改 schema，防破坏 GEOFlow）。"""
    result = await db_session.execute(
        text("SELECT has_schema_privilege('monitor_user', 'public', 'CREATE')")
    )
    assert result.scalar() is False


# --------------------------------------------------------------------------- #
# 3. public 表：SELECT（只读）+ 无 INSERT（防误写 GEOFlow 数据）               #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_monitor_user_can_select_public_table(db_session):
    """monitor_user 对 public 现有表有 SELECT（只读 GEOFlow 数据）。

    用 public.alembic_version（测试环境存在的真实表）验证。
    生产环境同理作用于 public.articles / public.admins 等所有 GEOFlow 表。
    """
    result = await db_session.execute(
        text("SELECT has_table_privilege('monitor_user', 'public.alembic_version', 'SELECT')")
    )
    assert result.scalar() is True


@pytest.mark.asyncio
async def test_monitor_user_cannot_insert_into_public_table(db_session):
    """monitor_user 对 public 表无 INSERT（DB 层强制防误写 GEOFlow 数据）。"""
    result = await db_session.execute(
        text("SELECT has_table_privilege('monitor_user', 'public.alembic_version', 'INSERT')")
    )
    assert result.scalar() is False


@pytest.mark.asyncio
async def test_monitor_user_cannot_update_public_table(db_session):
    """monitor_user 对 public 表无 UPDATE。"""
    result = await db_session.execute(
        text("SELECT has_table_privilege('monitor_user', 'public.alembic_version', 'UPDATE')")
    )
    assert result.scalar() is False


@pytest.mark.asyncio
async def test_monitor_user_cannot_delete_public_table(db_session):
    """monitor_user 对 public 表无 DELETE。"""
    result = await db_session.execute(
        text("SELECT has_table_privilege('monitor_user', 'public.alembic_version', 'DELETE')")
    )
    assert result.scalar() is False


# --------------------------------------------------------------------------- #
# 4. monitor schema：USAGE + 表 SELECT/INSERT（读写自己的数据）                #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_monitor_user_has_usage_on_monitor_schema(db_session):
    """monitor_user 对 monitor schema 有 USAGE。"""
    result = await db_session.execute(
        text("SELECT has_schema_privilege('monitor_user', 'monitor', 'USAGE')")
    )
    assert result.scalar() is True


@pytest.mark.asyncio
async def test_monitor_user_can_select_monitor_table(db_session):
    """monitor_user 对 monitor 表有 SELECT。"""
    result = await db_session.execute(
        text("SELECT has_table_privilege('monitor_user', 'monitor.clients', 'SELECT')")
    )
    assert result.scalar() is True


@pytest.mark.asyncio
async def test_monitor_user_can_insert_monitor_table(db_session):
    """monitor_user 对 monitor 表有 INSERT（读写监测系统自己的数据）。"""
    result = await db_session.execute(
        text("SELECT has_table_privilege('monitor_user', 'monitor.clients', 'INSERT')")
    )
    assert result.scalar() is True


@pytest.mark.asyncio
async def test_monitor_user_cannot_create_in_monitor_schema(db_session):
    """monitor_user 对 monitor schema 无 CREATE（DDL 留给 alembic/geo_user）。"""
    result = await db_session.execute(
        text("SELECT has_schema_privilege('monitor_user', 'monitor', 'CREATE')")
    )
    assert result.scalar() is False


# --------------------------------------------------------------------------- #
# 5. ALTER DEFAULT PRIVILEGES：geo_user 新建 public 表自动授予 SELECT          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_default_privileges_grant_select_on_new_public_table(db_session):
    """ALTER DEFAULT PRIVILEGES 生效：geo_user 新建 public 表自动授予 monitor_user SELECT。

    验证未来 GEOFlow migration 新建的表也会自动只读可访问，无需手动 GRANT。
    """
    await db_session.execute(text("DROP TABLE IF EXISTS public._test_default_priv"))
    await db_session.execute(text("CREATE TABLE public._test_default_priv (id int)"))
    await db_session.commit()
    try:
        result = await db_session.execute(
            text("SELECT has_table_privilege('monitor_user', 'public._test_default_priv', 'SELECT')")
        )
        assert result.scalar() is True, "新 public 表未自动授予 SELECT（DEFAULT PRIVILEGES 未生效？）"
    finally:
        # rollback 防 has_table_privilege 抛错导致事务中止，确保 DROP 能执行
        await db_session.rollback()
        await db_session.execute(text("DROP TABLE IF EXISTS public._test_default_priv"))
        await db_session.commit()


@pytest.mark.asyncio
async def test_default_privileges_do_not_grant_insert_on_new_public_table(db_session):
    """新 public 表自动授权仅限 SELECT，不含 INSERT（保持只读语义）。"""
    await db_session.execute(text("DROP TABLE IF EXISTS public._test_default_priv"))
    await db_session.execute(text("CREATE TABLE public._test_default_priv (id int)"))
    await db_session.commit()
    try:
        result = await db_session.execute(
            text("SELECT has_table_privilege('monitor_user', 'public._test_default_priv', 'INSERT')")
        )
        assert result.scalar() is False, "新 public 表不应自动授予 INSERT"
    finally:
        await db_session.rollback()
        await db_session.execute(text("DROP TABLE IF EXISTS public._test_default_priv"))
        await db_session.commit()
