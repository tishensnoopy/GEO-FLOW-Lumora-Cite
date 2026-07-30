# index-monitor/tests/unit/test_client_site_domain_unique.py
"""ClientSite domain UNIQUE 约束端到端测试。

设计文档第 4.1 节：一个 domain 只属于一个客户。

Task 5 的 test_client_lifecycle_fields.py 已通过 inspector 验证约束存在；
本测试进一步验证约束实际生效——插入重复 domain 必须抛 IntegrityError。

裁定（Plan 2 M1 Task 6）：避免与 Task 5 冗余，只写一个端到端行为测试。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.client import ClientSite


def test_client_site_domain_unique_enforced():
    """插入重复 domain 必须抛 IntegrityError（约束实际生效，非仅 inspector 报告）。

    裁定 3：DB URL 用 settings.POSTGRES_* 动态构造，不硬编码本地凭据。
    裁定：测试前后均清理测试数据，try/finally 确保 engine.dispose()。
    """
    sync_url = (
        f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    )
    engine = create_engine(sync_url)
    Session = sessionmaker(engine)
    session = Session()

    test_domain = "integrity-test-domain.example.com"
    try:
        # 测试前清理：防残留
        session.query(ClientSite).filter_by(domain=test_domain).delete()
        session.commit()

        # 插入第一条（成功）
        site1 = ClientSite(
            client_id="integrity_test_client_1",
            site_name="test site 1",
            domain=test_domain,
            site_type="official",
        )
        session.add(site1)
        session.commit()

        # 插入第二条（相同 domain，不同 client_id）→ 必须抛 IntegrityError
        # 触发的是 domain 单列 UNIQUE（client_sites_domain_unique_key），
        # 而非 (client_id, domain) 复合 UNIQUE
        site2 = ClientSite(
            client_id="integrity_test_client_2",
            site_name="test site 2",
            domain=test_domain,
            site_type="official",
        )
        session.add(site2)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()  # 回滚失败的事务，恢复 session 可用状态

    finally:
        # 测试后清理：删除第一条测试记录，避免污染 DB
        session.query(ClientSite).filter_by(domain=test_domain).delete()
        session.commit()
        session.close()
        engine.dispose()
