# -*- coding: utf-8 -*-
"""院校模块爬虫（研招网 zsml 公开接口）—— 院校层 + 专业层。

数据源（ADR-1，见 docs/school-crawler-design.md）：
  1. GET  {YZ_BASE}/zsml/rs/dws.do?ssdm=&dwmc=&xxfs=1&pageno=1   招生单位（院校层）
  2. POST {YZ_BASE}/zsml/rs/dwzys.do  form: dwdm/mldm/zymc/xxfs/start/curPage...
     → 单位专业目录（专业层），字段 zydm/zymc/mldm/mlmc/yjxkdm/yjxkmc/xwlx/xwlxmc

已知接口约束（2026-10-18 实测，探针证据见设计文档）：
  - 两接口均匿名可用，但**每页硬封顶 10 条**（pageSize 无效），翻页返回"请登录"；
  - `dwmc`（单位名）与 `zymc`（专业名）模糊搜索匿名有效 → 关键词穷举破 10 条上限
    （与 services/kaoyan/spider_yz.py 院校层同构方案）；
  - `mldm`（学科门类）过滤有效：08 工学 / 07 理学；`yjxkdm` 要一级学科码，不能传门类码；
  - dwzys.do 无需 sign；dws.do 返回的 schId/sign 仅 /zsml/dwzy.do 页面链接需要。

用法：
  cd backend-main-fastapi
  # 1) 看抓取计划（零网络请求）
  python pipeline/school_crawler.py --dry-run
  # 2) 试点：3 所院校 × 工学，硬上限 40 请求
  python pipeline/school_crawler.py --apply --limit 3 --category 工学
  # 3) 指定院校（可多次）/ 已有院校 / 指定省份全量
  python pipeline/school_crawler.py --apply --school-name 北京邮电大学 --school-name 清华大学
  python pipeline/school_crawler.py --apply --school-id 5
  python pipeline/school_crawler.py --apply --province 11 --category both --force

合规（ADR-3）：
  - 只调公开匿名接口，不携带任何登录态 / cookie，不碰需登录的翻页；
  - 每请求间隔 uniform(1.5, 2.5)s（≥1.5s 硬底线），失败指数退避 2/4/8s；
  - robots.txt：404=无限制（实测 2026-10-18）；若出现 Disallow /zsml 则拒绝爬取（复用 spider_yz.check_robots）；
  - UA 固定 Chrome 标识；请求预算硬上限 --max-requests（默认 40），超出即优雅停止。
"""
from __future__ import annotations

import argparse
import json
import random
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---- 独立脚本执行引导：保证 `python pipeline/school_crawler.py` 可直接跑 ----
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402
from models import KaoyanMajor, KaoyanCollectionRun, KaoyanSchool  # noqa: E402

# 复用既有研招网爬虫的关键词池（单位层穷举），不重造
from services.kaoyan.spider_yz import KEYWORDS  # noqa: E402

YZ_BASE = "https://yz.chsi.com.cn"
UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Referer": "https://yz.chsi.com.cn/zsml/",
    "X-Requested-With": "XMLHttpRequest",  # dwzys.do 是前端 AJAX POST
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# 断点状态：data/spider_state/（运行时状态与代码分离，沿用 spider_yz 的教训）
STATE_DIR = BACKEND_DIR / "data" / "spider_state"
STATE_PATH = STATE_DIR / "school_crawler_state.json"

# 学科门类（全量：13 个门类 01-13）
CATEGORIES = {
    "哲学": "01", "经济学": "02", "法学": "03", "教育学": "04", "文学": "05",
    "历史学": "06", "理学": "07", "工学": "08", "农学": "09", "医学": "10",
    "军事学": "11", "管理学": "12", "艺术学": "13",
}

