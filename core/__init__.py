"""课表查询核心库。

由 AstrBot 插件与本地工具共用。
"""

__version__ = "0.3.2"

from .schedule import Timetable  # noqa: F401

__all__ = ["Timetable", "__version__"]
