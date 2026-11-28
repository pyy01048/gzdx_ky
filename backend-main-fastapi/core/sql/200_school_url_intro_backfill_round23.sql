-- 200_school_url_intro_backfill_round23.sql
-- 院校官网+简介回填（第 200 批，2026-11-24）：中船 715/713 两所。
--
-- 口径同 173-199：只用官网「单位概况/单位简介」或所官网「七一三简介」原文，逐字摘录，句末截断；
-- official_url 与 intro 均仅在为空时更新；不物理删除。
-- 证据：backfill_local/out/school_intro_200_evidence.csv

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
    (384, 'https://www.715.com.cn',
     '中国船舶集团有限公司第七一五研究所是中国船舶集团有限公司成员单位，成立于1958年，是我国最早创建的国家级海洋信息装备技术研究所。经过六十多年的发展，已成为集水声装备应用基础研究、型号研制、生产制造、试验测试、综合服务保障为一体的重点骨干研究所。所内建有声纳技术重点实验室、国防科技工业水声专业计量站两个国家级专业技术机构，是国际电工委员会超声技术委员会（IEC/TC87）和国际标准化声学技术委员会水声分技术委员会（ISO/TC43/SC3）国内技术对口单位，为国防建设作出了重要贡献。七一五所深入贯彻国家发展战略，构建以公司为科技产业发展主体、以研究所为主要技术支撑的创新体系，形成“一所两平台”的科技产业组织架构。重点发展海洋仪器、超声电子、光纤传感和智能装备四大新兴科技产业板块与现代服务业。'),
    (507, 'http://www.csic713.com.cn',
     '中国船舶第七一三研究所创建于1963年4月，坐落在河南省郑州市，隶属于中国船舶集团有限公司。50多年来，七一三人不舍追求，攻关克难，出色完成了多项国家重点项目，先后获得国家、国防科工委、省部级等各类科技奖励400多项，其中国家科技进步特等奖4项、一等奖5项、二等奖8项。进入新世纪，七一三所在集团公司发展战略的引领下，全面实现了三个跨越：产品构成由配套设备向系统总体的跨越；能力建设由单一能力向数字化综合能力的跨越；体制建设由传统研究所向多种经营、协同发展的高新技术企业的跨越。目前，民品产业已形成以新能源、智能装备、交通运输装备、电子信息四大板块为支撑的产业发展格局。')
) AS v(id, official_url, intro)
WHERE s.id = v.id
  AND (
        (s.intro IS NULL OR btrim(s.intro) = '')
     OR coalesce(btrim(s.official_url), '') = ''
      );