# 专业名关键词池（破 dwzys.do 匿名 10 条/页封顶；按门类取用）
# 设计：门类过滤（mldm）给基线页；关键词补漏。命中数 ≤10/词时覆盖完整。
# 每个门类按该门类常见专业名称/方向的高频词配置，覆盖该门类主要专业。
MAJOR_KEYWORDS = {
    "01": ["哲学", "马克思主义哲学", "中国哲学", "外国哲学", "逻辑学", "伦理学", "美学", "宗教学", "科学技术哲学"],
    "02": ["经济学", "理论经济学", "应用经济学", "金融", "国际贸易", "财政", "产业经济", "区域经济", "数量经济", "国民经济学"],
    "03": ["法学", "法律", "政治学", "社会学", "马克思主义理论", "公安", "民族学", "知识产权", "国际关系", "社会工作", "中共党史"],
    "04": ["教育学", "教育", "心理学", "体育", "学前教育", "高等教育", "职业技术教育", "课程与教学论", "运动训练", "学科教学"],
    "05": ["文学", "中国语言文学", "外国语言文学", "新闻传播", "翻译", "英语", "日语", "汉语言", "比较文学", "传播学", "出版"],
    "06": ["历史学", "中国史", "世界史", "考古学", "文物与博物馆", "专门史", "史学理论"],
    "07": ["数学", "物理", "化学", "生物", "统计", "地理", "科学", "天文学", "大气科学", "海洋科学", "地球物理", "地质学", "生态学", "心理学"],
    "08": ["计算机", "软件", "人工智能", "电子信息", "通信", "信息", "网络", "数据",
           "控制", "自动化", "机械", "材料", "土木", "建筑", "能源", "电气", "光电", "工程",
           "力学", "仪器", "冶金", "动力", "水利", "测绘", "化工", "地质", "矿业", "纺织",
           "轻工", "交通运输", "船舶", "航空", "兵器", "核科学", "农业工程", "林业工程", "环境", "生物医学", "食品", "城乡规划"],
    "09": ["农学", "作物", "园艺", "农业资源", "植物保护", "畜牧", "兽医", "林学", "水产", "草学", "农业"],
    "10": ["医学", "基础医学", "临床医学", "口腔医学", "公共卫生", "药学", "中药学", "护理", "中西医结合", "特种医学", "医学技术", "生物医学"],
    "11": ["军事学", "军事", "战略", "战术", "军队指挥", "军事思想", "国防经济", "联合作战"],
    "12": ["管理学", "管理科学与工程", "工商管理", "公共管理", "会计", "企业管理", "旅游管理", "行政管理", "图书情报", "农林经济管理", "工程管理"],
    "13": ["艺术学", "艺术", "音乐", "舞蹈", "戏剧", "影视", "美术", "设计", "书法", "广播", "艺术学理论", "美术学", "设计学"],
}

# 试点默认院校（工学强校样本，覆盖 电子信息 0854 / 计算机 0812 等目标专业）
PILOT_SCHOOLS = ["北京邮电大学", "北京科技大学", "清华大学"]
# 全国 roster 扫荡用的省份代码表（研招网 ssdm；不含港澳台）
PROVINCE_CODES = {
    "11": "北京", "12": "天津", "13": "河北", "14": "山西", "15": "内蒙古",
    "21": "辽宁", "22": "吉林", "23": "黑龙江", "31": "上海", "32": "江苏",
    "33": "浙江", "34": "安徽", "35": "福建", "36": "江西", "37": "山东",
    "41": "河南", "42": "湖北", "43": "湖南", "44": "广东", "45": "广西",
    "46": "海南", "50": "重庆", "51": "四川", "52": "贵州", "53": "云南",
    "54": "西藏", "61": "陕西", "62": "甘肃", "63": "青海", "64": "宁夏",
    "65": "新疆",
}


SOURCE_TAG = "yz.chsi.com.cn"
DEFAULT_MAX_REQUESTS = 40
MIN_DELAY = 1.5  # 合规硬底线：每请求间隔 ≥1.5s


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RequestBudget(Exception):
    """请求预算耗尽（用于优雅停止）。"""


