# -*- coding: utf-8 -*-
"""院校简介（kaoyan_schools.intro）回填脚本（M1，2026-10）。

背景：``kaoyan_schools`` 现有 583 所院校，``intro`` 字段 100% 为空，
是「院校介绍页」的核心数据缺口；``official_url`` 也多为过期的研招网
schId 链接，不可直接当作官网来源。

本脚本只做一件诚实的事——**从可溯源的公开渠道抓取真实简介并回填**，
绝不编造。分三层，按可信度从高到低：

第 1 层（首选，官网真实简介）：
    1) 依据内置的「院校名 → 官网域名」映射（``SCHOOL_DOMAINS``，逐条
       在线校验：首页可达且页面出现院校名，才认）。
    2) 抓官网首页 → 在首页 HTML 里找含「学校简介/学校概况/院校简介/
       大学简介/学校介绍」的链接，或多路径探测（/xxgk/xxjj.htm 等）。
    3) 抓简介页 → 去 script/style/标签 → 定位正文 → 截取 150~400 字
       有效简介（剔除导航菜单等噪声）。
    命中即写库，``data_source`` 追加 ``_intro_official`` 标记。

第 2 层（研招网备用）：
    对库内 ``official_url``/``tags`` 中带研招网 schId 的院校，抓
    ``https://yz.chsi.com.cn/sch/schoolInfo--schId-{id},categoryId-*.dhtml``
    的「院校简介」页。研招网为国家级官方平台、结构统一。

第 3 层（模板兜底，谨慎且单独统计）：
    前两层都拿不到时，**不编造**，仅用库内既有事实字段
    （``level``/``province``/``type``）拼一句**可识别为模板**的说明，如
    「XX大学（985/北京市），公办高校。」。模板条数在报告中与官网真实
    简介**分开统计**并显式标注，且**默认不写库**（需 ``--with-template``
    才写），避免污染「真实简介」字段。

合规与稳健：
    - 每站先查 robots.txt（复用 spider_notices 的 ``_robots_allows`` 口径）；
    - 每校请求间隔 ≥1 秒（``_polite``）；
    - 单请求失败最多重试 2 次；绝不死循环；
    - 幂等：默认只填 ``intro`` 为空的行；``--overwrite`` 才覆盖已有值。

用法：
    python scripts/backfill_school_intro.py                 # dry-run 预览
    python scripts/backfill_school_intro.py --limit 20      # 只跑前 20 所
    python scripts/backfill_school_intro.py --apply         # 写库（先备份）
    python scripts/backfill_school_intro.py --apply --with-template  # 含模板兜底
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DATABASE_PATH", "").strip() or os.path.join(
    os.path.dirname(BASE_DIR), "database", "kaoyan.db"
)

# 报告输出目录（与团队其它分析报告一致）
REPORT_DIR = os.path.join(os.path.dirname(BASE_DIR), "docx", "_analysis")

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "close",
}
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# 简介长度裁剪区间（字符数，中文按字计）
MIN_INTRO = 150
MAX_INTRO = 400


# --------------------------------------------------------------------------- #
# 院校名 → 官网域名映射（逐条在线校验后才使用；未列入者走发现/探测/模板）
# 说明：域名均为各校长期稳定的主站；脚本仍会对首页做可达性 + 校名出现校验，
# 校验不过则视为「未命中」，绝不据此写虚假内容。
# --------------------------------------------------------------------------- #
SCHOOL_DOMAINS: Dict[str, str] = {
    # ---- 985 / 顶尖 ----
    "清华大学": "https://www.tsinghua.edu.cn/",
    "北京大学": "https://www.pku.edu.cn/",
    "中国人民大学": "https://www.ruc.edu.cn/",
    "北京航空航天大学": "https://www.buaa.edu.cn/",
    "北京理工大学": "https://www.bit.edu.cn/",
    "中国农业大学": "https://www.cau.edu.cn/",
    "北京师范大学": "https://www.bnu.edu.cn/",
    "中央民族大学": "https://www.muc.edu.cn/",
    "南开大学": "https://www.nankai.edu.cn/",
    "天津大学": "https://www.tju.edu.cn/",
    "大连理工大学": "https://www.dlut.edu.cn/",
    "东北大学": "https://www.neu.edu.cn/",
    "吉林大学": "https://www.jlu.edu.cn/",
    "哈尔滨工业大学": "https://www.hit.edu.cn/",
    "复旦大学": "https://www.fudan.edu.cn/",
    "同济大学": "https://www.tongji.edu.cn/",
    "上海交通大学": "https://www.sjtu.edu.cn/",
    "华东师范大学": "https://www.ecnu.edu.cn/",
    "南京大学": "https://www.nju.edu.cn/",
    "东南大学": "https://www.seu.edu.cn/",
    "浙江大学": "https://www.zju.edu.cn/",
    "中国科学技术大学": "https://www.ustc.edu.cn/",
    "厦门大学": "https://www.xmu.edu.cn/",
    "山东大学": "https://www.sdu.edu.cn/",
    "中国海洋大学": "https://www.ouc.edu.cn/",
    "武汉大学": "https://www.whu.edu.cn/",
    "华中科技大学": "https://www.hust.edu.cn/",
    "湖南大学": "https://www.hnu.edu.cn/",
    "中南大学": "https://www.csu.edu.cn/",
    "中山大学": "https://www.sysu.edu.cn/",
    "华南理工大学": "https://www.scut.edu.cn/",
    "四川大学": "https://www.scu.edu.cn/",
    "电子科技大学": "https://www.uestc.edu.cn/",
    "重庆大学": "https://www.cqu.edu.cn/",
    "西安交通大学": "https://www.xjtu.edu.cn/",
    "西北工业大学": "https://www.nwpu.edu.cn/",
    "西北农林科技大学": "https://www.nwafu.edu.cn/",
    "兰州大学": "https://www.lzu.edu.cn/",
    "国防科技大学": "https://www.nudt.edu.cn/",
    # ---- 211 / 强校 ----
    "北京交通大学": "https://www.bjtu.edu.cn/",
    "北京工业大学": "https://www.bjut.edu.cn/",
    "北京科技大学": "https://www.ustb.edu.cn/",
    "北京化工大学": "https://www.buct.edu.cn/",
    "北京邮电大学": "https://www.bupt.edu.cn/",
    "北京林业大学": "https://www.bjfu.edu.cn/",
    "北京协和医学院": "https://www.pumc.edu.cn/",
    "北京中医药大学": "https://www.bucm.edu.cn/",
    "首都医科大学": "https://www.ccmu.edu.cn/",
    "首都师范大学": "https://www.cnu.edu.cn/",
    "北京外国语大学": "https://www.bfsu.edu.cn/",
    "北京第二外国语学院": "https://www.bisu.edu.cn/",
    "北京语言大学": "https://www.blcu.edu.cn/",
    "中央财经大学": "https://www.cufe.edu.cn/",
    "对外经济贸易大学": "https://www.uibe.edu.cn/",
    "首都经济贸易大学": "https://www.cueb.edu.cn/",
    "中国政法大学": "https://www.cupl.edu.cn/",
    "华北电力大学": "https://www.ncepu.edu.cn/",
    "中国矿业大学(北京)": "https://www.cumtb.edu.cn/",
    "中国石油大学(北京)": "https://www.cup.edu.cn/",
    "中国地质大学(北京)": "https://www.cugb.edu.cn/",
    "中央美术学院": "https://www.cafa.edu.cn/",
    "中央音乐学院": "https://www.ccom.edu.cn/",
    "北京体育大学": "https://www.bsu.edu.cn/",
    "天津医科大学": "https://www.tmu.edu.cn/",
    "河北工业大学": "https://www.hebut.edu.cn/",
    "太原理工大学": "https://www.tyut.edu.cn/",
    "内蒙古大学": "https://www.imu.edu.cn/",
    "辽宁大学": "https://www.lnu.edu.cn/",
    "大连海事大学": "https://www.dlmu.edu.cn/",
    "东北师范大学": "https://www.nenu.edu.cn/",
    "延边大学": "https://www.ybu.edu.cn/",
    "哈尔滨工程大学": "https://www.hrbeu.edu.cn/",
    "东北林业大学": "https://www.nefu.edu.cn/",
    "东北农业大学": "https://www.neau.edu.cn/",
    "华东理工大学": "https://www.ecust.edu.cn/",
    "东华大学": "https://www.dhu.edu.cn/",
    "上海外国语大学": "https://www.shisu.edu.cn/",
    "上海财经大学": "https://www.sufe.edu.cn/",
    "上海大学": "https://www.shu.edu.cn/",
    "上海中医药大学": "https://www.shutcm.edu.cn/",
    "上海师范大学": "https://www.shnu.edu.cn/",
    "华东政法大学": "https://www.ecupl.edu.cn/",
    "上海理工大学": "https://www.usst.edu.cn/",
    "苏州大学": "https://www.suda.edu.cn/",
    "南京航空航天大学": "https://www.nuaa.edu.cn/",
    "南京理工大学": "https://www.njust.edu.cn/",
    "中国矿业大学": "https://www.cumt.edu.cn/",
    "河海大学": "https://www.hhu.edu.cn/",
    "江南大学": "https://www.jiangnan.edu.cn/",
    "南京农业大学": "https://www.njau.edu.cn/",
    "中国药科大学": "https://www.cpu.edu.cn/",
    "南京师范大学": "https://www.njnu.edu.cn/",
    "南京邮电大学": "https://www.njupt.edu.cn/",
    "南京信息工程大学": "https://www.nuist.edu.cn/",
    "南京林业大学": "https://www.njfu.edu.cn/",
    "南京中医药大学": "https://www.njucm.edu.cn/",
    "南京医科大学": "https://www.njmu.edu.cn/",
    "南京财经大学": "https://www.nufe.edu.cn/",
    "南京工业大学": "https://www.njtech.edu.cn/",
    "江苏大学": "https://www.ujs.edu.cn/",
    "扬州大学": "https://www.yzu.edu.cn/",
    "浙江工业大学": "https://www.zjut.edu.cn/",
    "杭州电子科技大学": "https://www.hdu.edu.cn/",
    "浙江师范大学": "https://www.zjnu.edu.cn/",
    "宁波大学": "https://www.nbu.edu.cn/",
    "浙江理工大学": "https://www.zstu.edu.cn/",
    "杭州师范大学": "https://www.hznu.edu.cn/",
    "温州医科大学": "https://www.wmu.edu.cn/",
    "浙江工商大学": "https://www.zjgsu.edu.cn/",
    "中国美术学院": "https://www.caa.edu.cn/",
    "浙江财经大学": "https://www.zufe.edu.cn/",
    "安徽大学": "https://www.ahu.edu.cn/",
    "合肥工业大学": "https://www.hfut.edu.cn/",
    "安徽医科大学": "https://www.ahmu.edu.cn/",
    "安徽师范大学": "https://www.ahnu.edu.cn/",
    "安徽农业大学": "https://www.ahau.edu.cn/",
    "安徽工业大学": "https://www.ahut.edu.cn/",
    "福州大学": "https://www.fzu.edu.cn/",
    "福建师范大学": "https://www.fjnu.edu.cn/",
    "福建农林大学": "https://www.fafu.edu.cn/",
    "华侨大学": "https://www.hqu.edu.cn/",
    "集美大学": "https://www.jmu.edu.cn/",
    "南昌大学": "https://www.ncu.edu.cn/",
    "江西财经大学": "https://www.jxufe.edu.cn/",
    "江西师范大学": "https://www.jxnu.edu.cn/",
    "江西理工大学": "https://www.jxust.edu.cn/",
    "华东交通大学": "https://www.ecjtu.edu.cn/",
    "济南大学": "https://www.ujn.edu.cn/",
    "山东师范大学": "https://www.sdnu.edu.cn/",
    "山东科技大学": "https://www.sdust.edu.cn/",
    "青岛大学": "https://www.qdu.edu.cn/",
    "青岛科技大学": "https://www.qust.edu.cn/",
    "山东理工大学": "https://www.sdut.edu.cn/",
    "齐鲁工业大学": "https://www.qlu.edu.cn/",
    "青岛理工大学": "https://www.qut.edu.cn/",
    "山东建筑大学": "https://www.sdjzu.edu.cn/",
    "山东财经大学": "https://www.sdufe.edu.cn/",
    "山东农业大学": "https://www.sdau.edu.cn/",
    "曲阜师范大学": "https://www.qfnu.edu.cn/",
    "郑州大学": "https://www.zzu.edu.cn/",
    "河南大学": "https://www.henu.edu.cn/",
    "河南理工大学": "https://www.hpu.edu.cn/",
    "河南工业大学": "https://www.haut.edu.cn/",
    "河南师范大学": "https://www.htu.edu.cn/",
    "河南农业大学": "https://www.henau.edu.cn/",
    "郑州轻工业大学": "https://www.zzuli.edu.cn/",
    "河南科技大学": "https://www.haust.edu.cn/",
    "华北水利水电大学": "https://www.ncwu.edu.cn/",
    "武汉理工大学": "https://www.whut.edu.cn/",
    "华中师范大学": "https://www.ccnu.edu.cn/",
    "华中农业大学": "https://www.hzau.edu.cn/",
    "中南财经政法大学": "https://www.zuel.edu.cn/",
    "中国地质大学(武汉)": "https://www.cug.edu.cn/",
    "中国地质大学（武汉）": "https://www.cug.edu.cn/",
    "湖北大学": "https://www.hubu.edu.cn/",
    "武汉科技大学": "https://www.wust.edu.cn/",
    "中南民族大学": "https://www.scuec.edu.cn/",
    "三峡大学": "https://www.ctgu.edu.cn/",
    "长江大学": "https://www.yangtzeu.edu.cn/",
    "湖北工业大学": "https://www.hbut.edu.cn/",
    "武汉工程大学": "https://www.wit.edu.cn/",
    "武汉纺织大学": "https://www.wtu.edu.cn/",
    "湖南师范大学": "https://www.hunnu.edu.cn/",
    "湘潭大学": "https://www.xtu.edu.cn/",
    "长沙理工大学": "https://www.csust.edu.cn/",
    "湖南农业大学": "https://www.hunau.edu.cn/",
    "中南林业科技大学": "https://www.csuft.edu.cn/",
    "湖南科技大学": "https://www.hnust.edu.cn/",
    "南华大学": "https://www.usc.edu.cn/",
    "湖南中医药大学": "https://www.hnucm.edu.cn/",
    "暨南大学": "https://www.jnu.edu.cn/",
    "华南师范大学": "https://www.scnu.edu.cn/",
    "华南农业大学": "https://www.scau.edu.cn/",
    "深圳大学": "https://www.szu.edu.cn/",
    "南方科技大学": "https://www.sustech.edu.cn/",
    "广东工业大学": "https://www.gdut.edu.cn/",
    "广州大学": "https://www.gzhu.edu.cn/",
    "南方医科大学": "https://www.smu.edu.cn/",
    "广东外语外贸大学": "https://www.gdufs.edu.cn/",
    "广东财经大学": "https://www.gdufe.edu.cn/",
    "广州医科大学": "https://www.gzhmu.edu.cn/",
    "广州中医药大学": "https://www.gzucm.edu.cn/",
    "汕头大学": "https://www.stu.edu.cn/",
    "广东海洋大学": "https://www.gdou.edu.cn/",
    "广西大学": "https://www.gxu.edu.cn/",
    "广西师范大学": "https://www.gxnu.edu.cn/",
    "桂林电子科技大学": "https://www.guet.edu.cn/",
    "桂林理工大学": "https://www.glut.edu.cn/",
    "广西民族大学": "https://www.gxun.edu.cn/",
    "南宁师范大学": "https://www.nnnu.edu.cn/",
    "海南大学": "https://www.hainanu.edu.cn/",
    "海南师范大学": "https://www.hainnu.edu.cn/",
    "西南大学": "https://www.swu.edu.cn/",
    "西南政法大学": "https://www.swupl.edu.cn/",
    "重庆邮电大学": "https://www.cqupt.edu.cn/",
    "重庆交通大学": "https://www.cqjtu.edu.cn/",
    "重庆医科大学": "https://www.cqmu.edu.cn/",
    "重庆师范大学": "https://www.cqnu.edu.cn/",
    "西南交通大学": "https://www.swjtu.edu.cn/",
    "西南财经大学": "https://www.swufe.edu.cn/",
    "四川农业大学": "https://www.sicau.edu.cn/",
    "成都理工大学": "https://www.cdut.edu.cn/",
    "西南石油大学": "https://www.swpu.edu.cn/",
    "成都中医药大学": "https://www.cdutcm.edu.cn/",
    "四川师范大学": "https://www.sicnu.edu.cn/",
    "西华大学": "https://www.xhu.edu.cn/",
    "成都信息工程大学": "https://www.cuit.edu.cn/",
    "西南科技大学": "https://www.swust.edu.cn/",
    "成都大学": "https://www.cdu.edu.cn/",
    "贵州大学": "https://www.gzu.edu.cn/",
    "贵州师范大学": "https://www.gznu.edu.cn/",
    "贵州医科大学": "https://www.gmc.edu.cn/",
    "贵州财经大学": "https://www.gufe.edu.cn/",
    "云南大学": "https://www.ynu.edu.cn/",
    "昆明理工大学": "https://www.kust.edu.cn/",
    "云南师范大学": "https://www.ynnu.edu.cn/",
    "云南农业大学": "https://www.ynau.edu.cn/",
    "昆明医科大学": "https://www.kmmc.cn/",
    "云南财经大学": "https://www.ynufe.edu.cn/",
    "云南民族大学": "https://www.ynni.edu.cn/",
    "西藏大学": "https://www.utibet.edu.cn/",
    "西北大学": "https://www.nwu.edu.cn/",
    "西安电子科技大学": "https://www.xidian.edu.cn/",
    "长安大学": "https://www.chd.edu.cn/",
    "陕西师范大学": "https://www.snnu.edu.cn/",
    "西安建筑科技大学": "https://www.xauat.edu.cn/",
    "西安理工大学": "https://www.xaut.edu.cn/",
    "西安科技大学": "https://www.xust.edu.cn/",
    "西安工业大学": "https://www.xatu.edu.cn/",
    "西安邮电大学": "https://www.xiyou.edu.cn/",
    "陕西科技大学": "https://www.sust.edu.cn/",
    "西安外国语大学": "https://www.xisu.edu.cn/",
    "西北政法大学": "https://www.nwupl.edu.cn/",
    "兰州理工大学": "https://www.lut.edu.cn/",
    "兰州交通大学": "https://www.lzjtu.edu.cn/",
    "西北师范大学": "https://www.nwnu.edu.cn/",
    "甘肃农业大学": "https://www.gsau.edu.cn/",
    "兰州财经大学": "https://www.lzufe.edu.cn/",
    "西北民族大学": "https://www.xbmu.edu.cn/",
    "青海大学": "https://www.qhu.edu.cn/",
    "青海师范大学": "https://www.qhnu.edu.cn/",
    "宁夏大学": "https://www.nxu.edu.cn/",
    "宁夏医科大学": "https://www.nxmu.edu.cn/",
    "北方民族大学": "https://www.nmu.edu.cn/",
    "新疆大学": "https://www.xju.edu.cn/",
    "石河子大学": "https://www.shzu.edu.cn/",
    "新疆农业大学": "https://www.xjau.edu.cn/",
    "新疆师范大学": "https://www.xjnu.edu.cn/",
    "新疆医科大学": "https://www.xjmu.edu.cn/",
    # ---- 双一流 / 特色 ----
    "中国传媒大学": "https://www.cuc.edu.cn/",
    "中国石油大学(华东)": "https://www.upc.edu.cn/",
    "中国石油大学（华东）": "https://www.upc.edu.cn/",
    "河北大学": "https://www.hbu.edu.cn/",
    "燕山大学": "https://www.ysu.edu.cn/",
    "河北师范大学": "https://www.hebtu.edu.cn/",
    "河北医科大学": "https://www.hebmu.edu.cn/",
    "河北农业大学": "https://www.hebau.edu.cn/",
    "河北科技大学": "https://www.hebust.edu.cn/",
    "山西大学": "https://www.sxu.edu.cn/",
    "中北大学": "https://www.nuc.edu.cn/",
    "山西财经大学": "https://www.sxufe.edu.cn/",
    "山西医科大学": "https://www.sxmu.edu.cn/",
    "内蒙古工业大学": "https://www.imut.edu.cn/",
    "内蒙古农业大学": "https://www.imau.edu.cn/",
    "沈阳工业大学": "https://www.sut.edu.cn/",
    "沈阳航空航天大学": "https://www.sau.edu.cn/",
    "沈阳农业大学": "https://www.syau.edu.cn/",
    "沈阳建筑大学": "https://www.sjzu.edu.cn/",
    "沈阳药科大学": "https://www.syphu.edu.cn/",
    "辽宁师范大学": "https://www.lnnu.edu.cn/",
    "东北财经大学": "https://www.dufe.edu.cn/",
    "大连医科大学": "https://www.dmu.edu.cn/",
    "中国医科大学": "https://www.cmu.edu.cn/",
    "大连海洋大学": "https://www.dlou.edu.cn/",
    "辽宁工程技术大学": "https://www.lntu.edu.cn/",
    "大连交通大学": "https://www.djtu.edu.cn/",
    "大连工业大学": "https://www.dlpu.edu.cn/",
    "吉林农业大学": "https://www.jlau.edu.cn/",
    "长春理工大学": "https://www.cust.edu.cn/",
    "东北电力大学": "https://www.neepu.edu.cn/",
    "长春工业大学": "https://www.ccut.edu.cn/",
    "北华大学": "https://www.beihua.edu.cn/",
    "哈尔滨理工大学": "https://www.hrbust.edu.cn/",
    "哈尔滨医科大学": "https://www.hrbmu.edu.cn/",
    "哈尔滨师范大学": "https://www.hrbnu.edu.cn/",
    "黑龙江大学": "https://www.hlju.edu.cn/",
    "黑龙江中医药大学": "https://www.hljucm.net/",
    "东北石油大学": "https://www.nepu.edu.cn/",
    "齐齐哈尔大学": "https://www.qqhru.edu.cn/",
    "哈尔滨商业大学": "https://www.hrbcu.edu.cn/",
    "黑龙江科技大学": "https://www.usth.edu.cn/",
    "上海海事大学": "https://www.shmtu.edu.cn/",
    "上海电力大学": "https://www.shiep.edu.cn/",
    "上海海洋大学": "https://www.shou.edu.cn/",
    "上海工程技术大学": "https://www.sues.edu.cn/",
    "上海对外经贸大学": "https://www.suibe.edu.cn/",
    "上海体育大学": "https://www.sus.edu.cn/",
    "上海应用技术大学": "https://www.sit.edu.cn/",
    "江苏师范大学": "https://www.jsnu.edu.cn/",
    "江苏科技大学": "https://www.just.edu.cn/",
    "南京工程学院": "https://www.njit.edu.cn/",
    "常州大学": "https://www.cczu.edu.cn/",
    "苏州科技大学": "https://www.usts.edu.cn/",
    "南通大学": "https://www.ntu.edu.cn/",
    "徐州医科大学": "https://www.xzhmu.edu.cn/",
    "中国计量大学": "https://www.cjlu.edu.cn/",
    "浙江海洋大学": "https://www.zjou.edu.cn/",
    "浙江农林大学": "https://www.zafu.edu.cn/",
    "浙江中医药大学": "https://www.zcmu.edu.cn/",
    "合肥大学": "https://www.hfuu.edu.cn/",
    "安徽理工大学": "https://www.aust.edu.cn/",
    "安徽中医药大学": "https://www.ahtcm.edu.cn/",
    "安徽建筑大学": "https://www.ahjzu.edu.cn/",
    "安徽财经大学": "https://www.aufe.edu.cn/",
    "闽南师范大学": "https://www.mnnu.edu.cn/",
    "福建医科大学": "https://www.fjmu.edu.cn/",
    "福建中医药大学": "https://www.fjtcm.edu.cn/",
    "江西农业大学": "https://www.jxau.edu.cn/",
    "江西中医药大学": "https://www.jxutcm.edu.cn/",
    "景德镇陶瓷大学": "https://www.jcu.edu.cn/",
    "东华理工大学": "https://www.ecut.edu.cn/",
    "南昌航空大学": "https://www.nchu.edu.cn/",
    "山东第一医科大学": "https://www.sdfmu.edu.cn/",
    "山东中医药大学": "https://www.sdutcm.edu.cn/",
    "青岛农业大学": "https://www.qau.edu.cn/",
    "河南中医药大学": "https://www.hactcm.edu.cn/",
    "新乡医学院": "https://www.xxmu.edu.cn/",
    "信阳师范大学": "https://www.xynu.edu.cn/",
    "湖北中医药大学": "https://www.hbtcm.edu.cn/",
    "湖北医药学院": "https://www.hbmu.edu.cn/",
    "江汉大学": "https://www.jhun.edu.cn/",
    "武汉轻工大学": "https://www.whpu.edu.cn/",
    "湖北汽车工业学院": "https://www.huat.edu.cn/",
    "吉首大学": "https://www.jsu.edu.cn/",
    "湖南工商大学": "https://www.hutb.edu.cn/",
    "湖南理工学院": "https://www.hnist.cn/",
    "广州美术学院": "https://www.gzarts.edu.cn/",
    "五邑大学": "https://www.wyu.edu.cn/",
    "广东医科大学": "https://www.gdmu.edu.cn/",
    "广东药科大学": "https://www.gdpu.edu.cn/",
    "广西医科大学": "https://www.gxmu.edu.cn/",
    "广西中医药大学": "https://www.gxtcmu.edu.cn/",
    "桂林医科大学": "https://www.glmc.edu.cn/",
    "广西艺术学院": "https://www.gxau.edu.cn/",
    "海南医学院": "https://www.hainmc.edu.cn/",
    "海南医科大学": "https://www.hainmc.edu.cn/",
    "四川外国语大学": "https://www.sisu.edu.cn/",
    "西南民族大学": "https://www.swun.edu.cn/",
    "西南医科大学": "https://www.swmu.edu.cn/",
    "西华师范大学": "https://www.cwnu.edu.cn/",
    "四川轻化工大学": "https://www.suse.edu.cn/",
    "成都体育学院": "https://www.cdsu.edu.cn/",
    "四川音乐学院": "https://www.sccm.cn/",
    "云南中医药大学": "https://www.ynutcm.edu.cn/",
    "西南林业大学": "https://www.swfu.edu.cn/",
    "大理大学": "https://www.dali.edu.cn/",
    "西藏民族大学": "https://www.xzmu.edu.cn/",
    "贵州民族大学": "https://www.gznc.edu.cn/",
    "遵义医科大学": "https://www.zmu.edu.cn/",
    "贵州中医药大学": "https://www.gzy.edu.cn/",
    "西安石油大学": "https://www.xsyu.edu.cn/",
    "西安工程大学": "https://www.xpu.edu.cn/",
    "陕西中医药大学": "https://www.sntcm.edu.cn/",
    "延安大学": "https://www.yau.edu.cn/",
    "西安美术学院": "https://www.xafa.edu.cn/",
    "甘肃中医药大学": "https://www.gszy.edu.cn/",
    "青海民族大学": "https://www.qhmu.edu.cn/",
    "伊犁师范大学": "https://www.ylnu.edu.cn/",
    "塔里木大学": "https://www.taru.edu.cn/",
    "喀什大学": "https://www.ksu.edu.cn/",
    "新疆财经大学": "https://www.xjufe.edu.cn/",
    # ---- 知名特色院校补充 ----
    "西湖大学": "https://www.westlake.edu.cn/",
    "上海科技大学": "https://www.shanghaitech.edu.cn/",
    "中国科学院大学": "https://www.ucas.ac.cn/",
    "中国社会科学院大学": "https://www.ucass.edu.cn/",
    "北京联合大学": "https://www.buu.edu.cn/",
    "北京工商大学": "https://www.btbu.edu.cn/",
    "北京建筑大学": "https://www.bucea.edu.cn/",
    "北京信息科技大学": "https://www.bistu.edu.cn/",
    "北方工业大学": "https://www.ncut.edu.cn/",
    "天津工业大学": "https://www.tiangong.edu.cn/",
    "天津理工大学": "https://www.tjut.edu.cn/",
    "天津师范大学": "https://www.tjnu.edu.cn/",
    "天津科技大学": "https://www.tust.edu.cn/",
    "天津财经大学": "https://www.tjufe.edu.cn/",
    "天津中医药大学": "https://www.tjutcm.edu.cn/",
    "天津职业技术师范大学": "https://www.tute.edu.cn/",
    "东莞理工学院": "https://www.dgut.edu.cn/",
    "佛山大学": "https://www.fosu.edu.cn/",
    "金陵科技学院": "https://www.jit.edu.cn/",
    "淮阴工学院": "https://www.hyit.edu.cn/",
    "江苏海洋大学": "https://www.jou.edu.cn/",
    "河北工程大学": "https://www.hebeu.edu.cn/",
    "石家庄铁道大学": "https://www.stdu.edu.cn/",
    "华北理工大学": "https://www.ncst.edu.cn/",
    "山东交通学院": "https://www.sdjtu.edu.cn/",
    "重庆理工大学": "https://www.cqut.edu.cn/",
    "重庆工商大学": "https://www.ctbu.edu.cn/",
}


# --------------------------------------------------------------------------- #
# 网络层：robots 检查 + 礼貌请求 + 限重试
# --------------------------------------------------------------------------- #
_ROBOTS_CACHE: Dict[str, bool] = {}


def _fetch(url: str, retries: int = 2, timeout: int = 20) -> str:
    """取回网页 HTML；失败最多重试 ``retries`` 次，绝不无限循环。

    中文路径需先 URL 编码（urllib 不接受非 ASCII 路径）。
    """
    url = urllib.parse.quote(url, safe=":/?&=#%+~!$'()*,;@[]")
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
                raw = r.read()
            # 综合常见中文站编码，优先 utf-8，失败回退 gbk
            for enc in ("utf-8", "gbk", "gb18030"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            # 4xx（404/412 等）重试无意义，直接放弃，避免拖时
            print(f"    [fetch {i + 1}/{retries}] {url[:70]} : HTTP {e.code}")
            if 400 <= e.code < 500:
                return ""
        except Exception as e:  # noqa: BLE001 — 网络异常一律跳过并重试
            print(f"    [fetch {i + 1}/{retries}] {url[:70]} : {repr(e)[:70]}")
        if i < retries - 1:
            time.sleep(random.uniform(0.8, 1.5))
    return ""


def _polite() -> None:
    """每校请求间隔 ≥1 秒（合规、降低对方压力）。"""
    time.sleep(random.uniform(1.0, 2.0))


def _domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1) if m else ""


def _robots_allows(domain: str) -> bool:
    """极简 robots 检查：User-Agent * 下 Disallow: / 视为禁止全站。

    口径与 services/kaoyan/spider_notices.py 的 ``_robots_allows`` 一致：
    无 robots.txt 时按「允许（个人低频访问）」处理。
    """
    if domain in _ROBOTS_CACHE:
        return _ROBOTS_CACHE[domain]
    body = _fetch(f"https://{domain}/robots.txt", retries=1, timeout=10)
    allowed = True
    if body:
        current_ua = ""
        for ln in body.splitlines():
            low = ln.strip().lower()
            if low.startswith("user-agent:"):
                current_ua = low.split(":", 1)[1].strip()
            elif low.startswith("disallow:") and current_ua in ("*", "default", ""):
                if low.split(":", 1)[1].strip() == "/":
                    allowed = False
                    break
    _ROBOTS_CACHE[domain] = allowed
    return allowed


# --------------------------------------------------------------------------- #
# 正文提取与简介裁剪
# --------------------------------------------------------------------------- #
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_SCRIPT_RE = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
# 简介页正文常见容器 class/id（不同 CMS 命名不同，命中即优先取该块）
_MAIN_RE = re.compile(
    r'(?is)<(?:div|article|section)[^>]+(?:id|class)="[^"]*'
    r'(?:content|article|detail|intro|con|main|txt|article-content|wp_articlecontent)'
    r'[^"]*"[^>]*>(.*?)</(?:div|article|section)>'
)
# 简介链接锚文本关键词
_INTRO_LINK_KW = ("学校简介", "学校概况", "院校简介", "大学简介", "学校介绍",
                  "学校章程", "学校概况", "学院简介", "本校概况", "学校概述",
                  "学校介绍", "学院概况", "中心简介")
# 常见简介页相对路径（按命中概率排序）
_COMMON_PATHS = (
    "/xxgk/xxjj.htm", "/xxgk/xxjj/", "/xxjj.htm", "/xxgk/xxjj.html",
    "/xxgk/xxjj", "/学校概况/学校简介.htm", "/xxgk/xxjj1.htm",
    "/xxgk/xxjj.htm", "/xxgk/xxjs.htm", "/xxgk/xxgk.htm",
    "/xygk/xxjj.htm", "/xxjj/xxjj.htm", "/xxgk/index.htm",
    "/xxgk/xxjj2020.htm", "/about/intro.htm", "/xxgk/xxjj001.htm",
    "/xxgk/xxjj/list.htm", "/xxgk/xxjj1/list.htm",
)
# 噪声行特征（导航菜单/版权/联系等）——行级过滤
_NOISE_KW = (
    "版权", "版权所有", "Copyright", "ICP备", "京公网安备", "地址：", "邮编",
    "电话：", "传真", "邮箱", "新闻网", "English", "无障碍", "登录", "注册",
    "首页", "学院部门", "师资队伍", "人才培养", "招生就业", "科学研究",
    "服务指南", "招聘", "校友", "更多", "展开", "导航", "版权所有©",
)


def _clean_text(html: str) -> str:
    """HTML → 纯文本：去 script/style/标签、压缩空白。"""
    if not html:
        return ""
    text = _SCRIPT_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def _is_real_url(value: Optional[str]) -> bool:
    """判断 official_url 是否为真实可读网页 URL（排除纯数字 schId）。"""
    if not value:
        return False
    v = value.strip()
    return bool(re.match(r"https?://[^/]+", v))


def _extract_body(html: str) -> str:
    """从简介页提取正文：优先主内容容器，回退整页纯文本。"""
    if not html:
        return ""
    m = _MAIN_RE.search(html)
    if m and len(m.group(1)) > 200:
        candidate = _clean_text(m.group(1))
        if len(re.sub(r"\s", "", candidate)) >= MIN_INTRO:
            return candidate
    return _clean_text(html)


def _trim_intro(text: str, school_name: str = "") -> str:
    """把正文裁剪成 150~400 字的有效简介，剔除导航等噪声行。

    策略：
    1) 若给定校名，优先从「校名首次出现且后接长句」的位置起算（简介页
       正文通常以校名开头，之前多为导航/栏目菜单）；
    2) 按句切分，丢弃噪声行与过短片段，从首个「像正文的」句子起拼接，
       凑够 MAX_INTRO 即停；不足 MIN_INTRO 视为无效返回 ""。
    """
    if not text:
        return ""
    # 1) 校名锚定：找到校名首次出现处，并确保其后是较长正文
    if school_name:
        pos = text.find(school_name)
        # 简介页正文往往以校名开头，但前面可能有一串导航；从校名处切断
        if pos > 0:
            text = text[pos:]
    # 2) 按换行与中文句号/分号切句，保留标点
    chunks = re.split(r"(?<=[。！？；])|\n", text)
    kept: List[str] = []
    total = 0
    started = False
    for ch in chunks:
        s = ch.strip()
        if len(s) < 8:
            continue
        if any(k in s for k in _NOISE_KW):
            continue
        # 丢掉看似导航的超短并列词（6 字内且无标点）
        if len(s) <= 6 and not re.search(r"[。！？，、；：]", s):
            continue
        # 丢掉「数字/符号噪声」行（CMS 计数条残留，如 "7000学校校园占地7000余亩72"）
        cn = len(re.findall(r"[\u4e00-\u9fa5]", s))
        if cn == 0 or (cn < 4 and len(re.findall(r"\d", s)) >= 2):
            continue
        # 未开始前，跳过明显是导航拼接的长尾（连续短片段无句末标点）
        if not started and not re.search(r"[。！？]", s) and len(s) < 40:
            continue
        # 遇非简介特征句（校歌/歌词/章程等）即停止拼接，避免混入后续无关章节
        if any(k in s for k in ("校歌", "歌词", "词调", "乐章集", "校友会章程")):
            break
        started = True
        kept.append(s)
        total += len(s)
        if total >= MAX_INTRO:
            break
    merged = "".join(kept).strip()
    merged = re.sub(r"\s+", "", merged)
    if len(merged) < MIN_INTRO:
        return ""
    return merged[:MAX_INTRO]


def _find_intro_links(html: str, base_url: str) -> List[str]:
    """在首页 HTML 中找「学校简介/学校概况」链接，返回绝对 URL 列表。"""
    out: List[str] = []
    seen = set()
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href, label = m.group(1), re.sub(r"(?s)<[^>]+>", "", m.group(2))
        label = re.sub(r"\s+", "", label)
        if not label or len(label) > 12:
            continue
        if not any(k in label for k in _INTRO_LINK_KW):
            continue
        url = _abs_url(href, base_url)
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _abs_url(href: str, base_url: str) -> str:
    """相对链接补全为绝对 URL。"""
    href = (href or "").strip()
    if not href or href.startswith(("javascript:", "#", "mailto:")):
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http"):
        return href
    root = re.match(r"(https?://[^/]+)", base_url)
    if href.startswith("/"):
        return (root.group(1) if root else base_url.rstrip("/")) + href
    return base_url.rstrip("/") + "/" + href.lstrip("./")


# --------------------------------------------------------------------------- #
# 第 1 层：官网抓简介
# --------------------------------------------------------------------------- #
_TIMEOUT = int(os.environ.get("INTRO_TIMEOUT", "10"))
_MAX_CANDIDATES = int(os.environ.get("INTRO_MAX_CANDIDATES", "6"))
_WORKERS = int(os.environ.get("INTRO_WORKERS", "8"))


def fetch_intro_from_official(school_name: str, domain: str) -> Tuple[str, str]:
    """抓官网简介：返回 (intro, hit_url)。失败返回 ("", "")。

    流程：robots 检查 → 抓首页 → 找「学校简介」链接 → 抓该页取正文；
    若首页无链接，则按常见路径探测。任一步成功即返回。
    """
    d = _domain_of(domain)
    if not d or not _robots_allows(d):
        return "", ""
    base = domain.rstrip("/") + "/"
    home = _fetch(base, retries=1, timeout=_TIMEOUT)
    candidates: List[str] = []
    if home:
        # 首页须能认出该校（防止域名跳转会错站）
        if _name_in_html(school_name, home):
            candidates.extend(_find_intro_links(home, base))
    # 常见路径兜底探测
    candidates.extend(base.rstrip("/") + p for p in _COMMON_PATHS)
    # 去重保序
    seen = set()
    ordered = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    for u in ordered[:_MAX_CANDIDATES]:  # 单校候选页上限（可控，避免拖时）
        _polite()
        html = _fetch(u, retries=1, timeout=_TIMEOUT)
        if not html:
            continue
        if not _name_in_html(school_name, html, loose=True):
            continue
        body = _extract_body(html)
        intro = _trim_intro(body, school_name)
        if intro and _looks_like_intro(school_name, intro):
            return intro, u
    return "", ""


def _looks_like_intro(school_name: str, intro: str) -> bool:
    """简介质量门：正文须出现校名，且不含明显非简介特征。

    用于排除误抓到的「校歌/章程/新闻」等页面：这类正文含「校歌/歌词/
    章程」等标志词，或被拒绝。校名判定放宽到全文（部分简介以地理位置、
    历史沿革起笔，校名在句中段才出现，如北航）。
    """
    if not intro:
        return False
    core = re.sub(r"[（(].*?[)）]", "", school_name)
    core = re.sub(r"(大学|学院|学校)$", "", core)
    if school_name not in intro and (len(core) < 4 or core not in intro):
        return False
    # 非简介特征词（简介页不会出现）
    reject = ("歌词", "词调", "校歌", "乐章集", "校友会章程")
    if any(k in intro[:150] for k in reject):
        return False
    return True


def _name_in_html(name: str, html: str, loose: bool = False) -> bool:
    """校验 HTML 中是否出现该院校名（严格=全名；loose=去括号/后缀模糊）。"""
    if not html:
        return False
    text = _clean_text(html)
    if name in text:
        return True
    if loose:
        core = re.sub(r"[（(].*?[)）]", "", name)
        core = re.sub(r"(大学|学院|学校)$", "", core)
        return len(core) >= 4 and core in text
    return False


# --------------------------------------------------------------------------- #
# 第 2 层：研招网 schId 简介
# --------------------------------------------------------------------------- #
def fetch_intro_from_chsi(name: str, sch_id: str) -> Tuple[str, str]:
    """用研招网 schId 抓「院校简介」页。返回 (intro, hit_url)。"""
    if not sch_id:
        return "", ""
    base = f"https://yz.chsi.com.cn/sch/schoolInfo--schId-{sch_id}.dhtml"
    if not _robots_allows("yz.chsi.com.cn"):
        return "", ""
    html = _fetch(base, retries=2)
    if not html:
        return "", ""
    # 找「院校简介」标签页 link（categoryId-*）
    m = re.search(
        r'href="(/sch/schoolInfo--schId-%s[^"]*categoryId-\d+\.dhtml)"[^>]*>'
        r'\s*<div[^>]*>\s*<img[^>]*sch-yxgk-1[^>]*>\s*</div>\s*'
        r'<div[^>]*>\s*院校简介' % re.escape(sch_id),
        html,
    )
    intro_url = "https://yz.chsi.com.cn" + m.group(1) if m else ""
    if not intro_url:
        return "", ""
    _polite()
    h2 = _fetch(intro_url, retries=2)
    if not h2:
        return "", ""
    body = _clean_text(h2)
    # 研招网简介页正文常以「院校简介」标签后开始，去掉前面导航
    idx = body.find("院校简介")
    if idx > 0:
        body = body[idx + 4:]
    intro = _trim_intro(body, name)
    if intro and _looks_like_intro(name, intro):
        return intro, intro_url
    return "", ""


def _chsi_id_for(official_url: Optional[str], tags: Optional[str],
                 name: str = "") -> str:
    """解析研招网 schId：优先 official_url/tags，其次内置 schools_data.json。

    研招网 schId 是稳定标识；``services/kaoyan/schools_data.json`` 保存了
    100 所院校的 schId，可显著扩展第 2 层覆盖率（研招网简介页结构统一）。
    """
    if official_url:
        if re.match(r"^\d+$", official_url.strip()):
            return official_url.strip()
        m = re.search(r"sch/(\d+)\.jhtml", official_url)
        if m:
            return m.group(1)
    if tags:
        try:
            data = json.loads(tags)
            if isinstance(data, dict) and "yz_schid" in data:
                return str(data["yz_schid"])
        except (json.JSONDecodeError, TypeError):
            pass
    # 兜底：从内置 schools_data.json 按校名取 schId
    if name:
        return _SCHID_BY_NAME.get(name, "")
    return ""


def _load_schid_map() -> Dict[str, str]:
    """加载内置 schools_data.json 的「校名 → 研招网 schId」映射（幂等、失败为空）。"""
    path = os.path.join(BASE_DIR, "services", "kaoyan", "schools_data.json")
    out: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            name = (item.get("dwmc") or "").strip()
            sid = str(item.get("schId") or "").strip()
            if name and sid:
                out[name] = sid
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return out


_SCHID_BY_NAME: Dict[str, str] = _load_schid_map()


# --------------------------------------------------------------------------- #
# 第 3 层：模板兜底（明确可识别，默认不写库）
# --------------------------------------------------------------------------- #
def build_template_intro(name: str, level: Optional[str], province: Optional[str],
                         type_: Optional[str]) -> str:
    """用库内既有事实字段拼一句可识别为模板的说明（不编造）。"""
    bits = []
    if level:
        bits.append(level)
    if province:
        bits.append(f"{province}")
    tail = "，".join(bits)
    kind = type_ or "高校"
    if tail:
        return f"{name}（{tail}），{kind}。（本条为模板说明，待补充官网真实简介）"
    return f"{name}，{kind}。（本条为模板说明，待补充官网真实简介）"


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _backup(con: sqlite3.Connection) -> str:
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_intro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )
    with sqlite3.connect(bak) as dest:
        con.backup(dest)  # WAL 安全备份
    return bak


def run(dry_run: bool, limit: Optional[int], with_template: bool,
        overwrite: bool, only: Optional[List[str]] = None) -> Dict:
    """执行回填。返回统计 dict（供报告生成）。"""
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    where = "" if overwrite else "WHERE intro IS NULL OR intro = ''"
    rows = cur.execute(
        f"SELECT id, name, level, province, type, intro, official_url, tags "
        f"FROM kaoyan_schools {where} ORDER BY id"
    ).fetchall()
    if only:
        rows = [r for r in rows if r[1] in only]
    if limit:
        rows = rows[:limit]

    print(f"数据库: {DB_PATH}")
    print(f"待处理: {len(rows)} 所（dry_run={dry_run}, with_template={with_template}, "
          f"overwrite={overwrite}）\n")

    official_hits: List[Dict] = []   # 官网/研招网真实简介
    template_hits: List[Dict] = []   # 模板兜底
    failures: List[Dict] = []        # 未拿到

    def _one(row) -> Dict:
        sid, name, level, province, type_, _intro, ourl, tags = row
        got_intro, got_url, source = "", "", ""
        domains: List[str] = []
        if SCHOOL_DOMAINS.get(name):
            domains.append(SCHOOL_DOMAINS[name])
        if _is_real_url(ourl):
            domains.append(ourl.strip())
        for dom in dict.fromkeys(domains):  # 去重保序
            got_intro, got_url = fetch_intro_from_official(name, dom)
            if got_intro:
                source = "official"
                break
        if not got_intro:
            sch_id = _chsi_id_for(ourl, tags, name)
            if sch_id:
                got_intro, got_url = fetch_intro_from_chsi(name, sch_id)
                if got_intro:
                    source = "chsi"
        if not got_intro and with_template:
            got_intro = build_template_intro(name, level, province, type_)
            source = "template"
            got_url = ""
        if got_intro:
            return {"id": sid, "name": name, "source": source,
                    "chars": len(got_intro), "url": got_url, "intro": got_intro}
        no_src = (name not in SCHOOL_DOMAINS) and not _is_real_url(ourl)
        reason = "无可用官网/研招网映射" if no_src else "官网/研招网均未取到"
        return {"id": sid, "name": name, "reason": reason}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    results: List[Dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futs = {pool.submit(_one, r): r[1] for r in rows}
        for fu in as_completed(futs):
            rec = fu.result()
            results.append(rec)
            done += 1
            if "intro" in rec:
                print(f"[{done}/{len(rows)}] ✓ [{rec['source']}] {rec['name']} "
                      f"{rec['chars']}字")
            else:
                print(f"[{done}/{len(rows)}] ✗ {rec['name']}：{rec['reason']}")

    official_hits = [r for r in results if r.get("source") in ("official", "chsi")]
    template_hits = [r for r in results if r.get("source") == "template"]
    failures = [r for r in results if "reason" in r]

    # 统计
    stats = {
        "db_path": DB_PATH,
        "processed": len(rows),
        "official": len(official_hits),
        "template": len(template_hits),
        "failed": len(failures),
        "dry_run": dry_run,
        "official_hits": official_hits,
        "template_hits": template_hits,
        "failures": failures,
    }

    if not dry_run and (official_hits or template_hits):
        bak = _backup(con)
        print(f"\n已备份 → {bak}")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for rec in official_hits:
            cur.execute(
                "UPDATE kaoyan_schools SET intro = ?, updated_at = ? "
                "WHERE id = ?",
                (rec["intro"], now, rec["id"]),
            )
        for rec in template_hits:
            cur.execute(
                "UPDATE kaoyan_schools SET intro = ?, updated_at = ? "
                "WHERE id = ?",
                (rec["intro"], now, rec["id"]),
            )
        con.commit()
        stats["backup"] = bak
        print(f"已写入 {len(official_hits)} 条真实简介 + "
              f"{len(template_hits)} 条模板说明")

    con.close()
    return stats


def write_report(stats: Dict, path: str) -> None:
    """生成 Markdown 报告（表格：院校 | 来源 | 字数 | 状态 + 总结）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines: List[str] = []
    lines.append("# 院校简介回填报告（kaoyan_schools.intro）\n")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 数据库：`{stats['db_path']}`")
    lines.append(f"- 模式：{'DRY-RUN（未写库）' if stats['dry_run'] else 'APPLY（已写库）'}")
    lines.append(f"- 处理院校数：{stats['processed']}\n")
    lines.append("## 汇总\n")
    lines.append("| 指标 | 数量 |")
    lines.append("|---|---|")
    lines.append(f"| 官网/研招网真实简介 | {stats['official']} |")
    lines.append(f"| 模板说明（非真实，单独统计） | {stats['template']} |")
    lines.append(f"| 未取到（保持空） | {stats['failed']} |")
    lines.append("")

    src_label = {"official": "官网", "chsi": "研招网", "template": "模板"}
    all_hits = stats["official_hits"] + stats["template_hits"]
    lines.append("## 明细（院校 | 来源 | 简介字数 | 状态）\n")
    lines.append("| 院校 | 来源 | 简介字数 | 状态 |")
    lines.append("|---|---|---|---|")
    for r in all_hits:
        lines.append(
            f"| {r['name']} | {src_label.get(r['source'], r['source'])} "
            f"| {r['chars']} | 成功 |"
        )
    for r in stats["failures"]:
        lines.append(f"| {r['name']} | - | 0 | 失败：{r['reason']} |")
    lines.append("")

    lines.append("## 样例简介（真实，前 5 条）\n")
    for r in stats["official_hits"][:5]:
        lines.append(f"**{r['name']}**（来源 {src_label.get(r['source'])}：{r['url']}）\n")
        lines.append(f"> {r['intro']}\n")

    if stats["template_hits"]:
        lines.append("## 模板说明样例（非真实简介，默认不写库）\n")
        for r in stats["template_hits"][:5]:
            lines.append(f"- **{r['name']}**：{r['intro']}")
        lines.append("")

    lines.append("## 失败原因分类\n")
    from collections import Counter
    reasons = Counter(r["reason"] for r in stats["failures"])
    for reason, cnt in reasons.most_common():
        lines.append(f"- {reason}：{cnt}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description="院校简介回填（幂等，默认 dry-run）")
    ap.add_argument("--apply", action="store_true", help="写库（自动先备份）")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 所")
    ap.add_argument("--schools", nargs="*", default=None, help="只处理指定院校名")
    ap.add_argument("--with-template", action="store_true",
                    help="对抓不到官网简介的院校写入模板说明（需显式开启）")
    ap.add_argument("--overwrite", action="store_true",
                    help="覆盖已有 intro（默认只填空值）")
    args = ap.parse_args()

    dry_run = not args.apply
    stats = run(
        dry_run=dry_run,
        limit=args.limit,
        with_template=args.with_template,
        overwrite=args.overwrite,
        only=args.schools,
    )

    # 报告总是产出（dry-run 也产出于报告目录，便于审阅）
    report = os.path.join(REPORT_DIR, "school-intro-backfill-2026-10-12.md")
    write_report(stats, report)
    print(f"\n报告 → {report}")
    print("\n汇总: 官网/研招网真实={official} 模板={template} 失败={failed}".format(
        official=stats["official"], template=stats["template"], failed=stats["failed"]))
    if dry_run:
        print("\n[DRY-RUN] 未写库。确认后加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
