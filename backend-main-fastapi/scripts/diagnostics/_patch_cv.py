# -*- coding: utf-8 -*-
p = r'D:\平台\backend-main-fastapi\services\circuit_vision.py'
s = open(p, encoding='utf-8').read()

old1 = '''            return {
                "ok": False, "circuit_type": "unknown",
                "components": [], "connections": [], "nodes": [],
                "description": "",
                "question_hints": "",
                "engines": engines, "errors": errors,
                "elapsed_ms": int((time.time() - t0) * 1000),
            }'''
new1 = '''            return {
                "ok": False, "circuit_type": "unknown",
                "components": self._cross_check([], ocr_labels),
                "connections": [], "nodes": [],
                "description": "",
                "question_hints": "",
                "engines": engines, "errors": errors,
                "ocr_labels": ocr_labels,
                "elapsed_ms": int((time.time() - t0) * 1000),
            }'''

old3 = '''                "components": [], "connections": [], "nodes": [],
                "description": raw[:500],  # 保留原文便于排查
                "question_hints": "",
                "engines": engines, "errors": errors,
                "elapsed_ms": int((time.time() - t0) * 1000),'''
new3 = '''                "components": self._cross_check([], ocr_labels),
                "connections": [], "nodes": [],
                "description": raw[:500],  # 保留原文便于排查
                "question_hints": "",
                "engines": engines, "errors": errors,
                "ocr_labels": ocr_labels,
                "elapsed_ms": int((time.time() - t0) * 1000),'''

n1 = s.count(old1)
s = s.replace(old1, new1, 2)
n3 = s.count(old3)
s = s.replace(old3, new3, 1)
open(p, 'w', encoding='utf-8').write(s)
print(f"replaced old1={n1} old3={n3}")
