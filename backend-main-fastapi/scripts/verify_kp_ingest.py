# -*- coding: utf-8 -*-
"""入库时知识点抽取的验证脚本（真跑本地模型 + 打印真实 SQL 输出）。

分两步：
  1) `--selftest`：不碰模型，只验质量门禁 / 学科双路判定 / JSON 解析
  2) 默认：对指定的 3 篇已入库文档重跑入库，打印 knowledge_points 新增行

安全：**不删任何文件**；只 INSERT knowledge_points。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

#: 验证用的 3 篇真实已入库文档（跨 3 个细分学科：数电 / 模电 / 408）
VERIFY_DOC_IDS = [789, 308, 2372]

#: 默认只跑入库钩子（不新增 documents 行）；--reingest 才重跑全管线
REINGEST = False


def selftest() -> int:
    """不调模型，验证纯函数层：噪声 / 标题 / 释义 / 学科双路 / JSON 解析。"""
    from services import kp_extract as K

    print("=== 质量门禁：名称噪声 ===")
    for n in ["555", "(1)", "_2", "???", "1、", "", "栈", "栅极",
              "a_{2}gg{}", "第1章", "知识点", "卡诺图", "Moore"]:
        print(f"  {n!r:14} noise={K.is_noise_name(n)}  title={K.name_is_title_only(n)}")

    print("\n=== 质量门禁：释义实质性 ===")
    cases = [
        ("卡诺图", "卡诺图是将逻辑函数化为最小项之和并用相邻最小项合并化简的图形方法。", True),
        ("卡诺图", "卡诺图。", False),
        ("卡诺图", "就是卡诺图", False),
        ("卡诺图", "", False),
        ("Moore", "Moore model is a clocked sequential circuit whose output depends on inputs and current state.", True),
        # 实测敷衍释义：串 → "字符序列，用于存储字符串数据。"
        ("串", "字符序列，用于存储字符串数据。", False),
    ]
    ok = True
    for name, desc, want in cases:
        got = K.desc_is_substantive(desc, name)
        flag = "OK " if got == want else "FAIL"
        if got != want:
            ok = False
        print(f"  [{flag}] {name!r} / {desc[:28]!r} → {got} (期望 {want})")

    print("\n=== 质量门禁：宣传/版权页噪声（实测真实抽出来的垃圾）===")
    junk = [
        ("数字课程资源", "包括重点和难点讲解视频、PPT电子教案、EDA应用举例及习题等。"),
        ("课程有效期", "课程绑定后一年为数字课程使用有效期。"),
        ("硬件限制", "部分内容无法在手机端显示，请按提示通过电脑访问学习。"),
        ("自测题和参考答案", "提供自测题及习题的参考答案，方便学生自主学习。"),
        ("场效应管", "一种利用外部电场控制电流流动的半导体器件，广泛应用于放大和开关电路中。"),
    ]
    for name, desc in junk:
        got = K.is_boilerplate(name, desc)
        want = name != "场效应管"      # 场效应管是真知识点，不能误杀
        flag = "OK " if got == want else "FAIL"
        if got != want:
            ok = False
        print(f"  [{flag}] boilerplate={got} | {name}")

    print("\n=== 质量门禁：泛化元词（实测抽出来的「算法描述」）===")
    generic = ["算法描述", "算法步骤", "具体步骤", "本章小结", "详细说明",
               "线性表合并算法描述", "表达式求值的具体步骤", "卡诺图", "场效应管",
               "排序算法", "线性表的插入操作"]
    for g in generic:
        got = K.name_is_generic(g)
        want = g not in ("卡诺图", "场效应管", "排序算法", "线性表的插入操作")
        flag = "OK " if got == want else "FAIL"
        if got != want:
            ok = False
        print(f"  [{flag}] generic={got} | {g}")

    print("\n=== 质量门禁：天书章节名（PDF 字体缺失）===")
    bad = "10.2.1 " + "".join(chr(x) for x in
                             [0x2b58, 0x4c18, 0x2b65, 0x441f, 0x34f4, 0x1840,
                              0x2cb4, 0x1bed, 0x11f6, 0x28a9, 0x4016])
    r1 = K.sanitize_chapter(bad, "第10章 脉冲波形的产生和整形")
    r2 = K.sanitize_chapter("第10章 脉冲波形的产生和整形", "")
    if r1 != "第10章 脉冲波形的产生和整形":
        ok = False
    if r2 != "第10章 脉冲波形的产生和整形":
        ok = False
    print(f"  [{'OK ' if r1.startswith('第10章') else 'FAIL'}] 天书章→兜底: {r1!r}")
    print(f"  [{'OK ' if r2.startswith('第10章') else 'FAIL'}] 正常章保留: {r2!r}")

    print("\n=== 质量门禁：近似重复（模型同段吐重复项）===")
    d1 = ("脉冲波形的产生和整形是通过各种电路将一个基本脉冲信号转换为所需形状、"
          "宽度或频率的脉冲信号的过程。这一过程在数字电路设计中常用。")
    nd_cases = [
        ("脉冲整形A", d1, {"脉冲整形": "脉冲整形"}, [K._bigrams(d1)], True),
        ("脉冲整形", "完全不同的另一段足够长的释义内容用于验证长度门槛是否生效",
         {"脉冲整形": "脉冲整形"}, [], True),
        ("卡诺图",
         "卡诺图是将逻辑函数化为最小项之和并用相邻最小项合并化简的图形方法，可减少门电路数量。",
         {"脉冲整形": "x"}, [], False),
    ]
    for name, desc, sn, sg, want in nd_cases:
        got = K.is_near_duplicate(name, desc, sn, sg)
        flag = "OK " if got == want else "FAIL"
        if got != want:
            ok = False
        print(f"  [{flag}] near_dup={got} | {name}")

    print("\n=== 学科双路判定（不一致时以模型为准 + 留痕）===")
    cases2 = [
        ("模拟电子技术", "数字电子技术", True, "", "模型说模电、关键词说数电"),
        ("数字电子技术", "数字电子技术", True, "", "两路一致"),
        ("数模电", "", False, "", "模型给压平标签 → 非法，走 fallback"),
        ("数模电", "数字电子技术", True, "", "模型给压平标签 → 关键词兜底"),
        ("电路", "数字电子技术", True, "", "模型说电路（非法细分）→ 关键词兜底"),
        ("", "", False, "", "两路皆无 → fallback"),
        ("公共课", "政治", True, "", "模型给公共课 → 关键词兜底"),
        ("数字电子技术", "", False, "计算机学科专业基础408",
         "408 文档 → 文档学科锁（防串/数组被标成数电）"),
        ("数字电子技术", "", False, "信号与系统",
         "信号与系统文档 → 文档学科锁"),
        ("数字电子技术", "", False, "政治",
         "文档学科在 CORE 内 → 不锁，仍走模型"),
        ("数字电子技术", "数字电子技术", True, "其他",
         "文档学科=其他（兜底值）→ 不锁，走模型"),
    ]
    for m, k, conf, ds, desc in cases2:
        subj, src = K.resolve_subject(m, k, conf, ds)
        print(f"  {desc:36} → {subj} [{src}]")

    print("\n=== 6 个细分学科未被压平 ===")
    from services.taxonomy import CORE_SUBJECTS

    print("  ", CORE_SUBJECTS)
    assert CORE_SUBJECTS == ["数字电子技术", "模拟电子技术", "数学", "英语",
                             "政治", "真题综合"], "细分学科枚举被改动！"
    for s in CORE_SUBJECTS:
        subj, src = K.resolve_subject(s, "", False, "")
        assert subj == s, f"{s} 归一后变成 {subj}"
    print("   6 科全部原样保留 ✓")

    print("\n=== 模型输出 JSON 解析（容忍包裹/废话）===")
    for raw in ['[{"name":"A","description":"xxxxx"}]',
                '好的，结果如下：\n```json\n[{"name":"B"}]\n```\n希望有用',
                '```\n[{"name":"C"}]\n```',
                '没有知识点',
                '']:
        got = K._parse_json_array(raw)
        print(f"  {raw[:38]!r:44} → {len(got)} 项")

    print("\nSELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def run_real(doc_ids: list) -> int:
    """真跑：对已入库文档跑知识点抽取钩子，展示 knowledge_points 新增行。

    默认**不重跑入库**（避免往documents 里塞重复文档行）：
    直接对已入库文档调用 `services.kp_extract.extract_kps_for_document`——
    这正是 `smart_ingest_file` 入库成功后调用的同一个函数。
    `--reingest` 才真的重跑 `smart_ingest_file` 全管线。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stdout,
    )
    from database import SessionLocal
    from services.kp_extract import extract_kps_for_document
    from services.smart_ingest import smart_ingest_file

    def q(sql, args=()):
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    before_total = q("SELECT COUNT(*) FROM knowledge_points")[0][0]
    print(f"【基线】knowledge_points 总数 = {before_total}")
    print(f"【模式】{'重跑全管线 smart_ingest_file' if REINGEST else '只跑入库钩子 kp_extract（不新增 documents 行）'}\n")

    for did in doc_ids:
        rows = q("SELECT file_name, file_path, subject, content FROM documents WHERE id=?",
                 (did,))
        if not rows:
            print(f"跳过 doc#{did}：不存在")
            continue
        fn, fp, subj, content = rows[0]
        print(f"\n{'='*72}\ndoc#{did}  {fn}\n  库内学科={subj}  正文={len(content or '')}字")

        sdb = SessionLocal()
        try:
            if REINGEST:
                r = smart_ingest_file(sdb, fp, dry_run=False, force=True,
                                      extract_kp=True)
                kp = r.get("knowledge_points") or {}
                print(f"  入库状态={r.get('status')} 新doc_id={r.get('doc_id')}")
            else:
                kp = extract_kps_for_document(
                    sdb, doc_id=did, text=content or "", file_name=fn,
                    doc_subject=subj or "",
                )
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ 异常: {type(e).__name__}: {e}")
            kp = {}
        finally:
            try:
                sdb.close()
            except Exception:
                pass

        print(f"  KP统计={json.dumps(kp, ensure_ascii=False)}")
        for e in (kp.get("errors") or [])[:5]:
            print(f"    KP错误: {e}")

    after_total = q("SELECT COUNT(*) FROM knowledge_points")[0][0]
    print(f"\n{'='*72}")
    print(f"【结果】knowledge_points {before_total} → {after_total} "
          f"(净增 {after_total - before_total})")

    print("\n【新增知识点（按 extract_source 定位本轮入库）】")
    rows = q("""SELECT id, name, subject, subject_source, chapter,
                       document_id, source_chunk_id, source_chunk_index,
                       exam_frequency, extract_source,
                       substr(COALESCE(description,''),1,60)
                FROM knowledge_points
                WHERE extract_source='smart_ingest'
                ORDER BY id DESC LIMIT 40""")
    if not rows:
        print("  （无新增行）")
    for r in rows:
        print(f"  #{r[0]:<6} {r[1][:26]:<28} {r[2]:<8} src={r[3]:<18} "
              f"doc={r[5]} chunk={r[6]}/{r[7]} freq={r[8]}")
        print(f"         章: {(r[4] or '')[:50]}")
        print(f"         释: {r[10]}")

    print("\n【新增知识点的学科分布】")
    for s, c in q("""SELECT subject, COUNT(*) FROM knowledge_points
                      WHERE extract_source='smart_ingest'
                      GROUP BY 1 ORDER BY 2 DESC"""):
        print(f"  {s}: {c}")
    # 边界检查：绝不能出现「压平标签」；且必须是项目登记过的真学科。
    # 注意：408/电路/信号与系统 等专业课支撑科目是**合法**结果（文档学科锁），
    # 不是越界—— 越界指的是被压平成「数模电/公共课」，或出现未登记科目。
    from services.taxonomy import ALL_SUBJECTS

    ph = ",".join(["?"] * len(ALL_SUBJECTS))
    bad_sql = (
        "SELECT DISTINCT subject FROM knowledge_points "
        "WHERE extract_source='smart_ingest' "
        "AND (subject LIKE '%数模电%' OR subject LIKE '%公共课%' "
        f"OR subject NOT IN ({ph}))")
    bad = q(bad_sql, tuple(ALL_SUBJECTS))
    print(f"  压平/未登记学科: {bad if bad else '无 ✓'}")
    core_hit = q("""SELECT subject, COUNT(*) FROM knowledge_points
                    WHERE extract_source='smart_ingest'
                      AND subject IN ('数字电子技术','模拟电子技术','数学',
                                      '英语','政治','真题综合')
                    GROUP BY 1""")
    print(f"  其中落在 6 个细分学科内的: {core_hit}")

    print("\n【溯源反查：新知识点 → 文档 → 分块】")
    for r in q("""SELECT kp.id, kp.name, d.file_name, d.subject,
                         substr(c.text,1,70)
                  FROM knowledge_points kp
                  JOIN documents d ON d.id=kp.document_id
                  LEFT JOIN knowledge_chunks c ON c.id=kp.source_chunk_id
                  WHERE kp.extract_source='smart_ingest'
                  ORDER BY kp.id DESC LIMIT 6"""):
        print(f"  KP#{r[0]} {r[1][:22]:<24} ←《{r[2][:30]}》(学科{r[3]})")
        print(f"      原文: {(r[4] or '(无分块)')[:70]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--ids", default=",".join(str(i) for i in VERIFY_DOC_IDS))
    ap.add_argument("--reingest", action="store_true",
                    help="重跑 smart_ingest_file 全管线（会新增 documents 行）")
    ap.add_argument("--max-chunks", type=int, default=None,
                    help="单文档最多抽几块（封顶本地模型负载）")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    global REINGEST
    REINGEST = args.reingest
    if args.max_chunks:
        os.environ["SMART_INGEST_KP_MAX_CHUNKS"] = str(args.max_chunks)
    ids = [int(x) for x in args.ids.split(",") if x.strip()]
    return run_real(ids)


if __name__ == "__main__":
    sys.exit(main())