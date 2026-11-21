"""院校品牌化回填：校徽 logo + 校门/校园封面图（自托管）。

来源（按优先级）：
  logo  —— 掌上高考校徽库 https://static-data.gaokao.cn/upload/logo/{gid}.jpg
           （gid 由 name.json 全量名单按名称精确匹配，全角/半角括号归一）
  cover —— 1) 院校官网首页 banner/swiper/og:image 实景大图
           2) 掌上高考宣传片封面 upload/svideo/*_thumb.jpg（横版校园画面）
           官网地址缺失时用 info.json 的 school_site 补齐 official_url。

铁律：
  * 默认 dry-run，--apply 才写库；幂等：已有 URL 且本地文件在 → 跳过。
  * 图片一律下载到 data/storage/images/school_{logos,covers}/{id}.{ext}，
    库里只存自托管 /media/images/... 路径，不热链外站。
  * 校验魔数 + 尺寸 + 体积：logo 需近方形 ≥80px；cover 需横版 ≥700px 宽、
    宽高比 ≥1.2、≥30KB（挡掉 AI 招生海报竖图 / 图标 / 二维码 / 错误页）。
  * 抓不到的学校保持 NULL —— 前端首字头像兜底，空态即交付。

用法：
  python scripts/backfill_school_branding.py                 # dry-run 全量
  python scripts/backfill_school_branding.py --apply --limit 30
  python scripts/backfill_school_branding.py --apply --school-id 5
  python scripts/backfill_school_branding.py --apply --workers 8
"""

from __future__ import annotations

import argparse
import io
import json
import re
import struct
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from database import engine  # noqa: E402
from sqlalchemy import text  # noqa: E402

IMG_ROOT = BASE / "data" / "storage" / "images"
LOGO_DIR = IMG_ROOT / "school_logos"
COVER_DIR = IMG_ROOT / "school_covers"
CACHE_DIR = BASE / "data" / "branding_tmp" / "cache"
REPORT = BASE / "data" / "branding_tmp" / "branding_report.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
GAOKAO_NAME = "https://static-data.gaokao.cn/www/2.0/school/name.json"
GAOKAO_INFO = "https://static-data.gaokao.cn/www/2.0/school/{gid}/info.json"
GAOKAO_LOGO = "https://static-data.gaokao.cn/upload/logo/{gid}.jpg"

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


