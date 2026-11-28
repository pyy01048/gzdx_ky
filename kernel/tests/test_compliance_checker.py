# -*- coding: utf-8 -*-
"""compliance_checker：40 fixture 必测（20 误报用例 + 20 违禁用例）。

红线（验收规范 §6.4）：误报 = 0，检出 = 100%。
误报用例：违禁词出现在注释/字符串/合法标识符子串中 → 不得报违规；
违禁用例：真实代码位置使用违禁头/函数/文件 I/O → 必须报且行号正确。
"""

import pytest

from kernel.compliance_checker import (
    MODE_EXAM,
    MODE_STRICT,
    check,
    strip_comments_and_strings,
)

# --------------------------------------------------------------------------- #
# 20 个误报用例：全部应 compliant=True（零误报红线）
# --------------------------------------------------------------------------- #
FALSE_POSITIVE_FIXTURES = [
    # --- 注释类 ---
    ("// 不要用 gets 函数", "int main(void){return 0;}"),
    ('/* system("rm") 是危险调用 */', "int x = 1;"),
    ("行尾注释提到 fork execve", "int a;  // fork(); execve(0);"),
    ("块注释跨行含 fopen", '/*\nfopen("a","r");\nsystem(1);\n*/\nint b;'),
    ("中文注释里 <windows.h>", "// windows.h 不能用在考场\nint c;"),
    ("注释里有 #include 字样", "// #include <stdio.h> 别忘了\nint d;"),
    # --- 字符串字面量类 ---
    ('printf 输出 "gets"', 'printf("gets is banned");'),
    ("字符串含 system", 'puts("do not use system()");'),
    ("字符串含 exec", 'char *s = "execvp";'),
    ("转义引号内违禁词", r'printf("say \"qsort\" loudly");'),
    ("字符常量单引号", "char ch = '\\''; char q = '\"';"),
    ("多段字符串拼接", 'char *a = "fork"; char *b = "popen";'),
    # --- 合法标识符子串/同名变量类 ---
    ("exec_prefix 不是 exec*", "int exec_prefix = 0;"),
    ("executable 单词非函数", "char *executable_name;"),
    ("my_system_helper 自定义名", "void my_system_helper(void){}"),
    ("fopen_s 变量名未调用", "int fopen_flag = 0;"),
    ("nextget 含 get 子串", "int nextget = 3;"),
    ("requeue 含 q 无关", "void requeue(void){}"),
    ("search 含 bsearch 子串", "int search_count = 5;"),
    ("executed 过去分词", "int executed = 1;"),
]


@pytest.mark.parametrize(
    "name,src",
    FALSE_POSITIVE_FIXTURES,
    ids=[f"fp{i + 1:02d}-{n[:12]}" for i, (n, _) in enumerate(FALSE_POSITIVE_FIXTURES)],
)
def test_false_positive_zero(name, src, compliance_cfg):
    rep = check(src, compliance_cfg, MODE_EXAM)
    assert rep.compliant, f"误报红线违反[{name}]: {rep.to_dict()}"
    assert rep.violations == ()


# --------------------------------------------------------------------------- #
# 20 个违禁用例：全部必须检出（100% 检出红线），并断言行号
# --------------------------------------------------------------------------- #
def _v(src_line_pairs, expect_token, expect_rule, line):
    return ("\n".join(src_line_pairs), expect_token, expect_rule, line)


VIOLATION_FIXTURES = [
    # (源码, 期望 token, 期望 rule, 期望行号)
    ("#include <windows.h>\nint main(){return 0;}", "windows.h", "header_not_allowed", 1),
    ("#include <conio.h>\nint a;", "conio.h", "header_not_allowed", 1),
    ("#include <thread>\nint a;", "thread", "header_not_allowed", 1),
    ("int main(){\n  gets(buf);\n}", "gets", "banned_function", 2),
    ('a=1;\nb=2;\nsystem("ls");', "system", "banned_function", 3),
    ('FILE *f = fopen("x", "r");', "fopen", "file_io", 1),
    ("fclose(f);", "fclose", "file_io", 1),
    ("pid_t p = fork();", "fork", "banned_function", 1),
    ("execvp(cmd, argv);", "execvp", "banned_function", 1),
    ('execl("/bin/sh", 0);', "execl", "banned_function", 1),
    ('FILE *g = popen("ls", "r");', "popen", "banned_function", 1),
    ("qsort(a, n, sizeof(int), cmp);", "qsort", "banned_function", 1),
    ("bsearch(&k, a, n, sz, cmp);", "bsearch", "banned_function", 1),
    ('fscanf(f, "%d", &x);', "fscanf", "file_io", 1),
    ('fprintf(stderr, "e");', "fprintf", "file_io", 1),
    ('remove("tmp.txt");', "remove", "file_io", 1),
    ("// 注释 gets\ngets(buf);", "gets", "banned_function", 2),
    ('printf("safe");\nfwrite(b,1,1,f);', "fwrite", "file_io", 2),
    ("int x;\nint y;\nrewind(f);", "rewind", "file_io", 3),
    # exam 模式 C++ 子集允许 algorithm——改用非白名单头验证多行 include 定位
    ("#include <unordered_map>\nint a;", "unordered_map", "header_not_allowed", 1),
]


