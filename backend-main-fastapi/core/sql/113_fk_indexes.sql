-- 113_fk_indexes.sql
-- 单列外键缺失索引补齐（2026-10-21 体检 D8）。
--
-- 口径：information_schema 中单列外键，且该列不是任何现有索引的首列。
-- 实测缺失 34 条（报告正文写 30 条，以本文件生成时的实测为准）。
-- 幂等：CREATE INDEX IF NOT EXISTS；重复执行不报错。

CREATE INDEX IF NOT EXISTS ix_fk_code_submission_results_testcase_id ON code_submission_results (testcase_id);
CREATE INDEX IF NOT EXISTS ix_fk_documents_chapter_id ON documents (chapter_id);
CREATE INDEX IF NOT EXISTS ix_fk_ebbinghaus_items_subject_id ON ebbinghaus_items (subject_id);
CREATE INDEX IF NOT EXISTS ix_fk_error_knowledge_links_chunk_id ON error_knowledge_links (chunk_id);
CREATE INDEX IF NOT EXISTS ix_fk_error_knowledge_links_document_id ON error_knowledge_links (document_id);
CREATE INDEX IF NOT EXISTS ix_fk_error_knowledge_links_knowledge_point_id ON error_knowledge_links (knowledge_point_id);
CREATE INDEX IF NOT EXISTS ix_fk_error_records_question_id ON error_records (question_id);
CREATE INDEX IF NOT EXISTS ix_fk_exam_answers_question_id ON exam_answers (question_id);
CREATE INDEX IF NOT EXISTS ix_fk_flashcards_knowledge_point_id ON flashcards (knowledge_point_id);
CREATE INDEX IF NOT EXISTS ix_fk_kaoyan_admissions_major_id ON kaoyan_admissions (major_id);
CREATE INDEX IF NOT EXISTS ix_fk_kaoyan_major_kb_link_school_id ON kaoyan_major_kb_link (school_id);
CREATE INDEX IF NOT EXISTS ix_fk_kaoyan_majors_college_id ON kaoyan_majors (college_id);
CREATE INDEX IF NOT EXISTS ix_fk_kaoyan_scorelines_major_id ON kaoyan_scorelines (major_id);
CREATE INDEX IF NOT EXISTS ix_fk_knowledge_chunks_chapter_id ON knowledge_chunks (chapter_id);
CREATE INDEX IF NOT EXISTS ix_fk_knowledge_points_chapter_id ON knowledge_points (chapter_id);
CREATE INDEX IF NOT EXISTS ix_fk_knowledge_points_source_chunk_id ON knowledge_points (source_chunk_id);
CREATE INDEX IF NOT EXISTS ix_fk_misconceptions_error_record_id ON misconceptions (error_record_id);
CREATE INDEX IF NOT EXISTS ix_fk_misconceptions_question_id ON misconceptions (question_id);
CREATE INDEX IF NOT EXISTS ix_fk_paper_questions_question_id ON paper_questions (question_id);
CREATE INDEX IF NOT EXISTS ix_fk_papers_subject_id ON papers (subject_id);
CREATE INDEX IF NOT EXISTS ix_fk_pending_questions_user_id ON pending_questions (user_id);
CREATE INDEX IF NOT EXISTS ix_fk_quiz_attempts_user_id ON quiz_attempts (user_id);
CREATE INDEX IF NOT EXISTS ix_fk_quiz_questions_origin_chunk_id ON quiz_questions (origin_chunk_id);
CREATE INDEX IF NOT EXISTS ix_fk_school_aliases_school_id ON school_aliases (school_id);
CREATE INDEX IF NOT EXISTS ix_fk_sft_examples_subject_id ON sft_examples (subject_id);
CREATE INDEX IF NOT EXISTS ix_fk_study_events_chapter_id ON study_events (chapter_id);
CREATE INDEX IF NOT EXISTS ix_fk_study_events_knowledge_point_id ON study_events (knowledge_point_id);
CREATE INDEX IF NOT EXISTS ix_fk_study_events_question_id ON study_events (question_id);
CREATE INDEX IF NOT EXISTS ix_fk_study_events_subject_id ON study_events (subject_id);
CREATE INDEX IF NOT EXISTS ix_fk_study_sessions_subject_id ON study_sessions (subject_id);
CREATE INDEX IF NOT EXISTS ix_fk_subject_aliases_subject_id ON subject_aliases (subject_id);
CREATE INDEX IF NOT EXISTS ix_fk_subject_discipline_links_discipline_id ON subject_discipline_links (discipline_id);
CREATE INDEX IF NOT EXISTS ix_fk_tasks_chapter_id ON tasks (chapter_id);
CREATE INDEX IF NOT EXISTS ix_fk_week_plans_month_plan_id ON week_plans (month_plan_id);