# --------------------------------------------------------------------------- #
# 网络 / 图片校验（纯标准库，不依赖 PIL）
# --------------------------------------------------------------------------- #
def fetch(url: str, timeout: float = 12.0, limit: int = 16_000_000, strict: bool = True) -> bytes | None:
    """strict=True 时超限返回 None：截断的 JPEG 头信息完整、能过 image_meta，
    但落盘就是坏图（实测武大首页大图被 4MB 上限截断）。HTML 抓取传 strict=False 容忍截断。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = resp.read(limit + 1)
            if strict and len(data) > limit:
                return None
            return data[:limit]
    except Exception:
        return None


def image_decodable(data: bytes) -> bool:
    """完整解码校验：image_meta 只读文件头，挡不住下载截断/损坏的图。"""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        im.load()
        return True
    except Exception:
        return False


def image_meta(data: bytes) -> tuple[str, int, int] | None:
    """返回 (ext, width, height)；非 JPEG/PNG/WebP 返回 None。"""
    if not data or len(data) < 64:
        return None
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
                h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                return "jpg", w, h
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return "webp", w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L":
            b0, b1, b2, b3 = data[21:25]
            w = 1 + (((b1 & 0x3F) << 8) | b0)
            h = 1 + (((b3 & 0xF) << 10) | (b2 << 2) | ((b1 & 0xC0) >> 6))
            return "webp", w, h
        if chunk == b"VP8X":
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return "webp", w, h
    return None


def norm_name(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").replace("（", "(").replace("）", ")"))


# --------------------------------------------------------------------------- #
# 官网首页候选图提取
# --------------------------------------------------------------------------- #
class HomepageImages(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cands: list[tuple[int, str]] = []  # (score, url)
        self._seen: set[str] = set()
        self._actx: list[str] | None = None  # 包裹 <a> 的 title/文本：新闻图靠上下文识别

    def _push(self, score: int, url: str | None) -> None:
        if not url:
            return
        url = url.strip()
        if url.startswith(("data:", "javascript:", "#")):
            return
        if url not in self._seen:
            self._seen.add(url)
            self.cands.append((score, url))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self._actx = [a.get("title") or "", a.get("href") or ""]
            return
        if tag == "meta":
            if (a.get("property") or a.get("name") or "") in ("og:image", "twitter:image"):
                self._push(2, a.get("content"))
            return
        if tag == "img":
            src = a.get("src") or a.get("data-src") or a.get("data-original") or a.get("_src")
            hint = " ".join(filter(None, [a.get("class"), a.get("id"), a.get("alt"), src]))
            if self._actx:
                hint += " " + " ".join(self._actx)
            low = hint.lower()
            # 新闻/成果图（团队合影、海报 banner）不是校园实景：硬排除，
            # 实测武大首页轮播首图是课题组合影，纯像素海报检测挡不住
            if POSTER_RE.search(hint):
                return
            score = 0
            if re.search(r"banner|swiper|slide|carousel|focus|flash|轮播|焦点", low):
                score += 3
            if re.search(r"logo|icon|qrcode|erweima|weixin|weibo|badge|foot|ewm", low):
                score -= 4
            if re.search(r"upload|attachment|photo|news|image", low):
                score += 1
            if re.search(r"/news/|xinwen|tzgg|/info/\d", low):
                score -= 2
            self._push(score, src)
            return
        style = a.get("style") or ""
        for m in re.finditer(r"background(?:-image)?\s*:\s*url\(['\"]?([^'\")]+)", style):
            self._push(2, m.group(1))

    def handle_data(self, data):
        if self._actx is not None:
            self._actx.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self._actx = None


def homepage_candidates(home_url: str, html: bytes) -> list[str]:
    try:
        text_html = html.decode("utf-8", errors="replace")
    except Exception:
        return []
    if re.search(r"charset=[\"']?(gb2312|gbk|gb18030)", text_html[:2000], re.I):
        try:
            text_html = html.decode("gb18030", errors="replace")
        except Exception:
            pass
    p = HomepageImages()
    try:
        p.feed(text_html)
    except Exception:
        pass
    ordered = sorted(p.cands, key=lambda t: -t[0])
    urls = []
    for _, u in ordered:
        abs_u = urljoin(home_url, u)
        if abs_u.startswith(("http://", "https://")) and abs_u not in urls:
            urls.append(abs_u)
    return urls[:10]


def pick_cover(home_url: str | None, info: dict | None) -> tuple[bytes, str, str] | None:
    """返回 (bytes, ext, source_label)。"""
    if home_url:
        html = fetch(home_url, timeout=12, limit=1_500_000, strict=False)
        if html and b"<" in html[:200]:
            for u in homepage_candidates(home_url, html):
                data = fetch(u, timeout=10)
                meta = image_meta(data or b"")
                if not meta:
                    continue
                ext, w, h = meta
                if (
                    w >= 700
                    and h > 0
                    and w / h >= 1.2
                    and len(data) >= 30_000
                    and image_decodable(data)
                    and not poster_like(data)
                ):
                    return data, ext, f"homepage:{urlparse(u).netloc}"
    if info:
        thumb = (info.get("video") or {}).get("img_url") or (info.get("video_pc") or {}).get("img_url")
        if thumb:
            data = fetch(thumb.replace("http://", "https://"), timeout=10)
            meta = image_meta(data or b"")
            if meta:
                ext, w, h = meta
                if (
                    w >= 600
                    and h > 0
                    and w / h >= 1.2
                    and len(data) >= 20_000
                    and image_decodable(data)
                    and not poster_like(data)
                ):
                    return data, ext, "gaokao_video_thumb"
    return None


class SceneryLinks(HTMLParser):
    """官网导航里「风光/视觉/影像/图片」类链接：比首页 banner 更可能是纯校园实景。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = "".join(self._text).strip()
            if re.search(
                r"风光|视觉|影像|图片|画廊|校园|校门|摄影|印象|文化|景观|风物|风采|gallery|photo|campus", text, re.I
            ):
                self.links.append((self._href, text))
            self._href = None
            self._text = []