@pytest.mark.parametrize("src,tok,rule,line", VIOLATION_FIXTURES, ids=[f"vio{i + 1:02d}" for i in range(20)])
def test_violation_detected_100(src, tok, rule, line, compliance_cfg):
    rep = check(src, compliance_cfg, MODE_EXAM)
    assert not rep.compliant
    hit = [v for v in rep.violations if v.token == tok]
    assert hit, f"漏检红线违反: {tok} -> {rep.to_dict()}"
    assert hit[0].rule == rule
    assert hit[0].line == line
    assert rep.grade == "hard_fact"


class TestModes:
    def test_strict_rejects_cpp_header(self, compliance_cfg):
        src = "#include <vector>\nint a;"
        assert check(src, compliance_cfg, MODE_EXAM).compliant  # exam 允许子集
        rep = check(src, compliance_cfg, MODE_STRICT)
        assert not rep.compliant
        assert rep.violations[0].rule == "header_not_allowed"

    def test_exam_allows_cpp_subset(self, compliance_cfg):
        src = "#include <vector>\n#include <cstdio>\nint main(){return 0;}"
        assert check(src, compliance_cfg, MODE_EXAM).compliant

    def test_unknown_mode_raises(self, compliance_cfg):
        with pytest.raises(ValueError):
            check("int a;", compliance_cfg, "loose")

    def test_banned_functions_both_modes(self, compliance_cfg):
        src = "gets(buf);"
        assert not check(src, compliance_cfg, MODE_EXAM).compliant
        assert not check(src, compliance_cfg, MODE_STRICT).compliant


class TestStreamsAndDedup:
    def test_stdin_stdout_stderr_allowed(self, compliance_cfg):
        src = 'fgets(line, 10, stdin); fputs(out, stdout); fprintf(stderr, "x");'
        # fgets/fputs/fprintf 属文件 I/O 族——stdin/stdout/stderr 本身不报
        rep = check(src, compliance_cfg, MODE_EXAM)
        assert all(v.token not in ("stdin", "stdout", "stderr") for v in rep.violations)

    def test_same_line_same_token_reported_once(self, compliance_cfg):
        rep = check("system(a); system(b);", compliance_cfg, MODE_EXAM)
        assert len([v for v in rep.violations if v.token == "system"]) == 1

    def test_to_dict_shape(self, compliance_cfg):
        rep = check("gets(x);", compliance_cfg, MODE_EXAM)
        d = rep.to_dict()
        assert d["grade"] == "hard_fact" and d["mode"] == MODE_EXAM
        assert d["violations"][0]["token"] == "gets"


class TestStripper:
    def test_line_numbers_preserved(self):
        src = "int a;\n// gets\nint b;\n/* block\n   system\n*/ int c;"
        clean = strip_comments_and_strings(src)
        assert clean.count("\n") == src.count("\n")
        assert "gets" not in clean and "system" not in clean

    def test_string_content_removed_quotes_kept(self):
        clean = strip_comments_and_strings('char *s = "qsort(bsearch)";')
        assert "qsort" not in clean
        assert '"qsort' not in clean

    def test_exec_prefix_regex(self, compliance_cfg):
        # exec 前缀但非 exec[lv][ep]* 的合法词不误报；真 exec* 全检出
        ok = check("int exec_prefix; execute_task();", compliance_cfg, MODE_EXAM)
        assert ok.compliant
        bad = check('execve(p, a, e); execlp("sh", 0);', compliance_cfg, MODE_EXAM)
        toks = {v.token for v in bad.violations}
        assert toks == {"execve", "execlp"}
