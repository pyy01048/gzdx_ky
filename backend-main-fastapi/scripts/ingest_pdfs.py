# -*- coding: utf-8 -*-
"""PDF 入库：文字版直接抽、扫描版走 RapidOCR，复用 ingest_source_folder 的
解析 / 跨源查重 / 写库逻辑。带文本缓存与断点续跑，按 phase 优先级处理。

phase:
  digital    —— 所有文字版 PDF（秒级，优先）
  questions  —— 扫描/混合版的题库类 PDF（OCR，价值最高）
  notes      —— 扫描/混合版的笔记类 PDF（OCR → 知识点）
  textbooks  —— 扫描/混合版的教材/其他 PDF（OCR，最慢，放最后）
  all        —— 以上全部（digital 先跑）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import defaultdict

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (_BACKEND, os.path.join(_BACKEND, "services"), os.path.join(_BACKEND, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ingest_source_folder as I  # noqa: E402
from services.parsers.router import route_parse  # noqa: E402

ROOT = os.environ.get("PDF_SOURCE_ROOT", r"D:\下载\QQ\压缩文件.zip\压缩文件")
TEMP = os.path.join(_BACKEND, ".temp")
CACHE_DIR = os.path.join(TEMP, "pdf_text_cache")
CACHE_INDEX = os.path.join(TEMP, "pdf_cache_index.json")
MANIFEST = os.path.join(TEMP, "pdf_manifest.json")
DONE_FILE = os.path.join(TEMP, "pdf_ingest_done.json")
CACHE_VERSION = "pdf-extract-v2"
os.makedirs(CACHE_DIR, exist_ok=True)


def _fp(path):
    st = os.stat(path)
    return hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()


def cache_key_for(path, kind, max_pages=None):
    return cache_key_from_fingerprint(_fp(path), kind, max_pages)


def cache_key_from_fingerprint(fp, kind, max_pages=None):
    payload = json.dumps(
        [CACHE_VERSION, fp, kind, max_pages],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_cache_index():
    try:
        with open(CACHE_INDEX, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("entries", {})
    except (OSError, ValueError, AttributeError):
        return {}


def remember_cache(rel, cache_key, cache_file, kind, max_pages, chars):
    entries = _load_cache_index()
    entries[cache_key] = {
        "rel": rel.replace("\\", "/"),
        "cache_key": cache_key,
        "cache_file": cache_file,
        "kind": kind,
        "max_pages": max_pages,
        "chars": chars,
    }
    os.makedirs(os.path.dirname(CACHE_INDEX), exist_ok=True)
    with open(CACHE_INDEX, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "entries": entries}, f, ensure_ascii=False, indent=2)


def find_cache_entry(rel, kind, max_pages=None):
    rel = rel.replace("\\", "/")
    for entry in _load_cache_index().values():
        if entry.get("rel") == rel and entry.get("kind") == kind and entry.get("max_pages") == max_pages:
            return entry
    return None


def extract_pdf_lines(path, kind, max_pages=None):
    """抽取 PDF 文本行，返回 (lines, cache_hit)。"""
    key = cache_key_for(path, kind, max_pages)
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, key + ".txt")
    if os.path.exists(cache) and os.path.getsize(cache) > 0:
        with open(cache, encoding="utf-8") as f:
            return f.read().splitlines(), True
    text = ""
    if kind == "digital":
        try:
            import fitz

            doc = fitz.open(path)
            text = "\n".join(pg.get_text("text") for pg in doc)
            doc.close()
        except Exception:  # noqa: BLE001
            text = ""
        if len(text.strip()) <= 200:
            # 误判的扫描件：兜底 OCR
            try:
                res = route_parse(path, prefer="rapidocr", max_pages=max_pages)
                text = "\n".join(b.text for pg in (res.pages or []) for b in (pg.blocks or []) if b.text)
            except Exception:  # noqa: BLE001
                pass
    else:
        res = route_parse(path, prefer="rapidocr", max_pages=max_pages)
        text = "\n".join(b.text for pg in (res.pages or []) for b in (pg.blocks or []) if b.text)
    lines = text.splitlines()
    if text.strip():
        with open(cache, "w", encoding="utf-8") as f:
            f.write(text)
    return lines, False


def _phase_order(rec):
    cat, kind = rec["category"], rec["kind"]
    if kind == "digital":
        return 0
    if cat == "questions":
        return 1
    if cat == "notes":
        return 2
    return 3  # textbooks / other scanned


def select_files(manifest, phase):
    files = manifest["files"]
    if phase == "digital":
        files = [r for r in files if r["kind"] == "digital"]
    elif phase == "questions":
        files = [r for r in files if r["kind"] != "digital" and r["category"] == "questions"]
    elif phase == "notes":
        files = [r for r in files if r["kind"] != "digital" and r["category"] == "notes"]
    elif phase == "textbooks":
        files = [r for r in files if r["kind"] != "digital" and r["category"] not in ("questions", "notes")]
    # all: keep all, sort by phase order then subject
    files.sort(key=lambda r: (_phase_order(r), r["subject"], r["name"]))
    return files


# PDF 抽出的文本常缺「目录」行（共享解析器靠它翻 started），且有页眉噪声。
# 这里做轻量归一化，不碰共享解析器，零风险。
_RE_PAGE_HEADER = re.compile(r"^第\s*\d+\s*页\s*(?:共\s*\d+\s*页)?$")
_RE_TOC_LINE = re.compile(r"^目\s*录$")


def normalize_pdf_lines(lines):
    out = []
    has_toc = False
    for ln in lines:
        s = (ln or "").strip()
        if not s:
            continue
        if _RE_PAGE_HEADER.match(s):
            continue
        if _RE_TOC_LINE.match(s):
            has_toc = True
        out.append(s)
    if out and not has_toc:
        out.insert(0, "目录")  # 强制 parse_questions 的 started=True
    return out


_RE_EXERCISE = re.compile(r"^习题\s*(\d+)\s*[-—－~.]\s*(\d+)(.*)$")
_RE_EXERCISE_COMPACT = re.compile(r"^习题\s*(\d)(\d+)(.*)$")
_RE_EXERCISE_NOISE = re.compile(
    r"更新公众号|控制考研咨询|基础习题册|答案册|题目册|课程咨询|全程保姆班|扫码|二维码|【考点|"
    r"真橙控制|专注自动化|bilibili|blibili"
)
_RE_SOURCE_MARKER = re.compile(r"[（(]\s*(?:19|20)\d{2}\s*年?[^）)]{2,60}[）)]")
_RE_FIGURE_REF = re.compile(r"如图|下图|结构图|曲线图|相平面|示意图|图中|所示")


def _clean_exercise_line(raw):
    s = re.sub(r"【(?:公众号|微信|QQ)[^】]*】", "", (raw or "")).strip()
    if not s or _RE_EXERCISE_NOISE.search(s):
        return ""
    if len(s) < 12 and (s.startswith("专题") or s in ("数学模型", "自动控制原理")):
        return ""
    return s


def _exercise_blocks(lines):
    blocks = {}
    current = None
    for raw in lines:
        s = _clean_exercise_line(raw)
        if not s:
            continue
        match = _RE_EXERCISE.match(s) or _RE_EXERCISE_COMPACT.match(s)
        if match:
            current = f"{match.group(1)}-{match.group(2)}"
            blocks[current] = []
            tail = _clean_exercise_line(match.group(3))
            if tail:
                blocks[current].append(tail)
        elif current is not None:
            blocks[current].append(s)
    return blocks


def _exercise_options(text):
    matches = list(re.finditer(r"\(([a-fA-F])\)\s*", text))
    if len(matches) < 2:
        return None, text
    options = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[match.end() : end].strip()
        if value:
            options.append({"key": match.group(1).upper(), "text": I._norm(value)})
    return (options if len(options) >= 2 else None), text[: matches[0].start()].strip()


def exercise_question_issues(question):
    from services.ocr_math_guard import detect_math_corruption

    stem = question.get("stem") or ""
    issues = []
    if _RE_FIGURE_REF.search(stem):
        issues.append("figure_missing")
    if detect_math_corruption(stem).hit:
        issues.append("math_ocr_unverified")
    if len(_RE_SOURCE_MARKER.findall(stem)) > 1:
        issues.append("cross_question_source")
    options = question.get("options")
    if options and [o.get("key") for o in options] != list("ABCD"):
        issues.append("options_incomplete_reading")
    return issues


def select_importable_exercise_questions(questions, kind):
    if kind != "digital":
        return [], len(questions)
    importable = [q for q in questions if not exercise_question_issues(q)]
    return importable, len(questions) - len(importable)


def parse_exercise_questions(lines, answer_lines=None):
    """解析「习题1-1」题型，并按同编号答案册补齐答案与解析。"""
    qblocks = _exercise_blocks(lines)
    ablocks = _exercise_blocks(answer_lines or [])
    questions = []
    for no, body in qblocks.items():
        text = I._norm(" ".join(body))
        options, stem = _exercise_options(text)
        answer_text = I._norm(" ".join(ablocks.get(no, [])))
        answer_match = re.search(
            r"答案(?:选|为|是|[:：])?\s*[（(]?([A-F](?:\s*[,，、/]\s*[A-F])*)[）)]?",
            answer_text,
            re.IGNORECASE,
        )
        answer = re.sub(r"[^A-F]", "", answer_match.group(1).upper()) if answer_match else None
        if options:
            qtype = "multiple" if answer and len(answer) > 1 else "single"
        elif "判断" in stem:
            qtype = "judge"
        elif "填空" in stem:
            qtype = "fill"
        elif re.search(r"求|试|已知|设|计算|系统|传递函数|根轨迹|响应|误差", stem):
            qtype = "calc"
        else:
            qtype = "essay"
        analysis = answer_text or None
        if not answer and analysis:
            answer = "见解析"
        if len(stem) < 4:
            continue
        questions.append(
            {
                "stem": stem,
                "options": options,
                "answer": answer,
                "analysis": analysis,
                "qtype": qtype,
                "atype": "objective" if qtype in ("single", "multiple", "judge") else "subjective",
                "chapter": no.split("-", 1)[0],
                "no": no,
            }
        )
    return questions


def exercise_pair_key(name):
    return re.sub(r"(题目册|答案册)", "", name or "").strip()


def find_exercise_answer_record(manifest, rec):
    if "答案册" in rec["name"]:
        return None
    key = exercise_pair_key(rec["name"])
    if not key:
        return None
    for other in manifest["files"]:
        if "答案册" in other["name"] and exercise_pair_key(other["name"]) == key:
            return other
    return None


# PDF 笔记常是「第一章 → 1. xxx → 2. xxx」结构，没有共享解析器要求的「复习笔记」段。
# 这里给一个轻量兜底：短行且像标题 → 知识点，后续正文 → 描述。仅在共享解析返回 0 时启用。
_RE_KP_PDF_HEAD = re.compile(r"^(?:[一二三四五六七八九十]+[、.．]|\d+[．.、]|（\d+）|\d+\.\d+)\s*(.+)$")
_RE_KP_BAD = re.compile(r"^(?:图|表|解|答|说明|目录|更多|公众号|QQ|微信)[\d\s:：]*$")


def parse_kps_pdf(lines, subject, subject_id):
    kps = []
    chapter = None
    current = None
    buf = []

    def flush():
        if current and buf:
            current["desc"] = I._norm(" ".join(buf))[:1500]

    for raw in lines:
        s = (raw or "").strip()
        if not s:
            continue
        m_ch = I.RE_CHAPTER.match(s)
        if m_ch:
            flush()
            chapter = I._norm(m_ch.group(1)) or s
            current = None
            buf = []
            continue
        if len(s) < 80:
            mh = _RE_KP_PDF_HEAD.match(s)
            if mh:
                name = I._norm(mh.group(1))
                if name and 2 <= len(name) <= 80 and not _RE_KP_BAD.match(name):
                    flush()
                    current = {
                        "name": name,
                        "parent_name": None,
                        "chapter": chapter,
                        "subject": subject,
                        "subject_id": subject_id,
                        "desc": None,
                    }
                    kps.append(current)
                    buf = []
                    continue
        if current:
            buf.append(s)
    flush()
    return kps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", default="all", choices=["digital", "questions", "notes", "textbooks", "all"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="忽略断点记录，重跑全部（全库查重兜底，不会长重复）")
    ap.add_argument("--max-pages", type=int, default=0, help="单文件最多 OCR 页数（0=不限）")
    ap.add_argument("--root", default=ROOT, help="PDF 源目录；也可用环境变量 PDF_SOURCE_ROOT")
    ap.add_argument("--cache-only", action="store_true", help="源 PDF 缺失时，按缓存索引复现已 OCR 内容")
    ap.add_argument("--report-out", default=os.path.join(TEMP, "ingest_pdf_report.json"))
    args = ap.parse_args()
    if not args.cache_only and not os.path.isdir(args.root):
        ap.error(f"PDF 源目录不存在：{args.root}；如只复现已有 OCR，请使用 --cache-only")

    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    files = select_files(manifest, args.phase)
    max_pages = args.max_pages if args.max_pages > 0 else None
    if args.cache_only:
        cached_files = [r for r in files if find_cache_entry(r["rel"], r["kind"], max_pages)]
        print(f"[cache-only] indexed={len(cached_files)} without_cache={len(files) - len(cached_files)}")
        files = cached_files
    if args.limit:
        files = files[: args.limit]

    done = set()
    if os.path.exists(DONE_FILE):
        try:
            with open(DONE_FILE, encoding="utf-8") as f:
                done = set(json.load(f))
        except Exception:  # noqa: BLE001
            done = set()

    print(f"[phase={args.phase}] files={len(files)}  already_done={len(done)}")

    report = {
        "phase": args.phase,
        "files_total": len(files),
        "dry_run": args.dry_run,
        "cache_only": args.cache_only,
        "per_file": [],
        "totals": defaultdict(int),
        "errors": [],
    }

    if args.dry_run:
        conn = idx = subj_names = by_name = existing_kps = None
    else:
        conn = I.engine.connect()
        idx, idx_n = I.build_dedup_index(conn)
        print(f"[dedup] index from {idx_n} existing questions")
        by_name, subj_names = I.load_subjects(conn)
        existing_kps = I.load_existing_kps(conn)
        report["dedup_index_size"] = idx_n

    max_pages = args.max_pages if args.max_pages > 0 else None

    def prepare_record(rec):
        if args.cache_only:
            entry = find_cache_entry(rec["rel"], rec["kind"], max_pages)
            if entry is None:
                raise FileNotFoundError(f"缓存索引无匹配记录：{rec['rel']}")
            return entry["cache_key"], os.path.join(CACHE_DIR, entry["cache_file"]), True
        path = os.path.join(args.root, rec["rel"])
        return cache_key_for(path, rec["kind"], max_pages), path, False

    def load_record(rec):
        run_key, path, from_cache = prepare_record(rec)
        if from_cache:
            with open(path, encoding="utf-8") as f:
                return f.read().splitlines(), True, run_key
        lines, cached = extract_pdf_lines(path, rec["kind"], max_pages=max_pages)
        remember_cache(rec["rel"], run_key, run_key + ".txt", rec["kind"], max_pages, sum(len(line) for line in lines))
        return lines, cached, run_key

    t0 = time.time()
    for i, rec in enumerate(files, 1):
        rel = rec["rel"]
        name = rec["name"]
        frec = {
            "file": rel,
            "kind": rec["kind"],
            "category": rec["category"],
            "subject": None,
            "chars": 0,
            "questions_parsed": 0,
            "questions_answerable": 0,
            "questions_without_answer": 0,
            "questions_unverified_ocr": 0,
            "questions_rejected": 0,
            "answers_parsed": 0,
            "kps_parsed": 0,
            "inserted": 0,
            "merged": 0,
            "skipped": 0,
            "kp_inserted": 0,
            "kp_exists": 0,
            "error": None,
            "status": None,
            "parser": "standard",
            "cached": False,
            "cache_key": None,
        }
        try:
            run_key, _path, _from_cache = prepare_record(rec)
            frec["cache_key"] = run_key
            if run_key in done and not args.force:
                frec["status"] = "already_done"
                report["per_file"].append(frec)
                continue
            t1 = time.time()
            lines, cached, run_key = load_record(rec)
            frec["cached"] = cached
            report["totals"]["cached_files"] += int(cached)
            lines = normalize_pdf_lines(lines)
            frec["chars"] = sum(len(line) for line in lines)
            frec["elapsed_extract"] = round(time.time() - t1, 1)
            if not lines:
                frec["error"] = "no_text_extracted"
                frec["status"] = "failed"
                report["per_file"].append(frec)
                report["errors"].append({"file": rel, "error": frec["error"]})
                continue
            has_q, is_notes = I.classify_file(name)
            # 信任 manifest 的 category：模拟题/冲刺题等文件名不含「题库/习题」关键词，
            # 但 manifest 已正确标为 questions。
            do_questions = has_q or is_notes or rec["category"] == "questions"
            subject = subject_id = None
            if not args.dry_run:
                subject, subject_id = I.match_subject(rel, subj_names, by_name)
            frec["subject"] = subject
            qcat = "真题" if "真题" in name else ("习题" if ("习题" in name or "题库" in name) else "练习题")
            qs = I.parse_questions(lines, name) if do_questions else []
            if do_questions and not qs:
                if "答案册" in name:
                    frec["answers_parsed"] = len(_exercise_blocks(lines))
                    frec["parser"] = "exercise_answers"
                else:
                    answer_rec = find_exercise_answer_record(manifest, rec)
                    if answer_rec is not None:
                        answer_lines, _answer_cached, _answer_key = load_record(answer_rec)
                        paired = parse_exercise_questions(lines, answer_lines)
                        qs, rejected = select_importable_exercise_questions(paired, rec["kind"])
                        if rec["kind"] == "digital":
                            frec["questions_rejected"] = rejected
                        else:
                            frec["questions_unverified_ocr"] = rejected
                        frec["answers_parsed"] = sum(1 for q in paired if q.get("answer"))
                        frec["parser"] = "exercise_pair"
            frec["questions_parsed"] = len(qs)
            answerable = [q for q in qs if (q.get("answer") or "").strip()]
            if rec["kind"] != "digital" and frec["parser"] != "exercise_pair":
                frec["questions_unverified_ocr"] = len(answerable)
                answerable = []
            elif rec["kind"] == "digital":
                importable = [q for q in answerable if not exercise_question_issues(q)]
                frec["questions_rejected"] += len(answerable) - len(importable)
                answerable = importable
            frec["questions_answerable"] = len(answerable)
            frec["questions_without_answer"] = len(qs) - len(answerable)
            kps = I.parse_knowledge_points(lines, subject, subject_id)
            # 笔记类共享解析返回 0 时，用 PDF 轻量抽取兜底
            if not kps and rec["category"] == "notes":
                kps = parse_kps_pdf(lines, subject, subject_id)
            frec["kps_parsed"] = len(kps)
            report["totals"]["questions_parsed"] += len(qs)
            report["totals"]["questions_answerable"] += len(answerable)
            report["totals"]["questions_without_answer"] += len(qs) - len(answerable)
            report["totals"]["answers_parsed"] += frec["answers_parsed"]
            report["totals"]["kps_parsed"] += len(kps)

            is_answer_book = "答案册" in name
            expects_questions = do_questions and "错题本" not in name and not is_answer_book
            if frec["questions_unverified_ocr"]:
                frec["error"] = "unverified_ocr_questions"
            elif do_questions and is_answer_book and not frec["answers_parsed"]:
                frec["error"] = "no_answers_parsed"
            elif expects_questions and not qs:
                frec["error"] = "no_questions_parsed"
            elif expects_questions and not answerable:
                frec["error"] = "no_answerable_questions"
            elif rec["category"] == "notes" and not kps:
                frec["error"] = "no_knowledge_points_parsed"

            if frec["error"]:
                frec["status"] = "failed"
                report["errors"].append({"file": rel, "error": frec["error"]})
            elif args.dry_run:
                frec["status"] = "dry_run"
            else:
                write_errors = []
                for q in answerable:
                    act = I.write_question(conn, q, idx, subject, subject_id, name, qcat)
                    if act == "inserted":
                        frec["inserted"] += 1
                        report["totals"]["inserted"] += 1
                    elif act == "merged":
                        frec["merged"] += 1
                        report["totals"]["merged"] += 1
                    else:
                        frec["skipped"] += 1
                        report["totals"]["skipped"] += 1
                        if act.startswith("error"):
                            write_errors.append(act)
                kp_errors = 0
                if kps:
                    ki, ke, kerr = I.write_knowledge_points(conn, kps, existing_kps, subject_id)
                    frec["kp_inserted"] = ki
                    frec["kp_exists"] = ke
                    kp_errors = kerr
                    report["totals"]["kp_inserted"] += ki
                    report["totals"]["kp_exists"] += ke
                    report["totals"]["kp_errors"] += kerr
                if write_errors or kp_errors:
                    frec["error"] = f"write_errors:{len(write_errors) + kp_errors}"
                    frec["status"] = "failed"
                    report["errors"].append({"file": rel, "error": frec["error"], "details": write_errors[:5]})
                elif expects_questions and not (frec["inserted"] or frec["merged"]):
                    frec["error"] = "no_writable_questions"
                    frec["status"] = "failed"
                    report["errors"].append({"file": rel, "error": frec["error"]})
                else:
                    frec["status"] = "done"
                    done.add(run_key)
                    report["totals"]["files_done"] += 1
                conn.commit()
        except Exception as e:  # noqa: BLE001
            frec["error"] = f"{type(e).__name__}:{str(e)[:160]}"
            frec["status"] = "failed"
            report["errors"].append({"file": rel, "error": frec["error"]})
            if not args.dry_run:
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
        report["per_file"].append(frec)
        # 每 5 个文件落盘一次 done，保证可断点续跑
        if not args.dry_run and i % 5 == 0:
            with open(DONE_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted(done), f)
        if i % 3 == 0 or i == len(files) or frec.get("error"):
            print(
                f"[{i}/{len(files)}] {rel[:55]} kind={rec['kind']} "
                f"q={frec['questions_parsed']} ans={frec['answers_parsed']} "
                f"ins={frec['inserted']} kp={frec['kp_inserted']} err={frec['error']}"
            )

    if not args.dry_run:
        with open(DONE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(done), f)
        conn.commit()
        conn.close()

    report["elapsed_sec"] = round(time.time() - t0, 1)
    report["totals"] = dict(report["totals"])
    with open(args.report_out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\n=== SUMMARY ===")
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    print(f"report -> {args.report_out}")


if __name__ == "__main__":
    main()
