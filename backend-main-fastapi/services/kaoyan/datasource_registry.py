# -*- coding: utf-8 -*-
"""动态数据源注册中心（D1 动态数据源）。

维护官方/第三方数据源清单，每条记录包含：
- name: 数据源名称
- base_url: 域名/根地址
- source_type: yz(研招网) / exam_authority(省教育考试院) / school_official(院校研究生院) / aggregator(聚合站)
- parser: 对应解析器（spider_yz / spider_school / manual / custom）
- status: active / paused / deprecated
- province: 省份（院校与考试院维度）
- remark: 备注

能力：
1. list_datasources() 列表查询（支持按类型/省份/状态过滤）
2. register_datasource() 新增注册（持久化到 datasource_registry.json，不覆盖内置清单）
3. resolve_source_type() 将库内 source 标记归一化为 官方/聚合/未验证 三档
"""
import json
from pathlib import Path
from datetime import datetime

REGISTRY_FILE = Path(__file__).parent / "datasource_registry.json"

# 内置官方数据源清单（研招网 + 31 省教育考试院 + 重点院校研究生院官网）
OFFICIAL_SOURCES = [
    # ---- 研招网（国家级官方） ----
    {
        "key": "yz_chsi",
        "name": "中国研究生招生信息网（研招网）",
        "base_url": "https://yz.chsi.com.cn/",
        "source_type": "yz",
        "parser": "spider_yz",
        "status": "active",
        "province": None,
        "remark": "教育部全国硕士招生目录官方平台，spider_yz.py 采集院校/专业目录，含断点续爬",
    },
    # ---- 各省教育考试院官网（官方） ----
    {"key": "ee_bj", "name": "北京教育考试院", "base_url": "https://www.bjeea.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "北京", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_tj", "name": "天津市招考资讯网", "base_url": "https://www.zhaokao.net/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "天津", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_he", "name": "河北省教育考试院", "base_url": "https://www.hebeea.edu.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "河北", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_sx", "name": "山西招生考试网", "base_url": "https://www.sxkszx.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "山西", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_nmg", "name": "内蒙古招生考试信息网", "base_url": "https://www.nm.zsks.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "内蒙古", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_ln", "name": "辽宁招生考试之窗", "base_url": "https://www.lnzsks.com/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "辽宁", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_jl", "name": "吉林省教育考试院", "base_url": "https://www.jleea.com.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "吉林", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_hlj", "name": "黑龙江省招生考试信息港", "base_url": "https://www.lzk.hl.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "黑龙江", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_sh", "name": "上海市教育考试院", "base_url": "https://www.shmeea.edu.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "上海", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_js", "name": "江苏省教育考试院", "base_url": "https://www.jseea.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "江苏", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_zj", "name": "浙江省教育考试院", "base_url": "https://www.zjzs.net/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "浙江", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_ah", "name": "安徽省教育招生考试院", "base_url": "https://www.ahzsks.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "安徽", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_fj", "name": "福建省教育考试院", "base_url": "https://www.eeafj.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "福建", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_jx", "name": "江西省教育考试院", "base_url": "https://www.jxeea.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "江西", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_sd", "name": "山东省教育招生考试院", "base_url": "https://www.sdzk.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "山东", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_ha", "name": "河南省教育考试院", "base_url": "https://www.haeea.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "河南", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_hb", "name": "湖北省教育考试院", "base_url": "https://www.hbea.edu.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "湖北", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_hn", "name": "湖南省教育考试院", "base_url": "https://www.hneeb.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "湖南", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_gd", "name": "广东省教育考试院", "base_url": "https://eea.gd.gov.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "广东", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_gx", "name": "广西招生考试院", "base_url": "https://www.gxeea.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "广西", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_hi", "name": "海南省考试局", "base_url": "https://ea.hainan.gov.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "海南", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_cq", "name": "重庆市教育考试院", "base_url": "https://www.cqksy.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "重庆", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_sc", "name": "四川省教育考试院", "base_url": "https://www.sceea.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "四川", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_gz", "name": "贵州省招生考试院", "base_url": "https://zsksy.guizhou.gov.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "贵州", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_yn", "name": "云南省招生考试院", "base_url": "https://www.ynzs.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "云南", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_xz", "name": "西藏教育考试院", "base_url": "https://zsks.edu.xizang.gov.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "西藏", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_sx61", "name": "陕西省教育考试院", "base_url": "https://www.sneea.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "陕西", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_gs", "name": "甘肃省教育考试院", "base_url": "https://www.ganseea.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "甘肃", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_qh", "name": "青海省教育考试网", "base_url": "https://www.qhjyks.com/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "青海", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_nx", "name": "宁夏教育考试院", "base_url": "https://www.nxjyks.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "宁夏", "remark": "官方招考公告/分数线发布渠道"},
    {"key": "ee_xj", "name": "新疆招生网", "base_url": "https://www.xjzk.gov.cn/", "source_type": "exam_authority", "parser": "spider_school", "status": "active", "province": "新疆", "remark": "官方招考公告/分数线发布渠道"},
    # ---- 重点院校研究生院官网（官方） ----
    {"key": "sch_tsinghua", "name": "清华大学研究生院", "base_url": "https://yz.tsinghua.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "北京", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_pku", "name": "北京大学研究生院", "base_url": "https://admission.pku.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "北京", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_zju", "name": "浙江大学研究生院", "base_url": "http://www.grs.zju.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "浙江", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_sjtu", "name": "上海交通大学研究生院", "base_url": "https://yzb.sjtu.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "上海", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_fudan", "name": "复旦大学研究生院", "base_url": "https://gsao.fudan.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "上海", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_nju", "name": "南京大学研究生院", "base_url": "https://grawww.nju.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "江苏", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_ustc", "name": "中国科学技术大学研究生院", "base_url": "https://yz.ustc.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "安徽", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_hit", "name": "哈尔滨工业大学研究生院", "base_url": "http://yzb.hit.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "黑龙江", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_xjtu", "name": "西安交通大学研究生院", "base_url": "http://yz.xjtu.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "陕西", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_hust", "name": "华中科技大学研究生院", "base_url": "http://gs.hust.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "湖北", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_ruc", "name": "中国人民大学研究生院", "base_url": "https://grs.ruc.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "北京", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_buaa", "name": "北京航空航天大学研究生院", "base_url": "https://yzb.buaa.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "北京", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_bit", "name": "北京理工大学研究生院", "base_url": "https://grad.bit.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "北京", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_tju", "name": "天津大学研究生院", "base_url": "https://yzb.tju.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "天津", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_nankai", "name": "南开大学研究生院", "base_url": "https://yzb.nankai.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "天津", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_tongji", "name": "同济大学研究生院", "base_url": "https://yz.tongji.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "上海", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_seu", "name": "东南大学研究生院", "base_url": "https://yzb.seu.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "江苏", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_whu", "name": "武汉大学研究生院", "base_url": "https://gs.whu.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "湖北", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_sysu", "name": "中山大学研究生院", "base_url": "https://graduate.sysu.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "广东", "remark": "院校官方复试线/拟录取公告"},
    {"key": "sch_scu", "name": "四川大学研究生院", "base_url": "https://gs.scu.edu.cn/", "source_type": "school_official", "parser": "spider_school", "status": "active", "province": "四川", "remark": "院校官方复试线/拟录取公告"},
]


def _default_payload():
    return {"builtin": OFFICIAL_SOURCES, "custom": [], "updated_at": None}


def load_registry():
    """加载数据源清单：内置官方源 + 用户注册的自定义源（持久化 JSON）。"""
    data = _default_payload()
    if REGISTRY_FILE.exists():
        try:
            saved = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                data["custom"] = saved.get("custom", [])
                data["updated_at"] = saved.get("updated_at")
        except Exception:
            pass
    return data


def save_registry(data):
    """持久化注册中心（仅保存 custom 段，内置清单保持代码维护）。"""
    payload = {
        "custom": data.get("custom", []),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    REGISTRY_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_datasources(source_type=None, province=None, status=None):
    """数据源列表查询。支持按 source_type / province / status 过滤。"""
    data = load_registry()
    items = data["builtin"] + data["custom"]
    if source_type:
        items = [it for it in items if it.get("source_type") == source_type]
    if province:
        items = [it for it in items if it.get("province") == province]
    if status:
        items = [it for it in items if it.get("status") == status]
    return items


def get_datasource(key):
    """按 key 获取单个数据源。"""
    for it in list_datasources():
        if it.get("key") == key:
            return it
    return None


def register_datasource(name, base_url, source_type="aggregator", parser="manual",
                        status="active", province=None, remark=""):
    """新增注册数据源（持久化到 datasource_registry.json）。

    默认 source_type=aggregator：第三方聚合站需显式标注，官方源请使用
    yz / exam_authority / school_official 类型。
    """
    if not name or not base_url:
        raise ValueError("name 与 base_url 必填")
    if source_type not in ("yz", "exam_authority", "school_official", "aggregator"):
        raise ValueError(f"非法 source_type: {source_type}")
    data = load_registry()
    key = f"custom_{len(data['custom']) + 1}_{len(data['builtin'])}"
    item = {
        "key": key,
        "name": name,
        "base_url": base_url,
        "source_type": source_type,
        "parser": parser,
        "status": status,
        "province": province,
        "remark": remark,
        "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    data["custom"].append(item)
    save_registry(data)
    return item


# 库内 source 标记 → 展示类型三档归一化
SOURCE_TYPE_MAP = {
    "yz.chsi.com.cn": "官方",
    "school_official": "官方",
    "yz_chsi": "官方",
    "exam_authority": "官方",
    "txkyer.cn": "聚合",
    "seed_txkyer": "聚合",
    "csv_sample": "聚合",
    "csv导入:c4_sample.csv": "聚合",
    "unverified": "未验证",
}


def resolve_source_type(source):
    """将库内 source/data_source 标记归一化为 官方/聚合/未验证 展示类型。"""
    if not source:
        return "未验证"
    if source in SOURCE_TYPE_MAP:
        return SOURCE_TYPE_MAP[source]
    # 域名启发式：官方 edu.cn / 教育考试院 / 研招网
    if "yz.chsi.com.cn" in source or ".edu.cn" in source or "exam" in source.lower():
        return "官方"
    if "txkyer" in source or "csv" in source.lower():
        return "聚合"
    return "未验证"
