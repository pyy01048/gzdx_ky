-- 137_quiz_essay_stem_backfill.sql
-- 英语写作题治理（2026-11-24）：81 条 content 只有「写作（第N题）」标签。
-- A 类：analysis 内已有自足的英文指令（不依赖图表），原样搬入 content，恢复可作答；
-- B 类：指令缺失或依赖漫画/图表 → 移出练习池待补图（可逆，不删数据）。
-- 生成方式：backfill_local/cloud_essay_prompt.py（逐条从 analysis 抽取，未改写/未翻译）。

-- [#23035] 2007 写作（第51题） ← analysis 抽取（table）
UPDATE quiz_questions SET content = $q$Write a letter to your university library, making suggestions for improving its service.$q$, updated_at = now() WHERE id = 23035 AND content = $q$写作（第51题）$q$;
-- [#23339] 2011 写作（第47题） ← analysis 抽取（directions）
UPDATE quiz_questions SET content = $q$Suppose your cousin Li Ming has just gotten a job offer. Write him/her a letter to: 1) congratulate him/her, and 2) give him/her suggestions on how to get prepared for career life. You should write about 100 words. Do not sign your own name at the end of the letter. Use "Zhang Wei" instead. Do not write the address.$q$, updated_at = now() WHERE id = 23339 AND content = $q$写作（第47题）$q$;
-- [#23439] 2012 写作（第47题） ← analysis 抽取（directions）
UPDATE quiz_questions SET content = $q$Suppose you have found something wrong with the air-conditioner that you bought from a store the other day. Write an email to the customer service center to 1) make a complaint, and 2) demand a prompt solution. You should write about 100 words. Do not sign your own name at the end of the letter. Use "Zhang Wei" instead.$q$, updated_at = now() WHERE id = 23439 AND content = $q$写作（第47题）$q$;
-- [#23491] 2013 写作（第51题） ← analysis 抽取（table）
UPDATE quiz_questions SET content = $q$Write an e-mail of about 100 words to a foreign teacher in your college, inviting him/her to be a judge for the upcoming English speech contest. You should include the details you think necessary.$q$, updated_at = now() WHERE id = 23491 AND content = $q$写作（第51题）$q$;
-- [#23539] 2013 写作（第47题） ← analysis 抽取（directions）
UPDATE quiz_questions SET content = $q$Suppose your class is to hold a film festival. Write your classmates an email to 1) inform them about the details and 2) encourage them to participate. Don't sign your own name at the end of the e-mail. Use "Li Ming" instead.$q$, updated_at = now() WHERE id = 23539 AND content = $q$写作（第47题）$q$;
-- [#23591] 2014 写作（第51题） ← analysis 抽取（table）
UPDATE quiz_questions SET content = $q$Write a letter of about 100 words to the president of your university, suggesting how to improve students' physical condition.$q$, updated_at = now() WHERE id = 23591 AND content = $q$写作（第51题）$q$;
-- [#23639] 2014 写作（第47题） ← analysis 抽取（directions）
UPDATE quiz_questions SET content = $q$Suppose you are going to work as an invited counselor in the Campus Journalist Group, write group members an email to 1) tell them about your working habits, and 2) ask for advice about working there. You should write about 100 words. Do not use your own name. Use "Li Ming" instead. Do not write your address.$q$, updated_at = now() WHERE id = 23639 AND content = $q$写作（第47题）$q$;
-- [#23739] 2015 写作（第47题） ← analysis 抽取（directions）
UPDATE quiz_questions SET content = $q$Suppose your university is going to hold a university sports meeting. Write a notice to 1) briefly introduce the sports meeting, and 2) call for volunteers. You should write about 100 words on the ANSWER SHEET. Do not use your name or the name of your university.$q$, updated_at = now() WHERE id = 23739 AND content = $q$写作（第47题）$q$;
-- [#23891] 2017 写作（第51题） ← analysis 抽取（directions）
UPDATE quiz_questions SET content = $q$Your university is electing "Student of the Year". Write a letter of about 100 words to the selecting committee to 1) recommend one of your classmates and 2) give reasons for your recommendation. Do not sign your name at the end of the letter. Use "Li Ming" instead. Do not write the address.$q$, updated_at = now() WHERE id = 23891 AND content = $q$写作（第51题）$q$;
-- [#23991] 2018 写作（第51题） ← analysis 抽取（table）
UPDATE quiz_questions SET content = $q$Write an email to all international experts on campus inviting them to attend the graduation ceremony. In your email you should include time, place and other relevant information about the ceremony.$q$, updated_at = now() WHERE id = 23991 AND content = $q$写作（第51题）$q$;
-- [#24039] 2018 写作（第47题） ← analysis 抽取（table）
UPDATE quiz_questions SET content = $q$Suppose you have to cancel your travel plan and will not be able to visit Professor Smith. Write him an email to 1) apologize and explain the situation, and 2) suggest a future meeting.$q$, updated_at = now() WHERE id = 24039 AND content = $q$写作（第47题）$q$;
-- [#24091] 2019 写作（第51题） ← analysis 抽取（directions）
UPDATE quiz_questions SET content = $q$You are planning on taking a trip to Taiwan and you are browsing hotels online. Write an email of about 100 words to the hotel manager, inquiring about the information on the hotel. Do not sign your name at the end of the letter. Use "Li Ming" instead. Do not write the address.$q$, updated_at = now() WHERE id = 24091 AND content = $q$写作（第51题）$q$;
-- [#24239] 2020 写作（第47题） ← analysis 抽取（table）
UPDATE quiz_questions SET content = $q$Suppose you are planning a tour of a historical site for a group of international students. Write them an email to 1) tell them about the site, and 2) give them some tips for the tour.$q$, updated_at = now() WHERE id = 24239 AND content = $q$写作（第47题）$q$;
-- [#24291] 2021 写作（第51题） ← analysis 抽取（table）
UPDATE quiz_questions SET content = $q$A foreign friend of yours has recently graduated from college and intends to find a job in China. Write him/her an e-mail to make some suggestions.$q$, updated_at = now() WHERE id = 24291 AND content = $q$写作（第51题）$q$;
-- [#24391] 2022 写作（第51题） ← analysis 抽取（table）
UPDATE quiz_questions SET content = $q$Write an email to a professor at a British university, inviting him/her to organize a team for the international innovation contest to be held at your university.$q$, updated_at = now() WHERE id = 24391 AND content = $q$写作（第51题）$q$;
-- [#24491] 2023 写作（第51题） ← analysis 抽取（table）
UPDATE quiz_questions SET content = $q$Write a notice to recruit a student for Prof. Smith's research project on campus sports activities. Specify the duties and requirements of the job.$q$, updated_at = now() WHERE id = 24491 AND content = $q$写作（第51题）$q$;
-- [#24539] 2023 写作（第47题） ← analysis 抽取（table）
UPDATE quiz_questions SET content = $q$An art exhibition and a robot show are to be held on Sunday, and your friend David asks you which one he should go to. Write him an email to 1) make a suggestion, and 2) give your reason(s).$q$, updated_at = now() WHERE id = 24539 AND content = $q$写作（第47题）$q$;

-- B 类：无法还原指令，移出练习池
UPDATE quiz_questions
SET is_available = false,
    needs_review = true,
    validation_status = 'warn',
    validation_errors = coalesce(validation_errors, '[]'::jsonb)
      || '[{"code":"stem_label_only","detail":"英语写作题题干仅有「写作（第N题）」标签，原题指令/配图缺失，无法作答，已移出练习池待补题"}]'::jsonb,
    validated_at = now(),
    updated_at = now()
WHERE is_available = true
  AND question_type = 'essay'
  AND length(btrim(content)) < 12
  AND id IN (
22624, 22660, 22696, 22742, 22788, 22834, 22880, 22931, 22932, 22983, 22984, 23036, 23087, 23088, 23139, 23140, 23191, 23192, 23239, 23240, 23291, 23292, 23340, 23391, 23392, 23440, 23492, 23540, 23592, 23640, 23691, 23692, 23740, 23791, 23792, 23839, 23840, 23892, 23939, 23940, 23992, 24040, 24092, 24139, 24140, 24191, 24192, 24240, 24292, 24339, 24340, 24392, 24439, 24440, 24492, 24540, 24591, 24592, 24639, 24640, 24691, 24692, 24739, 24740
);
