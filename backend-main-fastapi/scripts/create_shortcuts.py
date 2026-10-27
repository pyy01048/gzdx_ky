# -*- coding: utf-8 -*-
"""在桌面创建「考研学习平台」快捷方式（可选同时创建几个常用模式的）。

用法：
    python create_shortcuts.py            # 创建主快捷方式（启动器）
    python create_shortcuts.py --all      # 主 + 本机 + 局域网 + 停止
    python create_shortcuts.py --remove   # 删除由本脚本创建的快捷方式
"""

import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON = os.path.join(ROOT, "assets", "app_icon.ico")


def _desktop_dir() -> str:
    """取真实桌面路径。

    注意：桌面**不一定**在 `%USERPROFILE%\\Desktop` ——
    本机就被重定向到了 `D:\\桌面`。所以优先问 Windows 自己的 API，
    再退回环境变量与常见候选。
    """
    # 1. 让 PowerShell 走 .NET 的 Shell API（最可靠）
    try:
        import subprocess
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, text=True, timeout=30, errors="ignore",
        )
        p = r.stdout.strip()
        if p and os.path.isdir(p):
            return p
    except Exception:
        pass

    # 2. 注册表里的 User Shell Folders（可能含 %USERPROFILE% 变量）
    try:
        import subprocess
        r = subprocess.run(
            ["reg", "query",
             r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
             "/v", "Desktop"],
            capture_output=True, text=True, timeout=30, errors="ignore",
        )
        for line in r.stdout.splitlines():
            if "Desktop" in line and "REG_" in line:
                p = line.split("REG_")[1].split(None, 1)[1].strip()
                p = os.path.expandvars(p)
                if os.path.isdir(p):
                    return p
    except Exception:
        pass

    # 3. 常见候选
    for cand in (
        os.path.join(os.path.expanduser("~"), "Desktop"),
        os.path.join(os.path.expanduser("~"), "桌面"),
        os.path.join(os.environ.get("OneDrive", ""), "Desktop"),
        os.path.join(os.environ.get("OneDrive", ""), "桌面"),
        r"D:\桌面",
    ):
        if cand and os.path.isdir(cand):
            return cand
    return ""


DESKTOP = _desktop_dir()

#: (快捷方式名, 目标 bat, 描述)
SHORTCUTS = {
    "main": ("考研学习平台", "启动.bat", "启动器：本机 / 局域网 / 后台 / 停止"),
    "local": ("考研平台·本机", "启动-本机.bat", "仅本机访问，最安全"),
    "lan": ("考研平台·局域网", "启动-局域网.bat", "手机可访问，显示二维码"),
    "stop": ("考研平台·停止", "停止.bat", "关闭正在运行的服务"),
}


def _make(name: str, target: str, desc: str) -> str:
    """用 PowerShell 创建 .lnk（避免依赖 pywin32）。"""
    lnk = os.path.join(DESKTOP, f"{name}.lnk")
    target_path = os.path.join(ROOT, target)
    icon = ICON if os.path.exists(ICON) else target_path

    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{lnk}')
$sc.TargetPath = '{target_path}'
$sc.WorkingDirectory = '{ROOT}'
$sc.Description = '{desc}'
$sc.IconLocation = '{icon}'
$sc.WindowStyle = 1
$sc.Save()
"""
    import subprocess
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=60, errors="ignore")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200] or "PowerShell 执行失败")
    return lnk


def _remove() -> int:
    n = 0
    for key, (name, *_rest) in SHORTCUTS.items():
        lnk = os.path.join(DESKTOP, f"{name}.lnk")
        if os.path.exists(lnk):
            os.remove(lnk)
            print(f"  已删除 {lnk}")
            n += 1
    print(f"  共删除 {n} 个")
    return 0


def main() -> int:
    if "--remove" in sys.argv:
        return _remove()

    if not DESKTOP or not os.path.isdir(DESKTOP):
        print("  找不到桌面目录。可手动把「启动.bat」发送到桌面快捷方式。")
        print(f"  项目位置: {ROOT}")
        return 1

    want_all = "--all" in sys.argv
    keys = list(SHORTCUTS) if want_all else ["main"]

    print(f"  桌面目录: {DESKTOP}")
    if os.path.exists(ICON):
        print(f"  图标: {ICON}")
    else:
        print("  提示: assets/app_icon.ico 不存在，将使用默认图标")

    ok = 0
    for k in keys:
        name, target, desc = SHORTCUTS[k]
        bat = os.path.join(ROOT, target)
        if not os.path.exists(bat):
            print(f"  [跳过] {name} —— 找不到 {target}")
            continue
        try:
            lnk = _make(name, target, desc)
            print(f"  [OK] {lnk}")
            ok += 1
        except Exception as e:
            print(f"  [失败] {name}: {e}")

    print(f"\n  共创建 {ok} 个快捷方式")
    if ok:
        print("  以后直接双击桌面图标即可启动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