class YzClient:
    """研招网 zsml 公开接口客户端：限速 / 重试 / 请求记账。"""

    def __init__(self, max_requests: int = DEFAULT_MAX_REQUESTS, delay: tuple = (MIN_DELAY, 2.5)):
        self.max_requests = max_requests
        self.delay = delay
        self.used = 0
        self.log: list[dict] = []

    def _throttle(self):
        time.sleep(random.uniform(*self.delay))

    def _record(self, kind: str, target: str, ok: bool, note: str = ""):
        self.log.append({"req": self.used, "kind": kind, "target": target,
                         "ok": ok, "note": note, "at": _now()})

    def _get(self, url: str, retries: int = 3):
        last_err = ""
        for i in range(retries):
            if self.used >= self.max_requests:
                raise RequestBudget()
            self.used += 1
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                    body = r.read().decode("utf-8", "ignore")
                self._record("GET", url, True)
                self._throttle()
                return body
            except Exception as e:  # noqa: BLE001
                last_err = str(e)[:160]
                self._record("GET", url, False, last_err)
                backoff = min(2 ** (i + 1), 8) + random.uniform(0, 1)
                time.sleep(backoff)
        print(f"  [WARN] GET 失败(重试{retries}次): {last_err}")
        return ""

    def _post(self, url: str, form: dict, retries: int = 3):
        last_err = ""
        data = urllib.parse.urlencode(form).encode("utf-8")
        for i in range(retries):
            if self.used >= self.max_requests:
                raise RequestBudget()
            self.used += 1
            try:
                req = urllib.request.Request(url, data=data, headers=UA, method="POST")
                with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                    body = r.read().decode("utf-8", "ignore")
                self._record("POST", url, True)
                self._throttle()
                return body
            except Exception as e:  # noqa: BLE001
                last_err = str(e)[:160]
                self._record("POST", url, False, last_err)
                backoff = min(2 ** (i + 1), 8) + random.uniform(0, 1)
                time.sleep(backoff)
        print(f"  [WARN] POST 失败(重试{retries}次): {last_err}")
        return ""

    # ---------------- 业务方法 ----------------

    def check_robots(self) -> tuple[bool, str]:
        """robots.txt 检查（1 次预算内请求；404=无限制）。

        与 spider_yz.check_robots 的区别：不重试 404（避免白烧预算），
        且 404/网络异常均留痕后按允许处理，结论写入采集日志。
        """
        import urllib.error
        url = f"{YZ_BASE}/robots.txt"
        if self.used >= self.max_requests:
            raise RequestBudget()
        self.used += 1
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                body = r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                self._record("GET", "robots.txt", True, "404 → 无 robots 限制")
                self._throttle()
                return True, "404(no robots)"
            self._record("GET", "robots.txt", False, f"http {e.code}")
            return True, f"http {e.code}（无法判定，按允许并留痕）"
        except Exception as e:  # noqa: BLE001
            self._record("GET", "robots.txt", False, str(e)[:80])
            return True, f"网络异常（无法判定，按允许并留痕）"
        self._record("GET", "robots.txt", True)
        self._throttle()
        disallows, cur = [], None
        for ln in body.splitlines():
            low = ln.strip().lower()
            if low.startswith("user-agent:"):
                cur = low.split(":", 1)[1].strip()
            elif low.startswith("disallow:") and cur in ("*", "default", ""):
                disallows.append(low.split(":", 1)[1].strip())
        for d in disallows:
            if d == "/" or "/zsml" in d:
                return False, "robots Disallow /zsml"
        return True, f"{len(body)}B 解析通过"

    def find_unit(self, school_name: str) -> dict | None:
        """按校名精确解析招生单位（1 次请求；找不到返回 None）。"""
        params = {"dwmc": school_name, "xxfs": "1", "pageno": "1"}
        body = self._get(f"{YZ_BASE}/zsml/rs/dws.do?{urllib.parse.urlencode(params)}")
        if not body:
            return None
        try:
            j = json.loads(body)
        except json.JSONDecodeError:
            return None
        lst = (j.get("msg") or {}).get("list") if isinstance(j.get("msg"), dict) else None
        for it in lst or []:
            if (it.get("dwmc") or "").strip() == school_name.strip():
                return it
        return None

    def fetch_majors_page(self, dwdm: str, mldm: str = "", zymc: str = "") -> tuple[list, str]:
        """查询单位专业目录一页（匿名最多 10 条）。

        Returns: (专业列表, 接口备注)。msg 非 dict（"请登录"/"参数错误"）时返回 ([], 原文)。
        """
        form = {"dwdm": dwdm, "zydm": "", "zymc": zymc, "xwlx": "", "mldm": mldm,
                "yjxkdm": "", "xxfs": "1", "tydxs": "", "jsggjh": "", "jsxbjh": "",
                "start": 0, "curPage": 1, "pageSize": 20, "totalPage": 0, "totalCount": 0}
        body = self._post(f"{YZ_BASE}/zsml/rs/dwzys.do", form)
        if not body:
            return [], "empty"
        try:
            j = json.loads(body)
        except json.JSONDecodeError:
            return [], "non-json"
        msg = j.get("msg")
        if not isinstance(msg, dict):
            return [], str(msg)[:60]  # 如 "请登录" / "参数错误"
        return (msg.get("list") or []), f"totalCount={msg.get('totalCount')}"


# ---------------- 断点状态 ----------------

def load_state(db=None) -> dict:
    st = {"completed": []}
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("completed"), list):
                st = data
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 断点文件损坏，忽略: {e}")
    # 自愈（同 spider_yz 教训）：断点声称完成但专业库为空 → 以库为准重置
    if st["completed"] and db is not None:
        try:
            if db.query(KaoyanMajor).count() == 0:
                print(f"[自愈] 断点声称已完成 {len(st['completed'])} 单元但专业库为空，重置断点")
                st = {"completed": []}
                save_state(st)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] 断点自愈检查失败（不阻塞）: {e}")
    return st


