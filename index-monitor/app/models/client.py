# index-monitor/app/models/client.py
from sqlalchemy import Column, String, DateTime, UniqueConstraint
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ClientSite(Base):
    __tablename__ = "client_sites"
    # 控制者裁定 2：DB 有 UNIQUE(client_id, domain)，模型须声明同名约束
    # schema dict 由 monitor_table_args 自动附加在元组末尾
    __table_args__ = monitor_table_args(
        UniqueConstraint("client_id", "domain", name="client_sites_client_id_domain_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    site_name = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=False)
    site_type = Column(String(32), nullable=False)
    wordpress_api_url = Column(String(512))
    wordpress_api_token = Column(String(255))
    status = Column(String(32), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
