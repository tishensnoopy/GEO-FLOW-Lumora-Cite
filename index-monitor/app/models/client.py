# index-monitor/app/models/client.py
from sqlalchemy import Column, String, DateTime, Boolean, Date, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.models.base import Base, monitor_table_args
import uuid


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = monitor_table_args()

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), unique=True, nullable=False)
    username = Column(String(128), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255))
    phone = Column(String(32))
    company_name = Column(String(255))
    status = Column(String(32), default="active")
    # 设计文档第 6.1 节：客户生命周期联系信息
    contact_name = Column(String(128), nullable=True)
    contact_email = Column(String(255), nullable=True, unique=True)
    contact_phone = Column(String(32), nullable=True)
    # 服务期管理：合同起止日期
    service_start_date = Column(Date, nullable=True)
    service_end_date = Column(Date, nullable=True)
    # 设计文档第 21.6 节：合规留痕（首次同意用户协议 / 隐私政策时间）
    agreed_terms_at = Column(DateTime(timezone=True), nullable=True)
    agreed_privacy_at = Column(DateTime(timezone=True), nullable=True)
    # 登录留痕
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ClientSite(Base):
    __tablename__ = "client_sites"
    # 控制者裁定 2：DB 有 UNIQUE(client_id, domain)，模型须声明同名约束
    # schema dict 由 monitor_table_args 自动附加在元组末尾
    # Task 5：新增 domain 单列 UNIQUE（client_sites_domain_unique_key，迁移 007）
    __table_args__ = monitor_table_args(
        UniqueConstraint("client_id", "domain", name="client_sites_client_id_domain_key"),
        UniqueConstraint("domain", name="client_sites_domain_unique_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    site_name = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=False)
    # 裁定 2：保留 nullable=False（DB 中 site_type 仍 NOT NULL，迁移 007 不改 nullable），
    # 同时加 default="official" 作为应用层默认值
    site_type = Column(String(32), nullable=False, default="official")
    # 设计文档第 6.2 节：是否为 WordPress 站点
    has_wordpress = Column(Boolean, default=False)
    wordpress_api_url = Column(String(512))
    wordpress_api_token = Column(String(255))
    status = Column(String(32), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
