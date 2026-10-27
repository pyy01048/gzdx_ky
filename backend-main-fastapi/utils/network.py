# -*- coding: utf-8 -*-
"""局域网访问支持：算出可用的访问地址，供手机/平板打开。

场景：把电脑当服务器，手机连同一 WiFi 后访问 `http://<电脑IP>:8000`
整理错题、拍照 OCR。这里负责把"该用哪个地址"算准，避免用户猜 IP。
"""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import sys
from typing import Any


def _iter_candidates() -> list[tuple[str, str]]:
    """返回 [(ip, 来源)] —— 本机所有可能的局域网 IPv4。"""
    out: list[tuple[str, str]] = []

    # 方式 1：UDP "连接" 外部地址（不发包），拿默认出口网卡的 IP
    # 这是最可靠的方法：多网卡时能拿到实际路由使用的那个
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                out.append((ip, "默认路由"))
        finally:
            s.close()
    except Exception:
        pass

    # 方式 2：主机名解析
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                out.append((ip, "主机名"))
    except Exception:
        pass

    # 方式 3：解析 ipconfig（Windows）
    if sys.platform == "win32":
        try:
            r = subprocess.run(["ipconfig"], capture_output=True, text=True,
                               timeout=10, errors="ignore")
            import re
            for m in re.finditer(r"IPv4[^:]*:\s*([0-9.]+)", r.stdout):
                out.append((m.group(1), "ipconfig"))
        except Exception:
            pass

    # 去重并只保留私有网段
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for ip, src in out:
        if ip in seen:
            continue
        seen.add(ip)
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_private and not addr.is_loopback and not addr.is_link_local:
            result.append((ip, src))
    return result


def get_lan_ip() -> str | None:
    """返回最可能的局域网 IP（取默认路由那个）。"""
    cands = _iter_candidates()
    if not cands:
        return None
    # 优先 192.168.x / 10.x，其次 172.16-31.x
    for ip, _ in cands:
        if ip.startswith("192.168."):
            return ip
    for ip, _ in cands:
        if ip.startswith("10."):
            return ip
    return cands[0][0]


def get_all_ips() -> list[dict]:
    """返回所有候选局域网地址（多网卡时让用户自己选）。"""
    return [{"ip": ip, "source": src} for ip, src in _iter_candidates()]


def _qr_svg_data_uri(text: str) -> str | None:
    """把 URL 编成二维码 SVG（data URI），手机扫码直接打开。

    没有二维码库就返回 None —— 不引入硬依赖，前端自行降级为显示网址。
    """
    try:
        import qrcode  # type: ignore
        import qrcode.image.svg  # type: ignore
        import io
        import base64

        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(text, image_factory=factory, box_size=10, border=2)
        buf = io.BytesIO()
        img.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{b64}"
    except Exception:
        return None


def get_access_info(*, port: int | None = None, auth_enabled: bool = False) -> dict[str, Any]:
    """汇总访问信息：本机地址、局域网地址、二维码、注意事项。"""
    port = port or int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    lan_ip = get_lan_ip()

    local_url = f"http://127.0.0.1:{port}"
    lan_url = f"http://{lan_ip}:{port}" if lan_ip else None

    # 是否真的对外可访问：监听 0.0.0.0 或 具体局域网 IP 才算
    exposed = host not in ("127.0.0.1", "localhost")

    tips: list[str] = []
    if not exposed:
        tips.append(
            f"当前监听 {host}，**仅本机可访问**。"
            "要让手机访问，请把 backend-main-fastapi/.env 里的 HOST 改成 0.0.0.0 后重启。"
        )
    if exposed and not auth_enabled:
        tips.append(
            "已开放局域网访问但**未启用登录**：同一 WiFi 下任何设备都能打开。"
        )
    if lan_ip and lan_ip.startswith("169.254."):
        tips.append("检测到链路本地地址，可能没连上 WiFi。")
    tips.append("手机需与本电脑连同一个 WiFi；公司/校园网可能禁止设备互访。")
    if exposed and lan_ip and os.getenv("FIREWALL_HINT", "1") == "1":
        tips.append(
            "若手机打不开，多半是 Windows 防火墙拦了："
            f'以管理员运行 netsh advfirewall firewall add rule name="KaoyanPlatform" '
            f"dir=in action=allow protocol=TCP localport={port}"
        )

    return {
        "host": host,
        "port": port,
        "exposed": exposed,
        "lan_ip": lan_ip,
        "lan_url": lan_url,
        "local_url": local_url,
        "all_ips": get_all_ips(),
        "auth_enabled": auth_enabled,
        "qr_svg": _qr_svg_data_uri(lan_url) if (lan_url and exposed) else None,
        "tips": tips,
    }
