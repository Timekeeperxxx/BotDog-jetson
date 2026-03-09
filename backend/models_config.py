"""
配置管理模型。

职责边界：
- 存储系统运行时配置
- 支持热更新的配置项
- 配置变更历史记录
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base

from .database import Base


class SystemConfig(Base):
    """
    系统配置表。

    存储可运行时修改的配置项，用于支持热更新。
    """
    __tablename__ = "system_config"

    config_id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(String(500), nullable=False)
    value_type = Column(String(20), nullable=False)  # 'int', 'float', 'bool', 'string'
    category = Column(String(50), nullable=False)  # 'backend', 'frontend', 'storage'
    description = Column(String(500))
    is_hot_reloadable = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<SystemConfig(key={self.key}, value={self.value}, type={self.value_type})>"

    def to_dict(self):
        """转换为字典。"""
        return {
            "config_id": self.config_id,
            "key": self.key,
            "value": self._parse_value(),
            "value_type": self.value_type,
            "category": self.category,
            "description": self.description,
            "is_hot_reloadable": self.is_hot_reloadable,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def _parse_value(self):
        """根据类型解析值。"""
        if self.value_type == 'int':
            return int(self.value)
        elif self.value_type == 'float':
            return float(self.value)
        elif self.value_type == 'bool':
            return self.value.lower() in ('true', '1', 'yes')
        else:
            return self.value

    @classmethod
    def from_dict(cls, data):
        """从字典创建实例。"""
        return cls(
            key=data['key'],
            value=str(data['value']),
            value_type=data.get('value_type', 'string'),
            category=data.get('category', 'backend'),
            description=data.get('description', ''),
            is_hot_reloadable=data.get('is_hot_reloadable', True),
        )


class ConfigChangeHistory(Base):
    """
    配置变更历史表。

    记录配置项的修改历史，用于审计和回滚。
    """
    __tablename__ = "config_change_history"

    history_id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(100), nullable=False, index=True)
    old_value = Column(String(500))
    new_value = Column(String(500))
    changed_by = Column(String(100))  # 用户名或系统标识
    changed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    reason = Column(String(500))

    def __repr__(self):
        return f"<ConfigChangeHistory(key={self.config_key}, at={self.changed_at})>"

    def to_dict(self):
        """转换为字典。"""
        return {
            "history_id": self.history_id,
            "config_key": self.config_key,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "changed_by": self.changed_by,
            "changed_at": self.changed_at.isoformat() if self.changed_at else None,
            "reason": self.reason,
        }