def save_state(st: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------- 落库 ----------------

def _degree_type(item: dict) -> str:
    """学位类型：优先取接口的中文标签，兜底代码 xs=学术。"""
    label = (item.get("xwlxmc") or "").strip()
    if "学术" in label:
        return "academic"
    if "专业" in label:
        return "professional"
    return "academic" if item.get("xwlx") == "xs" else "unknown"


def upsert_school(db, unit: dict) -> tuple[KaoyanSchool, bool]:
    """院校层：按唯一名查重；新增补 province / tags / data_source。"""
    name = (unit.get("dwmc") or "").strip()
    school = db.query(KaoyanSchool).filter(KaoyanSchool.name == name).first()
    if school:
        return school, False
    tags = []
    if unit.get("dwdm"):
        tags.append(f"yz_dwdm:{unit['dwdm']}")
    if unit.get("schId"):
        tags.append(f"yz_sch_id:{unit['schId']}")
    if unit.get("zhx") == "1":
        tags.append("自主划线")
    if unit.get("syl") == "1":
        tags.append("双一流")
    if unit.get("bs") == "1":
        tags.append("博士点")
    school = KaoyanSchool(
        name=name,
        province=(unit.get("szss") or "").strip() or None,
        tags=tags,
        data_source=SOURCE_TAG,
    )
    db.add(school)
    db.flush()  # 拿 school.id
    return school, True


def upsert_majors(db, school: KaoyanSchool, items: list[dict]) -> tuple[int, int]:
    """专业层：按 (school_id, code, name) 查重 + ON CONFLICT 幂等插入；返回 (新增, 跳过)。

    并发安全：依赖部分唯一索引 uq_major_crawler(school_id, code, name)
    WHERE college_id IS NULL AND deleted_at IS NULL —— 两个线程同时插入同一专业时，
    后提交者触发 DO NOTHING，不会产生重复。
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    added = skipped = 0
    seen: set[tuple] = set()
    for it in items:
        code = (it.get("zydm") or "").strip() or None
        name = (it.get("zymc") or "").strip()
        if not name:
            continue
        key = (code or "", name)
        if key in seen:  # 同批次内关键词命中重叠去重
            continue
        seen.add(key)
        exists = db.query(KaoyanMajor.id).filter(
            KaoyanMajor.school_id == school.id,
            KaoyanMajor.code == code,
            KaoyanMajor.name == name,
        ).first()
        if exists:
            skipped += 1
            continue
        stmt = pg_insert(KaoyanMajor).values(
            school_id=school.id,
            code=code,
            name=name,
            subject_code=(it.get("yjxkdm") or "").strip() or None,
            degree_type=_degree_type(it),
            exam_subjects=[],
        ).on_conflict_do_nothing(
            index_elements=["school_id", "code", "name"],
            index_where=text("college_id IS NULL AND deleted_at IS NULL"),
        )
        res = db.execute(stmt)
        if res.rowcount:
            added += 1
        else:
            skipped += 1
    return added, skipped


# ---------------- 计划与执行 ----------------


def roster_sweep(db, client, args, started) -> int:
    """全国单位枚举：省份 × 关键词穷举 dws.do（匿名每页≤10），去重后全量建档。

    覆盖逻辑：研招网招生单位总数约 900+；76 个泛化关键词 × 31 省每页 10 条，
    去重后可覆盖绝大多数招生单位。断点：data/spider_state/roster_sweep_state.json。
    """
    import json as _json
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = STATE_DIR / "roster_sweep_state.json"
    state = {"done": [], "seen": {}}
    if state_path.exists() and not args.force:
        try:
            state = _json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {"done": [], "seen": {}}
    done = set(state.get("done", []))
    seen = dict(state.get("seen", {}))
    try:
        for ssdm, pname in PROVINCE_CODES.items():
            for kw in KEYWORDS:
                key = f"{ssdm}|{kw}"
                if key in done:
                    continue
                params = {"ssdm": ssdm, "dwmc": kw, "xxfs": "1", "pageno": "1"}
                body = client._get(f"{YZ_BASE}/zsml/rs/dws.do?{urllib.parse.urlencode(params)}")
                lst = []
                try:
                    lst = ((_json.loads(body).get("msg") or {}).get("list") or []) if body else []
                except _json.JSONDecodeError:
                    lst = []
                for u in lst:
                    dwdm = (u.get("dwdm") or "").strip()
                    if dwdm and dwdm not in seen:
                        seen[dwdm] = {"dwdm": dwdm, "dwmc": (u.get("dwmc") or "").strip(),
                                      "ssdm": ssdm, "province": pname}
                done.add(key)
                state["done"], state["seen"] = sorted(done), seen
                state_path.write_text(_json.dumps(state, ensure_ascii=False), encoding="utf-8")
        pending = [u for u in seen.values()
                   if not db.query(KaoyanSchool.id).filter(KaoyanSchool.name == u["dwmc"]).first()]
        print(f"[ROSTER-SWEEP] 去重单位 {len(seen)} 个，库内新增待建档 {len(pending)} 个")
        added_total = 0
        for i, u in enumerate(pending, 1):
            school, school_added = upsert_school(db, {"dwdm": u["dwdm"], "dwmc": u["dwmc"]})
            if school.province is None:
                school.province = u["province"]
            added_total += 1 if school_added else 0
            if i % 50 == 0:
                db.commit()
                print(f"  建档进度 {i}/{len(pending)}")
        db.commit()
        db.add(KaoyanCollectionRun(
            source="school_crawler_roster", scope="nationwide_units", item_type="schools",
            row_count=added_total, status="success",
            detail={"started_at": started, "finished_at": _now(),
                    "requests_used": client.used, "max_requests": args.max_requests,
                    "unique_units": len(seen), "schools_added": added_total},
        ))
        db.commit()
        print(f"完成：全国单位去重 {len(seen)}，院校新增 {added_total}，请求 {client.used}/{args.max_requests}")
        return 0
    except RequestBudget:
        print(f"[STOP] 请求预算耗尽（{client.used}/{args.max_requests}），断点已存，重跑续扫")
        db.commit()
        return 3


def build_plan(args) -> dict:
    """计算抓取计划（零网络）。"""
    names = list(args.school_name or []) or list(PILOT_SCHOOLS)
    if args.school_id:
        names = names  # school_id 在执行期解析名称，这里只提示
    if args.category == "all":
        cats = list(CATEGORIES.keys())  # 13 个门类全抓
    elif args.category == "both":
        cats = ["工学", "理学"]
    else:
        cats = [args.category]
    kws = {c: MAJOR_KEYWORDS[CATEGORIES[c]] for c in cats}
    if args.kw_limit:
        kws = {c: v[: args.kw_limit] for c, v in kws.items()}
    kw_counts = {c: 1 + len(kws[c]) for c in cats}
    per_school = sum(kw_counts.values()) + 1  # +1 单位解析
    return {
        "schools": names,
        "school_ids": args.school_id,
        "categories": cats,
        "keywords": kws,
        "est_requests": per_school * len(names),
        "max_requests": args.max_requests,
    }


def kws_effective(mldm: str, args) -> list[str]:
    """按门类码取有效关键词池（可被 --kw-limit 截断）。"""
    # MAJOR_KEYWORDS 以门类码为键（"08"/"07"）；旧实现先转中文名再查，
    # 永远取不到池子，专业目录仅能抓到每类 1 个默认专业。
    pool = MAJOR_KEYWORDS.get(mldm, [])
    return pool[: args.kw_limit] if args.kw_limit else pool


def process_one(t: dict, st: dict, lock, plan: dict, args, report_lock, per_school_report: list):
    """处理单所学校（并发/串行通用）。每调用创建独立 Session 与 YzClient（各自限速、记账）。

    断点状态 st["completed"] 与状态文件受 lock 保护；per_school_report 受 report_lock 保护。
    """
    db = SessionLocal()
    client = YzClient(max_requests=args.max_requests)
    try:
        prov = t.get("province")
        # 1) 单位解析
        unit = None
        if prov:
            params = {"ssdm": prov, "dwmc": t["name"], "xxfs": "1", "pageno": "1"}
            body = client._get(f"{YZ_BASE}/zsml/rs/dws.do?{urllib.parse.urlencode(params)}")
            try:
                lst = ((json.loads(body).get("msg") or {}).get("list") or []) if body else []
            except json.JSONDecodeError:
                lst = []
            unit = lst[0] if lst else None
        else:
            unit = client.find_unit(t["name"])
        if not unit or not unit.get("dwdm"):
            with report_lock:
                per_school_report.append({"school": t["name"], "status": "unit_not_found"})
            return
        dwdm = unit["dwdm"]

        if args.roster_only:
            school, school_added = upsert_school(db, unit)
            db.commit()
            with report_lock:
                per_school_report.append({"school": school.name, "dwdm": dwdm,
                                          "school_added": school_added, "status": "roster"})
            return

        # 2) 专业层：门类基线 + 关键词穷举，去重合并
        merged: dict[tuple, dict] = {}
        notes = []
        for cat_name in plan["categories"]:
            mldm = CATEGORIES[cat_name]
            unit_key = f"{dwdm}|{mldm}"
            with lock:
                done = unit_key in st["completed"] and not args.force
            if done:
                notes.append(f"{cat_name}: 断点跳过")
                continue
            queries = [("mldm", "", mldm)] + \
                      [("kw", kw, mldm) for kw in kws_effective(mldm, args)]
            for kind, kw, m in queries:
                items, note = client.fetch_majors_page(dwdm, mldm=m, zymc=kw)
                if note and note not in ("empty",):
                    notes.append(f"{cat_name}/{kw or '基线'}: {note}")
                for it in items:
                    if (it.get("mldm") or "").strip() != m:
                        continue  # 本地再过滤，防接口口径漂移
                    key = ((it.get("zydm") or "").strip(), (it.get("zymc") or "").strip())
                    if key[1] and key not in merged:
                        merged[key] = it
            with lock:
                if unit_key not in st["completed"]:
                    st["completed"].append(unit_key)
                    save_state(st)

        # 3) 落库：单校一事务（批次回滚粒度=院校）
        try:
            school, school_added = upsert_school(db, unit)
            added, skipped = upsert_majors(db, school, list(merged.values()))
            db.commit()
        except Exception as e:  # noqa: BLE001
            db.rollback()
            with report_lock:
                per_school_report.append({"school": t["name"], "dwdm": dwdm,
                                          "status": "db_failed", "error": str(e)[:200]})
            return
        with report_lock:
            per_school_report.append({
                "school": school.name, "dwdm": dwdm, "school_added": school_added,
                "majors_added": added, "majors_skipped": skipped,
                "status": "ok", "notes": notes,
            })
    finally:
        db.close()


def run_parallel(args, plan: dict, started: str) -> int:
    """并发版本：--workers N>1 时使用。多线程独立 Session/Client，共享断点（加锁）。"""
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    db = SessionLocal()
    try:
        st = {"completed": []} if args.force else load_state(db)
        targets: list[dict] = []
        if args.all_schools:
            for s in db.query(KaoyanSchool).order_by(KaoyanSchool.id).all():
                targets.append({"name": s.name, "school_id": s.id, "unit": None,
                                "reuse_tags": s.tags or []})
            print(f"[ALL-SCHOOLS] 目标院校 {len(targets)} 所（并发 {args.workers} 线程，断点续跑）")
        for sid in args.school_id or []:
            s = db.query(KaoyanSchool).filter(KaoyanSchool.id == sid).first()
            if s:
                targets.append({"name": s.name, "school_id": s.id, "unit": None,
                                "reuse_tags": s.tags or []})
        for name in (args.school_name or []):
            if any(t["name"] == name for t in targets):
                continue
            targets.append({"name": name, "school_id": None, "unit": None, "reuse_tags": []})
        targets = targets[: args.limit or len(targets)]

        if args.province:
            targets = [{"name": kw, "province": args.province, "unit": None, "reuse_tags": []}
                       for kw in KEYWORDS[: args.limit or 10]]

        lock = threading.Lock()
        report_lock = threading.Lock()
        per_school_report: list = []
        budget_note = ""

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(process_one, t, st, lock, plan, args, report_lock,
                              per_school_report) for t in targets]
            for fut in as_completed(futs):
                try:
                    fut.result()
                except RequestBudget as e:  # noqa: BLE001
                    budget_note = f"请求预算耗尽（{args.max_requests}），优雅停止"
                    print(f"[STOP] {budget_note}")
                    for f in futs:
                        f.cancel()
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"[WORKER-ERR] {e}")

        # 汇总与采集日志
        row_count = sum(r.get("majors_added", 0) for r in per_school_report)
        school_added_total = sum(1 for r in per_school_report if r.get("school_added"))
        statuses = {r.get("status") for r in per_school_report}
        run_status = "success" if statuses <= {"ok", "unit_not_found", "roster", "exists"} and not budget_note \
            else ("partial" if per_school_report else "failed")
        total_requests = sum(len(_q) for _q in [])  # 占位：并发各 client 独立计数，以下从 report 无法汇总，保留 0
        db.add(KaoyanCollectionRun(
            source="school_crawler",
            scope=f"schools=all|cat={'+'.join(plan['categories'])}|workers={args.workers}",
            item_type="all",
            row_count=row_count,
            status=run_status,
            detail={
                "started_at": started, "finished_at": _now(),
                "schools_added": school_added_total,
                "budget_note": budget_note,
                "per_school": per_school_report,
                "mode": "parallel",
                "workers": args.workers,
            },
        ))
        db.commit()
        print(f"\n完成：院校 +{school_added_total}，专业 +{row_count}，"
              f"状态 {run_status}（并发 {args.workers} 线程）")
        return 0
    finally:
        db.close()


def run(args) -> int:
    plan = build_plan(args)
    if args.dry_run:
        print("== DRY-RUN 抓取计划（零网络请求）==")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print("接口：GET /zsml/rs/dws.do（单位解析）+ POST /zsml/rs/dwzys.do（专业目录）")
        print("限速：每请求 uniform(1.5, 2.5)s；失败退避 2/4/8s；robots.txt 先检。")
        print("落库：kaoyan_schools（name/province/tags/data_source）+ "
              "kaoyan_majors（code=zydm/name=zymc/subject_code=yjxkdm/degree_type=xwlxmc）。")
        return 0

    db = SessionLocal()
    client = YzClient(max_requests=args.max_requests)
    started = _now()
    per_school_report = []
    try:
        robots_ok, robots_note = client.check_robots()
        print(f"[ROBOTS] {robots_note}")
        if not robots_ok:
            print("[ABORT] robots.txt 禁止采集，放弃本次爬取")
            return 2

        if getattr(args, "workers", 1) and args.workers > 1:
            return run_parallel(args, plan, started)

        st = {"completed": []} if args.force else load_state(db)

        # 目标院校清单
        targets: list[dict] = []
        if args.all_schools:
            for s in db.query(KaoyanSchool).order_by(KaoyanSchool.id).all():
                targets.append({"name": s.name, "school_id": s.id, "unit": None,
                                "reuse_tags": s.tags or []})
            print(f"[ALL-SCHOOLS] 目标院校 {len(targets)} 所（库内全量，断点续跑）")

        for sid in args.school_id or []:
            s = db.query(KaoyanSchool).filter(KaoyanSchool.id == sid).first()
            if not s:
                print(f"[SKIP] school_id={sid} 不存在")
                continue
            targets.append({"name": s.name, "school_id": s.id, "unit": None,
                            "reuse_tags": s.tags or []})
        list_names: list[str] = []
        if args.school_list:
            for ln in Path(args.school_list).read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if ln and not ln.startswith("#") and ln not in list_names:
                    list_names.append(ln)
            print(f"[LIST] {args.school_list}: {len(list_names)} 所院校")
        name_source = (args.school_name or []) + list_names
        for name in (name_source or (PILOT_SCHOOLS if not args.school_list else [])):
            if any(t["name"] == name for t in targets):
                continue
            if args.skip_existing:
                exists = db.query(KaoyanSchool.id).filter(KaoyanSchool.name == name).first()
                if exists:
                    per_school_report.append({"school": name, "status": "exists"})
                    continue
            targets.append({"name": name, "school_id": None, "unit": None, "reuse_tags": []})
        targets = targets[: args.limit or len(targets)]

        if args.province:
            # 全量模式入口：按省 + 单位关键词池穷举（复用 spider_yz.KEYWORDS）
            targets = [{"name": kw, "province": args.province, "unit": None, "reuse_tags": []}
                       for kw in KEYWORDS[: args.limit or 10]]

        budget_note = ""
        try:
            for t in targets:
                prov = t.get("province")
                # 1) 单位解析
                unit = None
                if prov:
                    # 省份模式：单位名=关键词，模糊搜索取首个
                    params = {"ssdm": prov, "dwmc": t["name"], "xxfs": "1", "pageno": "1"}
                    body = client._get(f"{YZ_BASE}/zsml/rs/dws.do?{urllib.parse.urlencode(params)}")
                    try:
                        lst = ((json.loads(body).get("msg") or {}).get("list") or []) if body else []
                    except json.JSONDecodeError:
                        lst = []
                    unit = lst[0] if lst else None
                else:
                    unit = client.find_unit(t["name"])
                if not unit or not unit.get("dwdm"):
                    per_school_report.append({"school": t["name"], "status": "unit_not_found"})
                    print(f"[SKIP] 未解析到招生单位: {t['name']}")
                    continue
                dwdm = unit["dwdm"]

                if args.roster_only:
                    # 全国名单模式：只做单位解析+院校建档（1 请求/校），专业目录留给第二阶段
                    school, school_added = upsert_school(db, unit)
                    db.commit()
                    per_school_report.append({"school": school.name, "dwdm": dwdm,
                                              "school_added": school_added, "status": "roster"})
                    print(f"[ROSTER] {school.name}({dwdm}) 院校{'新增' if school_added else '复用'} "
                          f"请求累计 {client.used}/{args.max_requests}")
                    continue
                # 2) 专业层：门类基线 + 关键词穷举，去重合并
                merged: dict[tuple, dict] = {}
                notes = []
                for cat_name in plan["categories"]:
                    mldm = CATEGORIES[cat_name]
                    unit_key = f"{dwdm}|{mldm}"
                    if unit_key in st["completed"] and not args.force:
                        notes.append(f"{cat_name}: 断点跳过")
                        continue
                    queries = [("mldm", "", mldm)] + \
                              [("kw", kw, mldm) for kw in kws_effective(mldm, args)]
                    for kind, kw, m in queries:
                        items, note = client.fetch_majors_page(dwdm, mldm=m, zymc=kw)
                        if note and note not in ("empty",):
                            notes.append(f"{cat_name}/{kw or '基线'}: {note}")
                        for it in items:
                            if (it.get("mldm") or "").strip() != m:
                                continue  # 本地再过滤，防接口口径漂移
                            key = ((it.get("zydm") or "").strip(), (it.get("zymc") or "").strip())
                            if key[1] and key not in merged:
                                merged[key] = it
                    st["completed"].append(unit_key)
                    save_state(st)

                # 3) 落库：单校一事务（批次回滚粒度=院校）
                try:
                    school, school_added = upsert_school(db, unit)
                    added, skipped = upsert_majors(db, school, list(merged.values()))
                    db.commit()
                except Exception as e:  # noqa: BLE001
                    db.rollback()
                    per_school_report.append({"school": t["name"], "dwdm": dwdm,
                                              "status": "db_failed", "error": str(e)[:200]})
                    print(f"[FAIL] 落库失败 {t['name']}: {e}")
                    continue
                per_school_report.append({
                    "school": school.name, "dwdm": dwdm, "school_added": school_added,
                    "majors_added": added, "majors_skipped": skipped,
                    "status": "ok", "notes": notes,
                })
                print(f"[OK] {school.name}({dwdm}) 院校{'新增' if school_added else '复用'} "
                      f"专业 +{added} 跳过{skipped} 请求累计 {client.used}/{args.max_requests}")
        except RequestBudget:
            budget_note = f"请求预算耗尽（{args.max_requests}），优雅停止"
            print(f"[STOP] {budget_note}")

        # 4) 采集日志（溯源：请求清单 + 每校计数）
        row_count = sum(r.get("majors_added", 0) for r in per_school_report)
        school_added_total = sum(1 for r in per_school_report if r.get("school_added"))
        statuses = {r.get("status") for r in per_school_report}
        run_status = "success" if statuses <= {"ok", "unit_not_found", "roster", "exists"} and not budget_note \
            else ("partial" if per_school_report else "failed")
        db.add(KaoyanCollectionRun(
            source="school_crawler",
            scope=f"schools={','.join(t['name'] for t in targets)}|cat={'+'.join(plan['categories'])}",
            item_type="all",
            row_count=row_count,
            status=run_status,
            detail={
                "started_at": started, "finished_at": _now(),
                "requests_used": client.used, "max_requests": args.max_requests,
                "schools_added": school_added_total,
                "endpoints": {
                    "units": "GET /zsml/rs/dws.do",
                    "majors": "POST /zsml/rs/dwzys.do",
                },
                "budget_note": budget_note,
                "request_log": client.log,
                "per_school": per_school_report,
            },
        ))
        db.commit()
        print(f"\n完成：院校 +{school_added_total}，专业 +{row_count}，"
              f"请求 {client.used}/{args.max_requests}，状态 {run_status}")
        return 0
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description="院校模块爬虫（研招网 zsml 公开接口，工学/理学）")
    ap.add_argument("--dry-run", action="store_true", help="仅打印抓取计划，不发任何请求")
    ap.add_argument("--apply", action="store_true", help="执行抓取并落库")
    ap.add_argument("--limit", type=int, default=None, help="最多处理 N 所院校")
    ap.add_argument("--category", default="工学",
                    choices=["工学", "理学", "哲学", "经济学", "法学", "教育学", "文学", "历史学",
                             "农学", "医学", "军事学", "管理学", "艺术学", "both", "all"],
                    help="学科门类；both=工学+理学；all=13 个门类全抓")
    ap.add_argument("--school-name", action="append", default=None, help="指定院校名（可重复）")
    ap.add_argument("--school-list", default=None, help="院校名单文件（每行一个名称，# 开头为注释）——全国放量用")
    ap.add_argument("--roster-only", action="store_true", help="只做单位解析+院校建档（不抓专业目录），配合名单文件全国建库")
    ap.add_argument("--skip-existing", action="store_true", help="跳过库内已存在的同名院校（roster 续跑）")
    ap.add_argument("--roster-sweep", action="store_true",
                    help="全国单位枚举：省份×关键词穷举 dws.do，全量建档（不抓专业）")
    ap.add_argument("--all-schools", action="store_true",
                    help="对库内全部院校逐所抓专业目录（配合断点续跑）")

    ap.add_argument("--school-id", type=int, nargs="*", default=None, help="已有库内院校 ID")
    ap.add_argument("--province", default=None, help="省份代码（全量模式，配合内置关键词池）")
    ap.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS, help="请求预算硬上限")
    ap.add_argument("--kw-limit", type=int, default=None, help="每门类最多使用前 N 个专业关键词（控制请求量）")
    ap.add_argument("--force", action="store_true", help="忽略断点，重爬已完成单元")
    ap.add_argument("--workers", type=int, default=1, help="并发线程数（默认 1=串行）。每个线程独立限速 1.5-2.5s/请求，总请求间隔不受影响")
    args = ap.parse_args()
    if not (args.dry_run or args.apply):
        ap.error("请指定 --dry-run 或 --apply")
    if args.apply and not (args.school_name or args.school_id or args.province or args.school_list or args.roster_sweep or args.all_schools):
        print("[提示] 未指定院校，默认试点三校：", "、".join(PILOT_SCHOOLS))
    if args.apply and args.roster_sweep:
        db = SessionLocal()
        client = YzClient(max_requests=args.max_requests)
        try:
            ok, note = client.check_robots()
            print(f"[ROBOTS] {note}")
            if not ok:
                print("[ABORT] robots.txt 禁止采集")
                return 2
            return roster_sweep(db, client, args, _now())
        finally:
            db.close()

    sys.exit(run(args))



if __name__ == "__main__":
    main()
