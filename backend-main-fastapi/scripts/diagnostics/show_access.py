# -*- coding: utf-8 -*-
"""在控制台打印局域网访问地址与二维码，手机扫码即可打开。

由 start-lan.bat 调用；也可单独运行：
    python show_access.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.network import get_access_info  # noqa: E402
from utils.auth import AUTH_ENABLED  # noqa: E402


def main() -> int:
    info = get_access_info(auth_enabled=bool(AUTH_ENABLED))

    print("=" * 62)
    print("  手机 / 平板 访问入口")
    print("=" * 62)
    print(f"  本机地址 : {info['local_url']}")
    if info["exposed"] and info["lan_url"]:
        print(f"  局域网   : {info['lan_url']}")
    elif info["lan_ip"]:
        print(f"  局域网   : 未开放（HOST={info['host']}）")
        print(f"             把 .env 的 HOST 改成 0.0.0.0 即可，IP 为 {info['lan_ip']}")
    print(f"  访问密码 : {'已开启' if info['auth_enabled'] else '未设置（建议设 APP_PASSWORD）'}")

    if len(info["all_ips"]) > 1:
        print("\n  检测到多个网卡，若上面的地址不通可试：")
        for item in info["all_ips"]:
            print(f"     http://{item['ip']}:{info['port']}   ({item['source']})")

    print("\n  提示：")
    for t in info["tips"]:
        print(f"    · {t.replace('**', '')}")

    # 控制台二维码
    if info["exposed"] and info["lan_url"]:
        try:
            import qrcode

            qr = qrcode.QRCode(border=1)
            qr.add_data(info["lan_url"])
            qr.make(fit=True)
            print("\n  用手机相机/微信扫下面这个码直接打开：\n")
            qr.print_ascii(invert=True)
        except Exception as e:
            print(f"\n  （二维码生成失败：{e}；直接手输上面的网址即可）")

    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
