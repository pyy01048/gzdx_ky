\pset pager off
\echo '=== subject_config rows (subject, is_custom) ==='
SELECT subject, is_custom FROM subject_config ORDER BY is_custom, subject;

\echo '=== knowledge_points subjects present in subject_config? ==='
SELECT kp.subject, count(*) AS kp_count,
       bool_or(sc.subject IS NOT NULL) AS in_subject_config
FROM knowledge_points kp
LEFT JOIN subject_config sc ON sc.subject = kp.subject
GROUP BY kp.subject
ORDER BY kp_count DESC;

\echo '=== knowledge_points subjects -> normalized ==='
SELECT subject, count(*),
       CASE
         WHEN subject IN ('数字电子技术','模拟电子技术','数学','英语','政治','真题综合') THEN 'CORE'
         WHEN subject IN ('电路','信号与系统','通信原理','光学与工程光学','普通物理','计算机学科专业基础408') THEN 'MAJOR'
         WHEN subject IN ('电路分析','光学','网络补充','其他','电气工程','电子科学与技术','控制科学与工程','计算机基础','数据结构','操作系统','计算机网络','软件工程','电子信息','信息与通信工程','计算机科学与技术','光学工程','自动控制原理') THEN 'EXT'
         WHEN subject IN ('管理类联考综合','经济类联考综合','法律硕士专业基础','教育学专业基础','心理学专业基础','西医综合','中医综合') THEN 'CROSS'
         ELSE 'UNKNOWN'
       END AS bucket
FROM knowledge_points
GROUP BY subject
ORDER BY count(*) DESC;