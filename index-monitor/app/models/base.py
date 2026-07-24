# index-monitor/app/models/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """监测系统模型基类。

    所有继承 ``Base`` 的模型表都属于 monitor schema（通过 ``monitor_table_args``
    在每个模型的 ``__table_args__`` 中显式声明）。
    """
    pass


def monitor_table_args(*args):
    """返回包含 ``schema='monitor'`` 的 ``__table_args__``。

    用法：

    - 无其他表级参数时：``__table_args__ = monitor_table_args()``
      返回 ``{"schema": "monitor"}``（SQLAlchemy 接受裸 dict 作为 ``__table_args__``）。
    - 有其他表级参数（如 ``UniqueConstraint``）时：
      ``__table_args__ = monitor_table_args(UniqueConstraint(...))``
      返回 ``(UniqueConstraint(...), {"schema": "monitor"})``，schema dict 始终在末尾。
    """
    if args:
        return (*args, {"schema": "monitor"})
    return {"schema": "monitor"}
