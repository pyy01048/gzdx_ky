-- 201_school_url_intro_backfill_round24.sql
-- 院校官网+简介回填（第 201 批，2026-11-24）：602 直升机所。
--
-- 口径同 173-200：只用官网「企业基本信息/研究所简介」原文，逐字摘录，句末截断；
-- official_url 与 intro 均仅在为空时更新；不物理删除。
-- 证据：backfill_local/out/school_intro_201_evidence.csv

UPDATE kaoyan_schools AS s
SET official_url = CASE
        WHEN coalesce(btrim(s.official_url), '') = '' AND v.official_url <> '' THEN v.official_url
        ELSE s.official_url
    END,
    intro = CASE
        WHEN s.intro IS NULL OR btrim(s.intro) = '' THEN v.intro
        ELSE s.intro
    END,
    updated_at = now()
FROM (VALUES
    (450, 'https://chrdi.avic.com',
     '中国直升机设计研究所（以下简称“直升机所”）创建于1969年，隶属于中国航空工业集团有限公司，是我国唯一以直升机型号研制和技术发展为使命的国家级大型科研院所，现已形成江西、天津“一所两地三区”的发展格局，分别在天津、景德镇和鄱阳建设了研发生产条件，并以“一套人马、一套体系”的模式运行，具备异地协同研制能力。直升机所是我国直升机型号研制总设计师单位和直升机技术发展抓总单位，在职员工3000余人。具备完整的研发体系，拥有总体气动、旋翼传动、航电系统、飞行控制等20多个直升机专业研究部门，设计、试验手段达到世界先进水平，具备研制第三代、第四代先进直升机能力。直升机所立足自主创新，成功研制了直-8、直-9、直-10、直-11、直-20、AC352、AR-200、AR-500、AR-2000等9大平台70余型军用、民用和无人直升机，形成“一机多型、系列发展”的良好格局。')
) AS v(id, official_url, intro)
WHERE s.id = v.id
  AND (
        (s.intro IS NULL OR btrim(s.intro) = '')
     OR coalesce(btrim(s.official_url), '') = ''
      );
