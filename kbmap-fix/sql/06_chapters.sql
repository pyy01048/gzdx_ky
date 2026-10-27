\pset pager off
\echo '=== 电磁场与电磁波 chapter distribution ==='
SELECT chapter, count(*) FROM knowledge_points WHERE subject='电磁场与电磁波' GROUP BY chapter ORDER BY count(*) DESC LIMIT 20;
\echo '=== 数字信号处理 chapter distribution ==='
SELECT chapter, count(*) FROM knowledge_points WHERE subject='数字信号处理' GROUP BY chapter ORDER BY count(*) DESC LIMIT 20;
\echo '=== 信号与系统 chapter distribution ==='
SELECT chapter, count(*) FROM knowledge_points WHERE subject='信号与系统' GROUP BY chapter ORDER BY count(*) DESC LIMIT 20;