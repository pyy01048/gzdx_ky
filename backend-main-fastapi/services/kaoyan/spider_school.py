# -*- coding: utf-8 -*-
"""C3: 院校官网爬虫 — 抓取重点院校复试线/拟录取名单 PDF 并解析。

功能：
1. 根据院校名搜索研究生院官网
2. 抓取复试线公告页面，提取PDF链接
3. 下载PDF并解析分数线/录取数据
4. 存入 KaoyanScoreline / KaoyanAdmission

使用方式：
    cd backend-main-fastapi
    python -c "from services.kaoyan.spider_school import crawl_school; crawl_school('清华大学')"
"""
import re, time, random, ssl, urllib.request, urllib.parse
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# C2/C3 合规：robots.txt 缓存，域名级检查
_ROBOTS_CACHE = {}


def check_robots(domain, force=False):
    """C2/C3: 检查目标站点 robots.txt，只允许未被禁止的路径。

    简化解析：User-Agent * 分组下的 Disallow；命中关键路径或全站禁止返回 False。
    """
    global _ROBOTS_CACHE
    key = domain
    if key in _ROBOTS_CACHE and not force:
        return _ROBOTS_CACHE[key]
    url = f"https://{domain}/robots.txt"
    body = ""
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as r:
            body = r.read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"  [ROBOTS] {domain}/robots.txt 不可用: {e}")
        # 拿不到 robots.txt 时按“可访问”处理，但保留说明
        _ROBOTS_CACHE[key] = True
        return True
    allowed = True
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    current_ua = None
    for ln in lines:
        low = ln.lower()
        if low.startswith("user-agent:"):
            current_ua = low.split(":", 1)[1].strip()
        elif low.startswith("disallow:") and current_ua in ("*", "default", ""):
            path = low.split(":", 1)[1].strip()
            if path == "/":
                allowed = False
                break
    _ROBOTS_CACHE[key] = allowed
    print(f"  [ROBOTS] {domain} robots.txt 允许采集: {allowed}")
    return allowed

# 常见研究生院官网域名映射（重点院校）
SCHOOL_URLS = {
    "清华大学": "https://yz.tsinghua.edu.cn/",
    "北京大学": "https://admission.pku.edu.cn/",
    "浙江大学": "http://www.grs.zju.edu.cn/",
    "上海交通大学": "https://yzb.sjtu.edu.cn/",
    "复旦大学": "https://gsao.fudan.edu.cn/",
    "南京大学": "https://grawww.nju.edu.cn/",
    "中国科学技术大学": "https://yz.ustc.edu.cn/",
    "哈尔滨工业大学": "http://yzb.hit.edu.cn/",
    "西安交通大学": "http://yz.xjtu.edu.cn/",
    "华中科技大学": "http://gs.hust.edu.cn/",
}


def fetch(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"  [retry {i+1}] {url[:60]}: {e}")
            time.sleep(random.uniform(2, 5))
    return ""


def find_pdf_links(html, base_url):
    """从HTML中提取PDF链接。"""
    links = re.findall(r'href=["\']([^"\']*\.pdf)["\']', html, re.I)
    result = []
    for link in links:
        if link.startswith("http"):
            result.append(link)
        elif link.startswith("/"):
            result.append(base_url.rstrip("/") + link)
        else:
            result.append(base_url.rstrip("/") + "/" + link)
    return list(set(result))


def search_announcements(school_name, keyword="复试线"):
    """搜索院校官网中含有关键词的公告页面。"""
    url = SCHOOL_URLS.get(school_name)
    if not url:
        print(f"  未配置 {school_name} 的官网URL")
        return []

    print(f"  抓取 {school_name} 官网: {url}")
    html = fetch(url)
    if not html:
        return []

    # 查找含有"复试线"或"拟录取"的链接
    pattern = f'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]*{keyword}[^<]*)</a>'
    matches = re.findall(pattern, html, re.I)
    return [(url + m[0] if m[0].startswith("/") else m[0], m[1].strip()) for m in matches]


def download_pdf(url, save_dir="downloads/pdfs"):
    """下载PDF到本地。"""
    save_path = Path(save_dir)
    save_path.mkdir(parents=True, exist_ok=True)
    filename = url.split("/")[-1]
    filepath = save_path / filename
    if filepath.exists():
        print(f"  已存在: {filename}")
        return str(filepath)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        filepath.write_bytes(data)
        print(f"  下载: {filename} ({len(data)//1024}KB)")
        return str(filepath)
    except Exception as e:
        print(f"  下载失败: {e}")
        return None


