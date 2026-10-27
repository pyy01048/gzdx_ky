-- =============================================================================
-- 106 subject_removals：科目删除墓碑表
-- 依赖：081（subjects 表）、092（subject_config 可写视图 INSTEAD OF 触发器）
--
-- 问题（2026-10-19 线上实测复现）
-- -----------
-- DELETE /api/taxonomy/subjects/{科目} 返回 200「科目配置已删除」，
-- INSTEAD OF DELETE 触发器也真正删掉了 subjects 行（实测 id 54 消失），
-- 但**下一次 GET /api/taxonomy/subjects 该科目又回来了**
-- （实测复活成新行 id 55，is_custom=false）。
--
-- 根因
-- ----
-- services/taxonomy.py::ensure_subject_config_seeds 采用「按缺失补齐」：
-- ALL_SUBJECTS（CORE+MAJOR+EXT+CROSS）里的内置科目被删后，下一次列表查询
-- 就被判定为「缺失」而重新 INSERT。该函数 docstring 声称
-- 「不会复活用户删掉的行」——承诺与实现不符，且没有任何测试守护这句话。
--
-- 修复（墓碑机制）
-- ----------------
-- 1. 删除 / 重命名（旧名是内置科目）时往本表记一条墓碑；
-- 2. 所有播种类函数（ensure_subject_config_seeds /
--    subject_registry._seed_missing_engineering_subjects）播种前读墓碑，
--    命中者跳过——删了就是删了，不再自动补齐；
-- 3. 用户显式重建同名科目（POST /api/taxonomy/subjects）时清墓碑——
--    墓碑只挡「自动补齐」，不挡「显式加回」。
-- =============================================================================

CREATE TABLE IF NOT EXISTS subject_removals (
    subject    TEXT PRIMARY KEY,
    removed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE subject_removals IS
    '科目删除墓碑：播种类函数须跳过此处登记的科目名；显式重建时清除';