def official_gallery_cover(home_url: str) -> tuple[bytes, str, str] | None:
    html = fetch(home_url, timeout=12, limit=1_500_000, strict=False)
    if not html or b"<" not in html[:200]:
        return None
    p = SceneryLinks()
    try:
        p.feed(html.decode("utf-8", errors="replace"))
    except Exception:
        return None
    host = urlparse(home_url).netloc
    tried = 0
    for href, _text in p.links:
        abs_u = urljoin(home_url, href)
        if urlparse(abs_u).netloc != host or not abs_u.startswith(("http://", "https://")):
            continue
        tried += 1
        if tried > 2:
            break
        page = fetch(abs_u, timeout=12, limit=1_500_000, strict=False)
        if not page:
            continue
        for u in homepage_candidates(abs_u, page):
            data = fetch(u, timeout=10)
            meta = image_meta(data or b"")
            if not meta:
                continue
            ext, w, h = meta
            if (
                w >= 700
                and h > 0
                and w / h >= 1.2
                and len(data) >= 30_000
                and image_decodable(data)
                and not poster_like(data)
            ):
                return data, ext, f"official_gallery:{host}"
    return None


# --------------------------------------------------------------------------- #
# Bing 图片搜索：校门 / 校园实景（标题相关度过滤，挡掉无关图与水印图库）
# --------------------------------------------------------------------------- #
BING_IMG = "https://cn.bing.com/images/search?q={q}&form=HDRSC2&first=1"
STOCK_HOSTS = (
    "699pic",
    "nximg",
    "nipic",
    "588ku",
    "photophoto",
    "vcg.com",
    "gettyimages",
    "shutterstock",
    "quanjing",
    "hellorf",
    "zcool",
    "tuchong",
    "ibaotu",
    "51miz",
    "ooopic",
    "sucai",
    "shetu66",
    "58pic",
    "huitu",
    "redocn",
    "千库",
    "千图",
    "包图",
    "摄图",
    "图虫",
    "视觉中国",
)
# 省/市名：简称变体若落进这里会把城市风光误判成该校实景（北京大学→北京 实测踩坑）
REGION_WORDS = frozenset(
    (
        "北京",
        "上海",
        "天津",
        "重庆",
        "河北",
        "山西",
        "辽宁",
        "吉林",
        "黑龙江",
        "江苏",
        "浙江",
        "安徽",
        "福建",
        "江西",
        "山东",
        "河南",
        "湖北",
        "湖南",
        "广东",
        "海南",
        "四川",
        "贵州",
        "云南",
        "陕西",
        "甘肃",
        "青海",
        "台湾",
        "内蒙古",
        "广西",
        "西藏",
        "宁夏",
        "新疆",
        "广州",
        "南京",
        "武汉",
        "成都",
        "西安",
        "杭州",
        "长沙",
        "郑州",
        "济南",
        "青岛",
        "大连",
        "沈阳",
        "哈尔滨",
        "长春",
        "石家庄",
        "太原",
        "合肥",
        "南昌",
        "福州",
        "厦门",
        "昆明",
        "贵阳",
        "南宁",
        "海口",
        "兰州",
        "西宁",
        "银川",
        "乌鲁木齐",
        "拉萨",
        "呼和浩特",
        "苏州",
        "无锡",
        "宁波",
        "温州",
        "东莞",
        "佛山",
        "珠海",
        "桂林",
        "三亚",
    )
)


def name_variants(name: str) -> list[str]:
    """全称 + 安全简称。 Bing 对全称长查询有时返回无关缓存页，
    简称（北大/浙大/清华）能命中真实图片簇；简称不得是省/市名。"""
    out = [name]
    if name.endswith("大学") and len(name) >= 4:
        core = name[:-2]
        if len(core) >= 2 and core not in REGION_WORDS:
            out.append(core)
        first = name[0] + "大"
        if first not in out:
            out.append(first)
    elif name.endswith("学院") and len(name) >= 4:
        core = name[:-2]
        if len(core) >= 2 and core not in REGION_WORDS:
            out.append(core)
    return out