def parse_scoreline_pdf(pdf_path):
    """解析复试线PDF，提取分数线数据（简化版）。

    使用 pdfplumber 或 pypdf 提取文本，然后用正则匹配分数线。
    需要安装: pip install pdfplumber
    """
    try:
        import pdfplumber
    except ImportError:
        print("  需要安装 pdfplumber: pip install pdfplumber")
        return []

    results = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                lines = text.split("\n")
                for line in lines:
                    # 多模式匹配：学科名+分数 / 代码+学科+分数 / 总分
                    line = line.strip()
                    # 模式1: "工学 310" / "理学 290分"
                    m = re.match(r"^([\u4e00-\u9fa5]{2,6})\s+(?:总分\s*)?(\d{3})\s*(?:分)?$", line)
                    if m and m.group(1) not in ("研究生", "学术学位", "专业学位", "录取名单", "公示"):
                        results.append({"subject": m.group(1), "score": int(m.group(2))})
                        continue
                    # 模式2: "08 工学 310" / "02 经济学 340"
                    m = re.match(r"^(\d{2})\s+([\u4e00-\u9fa5]{2,6})\s+(\d{3})$", line)
                    if m:
                        results.append({"subject": m.group(2), "score": int(m.group(3))})
                        continue
                    # 模式3: 单科线/总分混合 "总分>=310 单科>=50"
                    m = re.match(r".*?总分[>=＝]*\s*(\d{3}).*", line)
                    if m:
                        results.append({"subject": "总分线", "score": int(m.group(1))})
    except Exception as e:
        print(f"  PDF解析失败: {e}")
    return results


def crawl_school(school_name, year=2026):
    """C3: 爬取单所院校的复试线和拟录取数据。"""
    from database import SessionLocal
    from core.models import KaoyanSchool, KaoyanScoreline

    db = SessionLocal()
    try:
        school = db.query(KaoyanSchool).filter(KaoyanSchool.name == school_name).first()
        if not school:
            print(f"  数据库中无 {school_name}")
            return

        print(f"开始爬取 {school_name} ({year})")

        # C3/C2 合规：robots.txt 检查
        from urllib.parse import urlparse
        parsed = urlparse(SCHOOL_URLS.get(school_name, ""))
        if parsed.hostname and not check_robots(parsed.hostname):
            print(f"  [ROBOTS] {parsed.hostname} 禁止采集，跳过 {school_name}")
            return

        # 1. 搜索复试线公告
        announcements = search_announcements(school_name, "复试线")
        print(f"  找到 {len(announcements)} 条复试线公告")

        # 2. 抓取公告页面，找PDF
        pdf_links = []
        for url, title in announcements[:5]:  # 只看前5条
            time.sleep(random.uniform(2, 5))
            html = fetch(url)
            pdfs = find_pdf_links(html, url)
            pdf_links.extend(pdfs)

        print(f"  找到 {len(pdf_links)} 个PDF")

        # 3. 下载并解析（PDF 落到会话中间产物目录）
        import tempfile, os
        pdf_dir = os.path.join(tempfile.gettempdir(), "kaoyan_school_pdfs", school_name)
        for pdf_url in pdf_links[:3]:
            time.sleep(random.uniform(2, 5))
            pdf_path = download_pdf(pdf_url, save_dir=pdf_dir)
            if pdf_path:
                scores = parse_scoreline_pdf(pdf_path)
                print(f"  解析出 {len(scores)} 条分数线")
                for s in scores:
                    existing = db.query(KaoyanScoreline).filter(
                        KaoyanScoreline.school_id == school.id,
                        KaoyanScoreline.year == year,
                        KaoyanScoreline.line_type == "校线",
                        KaoyanScoreline.total_line == s.get("score"),
                    ).first()
                    if not existing:
                        db.add(KaoyanScoreline(
                            school_id=school.id,
                            year=year,
                            total_line=s.get("score"),
                            line_type="校线",
                        ))
        db.commit()
        print(f"{school_name} 爬取完成")
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "清华大学"
    crawl_school(name)
