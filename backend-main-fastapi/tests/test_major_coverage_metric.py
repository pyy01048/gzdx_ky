"""择校覆盖口径（`services/major_coverage.py`）的纯函数回归锁。

为什么要有这组用例：covered 率是择校页徽标和 `/api/quality` 的唯一口径来源，
而「能命中供给池」和「语料量达标」是两个数——#29 首版别名候选脚本把前者当后者
报，上限虚高了 5.3pt（85.0% vs 79.6%）才被拦住。这里把四条边界钉死，防止同类
口径混用再进任何下游报表。

本文件不连库、不建表（conftest 的临时库夹具一律不用），必须保持毫秒级。
"""
from __future__ import annotations


def test_decode_subjects_strips_codes_and_parenthetical_noise():
    """库内 exam_subjects 的真实格式：' | ' 拼接、(301) 代码前缀、数学（一）括注、JSON 数组。"""
    from services.major_coverage import decode_subjects

    assert decode_subjects('["思想政治理论", "英语一", "数学一", "专业课"]') == \
        ["思想政治理论", "英语一", "数学一", "专业课"]
    # 真库样例（2026-10-13 实测）：代码和罗马数字括注都要剥掉
    assert decode_subjects("(302)数学（二） | (204)英语（二） | (857)电子技术基础") == \
        ["数学", "英语", "电子技术基础"]
    assert decode_subjects("专业课（含有机化学）") == ["专业课"]
    assert decode_subjects(None) == []
    # 原生带空格的学科名要归一（supply 侧同样 _norm）
    assert decode_subjects("电路 原理") == ["电路原理"]


def test_professional_subject_skips_public_courses():
    """公共课人人必考，拿它匹配覆盖率会虚高到 98%，等于没信息量。"""
    from services.major_coverage import decode_subjects, professional_subject

    assert professional_subject(decode_subjects(
        "(301)数学（一） | (201)英语（一） | (802)通信类专业综合")) == "通信类专业综合"
    # 全是公共课 → None（该专业不进覆盖率分母）
    assert professional_subject(["数学一", "政治", "英语二"]) is None
    assert professional_subject([]) is None


def test_professional_subject_rejects_public_variants():
    """「自命题数学一」「英语或日语」这类变体本质仍是公共课，精确同名集合拦不住。

    首版别名候选脚本正是漏在这里，产出了「自命题数学一→数学」「英语或日语→英语」
    这种用人人必考语料刷覆盖率的建议。反向红线：「数学分析」「高等数学」是真自命题
    专业课，误判会把数学类专业的真实语料从分母里抹掉。
    """
    from services.major_coverage import decode_subjects, is_public_subject, professional_subject

    assert professional_subject(decode_subjects(
        "(302)数学（二） | (857)电子技术基础")) == "电子技术基础"
    assert professional_subject(["自命题数学一", "电子技术基础"]) == "电子技术基础"
    assert professional_subject(["英语或日语", "电路"]) == "电路"
    assert professional_subject(["自命题数学一"]) is None

    assert is_public_subject("自命题数学一") is True
    assert is_public_subject("英语或日语或自命题德语") is True
    assert is_public_subject("思想政治理论") is True
    assert is_public_subject("数学分析") is False
    assert is_public_subject("高等数学") is False
    assert is_public_subject("高等代数") is False
    assert is_public_subject("有机化学") is False
    assert is_public_subject("电子技术基础") is False


def test_coverage_state_boundaries():
    """四档边界。最要紧的一条：文档够多但 0 块 = unindexed，不能算 covered。"""
    from services.major_coverage import MIN_DOCUMENTS, coverage_state

    assert coverage_state(MIN_DOCUMENTS, 1) == "covered"
    assert coverage_state(MIN_DOCUMENTS, 0) == "unindexed"   # 数模电：186 篇 0 块
    assert coverage_state(MIN_DOCUMENTS - 1, 500) == "thin"  # 文档数不足，块再多也偏薄
    assert coverage_state(0, 0) == "uncovered"


def test_lookup_is_exact_plus_capability_suffix_only():
    """只允许精确同名和剥掉大纲「能力」后缀，其它一律算未覆盖（宁可少报不虚报）。"""
    from services.major_coverage import _lookup

    supply = {
        "数字电子技术": {"documents": 611, "chunks": 6595},
        "管理类联考综合": {"documents": 30, "chunks": 400},
    }
    assert _lookup("数字电子技术", supply)["chunks"] == 6595
    assert _lookup("管理类联考综合能力", supply)["documents"] == 30
    # 同科异名不许自动并——这正是必须人工过别名表的原因
    assert _lookup("电子技术基础", supply) == {}
    assert _lookup("数字电路", supply) == {}
    assert _lookup("", supply) == {}


def test_matched_rate_is_not_coverage_rate():
    """双口径分离：命中供给池 ≠ covered。混用就是 #29 首版那个错。"""
    from services.major_coverage import _lookup, coverage_state

    supply = {
        "数模电": {"documents": 186, "chunks": 0},      # 命中但无可检索语料
        "数字电子技术": {"documents": 611, "chunks": 6595},
        "通信原理": {"documents": 4, "chunks": 6},      # 命中但偏薄
    }
    majors = ["数模电", "数字电子技术", "通信原理", "半导体物理"]

    matched = sum(1 for ps in majors if _lookup(ps, supply))
    covered = sum(1 for ps in majors
                  if coverage_state(int(_lookup(ps, supply).get("documents") or 0),
                                    int(_lookup(ps, supply).get("chunks") or 0)) == "covered")
    assert matched == 3            # 命中率 3/4
    assert covered == 1            # covered 只有 1/4
    assert covered < matched       # 任何报表都必须区分这两者
