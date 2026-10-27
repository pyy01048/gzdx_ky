\pset pager off
\echo '=== knowledge_points total ==='
SELECT count(*) FROM knowledge_points;

\echo '=== knowledge_points by subject ==='
SELECT subject, count(*) AS total,
       count(*) FILTER (WHERE chapter_id IS NULL) AS no_chapter_id,
       count(*) FILTER (WHERE chapter_id IS NOT NULL) AS has_chapter_id,
       count(*) FILTER (WHERE chapter IS NULL OR chapter = '') AS no_chapter_text,
       count(*) FILTER (WHERE chapter IS NOT NULL AND chapter <> '') AS has_chapter_text
FROM knowledge_points
GROUP BY subject
ORDER BY total DESC;

\echo '=== knowledge_points subjects normalized not in CORE/MAJOR/EXT ==='
SELECT DISTINCT subject FROM knowledge_points ORDER BY subject;

\echo '=== knowledge_points no chapter_id sample (数学) ==='
SELECT id, name, subject, chapter_id, chapter, parent_id, document_id
FROM knowledge_points
WHERE subject = '数学' AND chapter_id IS NULL
ORDER BY id LIMIT 10;

\echo '=== words columns ==='
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'words' ORDER BY ordinal_position;

\echo '=== words root/example non-null counts ==='
SELECT count(*) AS total_words,
       count(*) FILTER (WHERE root IS NOT NULL AND root <> '') AS has_root_col,
       count(*) FILTER (WHERE example IS NOT NULL AND example <> '') AS has_example_col
FROM words;

\echo '=== word_examples columns ==='
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'word_examples' ORDER BY ordinal_position;

\echo '=== word_examples stats ==='
SELECT count(*) AS total, count(DISTINCT word_id) AS distinct_words,
       count(*) FILTER (WHERE sentence_cn IS NOT NULL AND sentence_cn <> '') AS with_cn
FROM word_examples;

\echo '=== word_roots columns ==='
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'word_roots' ORDER BY ordinal_position;

\echo '=== word_roots stats ==='
SELECT count(*) AS total,
       count(*) FILTER (WHERE meaning_cn IS NOT NULL AND meaning_cn <> '') AS with_cn
FROM word_roots;

\echo '=== question_knowledge_links stats ==='
SELECT count(*) AS total, count(DISTINCT question_id) AS questions, count(DISTINCT knowledge_point_id) AS kps
FROM question_knowledge_links;

\echo '=== knowledge_points with/without question links ==='
SELECT count(*) FILTER (WHERE id IN (SELECT DISTINCT knowledge_point_id FROM question_knowledge_links)) AS kp_with_links,
       count(*) FILTER (WHERE id NOT IN (SELECT DISTINCT knowledge_point_id FROM question_knowledge_links)) AS kp_without_links
FROM knowledge_points;

\echo '=== sample 3 kps with links ==='
SELECT kp.id, kp.name, kp.subject, kp.chapter, count(qkl.question_id) AS link_count
FROM knowledge_points kp
JOIN question_knowledge_links qkl ON qkl.knowledge_point_id = kp.id
GROUP BY kp.id
ORDER BY link_count DESC
LIMIT 3;

\echo '=== sample 3 kps without links ==='
SELECT kp.id, kp.name, kp.subject, kp.chapter
FROM knowledge_points kp
WHERE kp.id NOT IN (SELECT DISTINCT knowledge_point_id FROM question_knowledge_links)
ORDER BY kp.id
LIMIT 3;

\echo '=== min/max knowledge_point id ==='
SELECT min(id), max(id), count(*) FROM knowledge_points;