GOOD_HOSTS = ("bkimg.cdn.bcebos.com", "c-ctrip.com", "qunarzz.com")
# 标题里出现这些地标时，图大概率是地标本身而不是学校（北大→故宫 实测踩坑）
LANDMARKS = (
    "故宫",
    "圆明园",
    "颐和园",
    "天坛",
    "长城",
    "外滩",
    "东方明珠",
    "西湖",
    "兵马俑",
    "布达拉宫",
    "黄鹤楼",
    "滕王阁",
)
# 新闻/成果海报不是校园实景（北大首页「超冷量子气体」海报 实测踩坑）：
# 官网域名也不豁免，标题必须真的是校门/校园风光
POSTER_RE = re.compile(
    r"团队|成果|发表|期刊|荣获|获批|讲座|报告|通知|公告|招生|招聘|党建|会议|论坛|获奖|表彰|典礼|仪式"
    r"|精神|贯彻|落实|喜迎|庆祝|华诞|贺信|运动会|迎新|军训|开学|毕业"
)


def _clean_img_url(u: str) -> str:
    # 百科 smart 缩略参数会把原图限到 378px：剥掉处理段取原图
    m = re.match(r"(https://bkimg\.cdn\.bcebos\.com)/(?:smart|pic)/([0-9a-f]+)", u)
    if m:
        return f"{m.group(1)}/pic/{m.group(2)}"
    return u


def normalize_cover(data: bytes, ext: str) -> tuple[bytes | None, str]:
    """封面统一限宽 1600px：百科/官网原图可达上亿像素，2C2G 服务器存不起也传不动。"""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        w, h = im.size
        if max(w, h) <= 1600:
            return data, ext
        ratio = 1600 / max(w, h)
        im = im.resize((max(1, round(w * ratio)), max(1, round(h * ratio))), Image.LANCZOS)
        buf = io.BytesIO()
        if ext == "png":
            im.convert("RGB").save(buf, format="PNG", optimize=True)
        else:
            im.convert("RGB").save(buf, format="JPEG", quality=85, optimize=True)
            ext = "jpg"
        return buf.getvalue(), ext
    except Exception:
        # 解码失败绝不落盘：截断/损坏图宁可空缺（前端有首字兜底），不能展示坏图
        return None, ext


def poster_like(data: bytes) -> bool:
    """新闻/成果海报检测：单一高饱和色相占绝对主导（实测海报 0.76/0.83，
    真实校门/校园照 ≤0.24/0.45）。PIL 缺失时保守返回 False。"""
    try:
        import collections
        import colorsys

        from PIL import Image

        im = Image.open(io.BytesIO(data)).convert("RGB").resize((96, 96))
        px = list(im.getdata())
        hues = collections.Counter()
        sat_n = 0
        for r, g, b in px:
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if s > 0.35 and v > 0.25:
                sat_n += 1
                hues[int(h * 12) % 12] += 1
        if not sat_n:
            return False
        dom = hues.most_common(1)[0][1] / len(px)
        return dom >= 0.5 and sat_n / len(px) >= 0.6
    except Exception:
        return False


