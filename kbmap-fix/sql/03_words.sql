\pset pager off
\echo '=== words.root sample values (first 30 non-null) ==='
SELECT id, word, root FROM words WHERE root IS NOT NULL AND root <> '' ORDER BY id LIMIT 30;

\echo '=== word_roots sample (first 15) ==='
SELECT id, morpheme, variants, type, meaning, meaning_cn, example_words
FROM word_roots ORDER BY id LIMIT 15;

\echo '=== word root column tokens matching word_roots.morpheme ==='
WITH word_tokens AS (
  SELECT id, word, root,
         trim(both ' -' FROM t) AS tok
  FROM words, unnest(string_to_array(regexp_replace(root, '[\s,，、;；/]+', ','), ',')) AS t
  WHERE root IS NOT NULL AND root <> ''
)
SELECT count(DISTINCT wt.id) AS words_with_root_col,
       count(DISTINCT wt.id) FILTER (WHERE wr.id IS NOT NULL) AS words_with_matched_root
FROM word_tokens wt
LEFT JOIN word_roots wr ON wr.morpheme = wt.tok
   OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(wr.variants) v WHERE v = wt.tok);

\echo '=== words with example col empty but have word_examples ==='
SELECT count(*) AS words_needing_example_fill
FROM words w
WHERE (w.example IS NULL OR w.example = '')
  AND EXISTS (SELECT 1 FROM word_examples we WHERE we.word_id = w.id);

\echo '=== sample word with examples ==='
SELECT w.id, w.word, w.root, w.example,
       (SELECT jsonb_agg(jsonb_build_object('en', we.sentence_en, 'cn', we.sentence_cn))
        FROM (SELECT sentence_en, sentence_cn FROM word_examples WHERE word_id = w.id ORDER BY (sentence_cn IS NOT NULL) DESC, id LIMIT 2) we) AS examples
FROM words w
WHERE EXISTS (SELECT 1 FROM word_examples we WHERE we.word_id = w.id)
ORDER BY w.id LIMIT 5;

\echo '=== words.root column: how many words have it vs word_roots coverage ==='
SELECT count(*) AS total_words,
       count(*) FILTER (WHERE root IS NOT NULL AND root <> '') AS has_root
FROM words;

\echo '=== word_roots example_words sample ==='
SELECT id, morpheme, example_words FROM word_roots WHERE example_words IS NOT NULL LIMIT 5;