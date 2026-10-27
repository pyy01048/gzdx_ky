# -*- coding: utf-8 -*-
p = r'D:\平台\backend-main-fastapi\services\circuit_vision.py'
s = open(p, encoding='utf-8').read()
old = r'refdes_extract = re.compile(r"^\\s*([RCLDQUJVFSW]|RT|CN|JP|K)\\d{1,4}[A-Z]?")'
new = r'refdes_extract = re.compile(r"^\\s*((?:[RCLDQUJVFSW]|RT|CN|JP|K)\\d{1,4}[A-Z]?)")'
assert old in s, "regex not found"
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print("ok")