def bing_candidates(name: str, query_suffix: str, query_name: str | None = None) -> list[tuple[int, str]]:
    from urllib.parse import quote

    q = quote(f"{query_name or name} {query_suffix}")
    raw = fetch(BING_IMG.format(q=q), timeout=15, limit=2_000_000)
    if not raw:
        return []
    html_s = raw.decode("utf-8", errors="replace")
    variants = name_variants(name)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for m in re.finditer(r'm="([^"]+)"', html_s):
        try:
            d = json.loads(__import__("html").unescape(m.group(1)))
        except Exception:
            continue
        title, murl = d.get("t") or "", d.get("murl") or ""
        if not murl.startswith("http") or not any(v in title for v in variants):
            continue
        host = urlparse(murl).netloc.lower()
        if any(s in host for s in STOCK_HOSTS):
            continue
        if any(lm in title for lm in LANDMARKS) and not any(lm in name for lm in LANDMARKS):
            continue
        if POSTER_RE.search(title):
            continue
        is_edu = host.endswith(".edu.cn") or host.endswith(".ac.cn")
        has_scene = bool(
            re.search(
                r"校门|大门|二校门|西门|东门|南门|北门|正门|牌坊|牌楼|gate|校园|风光|全景|景色|风景|航拍|campus", title
            )
        )
        # 任何来源都要求标题明确是校门/校园实景：官网新闻海报同样挡掉
        if not has_scene:
            continue
        score = 0
        if re.search(r"校门|大门|二校门|西门|东门|南门|北门|正门|牌坊|牌楼|gate", title):
            score += 4
        if re.search(r"校园|风光|全景|景色|风景|航拍|campus", title):
            score += 2
        if is_edu:
            score += 6
        if "bkimg.cdn.bcebos.com" in host or "qhimg.com" in host:
            score += 3  # 百科词条图（百度/360）：人工 curated，优先于游记图
        elif any(g in host for g in GOOD_HOSTS):
            score += 2
        if re.search(r"校徽|logo|标志", title):
            score -= 5
        u = _clean_img_url(murl)
        if u not in seen:
            seen.add(u)
            scored.append((score, u))
    scored.sort(key=lambda t: -t[0])
    return scored[:6]


def bing_cover(name: str) -> tuple[bytes, str, str] | None:
    for suffix in ("校门", "西门", "牌坊", "校园风光"):
        for qn in name_variants(name):
            for score, u in bing_candidates(name, suffix, qn):
                if score < 4:
                    continue
                data = fetch(u, timeout=10)
                meta = image_meta(data or b"")
                if not meta:
                    continue
                ext, w, h = meta
                # 搜索源放宽到近方形：校门照常见 1:1，object-fit 裁切安全；
                # 首页 banner 仍要求横幅（见 pick_cover）
                if (
                    w >= 700
                    and h > 0
                    and w / h >= 0.9
                    and len(data) >= 30_000
                    and image_decodable(data)
                    and not poster_like(data)
                ):
                    return data, ext, f"bing:{urlparse(u).netloc}:{suffix}"
    return None


