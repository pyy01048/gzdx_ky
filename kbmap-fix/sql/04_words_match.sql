\pset pager off
\echo '=== words matched to word_roots via example_words (case-insensitive) ==='
SELECT count(DISTINCT w.id) AS words_matched_via_example_words
FROM words w
JOIN word_roots wr ON EXISTS (
  SELECT 1 FROM jsonb_array_elements_text(wr.example_words) ew
  WHERE lower(ew) = lower(w.word)
);

\echo '=== combined: words with root column OR matched via example_words ==='
SELECT count(*) AS total_words,
       count(*) FILTER (WHERE w.root IS NOT NULL AND w.root <> '') AS has_root_col,
       count(*) FILTER (WHERE wr.id IS NOT NULL) AS matched_root
FROM words w
LEFT JOIN word_roots wr ON EXISTS (
  SELECT 1 FROM jsonb_array_elements_text(wr.example_words) ew
  WHERE lower(ew) = lower(w.word)
);

\echo '=== example: words covered by word_examples ==='
SELECT count(*) AS total,
       count(*) FILTER (WHERE we.id IS NOT NULL) AS has_example
FROM words w
LEFT JOIN word_examples we ON we.word_id = w.id;

\echo '=== sample words without root col but matched via example_words ==='
SELECT w.id, w.word, wr.morpheme, wr.meaning_cn
FROM words w
JOIN word_roots wr ON EXISTS (
  SELECT 1 FROM jsonb_array_elements_text(wr.example_words) ew WHERE lower(ew) = lower(w.word)
)
WHERE (w.root IS NULL OR w.root = '')
ORDER BY w.id LIMIT 20;