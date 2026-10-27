"""运维自检：外部算力节点在线灯（/api/admin/ 前缀由 access_policy 限管理员）。"""

from fastapi import APIRouter, Depends

from utils.compute_nodes import probe_nodes
from utils.security import require_admin

router = APIRouter(prefix="/api/admin/system", tags=["admin-system"], dependencies=[Depends(require_admin)])


@router.get("/compute-nodes")
def compute_nodes():
    nodes = probe_nodes()
    return {"nodes": nodes, "online": sum(n["status"] == "online" for n in nodes), "total": len(nodes)}