# --------------------------------------------------------------------------- #
# 单校处理（线程内只做网络 + 落盘，不碰 DB）
# --------------------------------------------------------------------------- #
def process_school(row: dict, name_map: dict, args) -> dict:
    sid, name = row["id"], row["name"]
    out = {"id": sid, "name": name, "logo": None, "cover": None, "official_url": None, "note": []}
    gid = name_map.get(norm_name(name))
    if gid is None:
        out["note"].append("gaokao_name_unmatched")

    info = None
    if gid is not None:
        cache_f = CACHE_DIR / f"info_{gid}.json"
        if cache_f.exists():
            try:
                info = json.loads(cache_f.read_text(encoding="utf-8"))
            except Exception:
                info = None
        if info is None:
            raw = fetch(GAOKAO_INFO.format(gid=gid), timeout=10)
            if raw:
                try:
                    info = json.loads(raw.decode("utf-8"))["data"]
                    cache_f.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    info = None

    # ---- logo ----
    logo_done = row["logo_url"] and (IMG_ROOT / row["logo_url"].replace("/media/images/", "", 1)).exists()
    if not logo_done and gid is not None and not args.skip_logos:
        data = fetch(GAOKAO_LOGO.format(gid=gid), timeout=10)
        meta = image_meta(data or b"")
        if meta:
            ext, w, h = meta
            if w >= 80 and h >= 80 and 0.7 <= w / h <= 1.4 and len(data) >= 1500:
                LOGO_DIR.mkdir(parents=True, exist_ok=True)
                (LOGO_DIR / f"{sid}.{ext}").write_bytes(data)
                out["logo"] = f"/media/images/school_logos/{sid}.{ext}"
        if not out["logo"]:
            out["note"].append("logo_invalid_or_missing")
    elif logo_done:
        out["note"].append("logo_keep")

    # ---- official_url 补齐 ----
    site = (info or {}).get("school_site") or (info or {}).get("site")
    if not row["official_url"] and site and site.startswith("http"):
        out["official_url"] = site
    home = row["official_url"] or site

    # ---- cover ----
    cover_path = (IMG_ROOT / row["cover_url"].replace("/media/images/", "", 1)) if row["cover_url"] else None
    cover_exists = bool(cover_path and cover_path.exists())
    existing_poster = False
    # DB 指向不存在的文件（悬空指针）与坏图同罪：前端会 404
    existing_corrupt = bool(row["cover_url"]) and not cover_exists
    if cover_exists and args.redo_covers:
        if args.force_cover:
            existing_poster = True
        else:
            try:
                raw = cover_path.read_bytes()
                # 损坏/截断的旧图与海报同罪：必须重选，不能被 cover_keep 永久保护
                existing_corrupt = not image_decodable(raw)
                existing_poster = existing_corrupt or poster_like(raw)
            except Exception:
                existing_corrupt = True
                existing_poster = True
    cover_done = cover_exists and not args.redo_covers
    if cover_exists and args.redo_covers and not existing_poster:
        # 重跑只体检海报嫌疑图：真实景保持不动，也不发网络请求
        out["note"].append("cover_keep")
        return out
    if not cover_done and not args.skip_covers:
        time.sleep(0.3 + (sid % 5) * 0.1)  # 搜索源礼貌间隔
        got = bing_cover(name)
        if not got and home and home.startswith("http"):
            got = official_gallery_cover(home)
        # 重跑模式只允许「搜索源/官网风光页」替换已有封面：
        # 首页 banner 常是新闻海报，搜索源瞬时失败时不得把旧图降级成海报；
        # 例外：--force-cover 人工重选、旧图已损坏（坏图比任何合格兜底都差）
        if not got and (args.force_cover or existing_corrupt or not (args.redo_covers and cover_exists)):
            got = pick_cover(home if home and home.startswith("http") else None, info)
        if got:
            data, ext, src = got
            data, ext = normalize_cover(data, ext)
        if got and data:
            COVER_DIR.mkdir(parents=True, exist_ok=True)
            (COVER_DIR / f"{sid}.{ext}").write_bytes(data)
            # 换扩展重跑时清掉同校旧文件，避免孤儿图占用存储
            for old in COVER_DIR.glob(f"{sid}.*"):
                if old.name != f"{sid}.{ext}":
                    old.unlink(missing_ok=True)
            out["cover"] = f"/media/images/school_covers/{sid}.{ext}"
            out["note"].append(f"cover_src={src}")
        else:
            if existing_corrupt:
                # 全链也救不回的坏图/悬空指针：删文件 + 置空 DB，前端走首字/渐变兜底，
                # 绝不能让浏览器展示半截图或 404
                if cover_path:
                    cover_path.unlink(missing_ok=True)
                out["cover_clear"] = True
                out["note"].append("cover_cleared_corrupt")
            else:
                out["note"].append("cover_unavailable")
    else:
        out["note"].append("cover_keep")
    return out


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--school-id", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--skip-logos", action="store_true")
    ap.add_argument("--skip-covers", action="store_true")
    ap.add_argument("--redo-covers", action="store_true", help="忽略已有封面重新选图（过滤规则升级后重跑用）")
    ap.add_argument(
        "--force-cover",
        action="store_true",
        help="配合 --school-id：无视海报体检，强制为该重选封面（水印图等已知缺陷）",
    )
    ap.add_argument(
        "--corrupt-only",
        action="store_true",
        help="只处理坏图/悬空封面（解码失败或 DB 指向缺失文件），配合 --redo-covers",
    )
    ap.add_argument(
        "--poster-only",
        action="store_true",
        help="只处理海报嫌疑封面（像素体检命中），配合 --redo-covers --force-cover",
    )
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    COVER_DIR.mkdir(parents=True, exist_ok=True)

    name_cache = CACHE_DIR / "gaokao_name.json"
    raw = None
    if name_cache.exists():
        raw = name_cache.read_bytes()
    if not raw:
        raw = fetch(GAOKAO_NAME, timeout=20, limit=8_000_000)
        if not raw:
            log("[x] 无法下载掌上高考名单 name.json，中止")
            return 1
        name_cache.write_bytes(raw)
    entries = json.loads(raw.decode("utf-8"))["data"]
    name_map: dict[str, str] = {}
    for e in entries:
        name_map.setdefault(norm_name(e.get("name", "")), str(e["school_id"]))
    log(f"[i] 掌上高考名单 {len(entries)} 条，归一名称 {len(name_map)} 个")

    sql = "SELECT id, name, logo_url, cover_url, official_url FROM kaoyan_schools"
    params: dict = {}
    if args.school_id:
        sql += " WHERE id = :sid"
        params["sid"] = args.school_id
    sql += " ORDER BY id"
    with engine.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(text(sql), params)]
    if args.limit:
        rows = rows[: args.limit]
    if args.corrupt_only:
        keep = []
        for r in rows:
            cu = r["cover_url"]
            if not cu:
                continue
            p = IMG_ROOT / cu.replace("/media/images/", "", 1)
            try:
                ok = p.exists() and image_decodable(p.read_bytes())
            except Exception:
                ok = False
            if not ok:
                keep.append(r)
        rows = keep
        log(f"[i] corrupt-only：{len(rows)} 所坏图/悬空封面待修")
    if args.poster_only:
        keep = []
        for r in rows:
            cu = r["cover_url"]
            if not cu:
                continue
            p = IMG_ROOT / cu.replace("/media/images/", "", 1)
            try:
                if p.exists() and poster_like(p.read_bytes()):
                    keep.append(r)
            except Exception:
                continue
        rows = keep
        log(f"[i] poster-only：{len(rows)} 所海报嫌疑封面待修")
    log(f"[i] 待处理院校 {len(rows)} 所（{'APPLY' if args.apply else 'DRY-RUN'}，workers={args.workers}）")

    results: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(process_school, r, name_map, args): r for r in rows}
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            results.append(r)
            if i % 50 == 0 or i == len(rows):
                log(f"  … {i}/{len(rows)}  elapsed {time.time() - t0:.0f}s")

    n_logo = sum(1 for r in results if r["logo"])
    n_cover = sum(1 for r in results if r["cover"])
    n_clear = sum(1 for r in results if r.get("cover_clear"))
    n_site = sum(1 for r in results if r["official_url"])
    unmatched = sum(1 for r in results if "gaokao_name_unmatched" in r["note"])

    if args.apply:
        with engine.begin() as c:
            for r in results:
                sets, params = [], {"id": r["id"]}
                if r["logo"] and not args.skip_logos:
                    sets.append("logo_url = :logo")
                    params["logo"] = r["logo"]
                if r["cover"] and not args.skip_covers:
                    sets.append("cover_url = :cover")
                    params["cover"] = r["cover"]
                if r.get("cover_clear") and not args.skip_covers:
                    sets.append("cover_url = NULL")
                if r["official_url"]:
                    sets.append("official_url = :site")
                    params["site"] = r["official_url"]
                if sets:
                    c.execute(text(f"UPDATE kaoyan_schools SET {', '.join(sets)} WHERE id = :id"), params)
        log(f"[✓] 写库完成：logo {n_logo} / cover {n_cover} / 坏图置空 {n_clear} / official_url 补齐 {n_site}")
    else:
        log(f"[dry-run] 将写入：logo {n_logo} / cover {n_cover} / 坏图置空 {n_clear} / official_url 补齐 {n_site}")

    with engine.connect() as c:
        tot, nl, nc = c.execute(text("SELECT COUNT(*), COUNT(logo_url), COUNT(cover_url) FROM kaoyan_schools")).one()
    report = {
        "processed": len(results),
        "new_logo": n_logo,
        "new_cover": n_cover,
        "cover_cleared_corrupt": n_clear,
        "official_url_filled": n_site,
        "gaokao_unmatched": unmatched,
        "db_total": tot,
        "db_logo_filled": nl,
        "db_cover_filled": nc,
        "elapsed_s": round(time.time() - t0, 1),
        "apply": bool(args.apply),
        "details": sorted(results, key=lambda r: r["id"]),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[i] 库内现状：{tot} 所 / logo {nl} / cover {nc}；报告 {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
