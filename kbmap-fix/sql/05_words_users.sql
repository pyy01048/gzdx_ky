\pset pager off
\echo '=== words user_id distribution ==='
SELECT user_id, count(*) FROM words GROUP BY user_id ORDER BY count(*) DESC;

\echo '=== word_decks user_id distribution ==='
SELECT user_id, count(*) FROM word_decks GROUP BY user_id ORDER BY count(*) DESC;

\echo '=== users relevant ==='
SELECT id, username, role FROM users WHERE username IN ('qa_tester','pyy') OR id IN (SELECT DISTINCT user_id FROM words WHERE user_id IS NOT NULL) ORDER BY id;