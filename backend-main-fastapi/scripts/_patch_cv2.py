# -*- coding: utf-8 -*-
p = r'D:\平台\backend-main-fastapi\services\circuit_vision.py'
s = open(p, encoding='utf-8').read()

# 1) 替换 _looks_like_garbage 实现
old_g = '''    @staticmethod
    def _looks_like_garbage(text: str) -> bool:
        """判断 VLM 输出是否为乱码（视觉塔失效时常见表现）。

        启发式：
        - 去除空白/标点后，中文字符 + 常见英文单词（the/a/is/this/图/电路/电阻）
          占比 < 20%；
        - 或者重复字符密度异常高（如 "火烧火烧火烧..."）；
        - 或者总长度 > 0 但可打印 ASCII 中"有意义字母序列"很少。
        """
        if not text:
            return False
        # 统计 CJK 字符
        cjk = sum(1 for ch in text if "\\u4e00" <= ch <= "\\u9fff")
        # 统计常见有意义词
        meaningful_words = ["the", "this", "is", "are", "and", "图", "电路", "电阻",
                            "电容", "电源", "二极管", "三极管", "输出", "输入", "节点",
                            "resistor", "capacitor", "diode", "transistor", "Vcc", "GND"]
        lower = text.lower()
        meaningful_hits = sum(lower.count(w.lower()) for w in meaningful_words)
        # 重复字符检测：把字符串压成"相邻去重"，如果长度只剩 < 30%，说明重复严重
        compact: List[str] = []
        for ch in text:
            if not compact or compact[-1] != ch:
                compact.append(ch)
        ratio = len(compact) / max(len(text), 1)

        if cjk < 5 and meaningful_hits < 1 and len(text) > 50:
            return True
        if ratio < 0.3 and len(text) > 100:
            return True
        return False'''

new_g = '''    @staticmethod
    def _looks_like_garbage(text: str) -> bool:
        """判断 VLM 输出是否为乱码（视觉塔失效时常见表现）。

        启发式：
        1. CJK 字符极少 + 常见电路词汇命中为 0 + 文本较长 → 乱码。
        2. 周期性重复：取前 2~8 字符作为候选 unit，若 text 几乎由该 unit 重复而成 → 乱码。
        3. 相邻去重后长度 < 原文 30%（单字符重复，如 "aaaa..."）→ 乱码。
        """
        if not text:
            return False
        cjk = sum(1 for ch in text if "\\u4e00" <= ch <= "\\u9fff")
        meaningful_words = ["the", "this", "is", "are", "and", "图", "电路", "电阻",
                            "电容", "电源", "二极管", "三极管", "输出", "输入", "节点",
                            "resistor", "capacitor", "diode", "transistor", "Vcc", "GND"]
        lower = text.lower()
        meaningful_hits = sum(lower.count(w.lower()) for w in meaningful_words)

        # 条件 1：几乎无 CJK 且无有意义词
        if cjk < 5 and meaningful_hits < 1 and len(text) > 50:
            return True

        # 条件 2：周期重复（"火烧火烧..."、"a a a a..."）
        n = len(text)
        if n > 100:
            for unit_len in range(2, 9):
                unit = text[:unit_len]
                # 检查 text 是否≈ unit 重复
                repeats = n // unit_len
                expected = unit * repeats
                # 允许末尾截断
                if text.startswith(expected) or text[:len(expected)] == expected:
                    return True
                # 高相似度：超过 80% 位置匹配
                mismatches = sum(1 for i, ch in enumerate(text) if ch != unit[i % unit_len])
                if mismatches / n < 0.15:
                    return True

        # 条件 3：单字符重复
        compact: List[str] = []
        for ch in text:
            if not compact or compact[-1] != ch:
                compact.append(ch)
        ratio = len(compact) / max(n, 1)
        if ratio < 0.3 and n > 100:
            return True
        return False'''

assert old_g in s, "old garbage block not found"
s = s.replace(old_g, new_g)

# 2) 修 _cross_check：从 "R1=10kΩ" 这种标签里提取首位号
old_cc = '''        known_designators = {c.get("designator", "") for c in components}
        # 位号正则：R1, C10, Q2, U1, D1, Vcc 等（Vcc/GND 是节点不是元件，跳过）
        refdes_re = re.compile(r"^([RCLDQUJVFSW]|RT|CN|JP|K)\\d{1,4}[A-Z]?$")
        extras: List[Dict[str, Any]] = []
        for label in ocr_labels:
            lab = label.strip()
            if not lab or len(lab) > 20:
                continue
            if lab in {"GND", "VCC", "Vdd", "Vss", "Vin", "Vout"}:
                continue  # 这些是节点名，后面并入 nodes
            if refdes_re.match(lab) and lab not in known_designators:
                extras.append({
                    "designator": lab,
                    "type": "unknown",
                    "value": "unknown",
                    "net_nodes": ["unknown"],
                    "confidence": "low",
                    "source": "ocr_only",
                })
        return components + extras'''

new_cc = '''        known_designators = {c.get("designator", "") for c in components}
        # 位号正则：从 "R1=10kΩ"、"C1 100µF"、"Q1" 这类标签开头提取 R1/C1/Q1
        refdes_extract = re.compile(r"^\\s*([RCLDQUJVFSW]|RT|CN|JP|K)\\d{1,4}[A-Z]?")
        extras: List[Dict[str, Any]] = []
        seen_extras = set()
        for label in ocr_labels:
            lab = label.strip()
            if not lab or len(lab) > 30:
                continue
            if lab in {"GND", "VCC", "Vdd", "Vss", "Vin", "Vout", "+Vout", "+5V", "+12V", "AC220V"}:
                continue  # 这些是节点/电源名，后面并入 nodes
            m = refdes_extract.match(lab)
            if not m:
                continue
            desg = m.group(1)
            if desg in known_designators or desg in seen_extras:
                continue
            seen_extras.add(desg)
            extras.append({
                "designator": desg,
                "type": "unknown",
                "value": "unknown",
                "net_nodes": ["unknown"],
                "confidence": "low",
                "source": "ocr_only",
                "raw_label": lab,
            })
        return components + extras'''

assert old_cc in s, "old cross_check block not found"
s = s.replace(old_cc, new_cc)

open(p, 'w', encoding='utf-8').write(s)
print("patched ok")
