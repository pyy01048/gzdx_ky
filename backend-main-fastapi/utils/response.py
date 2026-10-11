"""
统一API响应工具
- 统一分页响应格式
- 统一成功/错误响应
- 字段命名自动转换（snake_case ↔ camelCase）
"""
from typing import Any, List, Optional, TypeVar, Generic
from fastapi.encoders import jsonable_encoder
import re


T = TypeVar("T")


class PaginatedResponse(Generic[T]):
    """分页响应包装器"""
    def __init__(self, items: List[T], total: int, page: int = 1, page_size: int = 20):
        self.items = items
        self.total = total
        self.page = page
        self.page_size = page_size
        self.total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

    def dict(self) -> dict:
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
        }


def paginate_query(query, page: int = 1, page_size: int = 20, max_page_size: int = 500) -> PaginatedResponse:
    """
    对 SQLAlchemy 查询进行分页。

    Args:
        query: SQLAlchemy 查询对象
        page: 页码（从1开始）
        page_size: 每页数量
        max_page_size: 最大每页数量（防止一次拉太多）

    Returns:
        PaginatedResponse 对象
    """
    # 参数校验
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), max_page_size))

    # 总数
    total = query.count()

    # 分页
    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()

    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size)


def success_response(data: Any = None, message: str = "success") -> dict:
    """统一成功响应"""
    return {
        "success": True,
        "message": message,
        "data": data,
    }


def error_response(code: str, message: str, detail: Any = None) -> dict:
    """统一错误响应"""
    result = {
        "success": False,
        "code": code,
        "message": message,
    }
    if detail is not None:
        result["detail"] = detail
    return result


# --------------------------------------------------------------------------- #
# 字段命名转换（snake_case ↔ camelCase）
# --------------------------------------------------------------------------- #

def _snake_to_camel(name: str) -> str:
    """snake_case 转 camelCase"""
    components = name.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def _camel_to_snake(name: str) -> str:
    """camelCase 转 snake_case"""
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def convert_dict_keys(data: Any, converter) -> Any:
    """递归转换字典的键名"""
    if isinstance(data, dict):
        return {converter(k): convert_dict_keys(v, converter) for k, v in data.items()}
    elif isinstance(data, list):
        return [convert_dict_keys(item, converter) for item in data]
    else:
        return data


def to_camel(data: Any) -> Any:
    """将数据中的 snake_case 键转为 camelCase（用于返回给前端）"""
    return convert_dict_keys(data, _snake_to_camel)


def to_snake(data: Any) -> Any:
    """将数据中的 camelCase 键转为 snake_case（用于接收前端数据）"""
    return convert_dict_keys(data, _camel_to_snake)
