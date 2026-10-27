--
-- PostgreSQL database dump
--

\restrict RBlXhaCLB5bdV6ewnLPsv2NyqZPu9G0HStfPqNfqVbMp4rB203J3tHL4rKpGR82

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: kaoyan_admissions; Type: TABLE; Schema: public; Owner: kaoyan
--

CREATE TABLE public.kaoyan_admissions (
    id bigint NOT NULL,
    school_id bigint NOT NULL,
    major_id bigint,
    year integer NOT NULL,
    enroll_count integer,
    retest_count integer,
    admit_count integer,
    admit_avg_score real,
    major_avg_score real,
    retest_ratio real,
    data_source character varying(50),
    source character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    deleted_at timestamp with time zone
);


ALTER TABLE public.kaoyan_admissions OWNER TO kaoyan;

--
-- Name: TABLE kaoyan_admissions; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON TABLE public.kaoyan_admissions IS '招生录取数据表：招生人数 / 录取均分 / 复录比';


--
-- Name: COLUMN kaoyan_admissions.school_id; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_admissions.school_id IS '院校 ID，级联删除';


--
-- Name: COLUMN kaoyan_admissions.major_id; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_admissions.major_id IS '专业 ID，级联删除';


--
-- Name: COLUMN kaoyan_admissions.year; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_admissions.year IS '招生年份';


--
-- Name: COLUMN kaoyan_admissions.enroll_count; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_admissions.enroll_count IS '计划招生人数';


--
-- Name: COLUMN kaoyan_admissions.retest_count; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_admissions.retest_count IS '进入复试人数';


--
-- Name: COLUMN kaoyan_admissions.admit_count; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_admissions.admit_count IS '实际录取人数';


--
-- Name: COLUMN kaoyan_admissions.admit_avg_score; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_admissions.admit_avg_score IS '录取平均分';


--
-- Name: COLUMN kaoyan_admissions.major_avg_score; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_admissions.major_avg_score IS '专业课平均分';


--
-- Name: COLUMN kaoyan_admissions.retest_ratio; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_admissions.retest_ratio IS '复录比';


--
-- Name: COLUMN kaoyan_admissions.data_source; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_admissions.data_source IS '采集来源';


--
-- Name: COLUMN kaoyan_admissions.source; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_admissions.source IS '采集批次标识';


--
-- Name: kaoyan_admissions_id_seq; Type: SEQUENCE; Schema: public; Owner: kaoyan
--

CREATE SEQUENCE public.kaoyan_admissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.kaoyan_admissions_id_seq OWNER TO kaoyan;

--
-- Name: kaoyan_admissions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kaoyan
--

ALTER SEQUENCE public.kaoyan_admissions_id_seq OWNED BY public.kaoyan_admissions.id;


--
-- Name: kaoyan_colleges; Type: TABLE; Schema: public; Owner: kaoyan
--

CREATE TABLE public.kaoyan_colleges (
    id bigint NOT NULL,
    school_id bigint NOT NULL,
    name character varying(200) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    deleted_at timestamp with time zone
);


ALTER TABLE public.kaoyan_colleges OWNER TO kaoyan;

--
-- Name: TABLE kaoyan_colleges; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON TABLE public.kaoyan_colleges IS '院校下属学院表';


--
-- Name: COLUMN kaoyan_colleges.school_id; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_colleges.school_id IS '所属院校 ID，院校删除时级联删除';


--
-- Name: COLUMN kaoyan_colleges.name; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_colleges.name IS '学院名称';


--
-- Name: kaoyan_colleges_id_seq; Type: SEQUENCE; Schema: public; Owner: kaoyan
--

CREATE SEQUENCE public.kaoyan_colleges_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.kaoyan_colleges_id_seq OWNER TO kaoyan;

--
-- Name: kaoyan_colleges_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kaoyan
--

ALTER SEQUENCE public.kaoyan_colleges_id_seq OWNED BY public.kaoyan_colleges.id;


--
-- Name: kaoyan_majors; Type: TABLE; Schema: public; Owner: kaoyan
--

CREATE TABLE public.kaoyan_majors (
    id bigint NOT NULL,
    school_id bigint NOT NULL,
    college_id bigint,
    code character varying(20),
    name character varying(200) NOT NULL,
    research_direction character varying(300),
    subject_code character varying(20),
    exam_subjects jsonb DEFAULT '[]'::jsonb NOT NULL,
    reference_books jsonb DEFAULT '[]'::jsonb NOT NULL,
    degree_type public.degree_type DEFAULT 'unknown'::public.degree_type NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    deleted_at timestamp with time zone
);


ALTER TABLE public.kaoyan_majors OWNER TO kaoyan;

--
-- Name: TABLE kaoyan_majors; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON TABLE public.kaoyan_majors IS '招生专业表';


--
-- Name: COLUMN kaoyan_majors.school_id; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_majors.school_id IS '所属院校 ID，院校删除时级联删除';


--
-- Name: COLUMN kaoyan_majors.college_id; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_majors.college_id IS '所属学院 ID';


--
-- Name: COLUMN kaoyan_majors.code; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_majors.code IS '专业代码';


--
-- Name: COLUMN kaoyan_majors.research_direction; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_majors.research_direction IS '研究方向';


--
-- Name: COLUMN kaoyan_majors.subject_code; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_majors.subject_code IS '所属学科代码';


--
-- Name: COLUMN kaoyan_majors.exam_subjects; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_majors.exam_subjects IS '初试科目数组（JSON）';


--
-- Name: COLUMN kaoyan_majors.reference_books; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_majors.reference_books IS '参考书目数组（JSON）';


--
-- Name: COLUMN kaoyan_majors.degree_type; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_majors.degree_type IS '学位类型：academic 学硕 / professional 专硕 / unknown';


--
-- Name: kaoyan_majors_id_seq; Type: SEQUENCE; Schema: public; Owner: kaoyan
--

CREATE SEQUENCE public.kaoyan_majors_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.kaoyan_majors_id_seq OWNER TO kaoyan;

--
-- Name: kaoyan_majors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kaoyan
--

ALTER SEQUENCE public.kaoyan_majors_id_seq OWNED BY public.kaoyan_majors.id;


--
-- Name: kaoyan_notices; Type: TABLE; Schema: public; Owner: kaoyan
--

CREATE TABLE public.kaoyan_notices (
    id bigint NOT NULL,
    school_id bigint,
    school_name text,
    title text NOT NULL,
    notice_type public.notice_type DEFAULT '公告'::public.notice_type NOT NULL,
    publish_date text,
    url text,
    source text,
    fetched_at text,
    importance_level public.importance_level,
    importance_score real,
    importance_reason text,
    deadline_date text,
    events_json text,
    classified_at text,
    is_read boolean DEFAULT false NOT NULL,
    is_starred boolean DEFAULT false NOT NULL,
    read_at text,
    starred_at text,
    content text,
    is_noise boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.kaoyan_notices OWNER TO kaoyan;

--
-- Name: TABLE kaoyan_notices; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON TABLE public.kaoyan_notices IS '研招通知表：院校公告/简章/复试/调剂/录取信息';


--
-- Name: COLUMN kaoyan_notices.school_id; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_notices.school_id IS '解析出的院校 ID，未匹配上为空';


--
-- Name: COLUMN kaoyan_notices.school_name; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_notices.school_name IS '通知上写的院校名原文';


--
-- Name: COLUMN kaoyan_notices.notice_type; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_notices.notice_type IS '通知类型：公告 / 简章 / 复试 / 调剂 / 录取';


--
-- Name: COLUMN kaoyan_notices.publish_date; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_notices.publish_date IS '发布日期（YYYY-MM-DD）';


--
-- Name: COLUMN kaoyan_notices.importance_level; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_notices.importance_level IS '重要级：urgent / important / normal / low';


--
-- Name: COLUMN kaoyan_notices.importance_score; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_notices.importance_score IS '重要度评分 0-1';


--
-- Name: COLUMN kaoyan_notices.importance_reason; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_notices.importance_reason IS '重要度判定理由';


--
-- Name: COLUMN kaoyan_notices.deadline_date; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_notices.deadline_date IS '截止日期（YYYY-MM-DD）';


--
-- Name: COLUMN kaoyan_notices.events_json; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_notices.events_json IS '抽取出的关键事件（JSON 数组）';


--
-- Name: COLUMN kaoyan_notices.is_noise; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_notices.is_noise IS '是否为噪声通知（招生宣传/无关资讯）';


--
-- Name: COLUMN kaoyan_notices.created_at; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_notices.created_at IS '入库时间（UTC，带时区）';


--
-- Name: kaoyan_notices_id_seq; Type: SEQUENCE; Schema: public; Owner: kaoyan
--

CREATE SEQUENCE public.kaoyan_notices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.kaoyan_notices_id_seq OWNER TO kaoyan;

--
-- Name: kaoyan_notices_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kaoyan
--

ALTER SEQUENCE public.kaoyan_notices_id_seq OWNED BY public.kaoyan_notices.id;


--
-- Name: kaoyan_schools; Type: TABLE; Schema: public; Owner: kaoyan
--

CREATE TABLE public.kaoyan_schools (
    id bigint NOT NULL,
    name character varying(200) NOT NULL,
    level character varying(50),
    province character varying(50),
    city character varying(50),
    logo_url character varying(500),
    intro text,
    tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    official_url character varying(500),
    data_source character varying(50),
    type character varying(30),
    region character varying(30),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    deleted_at timestamp with time zone
);


ALTER TABLE public.kaoyan_schools OWNER TO kaoyan;

--
-- Name: TABLE kaoyan_schools; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON TABLE public.kaoyan_schools IS '院校主数据表';


--
-- Name: COLUMN kaoyan_schools.name; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.name IS '院校名称，唯一';


--
-- Name: COLUMN kaoyan_schools.level; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.level IS '院校层次：985 / 211 / 双一流 / 普通';


--
-- Name: COLUMN kaoyan_schools.province; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.province IS '所在省份';


--
-- Name: COLUMN kaoyan_schools.city; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.city IS '所在城市';


--
-- Name: COLUMN kaoyan_schools.logo_url; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.logo_url IS '校徽地址';


--
-- Name: COLUMN kaoyan_schools.intro; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.intro IS '院校简介';


--
-- Name: COLUMN kaoyan_schools.tags; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.tags IS '院校标签数组，如 ["985","自主划线"]';


--
-- Name: COLUMN kaoyan_schools.official_url; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.official_url IS '官网地址';


--
-- Name: COLUMN kaoyan_schools.data_source; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.data_source IS '数据采集来源';


--
-- Name: COLUMN kaoyan_schools.type; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.type IS '院校类型：综合 / 理工 / 师范 等';


--
-- Name: COLUMN kaoyan_schools.region; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.region IS '所属地区';


--
-- Name: COLUMN kaoyan_schools.created_at; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.created_at IS '创建时间（UTC，带时区）';


--
-- Name: COLUMN kaoyan_schools.updated_at; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_schools.updated_at IS '最后更新时间';


--
-- Name: kaoyan_schools_id_seq; Type: SEQUENCE; Schema: public; Owner: kaoyan
--

CREATE SEQUENCE public.kaoyan_schools_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.kaoyan_schools_id_seq OWNER TO kaoyan;

--
-- Name: kaoyan_schools_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kaoyan
--

ALTER SEQUENCE public.kaoyan_schools_id_seq OWNED BY public.kaoyan_schools.id;


--
-- Name: kaoyan_scorelines; Type: TABLE; Schema: public; Owner: kaoyan
--

CREATE TABLE public.kaoyan_scorelines (
    id bigint NOT NULL,
    school_id bigint NOT NULL,
    major_id bigint,
    year integer NOT NULL,
    total_line integer,
    politics_line integer,
    english_line integer,
    math_line integer,
    major_line integer,
    national_line integer,
    retest_line integer,
    line_type character varying(20),
    source character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    deleted_at timestamp with time zone
);


ALTER TABLE public.kaoyan_scorelines OWNER TO kaoyan;

--
-- Name: TABLE kaoyan_scorelines; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON TABLE public.kaoyan_scorelines IS '分数线表：校线 / 院线 / 国家线 / 复试线';


--
-- Name: COLUMN kaoyan_scorelines.total_line; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_scorelines.total_line IS '总分线';


--
-- Name: COLUMN kaoyan_scorelines.politics_line; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_scorelines.politics_line IS '政治单科线';


--
-- Name: COLUMN kaoyan_scorelines.english_line; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_scorelines.english_line IS '英语单科线';


--
-- Name: COLUMN kaoyan_scorelines.math_line; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_scorelines.math_line IS '数学单科线';


--
-- Name: COLUMN kaoyan_scorelines.major_line; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_scorelines.major_line IS '专业课单科线';


--
-- Name: COLUMN kaoyan_scorelines.national_line; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_scorelines.national_line IS '当年国家线';


--
-- Name: COLUMN kaoyan_scorelines.retest_line; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_scorelines.retest_line IS '复试线';


--
-- Name: COLUMN kaoyan_scorelines.line_type; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_scorelines.line_type IS '线的类型：national 国家线 / school 校线 / college 院线 / retest 复试线';


--
-- Name: COLUMN kaoyan_scorelines.created_at; Type: COMMENT; Schema: public; Owner: kaoyan
--

COMMENT ON COLUMN public.kaoyan_scorelines.created_at IS '创建时间（UTC，带时区）';


--
-- Name: kaoyan_scorelines_id_seq; Type: SEQUENCE; Schema: public; Owner: kaoyan
--

CREATE SEQUENCE public.kaoyan_scorelines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.kaoyan_scorelines_id_seq OWNER TO kaoyan;

--
-- Name: kaoyan_scorelines_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: kaoyan
--

ALTER SEQUENCE public.kaoyan_scorelines_id_seq OWNED BY public.kaoyan_scorelines.id;


--
-- Name: kaoyan_admissions id; Type: DEFAULT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_admissions ALTER COLUMN id SET DEFAULT nextval('public.kaoyan_admissions_id_seq'::regclass);


--
-- Name: kaoyan_colleges id; Type: DEFAULT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_colleges ALTER COLUMN id SET DEFAULT nextval('public.kaoyan_colleges_id_seq'::regclass);


--
-- Name: kaoyan_majors id; Type: DEFAULT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_majors ALTER COLUMN id SET DEFAULT nextval('public.kaoyan_majors_id_seq'::regclass);


--
-- Name: kaoyan_notices id; Type: DEFAULT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_notices ALTER COLUMN id SET DEFAULT nextval('public.kaoyan_notices_id_seq'::regclass);


--
-- Name: kaoyan_schools id; Type: DEFAULT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_schools ALTER COLUMN id SET DEFAULT nextval('public.kaoyan_schools_id_seq'::regclass);


--
-- Name: kaoyan_scorelines id; Type: DEFAULT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_scorelines ALTER COLUMN id SET DEFAULT nextval('public.kaoyan_scorelines_id_seq'::regclass);


--
-- Data for Name: kaoyan_admissions; Type: TABLE DATA; Schema: public; Owner: kaoyan
--

COPY public.kaoyan_admissions (id, school_id, major_id, year, enroll_count, retest_count, admit_count, admit_avg_score, major_avg_score, retest_ratio, data_source, source, created_at, enabled, deleted_at) FROM stdin;
3	643	\N	2026	\N	\N	8	\N	\N	\N	notice:1679	\N	2026-10-19 12:20:18.242109+08	t	\N
4	643	\N	2026	\N	\N	53	326.8	\N	\N	notice:1680	\N	2026-10-19 12:20:31.409902+08	t	\N
5	108	\N	2018	\N	37	\N	329.1	\N	\N	notice:1524	\N	2026-10-19 12:21:07.961585+08	t	\N
6	108	\N	2018	\N	\N	\N	384.3	\N	\N	notice:1521	\N	2026-10-19 13:46:08.503536+08	t	\N
7	108	\N	2018	\N	\N	2	378	\N	\N	notice:1523	\N	2026-10-19 13:47:54.041951+08	t	\N
8	108	\N	2026	\N	23	\N	362.7	\N	\N	notice:2392:4	\N	2026-10-19 15:35:18.532029+08	t	\N
9	108	\N	2026	\N	6	\N	392.3	\N	\N	notice:2391:6	\N	2026-10-19 15:36:23.420085+08	t	\N
10	108	\N	2026	\N	32	\N	376.7	\N	\N	notice:2391:7	\N	2026-10-19 15:36:26.172472+08	t	\N
11	108	\N	2026	\N	3	\N	\N	\N	\N	notice:2391:8	\N	2026-10-19 15:36:31.332479+08	t	\N
12	108	\N	2026	\N	160	\N	159	\N	\N	notice:2391:13	\N	2026-10-19 15:36:42.229066+08	t	\N
13	108	\N	2026	\N	62	\N	189.1	\N	\N	notice:2392:6	\N	2026-10-19 15:37:06.761705+08	t	\N
14	108	\N	2026	\N	27	\N	180.1	\N	\N	notice:2392:7	\N	2026-10-19 15:37:09.711661+08	t	\N
15	108	\N	2026	\N	97	\N	220.2	\N	\N	notice:2392:8	\N	2026-10-19 15:37:12.537189+08	t	\N
16	108	\N	2026	\N	221	\N	201.9	\N	\N	notice:2392:9	\N	2026-10-19 15:37:15.991179+08	t	\N
17	108	\N	2026	\N	209	\N	192	\N	\N	notice:2392:10	\N	2026-10-19 15:37:19.743984+08	t	\N
18	108	\N	2026	\N	9	\N	164.3	\N	\N	notice:2392:11	\N	2026-10-19 15:37:22.707467+08	t	\N
19	108	\N	2026	\N	22	\N	387.2	\N	\N	notice:2392:20	\N	2026-10-19 15:37:47.525641+08	t	\N
20	108	\N	2026	\N	18	\N	358.2	\N	\N	notice:2392:27	\N	2026-10-19 15:38:06.149753+08	t	\N
21	108	\N	2026	\N	8	\N	391.6	\N	\N	notice:2392:28	\N	2026-10-19 15:38:09.716372+08	t	\N
22	108	\N	2026	\N	17	\N	376.6	\N	\N	notice:2392:31	\N	2026-10-19 15:38:17.593536+08	t	\N
23	108	\N	2026	\N	43	\N	399.7	\N	\N	notice:2392:39	\N	2026-10-19 15:38:36.217169+08	t	\N
24	108	\N	2026	\N	36	\N	364.4	\N	\N	notice:2392:42	\N	2026-10-19 15:38:53.649169+08	t	\N
25	108	\N	2026	\N	2	\N	376.5	\N	\N	notice:2392:43	\N	2026-10-19 15:39:00.007557+08	t	\N
26	592	\N	2026	\N	\N	74	346.7	\N	\N	notice:2395	\N	2026-10-19 22:20:45.685909+08	t	\N
27	108	\N	2026	\N	407	\N	202.9	\N	\N	notice:2392	\N	2026-10-19 23:46:18.722631+08	t	\N
\.


--
-- Data for Name: kaoyan_colleges; Type: TABLE DATA; Schema: public; Owner: kaoyan
--

COPY public.kaoyan_colleges (id, school_id, name, created_at, enabled, deleted_at) FROM stdin;
\.


--
-- Data for Name: kaoyan_majors; Type: TABLE DATA; Schema: public; Owner: kaoyan
--

COPY public.kaoyan_majors (id, school_id, college_id, code, name, research_direction, subject_code, exam_subjects, reference_books, degree_type, created_at, enabled, deleted_at) FROM stdin;
1	3	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 00:00:27.550813+08	t	\N
2	3	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 00:00:27.550818+08	t	\N
3	3	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 00:00:27.55082+08	t	\N
4	3	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 00:00:27.550821+08	t	\N
5	3	\N	0810J2	低空技术与工程	\N	0810	[]	[]	academic	2026-10-19 00:00:27.550822+08	t	\N
6	3	\N	0810Z1	数字媒体技术	\N	0810	[]	[]	academic	2026-10-19 00:00:27.550823+08	t	\N
7	3	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 00:00:27.550824+08	t	\N
8	3	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 00:00:27.550825+08	t	\N
9	3	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 00:00:27.550826+08	t	\N
10	3	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 00:00:27.550827+08	t	\N
11	4	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 00:00:32.545241+08	t	\N
12	4	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 00:00:32.545256+08	t	\N
13	4	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 00:00:32.545258+08	t	\N
14	4	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 00:00:32.545259+08	t	\N
15	4	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 00:00:32.54526+08	t	\N
16	4	\N	0806J4	储能化学与物理	\N	0806	[]	[]	academic	2026-10-19 00:00:32.545261+08	t	\N
17	4	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 00:00:32.545262+08	t	\N
18	4	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 00:00:32.545263+08	t	\N
19	4	\N	0810J1	人工智能科学与工程	\N	0810	[]	[]	academic	2026-10-19 00:00:32.545264+08	t	\N
20	4	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 00:00:32.545265+08	t	\N
21	5	\N	0812J3	数据科学和信息技术	\N	0812	[]	[]	academic	2026-10-19 00:00:36.786492+08	t	\N
22	5	\N	085100	建筑	\N	0851	[]	[]	professional	2026-10-19 00:00:36.786495+08	t	\N
23	5	\N	085300	城乡规划	\N	0853	[]	[]	professional	2026-10-19 00:00:36.786496+08	t	\N
24	5	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 00:00:36.786497+08	t	\N
25	5	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 00:00:36.786498+08	t	\N
26	5	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 00:00:36.786499+08	t	\N
27	5	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 00:00:36.786499+08	t	\N
28	5	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 00:00:36.7865+08	t	\N
29	5	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 00:00:36.786501+08	t	\N
30	5	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 00:00:36.786502+08	t	\N
31	3	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 00:44:25.194863+08	t	\N
32	3	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 00:44:25.194867+08	t	\N
33	3	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 00:44:25.194868+08	t	\N
34	3	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 00:44:25.194868+08	t	\N
35	4	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 00:44:29.66442+08	t	\N
36	4	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 00:44:29.664429+08	t	\N
37	4	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 00:44:29.664432+08	t	\N
38	4	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 00:44:29.664435+08	t	\N
39	4	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 00:44:29.664437+08	t	\N
40	4	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 00:44:29.664439+08	t	\N
41	4	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 00:44:29.664441+08	t	\N
42	5	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 00:44:33.920076+08	t	\N
43	5	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 00:44:33.920078+08	t	\N
44	6	\N	0805J6	科学智能	\N	0805	[]	[]	academic	2026-10-19 02:14:30.150491+08	t	\N
45	6	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:14:30.150505+08	t	\N
46	6	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:14:30.15051+08	t	\N
47	6	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:14:30.150512+08	t	\N
48	6	\N	0812J6	科学智能	\N	0812	[]	[]	academic	2026-10-19 02:14:30.150515+08	t	\N
49	6	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:14:30.150518+08	t	\N
50	6	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:14:30.15052+08	t	\N
51	6	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:14:30.150522+08	t	\N
52	6	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:14:30.150524+08	t	\N
53	6	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 02:14:30.150526+08	t	\N
54	6	\N	0705Z7	国土空间规划	\N	0705	[]	[]	academic	2026-10-19 02:14:30.150528+08	t	\N
55	6	\N	077601	环境科学	\N	0776	[]	[]	academic	2026-10-19 02:14:30.15053+08	t	\N
56	6	\N	077602	环境工程	\N	0776	[]	[]	academic	2026-10-19 02:14:30.150532+08	t	\N
57	7	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:14:37.624713+08	t	\N
58	7	\N	0812Z3	人工智能	\N	0812	[]	[]	academic	2026-10-19 02:14:37.624722+08	t	\N
59	7	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:14:37.624725+08	t	\N
60	7	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:14:37.624728+08	t	\N
61	7	\N	087100	管理科学与工程	\N	0871	[]	[]	academic	2026-10-19 02:14:37.62473+08	t	\N
62	7	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:14:37.624732+08	t	\N
63	7	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:14:37.624734+08	t	\N
64	7	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:14:37.624735+08	t	\N
65	7	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:14:37.624737+08	t	\N
66	7	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:14:37.624739+08	t	\N
67	7	\N	0752S1	数据科学	\N	0752	[]	[]	professional	2026-10-19 02:14:37.624741+08	t	\N
68	8	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:14:44.357787+08	t	\N
69	8	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:14:44.357798+08	t	\N
70	8	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:14:44.357802+08	t	\N
71	8	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:14:44.357805+08	t	\N
72	8	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:14:44.357807+08	t	\N
73	8	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:14:44.357809+08	t	\N
74	8	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:14:44.35781+08	t	\N
75	8	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:14:44.357812+08	t	\N
76	8	\N	0810J1	低空技术与工程	\N	0810	[]	[]	academic	2026-10-19 02:14:44.357814+08	t	\N
77	8	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:14:44.357816+08	t	\N
78	8	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:14:44.357818+08	t	\N
79	8	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:14:44.357821+08	t	\N
80	8	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:14:44.357823+08	t	\N
81	8	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 02:14:44.357825+08	t	\N
82	8	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:14:44.357826+08	t	\N
83	9	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:14:50.242343+08	t	\N
84	9	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:14:50.242346+08	t	\N
85	9	\N	0802J1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:14:50.242346+08	t	\N
86	9	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:14:50.242347+08	t	\N
87	9	\N	0803J1	量子科学与技术	\N	0803	[]	[]	academic	2026-10-19 02:14:50.242347+08	t	\N
88	9	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:14:50.242348+08	t	\N
89	9	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:14:50.242348+08	t	\N
90	9	\N	0805J2	资源环境与循环经济	\N	0805	[]	[]	academic	2026-10-19 02:14:50.242349+08	t	\N
91	9	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:14:50.242349+08	t	\N
92	9	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:14:50.242349+08	t	\N
93	9	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:14:50.24235+08	t	\N
94	9	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:14:50.24235+08	t	\N
95	9	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:14:50.242351+08	t	\N
96	9	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:14:50.242351+08	t	\N
97	9	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:14:50.242351+08	t	\N
98	10	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:14:57.834274+08	t	\N
99	10	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:14:57.834277+08	t	\N
100	10	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:14:57.834277+08	t	\N
101	10	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:14:57.834278+08	t	\N
102	10	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:14:57.834278+08	t	\N
103	10	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:14:57.834279+08	t	\N
104	10	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:14:57.834279+08	t	\N
105	10	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:14:57.83428+08	t	\N
106	10	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:14:57.83428+08	t	\N
107	10	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:14:57.83428+08	t	\N
108	10	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:14:57.834281+08	t	\N
109	10	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:14:57.834281+08	t	\N
110	10	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:14:57.834282+08	t	\N
111	10	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 02:14:57.834282+08	t	\N
112	10	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:14:57.834282+08	t	\N
113	10	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 02:14:57.834283+08	t	\N
114	11	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:15:05.634033+08	t	\N
115	11	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:15:05.634036+08	t	\N
116	11	\N	0802J1	工业与系统工程	\N	0802	[]	[]	academic	2026-10-19 02:15:05.634036+08	t	\N
117	11	\N	0802J2	光机电微纳制造	\N	0802	[]	[]	academic	2026-10-19 02:15:05.634037+08	t	\N
118	11	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:15:05.634037+08	t	\N
119	11	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:15:05.634038+08	t	\N
120	11	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:15:05.634038+08	t	\N
121	11	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:15:05.634038+08	t	\N
122	11	\N	0807J1	机电储能科学与工程	\N	0807	[]	[]	academic	2026-10-19 02:15:05.634039+08	t	\N
123	11	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:15:05.634039+08	t	\N
124	11	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:15:05.63404+08	t	\N
125	11	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:15:05.63404+08	t	\N
126	11	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:15:05.63404+08	t	\N
127	11	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:15:05.634041+08	t	\N
128	11	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:15:05.634041+08	t	\N
129	11	\N	0752S2	数据科学	\N	0752	[]	[]	professional	2026-10-19 02:15:05.634042+08	t	\N
130	11	\N	079903	低空技术与工程	\N	0799	[]	[]	academic	2026-10-19 02:15:05.634042+08	t	\N
131	12	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:15:12.476475+08	t	\N
132	12	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:15:12.476483+08	t	\N
133	12	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:15:12.476487+08	t	\N
134	12	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:15:12.476489+08	t	\N
135	12	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:15:12.476491+08	t	\N
136	12	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:15:12.476493+08	t	\N
137	12	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:15:12.476495+08	t	\N
138	12	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:15:12.476497+08	t	\N
139	12	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:15:12.476499+08	t	\N
140	12	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:15:12.476501+08	t	\N
141	12	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:15:12.476503+08	t	\N
142	12	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:15:12.476505+08	t	\N
143	13	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 02:15:19.380717+08	t	\N
144	13	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:15:19.380727+08	t	\N
145	13	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:15:19.38073+08	t	\N
146	13	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:15:19.380732+08	t	\N
147	13	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:15:19.380734+08	t	\N
148	13	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:15:19.380736+08	t	\N
149	13	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:15:19.380738+08	t	\N
150	13	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:15:19.38074+08	t	\N
151	13	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:15:19.380742+08	t	\N
152	13	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:15:19.380744+08	t	\N
153	13	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:15:19.380746+08	t	\N
154	13	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:15:19.380748+08	t	\N
155	13	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:15:19.38075+08	t	\N
156	14	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:15:25.569348+08	t	\N
157	14	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:15:25.56935+08	t	\N
158	14	\N	082102	纺织材料与纺织品设计	\N	0821	[]	[]	academic	2026-10-19 02:15:25.569351+08	t	\N
159	14	\N	082103	纺织化学与染整工程	\N	0821	[]	[]	academic	2026-10-19 02:15:25.569351+08	t	\N
160	14	\N	082104	服装设计与工程	\N	0821	[]	[]	academic	2026-10-19 02:15:25.569352+08	t	\N
161	14	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:15:25.569352+08	t	\N
162	15	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:15:32.06944+08	t	\N
163	15	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:15:32.069442+08	t	\N
164	15	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:15:32.069443+08	t	\N
165	15	\N	082200	轻工技术与工程	\N	0822	[]	[]	academic	2026-10-19 02:15:32.069443+08	t	\N
166	15	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:15:32.069444+08	t	\N
167	15	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:15:32.069444+08	t	\N
168	15	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:15:32.069445+08	t	\N
169	15	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:15:32.069445+08	t	\N
170	15	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 02:15:32.069446+08	t	\N
171	16	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:15:38.047021+08	t	\N
172	16	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:15:38.047023+08	t	\N
173	16	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:15:38.047024+08	t	\N
174	16	\N	0811Z1	智能立体交通工程	\N	0811	[]	[]	academic	2026-10-19 02:15:38.047024+08	t	\N
175	16	\N	0811Z2	低空域规划与安全管理	\N	0811	[]	[]	academic	2026-10-19 02:15:38.047025+08	t	\N
176	16	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:15:38.047025+08	t	\N
177	16	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:15:38.047025+08	t	\N
178	16	\N	083700	安全科学与工程	\N	0837	[]	[]	academic	2026-10-19 02:15:38.047026+08	t	\N
179	16	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:15:38.047026+08	t	\N
180	16	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:15:38.047027+08	t	\N
181	17	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:15:44.380138+08	t	\N
182	17	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:15:44.38014+08	t	\N
183	17	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 02:15:44.380141+08	t	\N
184	17	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:15:44.380141+08	t	\N
185	18	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:15:51.069064+08	t	\N
186	18	\N	083600	生物工程	\N	0836	[]	[]	academic	2026-10-19 02:15:51.069073+08	t	\N
187	18	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:15:51.069076+08	t	\N
188	18	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 02:15:51.069078+08	t	\N
189	19	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:15:57.795754+08	t	\N
190	19	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:15:57.795763+08	t	\N
191	19	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 02:15:57.795937+08	t	\N
192	19	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:15:57.795942+08	t	\N
193	19	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:15:57.795945+08	t	\N
194	19	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 02:15:57.795947+08	t	\N
195	19	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:15:57.795949+08	t	\N
196	19	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:15:57.795951+08	t	\N
197	19	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:15:57.795952+08	t	\N
198	19	\N	071011	生物物理学	\N	0710	[]	[]	academic	2026-10-19 02:15:57.795954+08	t	\N
199	22	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:16:16.922291+08	t	\N
200	22	\N	0812J1	物流科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:16:16.9223+08	t	\N
201	22	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:16:16.922303+08	t	\N
202	22	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:16:16.922306+08	t	\N
203	22	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:16:16.922308+08	t	\N
204	22	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:16:16.92231+08	t	\N
205	22	\N	086100	交通运输	\N	0861	[]	[]	professional	2026-10-19 02:16:16.922311+08	t	\N
206	22	\N	086102	道路交通运输	\N	0861	[]	[]	professional	2026-10-19 02:16:16.922313+08	t	\N
207	22	\N	087100	管理科学与工程	\N	0871	[]	[]	academic	2026-10-19 02:16:16.922315+08	t	\N
208	22	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 02:16:16.922317+08	t	\N
209	22	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:16:16.922319+08	t	\N
210	25	\N	081101	控制理论与控制工程	\N	0811	[]	[]	academic	2026-10-19 02:16:36.430039+08	t	\N
211	25	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 02:16:36.430048+08	t	\N
212	26	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 02:16:43.162041+08	t	\N
213	27	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:16:50.295658+08	t	\N
214	28	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:16:56.94793+08	t	\N
215	28	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:16:56.948124+08	t	\N
216	28	\N	081101	控制理论与控制工程	\N	0811	[]	[]	academic	2026-10-19 02:16:56.948144+08	t	\N
217	28	\N	081102	检测技术与自动化装置	\N	0811	[]	[]	academic	2026-10-19 02:16:56.948148+08	t	\N
218	29	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:17:03.436127+08	t	\N
219	29	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:17:03.436135+08	t	\N
220	29	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:17:03.436138+08	t	\N
221	30	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 02:17:10.306076+08	t	\N
222	31	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 02:17:17.222499+08	t	\N
223	31	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:17:17.222502+08	t	\N
224	32	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:17:22.991592+08	t	\N
225	32	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 02:17:22.991601+08	t	\N
226	32	\N	086100	交通运输	\N	0861	[]	[]	professional	2026-10-19 02:17:22.991604+08	t	\N
227	34	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:17:35.269043+08	t	\N
228	34	\N	080101	一般力学与力学基础	\N	0801	[]	[]	academic	2026-10-19 02:17:35.269052+08	t	\N
229	34	\N	080102	固体力学	\N	0801	[]	[]	academic	2026-10-19 02:17:35.269055+08	t	\N
230	34	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 02:17:35.269057+08	t	\N
231	34	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 02:17:35.26906+08	t	\N
232	34	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:17:35.269062+08	t	\N
233	34	\N	080201	机械制造及其自动化	\N	0802	[]	[]	academic	2026-10-19 02:17:35.269063+08	t	\N
234	34	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 02:17:35.269065+08	t	\N
235	34	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:17:35.269067+08	t	\N
236	34	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:17:35.269069+08	t	\N
237	34	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:17:35.269071+08	t	\N
238	34	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 02:17:35.269073+08	t	\N
239	34	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 02:17:35.269075+08	t	\N
240	34	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 02:17:35.269077+08	t	\N
241	34	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:17:35.269078+08	t	\N
242	34	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 02:17:35.26908+08	t	\N
243	34	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:17:35.269082+08	t	\N
244	34	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:17:35.269084+08	t	\N
245	34	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 02:17:35.269086+08	t	\N
246	34	\N	070203	原子与分子物理	\N	0702	[]	[]	academic	2026-10-19 02:17:35.269088+08	t	\N
247	36	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 02:17:50.201452+08	t	\N
248	36	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 02:17:50.201454+08	t	\N
249	36	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 02:17:50.201455+08	t	\N
250	36	\N	083001	环境科学	\N	0830	[]	[]	academic	2026-10-19 02:17:50.201455+08	t	\N
251	36	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 02:17:50.201456+08	t	\N
252	36	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:17:50.201456+08	t	\N
253	36	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 02:17:50.201457+08	t	\N
254	36	\N	086003	食品工程	\N	0860	[]	[]	professional	2026-10-19 02:17:50.201457+08	t	\N
255	36	\N	070600	大气科学	\N	0706	[]	[]	academic	2026-10-19 02:17:50.201458+08	t	\N
256	36	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:17:50.201458+08	t	\N
257	36	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:17:50.201458+08	t	\N
258	36	\N	071011	生物物理学	\N	0710	[]	[]	academic	2026-10-19 02:17:50.201459+08	t	\N
259	36	\N	0710Z1	生物信息学	\N	0710	[]	[]	academic	2026-10-19 02:17:50.201459+08	t	\N
260	36	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:17:50.20146+08	t	\N
261	36	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 02:17:50.20146+08	t	\N
262	37	\N	081800	地质资源与地质工程	\N	0818	[]	[]	academic	2026-10-19 02:17:56.781588+08	t	\N
263	37	\N	081902	矿物加工工程	\N	0819	[]	[]	academic	2026-10-19 02:17:56.78159+08	t	\N
264	37	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:17:56.781591+08	t	\N
265	37	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:17:56.781591+08	t	\N
266	37	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 02:17:56.781592+08	t	\N
267	37	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 02:17:56.781592+08	t	\N
268	39	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 02:18:10.75415+08	t	\N
269	39	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 02:18:10.754156+08	t	\N
270	39	\N	080902	电路与系统	\N	0809	[]	[]	academic	2026-10-19 02:18:10.754158+08	t	\N
271	39	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 02:18:10.75416+08	t	\N
272	39	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 02:18:10.754161+08	t	\N
273	39	\N	081103	系统工程	\N	0811	[]	[]	academic	2026-10-19 02:18:10.754163+08	t	\N
274	39	\N	081104	模式识别与智能系统	\N	0811	[]	[]	academic	2026-10-19 02:18:10.754166+08	t	\N
275	39	\N	081105	导航、制导与控制	\N	0811	[]	[]	academic	2026-10-19 02:18:10.754167+08	t	\N
276	39	\N	081201	计算机系统结构	\N	0812	[]	[]	academic	2026-10-19 02:18:10.754169+08	t	\N
277	39	\N	081202	计算机软件与理论	\N	0812	[]	[]	academic	2026-10-19 02:18:10.75417+08	t	\N
278	39	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:18:10.754171+08	t	\N
279	39	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:18:10.754173+08	t	\N
280	39	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:18:10.754174+08	t	\N
281	39	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:18:10.754175+08	t	\N
282	39	\N	0710Z1	生物信息学	\N	0710	[]	[]	academic	2026-10-19 02:18:10.754177+08	t	\N
283	39	\N	0710Z2	生物安全	\N	0710	[]	[]	academic	2026-10-19 02:18:10.754178+08	t	\N
284	39	\N	071101	系统理论	\N	0711	[]	[]	academic	2026-10-19 02:18:10.75418+08	t	\N
285	39	\N	071102	系统分析与集成	\N	0711	[]	[]	academic	2026-10-19 02:18:10.754181+08	t	\N
286	42	\N	082200	轻工技术与工程	\N	0822	[]	[]	academic	2026-10-19 02:18:29.775582+08	t	\N
287	42	\N	082900	林业工程	\N	0829	[]	[]	academic	2026-10-19 02:18:29.77559+08	t	\N
288	42	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:18:29.775594+08	t	\N
289	42	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:18:29.775596+08	t	\N
290	42	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:18:29.775598+08	t	\N
291	43	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 02:18:36.334714+08	t	\N
292	43	\N	081501	水文学及水资源	\N	0815	[]	[]	academic	2026-10-19 02:18:36.334719+08	t	\N
293	43	\N	081502	水力学及河流动力学	\N	0815	[]	[]	academic	2026-10-19 02:18:36.334721+08	t	\N
294	43	\N	081503	水工结构工程	\N	0815	[]	[]	academic	2026-10-19 02:18:36.334722+08	t	\N
295	43	\N	081504	水利水电工程	\N	0815	[]	[]	academic	2026-10-19 02:18:36.334724+08	t	\N
296	43	\N	0815Z1	水环境学	\N	0815	[]	[]	academic	2026-10-19 02:18:36.334725+08	t	\N
297	43	\N	0815Z2	水信息学	\N	0815	[]	[]	academic	2026-10-19 02:18:36.334726+08	t	\N
298	43	\N	0815Z3	水灾害与水安全	\N	0815	[]	[]	academic	2026-10-19 02:18:36.334727+08	t	\N
299	43	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:18:36.334729+08	t	\N
300	44	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:18:42.293317+08	t	\N
301	44	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 02:18:42.293326+08	t	\N
302	44	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 02:18:42.293329+08	t	\N
303	44	\N	085807	清洁能源技术	\N	0858	[]	[]	professional	2026-10-19 02:18:42.293331+08	t	\N
304	44	\N	085808	储能技术	\N	0858	[]	[]	professional	2026-10-19 02:18:42.293333+08	t	\N
305	45	\N	081304	建筑技术科学	\N	0813	[]	[]	academic	2026-10-19 02:18:49.502798+08	t	\N
306	45	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:18:49.5028+08	t	\N
307	45	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 02:18:49.5028+08	t	\N
308	46	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:18:54.833966+08	t	\N
309	47	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:19:04.973476+08	t	\N
310	48	\N	083001	环境科学	\N	0830	[]	[]	academic	2026-10-19 02:19:10.904927+08	t	\N
311	48	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 02:19:10.904929+08	t	\N
312	48	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 02:19:10.904929+08	t	\N
313	48	\N	070602	大气物理学与大气环境	\N	0706	[]	[]	academic	2026-10-19 02:19:10.90493+08	t	\N
314	48	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:19:10.90493+08	t	\N
315	48	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:19:10.904931+08	t	\N
316	49	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:19:17.789264+08	t	\N
317	49	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:19:17.789274+08	t	\N
318	49	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:19:17.789277+08	t	\N
319	53	\N	070601	气象学	\N	0706	[]	[]	academic	2026-10-19 02:19:44.779629+08	t	\N
320	53	\N	070701	物理海洋学	\N	0707	[]	[]	academic	2026-10-19 02:19:44.77964+08	t	\N
321	54	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:19:51.876785+08	t	\N
322	54	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:19:51.876787+08	t	\N
323	54	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:19:51.876788+08	t	\N
324	54	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:19:51.876788+08	t	\N
325	54	\N	082200	轻工技术与工程	\N	0822	[]	[]	academic	2026-10-19 02:19:51.876789+08	t	\N
326	54	\N	0822J1	监管科学	\N	0822	[]	[]	academic	2026-10-19 02:19:51.876789+08	t	\N
327	54	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:19:51.87679+08	t	\N
328	54	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:19:51.87679+08	t	\N
329	54	\N	0832J1	监管科学	\N	0832	[]	[]	academic	2026-10-19 02:19:51.876791+08	t	\N
330	54	\N	0832J2	食品经济学	\N	0832	[]	[]	academic	2026-10-19 02:19:51.876791+08	t	\N
331	54	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:19:51.876791+08	t	\N
332	54	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 02:19:51.876792+08	t	\N
333	54	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:19:51.876792+08	t	\N
334	54	\N	0714J1	数字商学	\N	0714	[]	[]	academic	2026-10-19 02:19:51.876793+08	t	\N
335	54	\N	0714J2	监管科学	\N	0714	[]	[]	academic	2026-10-19 02:19:51.876793+08	t	\N
336	54	\N	0714Z1	数据科学与人工智能	\N	0714	[]	[]	academic	2026-10-19 02:19:51.876794+08	t	\N
337	54	\N	077301	材料物理与化学	\N	0773	[]	[]	academic	2026-10-19 02:19:51.876794+08	t	\N
338	55	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:19:58.300992+08	t	\N
339	55	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:19:58.301002+08	t	\N
340	55	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:19:58.301006+08	t	\N
341	55	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:19:58.301008+08	t	\N
342	55	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:19:58.30101+08	t	\N
343	55	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 02:19:58.301012+08	t	\N
344	55	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 02:19:58.301014+08	t	\N
345	55	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 02:19:58.301016+08	t	\N
346	55	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 02:19:58.301018+08	t	\N
347	55	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 02:19:58.30102+08	t	\N
348	55	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:19:58.301022+08	t	\N
349	55	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:19:58.301023+08	t	\N
350	55	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:19:58.301025+08	t	\N
351	55	\N	070600	大气科学	\N	0706	[]	[]	academic	2026-10-19 02:19:58.301027+08	t	\N
352	55	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:19:58.301029+08	t	\N
353	55	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:19:58.30103+08	t	\N
354	55	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 02:19:58.301032+08	t	\N
355	56	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:20:04.799346+08	t	\N
356	56	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:20:04.799355+08	t	\N
357	56	\N	0810J4	互联网信息	\N	0810	[]	[]	academic	2026-10-19 02:20:04.799359+08	t	\N
358	56	\N	0810J5	信息传播学	\N	0810	[]	[]	academic	2026-10-19 02:20:04.799361+08	t	\N
359	56	\N	0810J8	新闻舆论学	\N	0810	[]	[]	academic	2026-10-19 02:20:04.799363+08	t	\N
360	56	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:20:04.799366+08	t	\N
361	56	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:20:04.799368+08	t	\N
362	56	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:20:04.79937+08	t	\N
363	56	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:20:04.799372+08	t	\N
364	56	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:20:04.799373+08	t	\N
365	56	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:20:04.799375+08	t	\N
366	57	\N	0838Z1	刑事科学技术	\N	0838	[]	[]	academic	2026-10-19 02:20:11.779231+08	t	\N
367	57	\N	0838Z2	安全防范工程	\N	0838	[]	[]	academic	2026-10-19 02:20:11.779241+08	t	\N
368	57	\N	0838Z3	交通管理工程	\N	0838	[]	[]	academic	2026-10-19 02:20:11.779244+08	t	\N
369	57	\N	0838Z4	网络空间安全执法技术	\N	0838	[]	[]	academic	2026-10-19 02:20:11.779246+08	t	\N
370	57	\N	0838Z5	数字证据科学与技术	\N	0838	[]	[]	academic	2026-10-19 02:20:11.779248+08	t	\N
371	57	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:20:11.77925+08	t	\N
372	57	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:20:11.779252+08	t	\N
373	61	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:20:40.860085+08	t	\N
374	61	\N	0801J8	力学技术科学与工程	\N	0801	[]	[]	academic	2026-10-19 02:20:40.860089+08	t	\N
375	61	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:20:40.860089+08	t	\N
376	61	\N	0802J4	储能科学与工程	\N	0802	[]	[]	academic	2026-10-19 02:20:40.860091+08	t	\N
377	61	\N	0802J7	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:20:40.860092+08	t	\N
378	61	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:20:40.860094+08	t	\N
379	61	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:20:40.860095+08	t	\N
380	61	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:20:40.860096+08	t	\N
381	61	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:20:40.860098+08	t	\N
382	61	\N	0814J3	能源建设工程	\N	0814	[]	[]	academic	2026-10-19 02:20:40.860099+08	t	\N
383	61	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:20:40.8601+08	t	\N
384	61	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:20:40.860102+08	t	\N
385	61	\N	070801	固体地球物理学	\N	0708	[]	[]	academic	2026-10-19 02:20:40.860103+08	t	\N
386	61	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 02:20:40.860104+08	t	\N
387	62	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:20:48.116405+08	t	\N
388	62	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:20:48.116408+08	t	\N
389	62	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:20:48.116408+08	t	\N
390	62	\N	0805J5	新能源科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:20:48.116409+08	t	\N
391	62	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:20:48.116409+08	t	\N
392	62	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:20:48.11641+08	t	\N
393	62	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:20:48.11641+08	t	\N
394	62	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:20:48.11641+08	t	\N
395	62	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:20:48.116411+08	t	\N
396	62	\N	081800	地质资源与地质工程	\N	0818	[]	[]	academic	2026-10-19 02:20:48.116411+08	t	\N
397	62	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:20:48.116412+08	t	\N
398	62	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:20:48.116412+08	t	\N
399	62	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:20:48.116412+08	t	\N
400	62	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 02:20:48.116413+08	t	\N
401	62	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 02:20:48.116413+08	t	\N
402	63	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:20:54.557712+08	t	\N
403	63	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:20:54.557714+08	t	\N
404	63	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:20:54.557715+08	t	\N
405	63	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:20:54.557715+08	t	\N
406	63	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:20:54.557716+08	t	\N
407	63	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:20:54.557716+08	t	\N
408	63	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 02:20:54.557717+08	t	\N
409	63	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 02:20:54.557717+08	t	\N
410	63	\N	081800	地质资源与地质工程	\N	0818	[]	[]	academic	2026-10-19 02:20:54.557718+08	t	\N
411	63	\N	082000	石油与天然气工程	\N	0820	[]	[]	academic	2026-10-19 02:20:54.557718+08	t	\N
412	63	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:20:54.557719+08	t	\N
413	63	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:20:54.557719+08	t	\N
414	63	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:20:54.557719+08	t	\N
415	63	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:20:54.55772+08	t	\N
416	63	\N	070600	大气科学	\N	0706	[]	[]	academic	2026-10-19 02:20:54.55772+08	t	\N
417	63	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:20:54.557721+08	t	\N
418	63	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 02:20:54.557721+08	t	\N
419	63	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 02:20:54.557722+08	t	\N
420	63	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:20:54.557722+08	t	\N
421	67	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:21:20.129985+08	t	\N
422	67	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 02:21:20.129988+08	t	\N
423	67	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 02:21:20.129989+08	t	\N
424	69	\N	082701	核能科学与工程	\N	0827	[]	[]	academic	2026-10-19 02:21:33.459395+08	t	\N
425	70	\N	081801	矿产普查与勘探	\N	0818	[]	[]	academic	2026-10-19 02:21:39.701828+08	t	\N
426	70	\N	081802	地球探测与信息技术	\N	0818	[]	[]	academic	2026-10-19 02:21:39.701833+08	t	\N
427	70	\N	081803	地质工程	\N	0818	[]	[]	academic	2026-10-19 02:21:39.701835+08	t	\N
428	70	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:21:39.701837+08	t	\N
429	70	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 02:21:39.701838+08	t	\N
430	71	\N	082702	核燃料循环与材料	\N	0827	[]	[]	academic	2026-10-19 02:21:45.469876+08	t	\N
431	72	\N	081402	结构工程	\N	0814	[]	[]	academic	2026-10-19 02:21:52.480675+08	t	\N
432	73	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 02:21:59.796838+08	t	\N
433	74	\N	082200	轻工技术与工程	\N	0822	[]	[]	academic	2026-10-19 02:22:06.143788+08	t	\N
434	75	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:22:12.62113+08	t	\N
435	75	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:22:12.621133+08	t	\N
436	75	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:22:12.621133+08	t	\N
437	75	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:22:12.621134+08	t	\N
438	75	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:22:12.621134+08	t	\N
439	75	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:22:12.621134+08	t	\N
440	75	\N	0811J1	低空技术与工程	\N	0811	[]	[]	academic	2026-10-19 02:22:12.621135+08	t	\N
441	75	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:22:12.621135+08	t	\N
442	75	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:22:12.621136+08	t	\N
443	75	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:22:12.621136+08	t	\N
444	75	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:22:12.621137+08	t	\N
445	75	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:22:12.621137+08	t	\N
446	76	\N	080901	物理电子学	\N	0809	[]	[]	academic	2026-10-19 02:22:18.850345+08	t	\N
447	76	\N	080903	微电子学与固体电子学	\N	0809	[]	[]	academic	2026-10-19 02:22:18.850347+08	t	\N
448	76	\N	080904	电磁场与微波技术	\N	0809	[]	[]	academic	2026-10-19 02:22:18.850348+08	t	\N
449	76	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 02:22:18.850349+08	t	\N
450	76	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 02:22:18.850349+08	t	\N
451	76	\N	081201	计算机系统结构	\N	0812	[]	[]	academic	2026-10-19 02:22:18.85035+08	t	\N
452	76	\N	081202	计算机软件与理论	\N	0812	[]	[]	academic	2026-10-19 02:22:18.85035+08	t	\N
453	76	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 02:22:18.85035+08	t	\N
454	76	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:22:18.850351+08	t	\N
455	76	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:22:18.850351+08	t	\N
456	76	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 02:22:18.850352+08	t	\N
457	77	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:22:26.050561+08	t	\N
458	77	\N	081202	计算机软件与理论	\N	0812	[]	[]	academic	2026-10-19 02:22:26.050567+08	t	\N
459	77	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 02:22:26.050568+08	t	\N
460	77	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 02:22:26.05057+08	t	\N
461	77	\N	082700	核科学与技术	\N	0827	[]	[]	academic	2026-10-19 02:22:26.050571+08	t	\N
462	77	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:22:26.050573+08	t	\N
463	77	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:22:26.050574+08	t	\N
464	77	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:22:26.050575+08	t	\N
465	77	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:22:26.050577+08	t	\N
466	77	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:22:26.050578+08	t	\N
467	77	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:22:26.050579+08	t	\N
468	77	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:22:26.050581+08	t	\N
469	77	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 02:22:26.050583+08	t	\N
470	77	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:22:26.050584+08	t	\N
471	77	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:22:26.050585+08	t	\N
472	77	\N	0702Z1	物理教育	\N	0702	[]	[]	academic	2026-10-19 02:22:26.050587+08	t	\N
473	77	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:22:26.050588+08	t	\N
474	77	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 02:22:26.05059+08	t	\N
475	77	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 02:22:26.050591+08	t	\N
476	77	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 02:22:26.050593+08	t	\N
477	78	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 02:22:32.810131+08	t	\N
478	78	\N	081202	计算机软件与理论	\N	0812	[]	[]	academic	2026-10-19 02:22:32.810141+08	t	\N
479	78	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 02:22:32.810145+08	t	\N
480	78	\N	0812Z2	人工智能	\N	0812	[]	[]	academic	2026-10-19 02:22:32.810147+08	t	\N
481	78	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:22:32.810149+08	t	\N
482	78	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:22:32.810151+08	t	\N
483	78	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:22:32.810153+08	t	\N
484	78	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:22:32.810154+08	t	\N
485	78	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 02:22:32.810156+08	t	\N
486	78	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 02:22:32.810158+08	t	\N
487	78	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:22:32.81016+08	t	\N
488	78	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:22:32.810161+08	t	\N
489	78	\N	070203	原子与分子物理	\N	0702	[]	[]	academic	2026-10-19 02:22:32.810163+08	t	\N
490	78	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:22:32.810166+08	t	\N
491	78	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:22:32.810168+08	t	\N
492	78	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:22:32.81017+08	t	\N
493	78	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 02:22:32.810171+08	t	\N
494	78	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 02:22:32.810173+08	t	\N
495	78	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 02:22:32.810175+08	t	\N
496	78	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:22:32.810177+08	t	\N
497	79	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 02:22:39.368279+08	t	\N
498	79	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 02:22:39.368289+08	t	\N
499	79	\N	083203	农产品加工及贮藏工程	\N	0832	[]	[]	academic	2026-10-19 02:22:39.368293+08	t	\N
500	79	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:22:39.368295+08	t	\N
501	80	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:22:44.964467+08	t	\N
502	80	\N	0802J6	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:22:44.96447+08	t	\N
503	80	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:22:44.964471+08	t	\N
504	80	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:22:44.964471+08	t	\N
505	80	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:22:44.964472+08	t	\N
506	80	\N	082900	林业工程	\N	0829	[]	[]	academic	2026-10-19 02:22:44.964472+08	t	\N
507	80	\N	0829J1	低空技术与工程	\N	0829	[]	[]	academic	2026-10-19 02:22:44.964472+08	t	\N
508	80	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:22:44.964473+08	t	\N
509	80	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:22:44.964473+08	t	\N
510	80	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:22:44.964474+08	t	\N
511	80	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:22:44.964474+08	t	\N
512	80	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:22:44.964474+08	t	\N
513	80	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:22:44.964475+08	t	\N
514	80	\N	071011	生物物理学	\N	0710	[]	[]	academic	2026-10-19 02:22:44.964475+08	t	\N
515	80	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:22:44.964476+08	t	\N
516	80	\N	0713J1	国家公园学	\N	0713	[]	[]	academic	2026-10-19 02:22:44.964477+08	t	\N
517	81	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:22:52.695048+08	t	\N
518	81	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:22:52.695051+08	t	\N
519	81	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:22:52.695051+08	t	\N
520	81	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 02:22:52.695052+08	t	\N
521	81	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:22:52.695052+08	t	\N
522	81	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:22:52.695053+08	t	\N
523	81	\N	071011	生物物理学	\N	0710	[]	[]	academic	2026-10-19 02:22:52.695053+08	t	\N
524	84	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:23:13.573646+08	t	\N
525	84	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:23:13.573656+08	t	\N
526	84	\N	0714Z1	经济统计	\N	0714	[]	[]	academic	2026-10-19 02:23:13.57366+08	t	\N
527	84	\N	0714Z2	数理统计	\N	0714	[]	[]	academic	2026-10-19 02:23:13.573662+08	t	\N
528	84	\N	0714Z3	金融统计与风险管理	\N	0714	[]	[]	academic	2026-10-19 02:23:13.573664+08	t	\N
529	84	\N	0714Z4	应用统计	\N	0714	[]	[]	academic	2026-10-19 02:23:13.573666+08	t	\N
530	85	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:23:20.792886+08	t	\N
531	85	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:23:20.792892+08	t	\N
532	85	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:23:20.792894+08	t	\N
533	85	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:23:20.792895+08	t	\N
534	85	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:23:20.792897+08	t	\N
535	85	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 02:23:20.792898+08	t	\N
536	85	\N	082502	航空宇航推进理论与工程	\N	0825	[]	[]	academic	2026-10-19 02:23:20.792899+08	t	\N
537	85	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:23:20.792901+08	t	\N
538	85	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:23:20.792902+08	t	\N
539	85	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:23:20.792903+08	t	\N
540	86	\N	080102	固体力学	\N	0801	[]	[]	academic	2026-10-19 02:23:26.985041+08	t	\N
541	86	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:23:26.98505+08	t	\N
542	86	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:23:26.985053+08	t	\N
543	87	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:23:33.802588+08	t	\N
544	87	\N	082503	航空宇航制造工程	\N	0825	[]	[]	academic	2026-10-19 02:23:33.802598+08	t	\N
545	89	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:23:47.638995+08	t	\N
546	89	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:23:47.639005+08	t	\N
547	89	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:23:47.639009+08	t	\N
548	89	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:23:47.639011+08	t	\N
549	89	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 02:23:47.639013+08	t	\N
550	89	\N	082600	兵器科学与技术	\N	0826	[]	[]	academic	2026-10-19 02:23:47.639015+08	t	\N
551	89	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:23:47.639017+08	t	\N
552	89	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:23:47.639019+08	t	\N
553	89	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:23:47.639021+08	t	\N
554	90	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 02:23:54.570895+08	t	\N
555	90	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 02:23:54.570905+08	t	\N
556	90	\N	081101	控制理论与控制工程	\N	0811	[]	[]	academic	2026-10-19 02:23:54.570908+08	t	\N
557	90	\N	081102	检测技术与自动化装置	\N	0811	[]	[]	academic	2026-10-19 02:23:54.57091+08	t	\N
558	90	\N	081103	系统工程	\N	0811	[]	[]	academic	2026-10-19 02:23:54.570912+08	t	\N
559	90	\N	081104	模式识别与智能系统	\N	0811	[]	[]	academic	2026-10-19 02:23:54.570914+08	t	\N
560	90	\N	081105	导航、制导与控制	\N	0811	[]	[]	academic	2026-10-19 02:23:54.570916+08	t	\N
561	90	\N	082501	飞行器设计	\N	0825	[]	[]	academic	2026-10-19 02:23:54.570918+08	t	\N
562	90	\N	082502	航空宇航推进理论与工程	\N	0825	[]	[]	academic	2026-10-19 02:23:54.57092+08	t	\N
563	90	\N	082503	航空宇航制造工程	\N	0825	[]	[]	academic	2026-10-19 02:23:54.570922+08	t	\N
564	91	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:24:01.18044+08	t	\N
565	91	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 02:24:01.180442+08	t	\N
566	92	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:24:06.701769+08	t	\N
567	92	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:24:06.701771+08	t	\N
568	92	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:24:06.701771+08	t	\N
569	92	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 02:24:06.701772+08	t	\N
570	92	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:24:06.701772+08	t	\N
571	92	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:24:06.701773+08	t	\N
572	92	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:24:06.701773+08	t	\N
573	92	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 02:24:06.701774+08	t	\N
574	93	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 02:24:12.949863+08	t	\N
575	93	\N	081801	矿产普查与勘探	\N	0818	[]	[]	academic	2026-10-19 02:24:12.949865+08	t	\N
576	93	\N	081802	地球探测与信息技术	\N	0818	[]	[]	academic	2026-10-19 02:24:12.949866+08	t	\N
577	93	\N	082001	油气井工程	\N	0820	[]	[]	academic	2026-10-19 02:24:12.949866+08	t	\N
578	93	\N	082002	油气田开发工程	\N	0820	[]	[]	academic	2026-10-19 02:24:12.949867+08	t	\N
579	93	\N	082003	油气储运工程	\N	0820	[]	[]	academic	2026-10-19 02:24:12.949867+08	t	\N
580	93	\N	0820Z1	油气信息工程	\N	0820	[]	[]	academic	2026-10-19 02:24:12.949868+08	t	\N
581	93	\N	0820Z2	油气田化学工程	\N	0820	[]	[]	academic	2026-10-19 02:24:12.949868+08	t	\N
582	93	\N	0820Z3	井下控制工程	\N	0820	[]	[]	academic	2026-10-19 02:24:12.949868+08	t	\N
583	93	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:24:12.949869+08	t	\N
584	94	\N	081701	化学工程	\N	0817	[]	[]	academic	2026-10-19 02:24:18.870962+08	t	\N
585	94	\N	081702	化学工艺	\N	0817	[]	[]	academic	2026-10-19 02:24:18.870971+08	t	\N
586	94	\N	081704	应用化学	\N	0817	[]	[]	academic	2026-10-19 02:24:18.870975+08	t	\N
587	94	\N	081705	工业催化	\N	0817	[]	[]	academic	2026-10-19 02:24:18.870977+08	t	\N
588	94	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:24:18.870979+08	t	\N
589	95	\N	070801	固体地球物理学	\N	0708	[]	[]	academic	2026-10-19 02:24:25.474377+08	t	\N
590	95	\N	070901	矿物学、岩石学、矿床学	\N	0709	[]	[]	academic	2026-10-19 02:24:25.47438+08	t	\N
591	95	\N	070902	地球化学	\N	0709	[]	[]	academic	2026-10-19 02:24:25.47438+08	t	\N
592	95	\N	070904	构造地质学	\N	0709	[]	[]	academic	2026-10-19 02:24:25.474381+08	t	\N
593	95	\N	070905	第四纪地质学	\N	0709	[]	[]	academic	2026-10-19 02:24:25.474381+08	t	\N
594	96	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:24:32.611576+08	t	\N
595	96	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:24:32.611579+08	t	\N
596	96	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:24:32.611579+08	t	\N
597	96	\N	0807J1	储能科学与工程	\N	0807	[]	[]	academic	2026-10-19 02:24:32.61158+08	t	\N
598	96	\N	0807J2	氢能科学与工程	\N	0807	[]	[]	academic	2026-10-19 02:24:32.61158+08	t	\N
599	96	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:24:32.61158+08	t	\N
600	96	\N	0808J1	可再生能源与清洁能源	\N	0808	[]	[]	academic	2026-10-19 02:24:32.611581+08	t	\N
601	96	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:24:32.611581+08	t	\N
602	96	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:24:32.611582+08	t	\N
603	96	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:24:32.611582+08	t	\N
604	96	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:24:32.611582+08	t	\N
605	96	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:24:32.611583+08	t	\N
606	97	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:24:39.075482+08	t	\N
607	97	\N	0802Z1	低空智能运载工程	\N	0802	[]	[]	academic	2026-10-19 02:24:39.075485+08	t	\N
608	97	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:24:39.075485+08	t	\N
609	97	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:24:39.075486+08	t	\N
610	97	\N	081304	建筑技术科学	\N	0813	[]	[]	academic	2026-10-19 02:24:39.075486+08	t	\N
611	97	\N	0813J1	建筑遗产保护	\N	0813	[]	[]	academic	2026-10-19 02:24:39.075486+08	t	\N
612	97	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 02:24:39.075487+08	t	\N
613	97	\N	081402	结构工程	\N	0814	[]	[]	academic	2026-10-19 02:24:39.075487+08	t	\N
614	97	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 02:24:39.075488+08	t	\N
615	97	\N	081404	供热、供燃气、通风及空调工程	\N	0814	[]	[]	academic	2026-10-19 02:24:39.075488+08	t	\N
616	97	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:24:39.075489+08	t	\N
617	98	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:24:45.384588+08	t	\N
618	98	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:24:45.384591+08	t	\N
619	99	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:24:51.813553+08	t	\N
620	99	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 02:24:51.813562+08	t	\N
621	100	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:24:58.583891+08	t	\N
622	100	\N	0803Z1	光电子器件及集成技术	\N	0803	[]	[]	academic	2026-10-19 02:24:58.583899+08	t	\N
623	100	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:24:58.583903+08	t	\N
624	100	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:24:58.583905+08	t	\N
625	100	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:24:58.583908+08	t	\N
626	100	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:24:58.58391+08	t	\N
627	100	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:24:58.583911+08	t	\N
628	100	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:24:58.583913+08	t	\N
629	100	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:24:58.583915+08	t	\N
630	100	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 02:24:58.583917+08	t	\N
631	100	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:24:58.583919+08	t	\N
632	100	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:24:58.58392+08	t	\N
633	100	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:24:58.583922+08	t	\N
634	100	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:24:58.583924+08	t	\N
635	102	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:25:14.041834+08	t	\N
636	102	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:25:14.041837+08	t	\N
637	103	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:25:20.981942+08	t	\N
638	103	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 02:25:20.981944+08	t	\N
639	104	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 02:25:27.414475+08	t	\N
640	104	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:25:27.414478+08	t	\N
641	104	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:25:27.414478+08	t	\N
642	104	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:25:27.414479+08	t	\N
643	104	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 02:25:27.414479+08	t	\N
644	104	\N	081406	桥梁与隧道工程	\N	0814	[]	[]	academic	2026-10-19 02:25:27.414479+08	t	\N
645	104	\N	082301	道路与铁道工程	\N	0823	[]	[]	academic	2026-10-19 02:25:27.41448+08	t	\N
646	104	\N	082302	交通信息工程及控制	\N	0823	[]	[]	academic	2026-10-19 02:25:27.41448+08	t	\N
647	104	\N	082303	交通运输规划与管理	\N	0823	[]	[]	academic	2026-10-19 02:25:27.414481+08	t	\N
648	104	\N	082304	载运工具运用工程	\N	0823	[]	[]	academic	2026-10-19 02:25:27.414481+08	t	\N
649	105	\N	080102	固体力学	\N	0801	[]	[]	academic	2026-10-19 02:25:33.750718+08	t	\N
650	105	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 02:25:33.750727+08	t	\N
651	105	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 02:25:33.750731+08	t	\N
652	105	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:25:33.750733+08	t	\N
653	105	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:25:33.750735+08	t	\N
654	105	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:25:33.750738+08	t	\N
655	105	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:25:33.75074+08	t	\N
656	105	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:25:33.750742+08	t	\N
657	105	\N	082600	兵器科学与技术	\N	0826	[]	[]	academic	2026-10-19 02:25:33.750744+08	t	\N
658	105	\N	082701	核能科学与工程	\N	0827	[]	[]	academic	2026-10-19 02:25:33.750745+08	t	\N
659	105	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 02:25:33.750747+08	t	\N
660	105	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 02:25:33.750749+08	t	\N
661	105	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:25:33.750751+08	t	\N
662	105	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:25:33.750753+08	t	\N
663	105	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 02:25:33.750756+08	t	\N
664	105	\N	070203	原子与分子物理	\N	0702	[]	[]	academic	2026-10-19 02:25:33.750758+08	t	\N
665	105	\N	070204	等离子体物理	\N	0702	[]	[]	academic	2026-10-19 02:25:33.75076+08	t	\N
666	105	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:25:33.750761+08	t	\N
667	105	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:25:33.750763+08	t	\N
668	105	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 02:25:33.750765+08	t	\N
669	106	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 02:25:40.558502+08	t	\N
670	107	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:25:47.820078+08	t	\N
671	107	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:25:47.820084+08	t	\N
672	107	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:25:47.820087+08	t	\N
673	107	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:25:47.820088+08	t	\N
674	107	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:25:47.820089+08	t	\N
675	107	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:25:47.820091+08	t	\N
676	107	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:25:47.820092+08	t	\N
677	107	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:25:47.820094+08	t	\N
678	107	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:25:47.820095+08	t	\N
679	107	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:25:47.820096+08	t	\N
680	107	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:25:47.820097+08	t	\N
681	107	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:25:47.820099+08	t	\N
682	107	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:25:47.8201+08	t	\N
683	107	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:25:47.820102+08	t	\N
684	107	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:25:47.820104+08	t	\N
685	107	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:25:47.820105+08	t	\N
686	108	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:25:54.161067+08	t	\N
687	108	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:25:54.161069+08	t	\N
688	108	\N	0802Z1	工业设计	\N	0802	[]	[]	academic	2026-10-19 02:25:54.161069+08	t	\N
689	108	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:25:54.16107+08	t	\N
690	108	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:25:54.16107+08	t	\N
691	108	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 02:25:54.161071+08	t	\N
692	108	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 02:25:54.161071+08	t	\N
693	108	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 02:25:54.161072+08	t	\N
694	108	\N	0805Z1	高分子材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:25:54.161072+08	t	\N
695	108	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:25:54.161072+08	t	\N
696	108	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:25:54.161073+08	t	\N
697	108	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:25:54.161073+08	t	\N
698	108	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:25:54.161074+08	t	\N
699	108	\N	0703Z1	分子光电科学	\N	0703	[]	[]	academic	2026-10-19 02:25:54.161074+08	t	\N
700	108	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:25:54.161074+08	t	\N
701	108	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:25:54.161075+08	t	\N
702	108	\N	0707Z1	海洋技术	\N	0707	[]	[]	academic	2026-10-19 02:25:54.161075+08	t	\N
703	108	\N	0707Z2	海洋经济管理	\N	0707	[]	[]	academic	2026-10-19 02:25:54.161076+08	t	\N
704	108	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:25:54.161076+08	t	\N
705	108	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:25:54.161076+08	t	\N
706	109	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:26:00.979343+08	t	\N
707	109	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:26:00.979346+08	t	\N
708	109	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:26:00.979346+08	t	\N
709	109	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:26:00.979347+08	t	\N
710	109	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:26:00.979347+08	t	\N
711	109	\N	082200	轻工技术与工程	\N	0822	[]	[]	academic	2026-10-19 02:26:00.979348+08	t	\N
712	109	\N	082203	发酵工程	\N	0822	[]	[]	academic	2026-10-19 02:26:00.979348+08	t	\N
713	109	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:26:00.979349+08	t	\N
714	109	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:26:00.979349+08	t	\N
715	109	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:26:00.979349+08	t	\N
716	109	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:26:00.97935+08	t	\N
717	109	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:26:00.97935+08	t	\N
718	109	\N	078000	药学	\N	0780	[]	[]	academic	2026-10-19 02:26:00.979351+08	t	\N
719	110	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:26:07.560916+08	t	\N
720	110	\N	0802J1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:26:07.560925+08	t	\N
721	110	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:26:07.560928+08	t	\N
722	110	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:26:07.560931+08	t	\N
723	110	\N	0805J1	先进分离膜材料	\N	0805	[]	[]	academic	2026-10-19 02:26:07.560933+08	t	\N
724	110	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:26:07.560935+08	t	\N
725	110	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:26:07.560937+08	t	\N
726	110	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:26:07.560938+08	t	\N
727	110	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:26:07.56094+08	t	\N
728	110	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:26:07.560942+08	t	\N
729	110	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:26:07.560944+08	t	\N
730	110	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:26:07.560946+08	t	\N
731	110	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:26:07.560947+08	t	\N
732	111	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:26:13.403092+08	t	\N
733	111	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:26:13.403094+08	t	\N
734	111	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:26:13.403095+08	t	\N
735	111	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:26:13.403095+08	t	\N
736	111	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:26:13.403096+08	t	\N
737	111	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 02:26:13.403096+08	t	\N
738	111	\N	0823Z1	低空安全技术与工程	\N	0823	[]	[]	academic	2026-10-19 02:26:13.403097+08	t	\N
739	111	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 02:26:13.403097+08	t	\N
740	111	\N	083700	安全科学与工程	\N	0837	[]	[]	academic	2026-10-19 02:26:13.403097+08	t	\N
741	111	\N	0837J1	航空器适航审定工程	\N	0837	[]	[]	academic	2026-10-19 02:26:13.403098+08	t	\N
742	111	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:26:13.403098+08	t	\N
743	111	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:26:13.403099+08	t	\N
744	111	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 02:26:13.403099+08	t	\N
745	112	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:26:20.194478+08	t	\N
746	112	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:26:20.194482+08	t	\N
747	112	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:26:20.194483+08	t	\N
748	112	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:26:20.194484+08	t	\N
749	112	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:26:20.194484+08	t	\N
750	112	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:26:20.194485+08	t	\N
751	112	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:26:20.194486+08	t	\N
752	112	\N	0812J1	低空技术与工程	\N	0812	[]	[]	academic	2026-10-19 02:26:20.194486+08	t	\N
753	112	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:26:20.194487+08	t	\N
754	112	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:26:20.194487+08	t	\N
755	112	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:26:20.194488+08	t	\N
756	112	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:26:20.194488+08	t	\N
757	112	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:26:20.194489+08	t	\N
758	113	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 02:26:26.882967+08	t	\N
759	113	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:26:26.882969+08	t	\N
760	113	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:26:26.882969+08	t	\N
761	113	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:26:26.88297+08	t	\N
762	113	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:26:26.88297+08	t	\N
763	113	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:26:26.882971+08	t	\N
764	113	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:26:26.882971+08	t	\N
765	113	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 02:26:26.882972+08	t	\N
766	113	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:26:26.882972+08	t	\N
767	114	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:26:33.392406+08	t	\N
768	114	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:26:33.392415+08	t	\N
769	114	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:26:33.392418+08	t	\N
770	115	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:26:39.712768+08	t	\N
771	116	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:26:45.763833+08	t	\N
772	116	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:26:45.763836+08	t	\N
773	116	\N	0810Z1	智能科学与技术	\N	0810	[]	[]	academic	2026-10-19 02:26:45.763837+08	t	\N
774	116	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:26:45.763837+08	t	\N
775	116	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 02:26:45.763838+08	t	\N
776	116	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:26:45.763838+08	t	\N
777	116	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:26:45.763839+08	t	\N
778	116	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:26:45.763839+08	t	\N
779	116	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 02:26:45.763839+08	t	\N
780	116	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 02:26:45.76384+08	t	\N
781	116	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:26:45.76384+08	t	\N
782	116	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:26:45.763841+08	t	\N
783	116	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:26:45.763841+08	t	\N
784	116	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 02:26:45.763842+08	t	\N
785	116	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:26:45.763842+08	t	\N
786	116	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:26:45.763842+08	t	\N
787	116	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 02:26:45.763843+08	t	\N
788	116	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:26:45.763843+08	t	\N
789	116	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 02:26:45.763844+08	t	\N
790	117	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:26:52.131236+08	t	\N
791	117	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:26:52.131238+08	t	\N
792	117	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:26:52.131239+08	t	\N
793	117	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:26:52.131239+08	t	\N
794	117	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 02:26:52.13124+08	t	\N
795	117	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:26:52.13124+08	t	\N
796	117	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:26:52.131241+08	t	\N
797	117	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:26:52.131241+08	t	\N
798	117	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:26:52.131241+08	t	\N
799	117	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 02:26:52.131242+08	t	\N
800	117	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:26:52.131242+08	t	\N
801	117	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 02:26:52.131243+08	t	\N
802	124	\N	081105	导航、制导与控制	\N	0811	[]	[]	academic	2026-10-19 02:27:36.840965+08	t	\N
803	125	\N	082702	核燃料循环与材料	\N	0827	[]	[]	academic	2026-10-19 02:27:43.356723+08	t	\N
804	126	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 02:27:49.296095+08	t	\N
805	126	\N	081105	导航、制导与控制	\N	0811	[]	[]	academic	2026-10-19 02:27:49.296097+08	t	\N
806	127	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:27:56.776547+08	t	\N
807	128	\N	081505	港口、海岸及近海工程	\N	0815	[]	[]	academic	2026-10-19 02:28:03.260423+08	t	\N
808	128	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:28:03.260425+08	t	\N
809	130	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:28:15.953499+08	t	\N
810	131	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:28:22.882163+08	t	\N
811	131	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:28:22.882173+08	t	\N
812	131	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:28:22.882176+08	t	\N
813	131	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:28:22.882178+08	t	\N
814	131	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:28:22.882181+08	t	\N
815	131	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:28:22.882183+08	t	\N
816	131	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:28:22.882184+08	t	\N
817	131	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:28:22.882186+08	t	\N
818	131	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:28:22.882188+08	t	\N
819	131	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:28:22.88219+08	t	\N
820	131	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:28:22.882192+08	t	\N
821	131	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:28:22.882194+08	t	\N
822	131	\N	070204	等离子体物理	\N	0702	[]	[]	academic	2026-10-19 02:28:22.882196+08	t	\N
823	131	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:28:22.882198+08	t	\N
824	131	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:28:22.8822+08	t	\N
825	131	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 02:28:22.882202+08	t	\N
826	131	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 02:28:22.882204+08	t	\N
827	131	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 02:28:22.882206+08	t	\N
828	131	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 02:28:22.882208+08	t	\N
829	131	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 02:28:22.88221+08	t	\N
830	132	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:28:29.258274+08	t	\N
831	132	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:28:29.258277+08	t	\N
832	132	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:28:29.258278+08	t	\N
833	132	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:28:29.258278+08	t	\N
834	132	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:28:29.258279+08	t	\N
835	132	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:28:29.258279+08	t	\N
836	132	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:28:29.258279+08	t	\N
837	132	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 02:28:29.25828+08	t	\N
838	132	\N	081404	供热、供燃气、通风及空调工程	\N	0814	[]	[]	academic	2026-10-19 02:28:29.25828+08	t	\N
839	132	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 02:28:29.258281+08	t	\N
840	133	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:28:36.494968+08	t	\N
841	133	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:28:36.494977+08	t	\N
842	133	\N	081800	地质资源与地质工程	\N	0818	[]	[]	academic	2026-10-19 02:28:36.49498+08	t	\N
843	133	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:28:36.494983+08	t	\N
844	133	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:28:36.494985+08	t	\N
845	133	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:28:36.494987+08	t	\N
846	133	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:28:36.494989+08	t	\N
847	133	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:28:36.494991+08	t	\N
848	133	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 02:28:36.494993+08	t	\N
849	133	\N	085703	地质工程	\N	0857	[]	[]	professional	2026-10-19 02:28:36.494995+08	t	\N
850	133	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:28:36.494997+08	t	\N
851	133	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 02:28:36.494999+08	t	\N
852	134	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:28:43.848445+08	t	\N
853	134	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:28:43.848459+08	t	\N
854	134	\N	0807J1	储能科学与工程	\N	0807	[]	[]	academic	2026-10-19 02:28:43.848461+08	t	\N
855	134	\N	0807J2	氢能科学与工程	\N	0807	[]	[]	academic	2026-10-19 02:28:43.848463+08	t	\N
856	134	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:28:43.848464+08	t	\N
857	134	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:28:43.848466+08	t	\N
858	134	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:28:43.848467+08	t	\N
859	134	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:28:43.848468+08	t	\N
860	134	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:28:43.84847+08	t	\N
861	134	\N	081404	供热、供燃气、通风及空调工程	\N	0814	[]	[]	academic	2026-10-19 02:28:43.848471+08	t	\N
862	134	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:28:43.848472+08	t	\N
863	134	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:28:43.848474+08	t	\N
864	135	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:28:51.015272+08	t	\N
865	135	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:28:51.015275+08	t	\N
866	135	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:28:51.015275+08	t	\N
867	135	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:28:51.015276+08	t	\N
868	135	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:28:51.015276+08	t	\N
869	135	\N	080706	化工过程机械	\N	0807	[]	[]	academic	2026-10-19 02:28:51.015277+08	t	\N
870	135	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:28:51.015277+08	t	\N
871	135	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:28:51.015278+08	t	\N
872	135	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:28:51.015278+08	t	\N
873	135	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:28:51.015278+08	t	\N
874	135	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:28:51.015279+08	t	\N
875	135	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:28:51.015279+08	t	\N
876	135	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:28:51.01528+08	t	\N
877	135	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:28:51.01528+08	t	\N
878	136	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:28:56.703262+08	t	\N
879	136	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:28:56.703264+08	t	\N
880	136	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:28:56.703265+08	t	\N
881	136	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 02:28:56.703265+08	t	\N
882	136	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:28:56.703266+08	t	\N
883	136	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:28:56.703266+08	t	\N
884	136	\N	0810J8	低空技术与工程	\N	0810	[]	[]	academic	2026-10-19 02:28:56.703267+08	t	\N
885	136	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:28:56.703267+08	t	\N
886	136	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:28:56.703268+08	t	\N
887	136	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:28:56.703268+08	t	\N
888	136	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:28:56.703268+08	t	\N
889	136	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:28:56.703269+08	t	\N
890	136	\N	0703Z1	碳中和化学	\N	0703	[]	[]	academic	2026-10-19 02:28:56.703269+08	t	\N
891	136	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:28:56.70327+08	t	\N
892	137	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:29:02.671011+08	t	\N
893	137	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:29:02.671013+08	t	\N
894	137	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 02:29:02.671014+08	t	\N
895	137	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:29:02.671014+08	t	\N
896	137	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:29:02.671015+08	t	\N
897	137	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:29:02.671015+08	t	\N
898	137	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:29:02.671016+08	t	\N
899	137	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:29:02.671016+08	t	\N
900	137	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:29:02.671017+08	t	\N
901	137	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:29:02.671017+08	t	\N
902	137	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:29:02.671017+08	t	\N
903	137	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:29:02.671018+08	t	\N
904	137	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:29:02.671018+08	t	\N
905	137	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:29:02.671019+08	t	\N
906	138	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:29:09.999803+08	t	\N
907	138	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:29:09.999813+08	t	\N
908	138	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 02:29:09.999817+08	t	\N
909	138	\N	081404	供热、供燃气、通风及空调工程	\N	0814	[]	[]	academic	2026-10-19 02:29:09.999819+08	t	\N
910	138	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:29:09.999821+08	t	\N
911	138	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:29:09.999823+08	t	\N
912	138	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:29:09.999825+08	t	\N
913	138	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:29:09.999827+08	t	\N
914	138	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:29:09.999829+08	t	\N
915	138	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 02:29:09.999831+08	t	\N
916	139	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:29:17.183595+08	t	\N
917	139	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:29:17.183669+08	t	\N
918	139	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:29:17.187881+08	t	\N
919	139	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 02:29:17.187885+08	t	\N
920	139	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 02:29:17.187888+08	t	\N
921	139	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 02:29:17.187891+08	t	\N
922	139	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 02:29:17.187893+08	t	\N
923	139	\N	0828Z1	农业信息化技术	\N	0828	[]	[]	academic	2026-10-19 02:29:17.187895+08	t	\N
924	139	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:29:17.187897+08	t	\N
925	139	\N	0832J1	营养与健康	\N	0832	[]	[]	academic	2026-10-19 02:29:17.187899+08	t	\N
926	139	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:29:17.187901+08	t	\N
927	139	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:29:17.187959+08	t	\N
928	139	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:29:17.187961+08	t	\N
929	139	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:29:17.187964+08	t	\N
930	139	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:29:17.187966+08	t	\N
931	139	\N	0710J1	生物信息学	\N	0710	[]	[]	academic	2026-10-19 02:29:17.187968+08	t	\N
932	139	\N	0710J2	化学生物学	\N	0710	[]	[]	academic	2026-10-19 02:29:17.187969+08	t	\N
933	139	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:29:17.187971+08	t	\N
934	140	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:29:24.527601+08	t	\N
935	140	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 02:29:24.52761+08	t	\N
936	140	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:29:24.527614+08	t	\N
937	140	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:29:24.527616+08	t	\N
938	140	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:29:24.527618+08	t	\N
939	140	\N	0710Z2	医药信息学	\N	0710	[]	[]	academic	2026-10-19 02:29:24.527621+08	t	\N
940	141	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:29:30.9108+08	t	\N
941	141	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:29:30.910802+08	t	\N
942	141	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:29:30.910802+08	t	\N
943	141	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:29:30.910803+08	t	\N
944	141	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:29:30.910803+08	t	\N
945	141	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:29:30.910804+08	t	\N
946	141	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 02:29:30.910804+08	t	\N
947	141	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 02:29:30.910805+08	t	\N
948	141	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 02:29:30.910805+08	t	\N
949	141	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:29:30.910806+08	t	\N
950	141	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:29:30.910806+08	t	\N
951	141	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:29:30.910806+08	t	\N
952	141	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:29:30.910807+08	t	\N
953	141	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 02:29:30.910807+08	t	\N
954	141	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 02:29:30.910808+08	t	\N
955	141	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 02:29:30.910808+08	t	\N
956	141	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 02:29:30.910809+08	t	\N
957	141	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:29:30.910809+08	t	\N
958	141	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 02:29:30.910809+08	t	\N
959	141	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:29:30.91081+08	t	\N
960	142	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:29:37.004432+08	t	\N
961	142	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:29:37.004441+08	t	\N
962	143	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:29:43.280244+08	t	\N
963	143	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:29:43.280253+08	t	\N
964	145	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:29:57.280155+08	t	\N
965	145	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 02:29:57.280157+08	t	\N
966	145	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 02:29:57.280157+08	t	\N
967	145	\N	070701	物理海洋学	\N	0707	[]	[]	academic	2026-10-19 02:29:57.280178+08	t	\N
968	145	\N	070703	海洋生物学	\N	0707	[]	[]	academic	2026-10-19 02:29:57.280179+08	t	\N
969	145	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:29:57.280179+08	t	\N
970	145	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:29:57.280179+08	t	\N
971	145	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:29:57.28018+08	t	\N
972	147	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 02:30:10.980769+08	t	\N
973	147	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:30:10.980771+08	t	\N
974	147	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:30:10.980772+08	t	\N
975	147	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:30:10.980773+08	t	\N
976	147	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:30:10.980773+08	t	\N
977	147	\N	085504	航天工程	\N	0855	[]	[]	professional	2026-10-19 02:30:10.980774+08	t	\N
978	147	\N	085507	工业设计工程	\N	0855	[]	[]	professional	2026-10-19 02:30:10.980774+08	t	\N
979	147	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 02:30:10.980774+08	t	\N
980	147	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 02:30:10.980775+08	t	\N
981	147	\N	085901	土木工程	\N	0859	[]	[]	professional	2026-10-19 02:30:10.980775+08	t	\N
982	147	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:30:10.980776+08	t	\N
983	147	\N	078700	遥感科学与技术	\N	0787	[]	[]	academic	2026-10-19 02:30:10.980776+08	t	\N
984	150	\N	081704	应用化学	\N	0817	[]	[]	academic	2026-10-19 02:30:29.132482+08	t	\N
985	150	\N	082401	船舶与海洋结构物设计制造	\N	0824	[]	[]	academic	2026-10-19 02:30:29.132484+08	t	\N
986	151	\N	083700	安全科学与工程	\N	0837	[]	[]	academic	2026-10-19 02:30:35.017685+08	t	\N
987	151	\N	083800	公安技术	\N	0838	[]	[]	academic	2026-10-19 02:30:35.017687+08	t	\N
988	151	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:30:35.017687+08	t	\N
989	151	\N	085702	安全工程	\N	0857	[]	[]	professional	2026-10-19 02:30:35.017688+08	t	\N
990	152	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 02:30:41.515539+08	t	\N
991	152	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 02:30:41.515641+08	t	\N
992	153	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:30:47.86364+08	t	\N
993	153	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:30:47.863649+08	t	\N
994	153	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:30:47.863652+08	t	\N
995	153	\N	0805J1	智能材料	\N	0805	[]	[]	academic	2026-10-19 02:30:47.863654+08	t	\N
996	153	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:30:47.863656+08	t	\N
997	153	\N	081102	检测技术与自动化装置	\N	0811	[]	[]	academic	2026-10-19 02:30:47.863658+08	t	\N
998	153	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:30:47.86366+08	t	\N
999	153	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:30:47.863662+08	t	\N
1000	153	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 02:30:47.863663+08	t	\N
1001	153	\N	081402	结构工程	\N	0814	[]	[]	academic	2026-10-19 02:30:47.863665+08	t	\N
1002	153	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:30:47.863667+08	t	\N
1003	153	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:30:47.863669+08	t	\N
1004	154	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:30:54.871273+08	t	\N
1005	154	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:30:54.871275+08	t	\N
1006	154	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:30:54.871276+08	t	\N
1007	154	\N	0811Z1	低空智能控制工程	\N	0811	[]	[]	academic	2026-10-19 02:30:54.871277+08	t	\N
1008	154	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:30:54.871277+08	t	\N
1009	154	\N	083001	环境科学	\N	0830	[]	[]	academic	2026-10-19 02:30:54.871278+08	t	\N
1010	154	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 02:30:54.871278+08	t	\N
1011	154	\N	0830J1	资源循环科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:30:54.871279+08	t	\N
1012	154	\N	0830Z1	环境生物医学	\N	0830	[]	[]	academic	2026-10-19 02:30:54.871279+08	t	\N
1013	154	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:30:54.87128+08	t	\N
1014	154	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:30:54.87128+08	t	\N
1015	154	\N	0701J7	生物数学与数据智能	\N	0701	[]	[]	academic	2026-10-19 02:30:54.871281+08	t	\N
1016	154	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:30:54.871281+08	t	\N
1017	154	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 02:30:54.871282+08	t	\N
1018	154	\N	070203	原子与分子物理	\N	0702	[]	[]	academic	2026-10-19 02:30:54.871282+08	t	\N
1019	154	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:30:54.871282+08	t	\N
1020	154	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:30:54.871283+08	t	\N
1021	154	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 02:30:54.871283+08	t	\N
1022	154	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 02:30:54.871284+08	t	\N
1023	154	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 02:30:54.871284+08	t	\N
1024	155	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:31:01.059231+08	t	\N
1025	155	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:31:01.059234+08	t	\N
1026	155	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:31:01.059234+08	t	\N
1027	155	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:31:01.059235+08	t	\N
1028	155	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 02:31:01.059235+08	t	\N
1029	155	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:31:01.059236+08	t	\N
1030	155	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:31:01.059236+08	t	\N
1031	155	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:31:01.059236+08	t	\N
1032	155	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:31:01.059237+08	t	\N
1033	155	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:31:01.059237+08	t	\N
1034	155	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:31:01.059238+08	t	\N
1035	155	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:31:01.059238+08	t	\N
1036	156	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:31:07.380986+08	t	\N
1037	156	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:31:07.380999+08	t	\N
1038	156	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:31:07.381002+08	t	\N
1039	156	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:31:07.381005+08	t	\N
1040	156	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:31:07.381007+08	t	\N
1041	156	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:31:07.381009+08	t	\N
1042	156	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:31:07.381011+08	t	\N
1043	156	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:31:07.381012+08	t	\N
1044	156	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:31:07.381014+08	t	\N
1045	156	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:31:07.381016+08	t	\N
1046	156	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:31:07.381018+08	t	\N
1047	156	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:31:07.38102+08	t	\N
1048	156	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:31:07.381021+08	t	\N
1049	156	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:31:07.381023+08	t	\N
1050	157	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:31:14.077789+08	t	\N
1051	157	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:31:14.077799+08	t	\N
1052	157	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:31:14.077802+08	t	\N
1053	157	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:31:14.077805+08	t	\N
1054	157	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:31:14.077807+08	t	\N
1055	157	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 02:31:14.077809+08	t	\N
1056	157	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:31:14.077811+08	t	\N
1057	157	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:31:14.077814+08	t	\N
1058	157	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:31:14.077817+08	t	\N
1059	157	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:31:14.077818+08	t	\N
1060	157	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:31:14.077821+08	t	\N
1061	157	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:31:14.077823+08	t	\N
1062	157	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:31:14.077825+08	t	\N
1063	158	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:31:20.878896+08	t	\N
1064	158	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 02:31:20.894454+08	t	\N
1065	158	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 02:31:20.894458+08	t	\N
1066	158	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 02:31:20.89446+08	t	\N
1067	158	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 02:31:20.894461+08	t	\N
1068	158	\N	0828Z1	智慧农业系统工程	\N	0828	[]	[]	academic	2026-10-19 02:31:20.894462+08	t	\N
1069	158	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:31:20.894463+08	t	\N
1070	158	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:31:20.894464+08	t	\N
1071	158	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:31:20.894465+08	t	\N
1072	158	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:31:20.894497+08	t	\N
1073	158	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:31:20.894525+08	t	\N
1074	159	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:31:26.767371+08	t	\N
1075	159	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:31:26.767373+08	t	\N
1076	159	\N	077800	基础医学	\N	0778	[]	[]	academic	2026-10-19 02:31:26.767374+08	t	\N
1077	161	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:31:39.465505+08	t	\N
1078	161	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:31:39.465511+08	t	\N
1079	161	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:31:39.465514+08	t	\N
1080	161	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:31:39.465515+08	t	\N
1081	161	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:31:39.465517+08	t	\N
1082	161	\N	086003	食品工程	\N	0860	[]	[]	professional	2026-10-19 02:31:39.465518+08	t	\N
1083	161	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:31:39.46552+08	t	\N
1084	161	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:31:39.465521+08	t	\N
1085	161	\N	070203	原子与分子物理	\N	0702	[]	[]	academic	2026-10-19 02:31:39.465523+08	t	\N
1086	161	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:31:39.465525+08	t	\N
1087	161	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:31:39.465527+08	t	\N
1088	161	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:31:39.465528+08	t	\N
1089	161	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:31:39.465529+08	t	\N
1090	161	\N	0713J1	生态毒理与修复生态学	\N	0713	[]	[]	academic	2026-10-19 02:31:39.465531+08	t	\N
1091	161	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 02:31:39.465532+08	t	\N
1092	161	\N	077300	材料科学与工程	\N	0773	[]	[]	academic	2026-10-19 02:31:39.465533+08	t	\N
1093	162	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:31:46.472609+08	t	\N
1094	162	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:31:46.472615+08	t	\N
1095	162	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:31:46.472617+08	t	\N
1096	162	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:31:46.472618+08	t	\N
1097	162	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 02:31:46.47262+08	t	\N
1098	162	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 02:31:46.472621+08	t	\N
1099	162	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 02:31:46.472622+08	t	\N
1100	162	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 02:31:46.472624+08	t	\N
1101	162	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 02:31:46.472625+08	t	\N
1102	162	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:31:46.472626+08	t	\N
1103	162	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 02:31:46.472628+08	t	\N
1104	162	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 02:31:46.47263+08	t	\N
1105	162	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 02:31:46.472631+08	t	\N
1106	162	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 02:31:46.472632+08	t	\N
1107	162	\N	0705Z2	自然资源与国土空间规划学	\N	0705	[]	[]	academic	2026-10-19 02:31:46.472634+08	t	\N
1108	162	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:31:46.472635+08	t	\N
1109	162	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:31:46.472636+08	t	\N
1110	163	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:31:54.479506+08	t	\N
1111	163	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:31:54.479516+08	t	\N
1112	163	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:31:54.479519+08	t	\N
1113	163	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 02:31:54.479521+08	t	\N
1114	163	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 02:31:54.479523+08	t	\N
1115	163	\N	085605	林业工程	\N	0856	[]	[]	professional	2026-10-19 02:31:54.479525+08	t	\N
1116	163	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 02:31:54.479527+08	t	\N
1117	163	\N	085702	安全工程	\N	0857	[]	[]	professional	2026-10-19 02:31:54.479529+08	t	\N
1118	163	\N	085703	地质工程	\N	0857	[]	[]	professional	2026-10-19 02:31:54.479531+08	t	\N
1119	163	\N	085704	测绘工程	\N	0857	[]	[]	professional	2026-10-19 02:31:54.479533+08	t	\N
1120	163	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:31:54.479535+08	t	\N
1121	163	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:31:54.479537+08	t	\N
1122	163	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:31:54.47954+08	t	\N
1123	163	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 02:31:54.479542+08	t	\N
1124	163	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 02:31:54.479545+08	t	\N
1125	163	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 02:31:54.479547+08	t	\N
1126	163	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 02:31:54.479549+08	t	\N
1127	164	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 02:32:00.475569+08	t	\N
1128	164	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:32:00.475575+08	t	\N
1129	164	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:32:00.475576+08	t	\N
1130	164	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:32:00.475578+08	t	\N
1131	166	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:32:12.491233+08	t	\N
1132	167	\N	081103	系统工程	\N	0811	[]	[]	academic	2026-10-19 02:32:18.616093+08	t	\N
1133	168	\N	082704	辐射防护及环境保护	\N	0827	[]	[]	academic	2026-10-19 02:32:25.741609+08	t	\N
1134	168	\N	083001	环境科学	\N	0830	[]	[]	academic	2026-10-19 02:32:25.741618+08	t	\N
1135	169	\N	081704	应用化学	\N	0817	[]	[]	academic	2026-10-19 02:32:32.328296+08	t	\N
1136	169	\N	081705	工业催化	\N	0817	[]	[]	academic	2026-10-19 02:32:32.3283+08	t	\N
1137	171	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:32:45.25274+08	t	\N
1138	171	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:32:45.252742+08	t	\N
1139	171	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:32:45.252743+08	t	\N
1140	171	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:32:45.252743+08	t	\N
1141	171	\N	0812J1	低空技术与工程	\N	0812	[]	[]	academic	2026-10-19 02:32:45.252744+08	t	\N
1142	171	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:32:45.252744+08	t	\N
1143	171	\N	081704	应用化学	\N	0817	[]	[]	academic	2026-10-19 02:32:45.252744+08	t	\N
1144	171	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:32:45.252745+08	t	\N
1145	171	\N	0830J1	智慧生态交通工程	\N	0830	[]	[]	academic	2026-10-19 02:32:45.252745+08	t	\N
1146	171	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:32:45.252746+08	t	\N
1147	171	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:32:45.252746+08	t	\N
1148	171	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:32:45.252746+08	t	\N
1149	171	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:32:45.252747+08	t	\N
1150	171	\N	0703J1	稀土科学与产业发展	\N	0703	[]	[]	academic	2026-10-19 02:32:45.252747+08	t	\N
1151	171	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:32:45.252748+08	t	\N
1152	171	\N	0710J1	生物种质资源保护与利用	\N	0710	[]	[]	academic	2026-10-19 02:32:45.252748+08	t	\N
1153	171	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:32:45.252749+08	t	\N
1154	171	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 02:32:45.252749+08	t	\N
1155	172	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:32:51.860575+08	t	\N
1156	172	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:32:51.860584+08	t	\N
1157	172	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 02:32:51.860587+08	t	\N
1158	172	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:32:51.86059+08	t	\N
1159	172	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:32:51.860592+08	t	\N
1160	172	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:32:51.860594+08	t	\N
1161	172	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:32:51.860596+08	t	\N
1162	172	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:32:51.860598+08	t	\N
1163	172	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:32:51.8606+08	t	\N
1164	172	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:32:51.860602+08	t	\N
1165	172	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:32:51.860604+08	t	\N
1166	172	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:32:51.860606+08	t	\N
1167	172	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:32:51.860608+08	t	\N
1168	173	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:32:59.201868+08	t	\N
1169	173	\N	0801J1	低空技术与工程	\N	0801	[]	[]	academic	2026-10-19 02:32:59.20187+08	t	\N
1170	173	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:32:59.201871+08	t	\N
1171	173	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:32:59.201872+08	t	\N
1172	173	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:32:59.201872+08	t	\N
1173	173	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:32:59.201872+08	t	\N
1174	173	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:32:59.201873+08	t	\N
1175	173	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:32:59.201873+08	t	\N
1176	173	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:32:59.201874+08	t	\N
1177	173	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:32:59.201874+08	t	\N
1178	174	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:33:05.831425+08	t	\N
1179	174	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 02:33:05.831427+08	t	\N
1180	174	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:33:05.831428+08	t	\N
1181	174	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:33:05.831428+08	t	\N
1182	174	\N	081501	水文学及水资源	\N	0815	[]	[]	academic	2026-10-19 02:33:05.831429+08	t	\N
1183	174	\N	081503	水工结构工程	\N	0815	[]	[]	academic	2026-10-19 02:33:05.831429+08	t	\N
1184	174	\N	081504	水利水电工程	\N	0815	[]	[]	academic	2026-10-19 02:33:05.83143+08	t	\N
1185	174	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 02:33:05.83143+08	t	\N
1186	174	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 02:33:05.831431+08	t	\N
1187	174	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 02:33:05.831431+08	t	\N
1188	174	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:33:05.831432+08	t	\N
1189	174	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:33:05.831432+08	t	\N
1190	174	\N	071008	发育生物学	\N	0710	[]	[]	academic	2026-10-19 02:33:05.831432+08	t	\N
1191	174	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:33:05.831433+08	t	\N
1192	174	\N	071011	生物物理学	\N	0710	[]	[]	academic	2026-10-19 02:33:05.831433+08	t	\N
1193	175	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:33:12.363914+08	t	\N
1194	175	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:33:12.363916+08	t	\N
1195	175	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:33:12.363916+08	t	\N
1196	176	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:33:18.488899+08	t	\N
1197	176	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:33:18.488905+08	t	\N
1198	176	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:33:18.488907+08	t	\N
1199	176	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 02:33:18.488909+08	t	\N
1200	176	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:33:18.48891+08	t	\N
1201	176	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:33:18.488911+08	t	\N
1202	176	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:33:18.488913+08	t	\N
1203	176	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:33:18.488914+08	t	\N
1204	176	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:33:18.488915+08	t	\N
1205	176	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:33:18.488917+08	t	\N
1206	176	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:33:18.488918+08	t	\N
1207	176	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:33:18.48892+08	t	\N
1208	176	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 02:33:18.488921+08	t	\N
1209	176	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 02:33:18.488922+08	t	\N
1210	176	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 02:33:18.488924+08	t	\N
1211	176	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:33:18.488925+08	t	\N
1212	176	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 02:33:18.488926+08	t	\N
1213	176	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:33:18.488927+08	t	\N
1214	176	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 02:33:18.488929+08	t	\N
1215	177	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:33:25.569322+08	t	\N
1216	177	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:33:25.569331+08	t	\N
1217	177	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:33:25.569335+08	t	\N
1218	177	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:33:25.569337+08	t	\N
1219	177	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:33:25.56934+08	t	\N
1220	177	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:33:25.569342+08	t	\N
1221	177	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:33:25.569344+08	t	\N
1222	177	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:33:25.569346+08	t	\N
1223	178	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:33:32.063409+08	t	\N
1224	178	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:33:32.063411+08	t	\N
1225	178	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:33:32.063412+08	t	\N
1226	178	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 02:33:32.063412+08	t	\N
1227	178	\N	086004	发酵工程	\N	0860	[]	[]	professional	2026-10-19 02:33:32.063413+08	t	\N
1228	179	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:33:38.430322+08	t	\N
1229	179	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:33:38.430324+08	t	\N
1230	179	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:33:38.430325+08	t	\N
1231	181	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:33:52.974464+08	t	\N
1232	181	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:33:52.974467+08	t	\N
1233	183	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 02:34:06.503084+08	t	\N
1234	184	\N	080102	固体力学	\N	0801	[]	[]	academic	2026-10-19 02:34:13.786211+08	t	\N
1235	184	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 02:34:13.786213+08	t	\N
1236	184	\N	080401	精密仪器及机械	\N	0804	[]	[]	academic	2026-10-19 02:34:13.786214+08	t	\N
1237	184	\N	080402	测试计量技术及仪器	\N	0804	[]	[]	academic	2026-10-19 02:34:13.786214+08	t	\N
1238	184	\N	0804Z1	光电检测与微电子学	\N	0804	[]	[]	academic	2026-10-19 02:34:13.786215+08	t	\N
1239	184	\N	081202	计算机软件与理论	\N	0812	[]	[]	academic	2026-10-19 02:34:13.786215+08	t	\N
1240	184	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 02:34:13.786216+08	t	\N
1241	184	\N	0812Z1	低空技术与工程	\N	0812	[]	[]	academic	2026-10-19 02:34:13.786216+08	t	\N
1242	184	\N	083001	环境科学	\N	0830	[]	[]	academic	2026-10-19 02:34:13.786217+08	t	\N
1243	184	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 02:34:13.786217+08	t	\N
1244	184	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 02:34:13.786217+08	t	\N
1245	184	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 02:34:13.786218+08	t	\N
1246	184	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:34:13.786218+08	t	\N
1247	184	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 02:34:13.786219+08	t	\N
1248	184	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:34:13.786219+08	t	\N
1249	184	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 02:34:13.78622+08	t	\N
1250	184	\N	070203	原子与分子物理	\N	0702	[]	[]	academic	2026-10-19 02:34:13.78622+08	t	\N
1251	184	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:34:13.786221+08	t	\N
1252	184	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:34:13.786221+08	t	\N
1253	184	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 02:34:13.786221+08	t	\N
1254	185	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:34:20.040012+08	t	\N
1255	185	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 02:34:20.040014+08	t	\N
1256	185	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:34:20.040015+08	t	\N
1257	185	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 02:34:20.040016+08	t	\N
1258	185	\N	0802J1	智能制造	\N	0802	[]	[]	academic	2026-10-19 02:34:20.040016+08	t	\N
1259	185	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:34:20.040017+08	t	\N
1260	185	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:34:20.040017+08	t	\N
1261	185	\N	0805Z1	高分子材料	\N	0805	[]	[]	academic	2026-10-19 02:34:20.040017+08	t	\N
1262	185	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:34:20.040018+08	t	\N
1263	185	\N	080706	化工过程机械	\N	0807	[]	[]	academic	2026-10-19 02:34:20.040018+08	t	\N
1264	185	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:34:20.040019+08	t	\N
1265	185	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:34:20.040019+08	t	\N
1266	185	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:34:20.040019+08	t	\N
1267	185	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:34:20.04002+08	t	\N
1268	185	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 02:34:20.04002+08	t	\N
1269	185	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:34:20.040021+08	t	\N
1270	185	\N	078000	药学	\N	0780	[]	[]	academic	2026-10-19 02:34:20.040021+08	t	\N
1271	186	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:34:27.555563+08	t	\N
1272	186	\N	0802J3	国际工程与语言服务	\N	0802	[]	[]	academic	2026-10-19 02:34:27.555565+08	t	\N
1273	186	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:34:27.555566+08	t	\N
1274	186	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:34:27.555566+08	t	\N
1275	186	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:34:27.555567+08	t	\N
1276	186	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:34:27.555567+08	t	\N
1277	186	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:34:27.555568+08	t	\N
1278	186	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:34:27.555568+08	t	\N
1279	186	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:34:27.555569+08	t	\N
1280	186	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:34:27.555569+08	t	\N
1281	186	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:34:27.555569+08	t	\N
1282	186	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:34:27.55557+08	t	\N
1283	187	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:34:34.031922+08	t	\N
1284	187	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:34:34.031931+08	t	\N
1285	187	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:34:34.031935+08	t	\N
1286	187	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:34:34.031938+08	t	\N
1287	187	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:34:34.03194+08	t	\N
1288	187	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:34:34.031943+08	t	\N
1289	187	\N	0811J1	人工智能	\N	0811	[]	[]	academic	2026-10-19 02:34:34.031945+08	t	\N
1290	187	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:34:34.031947+08	t	\N
1291	187	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 02:34:34.031949+08	t	\N
1292	187	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 02:34:34.031951+08	t	\N
1293	187	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:34:34.031953+08	t	\N
1294	188	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:34:40.842902+08	t	\N
1295	188	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:34:40.84291+08	t	\N
1296	188	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:34:40.842913+08	t	\N
1297	188	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:34:40.842916+08	t	\N
1298	188	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:34:40.842919+08	t	\N
1299	188	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:34:40.842921+08	t	\N
1300	188	\N	0811J1	优化理论与过程控制	\N	0811	[]	[]	academic	2026-10-19 02:34:40.842923+08	t	\N
1301	188	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:34:40.842925+08	t	\N
1302	188	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:34:40.842927+08	t	\N
1303	188	\N	082600	兵器科学与技术	\N	0826	[]	[]	academic	2026-10-19 02:34:40.842929+08	t	\N
1304	189	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:34:47.902536+08	t	\N
1305	189	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 02:34:47.902545+08	t	\N
1306	189	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:34:47.902548+08	t	\N
1307	189	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:34:47.902551+08	t	\N
1308	189	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:34:47.902553+08	t	\N
1309	189	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 02:34:47.902555+08	t	\N
1310	189	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:34:47.902558+08	t	\N
1311	189	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:34:47.90256+08	t	\N
1312	189	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:34:47.902562+08	t	\N
1313	189	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:34:47.902564+08	t	\N
1314	189	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:34:47.902566+08	t	\N
1315	189	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:34:47.902568+08	t	\N
1316	189	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:34:47.902569+08	t	\N
1317	189	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:34:47.902571+08	t	\N
1318	190	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:34:54.884592+08	t	\N
1319	190	\N	0802Z1	低空运载器系统工程	\N	0802	[]	[]	academic	2026-10-19 02:34:54.884597+08	t	\N
1320	190	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:34:54.884599+08	t	\N
1321	190	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:34:54.884601+08	t	\N
1322	190	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 02:34:54.884602+08	t	\N
1323	190	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:34:54.884603+08	t	\N
1324	190	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:34:54.884605+08	t	\N
1325	190	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 02:34:54.884606+08	t	\N
1326	190	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 02:34:54.884607+08	t	\N
1327	190	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:34:54.884609+08	t	\N
1328	190	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:34:54.88461+08	t	\N
1329	191	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:35:01.392244+08	t	\N
1330	191	\N	0801J1	碳储科学与工程	\N	0801	[]	[]	academic	2026-10-19 02:35:01.392254+08	t	\N
1331	191	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:35:01.392257+08	t	\N
1332	191	\N	0802J1	智能矿山工程	\N	0802	[]	[]	academic	2026-10-19 02:35:01.392259+08	t	\N
1333	191	\N	0802J2	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:35:01.392262+08	t	\N
1334	191	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:35:01.392264+08	t	\N
1335	191	\N	0805J1	储能科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:35:01.392266+08	t	\N
1336	191	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:35:01.392268+08	t	\N
1337	191	\N	0807J2	碳储科学与工程	\N	0807	[]	[]	academic	2026-10-19 02:35:01.39227+08	t	\N
1338	191	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:35:01.392272+08	t	\N
1339	191	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:35:01.392274+08	t	\N
1340	192	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:35:06.974754+08	t	\N
1341	192	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:35:06.974763+08	t	\N
1342	192	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:35:06.974766+08	t	\N
1343	192	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:35:06.974769+08	t	\N
1344	192	\N	0811Z1	机器人科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:35:06.974771+08	t	\N
1345	192	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:35:06.974773+08	t	\N
1346	192	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:35:06.974775+08	t	\N
1347	192	\N	0817Z1	化工材料与高性能计算	\N	0817	[]	[]	academic	2026-10-19 02:35:06.974777+08	t	\N
1348	192	\N	082000	石油与天然气工程	\N	0820	[]	[]	academic	2026-10-19 02:35:06.974779+08	t	\N
1349	192	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:35:06.974781+08	t	\N
1350	192	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:35:06.974783+08	t	\N
1351	192	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:35:06.974785+08	t	\N
1352	193	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:35:13.654225+08	t	\N
1353	193	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:35:13.654234+08	t	\N
1354	193	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 02:35:13.654237+08	t	\N
1355	193	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:35:13.654239+08	t	\N
1356	193	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:35:13.654242+08	t	\N
1357	193	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:35:13.654244+08	t	\N
1358	193	\N	0811Z1	集成电路	\N	0811	[]	[]	academic	2026-10-19 02:35:13.654246+08	t	\N
1359	193	\N	0811Z2	人工智能	\N	0811	[]	[]	academic	2026-10-19 02:35:13.654247+08	t	\N
1360	193	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:35:13.654249+08	t	\N
1361	193	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:35:13.654251+08	t	\N
1362	193	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:35:13.654253+08	t	\N
1363	193	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 02:35:13.654255+08	t	\N
1364	193	\N	0703Z1	精细合成化学与分子工程	\N	0703	[]	[]	academic	2026-10-19 02:35:13.654257+08	t	\N
1365	194	\N	083201	食品科学	\N	0832	[]	[]	academic	2026-10-19 02:35:20.446727+08	t	\N
1366	194	\N	083202	粮食、油脂及植物蛋白工程	\N	0832	[]	[]	academic	2026-10-19 02:35:20.446737+08	t	\N
1367	194	\N	083203	农产品加工及贮藏工程	\N	0832	[]	[]	academic	2026-10-19 02:35:20.44674+08	t	\N
1368	194	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 02:35:20.446743+08	t	\N
1369	194	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 02:35:20.446745+08	t	\N
1370	194	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:35:20.446748+08	t	\N
1371	194	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:35:20.44675+08	t	\N
1372	194	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:35:20.446752+08	t	\N
1373	194	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:35:20.446754+08	t	\N
1374	195	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 02:35:26.866467+08	t	\N
1375	196	\N	083800	公安技术	\N	0838	[]	[]	academic	2026-10-19 02:35:33.539226+08	t	\N
1376	200	\N	082700	核科学与技术	\N	0827	[]	[]	academic	2026-10-19 02:36:00.209812+08	t	\N
1377	200	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:36:00.209821+08	t	\N
1378	200	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:36:00.209825+08	t	\N
1379	200	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:36:00.209827+08	t	\N
1380	200	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 02:36:00.209829+08	t	\N
1381	200	\N	085802	动力工程	\N	0858	[]	[]	professional	2026-10-19 02:36:00.209831+08	t	\N
1382	200	\N	085803	核能工程	\N	0858	[]	[]	professional	2026-10-19 02:36:00.209833+08	t	\N
1383	201	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 02:36:06.458705+08	t	\N
1384	201	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:36:06.45871+08	t	\N
1385	201	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:36:06.458712+08	t	\N
1386	201	\N	086100	交通运输	\N	0861	[]	[]	professional	2026-10-19 02:36:06.458714+08	t	\N
1387	202	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 02:36:13.168171+08	t	\N
1388	203	\N	082403	水声工程	\N	0824	[]	[]	academic	2026-10-19 02:36:19.695021+08	t	\N
1389	204	\N	081105	导航、制导与控制	\N	0811	[]	[]	academic	2026-10-19 02:36:27.461917+08	t	\N
1390	204	\N	082501	飞行器设计	\N	0825	[]	[]	academic	2026-10-19 02:36:27.461926+08	t	\N
1391	205	\N	082502	航空宇航推进理论与工程	\N	0825	[]	[]	academic	2026-10-19 02:36:34.327216+08	t	\N
1392	206	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 02:36:41.213887+08	t	\N
1393	207	\N	081704	应用化学	\N	0817	[]	[]	academic	2026-10-19 02:36:47.281203+08	t	\N
1394	208	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:36:53.532106+08	t	\N
1395	208	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 02:36:53.532115+08	t	\N
1396	208	\N	0802J1	人工智能	\N	0802	[]	[]	academic	2026-10-19 02:36:53.532118+08	t	\N
1397	208	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:36:53.532122+08	t	\N
1398	208	\N	080802	电力系统及其自动化	\N	0808	[]	[]	academic	2026-10-19 02:36:53.532124+08	t	\N
1399	208	\N	080804	电力电子与电力传动	\N	0808	[]	[]	academic	2026-10-19 02:36:53.532127+08	t	\N
1400	208	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:36:53.532129+08	t	\N
1401	208	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:36:53.532131+08	t	\N
1402	208	\N	0811J1	人工智能	\N	0811	[]	[]	academic	2026-10-19 02:36:53.532133+08	t	\N
1403	208	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:36:53.532134+08	t	\N
1404	208	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:36:53.532136+08	t	\N
1405	210	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:37:08.539566+08	t	\N
1406	210	\N	0812Z1	人工智能	\N	0812	[]	[]	academic	2026-10-19 02:37:08.539568+08	t	\N
1407	210	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:37:08.539569+08	t	\N
1408	210	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 02:37:08.539569+08	t	\N
1409	210	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 02:37:08.539569+08	t	\N
1410	210	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 02:37:08.53957+08	t	\N
1411	210	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:37:08.53957+08	t	\N
1412	210	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 02:37:08.539571+08	t	\N
1413	210	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:37:08.539571+08	t	\N
1414	210	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 02:37:08.539571+08	t	\N
1415	210	\N	070203	原子与分子物理	\N	0702	[]	[]	academic	2026-10-19 02:37:08.539572+08	t	\N
1416	210	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:37:08.539572+08	t	\N
1417	210	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:37:08.539573+08	t	\N
1418	212	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:37:21.554428+08	t	\N
1419	212	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:37:21.554439+08	t	\N
1420	212	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:21.554442+08	t	\N
1421	212	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:37:21.554445+08	t	\N
1422	212	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:21.554447+08	t	\N
1423	212	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:21.554449+08	t	\N
1424	212	\N	071011	生物物理学	\N	0710	[]	[]	academic	2026-10-19 02:37:21.554451+08	t	\N
1425	212	\N	0710J1	医学实验学	\N	0710	[]	[]	academic	2026-10-19 02:37:21.554453+08	t	\N
1426	213	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:37:28.631354+08	t	\N
1427	213	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:37:28.631357+08	t	\N
1428	213	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:37:28.631358+08	t	\N
1429	213	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:37:28.631358+08	t	\N
1430	213	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:37:28.631359+08	t	\N
1431	213	\N	082100	纺织科学与工程	\N	0821	[]	[]	academic	2026-10-19 02:37:28.631359+08	t	\N
1432	213	\N	0821Z1	纤维复合材料	\N	0821	[]	[]	academic	2026-10-19 02:37:28.63136+08	t	\N
1433	213	\N	082200	轻工技术与工程	\N	0822	[]	[]	academic	2026-10-19 02:37:28.63136+08	t	\N
1434	213	\N	0822Z1	生物质能源与材料	\N	0822	[]	[]	academic	2026-10-19 02:37:28.63136+08	t	\N
1435	213	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:37:28.631361+08	t	\N
1436	213	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:37:28.631361+08	t	\N
1437	213	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:28.631362+08	t	\N
1438	213	\N	077600	环境科学与工程	\N	0776	[]	[]	academic	2026-10-19 02:37:28.631362+08	t	\N
1439	214	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 02:37:34.634761+08	t	\N
1440	214	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 02:37:34.634764+08	t	\N
1441	214	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:37:34.634765+08	t	\N
1442	214	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:37:34.634765+08	t	\N
1443	214	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:37:34.634766+08	t	\N
1444	214	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:37:34.634766+08	t	\N
1445	214	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:37:34.634766+08	t	\N
1446	214	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:37:34.634767+08	t	\N
1447	214	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:37:34.634767+08	t	\N
1448	214	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:37:34.634768+08	t	\N
1449	214	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:37:34.634768+08	t	\N
1450	214	\N	0703J1	低碳化工与绿色生态	\N	0703	[]	[]	academic	2026-10-19 02:37:34.634769+08	t	\N
1451	214	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:34.634769+08	t	\N
1452	214	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:37:34.634769+08	t	\N
1453	214	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 02:37:34.63477+08	t	\N
1454	215	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:37:41.15503+08	t	\N
1455	215	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:41.155032+08	t	\N
1456	215	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:41.155033+08	t	\N
1457	215	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:37:41.155033+08	t	\N
1458	215	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:41.155034+08	t	\N
1459	215	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:41.155034+08	t	\N
1460	215	\N	0710J1	智能医学	\N	0710	[]	[]	academic	2026-10-19 02:37:41.155035+08	t	\N
1461	216	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 02:37:47.579763+08	t	\N
1462	216	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:37:47.579765+08	t	\N
1463	216	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:47.579766+08	t	\N
1464	216	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:47.579767+08	t	\N
1465	216	\N	071008	发育生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:47.579767+08	t	\N
1466	216	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:47.579768+08	t	\N
1467	216	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:37:47.579768+08	t	\N
1468	216	\N	0710Z1	生物技术	\N	0710	[]	[]	academic	2026-10-19 02:37:47.579768+08	t	\N
1469	216	\N	0710Z2	生物信息学	\N	0710	[]	[]	academic	2026-10-19 02:37:47.579769+08	t	\N
1470	217	\N	0714Z2	数据科学与数理统计	\N	0714	[]	[]	academic	2026-10-19 02:37:54.01099+08	t	\N
1471	218	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:38:00.460803+08	t	\N
1472	218	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:38:00.460812+08	t	\N
1473	218	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 02:38:00.460815+08	t	\N
1474	218	\N	0802Z1	工业工程	\N	0802	[]	[]	academic	2026-10-19 02:38:00.460817+08	t	\N
1475	218	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:38:00.46082+08	t	\N
1476	218	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:38:00.460822+08	t	\N
1477	218	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:38:00.460824+08	t	\N
1478	218	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:38:00.460825+08	t	\N
1479	218	\N	082301	道路与铁道工程	\N	0823	[]	[]	academic	2026-10-19 02:38:00.460827+08	t	\N
1480	218	\N	082302	交通信息工程及控制	\N	0823	[]	[]	academic	2026-10-19 02:38:00.460829+08	t	\N
1481	218	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:38:00.460831+08	t	\N
1482	219	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:38:07.528011+08	t	\N
1483	219	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:38:07.528014+08	t	\N
1484	219	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:38:07.528014+08	t	\N
1485	219	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:38:07.528015+08	t	\N
1486	219	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:38:07.528015+08	t	\N
1487	219	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:38:07.528016+08	t	\N
1488	219	\N	0812J1	人工智能	\N	0812	[]	[]	academic	2026-10-19 02:38:07.528016+08	t	\N
1489	219	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:38:07.528017+08	t	\N
1490	219	\N	082301	道路与铁道工程	\N	0823	[]	[]	academic	2026-10-19 02:38:07.528017+08	t	\N
1491	219	\N	082302	交通信息工程及控制	\N	0823	[]	[]	academic	2026-10-19 02:38:07.528017+08	t	\N
1492	219	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:38:07.528018+08	t	\N
1493	219	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:38:07.528018+08	t	\N
1494	219	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:38:07.528019+08	t	\N
1495	219	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 02:38:07.528019+08	t	\N
1496	220	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:38:14.80694+08	t	\N
1497	220	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 02:38:14.806949+08	t	\N
1498	220	\N	082400	船舶与海洋工程	\N	0824	[]	[]	academic	2026-10-19 02:38:14.806952+08	t	\N
1499	220	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 02:38:14.806955+08	t	\N
1500	220	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:38:14.806957+08	t	\N
1501	220	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:38:14.806959+08	t	\N
1502	220	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:38:14.806962+08	t	\N
1503	220	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:38:14.806964+08	t	\N
1504	220	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:38:14.806965+08	t	\N
1505	220	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:38:14.806967+08	t	\N
1506	220	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:38:14.806969+08	t	\N
1507	220	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:38:14.806971+08	t	\N
1508	220	\N	077500	计算机科学与技术	\N	0775	[]	[]	academic	2026-10-19 02:38:14.806973+08	t	\N
1509	222	\N	0836J1	人工智能	\N	0836	[]	[]	academic	2026-10-19 02:38:23.283454+08	t	\N
1510	222	\N	0836Z1	基因工程	\N	0836	[]	[]	academic	2026-10-19 02:38:23.283456+08	t	\N
1511	222	\N	0836Z2	化学生物工程	\N	0836	[]	[]	academic	2026-10-19 02:38:23.283457+08	t	\N
1512	222	\N	0836Z3	食品生物工程	\N	0836	[]	[]	academic	2026-10-19 02:38:23.283457+08	t	\N
1513	222	\N	0836Z4	环境生物工程	\N	0836	[]	[]	academic	2026-10-19 02:38:23.283458+08	t	\N
1514	222	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:38:23.283458+08	t	\N
1515	222	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:38:23.283459+08	t	\N
1516	222	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:38:23.283459+08	t	\N
1517	222	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:38:23.283459+08	t	\N
1518	222	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:38:23.28346+08	t	\N
1519	222	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 02:38:23.28346+08	t	\N
1520	222	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:38:23.283461+08	t	\N
1521	224	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:38:36.773715+08	t	\N
1522	224	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:38:36.773731+08	t	\N
1523	224	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 02:38:36.773733+08	t	\N
1524	224	\N	0802Z1	车身工程	\N	0802	[]	[]	academic	2026-10-19 02:38:36.773735+08	t	\N
1525	224	\N	0802Z2	工业工程	\N	0802	[]	[]	academic	2026-10-19 02:38:36.773736+08	t	\N
1526	224	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:38:36.773738+08	t	\N
1527	224	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:38:36.773739+08	t	\N
1528	224	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:38:36.773741+08	t	\N
1529	224	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:38:36.773742+08	t	\N
1530	224	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:38:36.773744+08	t	\N
1531	224	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:38:36.773745+08	t	\N
1532	224	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:38:36.773746+08	t	\N
1533	224	\N	070203	原子与分子物理	\N	0702	[]	[]	academic	2026-10-19 02:38:36.773748+08	t	\N
1534	224	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:38:36.773749+08	t	\N
1535	224	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:38:36.77375+08	t	\N
1536	224	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 02:38:36.773752+08	t	\N
1537	224	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 02:38:36.773753+08	t	\N
1538	224	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:38:36.773754+08	t	\N
1539	224	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 02:38:36.773755+08	t	\N
1540	224	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:38:36.773757+08	t	\N
1541	225	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:38:43.640936+08	t	\N
1542	225	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:38:43.640938+08	t	\N
1543	225	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:38:43.640938+08	t	\N
1544	225	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:38:43.640939+08	t	\N
1545	225	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:38:43.640939+08	t	\N
1546	225	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 02:38:43.64094+08	t	\N
1547	225	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 02:38:43.64094+08	t	\N
1548	225	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:38:43.640941+08	t	\N
1549	225	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:38:43.640941+08	t	\N
1550	225	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:38:43.640941+08	t	\N
1551	225	\N	0703J4	生物功能分子学	\N	0703	[]	[]	academic	2026-10-19 02:38:43.640942+08	t	\N
1552	225	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:38:43.640942+08	t	\N
1553	225	\N	0705J2	区域生态安全与绿色文化	\N	0705	[]	[]	academic	2026-10-19 02:38:43.640943+08	t	\N
1554	225	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:38:43.640943+08	t	\N
1555	226	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:38:49.173654+08	t	\N
1556	226	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:38:49.173663+08	t	\N
1557	226	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:38:49.173666+08	t	\N
1558	226	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:38:49.173669+08	t	\N
1559	226	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:38:49.173671+08	t	\N
1560	226	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:38:49.173674+08	t	\N
1561	226	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:38:49.173675+08	t	\N
1562	226	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:38:49.173677+08	t	\N
1563	226	\N	0812J1	人工智能	\N	0812	[]	[]	academic	2026-10-19 02:38:49.173679+08	t	\N
1564	226	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:38:49.173681+08	t	\N
1565	226	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:38:49.173683+08	t	\N
1566	226	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:38:49.173685+08	t	\N
1567	226	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:38:49.173687+08	t	\N
1568	226	\N	077400	电子科学与技术	\N	0774	[]	[]	academic	2026-10-19 02:38:49.173689+08	t	\N
1569	226	\N	077600	环境科学与工程	\N	0776	[]	[]	academic	2026-10-19 02:38:49.17369+08	t	\N
1570	227	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:38:55.768329+08	t	\N
1571	227	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:38:55.768338+08	t	\N
1572	227	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:38:55.768341+08	t	\N
1573	227	\N	0807J2	储能科学与工程	\N	0807	[]	[]	academic	2026-10-19 02:38:55.768344+08	t	\N
1574	227	\N	0807Z1	新能源科学与工程	\N	0807	[]	[]	academic	2026-10-19 02:38:55.768346+08	t	\N
1575	227	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:38:55.768348+08	t	\N
1576	227	\N	0808Z1	电力经济与管理	\N	0808	[]	[]	academic	2026-10-19 02:38:55.76835+08	t	\N
1577	227	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:38:55.768352+08	t	\N
1578	227	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:38:55.768354+08	t	\N
1579	227	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:38:55.768356+08	t	\N
1580	227	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:38:55.768358+08	t	\N
1581	228	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:39:02.626835+08	t	\N
1582	228	\N	0802Z2	智能制造工程	\N	0802	[]	[]	academic	2026-10-19 02:39:02.626844+08	t	\N
1583	228	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:39:02.626847+08	t	\N
1584	228	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 02:39:02.62685+08	t	\N
1585	228	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:39:02.626852+08	t	\N
1586	228	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:39:02.626854+08	t	\N
1587	228	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:39:02.626856+08	t	\N
1588	228	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:39:02.626858+08	t	\N
1589	228	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:39:02.62686+08	t	\N
1590	228	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:39:02.626862+08	t	\N
1591	228	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:39:02.626864+08	t	\N
1592	228	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:39:02.626866+08	t	\N
1593	228	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:39:02.626868+08	t	\N
1594	228	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 02:39:02.626869+08	t	\N
1595	228	\N	0703J1	新能源材料科学与技术	\N	0703	[]	[]	academic	2026-10-19 02:39:02.626871+08	t	\N
1596	228	\N	0703Z1	制药化学	\N	0703	[]	[]	academic	2026-10-19 02:39:02.626873+08	t	\N
1597	228	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:39:02.626875+08	t	\N
1598	228	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:39:02.626876+08	t	\N
1599	228	\N	0714Z1	数据科学与人工智能	\N	0714	[]	[]	academic	2026-10-19 02:39:02.626878+08	t	\N
1600	229	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:39:09.133393+08	t	\N
1601	229	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:39:09.133395+08	t	\N
1602	229	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:39:09.133395+08	t	\N
1603	229	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 02:39:09.133396+08	t	\N
1604	229	\N	081402	结构工程	\N	0814	[]	[]	academic	2026-10-19 02:39:09.133396+08	t	\N
1605	229	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 02:39:09.133397+08	t	\N
1606	229	\N	081404	供热、供燃气、通风及空调工程	\N	0814	[]	[]	academic	2026-10-19 02:39:09.133397+08	t	\N
1607	229	\N	081405	防灾减灾工程及防护工程	\N	0814	[]	[]	academic	2026-10-19 02:39:09.133398+08	t	\N
1608	229	\N	081406	桥梁与隧道工程	\N	0814	[]	[]	academic	2026-10-19 02:39:09.133398+08	t	\N
1609	229	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 02:39:09.133399+08	t	\N
1610	230	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:39:16.610217+08	t	\N
1611	230	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:39:16.610224+08	t	\N
1612	230	\N	0817Z1	化工企业管理	\N	0817	[]	[]	academic	2026-10-19 02:39:16.610226+08	t	\N
1613	230	\N	0817Z2	化工经济贸易	\N	0817	[]	[]	academic	2026-10-19 02:39:16.610228+08	t	\N
1614	230	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:39:16.61023+08	t	\N
1615	230	\N	085407	仪器仪表工程	\N	0854	[]	[]	professional	2026-10-19 02:39:16.610231+08	t	\N
1616	230	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:39:16.610232+08	t	\N
1617	230	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 02:39:16.610234+08	t	\N
1618	230	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 02:39:16.610235+08	t	\N
1619	230	\N	085503	航空工程	\N	0855	[]	[]	professional	2026-10-19 02:39:16.610236+08	t	\N
1620	230	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:39:16.610238+08	t	\N
1621	230	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:39:16.610239+08	t	\N
1622	231	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 02:39:22.700904+08	t	\N
1623	231	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 02:39:22.700907+08	t	\N
1624	231	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 02:39:22.700907+08	t	\N
1625	231	\N	0828J1	光学农业科学与工程	\N	0828	[]	[]	academic	2026-10-19 02:39:22.700908+08	t	\N
1626	231	\N	0828Z1	机械制造技术	\N	0828	[]	[]	academic	2026-10-19 02:39:22.700908+08	t	\N
1627	231	\N	0828Z2	智慧农业工程	\N	0828	[]	[]	academic	2026-10-19 02:39:22.700909+08	t	\N
1628	231	\N	083201	食品科学	\N	0832	[]	[]	academic	2026-10-19 02:39:22.700909+08	t	\N
1629	231	\N	0832Z1	食品安全与控制	\N	0832	[]	[]	academic	2026-10-19 02:39:22.70091+08	t	\N
1630	231	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:39:22.70091+08	t	\N
1631	231	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:39:22.700911+08	t	\N
1632	231	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:39:22.700911+08	t	\N
1633	231	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:39:22.700911+08	t	\N
1634	231	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 02:39:22.700912+08	t	\N
1635	231	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:39:22.700912+08	t	\N
1636	231	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:39:22.700913+08	t	\N
1637	231	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:39:22.700913+08	t	\N
1638	231	\N	077500	计算机科学与技术	\N	0775	[]	[]	academic	2026-10-19 02:39:22.700913+08	t	\N
1639	231	\N	077600	环境科学与工程	\N	0776	[]	[]	academic	2026-10-19 02:39:22.700914+08	t	\N
1640	233	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:39:37.23658+08	t	\N
1641	233	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 02:39:37.236583+08	t	\N
1642	233	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:39:37.236605+08	t	\N
1643	233	\N	085300	城乡规划	\N	0853	[]	[]	professional	2026-10-19 02:39:37.236608+08	t	\N
1644	233	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:39:37.236609+08	t	\N
1645	233	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:39:37.236611+08	t	\N
1646	233	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:39:37.236612+08	t	\N
1647	233	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:39:37.236614+08	t	\N
1648	233	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:39:37.236615+08	t	\N
1649	233	\N	087600	智能科学与技术	\N	0876	[]	[]	academic	2026-10-19 02:39:37.236616+08	t	\N
1650	233	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 02:39:37.236618+08	t	\N
1651	233	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 02:39:37.236619+08	t	\N
1652	233	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:39:37.23662+08	t	\N
1653	233	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 02:39:37.236621+08	t	\N
1654	233	\N	0701Z1	数学教育	\N	0701	[]	[]	academic	2026-10-19 02:39:37.236623+08	t	\N
1655	233	\N	0701Z2	数学技术	\N	0701	[]	[]	academic	2026-10-19 02:39:37.236625+08	t	\N
1656	233	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:39:37.236626+08	t	\N
1657	233	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 02:39:37.236628+08	t	\N
1658	233	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:39:37.236629+08	t	\N
1659	233	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:39:37.23663+08	t	\N
1660	234	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:39:44.577752+08	t	\N
1661	234	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:39:44.577754+08	t	\N
1662	234	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:39:44.577754+08	t	\N
1663	237	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 02:40:04.956014+08	t	\N
1664	237	\N	085802	动力工程	\N	0858	[]	[]	professional	2026-10-19 02:40:04.956024+08	t	\N
1665	237	\N	085807	清洁能源技术	\N	0858	[]	[]	professional	2026-10-19 02:40:04.956027+08	t	\N
1666	237	\N	085901	土木工程	\N	0859	[]	[]	professional	2026-10-19 02:40:04.956029+08	t	\N
1667	237	\N	085902	水利工程	\N	0859	[]	[]	professional	2026-10-19 02:40:04.956031+08	t	\N
1668	237	\N	085904	农田水土工程	\N	0859	[]	[]	professional	2026-10-19 02:40:04.956033+08	t	\N
1669	237	\N	085905	市政工程（含给排水等）	\N	0859	[]	[]	professional	2026-10-19 02:40:04.956035+08	t	\N
1670	237	\N	085906	人工环境工程（含供热、通风及空调等）	\N	0859	[]	[]	professional	2026-10-19 02:40:04.956037+08	t	\N
1671	239	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:40:18.654394+08	t	\N
1672	239	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:40:18.654403+08	t	\N
1673	239	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 02:40:18.654406+08	t	\N
1674	239	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:40:18.654408+08	t	\N
1675	239	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:40:18.654411+08	t	\N
1676	239	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:40:18.654412+08	t	\N
1677	239	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:40:18.654414+08	t	\N
1678	239	\N	0703Z1	环境化学	\N	0703	[]	[]	academic	2026-10-19 02:40:18.654416+08	t	\N
1679	239	\N	0703Z4	绿色化学	\N	0703	[]	[]	academic	2026-10-19 02:40:18.654418+08	t	\N
1680	239	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 02:40:18.65442+08	t	\N
1681	239	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 02:40:18.654421+08	t	\N
1682	239	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 02:40:18.654424+08	t	\N
1683	239	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:40:18.654426+08	t	\N
1684	239	\N	077300	材料科学与工程	\N	0773	[]	[]	academic	2026-10-19 02:40:18.654428+08	t	\N
1685	240	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:40:26.040778+08	t	\N
1686	240	\N	0871Z1	人工智能技术与应用	\N	0871	[]	[]	academic	2026-10-19 02:40:26.040784+08	t	\N
1687	240	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:40:26.040786+08	t	\N
1688	240	\N	0714J1	智能技术与智慧财经	\N	0714	[]	[]	academic	2026-10-19 02:40:26.040787+08	t	\N
1689	242	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:40:37.864653+08	t	\N
1690	242	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:40:37.864665+08	t	\N
1691	242	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:40:37.864668+08	t	\N
1692	242	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:40:37.86467+08	t	\N
1693	242	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:40:37.864673+08	t	\N
1694	242	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:40:37.864675+08	t	\N
1695	242	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:40:37.864677+08	t	\N
1696	243	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 02:40:44.265442+08	t	\N
1697	244	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:40:50.178258+08	t	\N
1698	244	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:40:50.17826+08	t	\N
1699	244	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:40:50.178261+08	t	\N
1700	244	\N	0811Z1	机电一体化理论及其应用	\N	0811	[]	[]	academic	2026-10-19 02:40:50.178261+08	t	\N
1701	244	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:40:50.178261+08	t	\N
1702	244	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 02:40:50.178262+08	t	\N
1703	244	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:40:50.178262+08	t	\N
1704	244	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:40:50.178263+08	t	\N
1705	244	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:40:50.178263+08	t	\N
1706	244	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:40:50.178264+08	t	\N
1707	244	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:40:50.178264+08	t	\N
1708	244	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:40:50.178264+08	t	\N
1709	244	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:40:50.178265+08	t	\N
1710	244	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 02:40:50.178265+08	t	\N
1711	244	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 02:40:50.178266+08	t	\N
1712	244	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 02:40:50.178266+08	t	\N
1713	244	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 02:40:50.178267+08	t	\N
1714	244	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 02:40:50.178267+08	t	\N
1715	244	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:40:50.178267+08	t	\N
1716	244	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:40:50.178268+08	t	\N
1717	245	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:40:56.595373+08	t	\N
1718	245	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:40:56.595376+08	t	\N
1719	245	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:40:56.595377+08	t	\N
1720	245	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:40:56.595377+08	t	\N
1721	245	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:40:56.595378+08	t	\N
1722	245	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:40:56.595378+08	t	\N
1723	245	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:40:56.595379+08	t	\N
1724	245	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:40:56.595379+08	t	\N
1725	245	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:40:56.59538+08	t	\N
1726	245	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:40:56.59538+08	t	\N
1727	245	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:40:56.59538+08	t	\N
1728	245	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:40:56.595381+08	t	\N
1729	245	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:40:56.595381+08	t	\N
1730	245	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:40:56.595382+08	t	\N
1731	245	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:40:56.595382+08	t	\N
1732	245	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:40:56.595383+08	t	\N
1733	245	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 02:40:56.595383+08	t	\N
1734	246	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:41:04.34393+08	t	\N
1735	246	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:41:04.343941+08	t	\N
1736	246	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:41:04.343944+08	t	\N
1737	246	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:41:04.343947+08	t	\N
1738	246	\N	080702	热能工程	\N	0807	[]	[]	academic	2026-10-19 02:41:04.343949+08	t	\N
1739	246	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:41:04.343951+08	t	\N
1740	246	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:41:04.343953+08	t	\N
1741	246	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:41:04.343954+08	t	\N
1742	246	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:41:04.343956+08	t	\N
1743	246	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:41:04.343958+08	t	\N
1744	246	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:41:04.34396+08	t	\N
1745	246	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:41:04.343962+08	t	\N
1746	246	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:41:04.343963+08	t	\N
1747	246	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 02:41:04.343965+08	t	\N
1748	247	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:41:11.404198+08	t	\N
1749	247	\N	0801J6	低空技术与工程	\N	0801	[]	[]	academic	2026-10-19 02:41:11.404204+08	t	\N
1750	247	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:41:11.404206+08	t	\N
1751	247	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:41:11.404208+08	t	\N
1752	247	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:41:11.404209+08	t	\N
1753	247	\N	0804J7	集成电路与智能传感	\N	0804	[]	[]	academic	2026-10-19 02:41:11.404211+08	t	\N
1754	247	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:41:11.404212+08	t	\N
1755	247	\N	0805Z1	医学材料与工程	\N	0805	[]	[]	academic	2026-10-19 02:41:11.404213+08	t	\N
1756	247	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:41:11.404215+08	t	\N
1757	247	\N	0807J3	深远海能源动力	\N	0807	[]	[]	academic	2026-10-19 02:41:11.404216+08	t	\N
1758	247	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:41:11.404217+08	t	\N
1759	247	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:41:11.404219+08	t	\N
1760	247	\N	070206	声学	\N	0702	[]	[]	academic	2026-10-19 02:41:11.40422+08	t	\N
1761	247	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:41:11.404221+08	t	\N
1762	248	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:41:17.390995+08	t	\N
1763	248	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:41:17.391+08	t	\N
1764	248	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:41:17.391002+08	t	\N
1765	248	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 02:41:17.391003+08	t	\N
1766	248	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:41:17.391005+08	t	\N
1767	248	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:41:17.391006+08	t	\N
1768	248	\N	081900	矿业工程	\N	0819	[]	[]	academic	2026-10-19 02:41:17.391008+08	t	\N
1769	248	\N	083700	安全科学与工程	\N	0837	[]	[]	academic	2026-10-19 02:41:17.391009+08	t	\N
1770	248	\N	085300	城乡规划	\N	0853	[]	[]	professional	2026-10-19 02:41:17.39101+08	t	\N
1771	248	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:41:17.391012+08	t	\N
1772	248	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:41:17.391013+08	t	\N
1773	249	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:41:23.77999+08	t	\N
1774	249	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:41:23.779992+08	t	\N
1775	249	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 02:41:23.779993+08	t	\N
1776	249	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:41:23.779993+08	t	\N
1777	249	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:41:23.779994+08	t	\N
1778	249	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:41:23.779994+08	t	\N
1779	249	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:41:23.779995+08	t	\N
1780	249	\N	0811J1	低空技术与工程	\N	0811	[]	[]	academic	2026-10-19 02:41:23.779995+08	t	\N
1781	249	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:41:23.779995+08	t	\N
1782	249	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:41:23.779996+08	t	\N
1783	249	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:41:23.779996+08	t	\N
1784	249	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:41:23.779997+08	t	\N
1785	249	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 02:41:23.779997+08	t	\N
1786	250	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:41:31.293234+08	t	\N
1787	250	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 02:41:31.293236+08	t	\N
1788	250	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 02:41:31.293237+08	t	\N
1789	250	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 02:41:31.293237+08	t	\N
1790	250	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 02:41:31.293238+08	t	\N
1791	250	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:41:31.293238+08	t	\N
1792	250	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:41:31.293239+08	t	\N
1793	250	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:41:31.293239+08	t	\N
1794	250	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:41:31.293239+08	t	\N
1795	250	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:41:31.29324+08	t	\N
1796	250	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:41:31.29324+08	t	\N
1797	250	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 02:41:31.293241+08	t	\N
1798	250	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:41:31.293241+08	t	\N
1799	250	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 02:41:31.293242+08	t	\N
1800	250	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:41:31.293242+08	t	\N
1801	250	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:41:31.293243+08	t	\N
1802	251	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:41:37.756154+08	t	\N
1803	251	\N	0802J1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:41:37.756157+08	t	\N
1804	251	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 02:41:37.756157+08	t	\N
1805	251	\N	0828J1	低空技术与工程	\N	0828	[]	[]	academic	2026-10-19 02:41:37.756158+08	t	\N
1806	251	\N	0828J2	农业人工智能	\N	0828	[]	[]	academic	2026-10-19 02:41:37.756158+08	t	\N
1807	251	\N	0832J1	低空技术与工程	\N	0832	[]	[]	academic	2026-10-19 02:41:37.756159+08	t	\N
1808	251	\N	0832J3	食品人工智能	\N	0832	[]	[]	academic	2026-10-19 02:41:37.756159+08	t	\N
1809	251	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:41:37.75616+08	t	\N
1810	251	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 02:41:37.75616+08	t	\N
1811	251	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:41:37.756161+08	t	\N
1812	251	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:41:37.756161+08	t	\N
1813	252	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:41:44.569519+08	t	\N
1814	252	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:41:44.569528+08	t	\N
1815	252	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 02:41:44.569531+08	t	\N
1816	252	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 02:41:44.569534+08	t	\N
1817	252	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 02:41:44.569537+08	t	\N
1818	252	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 02:41:44.569539+08	t	\N
1819	252	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 02:41:44.569541+08	t	\N
1820	252	\N	0828J3	寒地黑土工程	\N	0828	[]	[]	academic	2026-10-19 02:41:44.569543+08	t	\N
1821	252	\N	0828Z1	农业系统工程与管理工程	\N	0828	[]	[]	academic	2026-10-19 02:41:44.569545+08	t	\N
1822	252	\N	083201	食品科学	\N	0832	[]	[]	academic	2026-10-19 02:41:44.569547+08	t	\N
1823	252	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:41:44.569549+08	t	\N
1824	252	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:41:44.56955+08	t	\N
1825	252	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 02:41:44.569552+08	t	\N
1826	252	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:41:44.569554+08	t	\N
1827	252	\N	071008	发育生物学	\N	0710	[]	[]	academic	2026-10-19 02:41:44.569556+08	t	\N
1828	252	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:41:44.569558+08	t	\N
1829	252	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:41:44.56956+08	t	\N
1830	252	\N	0710Z2	生物育种科学	\N	0710	[]	[]	academic	2026-10-19 02:41:44.569561+08	t	\N
1831	253	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:41:51.475935+08	t	\N
1832	253	\N	0802J2	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:41:51.475937+08	t	\N
1833	253	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:41:51.475938+08	t	\N
1834	253	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:41:51.475938+08	t	\N
1835	253	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:41:51.475939+08	t	\N
1836	253	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:41:51.475939+08	t	\N
1837	253	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:41:51.47594+08	t	\N
1838	253	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:41:51.47594+08	t	\N
1839	253	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 02:41:51.47594+08	t	\N
1840	253	\N	082900	林业工程	\N	0829	[]	[]	academic	2026-10-19 02:41:51.475941+08	t	\N
1841	253	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:41:51.475941+08	t	\N
1842	253	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:41:51.475942+08	t	\N
1843	253	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:41:51.475942+08	t	\N
1844	253	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:41:51.475943+08	t	\N
1845	254	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 02:41:57.649941+08	t	\N
1846	254	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:41:57.64995+08	t	\N
1847	254	\N	0701Z1	数学教育	\N	0701	[]	[]	academic	2026-10-19 02:41:57.649954+08	t	\N
1848	254	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:41:57.649956+08	t	\N
1849	254	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:41:57.649958+08	t	\N
1850	254	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 02:41:57.64996+08	t	\N
1851	254	\N	0702J1	人工智能	\N	0702	[]	[]	academic	2026-10-19 02:41:57.649962+08	t	\N
1852	254	\N	0702Z1	计算物理	\N	0702	[]	[]	academic	2026-10-19 02:41:57.649965+08	t	\N
1853	254	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 02:41:57.649967+08	t	\N
1854	254	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 02:41:57.649968+08	t	\N
1855	255	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:42:03.905509+08	t	\N
1856	255	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:42:03.905518+08	t	\N
1857	255	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:42:03.905521+08	t	\N
1858	255	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 02:42:03.905524+08	t	\N
1859	257	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:42:17.045776+08	t	\N
1860	258	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:42:23.505632+08	t	\N
1861	259	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:42:30.991095+08	t	\N
1862	259	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:42:30.991104+08	t	\N
1863	259	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:42:30.991107+08	t	\N
1864	259	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 02:42:30.991109+08	t	\N
1865	259	\N	085704	测绘工程	\N	0857	[]	[]	professional	2026-10-19 02:42:30.991112+08	t	\N
1866	259	\N	086100	交通运输	\N	0861	[]	[]	professional	2026-10-19 02:42:30.991114+08	t	\N
1867	263	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:42:56.21856+08	t	\N
1868	263	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:42:56.218568+08	t	\N
1869	264	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 02:43:02.263495+08	t	\N
1870	265	\N	080102	固体力学	\N	0801	[]	[]	academic	2026-10-19 02:43:09.309157+08	t	\N
1871	265	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 02:43:09.309159+08	t	\N
1872	265	\N	080402	测试计量技术及仪器	\N	0804	[]	[]	academic	2026-10-19 02:43:09.30916+08	t	\N
1873	265	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 02:43:09.30916+08	t	\N
1874	265	\N	081402	结构工程	\N	0814	[]	[]	academic	2026-10-19 02:43:09.30916+08	t	\N
1875	265	\N	081405	防灾减灾工程及防护工程	\N	0814	[]	[]	academic	2026-10-19 02:43:09.309161+08	t	\N
1876	265	\N	081406	桥梁与隧道工程	\N	0814	[]	[]	academic	2026-10-19 02:43:09.309161+08	t	\N
1877	266	\N	082402	轮机工程	\N	0824	[]	[]	academic	2026-10-19 02:43:15.919142+08	t	\N
1878	266	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:43:15.919144+08	t	\N
1879	267	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 02:43:23.880929+08	t	\N
1880	270	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:43:45.395733+08	t	\N
1881	270	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:43:45.395742+08	t	\N
1882	270	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:43:45.395745+08	t	\N
1883	270	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 02:43:45.395748+08	t	\N
1884	270	\N	085704	测绘工程	\N	0857	[]	[]	professional	2026-10-19 02:43:45.39575+08	t	\N
1885	270	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:43:45.395752+08	t	\N
1886	270	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:43:45.395754+08	t	\N
1887	270	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:43:45.395756+08	t	\N
1888	270	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:43:45.395758+08	t	\N
1889	270	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:43:45.39576+08	t	\N
1890	270	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 02:43:45.395762+08	t	\N
1891	270	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:43:45.395764+08	t	\N
1892	270	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:43:45.395766+08	t	\N
1893	270	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 02:43:45.395768+08	t	\N
1894	270	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:43:45.395769+08	t	\N
1895	270	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:43:45.395771+08	t	\N
1896	271	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:43:53.30497+08	t	\N
1897	271	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:43:53.304979+08	t	\N
1898	271	\N	071008	发育生物学	\N	0710	[]	[]	academic	2026-10-19 02:43:53.304983+08	t	\N
1899	271	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:43:53.304985+08	t	\N
1900	271	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:43:53.304987+08	t	\N
1901	271	\N	071011	生物物理学	\N	0710	[]	[]	academic	2026-10-19 02:43:53.304989+08	t	\N
1902	271	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 02:43:53.304991+08	t	\N
1903	272	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:43:59.983016+08	t	\N
1904	272	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:43:59.983018+08	t	\N
1905	272	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:43:59.983019+08	t	\N
1906	272	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:43:59.983019+08	t	\N
1907	272	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:43:59.98302+08	t	\N
1908	273	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:44:05.762958+08	t	\N
1909	273	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:44:05.762968+08	t	\N
1910	273	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:44:05.762971+08	t	\N
1911	273	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:44:05.762973+08	t	\N
1912	273	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:44:05.762975+08	t	\N
1913	273	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:44:05.762977+08	t	\N
1914	273	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:44:05.762979+08	t	\N
1915	273	\N	070600	大气科学	\N	0706	[]	[]	academic	2026-10-19 02:44:05.762981+08	t	\N
1916	273	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:44:05.762983+08	t	\N
1917	273	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:44:05.762985+08	t	\N
1918	273	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 02:44:05.762987+08	t	\N
1919	273	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:44:05.76299+08	t	\N
1920	273	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:44:05.762992+08	t	\N
1921	273	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:44:05.762994+08	t	\N
1922	273	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:44:05.762996+08	t	\N
1923	273	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 02:44:05.762997+08	t	\N
1924	274	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:44:11.431619+08	t	\N
1925	274	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:44:11.431625+08	t	\N
1926	274	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 02:44:11.431627+08	t	\N
1927	274	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:44:11.431629+08	t	\N
1928	274	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:44:11.43163+08	t	\N
1929	274	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:44:11.431632+08	t	\N
1930	274	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:44:11.431633+08	t	\N
1931	274	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:44:11.431635+08	t	\N
1932	274	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:44:11.431636+08	t	\N
1933	274	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:44:11.431637+08	t	\N
1934	274	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:44:11.431639+08	t	\N
1935	274	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:44:11.43164+08	t	\N
1936	274	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:44:11.431641+08	t	\N
1937	274	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:44:11.431642+08	t	\N
1938	274	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 02:44:11.431644+08	t	\N
1939	274	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:44:11.431645+08	t	\N
1940	274	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 02:44:11.431647+08	t	\N
1941	274	\N	077800	基础医学	\N	0778	[]	[]	academic	2026-10-19 02:44:11.431648+08	t	\N
1942	274	\N	079905	康复科学与技术	\N	0799	[]	[]	academic	2026-10-19 02:44:11.431649+08	t	\N
1943	275	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:44:18.263453+08	t	\N
1944	275	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:44:18.263455+08	t	\N
1945	275	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:44:18.263456+08	t	\N
1946	275	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:44:18.263456+08	t	\N
1947	275	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:44:18.263456+08	t	\N
1948	275	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:44:18.263457+08	t	\N
1949	275	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:44:18.263457+08	t	\N
1950	275	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:44:18.263458+08	t	\N
1951	275	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:44:18.263458+08	t	\N
1952	275	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:44:18.263459+08	t	\N
1953	275	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:44:18.263459+08	t	\N
1954	275	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:44:18.263459+08	t	\N
1955	275	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:44:18.26346+08	t	\N
1956	275	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:44:18.26346+08	t	\N
1957	275	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 02:44:18.263461+08	t	\N
1958	275	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:44:18.263461+08	t	\N
1959	276	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:44:24.6523+08	t	\N
1960	276	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:44:24.652309+08	t	\N
1961	276	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:44:24.652312+08	t	\N
1962	276	\N	080702	热能工程	\N	0807	[]	[]	academic	2026-10-19 02:44:24.652315+08	t	\N
1963	276	\N	0807Z1	储能科学与工程	\N	0807	[]	[]	academic	2026-10-19 02:44:24.652317+08	t	\N
1964	276	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:44:24.652319+08	t	\N
1965	276	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:44:24.652321+08	t	\N
1966	276	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:44:24.652323+08	t	\N
1967	276	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:44:24.652325+08	t	\N
1968	276	\N	081703	生物化工	\N	0817	[]	[]	academic	2026-10-19 02:44:24.652326+08	t	\N
1969	276	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:44:24.652329+08	t	\N
1970	276	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:44:24.652331+08	t	\N
1971	276	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 02:44:24.652333+08	t	\N
1972	276	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 02:44:24.652335+08	t	\N
1973	276	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 02:44:24.652337+08	t	\N
1974	276	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 02:44:24.652339+08	t	\N
1975	276	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 02:44:24.65234+08	t	\N
1976	276	\N	0703Z1	精细合成化学与分子工程	\N	0703	[]	[]	academic	2026-10-19 02:44:24.652342+08	t	\N
1977	276	\N	0703Z2	化学生物学	\N	0703	[]	[]	academic	2026-10-19 02:44:24.652344+08	t	\N
1978	276	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:44:24.652346+08	t	\N
1979	277	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:44:32.127273+08	t	\N
1980	277	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:44:32.127283+08	t	\N
1981	277	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:44:32.127286+08	t	\N
1982	277	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:44:32.127288+08	t	\N
1983	277	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:44:32.12729+08	t	\N
1984	277	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:44:32.127292+08	t	\N
1985	277	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:44:32.127294+08	t	\N
1986	277	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:44:32.127295+08	t	\N
1987	277	\N	081103	系统工程	\N	0811	[]	[]	academic	2026-10-19 02:44:32.127298+08	t	\N
1988	277	\N	0811J1	低空技术与工程	\N	0811	[]	[]	academic	2026-10-19 02:44:32.1273+08	t	\N
1989	277	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:44:32.127302+08	t	\N
1990	277	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:44:32.127303+08	t	\N
1991	277	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:44:32.127305+08	t	\N
1992	277	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 02:44:32.127307+08	t	\N
1993	278	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:44:38.925835+08	t	\N
1994	278	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:44:38.925844+08	t	\N
1995	278	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:44:38.925848+08	t	\N
1996	278	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:44:38.925851+08	t	\N
1997	278	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:44:38.925853+08	t	\N
1998	278	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:44:38.925855+08	t	\N
1999	278	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 02:44:38.925857+08	t	\N
2000	278	\N	082302	交通信息工程及控制	\N	0823	[]	[]	academic	2026-10-19 02:44:38.925859+08	t	\N
2001	278	\N	082303	交通运输规划与管理	\N	0823	[]	[]	academic	2026-10-19 02:44:38.925861+08	t	\N
2002	278	\N	082304	载运工具运用工程	\N	0823	[]	[]	academic	2026-10-19 02:44:38.925863+08	t	\N
2003	278	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:44:38.925865+08	t	\N
2004	279	\N	080102	固体力学	\N	0801	[]	[]	academic	2026-10-19 02:44:45.067166+08	t	\N
2005	279	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:44:45.067168+08	t	\N
2006	279	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 02:44:45.067169+08	t	\N
2007	279	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 02:44:45.067169+08	t	\N
2008	279	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 02:44:45.067169+08	t	\N
2009	279	\N	0805Z1	纳米纤维及杂化材料	\N	0805	[]	[]	academic	2026-10-19 02:44:45.06717+08	t	\N
2010	279	\N	0805Z2	功能与智能材料	\N	0805	[]	[]	academic	2026-10-19 02:44:45.06717+08	t	\N
2011	279	\N	0805Z3	生物与仿生材料	\N	0805	[]	[]	academic	2026-10-19 02:44:45.067171+08	t	\N
2012	279	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:44:45.067171+08	t	\N
2013	279	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:44:45.067172+08	t	\N
2014	279	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:44:45.067172+08	t	\N
2015	279	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:44:45.067173+08	t	\N
2016	279	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:44:45.067173+08	t	\N
2017	279	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:44:45.067173+08	t	\N
2018	279	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 02:44:45.067174+08	t	\N
2019	279	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 02:44:45.067174+08	t	\N
2020	280	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:44:51.592257+08	t	\N
2021	280	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:44:51.592263+08	t	\N
2022	280	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:44:51.592266+08	t	\N
2023	280	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:44:51.592267+08	t	\N
2024	280	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:44:51.592269+08	t	\N
2025	280	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:44:51.59227+08	t	\N
2026	280	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:44:51.592272+08	t	\N
2027	280	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 02:44:51.592273+08	t	\N
2028	280	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 02:44:51.592274+08	t	\N
2029	280	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:44:51.592275+08	t	\N
2030	280	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:44:51.592278+08	t	\N
2031	280	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:44:51.592279+08	t	\N
2032	281	\N	080201	机械制造及其自动化	\N	0802	[]	[]	academic	2026-10-19 02:44:57.555677+08	t	\N
2033	281	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 02:44:57.555679+08	t	\N
2034	281	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 02:44:57.55568+08	t	\N
2035	281	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 02:44:57.55568+08	t	\N
2036	281	\N	0802Z2	低空运载器系统工程	\N	0802	[]	[]	academic	2026-10-19 02:44:57.555681+08	t	\N
2037	281	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:44:57.555681+08	t	\N
2038	281	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:44:57.555682+08	t	\N
2039	281	\N	0811Z1	智能立体交通工程	\N	0811	[]	[]	academic	2026-10-19 02:44:57.555682+08	t	\N
2040	281	\N	081701	化学工程	\N	0817	[]	[]	academic	2026-10-19 02:44:57.555683+08	t	\N
2041	281	\N	081703	生物化工	\N	0817	[]	[]	academic	2026-10-19 02:44:57.555683+08	t	\N
2042	281	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:44:57.555683+08	t	\N
2043	281	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:44:57.555684+08	t	\N
2044	282	\N	080705	制冷及低温工程	\N	0807	[]	[]	academic	2026-10-19 02:45:04.017518+08	t	\N
2045	282	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:45:04.017527+08	t	\N
2046	282	\N	0812J1	低空技术与工程	\N	0812	[]	[]	academic	2026-10-19 02:45:04.01753+08	t	\N
2047	282	\N	082400	船舶与海洋工程	\N	0824	[]	[]	academic	2026-10-19 02:45:04.017533+08	t	\N
2048	282	\N	0824J1	低空技术与工程	\N	0824	[]	[]	academic	2026-10-19 02:45:04.017535+08	t	\N
2049	282	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:45:04.017537+08	t	\N
2050	282	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:45:04.017539+08	t	\N
2051	282	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:45:04.017541+08	t	\N
2052	282	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:45:04.017543+08	t	\N
2053	282	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:45:04.017545+08	t	\N
2054	282	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:45:04.017547+08	t	\N
2055	282	\N	0707J1	低空技术与工程	\N	0707	[]	[]	academic	2026-10-19 02:45:04.017549+08	t	\N
2056	282	\N	0707Z1	海洋经济与管理	\N	0707	[]	[]	academic	2026-10-19 02:45:04.017551+08	t	\N
2057	282	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:45:04.017553+08	t	\N
2058	287	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:45:38.260074+08	t	\N
2059	287	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:45:38.260076+08	t	\N
2060	287	\N	0811Z1	低空技术与工程	\N	0811	[]	[]	academic	2026-10-19 02:45:38.260077+08	t	\N
2061	287	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:45:38.260077+08	t	\N
2062	287	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:45:38.260078+08	t	\N
2063	287	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 02:45:38.260078+08	t	\N
2064	287	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:45:38.260079+08	t	\N
2065	287	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:45:38.260079+08	t	\N
2066	287	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:45:38.260079+08	t	\N
2067	287	\N	085503	航空工程	\N	0855	[]	[]	professional	2026-10-19 02:45:38.26008+08	t	\N
2068	288	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:45:46.090763+08	t	\N
2069	292	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:46:11.87948+08	t	\N
2070	293	\N	080402	测试计量技术及仪器	\N	0804	[]	[]	academic	2026-10-19 02:46:19.182475+08	t	\N
2071	293	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 02:46:19.182485+08	t	\N
2072	294	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 02:46:24.938779+08	t	\N
2073	294	\N	082302	交通信息工程及控制	\N	0823	[]	[]	academic	2026-10-19 02:46:24.938786+08	t	\N
2074	294	\N	082401	船舶与海洋结构物设计制造	\N	0824	[]	[]	academic	2026-10-19 02:46:24.938788+08	t	\N
2075	294	\N	082402	轮机工程	\N	0824	[]	[]	academic	2026-10-19 02:46:24.93879+08	t	\N
2076	295	\N	080904	电磁场与微波技术	\N	0809	[]	[]	academic	2026-10-19 02:46:30.623901+08	t	\N
2077	296	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:46:38.06342+08	t	\N
2078	297	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 02:46:44.025368+08	t	\N
2079	297	\N	081101	控制理论与控制工程	\N	0811	[]	[]	academic	2026-10-19 02:46:44.025377+08	t	\N
2080	297	\N	082402	轮机工程	\N	0824	[]	[]	academic	2026-10-19 02:46:44.025381+08	t	\N
2081	298	\N	082402	轮机工程	\N	0824	[]	[]	academic	2026-10-19 02:46:50.547661+08	t	\N
2082	298	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:46:50.547663+08	t	\N
2083	299	\N	082403	水声工程	\N	0824	[]	[]	academic	2026-10-19 02:46:57.079309+08	t	\N
2084	300	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:47:04.144374+08	t	\N
2085	300	\N	082501	飞行器设计	\N	0825	[]	[]	academic	2026-10-19 02:47:04.144383+08	t	\N
2086	300	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:47:04.144386+08	t	\N
2087	300	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:47:04.144388+08	t	\N
2088	301	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:47:10.863221+08	t	\N
2089	301	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:47:10.86323+08	t	\N
2090	301	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 02:47:10.863233+08	t	\N
2091	302	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:47:17.13253+08	t	\N
2092	303	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 02:47:23.650291+08	t	\N
2093	303	\N	082401	船舶与海洋结构物设计制造	\N	0824	[]	[]	academic	2026-10-19 02:47:23.6503+08	t	\N
2094	305	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:47:37.603652+08	t	\N
2095	305	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 02:47:37.603654+08	t	\N
2096	306	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:47:45.120609+08	t	\N
2097	306	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:47:45.120612+08	t	\N
2098	306	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:47:45.120612+08	t	\N
2099	306	\N	081701	化学工程	\N	0817	[]	[]	academic	2026-10-19 02:47:45.120613+08	t	\N
2100	306	\N	081703	生物化工	\N	0817	[]	[]	academic	2026-10-19 02:47:45.120613+08	t	\N
2101	306	\N	081704	应用化学	\N	0817	[]	[]	academic	2026-10-19 02:47:45.120614+08	t	\N
2102	306	\N	081705	工业催化	\N	0817	[]	[]	academic	2026-10-19 02:47:45.120614+08	t	\N
2103	306	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:47:45.120615+08	t	\N
2104	306	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 02:47:45.120616+08	t	\N
2105	306	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:47:45.120616+08	t	\N
2106	306	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 02:47:45.120616+08	t	\N
2107	306	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 02:47:45.120617+08	t	\N
2108	306	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 02:47:45.120617+08	t	\N
2109	306	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:47:45.120618+08	t	\N
2110	306	\N	0701Z2	数学教育	\N	0701	[]	[]	academic	2026-10-19 02:47:45.120618+08	t	\N
2111	306	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:47:45.120618+08	t	\N
2112	306	\N	070204	等离子体物理	\N	0702	[]	[]	academic	2026-10-19 02:47:45.120619+08	t	\N
2113	306	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:47:45.120619+08	t	\N
2114	306	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:47:45.12062+08	t	\N
2115	306	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 02:47:45.12062+08	t	\N
2116	308	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:47:59.217415+08	t	\N
2117	308	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:47:59.217424+08	t	\N
2118	308	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:47:59.217427+08	t	\N
2119	310	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:48:12.546045+08	t	\N
2120	310	\N	0802Z1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:48:12.546047+08	t	\N
2121	310	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:48:12.546048+08	t	\N
2122	310	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:48:12.546049+08	t	\N
2123	310	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 02:48:12.546049+08	t	\N
2124	310	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 02:48:12.546049+08	t	\N
2125	310	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:48:12.54605+08	t	\N
2126	310	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:48:12.54605+08	t	\N
2127	310	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:48:12.546051+08	t	\N
2128	310	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 02:48:12.546051+08	t	\N
2129	311	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:48:18.907735+08	t	\N
2130	311	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:48:18.907741+08	t	\N
2131	311	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:48:18.907743+08	t	\N
2132	311	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:48:18.907744+08	t	\N
2133	311	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:48:18.907746+08	t	\N
2134	311	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:48:18.907748+08	t	\N
2135	311	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:48:18.907749+08	t	\N
2136	311	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:48:18.90775+08	t	\N
2137	311	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:48:18.907751+08	t	\N
2138	311	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:48:18.907753+08	t	\N
2139	311	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:48:18.907754+08	t	\N
2140	311	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:48:18.907755+08	t	\N
2141	311	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:48:18.907757+08	t	\N
2142	311	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:48:18.907758+08	t	\N
2143	312	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:48:26.384017+08	t	\N
2144	312	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:48:26.384024+08	t	\N
2145	312	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 02:48:26.384025+08	t	\N
2146	312	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 02:48:26.384027+08	t	\N
2147	312	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:48:26.384028+08	t	\N
2148	312	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:48:26.38403+08	t	\N
2149	312	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:48:26.384031+08	t	\N
2150	312	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:48:26.384032+08	t	\N
2151	312	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:48:26.384034+08	t	\N
2152	312	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:48:26.384035+08	t	\N
2153	312	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:48:26.384036+08	t	\N
2154	312	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:48:26.384037+08	t	\N
2155	312	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:48:26.384039+08	t	\N
2156	312	\N	0702Z1	量子科学与技术	\N	0702	[]	[]	academic	2026-10-19 02:48:26.38404+08	t	\N
2157	312	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:48:26.384041+08	t	\N
2158	312	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:48:26.384043+08	t	\N
2159	312	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:48:26.384044+08	t	\N
2160	312	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:48:26.384045+08	t	\N
2161	312	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:48:26.384047+08	t	\N
2162	312	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 02:48:26.384048+08	t	\N
2163	314	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:48:39.436924+08	t	\N
2164	315	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:48:46.206936+08	t	\N
2165	315	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:48:46.206938+08	t	\N
2166	315	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:48:46.206938+08	t	\N
2167	315	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:48:46.206939+08	t	\N
2168	315	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:48:46.206939+08	t	\N
2169	315	\N	082100	纺织科学与工程	\N	0821	[]	[]	academic	2026-10-19 02:48:46.20694+08	t	\N
2170	315	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 02:48:46.20694+08	t	\N
2171	315	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:48:46.206941+08	t	\N
2172	315	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:48:46.206941+08	t	\N
2173	315	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:48:46.206942+08	t	\N
2174	315	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:48:46.206942+08	t	\N
2175	316	\N	082700	核科学与技术	\N	0827	[]	[]	academic	2026-10-19 02:48:52.804337+08	t	\N
2176	316	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:48:52.804347+08	t	\N
2177	317	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:48:59.200552+08	t	\N
2178	317	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:48:59.200563+08	t	\N
2179	317	\N	0805J1	健康工程	\N	0805	[]	[]	academic	2026-10-19 02:48:59.200566+08	t	\N
2180	317	\N	080901	物理电子学	\N	0809	[]	[]	academic	2026-10-19 02:48:59.200569+08	t	\N
2181	317	\N	080902	电路与系统	\N	0809	[]	[]	academic	2026-10-19 02:48:59.200571+08	t	\N
2182	317	\N	080903	微电子学与固体电子学	\N	0809	[]	[]	academic	2026-10-19 02:48:59.200573+08	t	\N
2183	317	\N	080904	电磁场与微波技术	\N	0809	[]	[]	academic	2026-10-19 02:48:59.200575+08	t	\N
2184	317	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 02:48:59.200577+08	t	\N
2185	317	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 02:48:59.200579+08	t	\N
2186	317	\N	0810Z1	控制科学与智能工程	\N	0810	[]	[]	academic	2026-10-19 02:48:59.200581+08	t	\N
2187	317	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:48:59.200582+08	t	\N
2188	317	\N	070206	声学	\N	0702	[]	[]	academic	2026-10-19 02:48:59.200584+08	t	\N
2189	317	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 02:48:59.200586+08	t	\N
2190	317	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:48:59.200588+08	t	\N
2191	317	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 02:48:59.20059+08	t	\N
2192	317	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 02:48:59.200592+08	t	\N
2193	317	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 02:48:59.200593+08	t	\N
2194	317	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 02:48:59.200595+08	t	\N
2195	317	\N	0705J2	海洋地球科学	\N	0705	[]	[]	academic	2026-10-19 02:48:59.200597+08	t	\N
2196	317	\N	0705Z5	资源环境遥感	\N	0705	[]	[]	academic	2026-10-19 02:48:59.200599+08	t	\N
2197	318	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:49:05.364212+08	t	\N
2198	318	\N	0802Z2	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:49:05.364216+08	t	\N
2199	318	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:49:05.364217+08	t	\N
2200	318	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:49:05.364218+08	t	\N
2201	318	\N	0805J4	新能源科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:49:05.364218+08	t	\N
2202	318	\N	0805Z1	材料冶金	\N	0805	[]	[]	academic	2026-10-19 02:49:05.364219+08	t	\N
2203	318	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 02:49:05.364219+08	t	\N
2204	318	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:49:05.36422+08	t	\N
2205	318	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:49:05.36422+08	t	\N
2206	318	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:49:05.364221+08	t	\N
2207	318	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:49:05.364221+08	t	\N
2208	318	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:49:05.364222+08	t	\N
2209	318	\N	0702Z2	能源与环境系统工程	\N	0702	[]	[]	academic	2026-10-19 02:49:05.364222+08	t	\N
2210	318	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:49:05.364222+08	t	\N
2211	318	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:49:05.364223+08	t	\N
2212	318	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:49:05.364223+08	t	\N
2213	318	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 02:49:05.364224+08	t	\N
2214	318	\N	077806	放射医学	\N	0778	[]	[]	academic	2026-10-19 02:49:05.364224+08	t	\N
2215	319	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:49:11.129694+08	t	\N
2216	319	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:49:11.129705+08	t	\N
2217	319	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:49:11.129708+08	t	\N
2218	319	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:49:11.12971+08	t	\N
2219	319	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:49:11.129712+08	t	\N
2220	319	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:49:11.129714+08	t	\N
2221	319	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:49:11.129716+08	t	\N
2222	319	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:49:11.129718+08	t	\N
2223	319	\N	080904	电磁场与微波技术	\N	0809	[]	[]	academic	2026-10-19 02:49:11.12972+08	t	\N
2224	319	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:49:11.129722+08	t	\N
2225	319	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:49:11.129724+08	t	\N
2226	319	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:49:11.129726+08	t	\N
2227	319	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:49:11.12988+08	t	\N
2228	319	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:49:11.129891+08	t	\N
2229	319	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 02:49:11.129895+08	t	\N
2230	319	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:49:11.129898+08	t	\N
2231	320	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:49:17.573673+08	t	\N
2232	320	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:49:17.573675+08	t	\N
2233	320	\N	0802J2	航天仿生科学与技术	\N	0802	[]	[]	academic	2026-10-19 02:49:17.573676+08	t	\N
2234	320	\N	0802Z1	微细制造及微机电系统	\N	0802	[]	[]	academic	2026-10-19 02:49:17.573676+08	t	\N
2235	320	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:49:17.573677+08	t	\N
2236	320	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:49:17.573677+08	t	\N
2237	320	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:49:17.573678+08	t	\N
2238	320	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:49:17.573678+08	t	\N
2239	320	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:49:17.573678+08	t	\N
2240	320	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:49:17.573679+08	t	\N
2241	320	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:49:17.573679+08	t	\N
2242	320	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:49:17.57368+08	t	\N
2243	320	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:49:17.57368+08	t	\N
2244	321	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:49:24.890291+08	t	\N
2245	321	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:49:24.890301+08	t	\N
2246	321	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:49:24.890304+08	t	\N
2247	321	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:49:24.890307+08	t	\N
2248	321	\N	080402	测试计量技术及仪器	\N	0804	[]	[]	academic	2026-10-19 02:49:24.890309+08	t	\N
2249	321	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:49:24.890311+08	t	\N
2250	321	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:49:24.890313+08	t	\N
2251	321	\N	080701	工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:49:24.890315+08	t	\N
2252	321	\N	080702	热能工程	\N	0807	[]	[]	academic	2026-10-19 02:49:24.890317+08	t	\N
2253	321	\N	0807Z1	新能源科学与工程	\N	0807	[]	[]	academic	2026-10-19 02:49:24.890319+08	t	\N
2254	321	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:49:24.890321+08	t	\N
2255	321	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:49:24.890323+08	t	\N
2256	321	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:49:24.890325+08	t	\N
2257	322	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:49:30.682832+08	t	\N
2258	322	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:49:30.682834+08	t	\N
2259	322	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:49:30.682835+08	t	\N
2260	322	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 02:49:30.682835+08	t	\N
2261	322	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:49:30.682836+08	t	\N
2262	322	\N	0807J1	能源化学工程	\N	0807	[]	[]	academic	2026-10-19 02:49:30.682836+08	t	\N
2263	322	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:49:30.682837+08	t	\N
2264	322	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:49:30.682837+08	t	\N
2265	322	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:49:30.682838+08	t	\N
2266	322	\N	0811J2	低空技术与工程	\N	0811	[]	[]	academic	2026-10-19 02:49:30.682838+08	t	\N
2267	322	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:49:30.682838+08	t	\N
2268	322	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:49:30.682839+08	t	\N
2269	322	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:49:30.682839+08	t	\N
2270	322	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 02:49:30.68284+08	t	\N
2271	322	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 02:49:30.68284+08	t	\N
2272	323	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:49:36.915782+08	t	\N
2273	323	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 02:49:36.915784+08	t	\N
2274	323	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:49:36.915785+08	t	\N
2275	323	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:49:36.915785+08	t	\N
2276	323	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:49:36.915786+08	t	\N
2277	323	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:49:36.915786+08	t	\N
2278	323	\N	0808J3	储能科学与工程	\N	0808	[]	[]	academic	2026-10-19 02:49:36.915787+08	t	\N
2279	323	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:49:36.915787+08	t	\N
2280	323	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:49:36.915787+08	t	\N
2281	323	\N	0811J1	人工智能	\N	0811	[]	[]	academic	2026-10-19 02:49:36.915788+08	t	\N
2282	323	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:49:36.915788+08	t	\N
2283	323	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:49:36.915789+08	t	\N
2284	323	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:49:36.915789+08	t	\N
2285	323	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:49:36.915789+08	t	\N
2286	323	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 02:49:36.91579+08	t	\N
2287	323	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 02:49:36.91579+08	t	\N
2288	323	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:49:36.915791+08	t	\N
2289	324	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:49:44.08703+08	t	\N
2290	324	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:49:44.087039+08	t	\N
2291	324	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:49:44.087042+08	t	\N
2292	324	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:49:44.087045+08	t	\N
2293	324	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:49:44.087047+08	t	\N
2294	324	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:49:44.087049+08	t	\N
2295	324	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:49:44.087051+08	t	\N
2296	324	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:49:44.087053+08	t	\N
2297	324	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:49:44.087055+08	t	\N
2298	324	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:49:44.087057+08	t	\N
2299	324	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:49:44.087058+08	t	\N
2300	324	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:49:44.08706+08	t	\N
2301	324	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:49:44.087062+08	t	\N
2302	324	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:49:44.087064+08	t	\N
2303	325	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:49:51.935524+08	t	\N
2304	325	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:49:51.93553+08	t	\N
2305	325	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:49:51.935532+08	t	\N
2306	325	\N	080702	热能工程	\N	0807	[]	[]	academic	2026-10-19 02:49:51.935534+08	t	\N
2307	325	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:49:51.935535+08	t	\N
2308	325	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:49:51.935537+08	t	\N
2309	325	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:49:51.935538+08	t	\N
2310	325	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:49:51.935539+08	t	\N
2311	325	\N	082000	石油与天然气工程	\N	0820	[]	[]	academic	2026-10-19 02:49:51.935541+08	t	\N
2312	325	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:49:51.935542+08	t	\N
2313	325	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:49:51.935543+08	t	\N
2314	325	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 02:49:51.935544+08	t	\N
2315	326	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:49:57.596019+08	t	\N
2316	326	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:49:57.596023+08	t	\N
2317	326	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:49:57.596025+08	t	\N
2318	326	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:49:57.596025+08	t	\N
2319	326	\N	080901	物理电子学	\N	0809	[]	[]	academic	2026-10-19 02:49:57.596026+08	t	\N
2320	326	\N	080902	电路与系统	\N	0809	[]	[]	academic	2026-10-19 02:49:57.596027+08	t	\N
2321	326	\N	080903	微电子学与固体电子学	\N	0809	[]	[]	academic	2026-10-19 02:49:57.596028+08	t	\N
2322	326	\N	080904	电磁场与微波技术	\N	0809	[]	[]	academic	2026-10-19 02:49:57.596028+08	t	\N
2323	326	\N	0809Z1	有机电子学	\N	0809	[]	[]	academic	2026-10-19 02:49:57.596029+08	t	\N
2324	326	\N	0809Z2	生物电子学	\N	0809	[]	[]	academic	2026-10-19 02:49:57.596029+08	t	\N
2325	326	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:49:57.59603+08	t	\N
2326	326	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:49:57.596031+08	t	\N
2327	326	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:49:57.596031+08	t	\N
2328	326	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 02:49:57.596032+08	t	\N
2329	327	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:50:04.380171+08	t	\N
2330	327	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:50:04.380181+08	t	\N
2331	327	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:50:04.380185+08	t	\N
2332	327	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:50:04.380187+08	t	\N
2333	327	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:50:04.38019+08	t	\N
2334	327	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 02:50:04.380192+08	t	\N
2335	327	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 02:50:04.380194+08	t	\N
2336	327	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 02:50:04.380196+08	t	\N
2337	327	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 02:50:04.380198+08	t	\N
2338	327	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 02:50:04.3802+08	t	\N
2339	327	\N	077300	材料科学与工程	\N	0773	[]	[]	academic	2026-10-19 02:50:04.380202+08	t	\N
2340	327	\N	077600	环境科学与工程	\N	0776	[]	[]	academic	2026-10-19 02:50:04.380204+08	t	\N
2341	327	\N	078800	智能科学与技术	\N	0788	[]	[]	academic	2026-10-19 02:50:04.380206+08	t	\N
2342	327	\N	078900	纳米科学与工程	\N	0789	[]	[]	academic	2026-10-19 02:50:04.380207+08	t	\N
2343	328	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:50:10.512297+08	t	\N
2344	328	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:50:10.5123+08	t	\N
2345	328	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:50:10.5123+08	t	\N
2346	328	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:50:10.512301+08	t	\N
2347	328	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:50:10.512301+08	t	\N
2348	329	\N	085807	清洁能源技术	\N	0858	[]	[]	professional	2026-10-19 02:50:17.846952+08	t	\N
2349	329	\N	085808	储能技术	\N	0858	[]	[]	professional	2026-10-19 02:50:17.846954+08	t	\N
2350	329	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 02:50:17.846955+08	t	\N
2351	329	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 02:50:17.846955+08	t	\N
2352	333	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:50:44.92811+08	t	\N
2353	333	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:50:44.928116+08	t	\N
2354	333	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:50:44.928117+08	t	\N
2355	333	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 02:50:44.928119+08	t	\N
2356	333	\N	085509	智能制造技术	\N	0855	[]	[]	professional	2026-10-19 02:50:44.92812+08	t	\N
2357	333	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 02:50:44.928122+08	t	\N
2358	333	\N	085807	清洁能源技术	\N	0858	[]	[]	professional	2026-10-19 02:50:44.928123+08	t	\N
2359	333	\N	085808	储能技术	\N	0858	[]	[]	professional	2026-10-19 02:50:44.928124+08	t	\N
2360	333	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 02:50:44.928126+08	t	\N
2361	334	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:50:51.485028+08	t	\N
2362	334	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:50:51.485038+08	t	\N
2363	334	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 02:50:51.485041+08	t	\N
2364	334	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 02:50:51.485044+08	t	\N
2365	334	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 02:50:51.485046+08	t	\N
2366	334	\N	085808	储能技术	\N	0858	[]	[]	professional	2026-10-19 02:50:51.485048+08	t	\N
2367	334	\N	086102	道路交通运输	\N	0861	[]	[]	professional	2026-10-19 02:50:51.48505+08	t	\N
2368	334	\N	086104	航空交通运输	\N	0861	[]	[]	professional	2026-10-19 02:50:51.485052+08	t	\N
2369	335	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:50:59.097946+08	t	\N
2370	335	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:50:59.097948+08	t	\N
2371	335	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:50:59.097948+08	t	\N
2372	335	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:50:59.097949+08	t	\N
2373	335	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:50:59.097949+08	t	\N
2374	335	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:50:59.09795+08	t	\N
2375	335	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:50:59.09795+08	t	\N
2376	335	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:50:59.097951+08	t	\N
2377	335	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 02:50:59.097951+08	t	\N
2378	335	\N	085802	动力工程	\N	0858	[]	[]	professional	2026-10-19 02:50:59.097951+08	t	\N
2379	336	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:51:04.990715+08	t	\N
2380	336	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:51:04.990717+08	t	\N
2381	336	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:51:04.990718+08	t	\N
2382	336	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:51:04.990719+08	t	\N
2383	336	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 02:51:04.990719+08	t	\N
2384	336	\N	085807	清洁能源技术	\N	0858	[]	[]	professional	2026-10-19 02:51:04.99072+08	t	\N
2385	337	\N	081101	控制理论与控制工程	\N	0811	[]	[]	academic	2026-10-19 02:51:12.785716+08	t	\N
2386	337	\N	081102	检测技术与自动化装置	\N	0811	[]	[]	academic	2026-10-19 02:51:12.785719+08	t	\N
2387	337	\N	081103	系统工程	\N	0811	[]	[]	academic	2026-10-19 02:51:12.785719+08	t	\N
2388	338	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:51:18.305179+08	t	\N
2389	338	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:51:18.305181+08	t	\N
2390	340	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:51:31.576228+08	t	\N
2391	341	\N	080802	电力系统及其自动化	\N	0808	[]	[]	academic	2026-10-19 02:51:37.691474+08	t	\N
2392	341	\N	080803	高电压与绝缘技术	\N	0808	[]	[]	academic	2026-10-19 02:51:37.691477+08	t	\N
2393	341	\N	080804	电力电子与电力传动	\N	0808	[]	[]	academic	2026-10-19 02:51:37.691477+08	t	\N
2394	341	\N	080805	电工理论与新技术	\N	0808	[]	[]	academic	2026-10-19 02:51:37.691478+08	t	\N
2395	342	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:51:44.948134+08	t	\N
2396	342	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 02:51:44.948137+08	t	\N
2397	342	\N	081402	结构工程	\N	0814	[]	[]	academic	2026-10-19 02:51:44.948137+08	t	\N
2398	342	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 02:51:44.948138+08	t	\N
2399	342	\N	081405	防灾减灾工程及防护工程	\N	0814	[]	[]	academic	2026-10-19 02:51:44.948138+08	t	\N
2400	342	\N	081406	桥梁与隧道工程	\N	0814	[]	[]	academic	2026-10-19 02:51:44.948138+08	t	\N
2401	342	\N	081501	水文学及水资源	\N	0815	[]	[]	academic	2026-10-19 02:51:44.948139+08	t	\N
2402	342	\N	081502	水力学及河流动力学	\N	0815	[]	[]	academic	2026-10-19 02:51:44.948139+08	t	\N
2403	342	\N	081503	水工结构工程	\N	0815	[]	[]	academic	2026-10-19 02:51:44.94814+08	t	\N
2404	342	\N	081504	水利水电工程	\N	0815	[]	[]	academic	2026-10-19 02:51:44.94814+08	t	\N
2405	343	\N	082504	人机与环境工程	\N	0825	[]	[]	academic	2026-10-19 02:51:51.788817+08	t	\N
2406	344	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 02:51:58.492463+08	t	\N
2407	344	\N	082401	船舶与海洋结构物设计制造	\N	0824	[]	[]	academic	2026-10-19 02:51:58.492473+08	t	\N
2408	344	\N	082602	兵器发射理论与技术	\N	0826	[]	[]	academic	2026-10-19 02:51:58.492477+08	t	\N
2409	344	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:51:58.492479+08	t	\N
2410	344	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:51:58.492482+08	t	\N
2411	345	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:52:04.851522+08	t	\N
2412	345	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:52:04.851524+08	t	\N
2413	345	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 02:52:04.851525+08	t	\N
2414	345	\N	0802J1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:52:04.851525+08	t	\N
2415	345	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:52:04.851526+08	t	\N
2416	345	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:52:04.851526+08	t	\N
2417	345	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 02:52:04.851527+08	t	\N
2418	345	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:52:04.851527+08	t	\N
2419	345	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:52:04.851528+08	t	\N
2420	345	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:52:04.851528+08	t	\N
2421	345	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:52:04.851528+08	t	\N
2422	345	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:52:04.851529+08	t	\N
2423	345	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:52:04.851529+08	t	\N
2424	345	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:52:04.85153+08	t	\N
2425	345	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:52:04.85153+08	t	\N
2426	345	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:52:04.85153+08	t	\N
2427	346	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:52:11.242069+08	t	\N
2428	346	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:52:11.242078+08	t	\N
2429	346	\N	081601	大地测量学与测量工程	\N	0816	[]	[]	academic	2026-10-19 02:52:11.242081+08	t	\N
2430	346	\N	081602	摄影测量与遥感	\N	0816	[]	[]	academic	2026-10-19 02:52:11.242084+08	t	\N
2431	346	\N	081603	地图制图学与地理信息工程	\N	0816	[]	[]	academic	2026-10-19 02:52:11.242086+08	t	\N
2432	346	\N	0816J1	低空技术与工程	\N	0816	[]	[]	academic	2026-10-19 02:52:11.242088+08	t	\N
2433	346	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:52:11.24209+08	t	\N
2434	346	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:52:11.242092+08	t	\N
2435	346	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 02:52:11.242094+08	t	\N
2436	346	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:52:11.242095+08	t	\N
2437	346	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 02:52:11.242097+08	t	\N
2438	346	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 02:52:11.2421+08	t	\N
2439	346	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 02:52:11.242102+08	t	\N
2440	346	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 02:52:11.242104+08	t	\N
2441	346	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 02:52:11.242106+08	t	\N
2442	346	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 02:52:11.242107+08	t	\N
2443	346	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 02:52:11.242109+08	t	\N
2444	346	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 02:52:11.242111+08	t	\N
2445	346	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:52:11.242113+08	t	\N
2446	346	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 02:52:11.242115+08	t	\N
2447	347	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:52:18.83033+08	t	\N
2448	347	\N	0802Z1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:52:18.830333+08	t	\N
2449	347	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:52:18.830334+08	t	\N
2450	347	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 02:52:18.830335+08	t	\N
2451	347	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:52:18.830335+08	t	\N
2452	347	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:52:18.830335+08	t	\N
2453	347	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:52:18.830336+08	t	\N
2454	347	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:52:18.830336+08	t	\N
2455	347	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:52:18.830337+08	t	\N
2456	347	\N	086100	交通运输	\N	0861	[]	[]	professional	2026-10-19 02:52:18.830337+08	t	\N
2457	348	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:52:25.301132+08	t	\N
2458	348	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:52:25.301142+08	t	\N
2459	348	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:52:25.301145+08	t	\N
2460	348	\N	0811J1	低空技术与工程（低空智能航行技术）	\N	0811	[]	[]	academic	2026-10-19 02:52:25.301148+08	t	\N
2461	348	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:52:25.30115+08	t	\N
2462	348	\N	082400	船舶与海洋工程	\N	0824	[]	[]	academic	2026-10-19 02:52:25.301152+08	t	\N
2463	348	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:52:25.301154+08	t	\N
2464	348	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:52:25.301156+08	t	\N
2465	348	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:52:25.301158+08	t	\N
2466	348	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:52:25.30116+08	t	\N
2467	348	\N	070701	物理海洋学	\N	0707	[]	[]	academic	2026-10-19 02:52:25.301162+08	t	\N
2468	348	\N	070702	海洋化学	\N	0707	[]	[]	academic	2026-10-19 02:52:25.301164+08	t	\N
2469	348	\N	070703	海洋生物学	\N	0707	[]	[]	academic	2026-10-19 02:52:25.301166+08	t	\N
2470	348	\N	070704	海洋地质	\N	0707	[]	[]	academic	2026-10-19 02:52:25.301168+08	t	\N
2471	348	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 02:52:25.30117+08	t	\N
2472	350	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:52:38.430608+08	t	\N
2473	350	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:52:38.430611+08	t	\N
2474	350	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:52:38.430612+08	t	\N
2475	350	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 02:52:38.430613+08	t	\N
2476	351	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:52:45.111957+08	t	\N
2477	351	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:52:45.111966+08	t	\N
2478	351	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:52:45.111969+08	t	\N
2479	351	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:52:45.111972+08	t	\N
2480	351	\N	0812Z1	低空智能航行技术	\N	0812	[]	[]	academic	2026-10-19 02:52:45.111974+08	t	\N
2481	351	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:52:45.111976+08	t	\N
2482	351	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:52:45.112013+08	t	\N
2483	351	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 02:52:45.112016+08	t	\N
2484	351	\N	081404	供热、供燃气、通风及空调工程	\N	0814	[]	[]	academic	2026-10-19 02:52:45.112018+08	t	\N
2485	351	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:52:45.11202+08	t	\N
2486	351	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:52:45.112023+08	t	\N
2487	351	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:52:45.112025+08	t	\N
2488	352	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:52:51.696859+08	t	\N
2489	352	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:52:51.696868+08	t	\N
2490	352	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:52:51.696871+08	t	\N
2491	352	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:52:51.696874+08	t	\N
2492	352	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 02:52:51.696876+08	t	\N
2493	352	\N	086100	交通运输	\N	0861	[]	[]	professional	2026-10-19 02:52:51.696879+08	t	\N
2494	353	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:52:58.734824+08	t	\N
2495	353	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:52:58.734826+08	t	\N
2496	353	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:52:58.734827+08	t	\N
2497	353	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:52:58.734827+08	t	\N
2498	353	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:52:58.734828+08	t	\N
2499	353	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 02:52:58.734829+08	t	\N
2500	353	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:52:58.734829+08	t	\N
2501	353	\N	083001	环境科学	\N	0830	[]	[]	academic	2026-10-19 02:52:58.73483+08	t	\N
2502	353	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 02:52:58.73483+08	t	\N
2503	353	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:52:58.734831+08	t	\N
2504	353	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:52:58.734831+08	t	\N
2505	353	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:52:58.734831+08	t	\N
2506	353	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:52:58.734832+08	t	\N
2507	353	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 02:52:58.734832+08	t	\N
2508	353	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 02:52:58.734833+08	t	\N
2509	353	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 02:52:58.734833+08	t	\N
2510	353	\N	0705Z2	地理环境遥感	\N	0705	[]	[]	academic	2026-10-19 02:52:58.734833+08	t	\N
2511	353	\N	0705Z3	地理教育学	\N	0705	[]	[]	academic	2026-10-19 02:52:58.734834+08	t	\N
2512	353	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:52:58.734834+08	t	\N
2513	353	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:52:58.734835+08	t	\N
2514	354	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:53:06.036065+08	t	\N
2515	354	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:53:06.036075+08	t	\N
2516	354	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 02:53:06.036078+08	t	\N
2517	354	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 02:53:06.03608+08	t	\N
2518	354	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 02:53:06.036082+08	t	\N
2519	354	\N	0828J1	植物表型组学	\N	0828	[]	[]	academic	2026-10-19 02:53:06.036084+08	t	\N
2520	354	\N	0828J2	智慧农业	\N	0828	[]	[]	academic	2026-10-19 02:53:06.036086+08	t	\N
2521	354	\N	0828Z2	智能科学与技术	\N	0828	[]	[]	academic	2026-10-19 02:53:06.036088+08	t	\N
2522	354	\N	083001	环境科学	\N	0830	[]	[]	academic	2026-10-19 02:53:06.03609+08	t	\N
2523	354	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 02:53:06.036092+08	t	\N
2524	354	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:53:06.036094+08	t	\N
2525	354	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:53:06.036096+08	t	\N
2526	354	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:53:06.036098+08	t	\N
2527	354	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 02:53:06.0361+08	t	\N
2528	354	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:06.036102+08	t	\N
2529	354	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:53:06.036103+08	t	\N
2530	354	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:06.036105+08	t	\N
2531	354	\N	0710J1	农业合成生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:06.036107+08	t	\N
2532	354	\N	0710Z1	生物信息学	\N	0710	[]	[]	academic	2026-10-19 02:53:06.036109+08	t	\N
2533	354	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 02:53:06.03611+08	t	\N
2534	355	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:53:12.604124+08	t	\N
2535	355	\N	0802Z1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:53:12.604134+08	t	\N
2536	355	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:53:12.604137+08	t	\N
2537	355	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:53:12.604139+08	t	\N
2538	355	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:53:12.604141+08	t	\N
2539	355	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:53:12.604143+08	t	\N
2540	355	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:53:12.604145+08	t	\N
2541	355	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 02:53:12.604147+08	t	\N
2542	355	\N	081402	结构工程	\N	0814	[]	[]	academic	2026-10-19 02:53:12.60415+08	t	\N
2543	355	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 02:53:12.604152+08	t	\N
2544	355	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:53:12.604153+08	t	\N
2545	355	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:53:12.604155+08	t	\N
2546	355	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 02:53:12.604157+08	t	\N
2547	355	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 02:53:12.604159+08	t	\N
2548	355	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:12.604161+08	t	\N
2549	355	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:12.604163+08	t	\N
2550	355	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:53:12.604165+08	t	\N
2551	355	\N	0713J1	碳中和科学与技术	\N	0713	[]	[]	academic	2026-10-19 02:53:12.604167+08	t	\N
2552	355	\N	077601	环境科学	\N	0776	[]	[]	academic	2026-10-19 02:53:12.604169+08	t	\N
2553	356	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:53:19.513556+08	t	\N
2554	356	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:53:19.513566+08	t	\N
2555	356	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:53:19.513569+08	t	\N
2556	356	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:19.513572+08	t	\N
2557	356	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:19.513574+08	t	\N
2558	356	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:53:19.513577+08	t	\N
2559	356	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:19.513579+08	t	\N
2560	356	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:19.513581+08	t	\N
2561	356	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 02:53:19.513583+08	t	\N
2562	357	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:53:26.816413+08	t	\N
2563	357	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 02:53:26.816415+08	t	\N
2564	357	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 02:53:26.816416+08	t	\N
2565	357	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:53:26.816417+08	t	\N
2566	357	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:26.816417+08	t	\N
2567	357	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:26.816417+08	t	\N
2568	357	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:53:26.816418+08	t	\N
2569	357	\N	071008	发育生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:26.816418+08	t	\N
2570	357	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:26.816419+08	t	\N
2571	357	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:26.816419+08	t	\N
2572	357	\N	071011	生物物理学	\N	0710	[]	[]	academic	2026-10-19 02:53:26.816419+08	t	\N
2573	357	\N	0710J1	医药生物技术学	\N	0710	[]	[]	academic	2026-10-19 02:53:26.81642+08	t	\N
2574	358	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 02:53:33.039187+08	t	\N
2575	358	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:33.039189+08	t	\N
2576	358	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:53:33.03919+08	t	\N
2577	359	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:53:39.827854+08	t	\N
2578	359	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:53:39.827856+08	t	\N
2579	359	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:53:39.827857+08	t	\N
2580	359	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:53:39.827858+08	t	\N
2581	359	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:53:39.827858+08	t	\N
2582	359	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:53:39.827859+08	t	\N
2583	359	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:53:39.827859+08	t	\N
2584	360	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:53:46.842153+08	t	\N
2585	360	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:53:46.842162+08	t	\N
2586	360	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:53:46.842165+08	t	\N
2587	360	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:53:46.842168+08	t	\N
2588	360	\N	0810J2	人工智能	\N	0810	[]	[]	academic	2026-10-19 02:53:46.84217+08	t	\N
2589	360	\N	0810J5	低空技术与工程	\N	0810	[]	[]	academic	2026-10-19 02:53:46.842172+08	t	\N
2590	360	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:53:46.842173+08	t	\N
2591	360	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:53:46.842175+08	t	\N
2592	360	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 02:53:46.842177+08	t	\N
2593	360	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 02:53:46.842179+08	t	\N
2594	360	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:53:46.842181+08	t	\N
2595	360	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:53:46.842183+08	t	\N
2596	360	\N	070601	气象学	\N	0706	[]	[]	academic	2026-10-19 02:53:46.842185+08	t	\N
2597	360	\N	070602	大气物理学与大气环境	\N	0706	[]	[]	academic	2026-10-19 02:53:46.842186+08	t	\N
2598	360	\N	0706Z2	应用气象学	\N	0706	[]	[]	academic	2026-10-19 02:53:46.842189+08	t	\N
2599	360	\N	0706Z3	大气遥感与大气探测	\N	0706	[]	[]	academic	2026-10-19 02:53:46.842191+08	t	\N
2600	360	\N	0706Z4	雷电科学与技术	\N	0706	[]	[]	academic	2026-10-19 02:53:46.842193+08	t	\N
2601	360	\N	0706Z5	3S集成与气象应用	\N	0706	[]	[]	academic	2026-10-19 02:53:46.842195+08	t	\N
2602	360	\N	0706Z6	空间天气学	\N	0706	[]	[]	academic	2026-10-19 02:53:46.842197+08	t	\N
2603	360	\N	0706Z9	水文气象学	\N	0706	[]	[]	academic	2026-10-19 02:53:46.842199+08	t	\N
2604	361	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 02:53:54.530535+08	t	\N
2605	361	\N	085901	土木工程	\N	0859	[]	[]	professional	2026-10-19 02:53:54.530544+08	t	\N
2606	361	\N	085905	市政工程（含给排水等）	\N	0859	[]	[]	professional	2026-10-19 02:53:54.530548+08	t	\N
2607	361	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 02:53:54.53055+08	t	\N
2608	361	\N	086003	食品工程	\N	0860	[]	[]	professional	2026-10-19 02:53:54.530552+08	t	\N
2609	362	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:54:02.246657+08	t	\N
2610	362	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:54:02.246659+08	t	\N
2611	362	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:54:02.246659+08	t	\N
2612	362	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:54:02.24666+08	t	\N
2613	362	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:54:02.24666+08	t	\N
2614	362	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:54:02.246661+08	t	\N
2615	362	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:54:02.246661+08	t	\N
2616	362	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:54:02.246662+08	t	\N
2617	362	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 02:54:02.246662+08	t	\N
2618	362	\N	082600	兵器科学与技术	\N	0826	[]	[]	academic	2026-10-19 02:54:02.246662+08	t	\N
2619	362	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:54:02.246663+08	t	\N
2620	363	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:54:09.31485+08	t	\N
2621	363	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:54:09.314852+08	t	\N
2622	363	\N	085100	建筑	\N	0851	[]	[]	professional	2026-10-19 02:54:09.314852+08	t	\N
2623	363	\N	085300	城乡规划	\N	0853	[]	[]	professional	2026-10-19 02:54:09.314853+08	t	\N
2624	363	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:54:09.314853+08	t	\N
2625	363	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:54:09.314854+08	t	\N
2626	363	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:54:09.314854+08	t	\N
2627	363	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:54:09.314855+08	t	\N
2628	363	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:54:09.314855+08	t	\N
2629	363	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:54:09.314856+08	t	\N
2630	363	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:54:09.314856+08	t	\N
2631	363	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:54:09.314856+08	t	\N
2632	363	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:54:09.314857+08	t	\N
2633	364	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:54:15.883298+08	t	\N
2634	364	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:54:15.8833+08	t	\N
2635	364	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:54:15.883301+08	t	\N
2636	364	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:54:15.883301+08	t	\N
2637	364	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:54:15.883302+08	t	\N
2638	364	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:54:15.883302+08	t	\N
2639	364	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:54:15.883302+08	t	\N
2640	364	\N	0812Z2	数字媒体技术	\N	0812	[]	[]	academic	2026-10-19 02:54:15.883303+08	t	\N
2641	364	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:54:15.883303+08	t	\N
2642	364	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:54:15.883304+08	t	\N
2643	364	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:54:15.883304+08	t	\N
2644	364	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:54:15.883304+08	t	\N
2645	365	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:54:22.952194+08	t	\N
2646	365	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:54:22.952197+08	t	\N
2647	365	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:54:22.952197+08	t	\N
2648	365	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:54:22.952198+08	t	\N
2649	365	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:54:22.952198+08	t	\N
2650	365	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:54:22.952199+08	t	\N
2651	365	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:54:22.952199+08	t	\N
2652	365	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:54:22.9522+08	t	\N
2653	365	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:54:22.9522+08	t	\N
2654	365	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:54:22.9522+08	t	\N
2655	365	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:54:22.952201+08	t	\N
2656	365	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:54:22.952201+08	t	\N
2657	365	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:54:22.952202+08	t	\N
2658	365	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:54:22.952202+08	t	\N
2659	365	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:54:22.952203+08	t	\N
2660	365	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 02:54:22.952203+08	t	\N
2661	366	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:54:29.136068+08	t	\N
2662	366	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:54:29.136074+08	t	\N
2663	366	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:54:29.136077+08	t	\N
2664	366	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:54:29.136079+08	t	\N
2665	366	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:54:29.13608+08	t	\N
2666	366	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:54:29.136082+08	t	\N
2667	366	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:54:29.136083+08	t	\N
2668	366	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:54:29.136084+08	t	\N
2669	366	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:54:29.136086+08	t	\N
2670	366	\N	082100	纺织科学与工程	\N	0821	[]	[]	academic	2026-10-19 02:54:29.136087+08	t	\N
2671	366	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:54:29.136088+08	t	\N
2672	366	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:54:29.13609+08	t	\N
2673	366	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:54:29.136091+08	t	\N
2674	366	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:54:29.136092+08	t	\N
2675	367	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:54:35.795048+08	t	\N
2676	367	\N	0802Z1	低空技术与工程学科	\N	0802	[]	[]	academic	2026-10-19 02:54:35.795057+08	t	\N
2677	367	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 02:54:35.795061+08	t	\N
2678	367	\N	082000	石油与天然气工程	\N	0820	[]	[]	academic	2026-10-19 02:54:35.795063+08	t	\N
2679	367	\N	082400	船舶与海洋工程	\N	0824	[]	[]	academic	2026-10-19 02:54:35.795065+08	t	\N
2680	367	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:54:35.795067+08	t	\N
2681	367	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:54:35.795069+08	t	\N
2682	367	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:54:35.795071+08	t	\N
2683	367	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:54:35.795074+08	t	\N
2684	367	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:54:35.795076+08	t	\N
2685	367	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:54:35.795078+08	t	\N
2686	367	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 02:54:35.79508+08	t	\N
2687	367	\N	070703	海洋生物学	\N	0707	[]	[]	academic	2026-10-19 02:54:35.795081+08	t	\N
2688	368	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:54:42.519795+08	t	\N
2689	368	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:54:42.519801+08	t	\N
2690	368	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:54:42.519803+08	t	\N
2691	368	\N	082900	林业工程	\N	0829	[]	[]	academic	2026-10-19 02:54:42.519804+08	t	\N
2692	368	\N	0829J1	竹业科学与技术	\N	0829	[]	[]	academic	2026-10-19 02:54:42.519806+08	t	\N
2693	368	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:54:42.519807+08	t	\N
2694	368	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:54:42.519808+08	t	\N
2695	368	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:54:42.51981+08	t	\N
2696	368	\N	085300	城乡规划	\N	0853	[]	[]	professional	2026-10-19 02:54:42.519811+08	t	\N
2697	368	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:54:42.519812+08	t	\N
2698	368	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:54:42.519814+08	t	\N
2699	368	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:54:42.519815+08	t	\N
2700	368	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:54:42.519817+08	t	\N
2701	368	\N	0713J1	竹业科学与技术	\N	0713	[]	[]	academic	2026-10-19 02:54:42.519818+08	t	\N
2702	369	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 02:54:48.680841+08	t	\N
2703	369	\N	0831Z2	内镜技术与工程学	\N	0831	[]	[]	academic	2026-10-19 02:54:48.680843+08	t	\N
2704	369	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 02:54:48.680844+08	t	\N
2705	369	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:54:48.680844+08	t	\N
2706	369	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:54:48.680845+08	t	\N
2707	370	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:54:56.217214+08	t	\N
2708	371	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:55:02.869113+08	t	\N
2709	371	\N	0802Z1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 02:55:02.869116+08	t	\N
2710	371	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:55:02.869117+08	t	\N
2711	371	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:55:02.869117+08	t	\N
2712	371	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:55:02.869118+08	t	\N
2713	371	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:55:02.869118+08	t	\N
2714	371	\N	0812Z2	智能交通技术	\N	0812	[]	[]	academic	2026-10-19 02:55:02.869119+08	t	\N
2715	371	\N	0812Z3	低空技术与工程	\N	0812	[]	[]	academic	2026-10-19 02:55:02.869119+08	t	\N
2716	371	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:55:02.869119+08	t	\N
2717	371	\N	085300	城乡规划	\N	0853	[]	[]	professional	2026-10-19 02:55:02.86912+08	t	\N
2718	371	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:55:02.86912+08	t	\N
2719	371	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:55:02.869121+08	t	\N
2720	371	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:55:02.869121+08	t	\N
2721	371	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 02:55:02.869121+08	t	\N
2722	371	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 02:55:02.869122+08	t	\N
2723	371	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 02:55:02.869122+08	t	\N
2724	371	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:55:02.869123+08	t	\N
2725	371	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:55:02.869123+08	t	\N
2726	372	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:55:09.837186+08	t	\N
2727	372	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:55:09.837193+08	t	\N
2728	372	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:55:09.837195+08	t	\N
2729	372	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:55:09.837197+08	t	\N
2730	372	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:55:09.837198+08	t	\N
2731	372	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:55:09.837199+08	t	\N
2732	372	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:55:09.837201+08	t	\N
2733	372	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:55:09.837203+08	t	\N
2734	372	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:55:09.837204+08	t	\N
2735	372	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:55:09.837206+08	t	\N
2736	372	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:55:09.837207+08	t	\N
2737	372	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:55:09.837208+08	t	\N
2738	372	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:55:09.837209+08	t	\N
2739	372	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:55:09.837211+08	t	\N
2740	372	\N	0710Z1	衰老生物学	\N	0710	[]	[]	academic	2026-10-19 02:55:09.837212+08	t	\N
2741	372	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:55:09.837213+08	t	\N
2742	372	\N	0713Z1	生态信息科学	\N	0713	[]	[]	academic	2026-10-19 02:55:09.837215+08	t	\N
2743	372	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 02:55:09.837216+08	t	\N
2744	373	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:55:16.541476+08	t	\N
2745	373	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:55:16.541485+08	t	\N
2746	373	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:55:16.541489+08	t	\N
2747	373	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 02:55:16.541491+08	t	\N
2748	373	\N	085509	智能制造技术	\N	0855	[]	[]	professional	2026-10-19 02:55:16.541494+08	t	\N
2749	373	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 02:55:16.541496+08	t	\N
2750	373	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 02:55:16.541498+08	t	\N
2751	373	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 02:55:16.5415+08	t	\N
2752	373	\N	085702	安全工程	\N	0857	[]	[]	professional	2026-10-19 02:55:16.541502+08	t	\N
2753	373	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 02:55:16.541504+08	t	\N
2754	373	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:55:16.541506+08	t	\N
2755	373	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:55:16.541508+08	t	\N
2756	374	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:55:23.48999+08	t	\N
2757	374	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:55:23.489999+08	t	\N
2758	374	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:55:23.490003+08	t	\N
2759	374	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 02:55:23.490005+08	t	\N
2760	374	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:55:23.490008+08	t	\N
2761	374	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:55:23.49001+08	t	\N
2762	375	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:55:30.522644+08	t	\N
2763	375	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 02:55:30.522646+08	t	\N
2764	376	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:55:36.479522+08	t	\N
2765	376	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:55:36.479524+08	t	\N
2766	376	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:55:36.479525+08	t	\N
2767	376	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 02:55:36.479525+08	t	\N
2768	376	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:55:36.479526+08	t	\N
2769	377	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 02:55:42.918028+08	t	\N
2770	377	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 02:55:42.918034+08	t	\N
2771	377	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 02:55:42.918036+08	t	\N
2772	377	\N	085901	土木工程	\N	0859	[]	[]	professional	2026-10-19 02:55:42.918037+08	t	\N
2773	377	\N	086100	交通运输	\N	0861	[]	[]	professional	2026-10-19 02:55:42.918039+08	t	\N
2774	379	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:55:56.770369+08	t	\N
2775	379	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:55:56.770377+08	t	\N
2776	379	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:55:56.770379+08	t	\N
2777	379	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 02:55:56.770381+08	t	\N
2778	380	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:56:03.577366+08	t	\N
2779	381	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 02:56:09.874745+08	t	\N
2780	381	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:56:09.874751+08	t	\N
2781	381	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:56:09.874752+08	t	\N
2782	381	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:56:09.874754+08	t	\N
2783	383	\N	081505	港口、海岸及近海工程	\N	0815	[]	[]	academic	2026-10-19 02:56:21.996749+08	t	\N
2784	383	\N	081802	地球探测与信息技术	\N	0818	[]	[]	academic	2026-10-19 02:56:21.996752+08	t	\N
2785	383	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:56:21.996752+08	t	\N
2786	383	\N	070701	物理海洋学	\N	0707	[]	[]	academic	2026-10-19 02:56:21.996753+08	t	\N
2787	383	\N	070702	海洋化学	\N	0707	[]	[]	academic	2026-10-19 02:56:21.996753+08	t	\N
2788	383	\N	070703	海洋生物学	\N	0707	[]	[]	academic	2026-10-19 02:56:21.996754+08	t	\N
2789	383	\N	070704	海洋地质	\N	0707	[]	[]	academic	2026-10-19 02:56:21.996754+08	t	\N
2790	384	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:56:28.309714+08	t	\N
2791	384	\N	082403	水声工程	\N	0824	[]	[]	academic	2026-10-19 02:56:28.309717+08	t	\N
2792	385	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:56:35.295746+08	t	\N
2793	385	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:56:35.295755+08	t	\N
2794	385	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:56:35.295759+08	t	\N
2795	385	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 02:56:35.295761+08	t	\N
2796	385	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:56:35.295763+08	t	\N
2797	385	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 02:56:35.295765+08	t	\N
2798	385	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:56:35.295767+08	t	\N
2799	385	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:56:35.295769+08	t	\N
2800	385	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:56:35.295771+08	t	\N
2801	385	\N	086003	食品工程	\N	0860	[]	[]	professional	2026-10-19 02:56:35.295773+08	t	\N
2802	385	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:56:35.295775+08	t	\N
2803	385	\N	0775Z1	计算科学	\N	0775	[]	[]	academic	2026-10-19 02:56:35.295776+08	t	\N
2804	386	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:56:41.986708+08	t	\N
2805	386	\N	0802Z3	智能制造与控制工程	\N	0802	[]	[]	academic	2026-10-19 02:56:41.98671+08	t	\N
2806	386	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:56:41.986711+08	t	\N
2807	386	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:56:41.986711+08	t	\N
2808	386	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:56:41.986712+08	t	\N
2809	386	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:56:41.986712+08	t	\N
2810	386	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:56:41.986713+08	t	\N
2811	386	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 02:56:41.986713+08	t	\N
2812	386	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:56:41.986714+08	t	\N
2813	386	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:56:41.986714+08	t	\N
2814	386	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:56:41.986714+08	t	\N
2815	386	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:56:41.986715+08	t	\N
2816	387	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:56:48.338913+08	t	\N
2817	387	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:56:48.338915+08	t	\N
2818	387	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:56:48.338916+08	t	\N
2819	387	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:56:48.338917+08	t	\N
2820	387	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:56:48.338917+08	t	\N
2821	387	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:56:48.338917+08	t	\N
2822	387	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:56:48.338918+08	t	\N
2823	387	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:56:48.338918+08	t	\N
2824	387	\N	083700	安全科学与工程	\N	0837	[]	[]	academic	2026-10-19 02:56:48.338919+08	t	\N
2825	387	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:56:48.338919+08	t	\N
2826	387	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:56:48.338919+08	t	\N
2827	387	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:56:48.33892+08	t	\N
2828	388	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:56:54.814464+08	t	\N
2829	388	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:56:54.814474+08	t	\N
2830	388	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:56:54.814477+08	t	\N
2831	388	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:56:54.814479+08	t	\N
2832	388	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 02:56:54.814481+08	t	\N
2833	388	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 02:56:54.814483+08	t	\N
2834	389	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:57:01.468135+08	t	\N
2835	389	\N	0812Z1	低空技术与工程	\N	0812	[]	[]	academic	2026-10-19 02:57:01.468138+08	t	\N
2836	389	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 02:57:01.468138+08	t	\N
2837	389	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:57:01.468139+08	t	\N
2838	389	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:57:01.468139+08	t	\N
2839	389	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:57:01.46814+08	t	\N
2840	389	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 02:57:01.46814+08	t	\N
2841	389	\N	085510	机器人工程	\N	0855	[]	[]	professional	2026-10-19 02:57:01.46814+08	t	\N
2842	389	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:57:01.468141+08	t	\N
2843	389	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 02:57:01.468141+08	t	\N
2844	389	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:57:01.468142+08	t	\N
2845	390	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:57:08.925258+08	t	\N
2846	390	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:57:08.925263+08	t	\N
2847	390	\N	0714Z5	数理统计学	\N	0714	[]	[]	academic	2026-10-19 02:57:08.925265+08	t	\N
2848	390	\N	0714Z7	大数据统计方法与应用	\N	0714	[]	[]	academic	2026-10-19 02:57:08.925266+08	t	\N
2849	392	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:57:23.96485+08	t	\N
2850	392	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:57:23.964852+08	t	\N
2851	392	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:57:23.964853+08	t	\N
2852	392	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:57:23.964853+08	t	\N
2853	392	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:57:23.964854+08	t	\N
2854	392	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:57:23.964854+08	t	\N
2855	392	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:57:23.964855+08	t	\N
2856	392	\N	081701	化学工程	\N	0817	[]	[]	academic	2026-10-19 02:57:23.964855+08	t	\N
2857	392	\N	081702	化学工艺	\N	0817	[]	[]	academic	2026-10-19 02:57:23.964855+08	t	\N
2858	392	\N	081704	应用化学	\N	0817	[]	[]	academic	2026-10-19 02:57:23.964856+08	t	\N
2859	392	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:57:23.964856+08	t	\N
2860	392	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:57:23.964857+08	t	\N
2861	392	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 02:57:23.964857+08	t	\N
2862	392	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 02:57:23.964857+08	t	\N
2863	392	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 02:57:23.964858+08	t	\N
2864	392	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 02:57:23.964858+08	t	\N
2865	392	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 02:57:23.964859+08	t	\N
2866	392	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:57:23.964859+08	t	\N
2867	392	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:57:23.964859+08	t	\N
2868	392	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:57:23.96486+08	t	\N
2869	393	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:57:30.155056+08	t	\N
2870	393	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:57:30.155058+08	t	\N
2871	393	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:57:30.155059+08	t	\N
2872	393	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:57:30.155059+08	t	\N
2873	393	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:57:30.15506+08	t	\N
2874	393	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:57:30.15506+08	t	\N
2875	393	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:57:30.15506+08	t	\N
2876	393	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:57:30.155061+08	t	\N
2877	393	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:57:30.155061+08	t	\N
2878	393	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:57:30.155062+08	t	\N
2879	393	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:57:30.155062+08	t	\N
2880	393	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:57:30.155063+08	t	\N
2881	393	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:57:30.155063+08	t	\N
2882	393	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 02:57:30.155064+08	t	\N
2883	393	\N	070600	大气科学	\N	0706	[]	[]	academic	2026-10-19 02:57:30.155064+08	t	\N
2884	393	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 02:57:30.155064+08	t	\N
2885	393	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 02:57:30.155065+08	t	\N
2886	393	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:57:30.155065+08	t	\N
2887	393	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 02:57:30.155066+08	t	\N
2888	393	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:57:30.155066+08	t	\N
2889	394	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:57:38.050977+08	t	\N
2890	394	\N	080201	机械制造及其自动化	\N	0802	[]	[]	academic	2026-10-19 02:57:38.050984+08	t	\N
2891	394	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 02:57:38.050986+08	t	\N
2892	394	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 02:57:38.050988+08	t	\N
2893	394	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 02:57:38.05099+08	t	\N
2894	394	\N	0802Z1	工业工程	\N	0802	[]	[]	academic	2026-10-19 02:57:38.050992+08	t	\N
2895	394	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:57:38.050993+08	t	\N
2896	394	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:57:38.050995+08	t	\N
2897	394	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:57:38.050996+08	t	\N
2898	394	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 02:57:38.050997+08	t	\N
2899	394	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:57:38.050998+08	t	\N
2900	394	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:57:38.051+08	t	\N
2901	394	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:57:38.051001+08	t	\N
2902	394	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 02:57:38.051002+08	t	\N
2903	394	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 02:57:38.051004+08	t	\N
2904	394	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:57:38.051005+08	t	\N
2905	395	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:57:44.233541+08	t	\N
2906	395	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 02:57:44.233543+08	t	\N
2907	395	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:57:44.233543+08	t	\N
2908	395	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 02:57:44.233544+08	t	\N
2909	395	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 02:57:44.233544+08	t	\N
2910	395	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:57:44.233545+08	t	\N
2911	395	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:57:44.233545+08	t	\N
2912	395	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:57:44.233546+08	t	\N
2913	395	\N	081402	结构工程	\N	0814	[]	[]	academic	2026-10-19 02:57:44.233546+08	t	\N
2914	395	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 02:57:44.233546+08	t	\N
2915	395	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:57:44.233547+08	t	\N
2916	395	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:57:44.233547+08	t	\N
2917	396	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 02:57:51.632256+08	t	\N
2918	396	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:57:51.632266+08	t	\N
2919	396	\N	0802J1	智能制造工程	\N	0802	[]	[]	academic	2026-10-19 02:57:51.63227+08	t	\N
2920	396	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 02:57:51.632272+08	t	\N
2921	396	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:57:51.632275+08	t	\N
2922	396	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:57:51.632277+08	t	\N
2923	396	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:57:51.632279+08	t	\N
2924	396	\N	0811Z1	光电系统与控制	\N	0811	[]	[]	academic	2026-10-19 02:57:51.632281+08	t	\N
2925	396	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:57:51.632282+08	t	\N
2926	396	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:57:51.632284+08	t	\N
2927	396	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:57:51.632286+08	t	\N
2928	397	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:57:58.418068+08	t	\N
2929	397	\N	0802J1	人工智能	\N	0802	[]	[]	academic	2026-10-19 02:57:58.418073+08	t	\N
2930	397	\N	0802J7	仿生与人形机器人	\N	0802	[]	[]	academic	2026-10-19 02:57:58.418075+08	t	\N
2931	397	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:57:58.418077+08	t	\N
2932	397	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 02:57:58.418078+08	t	\N
2933	397	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:57:58.418079+08	t	\N
2934	397	\N	0811J3	低空技术与工程	\N	0811	[]	[]	academic	2026-10-19 02:57:58.418081+08	t	\N
2935	397	\N	082100	纺织科学与工程	\N	0821	[]	[]	academic	2026-10-19 02:57:58.418083+08	t	\N
2936	397	\N	0821J8	柔性功能电子器件与系统	\N	0821	[]	[]	academic	2026-10-19 02:57:58.418084+08	t	\N
2937	397	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:57:58.418086+08	t	\N
2938	397	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:57:58.418087+08	t	\N
2939	397	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:57:58.418088+08	t	\N
2940	397	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 02:57:58.41809+08	t	\N
2941	398	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 02:58:05.636302+08	t	\N
2942	398	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:58:05.636305+08	t	\N
2943	398	\N	082100	纺织科学与工程	\N	0821	[]	[]	academic	2026-10-19 02:58:05.636305+08	t	\N
2944	398	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 02:58:05.636306+08	t	\N
2945	398	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 02:58:05.636306+08	t	\N
2946	398	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 02:58:05.636307+08	t	\N
2947	398	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 02:58:05.636308+08	t	\N
2948	398	\N	082900	林业工程	\N	0829	[]	[]	academic	2026-10-19 02:58:05.636308+08	t	\N
2949	398	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:58:05.636308+08	t	\N
2950	398	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:58:05.636309+08	t	\N
2951	398	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:58:05.636309+08	t	\N
2952	398	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:58:05.63631+08	t	\N
2953	398	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:58:05.63631+08	t	\N
2954	399	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 02:58:11.865101+08	t	\N
2955	399	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 02:58:11.865104+08	t	\N
2956	399	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 02:58:11.865104+08	t	\N
2957	399	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 02:58:11.865105+08	t	\N
2958	399	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 02:58:11.865105+08	t	\N
2959	399	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 02:58:11.865106+08	t	\N
2960	399	\N	0710Z1	免疫生物学	\N	0710	[]	[]	academic	2026-10-19 02:58:11.865106+08	t	\N
2961	400	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:58:19.567226+08	t	\N
2962	401	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:58:26.007732+08	t	\N
2963	401	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:58:26.007737+08	t	\N
2964	401	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:58:26.007739+08	t	\N
2965	402	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:58:31.825088+08	t	\N
2966	403	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:58:39.089403+08	t	\N
2967	403	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:58:39.089409+08	t	\N
2968	403	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:58:39.089411+08	t	\N
2969	403	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:58:39.089412+08	t	\N
2970	403	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:58:39.089414+08	t	\N
2971	403	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:58:39.089415+08	t	\N
2972	404	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:58:45.060054+08	t	\N
2973	404	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:58:45.060056+08	t	\N
2974	404	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:58:45.060057+08	t	\N
2975	405	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:58:52.099627+08	t	\N
2976	405	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:58:52.09963+08	t	\N
2977	405	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:58:52.09963+08	t	\N
2978	405	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 02:58:52.099631+08	t	\N
2979	405	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 02:58:52.099631+08	t	\N
2980	405	\N	086003	食品工程	\N	0860	[]	[]	professional	2026-10-19 02:58:52.099631+08	t	\N
2981	406	\N	081900	矿业工程	\N	0819	[]	[]	academic	2026-10-19 02:58:59.040088+08	t	\N
2982	406	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:58:59.04009+08	t	\N
2983	408	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:59:12.263065+08	t	\N
2984	408	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 02:59:12.263074+08	t	\N
2985	408	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:59:12.263077+08	t	\N
2986	408	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:59:12.263079+08	t	\N
2987	408	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 02:59:12.263082+08	t	\N
2988	408	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:59:12.263083+08	t	\N
2989	408	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:59:12.263085+08	t	\N
2990	408	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 02:59:12.263087+08	t	\N
2991	408	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:59:12.263089+08	t	\N
2992	408	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:59:12.263091+08	t	\N
2993	408	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:59:12.263093+08	t	\N
2994	408	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:59:12.263095+08	t	\N
2995	408	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:59:12.263097+08	t	\N
2996	408	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 02:59:12.263099+08	t	\N
2997	408	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 02:59:12.263101+08	t	\N
2998	408	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 02:59:12.263103+08	t	\N
2999	408	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 02:59:12.263105+08	t	\N
3000	408	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 02:59:12.263107+08	t	\N
3001	408	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 02:59:12.263109+08	t	\N
3002	408	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 02:59:12.263111+08	t	\N
3003	409	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:59:20.238611+08	t	\N
3004	409	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:59:20.238617+08	t	\N
3005	409	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:59:20.238619+08	t	\N
3006	409	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:59:20.23862+08	t	\N
3007	409	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:59:20.238622+08	t	\N
3008	409	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 02:59:20.238623+08	t	\N
3009	410	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:59:28.078391+08	t	\N
3010	410	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 02:59:28.078555+08	t	\N
3011	410	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 02:59:28.078561+08	t	\N
3012	410	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 02:59:28.078563+08	t	\N
3013	410	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 02:59:28.078566+08	t	\N
3014	410	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:59:28.078568+08	t	\N
3015	410	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:59:28.07857+08	t	\N
3016	410	\N	083700	安全科学与工程	\N	0837	[]	[]	academic	2026-10-19 02:59:28.078572+08	t	\N
3017	410	\N	085100	建筑	\N	0851	[]	[]	professional	2026-10-19 02:59:28.078574+08	t	\N
3018	410	\N	085300	城乡规划	\N	0853	[]	[]	professional	2026-10-19 02:59:28.078576+08	t	\N
3019	410	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:59:28.078578+08	t	\N
3020	411	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:59:34.733218+08	t	\N
3021	411	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:59:34.733231+08	t	\N
3022	411	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:59:34.733234+08	t	\N
3023	411	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:59:34.733236+08	t	\N
3024	411	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:59:34.733239+08	t	\N
3025	411	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:59:34.733241+08	t	\N
3026	411	\N	086003	食品工程	\N	0860	[]	[]	professional	2026-10-19 02:59:34.733243+08	t	\N
3027	411	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 02:59:34.733245+08	t	\N
3028	412	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 02:59:41.211002+08	t	\N
3029	412	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 02:59:41.211011+08	t	\N
3030	412	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:59:41.211015+08	t	\N
3031	412	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 02:59:41.211017+08	t	\N
3032	412	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:59:41.211019+08	t	\N
3033	412	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:59:41.211021+08	t	\N
3034	412	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:59:41.211024+08	t	\N
3035	413	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:59:48.543058+08	t	\N
3036	413	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 02:59:48.54306+08	t	\N
3037	413	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:59:48.543061+08	t	\N
3038	413	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:59:48.543062+08	t	\N
3039	413	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 02:59:48.543062+08	t	\N
3040	413	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:59:48.543062+08	t	\N
3041	413	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 02:59:48.543063+08	t	\N
3042	413	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 02:59:48.543063+08	t	\N
3043	413	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 02:59:48.543064+08	t	\N
3044	413	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:59:48.543064+08	t	\N
3045	413	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:59:48.543065+08	t	\N
3046	413	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 02:59:48.543065+08	t	\N
3047	413	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:59:48.543066+08	t	\N
3048	413	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 02:59:48.543066+08	t	\N
3049	414	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 02:59:55.282255+08	t	\N
3050	414	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 02:59:55.282258+08	t	\N
3051	414	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 02:59:55.282259+08	t	\N
3052	414	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 02:59:55.282259+08	t	\N
3053	414	\N	0835J1	人工智能	\N	0835	[]	[]	academic	2026-10-19 02:59:55.28226+08	t	\N
3054	414	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 02:59:55.28226+08	t	\N
3055	414	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 02:59:55.282261+08	t	\N
3056	414	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 02:59:55.282261+08	t	\N
3057	414	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 02:59:55.282262+08	t	\N
3058	414	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 02:59:55.282262+08	t	\N
3059	414	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 02:59:55.282263+08	t	\N
3060	414	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 02:59:55.282263+08	t	\N
3061	414	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 02:59:55.282264+08	t	\N
3062	415	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:00:01.812585+08	t	\N
3063	415	\N	0802J1	智能仪器与装备	\N	0802	[]	[]	academic	2026-10-19 03:00:01.812594+08	t	\N
3064	415	\N	0802J6	转化医学	\N	0802	[]	[]	academic	2026-10-19 03:00:01.812597+08	t	\N
3065	415	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:00:01.812599+08	t	\N
3066	415	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:00:01.812602+08	t	\N
3067	415	\N	080903	微电子学与固体电子学	\N	0809	[]	[]	academic	2026-10-19 03:00:01.812604+08	t	\N
3068	415	\N	0809Z2	光电工程	\N	0809	[]	[]	academic	2026-10-19 03:00:01.812606+08	t	\N
3069	415	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:00:01.812608+08	t	\N
3070	415	\N	0810J2	低空经济	\N	0810	[]	[]	academic	2026-10-19 03:00:01.81261+08	t	\N
3071	415	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:00:01.812612+08	t	\N
3072	415	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:00:01.812615+08	t	\N
3073	415	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:00:01.812617+08	t	\N
3074	415	\N	0702J4	健康大数据与智能医学	\N	0702	[]	[]	academic	2026-10-19 03:00:01.812619+08	t	\N
3075	415	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:00:01.812621+08	t	\N
3076	415	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 03:00:01.812623+08	t	\N
3077	415	\N	070701	物理海洋学	\N	0707	[]	[]	academic	2026-10-19 03:00:01.812624+08	t	\N
3078	415	\N	070702	海洋化学	\N	0707	[]	[]	academic	2026-10-19 03:00:01.812626+08	t	\N
3079	415	\N	070703	海洋生物学	\N	0707	[]	[]	academic	2026-10-19 03:00:01.812628+08	t	\N
3080	415	\N	070704	海洋地质	\N	0707	[]	[]	academic	2026-10-19 03:00:01.81263+08	t	\N
3081	415	\N	0707J3	海洋事务	\N	0707	[]	[]	academic	2026-10-19 03:00:01.812632+08	t	\N
3082	416	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:00:08.298185+08	t	\N
3083	416	\N	0802Z1	智能制造工程	\N	0802	[]	[]	academic	2026-10-19 03:00:08.298188+08	t	\N
3084	416	\N	0802Z2	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:00:08.298189+08	t	\N
3085	416	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:00:08.298189+08	t	\N
3086	416	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:00:08.29819+08	t	\N
3087	416	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:00:08.29819+08	t	\N
3088	416	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:00:08.298191+08	t	\N
3089	416	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:00:08.298191+08	t	\N
3090	416	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:00:08.298191+08	t	\N
3091	416	\N	085100	建筑	\N	0851	[]	[]	professional	2026-10-19 03:00:08.298192+08	t	\N
3092	416	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:00:08.298192+08	t	\N
3093	416	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:00:08.298193+08	t	\N
3094	416	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:00:08.298193+08	t	\N
3095	416	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:00:08.298194+08	t	\N
3096	416	\N	078000	药学	\N	0780	[]	[]	academic	2026-10-19 03:00:08.298194+08	t	\N
3097	417	\N	080101	一般力学与力学基础	\N	0801	[]	[]	academic	2026-10-19 03:00:13.973235+08	t	\N
3098	417	\N	080102	固体力学	\N	0801	[]	[]	academic	2026-10-19 03:00:13.973238+08	t	\N
3099	417	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 03:00:13.973238+08	t	\N
3100	417	\N	080201	机械制造及其自动化	\N	0802	[]	[]	academic	2026-10-19 03:00:13.973239+08	t	\N
3101	417	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 03:00:13.973239+08	t	\N
3102	417	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 03:00:13.973239+08	t	\N
3103	417	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:00:13.97324+08	t	\N
3104	417	\N	0802Z1	精密机械及测试	\N	0802	[]	[]	academic	2026-10-19 03:00:13.97324+08	t	\N
3105	417	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:00:13.973241+08	t	\N
3106	417	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:00:13.973241+08	t	\N
3107	417	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:00:13.973242+08	t	\N
3108	417	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:00:13.973242+08	t	\N
3109	417	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:00:13.973243+08	t	\N
3110	417	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 03:00:13.973243+08	t	\N
3111	417	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:00:13.973243+08	t	\N
3112	417	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:00:13.973244+08	t	\N
3113	417	\N	0703J1	新能源材料	\N	0703	[]	[]	academic	2026-10-19 03:00:13.973244+08	t	\N
3114	417	\N	0703Z1	材料化学	\N	0703	[]	[]	academic	2026-10-19 03:00:13.973245+08	t	\N
3115	417	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:00:13.973245+08	t	\N
3116	417	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:00:13.973246+08	t	\N
3117	418	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:00:19.884608+08	t	\N
3118	418	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:00:19.884613+08	t	\N
3119	418	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:00:19.884615+08	t	\N
3120	418	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:00:19.884617+08	t	\N
3121	418	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 03:00:19.884618+08	t	\N
3122	418	\N	0823Z1	低空技术与工程	\N	0823	[]	[]	academic	2026-10-19 03:00:19.884619+08	t	\N
3123	418	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:00:19.884621+08	t	\N
3124	418	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:00:19.884622+08	t	\N
3125	418	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:00:19.884623+08	t	\N
3126	418	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:00:19.884624+08	t	\N
3127	419	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:00:26.596523+08	t	\N
3128	419	\N	0802J6	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:00:26.596581+08	t	\N
3129	419	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:00:26.596613+08	t	\N
3130	419	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:00:26.596643+08	t	\N
3131	419	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 03:00:26.596672+08	t	\N
3132	419	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 03:00:26.596674+08	t	\N
3133	419	\N	082901	森林工程	\N	0829	[]	[]	academic	2026-10-19 03:00:26.596675+08	t	\N
3134	419	\N	082902	木材科学与技术	\N	0829	[]	[]	academic	2026-10-19 03:00:26.596676+08	t	\N
3135	419	\N	082903	林产化学加工工程	\N	0829	[]	[]	academic	2026-10-19 03:00:26.596677+08	t	\N
3136	419	\N	0829Z1	生物质能源与材料	\N	0829	[]	[]	academic	2026-10-19 03:00:26.596705+08	t	\N
3137	419	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:00:26.596736+08	t	\N
3138	419	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:00:26.597207+08	t	\N
3139	419	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 03:00:26.601276+08	t	\N
3140	419	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:00:26.601281+08	t	\N
3141	419	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:00:26.601284+08	t	\N
3142	419	\N	0713J3	菌草学	\N	0713	[]	[]	academic	2026-10-19 03:00:26.601286+08	t	\N
3143	419	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:00:26.601288+08	t	\N
3144	420	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:00:33.738634+08	t	\N
3145	420	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:00:33.738643+08	t	\N
3146	420	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 03:00:33.738646+08	t	\N
3147	420	\N	0823J2	低空技术与工程	\N	0823	[]	[]	academic	2026-10-19 03:00:33.738649+08	t	\N
3148	420	\N	082400	船舶与海洋工程	\N	0824	[]	[]	academic	2026-10-19 03:00:33.738651+08	t	\N
3149	420	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:00:33.738653+08	t	\N
3150	420	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:00:33.738655+08	t	\N
3151	420	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:00:33.738657+08	t	\N
3152	420	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:00:33.738658+08	t	\N
3153	420	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:00:33.73866+08	t	\N
3154	420	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:00:33.738662+08	t	\N
3155	420	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:00:33.738664+08	t	\N
3156	421	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:00:40.09507+08	t	\N
3157	421	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:00:40.095076+08	t	\N
3158	421	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:00:40.095079+08	t	\N
3159	421	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 03:00:40.095081+08	t	\N
3160	421	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:00:40.095082+08	t	\N
3161	421	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:00:40.095083+08	t	\N
3162	421	\N	071011	生物物理学	\N	0710	[]	[]	academic	2026-10-19 03:00:40.095085+08	t	\N
3163	421	\N	0710Z1	生物信息学	\N	0710	[]	[]	academic	2026-10-19 03:00:40.095086+08	t	\N
3164	423	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:00:54.514976+08	t	\N
3165	423	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:00:54.514982+08	t	\N
3166	423	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:00:54.514985+08	t	\N
3167	423	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:00:54.514986+08	t	\N
3168	423	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 03:00:54.514988+08	t	\N
3169	423	\N	0830Z1	环境健康	\N	0830	[]	[]	academic	2026-10-19 03:00:54.514989+08	t	\N
3170	423	\N	083600	生物工程	\N	0836	[]	[]	academic	2026-10-19 03:00:54.514991+08	t	\N
3171	423	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:00:54.514992+08	t	\N
3172	423	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:00:54.514993+08	t	\N
3173	423	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:00:54.514995+08	t	\N
3174	423	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:00:54.514996+08	t	\N
3175	423	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:00:54.514997+08	t	\N
3176	423	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:00:54.514998+08	t	\N
3177	423	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:00:54.515+08	t	\N
3178	423	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:00:54.515001+08	t	\N
3179	423	\N	0702Z1	能源与材料物理	\N	0702	[]	[]	academic	2026-10-19 03:00:54.515002+08	t	\N
3180	423	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:00:54.515004+08	t	\N
3181	423	\N	0703J1	资源循环科学与工程	\N	0703	[]	[]	academic	2026-10-19 03:00:54.515005+08	t	\N
3182	423	\N	0703Z2	环境化学	\N	0703	[]	[]	academic	2026-10-19 03:00:54.515006+08	t	\N
3183	423	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:00:54.515007+08	t	\N
3184	424	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:01:00.141548+08	t	\N
3185	424	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:01:00.141554+08	t	\N
3186	424	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:01:00.141556+08	t	\N
3187	424	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:01:00.141557+08	t	\N
3188	424	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:01:00.141558+08	t	\N
3189	424	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:01:00.14156+08	t	\N
3190	424	\N	085704	测绘工程	\N	0857	[]	[]	professional	2026-10-19 03:01:00.141562+08	t	\N
3191	425	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:01:07.081112+08	t	\N
3192	426	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:01:14.250228+08	t	\N
3193	426	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:01:14.25023+08	t	\N
3194	426	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:01:14.250231+08	t	\N
3195	428	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:01:26.018753+08	t	\N
3196	428	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:01:26.018759+08	t	\N
3197	428	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:01:26.01876+08	t	\N
3198	428	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:01:26.018762+08	t	\N
3199	428	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:01:26.018763+08	t	\N
3200	428	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:01:26.018765+08	t	\N
3201	428	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:01:26.018766+08	t	\N
3202	428	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:01:26.018767+08	t	\N
3203	428	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:01:26.018769+08	t	\N
3204	428	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:01:26.01877+08	t	\N
3205	428	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:01:26.018771+08	t	\N
3206	429	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:01:32.196892+08	t	\N
3207	429	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:01:32.196898+08	t	\N
3208	429	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:01:32.1969+08	t	\N
3209	429	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:01:32.196901+08	t	\N
3210	429	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 03:01:32.196903+08	t	\N
3211	429	\N	085509	智能制造技术	\N	0855	[]	[]	professional	2026-10-19 03:01:32.196904+08	t	\N
3212	429	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:01:32.196905+08	t	\N
3213	430	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:01:38.8469+08	t	\N
3214	430	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:01:38.846904+08	t	\N
3215	430	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:01:38.846904+08	t	\N
3216	430	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:01:38.846905+08	t	\N
3217	431	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:01:46.243804+08	t	\N
3218	431	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:01:46.243808+08	t	\N
3219	431	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:01:46.24381+08	t	\N
3220	431	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:01:46.243811+08	t	\N
3221	431	\N	085407	仪器仪表工程	\N	0854	[]	[]	professional	2026-10-19 03:01:46.243812+08	t	\N
3222	431	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:01:46.243813+08	t	\N
3223	431	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:01:46.243814+08	t	\N
3224	431	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:01:46.243815+08	t	\N
3225	431	\N	085509	智能制造技术	\N	0855	[]	[]	professional	2026-10-19 03:01:46.243815+08	t	\N
3226	431	\N	085510	机器人工程	\N	0855	[]	[]	professional	2026-10-19 03:01:46.243816+08	t	\N
3227	431	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:01:46.243817+08	t	\N
3228	431	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:01:46.243818+08	t	\N
3229	431	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:01:46.243819+08	t	\N
3230	434	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:02:05.192297+08	t	\N
3231	434	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:02:05.192305+08	t	\N
3232	434	\N	070701	物理海洋学	\N	0707	[]	[]	academic	2026-10-19 03:02:05.192308+08	t	\N
3233	434	\N	070702	海洋化学	\N	0707	[]	[]	academic	2026-10-19 03:02:05.19231+08	t	\N
3234	434	\N	070703	海洋生物学	\N	0707	[]	[]	academic	2026-10-19 03:02:05.192312+08	t	\N
3235	434	\N	070704	海洋地质	\N	0707	[]	[]	academic	2026-10-19 03:02:05.192314+08	t	\N
3236	435	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:02:11.25179+08	t	\N
3237	435	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 03:02:11.251801+08	t	\N
3238	435	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:02:11.251804+08	t	\N
3239	435	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:02:11.251807+08	t	\N
3240	435	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:02:11.251808+08	t	\N
3241	435	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:02:11.25181+08	t	\N
3242	435	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:02:11.251812+08	t	\N
3243	435	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:02:11.251814+08	t	\N
3244	435	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:02:11.251816+08	t	\N
3245	435	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:02:11.251818+08	t	\N
3246	435	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:02:11.25182+08	t	\N
3247	435	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:02:11.251821+08	t	\N
3248	435	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:02:11.251823+08	t	\N
3249	435	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:02:11.251825+08	t	\N
3250	435	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:02:11.251827+08	t	\N
3251	435	\N	0701Z1	数理经济与数理金融	\N	0701	[]	[]	academic	2026-10-19 03:02:11.251829+08	t	\N
3252	435	\N	0701Z2	数学教育	\N	0701	[]	[]	academic	2026-10-19 03:02:11.251831+08	t	\N
3253	435	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:02:11.251833+08	t	\N
3254	435	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 03:02:11.251835+08	t	\N
3255	435	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:02:11.251837+08	t	\N
3256	436	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:02:17.681497+08	t	\N
3257	436	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:02:17.6815+08	t	\N
3258	436	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:02:17.681501+08	t	\N
3259	436	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:02:17.681501+08	t	\N
3260	436	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:02:17.681502+08	t	\N
3261	436	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:02:17.681502+08	t	\N
3262	436	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:02:17.681503+08	t	\N
3263	436	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:02:17.681503+08	t	\N
3264	436	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:02:17.681504+08	t	\N
3265	436	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:02:17.681504+08	t	\N
3266	436	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:02:17.681504+08	t	\N
3267	436	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:02:17.681505+08	t	\N
3268	436	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:02:17.681505+08	t	\N
3269	436	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 03:02:17.681506+08	t	\N
3270	436	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:02:17.681506+08	t	\N
3271	436	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:02:17.681507+08	t	\N
3272	436	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:02:17.681507+08	t	\N
3273	436	\N	077903	营养与食品卫生学	\N	0779	[]	[]	academic	2026-10-19 03:02:17.681508+08	t	\N
3274	437	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:02:24.227461+08	t	\N
3275	437	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:02:24.227463+08	t	\N
3276	437	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:02:24.227464+08	t	\N
3277	437	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:02:24.227464+08	t	\N
3278	437	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:02:24.227465+08	t	\N
3279	437	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:02:24.227465+08	t	\N
3280	437	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 03:02:24.227466+08	t	\N
3281	437	\N	081402	结构工程	\N	0814	[]	[]	academic	2026-10-19 03:02:24.227466+08	t	\N
3282	437	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 03:02:24.227466+08	t	\N
3283	437	\N	081404	供热、供燃气、通风及空调工程	\N	0814	[]	[]	academic	2026-10-19 03:02:24.227467+08	t	\N
3284	437	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:02:24.227467+08	t	\N
3285	437	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:02:24.227468+08	t	\N
3286	438	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:02:31.624259+08	t	\N
3287	438	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:02:31.624262+08	t	\N
3288	438	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:02:31.624263+08	t	\N
3289	438	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:02:31.624263+08	t	\N
3290	438	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:02:31.624264+08	t	\N
3291	438	\N	081800	地质资源与地质工程	\N	0818	[]	[]	academic	2026-10-19 03:02:31.624264+08	t	\N
3292	438	\N	081900	矿业工程	\N	0819	[]	[]	academic	2026-10-19 03:02:31.624265+08	t	\N
3293	438	\N	082700	核科学与技术	\N	0827	[]	[]	academic	2026-10-19 03:02:31.624265+08	t	\N
3294	438	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:02:31.624265+08	t	\N
3295	438	\N	085300	城乡规划	\N	0853	[]	[]	professional	2026-10-19 03:02:31.624266+08	t	\N
3296	438	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:02:31.624266+08	t	\N
3297	438	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:02:31.624267+08	t	\N
3298	438	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:02:31.624267+08	t	\N
3299	438	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 03:02:31.624268+08	t	\N
3300	438	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 03:02:31.624268+08	t	\N
3301	438	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:02:31.624269+08	t	\N
3302	438	\N	077300	材料科学与工程	\N	0773	[]	[]	academic	2026-10-19 03:02:31.624269+08	t	\N
3303	438	\N	077400	电子科学与技术	\N	0774	[]	[]	academic	2026-10-19 03:02:31.62427+08	t	\N
3304	438	\N	077600	环境科学与工程	\N	0776	[]	[]	academic	2026-10-19 03:02:31.62427+08	t	\N
3305	439	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:02:38.675445+08	t	\N
3306	439	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:02:38.675454+08	t	\N
3307	439	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:02:38.675457+08	t	\N
3308	439	\N	0804Z1	先进试验与测试	\N	0804	[]	[]	academic	2026-10-19 03:02:38.67546+08	t	\N
3309	439	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:02:38.675463+08	t	\N
3310	439	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:02:38.675465+08	t	\N
3311	439	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:02:38.675467+08	t	\N
3312	439	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:02:38.675469+08	t	\N
3313	439	\N	0812Z1	物联网技术	\N	0812	[]	[]	academic	2026-10-19 03:02:38.675471+08	t	\N
3314	439	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:02:38.675473+08	t	\N
3315	439	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:02:38.675475+08	t	\N
3316	439	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:02:38.675476+08	t	\N
3317	439	\N	077600	环境科学与工程	\N	0776	[]	[]	academic	2026-10-19 03:02:38.675478+08	t	\N
3318	440	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:02:45.134764+08	t	\N
3319	440	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:02:45.134766+08	t	\N
3320	440	\N	0805J2	稀土科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:02:45.134766+08	t	\N
3321	440	\N	0805Z1	稀金材料智能创制	\N	0805	[]	[]	academic	2026-10-19 03:02:45.134767+08	t	\N
3322	440	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 03:02:45.134767+08	t	\N
3323	440	\N	0806Z1	稀土工程	\N	0806	[]	[]	academic	2026-10-19 03:02:45.134768+08	t	\N
3324	440	\N	0806Z2	智能冶金科学与技术	\N	0806	[]	[]	academic	2026-10-19 03:02:45.134768+08	t	\N
3325	440	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:02:45.134769+08	t	\N
3326	440	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:02:45.134769+08	t	\N
3327	440	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:02:45.13477+08	t	\N
3328	440	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:02:45.13477+08	t	\N
3329	440	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:02:45.13477+08	t	\N
3330	441	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:02:52.954269+08	t	\N
3331	441	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:02:52.954271+08	t	\N
3332	441	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:02:52.954272+08	t	\N
3333	441	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:02:52.954272+08	t	\N
3334	441	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:02:52.954273+08	t	\N
3335	441	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:02:52.954273+08	t	\N
3336	441	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:02:52.954273+08	t	\N
3337	441	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:02:52.954274+08	t	\N
3338	441	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:02:52.954274+08	t	\N
3339	441	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:02:52.954275+08	t	\N
3340	441	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 03:02:52.954275+08	t	\N
3341	441	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:02:52.954276+08	t	\N
3342	441	\N	0714J1	大数据科学与应用	\N	0714	[]	[]	academic	2026-10-19 03:02:52.954276+08	t	\N
3343	442	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:02:58.445879+08	t	\N
3344	442	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 03:02:58.445881+08	t	\N
3345	442	\N	0828J3	农业人工智能	\N	0828	[]	[]	academic	2026-10-19 03:02:58.445882+08	t	\N
3346	442	\N	083201	食品科学	\N	0832	[]	[]	academic	2026-10-19 03:02:58.445882+08	t	\N
3347	442	\N	0832Z1	食品营养与安全	\N	0832	[]	[]	academic	2026-10-19 03:02:58.445883+08	t	\N
3348	442	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:02:58.445883+08	t	\N
3349	442	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:02:58.445884+08	t	\N
3350	442	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:02:58.445884+08	t	\N
3351	442	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:02:58.445885+08	t	\N
3352	442	\N	085704	测绘工程	\N	0857	[]	[]	professional	2026-10-19 03:02:58.445885+08	t	\N
3353	442	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:02:58.445886+08	t	\N
3354	442	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 03:02:58.445886+08	t	\N
3355	442	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 03:02:58.445886+08	t	\N
3356	442	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:02:58.445887+08	t	\N
3357	442	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:02:58.445887+08	t	\N
3358	442	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:02:58.445888+08	t	\N
3359	442	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:02:58.445888+08	t	\N
3360	442	\N	0710J2	农业生物资源	\N	0710	[]	[]	academic	2026-10-19 03:02:58.445888+08	t	\N
3361	442	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:02:58.445889+08	t	\N
3362	443	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:03:05.253264+08	t	\N
3363	443	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:03:05.253267+08	t	\N
3364	443	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:03:05.253267+08	t	\N
3365	444	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:03:11.496073+08	t	\N
3366	444	\N	0831J1	组织工程与再生医学	\N	0831	[]	[]	academic	2026-10-19 03:03:11.496079+08	t	\N
3367	444	\N	0831J2	智能医学工程	\N	0831	[]	[]	academic	2026-10-19 03:03:11.496099+08	t	\N
3368	444	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:03:11.496101+08	t	\N
3369	444	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 03:03:11.496102+08	t	\N
3370	445	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:03:18.999441+08	t	\N
3371	445	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:03:18.999443+08	t	\N
3372	445	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:03:18.999443+08	t	\N
3373	445	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:03:18.999444+08	t	\N
3374	445	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:03:18.999444+08	t	\N
3375	445	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:03:18.999445+08	t	\N
3376	445	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:03:18.999445+08	t	\N
3377	445	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:03:18.999446+08	t	\N
3378	445	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:03:18.999446+08	t	\N
3379	445	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 03:03:18.999447+08	t	\N
3380	445	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:03:18.999447+08	t	\N
3381	445	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:03:18.999447+08	t	\N
3382	445	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:03:18.999448+08	t	\N
3383	445	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:03:18.999448+08	t	\N
3384	445	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:03:18.999449+08	t	\N
3385	445	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 03:03:18.999449+08	t	\N
3386	446	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:03:26.404649+08	t	\N
3387	446	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:03:26.404659+08	t	\N
3388	446	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:03:26.404663+08	t	\N
3389	448	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:03:39.728058+08	t	\N
3390	448	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:03:39.728064+08	t	\N
3391	448	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:03:39.728066+08	t	\N
3392	448	\N	086003	食品工程	\N	0860	[]	[]	professional	2026-10-19 03:03:39.728068+08	t	\N
3393	450	\N	082501	飞行器设计	\N	0825	[]	[]	academic	2026-10-19 03:03:53.290948+08	t	\N
3394	451	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:04:00.336868+08	t	\N
3395	451	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:04:00.336871+08	t	\N
3396	451	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:04:00.336871+08	t	\N
3397	451	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:04:00.336872+08	t	\N
3398	451	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:04:00.336872+08	t	\N
3399	451	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:04:00.336873+08	t	\N
3400	451	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:04:00.336873+08	t	\N
3401	451	\N	0714J1	财经人工智能	\N	0714	[]	[]	academic	2026-10-19 03:04:00.336873+08	t	\N
3402	452	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:04:06.946385+08	t	\N
3403	452	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:04:06.946389+08	t	\N
3404	452	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:04:06.94639+08	t	\N
3405	452	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:04:06.94639+08	t	\N
3406	452	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:04:06.94639+08	t	\N
3407	452	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:04:06.946391+08	t	\N
3408	452	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:04:06.946391+08	t	\N
3409	452	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 03:04:06.946392+08	t	\N
3410	452	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:04:06.946392+08	t	\N
3411	452	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:04:06.946393+08	t	\N
3412	452	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 03:04:06.946393+08	t	\N
3413	452	\N	0703Z1	材料化学	\N	0703	[]	[]	academic	2026-10-19 03:04:06.946394+08	t	\N
3414	452	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:04:06.946394+08	t	\N
3415	452	\N	077300	材料科学与工程	\N	0773	[]	[]	academic	2026-10-19 03:04:06.946394+08	t	\N
3416	453	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:04:13.941278+08	t	\N
3417	453	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:04:13.94128+08	t	\N
3418	453	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:04:13.941281+08	t	\N
3419	453	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:04:13.941281+08	t	\N
3420	453	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:04:13.941282+08	t	\N
3421	453	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:04:13.941282+08	t	\N
3422	453	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:04:13.941282+08	t	\N
3423	453	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:04:13.941283+08	t	\N
3424	453	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:04:13.941283+08	t	\N
3425	453	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 03:04:13.941284+08	t	\N
3426	454	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:04:20.367872+08	t	\N
3427	454	\N	0809J1	智能光电技术与系统	\N	0809	[]	[]	academic	2026-10-19 03:04:20.367878+08	t	\N
3428	454	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:04:20.367879+08	t	\N
3429	454	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:04:20.367881+08	t	\N
3430	454	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 03:04:20.367882+08	t	\N
3431	454	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:04:20.367883+08	t	\N
3432	454	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:04:20.367885+08	t	\N
3433	454	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:04:20.367886+08	t	\N
3434	454	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:04:20.367887+08	t	\N
3435	454	\N	0701Z1	数据智能分析与应用	\N	0701	[]	[]	academic	2026-10-19 03:04:20.367889+08	t	\N
3436	454	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:04:20.36789+08	t	\N
3437	454	\N	0703J1	新型光电材料与器件	\N	0703	[]	[]	academic	2026-10-19 03:04:20.367891+08	t	\N
3438	455	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:04:27.154384+08	t	\N
3439	455	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:04:27.154386+08	t	\N
3440	455	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:04:27.154387+08	t	\N
3441	455	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:04:27.154388+08	t	\N
3442	455	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:04:27.154388+08	t	\N
3443	455	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:04:27.154389+08	t	\N
3444	455	\N	080804	电力电子与电力传动	\N	0808	[]	[]	academic	2026-10-19 03:04:27.154389+08	t	\N
3445	455	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:04:27.154389+08	t	\N
3446	455	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:04:27.15439+08	t	\N
3447	455	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:04:27.15439+08	t	\N
3448	455	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:04:27.154391+08	t	\N
3449	455	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:04:27.154391+08	t	\N
3450	455	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:04:27.154392+08	t	\N
3451	455	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:04:27.154392+08	t	\N
3452	455	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:04:27.154393+08	t	\N
3453	455	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:04:27.154393+08	t	\N
3454	455	\N	0701Z1	信息安全	\N	0701	[]	[]	academic	2026-10-19 03:04:27.154394+08	t	\N
3455	455	\N	0701Z2	金融数学与金融工程	\N	0701	[]	[]	academic	2026-10-19 03:04:27.154394+08	t	\N
3456	455	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:04:27.154394+08	t	\N
3457	455	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 03:04:27.154395+08	t	\N
3458	456	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:04:33.623063+08	t	\N
3459	456	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:04:33.623066+08	t	\N
3460	456	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:04:33.623066+08	t	\N
3461	456	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:04:33.623067+08	t	\N
3462	456	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:04:33.623067+08	t	\N
3463	456	\N	0812J1	海洋技术	\N	0812	[]	[]	academic	2026-10-19 03:04:33.623068+08	t	\N
3464	456	\N	0812Z1	网络空间安全与保密	\N	0812	[]	[]	academic	2026-10-19 03:04:33.623068+08	t	\N
3465	456	\N	081501	水文学及水资源	\N	0815	[]	[]	academic	2026-10-19 03:04:33.623069+08	t	\N
3466	456	\N	081505	港口、海岸及近海工程	\N	0815	[]	[]	academic	2026-10-19 03:04:33.623069+08	t	\N
3467	456	\N	0815Z1	海洋能利用技术	\N	0815	[]	[]	academic	2026-10-19 03:04:33.62307+08	t	\N
3468	456	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:04:33.62307+08	t	\N
3469	456	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:04:33.62307+08	t	\N
3470	456	\N	070206	声学	\N	0702	[]	[]	academic	2026-10-19 03:04:33.623071+08	t	\N
3471	456	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:04:33.623071+08	t	\N
3472	456	\N	070600	大气科学	\N	0706	[]	[]	academic	2026-10-19 03:04:33.623072+08	t	\N
3473	456	\N	070701	物理海洋学	\N	0707	[]	[]	academic	2026-10-19 03:04:33.623072+08	t	\N
3474	456	\N	070702	海洋化学	\N	0707	[]	[]	academic	2026-10-19 03:04:33.623072+08	t	\N
3475	456	\N	070703	海洋生物学	\N	0707	[]	[]	academic	2026-10-19 03:04:33.623073+08	t	\N
3476	456	\N	070704	海洋地质	\N	0707	[]	[]	academic	2026-10-19 03:04:33.623073+08	t	\N
3477	456	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:04:33.623074+08	t	\N
3478	457	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:04:39.640753+08	t	\N
3479	457	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:04:39.640755+08	t	\N
3480	457	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:04:39.640756+08	t	\N
3481	457	\N	0802Z2	工业设计	\N	0802	[]	[]	academic	2026-10-19 03:04:39.640756+08	t	\N
3482	457	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:04:39.640757+08	t	\N
3483	457	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:04:39.640757+08	t	\N
3484	457	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:04:39.640758+08	t	\N
3485	457	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:04:39.640758+08	t	\N
3486	457	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:04:39.640758+08	t	\N
3487	457	\N	0811J2	储能科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:04:39.640759+08	t	\N
3488	457	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:04:39.640759+08	t	\N
3489	457	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:04:39.64076+08	t	\N
3490	457	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:04:39.64076+08	t	\N
3491	457	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:04:39.640761+08	t	\N
3492	457	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 03:04:39.640761+08	t	\N
3493	457	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:04:39.640761+08	t	\N
3494	457	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:04:39.640762+08	t	\N
3495	457	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:04:39.640762+08	t	\N
3496	457	\N	071101	系统理论	\N	0711	[]	[]	academic	2026-10-19 03:04:39.640763+08	t	\N
3497	457	\N	0711J4	海洋技术与装备	\N	0711	[]	[]	academic	2026-10-19 03:04:39.640763+08	t	\N
3498	458	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:04:46.421938+08	t	\N
3499	458	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:04:46.421944+08	t	\N
3500	458	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:04:46.421946+08	t	\N
3501	458	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:04:46.421947+08	t	\N
3502	458	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:04:46.421949+08	t	\N
3503	458	\N	0807J5	新能源科学与工程	\N	0807	[]	[]	academic	2026-10-19 03:04:46.42195+08	t	\N
3504	458	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:04:46.421951+08	t	\N
3505	458	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:04:46.421953+08	t	\N
3506	458	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:04:46.421954+08	t	\N
3507	458	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:04:46.421955+08	t	\N
3508	458	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:04:46.421956+08	t	\N
3509	458	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:04:46.421958+08	t	\N
3510	458	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:04:46.42196+08	t	\N
3511	458	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 03:04:46.421961+08	t	\N
3512	458	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 03:04:46.421962+08	t	\N
3513	458	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:04:46.421964+08	t	\N
3514	459	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:04:53.571049+08	t	\N
3515	459	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:04:53.571052+08	t	\N
3516	459	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:04:53.571052+08	t	\N
3517	459	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:04:53.571053+08	t	\N
3518	459	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:04:53.571053+08	t	\N
3519	459	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:04:53.571054+08	t	\N
3520	459	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:04:53.571054+08	t	\N
3521	459	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:04:53.571055+08	t	\N
3522	459	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:04:53.571055+08	t	\N
3523	459	\N	081704	应用化学	\N	0817	[]	[]	academic	2026-10-19 03:04:53.571056+08	t	\N
3524	459	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:04:53.571056+08	t	\N
3525	459	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:04:53.571056+08	t	\N
3526	459	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:04:53.571057+08	t	\N
3527	459	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 03:04:53.571057+08	t	\N
3528	459	\N	070702	海洋化学	\N	0707	[]	[]	academic	2026-10-19 03:04:53.571058+08	t	\N
3529	459	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:04:53.571058+08	t	\N
3530	460	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:05:00.446872+08	t	\N
3531	460	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:05:00.446874+08	t	\N
3532	460	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:05:00.446875+08	t	\N
3533	460	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:05:00.446875+08	t	\N
3534	460	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:05:00.446876+08	t	\N
3535	460	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:05:00.446876+08	t	\N
3536	460	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:05:00.446877+08	t	\N
3537	460	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:05:00.446877+08	t	\N
3538	460	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:05:00.446877+08	t	\N
3539	460	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:05:00.446878+08	t	\N
3540	460	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:05:00.446878+08	t	\N
3541	460	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:05:00.446879+08	t	\N
3542	460	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:05:00.446879+08	t	\N
3543	460	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:05:00.446879+08	t	\N
3544	461	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:05:06.46982+08	t	\N
3545	461	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:05:06.469829+08	t	\N
3546	461	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:05:06.469833+08	t	\N
3547	461	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:05:06.469836+08	t	\N
3548	461	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:05:06.469838+08	t	\N
3549	461	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:05:06.46984+08	t	\N
3550	461	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:05:06.469842+08	t	\N
3551	461	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:05:06.469844+08	t	\N
3552	461	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:05:06.469846+08	t	\N
3553	461	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:05:06.469848+08	t	\N
3554	461	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:05:06.46985+08	t	\N
3555	461	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:05:06.469851+08	t	\N
3556	462	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:05:12.08122+08	t	\N
3557	462	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:05:12.081223+08	t	\N
3558	462	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:05:12.081224+08	t	\N
3559	462	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:05:12.081224+08	t	\N
3560	462	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:05:12.081224+08	t	\N
3561	462	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:05:12.081225+08	t	\N
3562	462	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 03:05:12.081225+08	t	\N
3563	462	\N	081404	供热、供燃气、通风及空调工程	\N	0814	[]	[]	academic	2026-10-19 03:05:12.081226+08	t	\N
3564	462	\N	081406	桥梁与隧道工程	\N	0814	[]	[]	academic	2026-10-19 03:05:12.081226+08	t	\N
3565	462	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:05:12.081227+08	t	\N
3566	462	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:05:12.081227+08	t	\N
3567	463	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:05:18.037165+08	t	\N
3568	463	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:05:18.037171+08	t	\N
3569	463	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:05:18.037173+08	t	\N
3570	463	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:05:18.037175+08	t	\N
3571	463	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:05:18.037176+08	t	\N
3572	463	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:05:18.037177+08	t	\N
3573	463	\N	082200	轻工技术与工程	\N	0822	[]	[]	academic	2026-10-19 03:05:18.037179+08	t	\N
3574	463	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:05:18.03718+08	t	\N
3575	463	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:05:18.037181+08	t	\N
3576	463	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:05:18.037182+08	t	\N
3577	463	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:05:18.037184+08	t	\N
3578	463	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:05:18.037185+08	t	\N
3579	463	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:05:18.037186+08	t	\N
3580	464	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:05:23.847939+08	t	\N
3581	464	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:05:23.847941+08	t	\N
3582	464	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:05:23.847942+08	t	\N
3583	464	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:05:23.847942+08	t	\N
3584	464	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:05:23.847942+08	t	\N
3585	464	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:05:23.847943+08	t	\N
3586	464	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:05:23.847943+08	t	\N
3587	464	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:05:23.847944+08	t	\N
3588	464	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:05:23.847944+08	t	\N
3589	464	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:05:23.847944+08	t	\N
3590	464	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:05:23.847945+08	t	\N
3591	464	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:05:23.847945+08	t	\N
3592	464	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:05:23.847946+08	t	\N
3593	466	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 03:05:37.404005+08	t	\N
3594	466	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:05:37.404007+08	t	\N
3595	466	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:05:37.404007+08	t	\N
3596	466	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:05:37.404008+08	t	\N
3597	466	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:05:37.404008+08	t	\N
3598	466	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:05:37.404009+08	t	\N
3599	467	\N	082501	飞行器设计	\N	0825	[]	[]	academic	2026-10-19 03:05:44.873654+08	t	\N
3600	467	\N	082502	航空宇航推进理论与工程	\N	0825	[]	[]	academic	2026-10-19 03:05:44.873656+08	t	\N
3601	467	\N	082503	航空宇航制造工程	\N	0825	[]	[]	academic	2026-10-19 03:05:44.873657+08	t	\N
3602	467	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:05:44.873657+08	t	\N
3603	467	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:05:44.873658+08	t	\N
3604	467	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:05:44.873658+08	t	\N
3605	467	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:05:44.873658+08	t	\N
3606	467	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:05:44.873659+08	t	\N
3607	467	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:05:44.873659+08	t	\N
3608	467	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:05:44.87366+08	t	\N
3609	468	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:05:51.655375+08	t	\N
3610	468	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:05:51.655384+08	t	\N
3611	468	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:05:51.655387+08	t	\N
3612	468	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:05:51.655389+08	t	\N
3613	468	\N	086004	发酵工程	\N	0860	[]	[]	professional	2026-10-19 03:05:51.655392+08	t	\N
3614	471	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:06:11.349348+08	t	\N
3615	471	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:06:11.349357+08	t	\N
3616	471	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:06:11.34936+08	t	\N
3617	471	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:06:11.349362+08	t	\N
3618	471	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:06:11.349365+08	t	\N
3619	471	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:06:11.349367+08	t	\N
3620	471	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:06:11.349369+08	t	\N
3621	473	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:06:24.081564+08	t	\N
3622	473	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:06:24.081571+08	t	\N
3623	473	\N	085508	农机装备工程	\N	0855	[]	[]	professional	2026-10-19 03:06:24.081572+08	t	\N
3624	473	\N	085509	智能制造技术	\N	0855	[]	[]	professional	2026-10-19 03:06:24.081574+08	t	\N
3625	473	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:06:24.081575+08	t	\N
3626	473	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:06:24.081577+08	t	\N
3627	474	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 03:06:30.855252+08	t	\N
3628	474	\N	082302	交通信息工程及控制	\N	0823	[]	[]	academic	2026-10-19 03:06:30.855258+08	t	\N
3629	474	\N	082304	载运工具运用工程	\N	0823	[]	[]	academic	2026-10-19 03:06:30.85526+08	t	\N
3630	474	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:06:30.855261+08	t	\N
3631	474	\N	085503	航空工程	\N	0855	[]	[]	professional	2026-10-19 03:06:30.855263+08	t	\N
3632	474	\N	085505	船舶工程	\N	0855	[]	[]	professional	2026-10-19 03:06:30.855264+08	t	\N
3633	474	\N	085510	机器人工程	\N	0855	[]	[]	professional	2026-10-19 03:06:30.855266+08	t	\N
3634	474	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:06:30.855267+08	t	\N
3635	474	\N	086100	交通运输	\N	0861	[]	[]	professional	2026-10-19 03:06:30.855268+08	t	\N
3636	475	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:06:38.45243+08	t	\N
3637	476	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:06:45.661719+08	t	\N
3638	476	\N	085703	地质工程	\N	0857	[]	[]	professional	2026-10-19 03:06:45.661721+08	t	\N
3639	476	\N	085704	测绘工程	\N	0857	[]	[]	professional	2026-10-19 03:06:45.661721+08	t	\N
3640	476	\N	070701	物理海洋学	\N	0707	[]	[]	academic	2026-10-19 03:06:45.661722+08	t	\N
3641	476	\N	070702	海洋化学	\N	0707	[]	[]	academic	2026-10-19 03:06:45.661722+08	t	\N
3642	476	\N	070703	海洋生物学	\N	0707	[]	[]	academic	2026-10-19 03:06:45.661723+08	t	\N
3643	476	\N	070704	海洋地质	\N	0707	[]	[]	academic	2026-10-19 03:06:45.661723+08	t	\N
3644	476	\N	077601	环境科学	\N	0776	[]	[]	academic	2026-10-19 03:06:45.661723+08	t	\N
3645	476	\N	077602	环境工程	\N	0776	[]	[]	academic	2026-10-19 03:06:45.661724+08	t	\N
3646	477	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:06:51.581326+08	t	\N
3647	477	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:06:51.581329+08	t	\N
3648	477	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:06:51.581329+08	t	\N
3649	477	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:06:51.58133+08	t	\N
3650	477	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:06:51.58133+08	t	\N
3651	477	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 03:06:51.581331+08	t	\N
3652	477	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:06:51.581331+08	t	\N
3653	477	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:06:51.581331+08	t	\N
3654	477	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:06:51.581332+08	t	\N
3655	477	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:06:51.581332+08	t	\N
3656	477	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:06:51.581333+08	t	\N
3657	477	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:06:51.581333+08	t	\N
3658	478	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:06:58.567804+08	t	\N
3659	478	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:06:58.567815+08	t	\N
3660	478	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:06:58.567818+08	t	\N
3661	478	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:06:58.567821+08	t	\N
3662	478	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:06:58.567823+08	t	\N
3663	478	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:06:58.567825+08	t	\N
3664	479	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:07:05.270547+08	t	\N
3665	479	\N	083600	生物工程	\N	0836	[]	[]	academic	2026-10-19 03:07:05.270549+08	t	\N
3666	479	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:07:05.27055+08	t	\N
3667	479	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:07:05.27055+08	t	\N
3668	479	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 03:07:05.270551+08	t	\N
3669	479	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:07:05.270551+08	t	\N
3670	479	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:07:05.270552+08	t	\N
3671	479	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:07:05.270552+08	t	\N
3672	480	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:07:11.06449+08	t	\N
3673	480	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:07:11.064499+08	t	\N
3674	480	\N	0710J1	生物智能与生物计算	\N	0710	[]	[]	academic	2026-10-19 03:07:11.064502+08	t	\N
3675	481	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:07:17.753819+08	t	\N
3676	481	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:07:17.753822+08	t	\N
3677	481	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:07:17.753822+08	t	\N
3678	481	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 03:07:17.753823+08	t	\N
3679	482	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:07:24.358737+08	t	\N
3680	482	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:07:24.358745+08	t	\N
3681	482	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:07:24.358782+08	t	\N
3682	482	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:07:24.358785+08	t	\N
3683	482	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:07:24.358787+08	t	\N
3684	482	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:07:24.358789+08	t	\N
3685	482	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:07:24.358791+08	t	\N
3686	482	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:07:24.358793+08	t	\N
3687	482	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:07:24.358795+08	t	\N
3688	482	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:07:24.358797+08	t	\N
3689	482	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:07:24.358799+08	t	\N
3690	482	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:07:24.3588+08	t	\N
3691	482	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:07:24.358802+08	t	\N
3692	482	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:07:24.358804+08	t	\N
3693	482	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:07:24.358806+08	t	\N
3694	482	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:07:24.358807+08	t	\N
3695	482	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 03:07:24.358809+08	t	\N
3696	482	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:07:24.358811+08	t	\N
3697	482	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:07:24.358813+08	t	\N
3698	482	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:07:24.358814+08	t	\N
3699	483	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:07:29.947054+08	t	\N
3700	483	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:07:29.947056+08	t	\N
3701	483	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:07:29.947057+08	t	\N
3702	483	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:07:29.947057+08	t	\N
3703	483	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:07:29.947058+08	t	\N
3704	483	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:07:29.947058+08	t	\N
3705	483	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:07:29.947059+08	t	\N
3706	483	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:07:29.947059+08	t	\N
3707	483	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:07:29.947059+08	t	\N
3708	483	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:07:29.94706+08	t	\N
3709	483	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:07:29.94706+08	t	\N
3710	483	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:07:29.947061+08	t	\N
3711	483	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:07:29.947061+08	t	\N
3712	483	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:07:29.947062+08	t	\N
3713	483	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:07:29.947062+08	t	\N
3714	483	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:07:29.947062+08	t	\N
3715	483	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:07:29.947063+08	t	\N
3716	483	\N	077300	材料科学与工程	\N	0773	[]	[]	academic	2026-10-19 03:07:29.947063+08	t	\N
3717	483	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 03:07:29.947064+08	t	\N
3718	484	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:07:36.437328+08	t	\N
3719	484	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 03:07:36.437331+08	t	\N
3720	484	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:07:36.437331+08	t	\N
3721	484	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:07:36.437332+08	t	\N
3722	484	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:07:36.437332+08	t	\N
3723	484	\N	085508	农机装备工程	\N	0855	[]	[]	professional	2026-10-19 03:07:36.437333+08	t	\N
3724	484	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:07:36.437333+08	t	\N
3725	484	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:07:36.437333+08	t	\N
3726	484	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:07:36.437334+08	t	\N
3727	484	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:07:36.437334+08	t	\N
3728	484	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:07:36.437335+08	t	\N
3729	484	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:07:36.437335+08	t	\N
3730	485	\N	081202	计算机软件与理论	\N	0812	[]	[]	academic	2026-10-19 03:07:43.967362+08	t	\N
3731	485	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 03:07:43.967364+08	t	\N
3732	485	\N	0812J1	金融信息工程	\N	0812	[]	[]	academic	2026-10-19 03:07:43.967365+08	t	\N
3733	485	\N	0812Z1	数字媒体技术	\N	0812	[]	[]	academic	2026-10-19 03:07:43.967365+08	t	\N
3734	485	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:07:43.967366+08	t	\N
3735	485	\N	087100	管理科学与工程	\N	0871	[]	[]	academic	2026-10-19 03:07:43.967366+08	t	\N
3736	485	\N	0871J6	大数据管理与工程	\N	0871	[]	[]	academic	2026-10-19 03:07:43.967366+08	t	\N
3737	485	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:07:43.967367+08	t	\N
3738	485	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:07:43.967367+08	t	\N
3739	487	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:07:56.679349+08	t	\N
3740	487	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:07:56.679351+08	t	\N
3741	487	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:07:56.679352+08	t	\N
3742	487	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:07:56.679352+08	t	\N
3743	487	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:07:56.679353+08	t	\N
3744	488	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 03:08:03.144667+08	t	\N
3745	488	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:08:03.144677+08	t	\N
3746	488	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:08:03.14468+08	t	\N
3747	488	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:08:03.144682+08	t	\N
3748	488	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:08:03.144685+08	t	\N
3749	488	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:08:03.144686+08	t	\N
3750	488	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:08:03.144688+08	t	\N
3751	488	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:08:03.14469+08	t	\N
3752	488	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:08:03.144692+08	t	\N
3753	488	\N	081800	地质资源与地质工程	\N	0818	[]	[]	academic	2026-10-19 03:08:03.144694+08	t	\N
3754	488	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:08:03.144695+08	t	\N
3755	488	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:08:03.144697+08	t	\N
3756	489	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:08:09.888413+08	t	\N
3757	489	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:08:09.888416+08	t	\N
3758	489	\N	080402	测试计量技术及仪器	\N	0804	[]	[]	academic	2026-10-19 03:08:09.888416+08	t	\N
3759	489	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:08:09.888417+08	t	\N
3760	489	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:08:09.888417+08	t	\N
3761	489	\N	080603	有色金属冶金	\N	0806	[]	[]	academic	2026-10-19 03:08:09.888418+08	t	\N
3762	489	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:08:09.888418+08	t	\N
3763	489	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:08:09.888419+08	t	\N
3764	489	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:08:09.888419+08	t	\N
3765	489	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:08:09.888419+08	t	\N
3766	489	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:08:09.88842+08	t	\N
3767	489	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:08:09.88842+08	t	\N
3768	489	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:08:09.888421+08	t	\N
3769	489	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:08:09.888421+08	t	\N
3770	489	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:08:09.888421+08	t	\N
3771	489	\N	0701J2	大数据科学与技术	\N	0701	[]	[]	academic	2026-10-19 03:08:09.888422+08	t	\N
3772	489	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:08:09.888422+08	t	\N
3773	489	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 03:08:09.888423+08	t	\N
3774	489	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:08:09.888423+08	t	\N
3775	489	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:08:09.888423+08	t	\N
3776	490	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:08:16.406548+08	t	\N
3777	490	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:08:16.406559+08	t	\N
3778	490	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:08:16.406563+08	t	\N
3779	490	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:08:16.406565+08	t	\N
3780	490	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:08:16.406568+08	t	\N
3781	490	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:08:16.40657+08	t	\N
3782	490	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:08:16.406572+08	t	\N
3783	490	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:08:16.406574+08	t	\N
3784	490	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:08:16.406576+08	t	\N
3785	490	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:08:16.406578+08	t	\N
3786	490	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:08:16.40658+08	t	\N
3787	490	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:08:16.406581+08	t	\N
3788	490	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:08:16.406583+08	t	\N
3789	491	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:08:23.894101+08	t	\N
3790	491	\N	0802J3	高端装备	\N	0802	[]	[]	academic	2026-10-19 03:08:23.894111+08	t	\N
3791	491	\N	0802Z1	智能制造工程	\N	0802	[]	[]	academic	2026-10-19 03:08:23.894114+08	t	\N
3792	491	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:08:23.894116+08	t	\N
3793	491	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:08:23.894118+08	t	\N
3794	491	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:08:23.89412+08	t	\N
3795	491	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:08:23.894122+08	t	\N
3796	491	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:08:23.894124+08	t	\N
3797	491	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:08:23.894126+08	t	\N
3798	491	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:08:23.894128+08	t	\N
3799	491	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:08:23.89413+08	t	\N
3800	492	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:08:30.207963+08	t	\N
3801	492	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:08:30.207972+08	t	\N
3802	492	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:08:30.207976+08	t	\N
3803	492	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:08:30.207978+08	t	\N
3804	492	\N	0811J1	智慧储运科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:08:30.207981+08	t	\N
3805	492	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:08:30.207983+08	t	\N
3806	492	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:08:30.207985+08	t	\N
3807	492	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:08:30.207986+08	t	\N
3808	492	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:08:30.207988+08	t	\N
3809	492	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:08:30.20799+08	t	\N
3810	492	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:08:30.207992+08	t	\N
3811	492	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:08:30.207994+08	t	\N
3812	492	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:08:30.207995+08	t	\N
3813	492	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:08:30.207997+08	t	\N
3814	493	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:08:36.757222+08	t	\N
3815	493	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:08:36.757232+08	t	\N
3816	493	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:08:36.757235+08	t	\N
3817	493	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:08:36.757238+08	t	\N
3818	493	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:08:36.75724+08	t	\N
3819	493	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 03:08:36.757242+08	t	\N
3820	493	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:08:36.757243+08	t	\N
3821	493	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:08:36.757245+08	t	\N
3822	493	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:08:36.757247+08	t	\N
3823	493	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:08:36.757249+08	t	\N
3824	493	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:08:36.757251+08	t	\N
3825	493	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:08:36.757253+08	t	\N
3826	493	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:08:36.757254+08	t	\N
3827	493	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:08:36.757256+08	t	\N
3828	493	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:08:36.757258+08	t	\N
3829	493	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:08:36.75726+08	t	\N
3830	493	\N	077500	计算机科学与技术	\N	0775	[]	[]	academic	2026-10-19 03:08:36.757261+08	t	\N
3831	493	\N	078000	药学	\N	0780	[]	[]	academic	2026-10-19 03:08:36.757263+08	t	\N
3832	494	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:08:42.412605+08	t	\N
3833	494	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:08:42.412614+08	t	\N
3834	494	\N	0805Z1	低维量子物理与材料	\N	0805	[]	[]	academic	2026-10-19 03:08:42.412618+08	t	\N
3835	494	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:08:42.412621+08	t	\N
3836	494	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:08:42.412623+08	t	\N
3837	494	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 03:08:42.412625+08	t	\N
3838	494	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 03:08:42.412627+08	t	\N
3839	494	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:08:42.412629+08	t	\N
3840	494	\N	0811Z1	复杂系统的数学理论与技术	\N	0811	[]	[]	academic	2026-10-19 03:08:42.412631+08	t	\N
3841	494	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:08:42.412633+08	t	\N
3842	495	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:08:50.050158+08	t	\N
3843	495	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:08:50.050165+08	t	\N
3844	495	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 03:08:50.050167+08	t	\N
3845	495	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:08:50.050169+08	t	\N
3846	495	\N	0832Z1	烟草科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:08:50.050171+08	t	\N
3847	495	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:08:50.050172+08	t	\N
3848	495	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:08:50.050173+08	t	\N
3849	495	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:08:50.050174+08	t	\N
3850	495	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:08:50.050176+08	t	\N
3851	495	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:08:50.050177+08	t	\N
3852	495	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:08:50.050178+08	t	\N
3853	495	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:08:50.05018+08	t	\N
3854	495	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:08:50.050181+08	t	\N
3855	496	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:08:55.882973+08	t	\N
3856	496	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:08:55.882982+08	t	\N
3857	496	\N	083600	生物工程	\N	0836	[]	[]	academic	2026-10-19 03:08:55.882985+08	t	\N
3858	496	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:08:55.882988+08	t	\N
3859	496	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:08:55.88299+08	t	\N
3860	496	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:08:55.882993+08	t	\N
3861	496	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:08:55.882995+08	t	\N
3862	496	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:08:55.882997+08	t	\N
3863	496	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:08:55.882999+08	t	\N
3864	496	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:08:55.883001+08	t	\N
3865	496	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:08:55.883003+08	t	\N
3866	496	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:08:55.883005+08	t	\N
3867	496	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:08:55.883007+08	t	\N
3868	497	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:09:02.476314+08	t	\N
3869	498	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:09:08.854886+08	t	\N
3870	498	\N	0831J1	医用具身智能	\N	0831	[]	[]	academic	2026-10-19 03:09:08.854896+08	t	\N
3871	498	\N	0831J2	数理医学	\N	0831	[]	[]	academic	2026-10-19 03:09:08.854899+08	t	\N
3872	498	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:09:08.854902+08	t	\N
3873	498	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:09:08.854904+08	t	\N
3874	498	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:09:08.854906+08	t	\N
3875	498	\N	0710J1	合成生物学	\N	0710	[]	[]	academic	2026-10-19 03:09:08.854908+08	t	\N
3876	499	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:09:15.805715+08	t	\N
3877	499	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:09:15.805725+08	t	\N
3878	499	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:09:15.805728+08	t	\N
3879	499	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:09:15.805731+08	t	\N
3880	499	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:09:15.805733+08	t	\N
3881	499	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:09:15.805735+08	t	\N
3882	499	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:09:15.805737+08	t	\N
3883	499	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:09:15.805739+08	t	\N
3884	499	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:09:15.80574+08	t	\N
3885	499	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:09:15.805742+08	t	\N
3886	499	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:09:15.805745+08	t	\N
3887	499	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:09:15.805747+08	t	\N
3888	499	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:09:15.805749+08	t	\N
3889	499	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:09:15.805751+08	t	\N
3890	499	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:09:15.805753+08	t	\N
3891	499	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:09:15.805755+08	t	\N
3892	499	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:09:15.805757+08	t	\N
3893	499	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:09:15.805759+08	t	\N
3894	499	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 03:09:15.805761+08	t	\N
3895	500	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:09:21.976606+08	t	\N
3896	500	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:09:21.976608+08	t	\N
3897	500	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:09:21.976609+08	t	\N
3898	500	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:09:21.976609+08	t	\N
3899	501	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:09:30.416406+08	t	\N
3900	501	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:09:30.416409+08	t	\N
3901	501	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:09:30.41641+08	t	\N
3902	501	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:09:30.41641+08	t	\N
3903	501	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:09:30.41641+08	t	\N
3904	501	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:09:30.416411+08	t	\N
3905	501	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:09:30.416411+08	t	\N
3906	501	\N	085603	冶金工程	\N	0856	[]	[]	professional	2026-10-19 03:09:30.416412+08	t	\N
3907	501	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:09:30.416412+08	t	\N
3908	501	\N	085704	测绘工程	\N	0857	[]	[]	professional	2026-10-19 03:09:30.416413+08	t	\N
3909	501	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:09:30.416413+08	t	\N
3910	501	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:09:30.416413+08	t	\N
3911	503	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:09:44.698397+08	t	\N
3912	503	\N	081402	结构工程	\N	0814	[]	[]	academic	2026-10-19 03:09:44.698399+08	t	\N
3913	503	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 03:09:44.6984+08	t	\N
3914	503	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:09:44.6984+08	t	\N
3915	503	\N	082502	航空宇航推进理论与工程	\N	0825	[]	[]	academic	2026-10-19 03:09:44.698401+08	t	\N
3916	503	\N	082503	航空宇航制造工程	\N	0825	[]	[]	academic	2026-10-19 03:09:44.698401+08	t	\N
3917	503	\N	0825Z1	低空技术与工程	\N	0825	[]	[]	academic	2026-10-19 03:09:44.698402+08	t	\N
3918	503	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:09:44.698402+08	t	\N
3919	503	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:09:44.698402+08	t	\N
3920	503	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:09:44.698403+08	t	\N
3921	504	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:09:50.778423+08	t	\N
3922	504	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:09:50.778426+08	t	\N
3923	505	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:09:57.086385+08	t	\N
3924	505	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:09:57.086394+08	t	\N
3925	505	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:09:57.086397+08	t	\N
3926	506	\N	080102	固体力学	\N	0801	[]	[]	academic	2026-10-19 03:10:03.252129+08	t	\N
3927	506	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 03:10:03.252138+08	t	\N
3928	506	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 03:10:03.252141+08	t	\N
3929	506	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:10:03.252144+08	t	\N
3930	507	\N	082602	兵器发射理论与技术	\N	0826	[]	[]	academic	2026-10-19 03:10:10.185916+08	t	\N
3931	507	\N	082603	火炮、自动武器与弹药工程	\N	0826	[]	[]	academic	2026-10-19 03:10:10.185919+08	t	\N
3932	507	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:10:10.185919+08	t	\N
3933	507	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 03:10:10.18592+08	t	\N
3934	507	\N	085509	智能制造技术	\N	0855	[]	[]	professional	2026-10-19 03:10:10.18592+08	t	\N
3935	507	\N	085510	机器人工程	\N	0855	[]	[]	professional	2026-10-19 03:10:10.185921+08	t	\N
3936	508	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:10:16.799069+08	t	\N
3937	509	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:10:23.862846+08	t	\N
3938	509	\N	081105	导航、制导与控制	\N	0811	[]	[]	academic	2026-10-19 03:10:23.862853+08	t	\N
3939	509	\N	082501	飞行器设计	\N	0825	[]	[]	academic	2026-10-19 03:10:23.862855+08	t	\N
3940	509	\N	082502	航空宇航推进理论与工程	\N	0825	[]	[]	academic	2026-10-19 03:10:23.862856+08	t	\N
3941	510	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:10:29.793379+08	t	\N
3942	510	\N	081103	系统工程	\N	0811	[]	[]	academic	2026-10-19 03:10:29.793388+08	t	\N
3943	510	\N	081105	导航、制导与控制	\N	0811	[]	[]	academic	2026-10-19 03:10:29.793391+08	t	\N
3944	510	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:10:29.793394+08	t	\N
3945	512	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:10:39.307483+08	t	\N
3946	512	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:10:39.307485+08	t	\N
3947	512	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:10:39.307485+08	t	\N
3948	512	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:10:39.307486+08	t	\N
3949	512	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:10:39.307486+08	t	\N
3950	512	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:10:39.307487+08	t	\N
3951	512	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:10:39.307487+08	t	\N
3952	512	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:10:39.307487+08	t	\N
3953	512	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:10:39.307488+08	t	\N
3954	512	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:10:39.307488+08	t	\N
3955	512	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:10:39.307489+08	t	\N
3956	512	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:10:39.307489+08	t	\N
3957	512	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:10:39.30749+08	t	\N
3958	512	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:10:39.30749+08	t	\N
3959	512	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:10:39.307491+08	t	\N
3960	512	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:10:39.307491+08	t	\N
3961	512	\N	078000	药学	\N	0780	[]	[]	academic	2026-10-19 03:10:39.307491+08	t	\N
3962	512	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 03:10:39.307492+08	t	\N
3963	513	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:10:46.061932+08	t	\N
3964	513	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:10:46.061934+08	t	\N
3965	513	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:10:46.061935+08	t	\N
3966	513	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:10:46.061936+08	t	\N
3967	513	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:10:46.061936+08	t	\N
3968	513	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:10:46.061936+08	t	\N
3969	514	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:10:52.414372+08	t	\N
3970	514	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:10:52.414378+08	t	\N
3971	514	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:10:52.414379+08	t	\N
3972	514	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:10:52.414381+08	t	\N
3973	514	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:10:52.414382+08	t	\N
3974	514	\N	085704	测绘工程	\N	0857	[]	[]	professional	2026-10-19 03:10:52.414384+08	t	\N
3975	514	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:10:52.414385+08	t	\N
3976	514	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:10:52.414387+08	t	\N
3977	514	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:10:52.414388+08	t	\N
3978	514	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:10:52.414389+08	t	\N
3979	514	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:10:52.414391+08	t	\N
3980	514	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:10:52.414392+08	t	\N
3981	514	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:10:52.414393+08	t	\N
3982	514	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:10:52.414395+08	t	\N
3983	515	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:10:59.606167+08	t	\N
3984	515	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:10:59.606169+08	t	\N
3985	515	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:10:59.60617+08	t	\N
3986	515	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:10:59.60617+08	t	\N
3987	515	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:10:59.60617+08	t	\N
3988	515	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:10:59.606171+08	t	\N
3989	515	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:10:59.606171+08	t	\N
3990	515	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:10:59.606172+08	t	\N
3991	515	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:10:59.606172+08	t	\N
3992	515	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:10:59.606173+08	t	\N
3993	515	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:10:59.606173+08	t	\N
3994	516	\N	080102	固体力学	\N	0801	[]	[]	academic	2026-10-19 03:11:06.169188+08	t	\N
3995	516	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 03:11:06.169195+08	t	\N
3996	516	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 03:11:06.169197+08	t	\N
3997	516	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:11:06.169199+08	t	\N
3998	516	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:11:06.169201+08	t	\N
3999	516	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 03:11:06.169202+08	t	\N
4000	516	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:11:06.169204+08	t	\N
4001	516	\N	0805Z1	纳米科学与技术	\N	0805	[]	[]	academic	2026-10-19 03:11:06.169205+08	t	\N
4002	516	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:11:06.169206+08	t	\N
4003	516	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:11:06.169208+08	t	\N
4004	516	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:11:06.169209+08	t	\N
4005	516	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:11:06.16921+08	t	\N
4006	516	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:11:06.169212+08	t	\N
4007	516	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:11:06.169213+08	t	\N
4008	516	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:11:06.169214+08	t	\N
4009	516	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 03:11:06.169216+08	t	\N
4010	516	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:11:06.169217+08	t	\N
4011	516	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 03:11:06.169218+08	t	\N
4012	516	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:11:06.16922+08	t	\N
4013	516	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:11:06.169221+08	t	\N
4014	517	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:11:12.07086+08	t	\N
4015	517	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:11:12.070876+08	t	\N
4016	517	\N	0802Z1	工业工程	\N	0802	[]	[]	academic	2026-10-19 03:11:12.070877+08	t	\N
4017	517	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:11:12.070877+08	t	\N
4018	517	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:11:12.070877+08	t	\N
4019	517	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 03:11:12.070878+08	t	\N
4020	517	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:11:12.070878+08	t	\N
4021	517	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:11:12.070879+08	t	\N
4022	517	\N	0805Z3	电子封装	\N	0805	[]	[]	academic	2026-10-19 03:11:12.070879+08	t	\N
4023	517	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:11:12.07088+08	t	\N
4024	517	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:11:12.07088+08	t	\N
4025	517	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:11:12.070881+08	t	\N
4026	517	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:11:12.070881+08	t	\N
4027	517	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:11:12.070881+08	t	\N
4028	517	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:11:12.070882+08	t	\N
4029	518	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:11:19.947592+08	t	\N
4030	518	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:11:19.947602+08	t	\N
4031	518	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:11:19.947606+08	t	\N
4032	518	\N	0802J2	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:11:19.947609+08	t	\N
4033	518	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:11:19.947611+08	t	\N
4034	518	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:11:19.947613+08	t	\N
4035	518	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 03:11:19.947615+08	t	\N
4036	518	\N	0806J3	新能源与储能技术	\N	0806	[]	[]	academic	2026-10-19 03:11:19.947617+08	t	\N
4037	518	\N	0806Z1	冶金热能工程	\N	0806	[]	[]	academic	2026-10-19 03:11:19.947619+08	t	\N
4038	518	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:11:19.94762+08	t	\N
4039	518	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:11:19.947622+08	t	\N
4040	518	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:11:19.947624+08	t	\N
4041	518	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:11:19.947626+08	t	\N
4042	518	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:11:19.947627+08	t	\N
4043	518	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:11:19.947629+08	t	\N
4044	518	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:11:19.947631+08	t	\N
4045	519	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:11:26.957729+08	t	\N
4046	519	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:11:26.957731+08	t	\N
4047	519	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:11:26.957732+08	t	\N
4048	519	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:11:26.957732+08	t	\N
4049	519	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:11:26.957733+08	t	\N
4050	519	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:11:26.957733+08	t	\N
4051	519	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 03:11:26.957734+08	t	\N
4052	519	\N	0814Z1	工程管理	\N	0814	[]	[]	academic	2026-10-19 03:11:26.957734+08	t	\N
4053	519	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:11:26.957734+08	t	\N
4054	519	\N	081800	地质资源与地质工程	\N	0818	[]	[]	academic	2026-10-19 03:11:26.957735+08	t	\N
4055	519	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:11:26.957735+08	t	\N
4056	519	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:11:26.957736+08	t	\N
4057	519	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 03:11:26.957736+08	t	\N
4058	519	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:11:26.957737+08	t	\N
4059	519	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:11:26.957737+08	t	\N
4060	519	\N	077500	计算机科学与技术	\N	0775	[]	[]	academic	2026-10-19 03:11:26.957737+08	t	\N
4061	519	\N	077600	环境科学与工程	\N	0776	[]	[]	academic	2026-10-19 03:11:26.957738+08	t	\N
4062	520	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:11:34.006722+08	t	\N
4063	520	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:11:34.006724+08	t	\N
4064	520	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:11:34.006724+08	t	\N
4065	520	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:11:34.006725+08	t	\N
4066	520	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:11:34.006725+08	t	\N
4067	520	\N	080705	制冷及低温工程	\N	0807	[]	[]	academic	2026-10-19 03:11:34.006726+08	t	\N
4068	520	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 03:11:34.006726+08	t	\N
4069	520	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 03:11:34.006727+08	t	\N
4070	520	\N	081101	控制理论与控制工程	\N	0811	[]	[]	academic	2026-10-19 03:11:34.006727+08	t	\N
4071	520	\N	081102	检测技术与自动化装置	\N	0811	[]	[]	academic	2026-10-19 03:11:34.006728+08	t	\N
4072	520	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:11:34.006728+08	t	\N
4073	520	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 03:11:34.006728+08	t	\N
4074	520	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:11:34.006729+08	t	\N
4075	520	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:11:34.006729+08	t	\N
4076	520	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 03:11:34.00673+08	t	\N
4077	520	\N	0703Z1	工业微生物	\N	0703	[]	[]	academic	2026-10-19 03:11:34.00673+08	t	\N
4078	520	\N	0703Z2	制药化学	\N	0703	[]	[]	academic	2026-10-19 03:11:34.00673+08	t	\N
4079	521	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:11:39.850879+08	t	\N
4080	521	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:11:39.850882+08	t	\N
4081	521	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:11:39.850882+08	t	\N
4082	521	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:11:39.850883+08	t	\N
4083	521	\N	0811Z2	低空技术与工程	\N	0811	[]	[]	academic	2026-10-19 03:11:39.850883+08	t	\N
4084	521	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:11:39.850884+08	t	\N
4085	521	\N	0812Z1	信息安全	\N	0812	[]	[]	academic	2026-10-19 03:11:39.850884+08	t	\N
4086	521	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:11:39.850885+08	t	\N
4087	521	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:11:39.850885+08	t	\N
4088	521	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:11:39.850885+08	t	\N
4089	521	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:11:39.850886+08	t	\N
4090	521	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:11:39.850886+08	t	\N
4091	521	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:11:39.850887+08	t	\N
4092	521	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:11:39.850887+08	t	\N
4093	521	\N	070600	大气科学	\N	0706	[]	[]	academic	2026-10-19 03:11:39.850888+08	t	\N
4094	521	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 03:11:39.850888+08	t	\N
4095	521	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 03:11:39.850889+08	t	\N
4096	521	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:11:39.850889+08	t	\N
4097	521	\N	0709Z1	宝石学	\N	0709	[]	[]	academic	2026-10-19 03:11:39.850889+08	t	\N
4098	521	\N	0709Z4	水文地质学	\N	0709	[]	[]	academic	2026-10-19 03:11:39.85089+08	t	\N
4099	522	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:11:46.016938+08	t	\N
4100	522	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:11:46.01694+08	t	\N
4101	522	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:11:46.016941+08	t	\N
4102	522	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:11:46.016941+08	t	\N
4103	522	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:11:46.016942+08	t	\N
4104	522	\N	082100	纺织科学与工程	\N	0821	[]	[]	academic	2026-10-19 03:11:46.016942+08	t	\N
4105	522	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:11:46.016943+08	t	\N
4106	522	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:11:46.016943+08	t	\N
4107	522	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:11:46.016943+08	t	\N
4108	522	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:11:46.016944+08	t	\N
4109	522	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:11:46.016944+08	t	\N
4110	522	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:11:46.016945+08	t	\N
4111	522	\N	077300	材料科学与工程	\N	0773	[]	[]	academic	2026-10-19 03:11:46.016945+08	t	\N
4112	522	\N	077400	电子科学与技术	\N	0774	[]	[]	academic	2026-10-19 03:11:46.016945+08	t	\N
4113	522	\N	077600	环境科学与工程	\N	0776	[]	[]	academic	2026-10-19 03:11:46.016946+08	t	\N
4114	523	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:11:53.357689+08	t	\N
4115	523	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:11:53.360071+08	t	\N
4116	523	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:11:53.360079+08	t	\N
4117	523	\N	081701	化学工程	\N	0817	[]	[]	academic	2026-10-19 03:11:53.360082+08	t	\N
4118	523	\N	081702	化学工艺	\N	0817	[]	[]	academic	2026-10-19 03:11:53.360084+08	t	\N
4119	523	\N	081703	生物化工	\N	0817	[]	[]	academic	2026-10-19 03:11:53.360087+08	t	\N
4120	523	\N	081704	应用化学	\N	0817	[]	[]	academic	2026-10-19 03:11:53.360089+08	t	\N
4121	523	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:11:53.360705+08	t	\N
4122	523	\N	083201	食品科学	\N	0832	[]	[]	academic	2026-10-19 03:11:53.360712+08	t	\N
4123	523	\N	0832J1	硒科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:11:53.360714+08	t	\N
4124	523	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:11:53.360715+08	t	\N
4125	524	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:11:59.187834+08	t	\N
4126	524	\N	0801J1	低空技术与工程	\N	0801	[]	[]	academic	2026-10-19 03:11:59.187843+08	t	\N
4127	524	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:11:59.187848+08	t	\N
4128	524	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:11:59.18785+08	t	\N
4129	524	\N	0802Z1	工业工程	\N	0802	[]	[]	academic	2026-10-19 03:11:59.187852+08	t	\N
4130	524	\N	0802Z2	汽车运用工程	\N	0802	[]	[]	academic	2026-10-19 03:11:59.187854+08	t	\N
4131	524	\N	0802Z5	智能电动车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:11:59.187856+08	t	\N
4132	524	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:11:59.187858+08	t	\N
4133	524	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:11:59.187859+08	t	\N
4134	524	\N	0805J1	低空技术与工程	\N	0805	[]	[]	academic	2026-10-19 03:11:59.187861+08	t	\N
4135	524	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:11:59.187863+08	t	\N
4136	524	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:11:59.187865+08	t	\N
4137	524	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:11:59.187867+08	t	\N
4138	524	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:11:59.187869+08	t	\N
4139	524	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:11:59.187871+08	t	\N
4140	525	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:12:06.904254+08	t	\N
4141	525	\N	0802J2	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:12:06.904256+08	t	\N
4142	525	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:12:06.904257+08	t	\N
4143	525	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:12:06.904257+08	t	\N
4144	525	\N	0805J1	防水材料与工程	\N	0805	[]	[]	academic	2026-10-19 03:12:06.904258+08	t	\N
4145	525	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:12:06.904258+08	t	\N
4146	525	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:12:06.904259+08	t	\N
4147	525	\N	0809J2	低空技术与工程	\N	0809	[]	[]	academic	2026-10-19 03:12:06.904259+08	t	\N
4148	525	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:12:06.90426+08	t	\N
4149	525	\N	0811J2	低空技术与工程	\N	0811	[]	[]	academic	2026-10-19 03:12:06.90426+08	t	\N
4150	525	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:12:06.90426+08	t	\N
4151	525	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:12:06.904261+08	t	\N
4152	525	\N	077302	材料学	\N	0773	[]	[]	academic	2026-10-19 03:12:06.904261+08	t	\N
4153	526	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:12:13.723793+08	t	\N
4154	527	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:12:20.414975+08	t	\N
4155	527	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:12:20.414978+08	t	\N
4156	527	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:12:20.414979+08	t	\N
4157	527	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:12:20.414979+08	t	\N
4158	527	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 03:12:20.414979+08	t	\N
4159	527	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:12:20.41498+08	t	\N
4160	527	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:12:20.41498+08	t	\N
4161	527	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:12:20.414981+08	t	\N
4162	527	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:12:20.414981+08	t	\N
4163	527	\N	086003	食品工程	\N	0860	[]	[]	professional	2026-10-19 03:12:20.414982+08	t	\N
4164	527	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:12:20.414982+08	t	\N
4165	527	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:12:20.414982+08	t	\N
4166	529	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 03:12:34.087215+08	t	\N
4167	530	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:12:40.722861+08	t	\N
4168	530	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:12:40.722863+08	t	\N
4169	530	\N	0802J1	智能电动车辆	\N	0802	[]	[]	academic	2026-10-19 03:12:40.722864+08	t	\N
4170	530	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:12:40.722864+08	t	\N
4171	530	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:12:40.722865+08	t	\N
4172	530	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:12:40.722865+08	t	\N
4173	530	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:12:40.722866+08	t	\N
4174	530	\N	0811J2	人工智能科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:12:40.722866+08	t	\N
4175	530	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:12:40.722866+08	t	\N
4176	530	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:12:40.722867+08	t	\N
4177	530	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:12:40.722867+08	t	\N
4178	530	\N	077200	力学	\N	0772	[]	[]	academic	2026-10-19 03:12:40.722868+08	t	\N
4179	530	\N	077300	材料科学与工程	\N	0773	[]	[]	academic	2026-10-19 03:12:40.722868+08	t	\N
4180	530	\N	077301	材料物理与化学	\N	0773	[]	[]	academic	2026-10-19 03:12:40.722868+08	t	\N
4181	531	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:12:47.096495+08	t	\N
4182	531	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:12:47.096497+08	t	\N
4183	532	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:12:54.203887+08	t	\N
4184	532	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:12:54.203893+08	t	\N
4185	532	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:12:54.203895+08	t	\N
4186	532	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:12:54.203896+08	t	\N
4187	533	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:12:59.964366+08	t	\N
4188	533	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:12:59.964375+08	t	\N
4189	534	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:13:05.711336+08	t	\N
4190	534	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:13:05.711339+08	t	\N
4191	534	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:13:05.71134+08	t	\N
4192	534	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:13:05.71134+08	t	\N
4193	534	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:13:05.711341+08	t	\N
4194	534	\N	077802	免疫学	\N	0778	[]	[]	academic	2026-10-19 03:13:05.711341+08	t	\N
4195	536	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 03:13:18.273328+08	t	\N
4196	536	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:13:18.273342+08	t	\N
4197	538	\N	081405	防灾减灾工程及防护工程	\N	0814	[]	[]	academic	2026-10-19 03:13:30.687991+08	t	\N
4198	538	\N	081601	大地测量学与测量工程	\N	0816	[]	[]	academic	2026-10-19 03:13:30.687997+08	t	\N
4199	538	\N	070801	固体地球物理学	\N	0708	[]	[]	academic	2026-10-19 03:13:30.687999+08	t	\N
4200	539	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:13:37.472317+08	t	\N
4201	539	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:13:37.472319+08	t	\N
4202	540	\N	080801	电机与电器	\N	0808	[]	[]	academic	2026-10-19 03:13:44.102102+08	t	\N
4203	540	\N	080804	电力电子与电力传动	\N	0808	[]	[]	academic	2026-10-19 03:13:44.102104+08	t	\N
4204	540	\N	080805	电工理论与新技术	\N	0808	[]	[]	academic	2026-10-19 03:13:44.102105+08	t	\N
4205	540	\N	0824Z4	船舶化学电源技术	\N	0824	[]	[]	academic	2026-10-19 03:13:44.102105+08	t	\N
4206	541	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:13:50.252723+08	t	\N
4207	541	\N	081102	检测技术与自动化装置	\N	0811	[]	[]	academic	2026-10-19 03:13:50.252733+08	t	\N
4208	542	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 03:13:57.055898+08	t	\N
4209	542	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 03:13:57.055901+08	t	\N
4210	542	\N	0824Z5	舰船通信天线技术	\N	0824	[]	[]	academic	2026-10-19 03:13:57.055901+08	t	\N
4211	542	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:13:57.055902+08	t	\N
4212	543	\N	082401	船舶与海洋结构物设计制造	\N	0824	[]	[]	academic	2026-10-19 03:14:03.962699+08	t	\N
4213	543	\N	082701	核能科学与工程	\N	0827	[]	[]	academic	2026-10-19 03:14:03.962709+08	t	\N
4214	544	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 03:14:10.121357+08	t	\N
4215	544	\N	081405	防灾减灾工程及防护工程	\N	0814	[]	[]	academic	2026-10-19 03:14:10.121359+08	t	\N
4216	544	\N	081501	水文学及水资源	\N	0815	[]	[]	academic	2026-10-19 03:14:10.12136+08	t	\N
4217	544	\N	081502	水力学及河流动力学	\N	0815	[]	[]	academic	2026-10-19 03:14:10.12136+08	t	\N
4218	544	\N	081503	水工结构工程	\N	0815	[]	[]	academic	2026-10-19 03:14:10.121361+08	t	\N
4219	544	\N	0815Z1	水土保持工程	\N	0815	[]	[]	academic	2026-10-19 03:14:10.121361+08	t	\N
4220	544	\N	0815Z2	流域水环境与生态	\N	0815	[]	[]	academic	2026-10-19 03:14:10.121362+08	t	\N
4221	544	\N	085901	土木工程	\N	0859	[]	[]	professional	2026-10-19 03:14:10.121362+08	t	\N
4222	544	\N	085902	水利工程	\N	0859	[]	[]	professional	2026-10-19 03:14:10.121362+08	t	\N
4223	544	\N	085904	农田水土工程	\N	0859	[]	[]	professional	2026-10-19 03:14:10.121363+08	t	\N
4224	546	\N	081903	安全技术及工程	\N	0819	[]	[]	academic	2026-10-19 03:14:24.573279+08	t	\N
4225	546	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 03:14:24.573288+08	t	\N
4226	547	\N	082502	航空宇航推进理论与工程	\N	0825	[]	[]	academic	2026-10-19 03:14:31.865462+08	t	\N
4227	547	\N	082504	人机与环境工程	\N	0825	[]	[]	academic	2026-10-19 03:14:31.865464+08	t	\N
4228	548	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:14:38.582537+08	t	\N
4229	548	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:14:38.582539+08	t	\N
4230	549	\N	080901	物理电子学	\N	0809	[]	[]	academic	2026-10-19 03:14:45.472862+08	t	\N
4231	549	\N	080904	电磁场与微波技术	\N	0809	[]	[]	academic	2026-10-19 03:14:45.472865+08	t	\N
4232	549	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 03:14:45.472865+08	t	\N
4233	549	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 03:14:45.472866+08	t	\N
4234	549	\N	0810Z1	信息安全	\N	0810	[]	[]	academic	2026-10-19 03:14:45.472866+08	t	\N
4235	549	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:14:45.472867+08	t	\N
4236	549	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:14:45.472867+08	t	\N
4237	549	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:14:45.472867+08	t	\N
4238	549	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:14:45.472868+08	t	\N
4239	550	\N	082401	船舶与海洋结构物设计制造	\N	0824	[]	[]	academic	2026-10-19 03:14:52.233703+08	t	\N
4240	550	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:14:52.233709+08	t	\N
4241	550	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:14:52.233711+08	t	\N
4242	551	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:14:58.678246+08	t	\N
4243	551	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:14:58.678255+08	t	\N
4244	551	\N	087100	管理科学与工程	\N	0871	[]	[]	academic	2026-10-19 03:14:58.678259+08	t	\N
4245	552	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:15:05.119973+08	t	\N
4246	552	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:15:05.119975+08	t	\N
4247	552	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:15:05.119976+08	t	\N
4248	552	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:15:05.119976+08	t	\N
4249	552	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:15:05.119977+08	t	\N
4250	552	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:15:05.119977+08	t	\N
4251	552	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:15:05.119977+08	t	\N
4252	552	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:15:05.119978+08	t	\N
4253	552	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:15:05.119978+08	t	\N
4254	552	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:15:05.119979+08	t	\N
4255	552	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:15:05.119979+08	t	\N
4256	552	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:15:05.119979+08	t	\N
4257	552	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:15:05.11998+08	t	\N
4258	552	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:15:05.11998+08	t	\N
4259	552	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:15:05.119981+08	t	\N
4260	552	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 03:15:05.119981+08	t	\N
4261	552	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:15:05.119982+08	t	\N
4262	552	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:15:05.119982+08	t	\N
4263	553	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:15:12.044172+08	t	\N
4264	553	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:15:12.044174+08	t	\N
4265	553	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:15:12.044174+08	t	\N
4266	553	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:15:12.044175+08	t	\N
4267	553	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:15:12.044175+08	t	\N
4268	553	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:15:12.044176+08	t	\N
4269	553	\N	085407	仪器仪表工程	\N	0854	[]	[]	professional	2026-10-19 03:15:12.044176+08	t	\N
4270	553	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:15:12.044177+08	t	\N
4271	553	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:15:12.044177+08	t	\N
4272	553	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:15:12.044178+08	t	\N
4273	553	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:15:12.044178+08	t	\N
4274	553	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:15:12.044178+08	t	\N
4275	553	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:15:12.044179+08	t	\N
4276	553	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:15:12.044179+08	t	\N
4277	554	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:15:18.821928+08	t	\N
4278	554	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:15:18.82193+08	t	\N
4279	554	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:15:18.821931+08	t	\N
4280	554	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:15:18.821931+08	t	\N
4281	554	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:15:18.821932+08	t	\N
4282	554	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:15:18.821932+08	t	\N
4283	554	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:15:18.821933+08	t	\N
4284	554	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:15:18.821933+08	t	\N
4285	554	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 03:15:18.821933+08	t	\N
4286	554	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:15:18.821934+08	t	\N
4287	554	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:15:18.821934+08	t	\N
4288	555	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:15:25.672428+08	t	\N
4289	555	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:15:25.67243+08	t	\N
4290	555	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:15:25.672431+08	t	\N
4291	555	\N	0812J4	数字媒体技术	\N	0812	[]	[]	academic	2026-10-19 03:15:25.672431+08	t	\N
4292	555	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:15:25.672431+08	t	\N
4293	555	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:15:25.672432+08	t	\N
4294	555	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:15:25.672432+08	t	\N
4295	555	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:15:25.672433+08	t	\N
4296	555	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:15:25.672433+08	t	\N
4297	555	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:15:25.672433+08	t	\N
4298	555	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:15:25.672434+08	t	\N
4299	555	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:15:25.672434+08	t	\N
4300	555	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:15:25.672435+08	t	\N
4301	555	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 03:15:25.672435+08	t	\N
4302	555	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:15:25.672436+08	t	\N
4303	555	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:15:25.672436+08	t	\N
4304	555	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:15:25.672436+08	t	\N
4305	555	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:15:25.672437+08	t	\N
4306	555	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 03:15:25.672437+08	t	\N
4307	556	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:15:32.207711+08	t	\N
4308	556	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:15:32.207714+08	t	\N
4309	556	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 03:15:32.207714+08	t	\N
4310	556	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 03:15:32.207715+08	t	\N
4311	556	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 03:15:32.207715+08	t	\N
4312	556	\N	0828Z1	现代农业装备工程	\N	0828	[]	[]	academic	2026-10-19 03:15:32.207716+08	t	\N
4313	556	\N	0828Z4	智慧农业技术与装备	\N	0828	[]	[]	academic	2026-10-19 03:15:32.207716+08	t	\N
4314	556	\N	083001	环境科学	\N	0830	[]	[]	academic	2026-10-19 03:15:32.207716+08	t	\N
4315	556	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 03:15:32.207717+08	t	\N
4316	556	\N	0830Z1	环境规划与管理	\N	0830	[]	[]	academic	2026-10-19 03:15:32.207717+08	t	\N
4317	556	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:15:32.207718+08	t	\N
4318	556	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:15:32.207718+08	t	\N
4319	556	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:15:32.207718+08	t	\N
4320	556	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:15:32.207719+08	t	\N
4321	556	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:15:32.207719+08	t	\N
4322	556	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:15:32.20772+08	t	\N
4323	556	\N	0710Z1	生物信息学	\N	0710	[]	[]	academic	2026-10-19 03:15:32.20772+08	t	\N
4324	556	\N	0710Z6	智能生物学	\N	0710	[]	[]	academic	2026-10-19 03:15:32.20772+08	t	\N
4325	556	\N	0710Z7	主动健康生物学	\N	0710	[]	[]	academic	2026-10-19 03:15:32.207721+08	t	\N
4326	556	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:15:32.207721+08	t	\N
4327	557	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:15:39.359973+08	t	\N
4328	557	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:15:39.359983+08	t	\N
4329	557	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:15:39.359986+08	t	\N
4330	557	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:15:39.359989+08	t	\N
4331	557	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:15:39.359991+08	t	\N
4332	557	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:15:39.359993+08	t	\N
4333	557	\N	0714Z1	经济统计学	\N	0714	[]	[]	academic	2026-10-19 03:15:39.359994+08	t	\N
4334	557	\N	0714Z2	金融统计、保险精算与风险管理	\N	0714	[]	[]	academic	2026-10-19 03:15:39.359996+08	t	\N
4335	557	\N	0714Z3	应用统计	\N	0714	[]	[]	academic	2026-10-19 03:15:39.359998+08	t	\N
4336	557	\N	0714Z4	数理统计	\N	0714	[]	[]	academic	2026-10-19 03:15:39.36+08	t	\N
4337	558	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:15:46.33532+08	t	\N
4338	558	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:15:46.335322+08	t	\N
4339	558	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:15:46.335322+08	t	\N
4340	558	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:15:46.335323+08	t	\N
4341	558	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:15:46.335323+08	t	\N
4342	558	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:15:46.335324+08	t	\N
4343	558	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:15:46.335324+08	t	\N
4344	558	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:15:46.335325+08	t	\N
4345	558	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:15:46.335325+08	t	\N
4346	558	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 03:15:46.335325+08	t	\N
4347	558	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:15:46.335326+08	t	\N
4348	558	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:15:46.335326+08	t	\N
4349	558	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:15:46.335327+08	t	\N
4350	558	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:15:46.335327+08	t	\N
4351	558	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 03:15:46.335328+08	t	\N
4352	559	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:15:52.985219+08	t	\N
4353	559	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:15:52.985227+08	t	\N
4354	559	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:15:52.985231+08	t	\N
4355	559	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:15:52.985233+08	t	\N
4356	559	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:15:52.985235+08	t	\N
4357	559	\N	082400	船舶与海洋工程	\N	0824	[]	[]	academic	2026-10-19 03:15:52.985237+08	t	\N
4358	559	\N	082600	兵器科学与技术	\N	0826	[]	[]	academic	2026-10-19 03:15:52.985239+08	t	\N
4359	559	\N	082700	核科学与技术	\N	0827	[]	[]	academic	2026-10-19 03:15:52.985241+08	t	\N
4360	559	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:15:52.985243+08	t	\N
4361	559	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:15:52.985245+08	t	\N
4362	559	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:15:52.985247+08	t	\N
4363	560	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:16:00.45417+08	t	\N
4364	560	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:16:00.454172+08	t	\N
4365	561	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:16:06.920003+08	t	\N
4366	561	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:16:06.920005+08	t	\N
4367	561	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:16:06.920006+08	t	\N
4368	561	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:16:06.920006+08	t	\N
4369	561	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:16:06.920006+08	t	\N
4370	561	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:16:06.920007+08	t	\N
4371	561	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:16:06.920007+08	t	\N
4372	561	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:16:06.920008+08	t	\N
4373	561	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:16:06.920008+08	t	\N
4374	561	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:16:06.920009+08	t	\N
4375	561	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:16:06.920009+08	t	\N
4376	561	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:16:06.920009+08	t	\N
4377	561	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:16:06.92001+08	t	\N
4378	561	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 03:16:06.92001+08	t	\N
4379	561	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:16:06.920011+08	t	\N
4380	562	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:16:14.070325+08	t	\N
4381	562	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:16:14.070334+08	t	\N
4382	562	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:16:14.070338+08	t	\N
4383	562	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:16:14.07034+08	t	\N
4384	562	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:16:14.070342+08	t	\N
4385	562	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:16:14.070344+08	t	\N
4386	562	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:16:14.070346+08	t	\N
4387	562	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:16:14.070348+08	t	\N
4388	562	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:16:14.07035+08	t	\N
4389	562	\N	086003	食品工程	\N	0860	[]	[]	professional	2026-10-19 03:16:14.070351+08	t	\N
4390	562	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:16:14.070353+08	t	\N
4391	562	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:16:14.070355+08	t	\N
4392	562	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:16:14.070357+08	t	\N
4393	562	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:16:14.070359+08	t	\N
4394	562	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:16:14.070361+08	t	\N
4395	562	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:16:14.070362+08	t	\N
4396	563	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:16:21.327381+08	t	\N
4397	563	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:16:21.327383+08	t	\N
4398	563	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:16:21.327383+08	t	\N
4399	563	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:16:21.327384+08	t	\N
4400	563	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:16:21.327384+08	t	\N
4401	563	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:16:21.327385+08	t	\N
4402	563	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:16:21.327385+08	t	\N
4403	563	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:16:21.327386+08	t	\N
4404	563	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:16:21.327386+08	t	\N
4405	563	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 03:16:21.327387+08	t	\N
4406	563	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:16:21.327387+08	t	\N
4407	563	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:16:21.327387+08	t	\N
4408	563	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:16:21.327388+08	t	\N
4409	563	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:16:21.327388+08	t	\N
4410	563	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:16:21.327389+08	t	\N
4411	564	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:16:28.52957+08	t	\N
4412	564	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:16:28.529572+08	t	\N
4413	564	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:16:28.529573+08	t	\N
4414	564	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:16:28.529574+08	t	\N
4415	564	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 03:16:28.529574+08	t	\N
4416	564	\N	080601	冶金物理化学	\N	0806	[]	[]	academic	2026-10-19 03:16:28.529575+08	t	\N
4417	564	\N	080602	钢铁冶金	\N	0806	[]	[]	academic	2026-10-19 03:16:28.529575+08	t	\N
4418	564	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:16:28.529576+08	t	\N
4419	564	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:16:28.529576+08	t	\N
4420	564	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:16:28.529576+08	t	\N
4421	564	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:16:28.529577+08	t	\N
4422	564	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:16:28.529577+08	t	\N
4423	564	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:16:28.529578+08	t	\N
4424	564	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:16:28.529578+08	t	\N
4425	564	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:16:28.529579+08	t	\N
4426	564	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:16:28.529579+08	t	\N
4427	564	\N	0710Z2	生物工程	\N	0710	[]	[]	academic	2026-10-19 03:16:28.529579+08	t	\N
4428	564	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:16:28.52958+08	t	\N
4429	565	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:16:36.270495+08	t	\N
4430	565	\N	0802J1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:16:36.270498+08	t	\N
4431	565	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:16:36.270498+08	t	\N
4432	565	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:16:36.270499+08	t	\N
4433	565	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:16:36.270499+08	t	\N
4434	565	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:16:36.2705+08	t	\N
4435	565	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:16:36.2705+08	t	\N
4436	565	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:16:36.270501+08	t	\N
4437	565	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:16:36.270501+08	t	\N
4438	565	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:16:36.270502+08	t	\N
4439	565	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:16:36.270502+08	t	\N
4440	565	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:16:36.270502+08	t	\N
4441	565	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:16:36.270503+08	t	\N
4442	565	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:16:36.270503+08	t	\N
4443	566	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:16:43.701085+08	t	\N
4444	566	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:16:43.701087+08	t	\N
4445	566	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:16:43.701088+08	t	\N
4446	566	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:16:43.701088+08	t	\N
4447	566	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:16:43.701088+08	t	\N
4448	566	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:16:43.701089+08	t	\N
4449	566	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:16:43.70109+08	t	\N
4450	566	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:16:43.70109+08	t	\N
4451	566	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:16:43.70109+08	t	\N
4452	566	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:16:43.701091+08	t	\N
4453	566	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:16:43.701091+08	t	\N
4454	566	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:16:43.701092+08	t	\N
4455	566	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:16:43.701092+08	t	\N
4456	566	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:16:43.701092+08	t	\N
4457	566	\N	077400	电子科学与技术	\N	0774	[]	[]	academic	2026-10-19 03:16:43.701093+08	t	\N
4458	567	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:16:50.869877+08	t	\N
4459	567	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 03:16:50.869879+08	t	\N
4460	567	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:16:50.86988+08	t	\N
4461	567	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:16:50.86988+08	t	\N
4462	567	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:16:50.869881+08	t	\N
4463	567	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:16:50.869881+08	t	\N
4464	567	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:16:50.869882+08	t	\N
4465	567	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:16:50.869882+08	t	\N
4466	567	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:16:50.869882+08	t	\N
4467	567	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:16:50.869883+08	t	\N
4468	567	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:16:50.869883+08	t	\N
4469	567	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:16:50.869884+08	t	\N
4470	567	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:16:50.869884+08	t	\N
4471	568	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:16:58.218425+08	t	\N
4472	568	\N	0802J2	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:16:58.218431+08	t	\N
4473	568	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:16:58.218433+08	t	\N
4474	568	\N	0805Z1	新能源技术和储能技术	\N	0805	[]	[]	academic	2026-10-19 03:16:58.218434+08	t	\N
4475	568	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:16:58.218435+08	t	\N
4476	568	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:16:58.218437+08	t	\N
4477	568	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:16:58.218438+08	t	\N
4478	568	\N	082900	林业工程	\N	0829	[]	[]	academic	2026-10-19 03:16:58.218439+08	t	\N
4479	568	\N	0829Z1	碳达峰碳中和	\N	0829	[]	[]	academic	2026-10-19 03:16:58.218441+08	t	\N
4480	568	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:16:58.218442+08	t	\N
4481	568	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:16:58.218443+08	t	\N
4482	568	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:16:58.218444+08	t	\N
4483	569	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:17:04.138302+08	t	\N
4484	570	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:17:10.861571+08	t	\N
4485	570	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:17:10.861581+08	t	\N
4486	570	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:17:10.861584+08	t	\N
4487	570	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:17:10.861587+08	t	\N
4488	570	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:17:10.861589+08	t	\N
4489	570	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:17:10.861591+08	t	\N
4490	570	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:17:10.861593+08	t	\N
4491	570	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:17:10.861596+08	t	\N
4492	570	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:17:10.861598+08	t	\N
4493	570	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:17:10.8616+08	t	\N
4494	570	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:17:10.861601+08	t	\N
4495	570	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:17:10.861603+08	t	\N
4496	570	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:17:10.861605+08	t	\N
4497	570	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 03:17:10.861607+08	t	\N
4498	570	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:17:10.861609+08	t	\N
4499	570	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:17:10.861611+08	t	\N
4500	570	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 03:17:10.861613+08	t	\N
4501	570	\N	0705J2	旅游地理学	\N	0705	[]	[]	academic	2026-10-19 03:17:10.861615+08	t	\N
4502	570	\N	0705Z1	国土资源利用与管理	\N	0705	[]	[]	academic	2026-10-19 03:17:10.861616+08	t	\N
4503	570	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 03:17:10.861618+08	t	\N
4504	571	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:17:16.516322+08	t	\N
4505	571	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:17:16.516328+08	t	\N
4506	571	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:17:16.51633+08	t	\N
4507	571	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:17:16.516331+08	t	\N
4508	571	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:17:16.516333+08	t	\N
4509	571	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:17:16.516334+08	t	\N
4510	571	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:17:16.516335+08	t	\N
4511	571	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:17:16.516337+08	t	\N
4512	571	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:17:16.516338+08	t	\N
4513	571	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:17:16.51634+08	t	\N
4514	571	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:17:16.516341+08	t	\N
4515	572	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:17:22.765393+08	t	\N
4516	572	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:17:22.765402+08	t	\N
4517	573	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:17:29.638643+08	t	\N
4518	573	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:17:29.638649+08	t	\N
4519	574	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:17:35.94851+08	t	\N
4520	574	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:17:35.948516+08	t	\N
4521	576	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:17:50.008014+08	t	\N
4522	576	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:17:50.008017+08	t	\N
4523	577	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:17:56.791994+08	t	\N
4524	577	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 03:17:56.792003+08	t	\N
4525	577	\N	085509	智能制造技术	\N	0855	[]	[]	professional	2026-10-19 03:17:56.792006+08	t	\N
4526	577	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:17:56.792008+08	t	\N
4527	577	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:17:56.79201+08	t	\N
4528	577	\N	085604	纺织工程	\N	0856	[]	[]	professional	2026-10-19 03:17:56.792012+08	t	\N
4529	577	\N	085606	轻化工程（含皮革、纸张、织物加工等）	\N	0856	[]	[]	professional	2026-10-19 03:17:56.792014+08	t	\N
4530	577	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 03:17:56.792016+08	t	\N
4531	577	\N	085802	动力工程	\N	0858	[]	[]	professional	2026-10-19 03:17:56.792018+08	t	\N
4532	577	\N	085807	清洁能源技术	\N	0858	[]	[]	professional	2026-10-19 03:17:56.792019+08	t	\N
4533	578	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:18:03.381822+08	t	\N
4534	578	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:18:03.381824+08	t	\N
4535	578	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:18:03.381825+08	t	\N
4536	578	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:18:03.381825+08	t	\N
4537	578	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 03:18:03.381826+08	t	\N
4538	578	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:18:03.381826+08	t	\N
4539	580	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:18:17.139378+08	t	\N
4540	581	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:18:23.415544+08	t	\N
4541	581	\N	080603	有色金属冶金	\N	0806	[]	[]	academic	2026-10-19 03:18:23.415554+08	t	\N
4542	581	\N	081901	采矿工程	\N	0819	[]	[]	academic	2026-10-19 03:18:23.415557+08	t	\N
4543	581	\N	081902	矿物加工工程	\N	0819	[]	[]	academic	2026-10-19 03:18:23.41556+08	t	\N
4544	582	\N	082502	航空宇航推进理论与工程	\N	0825	[]	[]	academic	2026-10-19 03:18:31.045702+08	t	\N
4545	583	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 03:18:37.684225+08	t	\N
4546	583	\N	081901	采矿工程	\N	0819	[]	[]	academic	2026-10-19 03:18:37.684228+08	t	\N
4547	585	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:18:50.418358+08	t	\N
4548	585	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:18:50.418364+08	t	\N
4549	585	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:18:50.418365+08	t	\N
4550	585	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:18:50.418367+08	t	\N
4622	590	\N	080102	固体力学	\N	0801	[]	[]	academic	2026-10-19 03:19:24.394946+08	t	\N
4551	585	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:18:50.418368+08	t	\N
4552	585	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:18:50.418369+08	t	\N
4553	585	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:18:50.418371+08	t	\N
4554	585	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:18:50.418372+08	t	\N
4555	585	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:18:50.418373+08	t	\N
4556	585	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:18:50.418375+08	t	\N
4557	585	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:18:50.418376+08	t	\N
4558	585	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:18:50.418377+08	t	\N
4559	585	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:18:50.418379+08	t	\N
4560	586	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:18:56.754242+08	t	\N
4561	586	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:18:56.754244+08	t	\N
4562	586	\N	0835J1	人工智能	\N	0835	[]	[]	academic	2026-10-19 03:18:56.754245+08	t	\N
4563	586	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:18:56.754245+08	t	\N
4564	586	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:18:56.754246+08	t	\N
4565	586	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:18:56.754246+08	t	\N
4566	586	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:18:56.754247+08	t	\N
4567	586	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:18:56.754247+08	t	\N
4568	586	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:18:56.754247+08	t	\N
4569	586	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:18:56.754248+08	t	\N
4570	586	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:18:56.754248+08	t	\N
4571	587	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:19:03.863921+08	t	\N
4572	587	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:19:03.863944+08	t	\N
4573	587	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:19:03.863945+08	t	\N
4574	587	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:19:03.863946+08	t	\N
4575	587	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:19:03.863947+08	t	\N
4576	587	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:19:03.863967+08	t	\N
4577	587	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:19:03.863968+08	t	\N
4578	587	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:19:03.863969+08	t	\N
4579	587	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:19:03.863969+08	t	\N
4580	587	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:19:03.86397+08	t	\N
4581	587	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:19:03.863971+08	t	\N
4582	587	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:19:03.863971+08	t	\N
4583	587	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:19:03.863972+08	t	\N
4584	587	\N	070600	大气科学	\N	0706	[]	[]	academic	2026-10-19 03:19:03.863972+08	t	\N
4585	587	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 03:19:03.863992+08	t	\N
4586	587	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:19:03.863993+08	t	\N
4587	587	\N	079901	量子信息科学与技术	\N	0799	[]	[]	academic	2026-10-19 03:19:03.863993+08	t	\N
4588	588	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:19:11.008935+08	t	\N
4589	588	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:19:11.008942+08	t	\N
4590	588	\N	0805J2	包装工程与设计	\N	0805	[]	[]	academic	2026-10-19 03:19:11.008944+08	t	\N
4591	588	\N	0805Z1	包装工程	\N	0805	[]	[]	academic	2026-10-19 03:19:11.008946+08	t	\N
4592	588	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 03:19:11.008947+08	t	\N
4593	588	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:19:11.00895+08	t	\N
4594	588	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:19:11.008951+08	t	\N
4595	588	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:19:11.008953+08	t	\N
4596	588	\N	0812Z1	低空技术与工程	\N	0812	[]	[]	academic	2026-10-19 03:19:11.008954+08	t	\N
4597	588	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:19:11.008955+08	t	\N
4598	588	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:19:11.008957+08	t	\N
4599	588	\N	077300	材料科学与工程	\N	0773	[]	[]	academic	2026-10-19 03:19:11.008958+08	t	\N
4600	588	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 03:19:11.008959+08	t	\N
4601	589	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:19:17.148699+08	t	\N
4602	589	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:19:17.148709+08	t	\N
4603	589	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:19:17.148713+08	t	\N
4604	589	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:19:17.148715+08	t	\N
4605	589	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:19:17.148717+08	t	\N
4606	589	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:19:17.148719+08	t	\N
4607	589	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:19:17.148721+08	t	\N
4608	589	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:19:17.148723+08	t	\N
4609	589	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:19:17.148725+08	t	\N
4610	589	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:19:17.148727+08	t	\N
4611	589	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:19:17.148729+08	t	\N
4612	589	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:19:17.148731+08	t	\N
4613	589	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:19:17.148733+08	t	\N
4614	589	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 03:19:17.148735+08	t	\N
4615	589	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:19:17.148737+08	t	\N
4616	589	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:19:17.148739+08	t	\N
4617	589	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 03:19:17.148741+08	t	\N
4618	589	\N	070600	大气科学	\N	0706	[]	[]	academic	2026-10-19 03:19:17.148743+08	t	\N
4619	589	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 03:19:17.148745+08	t	\N
4620	589	\N	070703	海洋生物学	\N	0707	[]	[]	academic	2026-10-19 03:19:17.148747+08	t	\N
4621	590	\N	080101	一般力学与力学基础	\N	0801	[]	[]	academic	2026-10-19 03:19:24.394943+08	t	\N
4623	590	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 03:19:24.394947+08	t	\N
4624	590	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:19:24.394948+08	t	\N
4625	590	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 03:19:24.394948+08	t	\N
4626	590	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:19:24.394949+08	t	\N
4627	590	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:19:24.394949+08	t	\N
4628	590	\N	0805Z1	生物材料	\N	0805	[]	[]	academic	2026-10-19 03:19:24.39495+08	t	\N
4629	590	\N	080902	电路与系统	\N	0809	[]	[]	academic	2026-10-19 03:19:24.39495+08	t	\N
4630	590	\N	080903	微电子学与固体电子学	\N	0809	[]	[]	academic	2026-10-19 03:19:24.394951+08	t	\N
4631	590	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:19:24.394951+08	t	\N
4632	590	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:19:24.394951+08	t	\N
4633	590	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:19:24.394952+08	t	\N
4634	590	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:19:24.394952+08	t	\N
4635	590	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:19:24.394953+08	t	\N
4636	590	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:19:24.394953+08	t	\N
4637	590	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:19:24.394953+08	t	\N
4638	590	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 03:19:24.394954+08	t	\N
4639	590	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:19:24.394954+08	t	\N
4640	590	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:19:24.394955+08	t	\N
4641	591	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:19:31.224952+08	t	\N
4642	591	\N	0802Z1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:19:31.224958+08	t	\N
4643	591	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:19:31.22496+08	t	\N
4644	591	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:19:31.224961+08	t	\N
4645	591	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:19:31.224962+08	t	\N
4646	591	\N	081705	工业催化	\N	0817	[]	[]	academic	2026-10-19 03:19:31.224964+08	t	\N
4647	591	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:19:31.224965+08	t	\N
4648	591	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:19:31.224967+08	t	\N
4649	591	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:19:31.224968+08	t	\N
4650	591	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:19:31.22497+08	t	\N
4651	591	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:19:31.224971+08	t	\N
4652	591	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:19:31.224972+08	t	\N
4653	591	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:19:31.224974+08	t	\N
4654	591	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:19:31.224975+08	t	\N
4655	591	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:19:31.224976+08	t	\N
4656	591	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:19:31.224978+08	t	\N
4657	591	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 03:19:31.224979+08	t	\N
4658	591	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:19:31.22498+08	t	\N
4659	592	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:19:38.051022+08	t	\N
4660	592	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:19:38.051024+08	t	\N
4661	592	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:19:38.051025+08	t	\N
4662	592	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:19:38.051025+08	t	\N
4663	592	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:19:38.051026+08	t	\N
4664	592	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:19:38.051026+08	t	\N
4665	592	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:19:38.051027+08	t	\N
4666	592	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:19:38.051027+08	t	\N
4667	592	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:19:38.051028+08	t	\N
4668	592	\N	081301	建筑历史与理论	\N	0813	[]	[]	academic	2026-10-19 03:19:38.051028+08	t	\N
4669	592	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:19:38.051028+08	t	\N
4670	592	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:19:38.051029+08	t	\N
4671	592	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:19:38.051029+08	t	\N
4672	592	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:19:38.05103+08	t	\N
4673	592	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:19:38.05103+08	t	\N
4674	592	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:19:38.05103+08	t	\N
4675	592	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:19:38.051031+08	t	\N
4676	592	\N	070206	声学	\N	0702	[]	[]	academic	2026-10-19 03:19:38.051031+08	t	\N
4677	592	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:19:38.051032+08	t	\N
4678	592	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:19:38.051032+08	t	\N
4679	593	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:19:45.44088+08	t	\N
4680	593	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:19:45.440882+08	t	\N
4681	593	\N	0810Z1	低空技术与工程	\N	0810	[]	[]	academic	2026-10-19 03:19:45.440882+08	t	\N
4682	593	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:19:45.440883+08	t	\N
4683	593	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:19:45.440883+08	t	\N
4684	593	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 03:19:45.440884+08	t	\N
4685	593	\N	082900	林业工程	\N	0829	[]	[]	academic	2026-10-19 03:19:45.440884+08	t	\N
4686	593	\N	0829J2	家居智能设计与工程	\N	0829	[]	[]	academic	2026-10-19 03:19:45.440885+08	t	\N
4687	593	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:19:45.440885+08	t	\N
4688	593	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:19:45.440885+08	t	\N
4689	593	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:19:45.440886+08	t	\N
4690	593	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:19:45.440886+08	t	\N
4691	593	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 03:19:45.440887+08	t	\N
4692	593	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:19:45.440887+08	t	\N
4693	594	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:19:51.803711+08	t	\N
4694	594	\N	0802Z1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:19:51.803713+08	t	\N
4695	594	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:19:51.803714+08	t	\N
4696	594	\N	082400	船舶与海洋工程	\N	0824	[]	[]	academic	2026-10-19 03:19:51.803715+08	t	\N
4697	594	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:19:51.803715+08	t	\N
4698	594	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:19:51.803715+08	t	\N
4699	594	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:19:51.803716+08	t	\N
4700	594	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:19:51.803716+08	t	\N
4701	594	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:19:51.803717+08	t	\N
4702	594	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:19:51.803717+08	t	\N
4703	594	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 03:19:51.803717+08	t	\N
4704	594	\N	0707Z2	海洋技术	\N	0707	[]	[]	academic	2026-10-19 03:19:51.803718+08	t	\N
4705	594	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 03:19:51.803718+08	t	\N
4706	595	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:19:58.124384+08	t	\N
4707	595	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:19:58.12439+08	t	\N
4708	595	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:19:58.124392+08	t	\N
4709	595	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:19:58.124393+08	t	\N
4710	595	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:19:58.124395+08	t	\N
4711	595	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:19:58.124396+08	t	\N
4712	595	\N	071008	发育生物学	\N	0710	[]	[]	academic	2026-10-19 03:19:58.124397+08	t	\N
4713	595	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:19:58.124399+08	t	\N
4714	595	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:19:58.1244+08	t	\N
4715	595	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 03:19:58.124401+08	t	\N
4716	596	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:20:04.025203+08	t	\N
4717	596	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:20:04.025213+08	t	\N
4718	596	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:20:04.025216+08	t	\N
4719	596	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:20:04.025218+08	t	\N
4720	596	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:20:04.025221+08	t	\N
4721	598	\N	083600	生物工程	\N	0836	[]	[]	academic	2026-10-19 03:20:15.889782+08	t	\N
4722	598	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:20:15.889791+08	t	\N
4723	598	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:20:15.889794+08	t	\N
4724	599	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:20:21.764441+08	t	\N
4725	599	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:20:21.764451+08	t	\N
4726	600	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:20:28.564851+08	t	\N
4727	600	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:20:28.564853+08	t	\N
4728	600	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:20:28.564854+08	t	\N
4729	600	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:20:28.564854+08	t	\N
4730	600	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:20:28.564855+08	t	\N
4731	601	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:20:35.295278+08	t	\N
4732	601	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:20:35.295288+08	t	\N
4733	601	\N	086003	食品工程	\N	0860	[]	[]	professional	2026-10-19 03:20:35.295291+08	t	\N
4734	602	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:20:41.428279+08	t	\N
4735	602	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:20:41.428285+08	t	\N
4736	603	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:20:47.672743+08	t	\N
4737	603	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:20:47.672753+08	t	\N
4738	603	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:20:47.672756+08	t	\N
4739	603	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:20:47.672758+08	t	\N
4740	606	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:21:08.336551+08	t	\N
4741	606	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 03:21:08.33656+08	t	\N
4742	608	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:21:20.732238+08	t	\N
4743	608	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 03:21:20.732241+08	t	\N
4744	608	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:21:20.732241+08	t	\N
4745	608	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:21:20.732242+08	t	\N
4746	608	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:21:20.732242+08	t	\N
4747	608	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:21:20.732243+08	t	\N
4748	608	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 03:21:20.732243+08	t	\N
4749	611	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:21:41.161211+08	t	\N
4750	611	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:21:41.161213+08	t	\N
4751	611	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:21:41.161214+08	t	\N
4752	611	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:21:41.161214+08	t	\N
4753	611	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:21:41.161215+08	t	\N
4754	611	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:21:41.161215+08	t	\N
4755	611	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:21:41.161216+08	t	\N
4756	611	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:21:41.161216+08	t	\N
4757	611	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:21:41.161216+08	t	\N
4758	611	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 03:21:41.161217+08	t	\N
4759	611	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:21:41.161217+08	t	\N
4760	612	\N	083700	安全科学与工程	\N	0837	[]	[]	academic	2026-10-19 03:21:48.061758+08	t	\N
4761	612	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:21:48.061762+08	t	\N
4762	612	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:21:48.061762+08	t	\N
4763	612	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:21:48.061763+08	t	\N
4764	612	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:21:48.061763+08	t	\N
4765	614	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:22:00.832475+08	t	\N
4766	614	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:22:00.832481+08	t	\N
4767	614	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:22:00.832483+08	t	\N
4768	614	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:22:00.832484+08	t	\N
4769	614	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:22:00.832486+08	t	\N
4770	614	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:22:00.832487+08	t	\N
4771	614	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:22:00.832489+08	t	\N
4772	614	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:22:00.83249+08	t	\N
4773	614	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:22:00.832491+08	t	\N
4774	614	\N	085703	地质工程	\N	0857	[]	[]	professional	2026-10-19 03:22:00.832493+08	t	\N
4775	615	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:22:07.125806+08	t	\N
4776	615	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:22:07.125815+08	t	\N
4777	615	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:22:07.125819+08	t	\N
4778	615	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:22:07.125821+08	t	\N
4779	615	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 03:22:07.125823+08	t	\N
4780	615	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:22:07.125825+08	t	\N
4781	615	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:22:07.125827+08	t	\N
4782	615	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:22:07.125829+08	t	\N
4783	615	\N	080903	微电子学与固体电子学	\N	0809	[]	[]	academic	2026-10-19 03:22:07.12583+08	t	\N
4784	615	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:22:07.125832+08	t	\N
4785	615	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:22:07.125835+08	t	\N
4786	616	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:22:15.187813+08	t	\N
4787	616	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:22:15.187816+08	t	\N
4788	616	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:22:15.187816+08	t	\N
4789	616	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:22:15.187817+08	t	\N
4790	618	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:22:28.728111+08	t	\N
4791	618	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:22:28.728117+08	t	\N
4792	618	\N	0812J1	低空技术与工程	\N	0812	[]	[]	academic	2026-10-19 03:22:28.728118+08	t	\N
4793	618	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:22:28.728119+08	t	\N
4794	618	\N	081405	防灾减灾工程及防护工程	\N	0814	[]	[]	academic	2026-10-19 03:22:28.72812+08	t	\N
4795	618	\N	0814J1	低空技术与工程	\N	0814	[]	[]	academic	2026-10-19 03:22:28.728121+08	t	\N
4796	618	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:22:28.728122+08	t	\N
4797	618	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:22:28.728123+08	t	\N
4798	618	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:22:28.728156+08	t	\N
4799	618	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:22:28.728158+08	t	\N
4800	618	\N	077000	集成电路科学与工程	\N	0770	[]	[]	academic	2026-10-19 03:22:28.728159+08	t	\N
4801	618	\N	077500	计算机科学与技术	\N	0775	[]	[]	academic	2026-10-19 03:22:28.72816+08	t	\N
4802	619	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:22:36.065136+08	t	\N
4803	619	\N	0801Z1	智能制造与机器人	\N	0801	[]	[]	academic	2026-10-19 03:22:36.065139+08	t	\N
4804	619	\N	0801Z2	低空技术与工程	\N	0801	[]	[]	academic	2026-10-19 03:22:36.065139+08	t	\N
4805	619	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:22:36.06514+08	t	\N
4806	619	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:22:36.06514+08	t	\N
4807	619	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:22:36.065141+08	t	\N
4808	619	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:22:36.065141+08	t	\N
4809	619	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:22:36.065141+08	t	\N
4810	619	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:22:36.065142+08	t	\N
4811	619	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:22:36.065142+08	t	\N
4812	619	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:22:36.065143+08	t	\N
4813	619	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:22:36.065143+08	t	\N
4814	619	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:22:36.065144+08	t	\N
4815	619	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 03:22:36.065144+08	t	\N
4816	619	\N	0708Z1	海洋地球物理学	\N	0708	[]	[]	academic	2026-10-19 03:22:36.065144+08	t	\N
4817	619	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:22:36.065145+08	t	\N
4818	620	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:22:42.963057+08	t	\N
4819	620	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:22:42.963059+08	t	\N
4820	620	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:22:42.96306+08	t	\N
4821	620	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:22:42.96306+08	t	\N
4822	620	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:22:42.963061+08	t	\N
4823	620	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:22:42.963061+08	t	\N
4824	620	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:22:42.963062+08	t	\N
4825	620	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:22:42.963062+08	t	\N
4826	620	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:22:42.963063+08	t	\N
4827	620	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:22:42.963063+08	t	\N
4828	620	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:22:42.963063+08	t	\N
4829	620	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:22:42.963064+08	t	\N
4830	620	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:22:42.963064+08	t	\N
4831	620	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:22:42.963065+08	t	\N
4832	620	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:22:42.963065+08	t	\N
4833	620	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:22:42.963066+08	t	\N
4834	620	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 03:22:42.963066+08	t	\N
4835	621	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:22:49.053012+08	t	\N
4836	621	\N	0831Z1	医学人工智能	\N	0831	[]	[]	academic	2026-10-19 03:22:49.053018+08	t	\N
4837	621	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 03:22:49.05302+08	t	\N
4838	621	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:22:49.053022+08	t	\N
4839	621	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 03:22:49.053023+08	t	\N
4840	621	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:22:49.053024+08	t	\N
4841	621	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 03:22:49.053026+08	t	\N
4842	621	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:22:49.053027+08	t	\N
4843	621	\N	071008	发育生物学	\N	0710	[]	[]	academic	2026-10-19 03:22:49.053028+08	t	\N
4844	621	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:22:49.05303+08	t	\N
4845	621	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:22:49.053031+08	t	\N
4846	621	\N	0710J3	生物信息学	\N	0710	[]	[]	academic	2026-10-19 03:22:49.053033+08	t	\N
4847	622	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:22:56.367516+08	t	\N
4848	622	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:22:56.367519+08	t	\N
4849	622	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:22:56.36752+08	t	\N
4850	622	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:22:56.36752+08	t	\N
4851	622	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:22:56.367521+08	t	\N
4852	622	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:22:56.367521+08	t	\N
4853	622	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:22:56.367522+08	t	\N
4854	622	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:22:56.367522+08	t	\N
4855	622	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:22:56.367523+08	t	\N
4856	622	\N	081900	矿业工程	\N	0819	[]	[]	academic	2026-10-19 03:22:56.367523+08	t	\N
4857	622	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:22:56.367523+08	t	\N
4858	622	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:22:56.367524+08	t	\N
4859	622	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:22:56.367524+08	t	\N
4860	622	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 03:22:56.367525+08	t	\N
4861	622	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:22:56.367525+08	t	\N
4862	622	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:22:56.367526+08	t	\N
4863	623	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:23:02.956903+08	t	\N
4864	623	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:23:02.956905+08	t	\N
4865	623	\N	0802Z1	工业工程	\N	0802	[]	[]	academic	2026-10-19 03:23:02.956906+08	t	\N
4866	623	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:23:02.956906+08	t	\N
4867	623	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:23:02.956907+08	t	\N
4868	623	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:23:02.956907+08	t	\N
4869	623	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:23:02.956908+08	t	\N
4870	623	\N	082100	纺织科学与工程	\N	0821	[]	[]	academic	2026-10-19 03:23:02.956908+08	t	\N
4871	623	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:23:02.956909+08	t	\N
4872	623	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:23:02.956909+08	t	\N
4873	623	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:23:02.956909+08	t	\N
4874	623	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:23:02.95691+08	t	\N
4875	624	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:23:10.175111+08	t	\N
4876	624	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:23:10.175113+08	t	\N
4877	624	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:23:10.175114+08	t	\N
4878	624	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:23:10.175114+08	t	\N
4879	624	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:23:10.175115+08	t	\N
4880	624	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:23:10.175115+08	t	\N
4881	624	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:23:10.175116+08	t	\N
4882	624	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:23:10.175116+08	t	\N
4883	624	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:23:10.175116+08	t	\N
4884	624	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 03:23:10.175117+08	t	\N
4885	624	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:23:10.175118+08	t	\N
4886	625	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:23:16.854927+08	t	\N
4887	625	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:23:16.854929+08	t	\N
4888	625	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 03:23:16.85493+08	t	\N
4889	625	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:23:16.85493+08	t	\N
4890	625	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:23:16.854931+08	t	\N
4891	625	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:23:16.854931+08	t	\N
4892	625	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:23:16.854932+08	t	\N
4893	625	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:23:16.854932+08	t	\N
4894	625	\N	081800	地质资源与地质工程	\N	0818	[]	[]	academic	2026-10-19 03:23:16.854933+08	t	\N
4895	625	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:23:16.854933+08	t	\N
4896	625	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:23:16.854933+08	t	\N
4897	625	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:23:16.854934+08	t	\N
4898	625	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:23:16.854934+08	t	\N
4899	625	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:23:16.854935+08	t	\N
4900	625	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:23:16.854935+08	t	\N
4901	626	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:23:23.639518+08	t	\N
4902	626	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 03:23:23.639529+08	t	\N
4903	626	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:23:23.639532+08	t	\N
4904	626	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:23:23.639534+08	t	\N
4905	626	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:23:23.639536+08	t	\N
4906	626	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:23:23.639538+08	t	\N
4907	626	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:23:23.63954+08	t	\N
4908	629	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:23:41.705936+08	t	\N
4909	629	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 03:23:41.705942+08	t	\N
4910	630	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:23:48.948745+08	t	\N
4911	630	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:23:48.948755+08	t	\N
4912	630	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:23:48.948757+08	t	\N
4913	630	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:23:48.94876+08	t	\N
4914	630	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:23:48.948762+08	t	\N
4915	630	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:23:48.948764+08	t	\N
4916	630	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:23:48.948766+08	t	\N
4917	630	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:23:48.948768+08	t	\N
4918	630	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:23:48.948769+08	t	\N
4919	630	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:23:48.948771+08	t	\N
4920	630	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:23:48.948773+08	t	\N
4921	630	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:23:48.948775+08	t	\N
4922	630	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:23:48.948777+08	t	\N
4923	630	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:23:48.948779+08	t	\N
4924	630	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:23:48.948781+08	t	\N
4925	630	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:23:48.948783+08	t	\N
4926	630	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:23:48.948784+08	t	\N
4927	631	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:23:56.37323+08	t	\N
4928	631	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:23:56.37324+08	t	\N
4929	631	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:23:56.373244+08	t	\N
4930	631	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:23:56.373246+08	t	\N
4931	631	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:23:56.373248+08	t	\N
4932	631	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:23:56.37325+08	t	\N
4933	631	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:23:56.373253+08	t	\N
4934	631	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:23:56.373255+08	t	\N
4935	631	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:23:56.373257+08	t	\N
4936	631	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:23:56.373259+08	t	\N
4937	631	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:23:56.37326+08	t	\N
4938	631	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 03:23:56.373262+08	t	\N
4939	631	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:23:56.373264+08	t	\N
4940	631	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:23:56.373266+08	t	\N
4941	631	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 03:23:56.373268+08	t	\N
4942	631	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:23:56.37327+08	t	\N
4943	632	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:24:03.194101+08	t	\N
4944	632	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:24:03.194106+08	t	\N
4945	632	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:24:03.194107+08	t	\N
4946	632	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:24:03.194108+08	t	\N
4947	632	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:24:03.194108+08	t	\N
4948	632	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:24:03.194109+08	t	\N
4949	632	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:24:03.194109+08	t	\N
4950	632	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:24:03.19411+08	t	\N
4951	632	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:24:03.194111+08	t	\N
4952	632	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 03:24:03.194111+08	t	\N
4953	633	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:24:10.061183+08	t	\N
4954	634	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 03:24:17.392334+08	t	\N
4955	636	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:24:29.463144+08	t	\N
4956	638	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:24:43.167904+08	t	\N
4957	638	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:24:43.167912+08	t	\N
4958	638	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:24:43.167916+08	t	\N
4959	638	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:24:43.167918+08	t	\N
4960	638	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:24:43.16792+08	t	\N
4961	638	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:24:43.167922+08	t	\N
4962	638	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 03:24:43.167924+08	t	\N
4963	638	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:24:43.167926+08	t	\N
4964	638	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:24:43.167927+08	t	\N
4965	638	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:24:43.167929+08	t	\N
4966	638	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:24:43.167931+08	t	\N
4967	638	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:24:43.167933+08	t	\N
4968	638	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:24:43.167934+08	t	\N
4969	638	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 03:24:43.167937+08	t	\N
4970	638	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:24:43.167939+08	t	\N
4971	638	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:24:43.167941+08	t	\N
4972	639	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:24:50.52976+08	t	\N
4973	639	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:24:50.529766+08	t	\N
4974	639	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:24:50.529768+08	t	\N
4975	639	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:24:50.52977+08	t	\N
4976	639	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:24:50.529771+08	t	\N
4977	639	\N	070700	海洋科学	\N	0707	[]	[]	academic	2026-10-19 03:24:50.529772+08	t	\N
4978	640	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:24:56.513005+08	t	\N
4979	640	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:24:56.513007+08	t	\N
4980	640	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:24:56.513008+08	t	\N
4981	640	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:24:56.513008+08	t	\N
4982	640	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:24:56.513009+08	t	\N
4983	640	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:24:56.513009+08	t	\N
4984	640	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:24:56.51301+08	t	\N
4985	640	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:24:56.51301+08	t	\N
4986	640	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:24:56.51301+08	t	\N
4987	640	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:24:56.513011+08	t	\N
4988	640	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:24:56.513011+08	t	\N
4989	640	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:24:56.513012+08	t	\N
4990	640	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:24:56.513012+08	t	\N
4991	640	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:24:56.513013+08	t	\N
4992	640	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:24:56.513013+08	t	\N
4993	641	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:25:03.374622+08	t	\N
4994	641	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 03:25:03.374631+08	t	\N
4995	641	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:25:03.374634+08	t	\N
4996	641	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:25:03.374636+08	t	\N
4997	642	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:25:10.214689+08	t	\N
4998	643	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:25:16.578345+08	t	\N
4999	643	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:25:16.578348+08	t	\N
5000	643	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:25:16.578348+08	t	\N
5001	643	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:25:16.578349+08	t	\N
5002	643	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:25:16.578349+08	t	\N
5003	643	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 03:25:16.57835+08	t	\N
5004	643	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:25:16.57835+08	t	\N
5005	643	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:25:16.57835+08	t	\N
5006	643	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:25:16.578351+08	t	\N
5007	643	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:25:16.578351+08	t	\N
5008	643	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:25:16.578352+08	t	\N
5009	643	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:25:16.578352+08	t	\N
5010	643	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:25:16.578352+08	t	\N
5011	643	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:25:16.578353+08	t	\N
5012	643	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:25:16.578353+08	t	\N
5013	643	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:25:16.578354+08	t	\N
5014	643	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 03:25:16.578354+08	t	\N
5015	644	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:25:22.866929+08	t	\N
5016	644	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:25:22.866935+08	t	\N
5017	644	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:25:22.866937+08	t	\N
5018	644	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:25:22.866938+08	t	\N
5019	644	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:25:22.86694+08	t	\N
5020	644	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:25:22.866941+08	t	\N
5021	644	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:25:22.866943+08	t	\N
5022	644	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:25:22.866944+08	t	\N
5023	644	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:25:22.866945+08	t	\N
5024	644	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:25:22.866947+08	t	\N
5025	644	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:25:22.866948+08	t	\N
5026	644	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:25:22.866949+08	t	\N
5027	644	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:25:22.866951+08	t	\N
5028	644	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:25:22.866952+08	t	\N
5029	645	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:25:30.627441+08	t	\N
5030	645	\N	0801J1	生态力学	\N	0801	[]	[]	academic	2026-10-19 03:25:30.627443+08	t	\N
5031	645	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:25:30.627444+08	t	\N
5032	645	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:25:30.627444+08	t	\N
5033	645	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:25:30.627445+08	t	\N
5034	645	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:25:30.627445+08	t	\N
5035	645	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:25:30.627446+08	t	\N
5036	645	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:25:30.627446+08	t	\N
5037	645	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:25:30.627447+08	t	\N
5038	645	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 03:25:30.627447+08	t	\N
5039	645	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:25:30.627447+08	t	\N
5040	645	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:25:30.627448+08	t	\N
5041	646	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:25:37.094336+08	t	\N
5042	646	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 03:25:37.094341+08	t	\N
5043	646	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:25:37.094343+08	t	\N
5044	646	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:25:37.094344+08	t	\N
5045	646	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 03:25:37.094346+08	t	\N
5046	646	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:25:37.094347+08	t	\N
5047	646	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 03:25:37.094349+08	t	\N
5048	646	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:25:37.09435+08	t	\N
5049	646	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:25:37.094352+08	t	\N
5050	646	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:25:37.094353+08	t	\N
5051	646	\N	0710Z1	生物信息学	\N	0710	[]	[]	academic	2026-10-19 03:25:37.094354+08	t	\N
5052	647	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:25:42.727626+08	t	\N
5053	647	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:25:42.727636+08	t	\N
5054	647	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:25:42.727639+08	t	\N
5055	647	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:25:42.727642+08	t	\N
5056	647	\N	082100	纺织科学与工程	\N	0821	[]	[]	academic	2026-10-19 03:25:42.727644+08	t	\N
5057	647	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 03:25:42.727646+08	t	\N
5058	647	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 03:25:42.727648+08	t	\N
5059	647	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 03:25:42.72765+08	t	\N
5060	647	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 03:25:42.727651+08	t	\N
5061	647	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:25:42.727653+08	t	\N
5062	647	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:25:42.727655+08	t	\N
5063	647	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:25:42.727657+08	t	\N
5064	647	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:25:42.727659+08	t	\N
5065	647	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:25:42.72766+08	t	\N
5066	647	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:25:42.727662+08	t	\N
5067	647	\N	0703J1	洁净能源科学	\N	0703	[]	[]	academic	2026-10-19 03:25:42.727664+08	t	\N
5068	647	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:25:42.727666+08	t	\N
5069	647	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:25:42.727667+08	t	\N
5070	647	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 03:25:42.727669+08	t	\N
5071	647	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:25:42.727671+08	t	\N
5072	648	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:25:50.016996+08	t	\N
5073	648	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:25:50.016999+08	t	\N
5074	648	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:25:50.017+08	t	\N
5075	648	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:25:50.017001+08	t	\N
5076	648	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:25:50.017001+08	t	\N
5077	648	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:25:50.017002+08	t	\N
5078	648	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:25:50.017002+08	t	\N
5079	648	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:25:50.017002+08	t	\N
5080	648	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:25:50.017003+08	t	\N
5081	648	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:25:50.017003+08	t	\N
5082	648	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:25:50.017004+08	t	\N
5083	648	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:25:50.017004+08	t	\N
5084	648	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:25:50.017004+08	t	\N
5085	648	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:25:50.017005+08	t	\N
5086	648	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:25:50.017005+08	t	\N
5087	648	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:25:50.017006+08	t	\N
5088	648	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:25:50.017006+08	t	\N
5089	648	\N	077100	心理学	\N	0771	[]	[]	academic	2026-10-19 03:25:50.017007+08	t	\N
5090	648	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 03:25:50.017007+08	t	\N
5091	649	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:25:56.72621+08	t	\N
5092	649	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:25:56.726219+08	t	\N
5093	649	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:25:56.726222+08	t	\N
5094	649	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 03:25:56.726225+08	t	\N
5095	649	\N	085503	航空工程	\N	0855	[]	[]	professional	2026-10-19 03:25:56.726227+08	t	\N
5096	649	\N	085508	农机装备工程	\N	0855	[]	[]	professional	2026-10-19 03:25:56.726229+08	t	\N
5097	649	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:25:56.726231+08	t	\N
5098	649	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:25:56.726233+08	t	\N
5099	649	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:25:56.726235+08	t	\N
5100	649	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:25:56.726237+08	t	\N
5101	649	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:25:56.726238+08	t	\N
5102	650	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:26:02.847502+08	t	\N
5103	650	\N	0809Z1	机电系统电子技术	\N	0809	[]	[]	academic	2026-10-19 03:26:02.847505+08	t	\N
5104	650	\N	0809Z3	低空技术与工程	\N	0809	[]	[]	academic	2026-10-19 03:26:02.847505+08	t	\N
5105	650	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:26:02.847506+08	t	\N
5106	650	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:26:02.847506+08	t	\N
5107	650	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:26:02.847506+08	t	\N
5108	650	\N	085502	车辆工程	\N	0855	[]	[]	professional	2026-10-19 03:26:02.847507+08	t	\N
5109	650	\N	085508	农机装备工程	\N	0855	[]	[]	professional	2026-10-19 03:26:02.847507+08	t	\N
5110	650	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:26:02.847508+08	t	\N
5111	650	\N	085702	安全工程	\N	0857	[]	[]	professional	2026-10-19 03:26:02.847508+08	t	\N
5112	650	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:26:02.847509+08	t	\N
5113	650	\N	077600	环境科学与工程	\N	0776	[]	[]	academic	2026-10-19 03:26:02.847509+08	t	\N
5114	651	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:26:09.122886+08	t	\N
5115	651	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:26:09.12289+08	t	\N
5116	651	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:26:09.122892+08	t	\N
5117	651	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:26:09.122893+08	t	\N
5118	651	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:26:09.122895+08	t	\N
5119	654	\N	082000	石油与天然气工程	\N	0820	[]	[]	academic	2026-10-19 03:26:28.515928+08	t	\N
5120	654	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:26:28.51593+08	t	\N
5121	654	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:26:28.515931+08	t	\N
5122	654	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:26:28.515931+08	t	\N
5123	654	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:26:28.515932+08	t	\N
5124	654	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:26:28.515932+08	t	\N
5125	654	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:26:28.515933+08	t	\N
5126	654	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:26:28.515933+08	t	\N
5127	654	\N	085509	智能制造技术	\N	0855	[]	[]	professional	2026-10-19 03:26:28.515934+08	t	\N
5128	654	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:26:28.515934+08	t	\N
5129	654	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:26:28.515934+08	t	\N
5130	655	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 03:26:35.946836+08	t	\N
5131	657	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:26:48.880361+08	t	\N
5132	657	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:26:48.880373+08	t	\N
5133	657	\N	0802Z2	地面武器机动工程	\N	0802	[]	[]	academic	2026-10-19 03:26:48.880376+08	t	\N
5134	657	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:26:48.880378+08	t	\N
5135	657	\N	0803Z1	光电隐身技术	\N	0803	[]	[]	academic	2026-10-19 03:26:48.880381+08	t	\N
5136	657	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:26:48.880383+08	t	\N
5137	657	\N	0804Z2	电气测试技术与仪器	\N	0804	[]	[]	academic	2026-10-19 03:26:48.880385+08	t	\N
5138	657	\N	0804Z3	量子传感与精密仪器	\N	0804	[]	[]	academic	2026-10-19 03:26:48.880387+08	t	\N
5139	657	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:26:48.880389+08	t	\N
5140	657	\N	0805Z2	电子光电子材料与元器件	\N	0805	[]	[]	academic	2026-10-19 03:26:48.880391+08	t	\N
5141	657	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:26:48.880393+08	t	\N
5142	657	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:26:48.880395+08	t	\N
5143	658	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:26:56.030661+08	t	\N
5144	658	\N	0802Z1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:26:56.030663+08	t	\N
5145	658	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:26:56.030664+08	t	\N
5146	658	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:26:56.030664+08	t	\N
5147	658	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:26:56.030665+08	t	\N
5148	658	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:26:56.030665+08	t	\N
5149	658	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:26:56.030666+08	t	\N
5150	658	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:26:56.030666+08	t	\N
5151	658	\N	085407	仪器仪表工程	\N	0854	[]	[]	professional	2026-10-19 03:26:56.030667+08	t	\N
5152	658	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:26:56.030667+08	t	\N
5153	658	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:26:56.030668+08	t	\N
5154	658	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:26:56.030668+08	t	\N
5155	659	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:27:02.033642+08	t	\N
5156	659	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:27:02.033645+08	t	\N
5157	659	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:27:02.033645+08	t	\N
5158	659	\N	082000	石油与天然气工程	\N	0820	[]	[]	academic	2026-10-19 03:27:02.033646+08	t	\N
5159	659	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:27:02.033646+08	t	\N
5160	659	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:27:02.033647+08	t	\N
5161	659	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:27:02.033647+08	t	\N
5162	659	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:27:02.033648+08	t	\N
5163	659	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 03:27:02.033648+08	t	\N
5164	659	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:27:02.033648+08	t	\N
5165	660	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:27:09.014292+08	t	\N
5166	660	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:27:09.014295+08	t	\N
5167	660	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:27:09.014296+08	t	\N
5168	660	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:27:09.014297+08	t	\N
5169	660	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:27:09.014297+08	t	\N
5170	660	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:27:09.014298+08	t	\N
5171	660	\N	0805Z4	纳米材料与纳米技术	\N	0805	[]	[]	academic	2026-10-19 03:27:09.014298+08	t	\N
5172	660	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:27:09.014299+08	t	\N
5173	660	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:27:09.0143+08	t	\N
5174	660	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:27:09.0143+08	t	\N
5175	660	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:27:09.014301+08	t	\N
5176	660	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:27:09.014301+08	t	\N
5177	660	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:27:09.014302+08	t	\N
5178	660	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:27:09.014302+08	t	\N
5179	660	\N	0703Z2	化学生物学	\N	0703	[]	[]	academic	2026-10-19 03:27:09.014303+08	t	\N
5180	660	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:27:09.014303+08	t	\N
5181	660	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:27:09.014304+08	t	\N
5182	660	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:27:09.014305+08	t	\N
5183	660	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:27:09.014305+08	t	\N
5184	660	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:27:09.014306+08	t	\N
5185	661	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:27:16.376263+08	t	\N
5186	661	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:27:16.376265+08	t	\N
5187	661	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:27:16.376265+08	t	\N
5188	661	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:27:16.376266+08	t	\N
5189	661	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:27:16.376266+08	t	\N
5190	661	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:27:16.376267+08	t	\N
5191	661	\N	0808Z1	轨道交通电气化与信息技术	\N	0808	[]	[]	academic	2026-10-19 03:27:16.376267+08	t	\N
5192	661	\N	0808Z2	电磁悬浮与超导工程	\N	0808	[]	[]	academic	2026-10-19 03:27:16.376268+08	t	\N
5193	661	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:27:16.376268+08	t	\N
5194	661	\N	080902	电路与系统	\N	0809	[]	[]	academic	2026-10-19 03:27:16.376269+08	t	\N
5195	661	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:27:16.376269+08	t	\N
5196	661	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:27:16.37627+08	t	\N
5197	661	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:27:16.37627+08	t	\N
5198	661	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:27:16.37627+08	t	\N
5199	661	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:27:16.376271+08	t	\N
5200	661	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:27:16.376271+08	t	\N
5201	662	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:27:22.593186+08	t	\N
5202	662	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:27:22.593188+08	t	\N
5203	662	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:27:22.593189+08	t	\N
5204	662	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:27:22.593189+08	t	\N
5205	662	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:27:22.59319+08	t	\N
5206	662	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:27:22.59319+08	t	\N
5207	662	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:27:22.593191+08	t	\N
5208	662	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:27:22.593191+08	t	\N
5209	662	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:27:22.593191+08	t	\N
5210	662	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:27:22.593192+08	t	\N
5211	662	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:27:22.593192+08	t	\N
5212	662	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:27:22.593193+08	t	\N
5213	662	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:27:22.593193+08	t	\N
5214	662	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:27:22.593193+08	t	\N
5215	662	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:27:22.593194+08	t	\N
5216	663	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:27:29.334014+08	t	\N
5217	663	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 03:27:29.334016+08	t	\N
5218	663	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:27:29.334017+08	t	\N
5219	663	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:27:29.334017+08	t	\N
5220	663	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:27:29.334018+08	t	\N
5221	663	\N	0805J4	氢能科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:27:29.334018+08	t	\N
5222	663	\N	0805J8	储能科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:27:29.334019+08	t	\N
5223	663	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:27:29.334019+08	t	\N
5224	663	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:27:29.33402+08	t	\N
5225	663	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:27:29.33402+08	t	\N
5226	663	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:27:29.33402+08	t	\N
5227	663	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:27:29.334021+08	t	\N
5228	664	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:27:36.027489+08	t	\N
5229	664	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:27:36.027497+08	t	\N
5230	664	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:27:36.027499+08	t	\N
5231	664	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:27:36.027501+08	t	\N
5232	664	\N	0810Z1	低空技术与工程	\N	0810	[]	[]	academic	2026-10-19 03:27:36.027502+08	t	\N
5233	664	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:27:36.027504+08	t	\N
5234	664	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:27:36.027505+08	t	\N
5235	664	\N	0814Z1	智能建造	\N	0814	[]	[]	academic	2026-10-19 03:27:36.027507+08	t	\N
5236	664	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:27:36.027508+08	t	\N
5237	664	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:27:36.027509+08	t	\N
5238	664	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:27:36.027511+08	t	\N
5239	664	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:27:36.027512+08	t	\N
5240	664	\N	0702Z1	量子信息科学与技术	\N	0702	[]	[]	academic	2026-10-19 03:27:36.027513+08	t	\N
5241	664	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:27:36.027515+08	t	\N
5242	664	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:27:36.027516+08	t	\N
5243	664	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 03:27:36.027517+08	t	\N
5244	664	\N	070800	地球物理学	\N	0708	[]	[]	academic	2026-10-19 03:27:36.027519+08	t	\N
5245	664	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:27:36.027521+08	t	\N
5246	665	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:27:43.840063+08	t	\N
5247	665	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:27:43.840073+08	t	\N
5248	665	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:27:43.840076+08	t	\N
5249	665	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:27:43.840079+08	t	\N
5250	665	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:27:43.840081+08	t	\N
5251	665	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:27:43.840083+08	t	\N
5252	665	\N	081800	地质资源与地质工程	\N	0818	[]	[]	academic	2026-10-19 03:27:43.840085+08	t	\N
5253	665	\N	081900	矿业工程	\N	0819	[]	[]	academic	2026-10-19 03:27:43.840087+08	t	\N
5254	665	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:27:43.840089+08	t	\N
5255	665	\N	082600	兵器科学与技术	\N	0826	[]	[]	academic	2026-10-19 03:27:43.840091+08	t	\N
5256	665	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:27:43.840093+08	t	\N
5257	665	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:27:43.840095+08	t	\N
5258	665	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:27:43.840098+08	t	\N
5259	665	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:27:43.840099+08	t	\N
5260	666	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:27:49.137099+08	t	\N
5261	666	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 03:27:49.137101+08	t	\N
5262	666	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 03:27:49.137102+08	t	\N
5263	666	\N	0810J1	气象探测技术	\N	0810	[]	[]	academic	2026-10-19 03:27:49.137102+08	t	\N
5264	666	\N	0810Z1	电子微系统工程	\N	0810	[]	[]	academic	2026-10-19 03:27:49.137103+08	t	\N
5265	666	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:27:49.137103+08	t	\N
5266	666	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:27:49.137104+08	t	\N
5267	666	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:27:49.137104+08	t	\N
5268	666	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:27:49.137105+08	t	\N
5269	666	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:27:49.137105+08	t	\N
5270	666	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:27:49.137105+08	t	\N
5271	666	\N	070600	大气科学	\N	0706	[]	[]	academic	2026-10-19 03:27:49.137106+08	t	\N
5272	666	\N	0706Z3	3S集成与气象应用	\N	0706	[]	[]	academic	2026-10-19 03:27:49.137106+08	t	\N
5273	666	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:27:49.137107+08	t	\N
5274	666	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 03:27:49.137107+08	t	\N
5275	667	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:27:56.300422+08	t	\N
5276	667	\N	0802J5	智能制造装备与系统	\N	0802	[]	[]	academic	2026-10-19 03:27:56.300424+08	t	\N
5277	667	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:27:56.300425+08	t	\N
5278	667	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:27:56.300426+08	t	\N
5279	667	\N	0811J2	人工智能	\N	0811	[]	[]	academic	2026-10-19 03:27:56.300426+08	t	\N
5280	667	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:27:56.300427+08	t	\N
5281	667	\N	0817J3	智慧化工	\N	0817	[]	[]	academic	2026-10-19 03:27:56.300427+08	t	\N
5282	667	\N	082700	核科学与技术	\N	0827	[]	[]	academic	2026-10-19 03:27:56.300427+08	t	\N
5283	667	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:27:56.300428+08	t	\N
5284	667	\N	0832J4	智能酿造工程	\N	0832	[]	[]	academic	2026-10-19 03:27:56.300428+08	t	\N
5285	667	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:27:56.300429+08	t	\N
5286	667	\N	0701J1	数据科学	\N	0701	[]	[]	academic	2026-10-19 03:27:56.300429+08	t	\N
5287	667	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:27:56.300429+08	t	\N
5288	667	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:27:56.30043+08	t	\N
5289	668	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:28:01.985851+08	t	\N
5290	668	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:28:01.985857+08	t	\N
5291	668	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:28:01.98586+08	t	\N
5292	668	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:28:01.985862+08	t	\N
5293	668	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:28:01.985863+08	t	\N
5294	668	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:28:01.985865+08	t	\N
5295	668	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:28:01.985866+08	t	\N
5296	668	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:28:01.985867+08	t	\N
5297	668	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 03:28:01.985869+08	t	\N
5298	668	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:28:01.985871+08	t	\N
5299	668	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:28:01.985872+08	t	\N
5300	668	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:28:01.985874+08	t	\N
5301	668	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:28:01.985876+08	t	\N
5302	669	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 03:28:09.053578+08	t	\N
5303	669	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:28:09.053581+08	t	\N
5304	669	\N	083700	安全科学与工程	\N	0837	[]	[]	academic	2026-10-19 03:28:09.053581+08	t	\N
5305	669	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:28:09.053582+08	t	\N
5306	669	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:28:09.053582+08	t	\N
5307	669	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:28:09.053583+08	t	\N
5308	669	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:28:09.053583+08	t	\N
5309	669	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:28:09.053584+08	t	\N
5310	669	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:28:09.053584+08	t	\N
5311	669	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:28:09.053584+08	t	\N
5312	669	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:28:09.053585+08	t	\N
5313	669	\N	070600	大气科学	\N	0706	[]	[]	academic	2026-10-19 03:28:09.053585+08	t	\N
5314	669	\N	075100	气象	\N	0751	[]	[]	professional	2026-10-19 03:28:09.053586+08	t	\N
5315	670	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:28:15.92685+08	t	\N
5316	670	\N	081403	市政工程	\N	0814	[]	[]	academic	2026-10-19 03:28:15.926852+08	t	\N
5317	670	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 03:28:15.926852+08	t	\N
5318	670	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 03:28:15.926853+08	t	\N
5319	670	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 03:28:15.926853+08	t	\N
5320	670	\N	0828Z1	农业信息工程	\N	0828	[]	[]	academic	2026-10-19 03:28:15.926854+08	t	\N
5321	670	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:28:15.926854+08	t	\N
5322	670	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:28:15.926855+08	t	\N
5323	670	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:28:15.926855+08	t	\N
5324	670	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:28:15.926855+08	t	\N
5325	670	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:28:15.926856+08	t	\N
5326	670	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:28:15.926856+08	t	\N
5327	670	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:28:15.926857+08	t	\N
5328	671	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:28:22.87112+08	t	\N
5329	672	\N	085409	生物医学工程	\N	0854	[]	[]	professional	2026-10-19 03:28:30.099091+08	t	\N
5330	672	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:28:30.099094+08	t	\N
5331	672	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:28:30.099094+08	t	\N
5332	672	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:28:30.099095+08	t	\N
5333	672	\N	077800	基础医学	\N	0778	[]	[]	academic	2026-10-19 03:28:30.099095+08	t	\N
5334	672	\N	078001	药物化学	\N	0780	[]	[]	academic	2026-10-19 03:28:30.099096+08	t	\N
5335	673	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:28:37.117859+08	t	\N
5336	673	\N	085704	测绘工程	\N	0857	[]	[]	professional	2026-10-19 03:28:37.117861+08	t	\N
5337	674	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:28:43.410971+08	t	\N
5338	674	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:28:43.410973+08	t	\N
5339	675	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:28:50.880644+08	t	\N
5340	675	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:28:50.880646+08	t	\N
5341	675	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:28:50.880647+08	t	\N
5342	675	\N	086003	食品工程	\N	0860	[]	[]	professional	2026-10-19 03:28:50.880647+08	t	\N
5343	676	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:28:57.430437+08	t	\N
5344	676	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:28:57.430443+08	t	\N
5345	679	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:29:17.866734+08	t	\N
5346	679	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:29:17.866743+08	t	\N
5347	679	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:29:17.866746+08	t	\N
5348	679	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:29:17.866748+08	t	\N
5349	679	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:29:17.866751+08	t	\N
5350	679	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:29:17.866753+08	t	\N
5351	679	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:29:17.866755+08	t	\N
5352	679	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:29:17.866757+08	t	\N
5353	680	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:29:24.794711+08	t	\N
5354	681	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 03:29:31.430619+08	t	\N
5355	682	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 03:29:37.405352+08	t	\N
5356	682	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 03:29:37.405354+08	t	\N
5357	684	\N	080804	电力电子与电力传动	\N	0808	[]	[]	academic	2026-10-19 03:29:50.655482+08	t	\N
5358	684	\N	082701	核能科学与工程	\N	0827	[]	[]	academic	2026-10-19 03:29:50.655488+08	t	\N
5359	684	\N	082703	核技术及应用	\N	0827	[]	[]	academic	2026-10-19 03:29:50.65549+08	t	\N
5360	685	\N	081103	系统工程	\N	0811	[]	[]	academic	2026-10-19 03:29:57.055738+08	t	\N
5361	685	\N	082501	飞行器设计	\N	0825	[]	[]	academic	2026-10-19 03:29:57.055744+08	t	\N
5362	686	\N	082502	航空宇航推进理论与工程	\N	0825	[]	[]	academic	2026-10-19 03:30:03.904527+08	t	\N
5363	687	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:30:10.568898+08	t	\N
5364	687	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:30:10.568907+08	t	\N
5365	687	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:30:10.56891+08	t	\N
5366	687	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:30:10.568912+08	t	\N
5367	687	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:30:10.568914+08	t	\N
5368	687	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:30:10.568916+08	t	\N
5369	687	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:30:10.568918+08	t	\N
5370	687	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:30:10.56892+08	t	\N
5371	687	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:30:10.568922+08	t	\N
5372	687	\N	085702	安全工程	\N	0857	[]	[]	professional	2026-10-19 03:30:10.568923+08	t	\N
5373	687	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:30:10.568925+08	t	\N
5374	687	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:30:10.568927+08	t	\N
5375	687	\N	0702J1	量子光电材料与器件	\N	0702	[]	[]	academic	2026-10-19 03:30:10.568929+08	t	\N
5376	687	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:30:10.56893+08	t	\N
5377	687	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:30:10.568933+08	t	\N
5378	687	\N	0705J1	低空技术与工程	\N	0705	[]	[]	academic	2026-10-19 03:30:10.568935+08	t	\N
5379	687	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:30:10.568936+08	t	\N
5380	687	\N	077101	基础心理学	\N	0771	[]	[]	academic	2026-10-19 03:30:10.568938+08	t	\N
5381	687	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 03:30:10.56894+08	t	\N
5382	688	\N	083800	公安技术	\N	0838	[]	[]	academic	2026-10-19 03:30:17.791837+08	t	\N
5383	690	\N	082701	核能科学与工程	\N	0827	[]	[]	academic	2026-10-19 03:30:32.014764+08	t	\N
5384	690	\N	082702	核燃料循环与材料	\N	0827	[]	[]	academic	2026-10-19 03:30:32.014767+08	t	\N
5385	690	\N	082703	核技术及应用	\N	0827	[]	[]	academic	2026-10-19 03:30:32.014768+08	t	\N
5386	690	\N	082704	辐射防护及环境保护	\N	0827	[]	[]	academic	2026-10-19 03:30:32.014768+08	t	\N
5387	691	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:30:38.222935+08	t	\N
5388	691	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:30:38.222941+08	t	\N
5389	691	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:30:38.222943+08	t	\N
5390	691	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:30:38.222944+08	t	\N
5391	691	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:30:38.222946+08	t	\N
5392	691	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:30:38.222947+08	t	\N
5393	691	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:30:38.222948+08	t	\N
5394	691	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:30:38.22295+08	t	\N
5395	691	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:30:38.222951+08	t	\N
5396	691	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:30:38.222952+08	t	\N
5397	691	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:30:38.222954+08	t	\N
5398	691	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 03:30:38.222955+08	t	\N
5399	691	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:30:38.222956+08	t	\N
5400	691	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:30:38.222958+08	t	\N
5401	691	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:30:38.222959+08	t	\N
5402	691	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 03:30:38.222961+08	t	\N
5403	692	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:30:44.392003+08	t	\N
5404	692	\N	086002	制药工程	\N	0860	[]	[]	professional	2026-10-19 03:30:44.392005+08	t	\N
5405	693	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:30:51.589233+08	t	\N
5406	694	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:30:58.978781+08	t	\N
5407	694	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:30:58.978789+08	t	\N
5408	694	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:30:58.978793+08	t	\N
5409	694	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:30:58.978795+08	t	\N
5410	695	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:31:06.126265+08	t	\N
5411	695	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:31:06.126267+08	t	\N
5412	695	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:31:06.126268+08	t	\N
5413	695	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:31:06.126268+08	t	\N
5414	695	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:31:06.126269+08	t	\N
5415	695	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:31:06.126269+08	t	\N
5416	695	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:31:06.126269+08	t	\N
5417	695	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:31:06.12627+08	t	\N
5418	695	\N	085407	仪器仪表工程	\N	0854	[]	[]	professional	2026-10-19 03:31:06.12627+08	t	\N
5419	695	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:31:06.126271+08	t	\N
5420	695	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:31:06.126271+08	t	\N
5421	695	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:31:06.126271+08	t	\N
5422	695	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:31:06.126272+08	t	\N
5423	696	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:31:13.16799+08	t	\N
5424	696	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:31:13.167992+08	t	\N
5425	696	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 03:31:13.167993+08	t	\N
5426	696	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:31:13.167993+08	t	\N
5427	696	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:31:13.167994+08	t	\N
5428	696	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:31:13.167994+08	t	\N
5429	696	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:31:13.167995+08	t	\N
5430	696	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:31:13.167995+08	t	\N
5431	696	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:31:13.167995+08	t	\N
5432	696	\N	081600	测绘科学与技术	\N	0816	[]	[]	academic	2026-10-19 03:31:13.167996+08	t	\N
5433	696	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:31:13.167996+08	t	\N
5434	696	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:31:13.167997+08	t	\N
5435	696	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:31:13.167997+08	t	\N
5436	696	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:31:13.167998+08	t	\N
5437	696	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 03:31:13.167998+08	t	\N
5438	696	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:31:13.167999+08	t	\N
5439	696	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:31:13.167999+08	t	\N
5440	696	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:31:13.167999+08	t	\N
5441	696	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 03:31:13.168+08	t	\N
5442	696	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:31:13.168+08	t	\N
5443	697	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:31:19.402576+08	t	\N
5444	697	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:31:19.402582+08	t	\N
5445	697	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 03:31:19.402584+08	t	\N
5446	697	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:31:19.402586+08	t	\N
5447	697	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:31:19.402587+08	t	\N
5448	697	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:31:19.402588+08	t	\N
5449	698	\N	083600	生物工程	\N	0836	[]	[]	academic	2026-10-19 03:31:25.895629+08	t	\N
5450	698	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:31:25.895634+08	t	\N
5451	698	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:31:25.895636+08	t	\N
5452	698	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:31:25.895637+08	t	\N
5453	698	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:31:25.895638+08	t	\N
5454	698	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:31:25.89564+08	t	\N
5455	699	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:31:31.919048+08	t	\N
5456	699	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:31:31.91905+08	t	\N
5457	700	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:31:39.062815+08	t	\N
5458	700	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:31:39.062817+08	t	\N
5459	700	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:31:39.062817+08	t	\N
5460	700	\N	083001	环境科学	\N	0830	[]	[]	academic	2026-10-19 03:31:39.062818+08	t	\N
5461	700	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 03:31:39.062818+08	t	\N
5462	700	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:31:39.062819+08	t	\N
5463	700	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:31:39.062819+08	t	\N
5464	700	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:31:39.062819+08	t	\N
5465	700	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:31:39.06282+08	t	\N
5466	700	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:31:39.06282+08	t	\N
5467	700	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:31:39.062821+08	t	\N
5468	700	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:31:39.062821+08	t	\N
5469	700	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:31:39.062821+08	t	\N
5470	700	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:31:39.062822+08	t	\N
5471	700	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:31:39.062822+08	t	\N
5472	700	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:31:39.062823+08	t	\N
5473	700	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:31:39.062823+08	t	\N
5474	700	\N	070400	天文学	\N	0704	[]	[]	academic	2026-10-19 03:31:39.062824+08	t	\N
5475	700	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:31:39.062824+08	t	\N
5476	700	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:31:39.062824+08	t	\N
5477	702	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:31:52.443181+08	t	\N
5478	702	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:31:52.443183+08	t	\N
5479	703	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:32:00.141343+08	t	\N
5480	703	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:32:00.141346+08	t	\N
5481	703	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:32:00.141347+08	t	\N
5482	704	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:32:07.181358+08	t	\N
5483	704	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:32:07.181362+08	t	\N
5484	704	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:32:07.181363+08	t	\N
5485	704	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:32:07.181364+08	t	\N
5486	704	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:32:07.181364+08	t	\N
5487	704	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:32:07.181365+08	t	\N
5488	704	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:32:07.181366+08	t	\N
5489	704	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:32:07.181366+08	t	\N
5490	705	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:32:14.405075+08	t	\N
5491	705	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:32:14.405084+08	t	\N
5492	705	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:32:14.405087+08	t	\N
5493	705	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:32:14.40509+08	t	\N
5494	705	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:32:14.405092+08	t	\N
5495	705	\N	085703	地质工程	\N	0857	[]	[]	professional	2026-10-19 03:32:14.405094+08	t	\N
5496	705	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:32:14.405096+08	t	\N
5497	705	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:32:14.405098+08	t	\N
5498	705	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:32:14.4051+08	t	\N
5499	705	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:32:14.405101+08	t	\N
5500	705	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:32:14.405103+08	t	\N
5501	706	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:32:21.174489+08	t	\N
5502	706	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:32:21.174495+08	t	\N
5503	706	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:32:21.174496+08	t	\N
5504	706	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:32:21.174498+08	t	\N
5505	706	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:32:21.174499+08	t	\N
5506	706	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:32:21.174501+08	t	\N
5507	707	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:32:27.399701+08	t	\N
5508	707	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:32:27.399703+08	t	\N
5509	707	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:32:27.399703+08	t	\N
5510	707	\N	085702	安全工程	\N	0857	[]	[]	professional	2026-10-19 03:32:27.399704+08	t	\N
5511	707	\N	085704	测绘工程	\N	0857	[]	[]	professional	2026-10-19 03:32:27.399704+08	t	\N
5512	708	\N	082501	飞行器设计	\N	0825	[]	[]	academic	2026-10-19 03:32:33.859045+08	t	\N
5513	709	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 03:32:40.200047+08	t	\N
5514	709	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:32:40.200049+08	t	\N
5515	709	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:32:40.20005+08	t	\N
5516	709	\N	0805Z1	新能源科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:32:40.20005+08	t	\N
5517	709	\N	0805Z2	新能源材料与器件	\N	0805	[]	[]	academic	2026-10-19 03:32:40.200051+08	t	\N
5518	709	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 03:32:40.200051+08	t	\N
5519	709	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 03:32:40.200052+08	t	\N
5520	709	\N	0810Z2	低空技术与工程	\N	0810	[]	[]	academic	2026-10-19 03:32:40.200052+08	t	\N
5521	709	\N	081101	控制理论与控制工程	\N	0811	[]	[]	academic	2026-10-19 03:32:40.200052+08	t	\N
5522	709	\N	081102	检测技术与自动化装置	\N	0811	[]	[]	academic	2026-10-19 03:32:40.200053+08	t	\N
5523	709	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:32:40.200053+08	t	\N
5524	709	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:32:40.200054+08	t	\N
5525	709	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:32:40.200054+08	t	\N
5526	709	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:32:40.200055+08	t	\N
5527	709	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:32:40.200055+08	t	\N
5528	709	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:32:40.200055+08	t	\N
5529	709	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 03:32:40.200056+08	t	\N
5530	709	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:32:40.200056+08	t	\N
5531	709	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:32:40.200057+08	t	\N
5532	709	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:32:40.200057+08	t	\N
5533	710	\N	080102	固体力学	\N	0801	[]	[]	academic	2026-10-19 03:32:47.513493+08	t	\N
5534	710	\N	080103	流体力学	\N	0801	[]	[]	academic	2026-10-19 03:32:47.513499+08	t	\N
5535	710	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 03:32:47.513501+08	t	\N
5536	710	\N	080201	机械制造及其自动化	\N	0802	[]	[]	academic	2026-10-19 03:32:47.513502+08	t	\N
5537	710	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 03:32:47.513503+08	t	\N
5538	710	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 03:32:47.513504+08	t	\N
5539	710	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:32:47.513505+08	t	\N
5540	710	\N	0802Z1	工业工程	\N	0802	[]	[]	academic	2026-10-19 03:32:47.513506+08	t	\N
5541	710	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 03:32:47.513507+08	t	\N
5542	710	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:32:47.513508+08	t	\N
5543	710	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:32:47.513509+08	t	\N
5544	710	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:32:47.513509+08	t	\N
5545	710	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:32:47.51351+08	t	\N
5546	710	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:32:47.513511+08	t	\N
5547	710	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:32:47.513513+08	t	\N
5548	710	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:32:47.513514+08	t	\N
5549	710	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:32:47.513515+08	t	\N
5550	710	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:32:47.513516+08	t	\N
5551	710	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 03:32:47.513517+08	t	\N
5552	710	\N	0702Z1	计算物理	\N	0702	[]	[]	academic	2026-10-19 03:32:47.513517+08	t	\N
5553	711	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:32:54.232522+08	t	\N
5554	711	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 03:32:54.232525+08	t	\N
5555	711	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 03:32:54.232526+08	t	\N
5556	711	\N	0828J1	城乡建设工程与管理	\N	0828	[]	[]	academic	2026-10-19 03:32:54.232526+08	t	\N
5557	711	\N	0828Z1	农业信息技术与工程	\N	0828	[]	[]	academic	2026-10-19 03:32:54.232527+08	t	\N
5558	711	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 03:32:54.232527+08	t	\N
5559	711	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:32:54.232528+08	t	\N
5560	711	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:32:54.232528+08	t	\N
5561	711	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:32:54.232529+08	t	\N
5562	711	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:32:54.232529+08	t	\N
5563	711	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:32:54.23253+08	t	\N
5564	711	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 03:32:54.23253+08	t	\N
5565	712	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:33:00.15783+08	t	\N
5566	712	\N	0802Z1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:33:00.157836+08	t	\N
5567	712	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:33:00.157838+08	t	\N
5568	712	\N	082901	森林工程	\N	0829	[]	[]	academic	2026-10-19 03:33:00.157839+08	t	\N
5569	712	\N	082902	木材科学与技术	\N	0829	[]	[]	academic	2026-10-19 03:33:00.157841+08	t	\N
5570	712	\N	082903	林产化学加工工程	\N	0829	[]	[]	academic	2026-10-19 03:33:00.157842+08	t	\N
5571	712	\N	0829J1	森林防火	\N	0829	[]	[]	academic	2026-10-19 03:33:00.157844+08	t	\N
5572	712	\N	0829J5	家具设计与工程	\N	0829	[]	[]	academic	2026-10-19 03:33:00.157845+08	t	\N
5573	712	\N	0829J7	林区建筑与结构工程	\N	0829	[]	[]	academic	2026-10-19 03:33:00.157847+08	t	\N
5574	712	\N	0829Z1	生物质能源与材料	\N	0829	[]	[]	academic	2026-10-19 03:33:00.157848+08	t	\N
5575	712	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:33:00.157849+08	t	\N
5576	712	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:33:00.15785+08	t	\N
5577	712	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:33:00.157852+08	t	\N
5578	712	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 03:33:00.157853+08	t	\N
5579	712	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 03:33:00.157854+08	t	\N
5580	712	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 03:33:00.157856+08	t	\N
5581	712	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:33:00.157857+08	t	\N
5582	712	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:33:00.157858+08	t	\N
5583	712	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:33:00.15786+08	t	\N
5584	712	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:33:00.157861+08	t	\N
5585	713	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:33:06.953593+08	t	\N
5586	713	\N	071006	神经生物学	\N	0710	[]	[]	academic	2026-10-19 03:33:06.953599+08	t	\N
5587	713	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:33:06.953601+08	t	\N
5588	713	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:33:06.953603+08	t	\N
5589	713	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:33:06.953604+08	t	\N
5590	713	\N	071011	生物物理学	\N	0710	[]	[]	academic	2026-10-19 03:33:06.953606+08	t	\N
5591	714	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:33:13.603305+08	t	\N
5592	714	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:33:13.603307+08	t	\N
5593	714	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:33:13.603307+08	t	\N
5594	714	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:33:13.603308+08	t	\N
5595	714	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:33:13.603308+08	t	\N
5596	714	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:33:13.603309+08	t	\N
5597	714	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:33:13.603309+08	t	\N
5598	714	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:33:13.603309+08	t	\N
5599	714	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:33:13.60331+08	t	\N
5600	714	\N	0713J1	生态安全与健康	\N	0713	[]	[]	academic	2026-10-19 03:33:13.60331+08	t	\N
5601	715	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:33:19.559849+08	t	\N
5602	716	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:33:25.859348+08	t	\N
5603	716	\N	0803J1	低空技术与工程	\N	0803	[]	[]	academic	2026-10-19 03:33:25.859355+08	t	\N
5604	716	\N	081201	计算机系统结构	\N	0812	[]	[]	academic	2026-10-19 03:33:25.859357+08	t	\N
5605	716	\N	081202	计算机软件与理论	\N	0812	[]	[]	academic	2026-10-19 03:33:25.859359+08	t	\N
5606	716	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 03:33:25.85936+08	t	\N
5607	716	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 03:33:25.859361+08	t	\N
5608	716	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 03:33:25.859363+08	t	\N
5609	716	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 03:33:25.859364+08	t	\N
5610	716	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 03:33:25.859367+08	t	\N
5611	716	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:33:25.859369+08	t	\N
5612	716	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:33:25.85937+08	t	\N
5613	716	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:33:25.859371+08	t	\N
5614	716	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:33:25.859373+08	t	\N
5615	716	\N	070105	运筹学与控制论	\N	0701	[]	[]	academic	2026-10-19 03:33:25.859374+08	t	\N
5616	716	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:33:25.859375+08	t	\N
5617	716	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:33:25.859377+08	t	\N
5618	716	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:33:25.859378+08	t	\N
5619	716	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 03:33:25.859379+08	t	\N
5620	716	\N	0702Z1	天文物理学	\N	0702	[]	[]	academic	2026-10-19 03:33:25.85938+08	t	\N
5621	716	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:33:25.859382+08	t	\N
5622	717	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:33:33.214207+08	t	\N
5623	718	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:33:39.807404+08	t	\N
5624	719	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:33:46.759079+08	t	\N
5625	719	\N	0812J1	数字经济工程与技术	\N	0812	[]	[]	academic	2026-10-19 03:33:46.75909+08	t	\N
5626	719	\N	0812J2	低空技术与工程	\N	0812	[]	[]	academic	2026-10-19 03:33:46.759093+08	t	\N
5627	719	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:33:46.759095+08	t	\N
5628	719	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:33:46.759097+08	t	\N
5629	719	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:33:46.759099+08	t	\N
5630	719	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:33:46.759101+08	t	\N
5631	719	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:33:46.759103+08	t	\N
5632	719	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:33:46.759104+08	t	\N
5633	720	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:33:53.914401+08	t	\N
5634	720	\N	0810Z1	低空技术与工程	\N	0810	[]	[]	academic	2026-10-19 03:33:53.914409+08	t	\N
5635	720	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:33:53.914412+08	t	\N
5636	720	\N	083001	环境科学	\N	0830	[]	[]	academic	2026-10-19 03:33:53.914415+08	t	\N
5637	720	\N	083002	环境工程	\N	0830	[]	[]	academic	2026-10-19 03:33:53.914417+08	t	\N
5638	720	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:33:53.914418+08	t	\N
5639	720	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:33:53.91442+08	t	\N
5640	720	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 03:33:53.914422+08	t	\N
5641	720	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:33:53.914424+08	t	\N
5642	720	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:33:53.914426+08	t	\N
5643	720	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:33:53.914428+08	t	\N
5644	720	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:33:53.91443+08	t	\N
5645	720	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:33:53.914432+08	t	\N
5646	720	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:33:53.914433+08	t	\N
5647	720	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 03:33:53.914436+08	t	\N
5648	720	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:33:53.914438+08	t	\N
5649	720	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:33:53.91444+08	t	\N
5650	720	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 03:33:53.914442+08	t	\N
5651	720	\N	0703Z3	化学生物学	\N	0703	[]	[]	academic	2026-10-19 03:33:53.914443+08	t	\N
5652	722	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:34:08.071699+08	t	\N
5653	723	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:34:14.63259+08	t	\N
5654	724	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:34:20.241823+08	t	\N
5655	724	\N	085509	智能制造技术	\N	0855	[]	[]	professional	2026-10-19 03:34:20.241825+08	t	\N
5656	724	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:34:20.241826+08	t	\N
5657	724	\N	085901	土木工程	\N	0859	[]	[]	professional	2026-10-19 03:34:20.241826+08	t	\N
5658	724	\N	085902	水利工程	\N	0859	[]	[]	professional	2026-10-19 03:34:20.241827+08	t	\N
5659	724	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:34:20.241827+08	t	\N
5660	724	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:34:20.241828+08	t	\N
5661	724	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:34:20.241828+08	t	\N
5662	724	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:34:20.241829+08	t	\N
5663	725	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:34:26.286037+08	t	\N
5664	726	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:34:33.448163+08	t	\N
5665	726	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 03:34:33.448171+08	t	\N
5666	726	\N	081705	工业催化	\N	0817	[]	[]	academic	2026-10-19 03:34:33.448174+08	t	\N
5667	727	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:34:40.012583+08	t	\N
5668	727	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:34:40.012586+08	t	\N
5669	727	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 03:34:40.012586+08	t	\N
5670	727	\N	085802	动力工程	\N	0858	[]	[]	professional	2026-10-19 03:34:40.012587+08	t	\N
5671	727	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:34:40.012587+08	t	\N
5672	727	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:34:40.012587+08	t	\N
5673	727	\N	086200	风景园林	\N	0862	[]	[]	professional	2026-10-19 03:34:40.012588+08	t	\N
5674	728	\N	081001	通信与信息系统	\N	0810	[]	[]	academic	2026-10-19 03:34:46.777239+08	t	\N
5675	728	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 03:34:46.777241+08	t	\N
5676	728	\N	081201	计算机系统结构	\N	0812	[]	[]	academic	2026-10-19 03:34:46.777242+08	t	\N
5677	728	\N	081202	计算机软件与理论	\N	0812	[]	[]	academic	2026-10-19 03:34:46.777242+08	t	\N
5678	728	\N	081203	计算机应用技术	\N	0812	[]	[]	academic	2026-10-19 03:34:46.777243+08	t	\N
5679	728	\N	081301	建筑历史与理论	\N	0813	[]	[]	academic	2026-10-19 03:34:46.777243+08	t	\N
5680	728	\N	081302	建筑设计及其理论	\N	0813	[]	[]	academic	2026-10-19 03:34:46.777243+08	t	\N
5681	728	\N	081304	建筑技术科学	\N	0813	[]	[]	academic	2026-10-19 03:34:46.777244+08	t	\N
5682	728	\N	081801	矿产普查与勘探	\N	0818	[]	[]	academic	2026-10-19 03:34:46.777244+08	t	\N
5683	728	\N	081802	地球探测与信息技术	\N	0818	[]	[]	academic	2026-10-19 03:34:46.777245+08	t	\N
5684	728	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:34:46.777245+08	t	\N
5685	728	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:34:46.777245+08	t	\N
5686	728	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:34:46.777246+08	t	\N
5687	728	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:34:46.777246+08	t	\N
5688	728	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 03:34:46.777247+08	t	\N
5689	728	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:34:46.777247+08	t	\N
5690	728	\N	0702Z1	多信使天体物理	\N	0702	[]	[]	academic	2026-10-19 03:34:46.777248+08	t	\N
5691	728	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:34:46.777248+08	t	\N
5692	728	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:34:46.777248+08	t	\N
5693	729	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:34:53.015282+08	t	\N
5694	729	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:34:53.015284+08	t	\N
5695	729	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:34:53.015285+08	t	\N
5696	729	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:34:53.015285+08	t	\N
5697	731	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:35:07.578236+08	t	\N
5698	731	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:35:07.578242+08	t	\N
5699	731	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:35:07.578244+08	t	\N
5700	731	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:35:07.578245+08	t	\N
5701	731	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:35:07.578246+08	t	\N
5702	731	\N	0817J1	碳储科学与工程	\N	0817	[]	[]	academic	2026-10-19 03:35:07.578247+08	t	\N
5703	731	\N	081800	地质资源与地质工程	\N	0818	[]	[]	academic	2026-10-19 03:35:07.578248+08	t	\N
5704	731	\N	0818J1	碳储科学与工程	\N	0818	[]	[]	academic	2026-10-19 03:35:07.578249+08	t	\N
5705	731	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:35:07.57825+08	t	\N
5706	731	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:35:07.578251+08	t	\N
5707	731	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:35:07.578252+08	t	\N
5708	731	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:35:07.578252+08	t	\N
5709	731	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:35:07.578253+08	t	\N
5710	731	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:35:07.578254+08	t	\N
5711	731	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:35:07.578256+08	t	\N
5712	731	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:35:07.578257+08	t	\N
5713	731	\N	071200	科学技术史	\N	0712	[]	[]	academic	2026-10-19 03:35:07.578258+08	t	\N
5714	731	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:35:07.578259+08	t	\N
5715	731	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:35:07.57826+08	t	\N
5716	732	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:35:14.251409+08	t	\N
5717	732	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:35:14.251412+08	t	\N
5718	732	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:35:14.251413+08	t	\N
5719	732	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:35:14.251413+08	t	\N
5720	732	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:35:14.251414+08	t	\N
5721	732	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:35:14.251414+08	t	\N
5722	732	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:35:14.251415+08	t	\N
5723	732	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:35:14.251415+08	t	\N
5724	732	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:35:14.251415+08	t	\N
5725	732	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:35:14.251416+08	t	\N
5726	732	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:35:14.251416+08	t	\N
5727	732	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:35:14.251417+08	t	\N
5728	732	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:35:14.251417+08	t	\N
5729	732	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:35:14.251418+08	t	\N
5730	733	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:35:21.576989+08	t	\N
5731	733	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:35:21.576995+08	t	\N
5732	733	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:35:21.576996+08	t	\N
5733	733	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 03:35:21.576997+08	t	\N
5734	733	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:35:21.576999+08	t	\N
5735	733	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:35:21.577+08	t	\N
5736	733	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:35:21.577001+08	t	\N
5737	733	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:35:21.577001+08	t	\N
5738	733	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:35:21.577002+08	t	\N
5739	733	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:35:21.577003+08	t	\N
5740	733	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:35:21.577004+08	t	\N
5741	733	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:35:21.577005+08	t	\N
5742	733	\N	070206	声学	\N	0702	[]	[]	academic	2026-10-19 03:35:21.577006+08	t	\N
5743	733	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:35:21.577007+08	t	\N
5744	733	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 03:35:21.577008+08	t	\N
5745	733	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:35:21.577009+08	t	\N
5746	733	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:35:21.57701+08	t	\N
5747	733	\N	070305	高分子化学与物理	\N	0703	[]	[]	academic	2026-10-19 03:35:21.57701+08	t	\N
5748	733	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:35:21.577011+08	t	\N
5749	733	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:35:21.577012+08	t	\N
5750	734	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:35:28.305387+08	t	\N
5751	734	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:35:28.305393+08	t	\N
5752	734	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:35:28.305395+08	t	\N
5753	734	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:35:28.305397+08	t	\N
5754	734	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 03:35:28.305398+08	t	\N
5755	734	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:35:28.3054+08	t	\N
5756	734	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:35:28.305401+08	t	\N
5757	734	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:35:28.305402+08	t	\N
5758	734	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:35:28.305403+08	t	\N
5759	734	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:35:28.305405+08	t	\N
5760	734	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:35:28.305406+08	t	\N
5761	734	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:35:28.305408+08	t	\N
5762	735	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:35:35.023249+08	t	\N
5763	735	\N	0801J7	低空技术与工程	\N	0801	[]	[]	academic	2026-10-19 03:35:35.023258+08	t	\N
5764	735	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:35:35.023262+08	t	\N
5765	735	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:35:35.023266+08	t	\N
5766	735	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:35:35.023268+08	t	\N
5767	735	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:35:35.02327+08	t	\N
5768	735	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:35:35.023272+08	t	\N
5769	735	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:35:35.023274+08	t	\N
5770	735	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:35:35.023276+08	t	\N
5771	735	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:35:35.023278+08	t	\N
5772	735	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:35:35.023279+08	t	\N
5773	735	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:35:35.023281+08	t	\N
5774	735	\N	0702J7	低空技术与工程	\N	0702	[]	[]	academic	2026-10-19 03:35:35.023283+08	t	\N
5775	735	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:35:35.023285+08	t	\N
5776	735	\N	077700	生物医学工程	\N	0777	[]	[]	academic	2026-10-19 03:35:35.023287+08	t	\N
5777	736	\N	080201	机械制造及其自动化	\N	0802	[]	[]	academic	2026-10-19 03:35:42.1282+08	t	\N
5778	736	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 03:35:42.128206+08	t	\N
5779	736	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 03:35:42.128208+08	t	\N
5780	736	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:35:42.128209+08	t	\N
5781	736	\N	0802Z1	工业设计	\N	0802	[]	[]	academic	2026-10-19 03:35:42.128211+08	t	\N
5782	736	\N	0802Z2	包装工程	\N	0802	[]	[]	academic	2026-10-19 03:35:42.128212+08	t	\N
5783	736	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:35:42.128214+08	t	\N
5784	736	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:35:42.128215+08	t	\N
5785	736	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:35:42.128217+08	t	\N
5786	736	\N	081101	控制理论与控制工程	\N	0811	[]	[]	academic	2026-10-19 03:35:42.128218+08	t	\N
5787	736	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:35:42.128219+08	t	\N
5788	736	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:35:42.128221+08	t	\N
5789	737	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:35:49.873045+08	t	\N
5790	737	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:35:49.873055+08	t	\N
5791	737	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:35:49.873058+08	t	\N
5792	737	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:35:49.873061+08	t	\N
5793	737	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 03:35:49.873063+08	t	\N
5794	737	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:35:49.873065+08	t	\N
5795	737	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:35:49.873067+08	t	\N
5796	737	\N	0811Z1	智能建筑	\N	0811	[]	[]	academic	2026-10-19 03:35:49.873069+08	t	\N
5797	737	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:35:49.873071+08	t	\N
5798	737	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:35:49.873073+08	t	\N
5799	737	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:35:49.873074+08	t	\N
5800	737	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:35:49.873076+08	t	\N
5801	737	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:35:49.873078+08	t	\N
5802	738	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:35:56.44469+08	t	\N
5803	738	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:35:56.444693+08	t	\N
5804	738	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:35:56.444693+08	t	\N
5805	738	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:35:56.444694+08	t	\N
5806	738	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:35:56.444694+08	t	\N
5807	738	\N	0808J4	新能源与储能工程	\N	0808	[]	[]	academic	2026-10-19 03:35:56.444695+08	t	\N
5808	738	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:35:56.444695+08	t	\N
5809	738	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:35:56.444696+08	t	\N
5810	738	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:35:56.444696+08	t	\N
5811	738	\N	0811J3	低空技术与工程	\N	0811	[]	[]	academic	2026-10-19 03:35:56.444696+08	t	\N
5812	738	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:35:56.444697+08	t	\N
5813	738	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:35:56.444698+08	t	\N
5814	738	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:35:56.444698+08	t	\N
5815	738	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:35:56.444699+08	t	\N
5816	739	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:36:03.067859+08	t	\N
5817	739	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:36:03.067865+08	t	\N
5818	739	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:36:03.067867+08	t	\N
5819	739	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:36:03.067869+08	t	\N
5820	739	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:36:03.06787+08	t	\N
5821	739	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:36:03.067872+08	t	\N
5822	739	\N	0808J1	新能源与储能工程	\N	0808	[]	[]	academic	2026-10-19 03:36:03.067873+08	t	\N
5823	739	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:36:03.067875+08	t	\N
5824	739	\N	0811J2	低空技术与工程	\N	0811	[]	[]	academic	2026-10-19 03:36:03.067876+08	t	\N
5825	739	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:36:03.067877+08	t	\N
5826	739	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:36:03.067879+08	t	\N
5827	739	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:36:03.06788+08	t	\N
5828	740	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:36:09.910881+08	t	\N
5829	740	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:36:09.910884+08	t	\N
5830	740	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:36:09.910884+08	t	\N
5831	740	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:36:09.910885+08	t	\N
5832	740	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:36:09.910885+08	t	\N
5833	740	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:36:09.910885+08	t	\N
5834	740	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:36:09.910886+08	t	\N
5835	740	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:36:09.910886+08	t	\N
5836	740	\N	082200	轻工技术与工程	\N	0822	[]	[]	academic	2026-10-19 03:36:09.910887+08	t	\N
5837	740	\N	0822Z3	生物质化学与材料工程	\N	0822	[]	[]	academic	2026-10-19 03:36:09.910887+08	t	\N
5838	740	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:36:09.910887+08	t	\N
5839	740	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:36:09.910888+08	t	\N
5840	740	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:36:09.910888+08	t	\N
5841	741	\N	080201	机械制造及其自动化	\N	0802	[]	[]	academic	2026-10-19 03:36:16.803972+08	t	\N
5842	741	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 03:36:16.803981+08	t	\N
5843	741	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 03:36:16.803984+08	t	\N
5844	741	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:36:16.803986+08	t	\N
5845	741	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:36:16.803988+08	t	\N
5846	741	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:36:16.80399+08	t	\N
5847	741	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:36:16.803992+08	t	\N
5848	741	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:36:16.803994+08	t	\N
5849	741	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:36:16.803996+08	t	\N
5850	741	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:36:16.803998+08	t	\N
5851	741	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:36:16.803999+08	t	\N
5852	741	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:36:16.804001+08	t	\N
5853	741	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:36:16.804003+08	t	\N
5854	741	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:36:16.804005+08	t	\N
5855	741	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:36:16.804007+08	t	\N
5856	741	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:36:16.804009+08	t	\N
5857	741	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 03:36:16.804011+08	t	\N
5858	741	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:36:16.804013+08	t	\N
5859	741	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:36:16.804014+08	t	\N
5860	741	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:36:16.804016+08	t	\N
5861	746	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:36:50.898388+08	t	\N
5862	747	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:36:57.456934+08	t	\N
5863	747	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:36:57.456943+08	t	\N
5864	747	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:36:57.456946+08	t	\N
5865	748	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:37:04.41556+08	t	\N
5866	750	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:37:17.813248+08	t	\N
5867	750	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:37:17.813251+08	t	\N
5868	750	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:37:17.813251+08	t	\N
5869	750	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:37:17.813252+08	t	\N
5870	750	\N	085510	机器人工程	\N	0855	[]	[]	professional	2026-10-19 03:37:17.813253+08	t	\N
5871	750	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:37:17.813253+08	t	\N
5872	750	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:37:17.813253+08	t	\N
5873	750	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 03:37:17.813254+08	t	\N
5874	750	\N	085803	核能工程	\N	0858	[]	[]	professional	2026-10-19 03:37:17.813254+08	t	\N
5875	750	\N	085901	土木工程	\N	0859	[]	[]	professional	2026-10-19 03:37:17.813255+08	t	\N
5876	751	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 03:37:24.690982+08	t	\N
5877	751	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:37:24.69099+08	t	\N
5878	751	\N	081704	应用化学	\N	0817	[]	[]	academic	2026-10-19 03:37:24.690993+08	t	\N
5879	752	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:37:31.272988+08	t	\N
5880	753	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 03:37:37.646285+08	t	\N
5881	754	\N	082604	军事化学与烟火技术	\N	0826	[]	[]	academic	2026-10-19 03:37:44.435632+08	t	\N
5882	755	\N	082603	火炮、自动武器与弹药工程	\N	0826	[]	[]	academic	2026-10-19 03:37:50.924192+08	t	\N
5883	756	\N	082601	武器系统与运用工程	\N	0826	[]	[]	academic	2026-10-19 03:37:57.787046+08	t	\N
5884	757	\N	082601	武器系统与运用工程	\N	0826	[]	[]	academic	2026-10-19 03:38:03.744888+08	t	\N
5885	758	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:38:09.776801+08	t	\N
5886	758	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:38:09.776803+08	t	\N
5887	759	\N	080904	电磁场与微波技术	\N	0809	[]	[]	academic	2026-10-19 03:38:16.303897+08	t	\N
5888	760	\N	082403	水声工程	\N	0824	[]	[]	academic	2026-10-19 03:38:23.549111+08	t	\N
5889	760	\N	082601	武器系统与运用工程	\N	0826	[]	[]	academic	2026-10-19 03:38:23.549114+08	t	\N
5890	761	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:38:29.504862+08	t	\N
5891	762	\N	081103	系统工程	\N	0811	[]	[]	academic	2026-10-19 03:38:35.429217+08	t	\N
5892	762	\N	082501	飞行器设计	\N	0825	[]	[]	academic	2026-10-19 03:38:35.429219+08	t	\N
5893	763	\N	080104	工程力学	\N	0801	[]	[]	academic	2026-10-19 03:38:41.931754+08	t	\N
5894	764	\N	080402	测试计量技术及仪器	\N	0804	[]	[]	academic	2026-10-19 03:38:48.397874+08	t	\N
5895	764	\N	081105	导航、制导与控制	\N	0811	[]	[]	academic	2026-10-19 03:38:48.397877+08	t	\N
5896	764	\N	082501	飞行器设计	\N	0825	[]	[]	academic	2026-10-19 03:38:48.397878+08	t	\N
5897	764	\N	082502	航空宇航推进理论与工程	\N	0825	[]	[]	academic	2026-10-19 03:38:48.397878+08	t	\N
5898	764	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:38:48.397879+08	t	\N
5899	764	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:38:48.397879+08	t	\N
5900	765	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:38:54.82477+08	t	\N
5901	765	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:38:54.824778+08	t	\N
5902	765	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:38:54.824781+08	t	\N
5903	765	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:38:54.824784+08	t	\N
5904	766	\N	080401	精密仪器及机械	\N	0804	[]	[]	academic	2026-10-19 03:39:01.853271+08	t	\N
5905	766	\N	081105	导航、制导与控制	\N	0811	[]	[]	academic	2026-10-19 03:39:01.853279+08	t	\N
5906	768	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:39:14.762187+08	t	\N
5907	768	\N	081002	信号与信息处理	\N	0810	[]	[]	academic	2026-10-19 03:39:14.762196+08	t	\N
5908	768	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:39:14.762199+08	t	\N
5909	768	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:39:14.762201+08	t	\N
5910	768	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:39:14.762203+08	t	\N
5911	768	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:39:14.762205+08	t	\N
5912	768	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:39:14.762207+08	t	\N
5913	768	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:39:14.762209+08	t	\N
5914	768	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:39:14.762211+08	t	\N
5915	768	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:39:14.762213+08	t	\N
5916	768	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:39:14.762215+08	t	\N
5917	768	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:39:14.762217+08	t	\N
5918	768	\N	070203	原子与分子物理	\N	0702	[]	[]	academic	2026-10-19 03:39:14.762219+08	t	\N
5919	768	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:39:14.762221+08	t	\N
5920	768	\N	070206	声学	\N	0702	[]	[]	academic	2026-10-19 03:39:14.762223+08	t	\N
5921	768	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:39:14.762225+08	t	\N
5922	768	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:39:14.762227+08	t	\N
5923	768	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:39:14.762229+08	t	\N
5924	768	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:39:14.762231+08	t	\N
5925	768	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 03:39:14.762232+08	t	\N
5926	769	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:39:21.052919+08	t	\N
5927	769	\N	0802J1	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:39:21.052922+08	t	\N
5928	769	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:39:21.052923+08	t	\N
5929	769	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:39:21.052923+08	t	\N
5930	769	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:39:21.052924+08	t	\N
5931	769	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:39:21.052924+08	t	\N
5932	769	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:39:21.052925+08	t	\N
5933	769	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:39:21.052925+08	t	\N
5934	769	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:39:21.052925+08	t	\N
5935	769	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:39:21.052926+08	t	\N
5936	769	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:39:21.052926+08	t	\N
5937	769	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:39:21.052927+08	t	\N
5938	769	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:39:21.052927+08	t	\N
5939	769	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:39:21.052928+08	t	\N
5940	771	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:39:34.378376+08	t	\N
5941	771	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:39:34.378384+08	t	\N
5942	771	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:39:34.378386+08	t	\N
5943	771	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:39:34.378388+08	t	\N
5944	771	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 03:39:34.378389+08	t	\N
5945	771	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 03:39:34.37839+08	t	\N
5946	771	\N	082803	农业生物环境与能源工程	\N	0828	[]	[]	academic	2026-10-19 03:39:34.378392+08	t	\N
5947	771	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 03:39:34.378393+08	t	\N
5948	771	\N	082900	林业工程	\N	0829	[]	[]	academic	2026-10-19 03:39:34.378394+08	t	\N
5949	771	\N	083001	环境科学	\N	0830	[]	[]	academic	2026-10-19 03:39:34.378395+08	t	\N
5950	771	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:39:34.378396+08	t	\N
5951	771	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:39:34.378397+08	t	\N
5952	771	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:39:34.378399+08	t	\N
5953	771	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 03:39:34.3784+08	t	\N
5954	771	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 03:39:34.378401+08	t	\N
5955	771	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:39:34.378403+08	t	\N
5956	771	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:39:34.378404+08	t	\N
5957	771	\N	071008	发育生物学	\N	0710	[]	[]	academic	2026-10-19 03:39:34.378405+08	t	\N
5958	771	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:39:34.378406+08	t	\N
5959	771	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:39:34.378407+08	t	\N
5960	772	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:39:41.082467+08	t	\N
5961	772	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:39:41.082469+08	t	\N
5962	772	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:39:41.082469+08	t	\N
5963	773	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:39:48.852557+08	t	\N
5964	773	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:39:48.852566+08	t	\N
5965	773	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:39:48.852569+08	t	\N
5966	775	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:40:02.542326+08	t	\N
5967	776	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:40:08.999997+08	t	\N
5968	776	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:40:09+08	t	\N
5969	776	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:40:09+08	t	\N
5970	776	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:40:09.000001+08	t	\N
5971	776	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:40:09.000001+08	t	\N
5972	777	\N	080300	光学工程	\N	0803	[]	[]	academic	2026-10-19 03:40:14.799587+08	t	\N
5973	777	\N	080400	仪器科学与技术	\N	0804	[]	[]	academic	2026-10-19 03:40:14.799615+08	t	\N
5974	777	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:40:14.799617+08	t	\N
5975	777	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:40:14.799618+08	t	\N
5976	777	\N	0810J4	低空技术与工程	\N	0810	[]	[]	academic	2026-10-19 03:40:14.799619+08	t	\N
5977	777	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:40:14.799619+08	t	\N
5978	777	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:40:14.79962+08	t	\N
5979	777	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:40:14.79962+08	t	\N
5980	777	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:40:14.79962+08	t	\N
5981	777	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:40:14.799621+08	t	\N
5982	777	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:40:14.799621+08	t	\N
5983	777	\N	071100	系统科学	\N	0711	[]	[]	academic	2026-10-19 03:40:14.799622+08	t	\N
5984	777	\N	077500	计算机科学与技术	\N	0775	[]	[]	academic	2026-10-19 03:40:14.799622+08	t	\N
5985	778	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:40:21.269752+08	t	\N
5986	779	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:40:28.215955+08	t	\N
5987	779	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:40:28.215957+08	t	\N
5988	779	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:40:28.215958+08	t	\N
5989	779	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:40:28.215959+08	t	\N
5990	779	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:40:28.215959+08	t	\N
5991	779	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:40:28.21596+08	t	\N
5992	779	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:40:28.21596+08	t	\N
5993	779	\N	082100	纺织科学与工程	\N	0821	[]	[]	academic	2026-10-19 03:40:28.21596+08	t	\N
5994	779	\N	083000	环境科学与工程	\N	0830	[]	[]	academic	2026-10-19 03:40:28.215961+08	t	\N
5995	779	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:40:28.215961+08	t	\N
5996	779	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:40:28.215962+08	t	\N
5997	779	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:40:28.215962+08	t	\N
5998	780	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:40:35.233784+08	t	\N
5999	780	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:40:35.233795+08	t	\N
6000	780	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:40:35.233798+08	t	\N
6001	780	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 03:40:35.2338+08	t	\N
6002	780	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:40:35.233803+08	t	\N
6003	780	\N	082600	兵器科学与技术	\N	0826	[]	[]	academic	2026-10-19 03:40:35.233805+08	t	\N
6004	780	\N	082700	核科学与技术	\N	0827	[]	[]	academic	2026-10-19 03:40:35.233806+08	t	\N
6005	780	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:40:35.233808+08	t	\N
6006	780	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:40:35.23381+08	t	\N
6007	780	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:40:35.233812+08	t	\N
6008	780	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:40:35.233814+08	t	\N
6009	781	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:40:42.154264+08	t	\N
6010	781	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:40:42.154269+08	t	\N
6011	781	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:40:42.154271+08	t	\N
6012	781	\N	082500	航空宇航科学与技术	\N	0825	[]	[]	academic	2026-10-19 03:40:42.154273+08	t	\N
6013	781	\N	082600	兵器科学与技术	\N	0826	[]	[]	academic	2026-10-19 03:40:42.154275+08	t	\N
6014	781	\N	082700	核科学与技术	\N	0827	[]	[]	academic	2026-10-19 03:40:42.154276+08	t	\N
6015	781	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:40:42.154278+08	t	\N
6016	781	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:40:42.154279+08	t	\N
6017	781	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 03:40:42.15428+08	t	\N
6018	782	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:40:49.385254+08	t	\N
6019	782	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:40:49.385257+08	t	\N
6020	783	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:40:56.931672+08	t	\N
6021	783	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:40:56.931675+08	t	\N
6022	783	\N	0805Z1	空间科学与技术	\N	0805	[]	[]	academic	2026-10-19 03:40:56.931675+08	t	\N
6023	783	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:40:56.931676+08	t	\N
6024	783	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:40:56.931676+08	t	\N
6025	783	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:40:56.931677+08	t	\N
6026	783	\N	0812J6	人工智能	\N	0812	[]	[]	academic	2026-10-19 03:40:56.931677+08	t	\N
6027	783	\N	0812Z1	低空技术与工程	\N	0812	[]	[]	academic	2026-10-19 03:40:56.931678+08	t	\N
6028	783	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:40:56.931678+08	t	\N
6029	783	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:40:56.931679+08	t	\N
6030	783	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:40:56.931679+08	t	\N
6031	783	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:40:56.931679+08	t	\N
6032	783	\N	070202	粒子物理与原子核物理	\N	0702	[]	[]	academic	2026-10-19 03:40:56.93168+08	t	\N
6033	783	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 03:40:56.93168+08	t	\N
6034	783	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:40:56.931681+08	t	\N
6035	783	\N	0703Z3	放射化学	\N	0703	[]	[]	academic	2026-10-19 03:40:56.931681+08	t	\N
6036	783	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:40:56.931681+08	t	\N
6037	783	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:40:56.931682+08	t	\N
6038	783	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 03:40:56.931682+08	t	\N
6039	783	\N	0705Z1	城市与区域规划	\N	0705	[]	[]	academic	2026-10-19 03:40:56.931683+08	t	\N
6040	784	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:41:03.675374+08	t	\N
6041	784	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:41:03.675381+08	t	\N
6042	784	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 03:41:03.675384+08	t	\N
6043	784	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:41:03.675385+08	t	\N
6044	784	\N	080600	冶金工程	\N	0806	[]	[]	academic	2026-10-19 03:41:03.675387+08	t	\N
6045	784	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:41:03.675388+08	t	\N
6046	784	\N	080706	化工过程机械	\N	0807	[]	[]	academic	2026-10-19 03:41:03.67539+08	t	\N
6047	784	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:41:03.675391+08	t	\N
6048	784	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:41:03.675392+08	t	\N
6049	784	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:41:03.675394+08	t	\N
6050	784	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:41:03.675395+08	t	\N
6051	784	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:41:03.675398+08	t	\N
6052	785	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:41:10.494577+08	t	\N
6053	785	\N	080201	机械制造及其自动化	\N	0802	[]	[]	academic	2026-10-19 03:41:10.494579+08	t	\N
6054	785	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 03:41:10.49458+08	t	\N
6055	785	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 03:41:10.49458+08	t	\N
6056	785	\N	080204	车辆工程	\N	0802	[]	[]	academic	2026-10-19 03:41:10.494581+08	t	\N
6057	785	\N	0802Z2	绿色镀膜技术与装备	\N	0802	[]	[]	academic	2026-10-19 03:41:10.494581+08	t	\N
6058	785	\N	0802Z4	交通装备检测及控制工程	\N	0802	[]	[]	academic	2026-10-19 03:41:10.494582+08	t	\N
6059	785	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:41:10.494582+08	t	\N
6060	785	\N	080701	工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:41:10.494583+08	t	\N
6061	785	\N	080702	热能工程	\N	0807	[]	[]	academic	2026-10-19 03:41:10.494583+08	t	\N
6062	785	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:41:10.494584+08	t	\N
6063	785	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:41:10.494584+08	t	\N
6064	785	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:41:10.494584+08	t	\N
6065	785	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:41:10.494585+08	t	\N
6066	785	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:41:10.494585+08	t	\N
6067	786	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 03:41:17.337591+08	t	\N
6068	786	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 03:41:17.337601+08	t	\N
6069	786	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:41:17.337604+08	t	\N
6070	786	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 03:41:17.337607+08	t	\N
6071	786	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 03:41:17.337609+08	t	\N
6072	786	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 03:41:17.337611+08	t	\N
6073	786	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:41:17.337613+08	t	\N
6074	786	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:41:17.337614+08	t	\N
6075	786	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:41:17.337616+08	t	\N
6076	786	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:41:17.337618+08	t	\N
6077	786	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:41:17.33762+08	t	\N
6078	786	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 03:41:17.337622+08	t	\N
6079	786	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:41:17.337624+08	t	\N
6080	786	\N	071008	发育生物学	\N	0710	[]	[]	academic	2026-10-19 03:41:17.337626+08	t	\N
6081	786	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:41:17.337628+08	t	\N
6082	786	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:41:17.337629+08	t	\N
6083	787	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:41:24.809316+08	t	\N
6084	788	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:41:32.054308+08	t	\N
6085	788	\N	080902	电路与系统	\N	0809	[]	[]	academic	2026-10-19 03:41:32.054316+08	t	\N
6086	788	\N	080904	电磁场与微波技术	\N	0809	[]	[]	academic	2026-10-19 03:41:32.054319+08	t	\N
6087	788	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:41:32.054322+08	t	\N
6088	788	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:41:32.054324+08	t	\N
6089	788	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:41:32.054326+08	t	\N
6090	788	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:41:32.054328+08	t	\N
6091	788	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:41:32.054329+08	t	\N
6092	788	\N	085405	软件工程	\N	0854	[]	[]	professional	2026-10-19 03:41:32.054331+08	t	\N
6093	788	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:41:32.054333+08	t	\N
6094	788	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:41:32.054335+08	t	\N
6095	788	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:41:32.054337+08	t	\N
6096	788	\N	070203	原子与分子物理	\N	0702	[]	[]	academic	2026-10-19 03:41:32.054339+08	t	\N
6097	788	\N	070204	等离子体物理	\N	0702	[]	[]	academic	2026-10-19 03:41:32.05434+08	t	\N
6098	788	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:41:32.054343+08	t	\N
6099	788	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:41:32.054345+08	t	\N
6100	788	\N	0702Z1	光电子学	\N	0702	[]	[]	academic	2026-10-19 03:41:32.054347+08	t	\N
6101	788	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:41:32.054349+08	t	\N
6102	788	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:41:32.054351+08	t	\N
6103	788	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:41:32.054352+08	t	\N
6104	789	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:41:38.540585+08	t	\N
6105	789	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:41:38.540594+08	t	\N
6106	789	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:41:38.540598+08	t	\N
6107	789	\N	085706	石油与天然气工程	\N	0857	[]	[]	professional	2026-10-19 03:41:38.5406+08	t	\N
6108	790	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:41:45.03154+08	t	\N
6109	790	\N	085901	土木工程	\N	0859	[]	[]	professional	2026-10-19 03:41:45.031578+08	t	\N
6110	790	\N	086001	生物技术与工程	\N	0860	[]	[]	professional	2026-10-19 03:41:45.031583+08	t	\N
6111	791	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:41:52.335903+08	t	\N
6112	791	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:41:52.335905+08	t	\N
6113	791	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:41:52.335906+08	t	\N
6114	791	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:41:52.335906+08	t	\N
6115	791	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 03:41:52.335906+08	t	\N
6116	791	\N	085900	土木水利	\N	0859	[]	[]	professional	2026-10-19 03:41:52.335907+08	t	\N
6117	791	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:41:52.335907+08	t	\N
6118	791	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:41:52.335908+08	t	\N
6119	791	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:41:52.335908+08	t	\N
6120	792	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:41:58.430338+08	t	\N
6121	792	\N	085800	能源动力	\N	0858	[]	[]	professional	2026-10-19 03:41:58.430347+08	t	\N
6122	792	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:41:58.43035+08	t	\N
6123	792	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:41:58.430353+08	t	\N
6124	793	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:42:04.451399+08	t	\N
6125	793	\N	0714Z3	数理统计学	\N	0714	[]	[]	academic	2026-10-19 03:42:04.451402+08	t	\N
6126	794	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:42:11.243556+08	t	\N
6127	794	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:42:11.243559+08	t	\N
6128	794	\N	083600	生物工程	\N	0836	[]	[]	academic	2026-10-19 03:42:11.24356+08	t	\N
6129	794	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:42:11.24356+08	t	\N
6130	794	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:42:11.243561+08	t	\N
6131	794	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:42:11.243561+08	t	\N
6132	794	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:42:11.243562+08	t	\N
6133	794	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:42:11.243562+08	t	\N
6134	794	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:42:11.243562+08	t	\N
6135	794	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:42:11.243563+08	t	\N
6136	794	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:42:11.243563+08	t	\N
6137	794	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:42:11.243564+08	t	\N
6138	794	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 03:42:11.243564+08	t	\N
6139	795	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:42:18.486754+08	t	\N
6140	797	\N	070801	固体地球物理学	\N	0708	[]	[]	academic	2026-10-19 03:42:31.937728+08	t	\N
6141	797	\N	070904	构造地质学	\N	0709	[]	[]	academic	2026-10-19 03:42:31.93773+08	t	\N
6142	798	\N	080705	制冷及低温工程	\N	0807	[]	[]	academic	2026-10-19 03:42:39.772269+08	t	\N
6143	798	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:42:39.772281+08	t	\N
6144	799	\N	080202	机械电子工程	\N	0802	[]	[]	academic	2026-10-19 03:42:45.870602+08	t	\N
6145	799	\N	080203	机械设计及理论	\N	0802	[]	[]	academic	2026-10-19 03:42:45.870605+08	t	\N
6146	799	\N	080501	材料物理与化学	\N	0805	[]	[]	academic	2026-10-19 03:42:45.870605+08	t	\N
6147	799	\N	080502	材料学	\N	0805	[]	[]	academic	2026-10-19 03:42:45.870606+08	t	\N
6148	799	\N	080503	材料加工工程	\N	0805	[]	[]	academic	2026-10-19 03:42:45.870606+08	t	\N
6149	799	\N	081401	岩土工程	\N	0814	[]	[]	academic	2026-10-19 03:42:45.870606+08	t	\N
6150	799	\N	081402	结构工程	\N	0814	[]	[]	academic	2026-10-19 03:42:45.870607+08	t	\N
6151	799	\N	081405	防灾减灾工程及防护工程	\N	0814	[]	[]	academic	2026-10-19 03:42:45.870607+08	t	\N
6152	799	\N	081406	桥梁与隧道工程	\N	0814	[]	[]	academic	2026-10-19 03:42:45.870608+08	t	\N
6153	799	\N	081501	水文学及水资源	\N	0815	[]	[]	academic	2026-10-19 03:42:45.870608+08	t	\N
6154	799	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 03:42:45.870608+08	t	\N
6155	799	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 03:42:45.870609+08	t	\N
6156	799	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:42:45.870609+08	t	\N
6157	799	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:42:45.87061+08	t	\N
6158	800	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:42:53.062531+08	t	\N
6159	800	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:42:53.062533+08	t	\N
6160	800	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:42:53.062534+08	t	\N
6161	800	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:42:53.062534+08	t	\N
6162	800	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:42:53.062535+08	t	\N
6163	800	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:42:53.062535+08	t	\N
6164	800	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:42:53.062536+08	t	\N
6165	800	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:42:53.062536+08	t	\N
6166	800	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:42:53.062537+08	t	\N
6167	800	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:42:53.062537+08	t	\N
6168	801	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:43:00.566012+08	t	\N
6169	801	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:43:00.566015+08	t	\N
6170	801	\N	085807	清洁能源技术	\N	0858	[]	[]	professional	2026-10-19 03:43:00.566015+08	t	\N
6171	801	\N	085808	储能技术	\N	0858	[]	[]	professional	2026-10-19 03:43:00.566016+08	t	\N
6172	801	\N	085901	土木工程	\N	0859	[]	[]	professional	2026-10-19 03:43:00.566016+08	t	\N
6173	801	\N	085902	水利工程	\N	0859	[]	[]	professional	2026-10-19 03:43:00.566017+08	t	\N
6174	801	\N	086101	轨道交通运输	\N	0861	[]	[]	professional	2026-10-19 03:43:00.566017+08	t	\N
6175	801	\N	086102	道路交通运输	\N	0861	[]	[]	professional	2026-10-19 03:43:00.566017+08	t	\N
6176	801	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:43:00.566018+08	t	\N
6177	801	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:43:00.566018+08	t	\N
6178	801	\N	0703Z2	新材料	\N	0703	[]	[]	academic	2026-10-19 03:43:00.566019+08	t	\N
6179	802	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:43:07.136374+08	t	\N
6180	802	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:43:07.136377+08	t	\N
6181	802	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:43:07.136378+08	t	\N
6182	802	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:43:07.136378+08	t	\N
6183	802	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:43:07.136379+08	t	\N
6184	802	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:43:07.136379+08	t	\N
6185	802	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:43:07.13638+08	t	\N
6186	802	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:43:07.13638+08	t	\N
6187	802	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:43:07.136381+08	t	\N
6188	802	\N	085300	城乡规划	\N	0853	[]	[]	professional	2026-10-19 03:43:07.136381+08	t	\N
6189	802	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:43:07.136382+08	t	\N
6190	802	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:43:07.136382+08	t	\N
6191	802	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:43:07.136382+08	t	\N
6192	802	\N	070501	自然地理学	\N	0705	[]	[]	academic	2026-10-19 03:43:07.136383+08	t	\N
6193	802	\N	070502	人文地理学	\N	0705	[]	[]	academic	2026-10-19 03:43:07.136383+08	t	\N
6194	802	\N	070503	地图学与地理信息系统	\N	0705	[]	[]	academic	2026-10-19 03:43:07.136384+08	t	\N
6195	802	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:43:07.136384+08	t	\N
6196	802	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:43:07.136385+08	t	\N
6197	802	\N	078401	教育技术学	\N	0784	[]	[]	academic	2026-10-19 03:43:07.136385+08	t	\N
6198	803	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:43:13.539405+08	t	\N
6199	803	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:43:13.539407+08	t	\N
6200	803	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:43:13.539408+08	t	\N
6201	803	\N	071008	发育生物学	\N	0710	[]	[]	academic	2026-10-19 03:43:13.539409+08	t	\N
6202	803	\N	071009	细胞生物学	\N	0710	[]	[]	academic	2026-10-19 03:43:13.539409+08	t	\N
6203	803	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:43:13.53941+08	t	\N
6204	803	\N	071011	生物物理学	\N	0710	[]	[]	academic	2026-10-19 03:43:13.53941+08	t	\N
6205	803	\N	0710Z1	化学生物学	\N	0710	[]	[]	academic	2026-10-19 03:43:13.53941+08	t	\N
6206	803	\N	0710Z2	生物信息与计算生物学	\N	0710	[]	[]	academic	2026-10-19 03:43:13.539411+08	t	\N
6207	804	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:43:21.317422+08	t	\N
6208	804	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:43:21.317432+08	t	\N
6209	804	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:43:21.317435+08	t	\N
6210	805	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:43:28.554508+08	t	\N
6211	805	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:43:28.554518+08	t	\N
6212	805	\N	080900	电子科学与技术	\N	0809	[]	[]	academic	2026-10-19 03:43:28.554521+08	t	\N
6213	805	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:43:28.554524+08	t	\N
6214	805	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:43:28.554526+08	t	\N
6215	805	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:43:28.554528+08	t	\N
6216	805	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:43:28.55453+08	t	\N
6217	805	\N	085403	集成电路工程	\N	0854	[]	[]	professional	2026-10-19 03:43:28.554531+08	t	\N
6218	805	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:43:28.554533+08	t	\N
6219	805	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:43:28.554536+08	t	\N
6220	805	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:43:28.554538+08	t	\N
6221	805	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:43:28.55454+08	t	\N
6222	806	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:43:35.496331+08	t	\N
6223	806	\N	085406	控制工程	\N	0854	[]	[]	professional	2026-10-19 03:43:35.496337+08	t	\N
6224	806	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:43:35.496338+08	t	\N
6225	806	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:43:35.49634+08	t	\N
6226	807	\N	080100	力学	\N	0801	[]	[]	academic	2026-10-19 03:43:41.873148+08	t	\N
6227	807	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:43:41.873154+08	t	\N
6228	807	\N	080500	材料科学与工程	\N	0805	[]	[]	academic	2026-10-19 03:43:41.873156+08	t	\N
6229	807	\N	080700	动力工程及工程热物理	\N	0807	[]	[]	academic	2026-10-19 03:43:41.873158+08	t	\N
6230	807	\N	080800	电气工程	\N	0808	[]	[]	academic	2026-10-19 03:43:41.873159+08	t	\N
6231	807	\N	081000	信息与通信工程	\N	0810	[]	[]	academic	2026-10-19 03:43:41.87316+08	t	\N
6232	807	\N	081100	控制科学与工程	\N	0811	[]	[]	academic	2026-10-19 03:43:41.873162+08	t	\N
6233	807	\N	081200	计算机科学与技术	\N	0812	[]	[]	academic	2026-10-19 03:43:41.873163+08	t	\N
6234	807	\N	0812J1	数智文旅	\N	0812	[]	[]	academic	2026-10-19 03:43:41.873165+08	t	\N
6235	807	\N	081300	建筑学	\N	0813	[]	[]	academic	2026-10-19 03:43:41.873166+08	t	\N
6236	807	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:43:41.873167+08	t	\N
6237	807	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:43:41.873169+08	t	\N
6238	807	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:43:41.87317+08	t	\N
6239	807	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:43:41.873171+08	t	\N
6240	807	\N	070900	地质学	\N	0709	[]	[]	academic	2026-10-19 03:43:41.873173+08	t	\N
6241	807	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:43:41.873174+08	t	\N
6242	807	\N	071300	生态学	\N	0713	[]	[]	academic	2026-10-19 03:43:41.873175+08	t	\N
6243	807	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:43:41.873177+08	t	\N
6244	808	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:43:48.022396+08	t	\N
6245	808	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 03:43:48.022407+08	t	\N
6246	808	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:43:48.02241+08	t	\N
6247	808	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:43:48.022412+08	t	\N
6248	808	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:43:48.022415+08	t	\N
6249	808	\N	085412	网络与信息安全	\N	0854	[]	[]	professional	2026-10-19 03:43:48.022417+08	t	\N
6250	808	\N	085501	机械工程	\N	0855	[]	[]	professional	2026-10-19 03:43:48.022419+08	t	\N
6251	808	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:43:48.022421+08	t	\N
6252	808	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:43:48.022423+08	t	\N
6253	808	\N	085604	纺织工程	\N	0856	[]	[]	professional	2026-10-19 03:43:48.022425+08	t	\N
6254	808	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:43:48.022427+08	t	\N
6255	809	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:43:54.135879+08	t	\N
6256	809	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:43:54.135888+08	t	\N
6257	809	\N	082300	交通运输工程	\N	0823	[]	[]	academic	2026-10-19 03:43:54.135891+08	t	\N
6258	809	\N	082801	农业机械化工程	\N	0828	[]	[]	academic	2026-10-19 03:43:54.135893+08	t	\N
6259	809	\N	082802	农业水土工程	\N	0828	[]	[]	academic	2026-10-19 03:43:54.135895+08	t	\N
6260	809	\N	082804	农业电气化与自动化	\N	0828	[]	[]	academic	2026-10-19 03:43:54.135897+08	t	\N
6261	809	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:43:54.135899+08	t	\N
6262	809	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:43:54.135901+08	t	\N
6263	809	\N	085500	机械	\N	0855	[]	[]	professional	2026-10-19 03:43:54.135903+08	t	\N
6264	809	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:43:54.135905+08	t	\N
6265	809	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:43:54.135907+08	t	\N
6266	809	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:43:54.135909+08	t	\N
6267	810	\N	080200	机械工程	\N	0802	[]	[]	academic	2026-10-19 03:44:00.854478+08	t	\N
6268	810	\N	0802J2	低空技术与工程	\N	0802	[]	[]	academic	2026-10-19 03:44:00.85448+08	t	\N
6269	810	\N	0802J3	能源电力与储能工程	\N	0802	[]	[]	academic	2026-10-19 03:44:00.854481+08	t	\N
6270	810	\N	081400	土木工程	\N	0814	[]	[]	academic	2026-10-19 03:44:00.854481+08	t	\N
6271	810	\N	081500	水利工程	\N	0815	[]	[]	academic	2026-10-19 03:44:00.854482+08	t	\N
6272	810	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:44:00.854482+08	t	\N
6273	810	\N	082800	农业工程	\N	0828	[]	[]	academic	2026-10-19 03:44:00.854483+08	t	\N
6274	810	\N	083200	食品科学与工程	\N	0832	[]	[]	academic	2026-10-19 03:44:00.854483+08	t	\N
6275	810	\N	083300	城乡规划学	\N	0833	[]	[]	academic	2026-10-19 03:44:00.854483+08	t	\N
6276	810	\N	083900	网络空间安全	\N	0839	[]	[]	academic	2026-10-19 03:44:00.854484+08	t	\N
6277	810	\N	070100	数学	\N	0701	[]	[]	academic	2026-10-19 03:44:00.854484+08	t	\N
6278	810	\N	070200	物理学	\N	0702	[]	[]	academic	2026-10-19 03:44:00.854485+08	t	\N
6279	810	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:44:00.854485+08	t	\N
6280	810	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:44:00.854485+08	t	\N
6281	810	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:44:00.854486+08	t	\N
6282	811	\N	083100	生物医学工程	\N	0831	[]	[]	academic	2026-10-19 03:44:07.332979+08	t	\N
6283	811	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:44:07.332987+08	t	\N
6284	811	\N	071003	生理学	\N	0710	[]	[]	academic	2026-10-19 03:44:07.332991+08	t	\N
6285	811	\N	071007	遗传学	\N	0710	[]	[]	academic	2026-10-19 03:44:07.332993+08	t	\N
6286	811	\N	071010	生物化学与分子生物学	\N	0710	[]	[]	academic	2026-10-19 03:44:07.332996+08	t	\N
6287	812	\N	083500	软件工程	\N	0835	[]	[]	academic	2026-10-19 03:44:13.93134+08	t	\N
6288	812	\N	085402	通信工程（含宽带网络、移动通信等）	\N	0854	[]	[]	professional	2026-10-19 03:44:13.931349+08	t	\N
6289	812	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:44:13.931352+08	t	\N
6290	812	\N	085600	材料与化工	\N	0856	[]	[]	professional	2026-10-19 03:44:13.931354+08	t	\N
6291	812	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:44:13.931356+08	t	\N
6292	812	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:44:13.931358+08	t	\N
6293	812	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:44:13.93136+08	t	\N
6294	812	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:44:13.931362+08	t	\N
6295	812	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:44:13.931364+08	t	\N
6296	812	\N	070201	理论物理	\N	0702	[]	[]	academic	2026-10-19 03:44:13.931366+08	t	\N
6297	812	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:44:13.931367+08	t	\N
6298	812	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:44:13.931369+08	t	\N
6299	812	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 03:44:13.931371+08	t	\N
6300	812	\N	070300	化学	\N	0703	[]	[]	academic	2026-10-19 03:44:13.931373+08	t	\N
6301	812	\N	070500	地理学	\N	0705	[]	[]	academic	2026-10-19 03:44:13.931375+08	t	\N
6302	812	\N	071000	生物学	\N	0710	[]	[]	academic	2026-10-19 03:44:13.931377+08	t	\N
6303	813	\N	085408	光电信息工程	\N	0854	[]	[]	professional	2026-10-19 03:44:20.67088+08	t	\N
6304	813	\N	085410	人工智能	\N	0854	[]	[]	professional	2026-10-19 03:44:20.670887+08	t	\N
6305	813	\N	085411	大数据技术与工程	\N	0854	[]	[]	professional	2026-10-19 03:44:20.670888+08	t	\N
6306	813	\N	085701	环境工程	\N	0857	[]	[]	professional	2026-10-19 03:44:20.67089+08	t	\N
6307	813	\N	085901	土木工程	\N	0859	[]	[]	professional	2026-10-19 03:44:20.670891+08	t	\N
6308	813	\N	085905	市政工程（含给排水等）	\N	0859	[]	[]	professional	2026-10-19 03:44:20.670892+08	t	\N
6309	813	\N	086000	生物与医药	\N	0860	[]	[]	professional	2026-10-19 03:44:20.670894+08	t	\N
6310	813	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 03:44:20.670896+08	t	\N
6311	813	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:44:20.670897+08	t	\N
6312	813	\N	070304	物理化学	\N	0703	[]	[]	academic	2026-10-19 03:44:20.670898+08	t	\N
6313	813	\N	071001	植物学	\N	0710	[]	[]	academic	2026-10-19 03:44:20.6709+08	t	\N
6314	813	\N	071002	动物学	\N	0710	[]	[]	academic	2026-10-19 03:44:20.670901+08	t	\N
6315	813	\N	071005	微生物学	\N	0710	[]	[]	academic	2026-10-19 03:44:20.670902+08	t	\N
6316	814	\N	085401	新一代电子信息技术（含量子技术等）	\N	0854	[]	[]	professional	2026-10-19 03:44:28.138606+08	t	\N
6317	814	\N	085404	计算机技术	\N	0854	[]	[]	professional	2026-10-19 03:44:28.138615+08	t	\N
6318	814	\N	085700	资源与环境	\N	0857	[]	[]	professional	2026-10-19 03:44:28.138619+08	t	\N
6319	814	\N	070101	基础数学	\N	0701	[]	[]	academic	2026-10-19 03:44:28.138621+08	t	\N
6320	814	\N	070102	计算数学	\N	0701	[]	[]	academic	2026-10-19 03:44:28.138623+08	t	\N
6321	814	\N	070103	概率论与数理统计	\N	0701	[]	[]	academic	2026-10-19 03:44:28.138626+08	t	\N
6322	814	\N	070104	应用数学	\N	0701	[]	[]	academic	2026-10-19 03:44:28.138628+08	t	\N
6323	814	\N	070205	凝聚态物理	\N	0702	[]	[]	academic	2026-10-19 03:44:28.13863+08	t	\N
6324	814	\N	070207	光学	\N	0702	[]	[]	academic	2026-10-19 03:44:28.138632+08	t	\N
6325	814	\N	070208	无线电物理	\N	0702	[]	[]	academic	2026-10-19 03:44:28.138634+08	t	\N
6326	814	\N	070301	无机化学	\N	0703	[]	[]	academic	2026-10-19 03:44:28.138636+08	t	\N
6327	814	\N	070302	分析化学	\N	0703	[]	[]	academic	2026-10-19 03:44:28.138637+08	t	\N
6328	814	\N	070303	有机化学	\N	0703	[]	[]	academic	2026-10-19 03:44:28.138639+08	t	\N
6329	815	\N	085400	电子信息	\N	0854	[]	[]	professional	2026-10-19 03:44:35.142146+08	t	\N
6330	815	\N	071400	统计学	\N	0714	[]	[]	academic	2026-10-19 03:44:35.142157+08	t	\N
6331	817	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:44:48.400499+08	t	\N
6332	817	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:44:48.400501+08	t	\N
6333	817	\N	085702	安全工程	\N	0857	[]	[]	professional	2026-10-19 03:44:48.400501+08	t	\N
6334	817	\N	085703	地质工程	\N	0857	[]	[]	professional	2026-10-19 03:44:48.400502+08	t	\N
6335	817	\N	085705	矿业工程	\N	0857	[]	[]	professional	2026-10-19 03:44:48.400502+08	t	\N
6336	818	\N	081700	化学工程与技术	\N	0817	[]	[]	academic	2026-10-19 03:44:55.274513+08	t	\N
6337	818	\N	085601	材料工程	\N	0856	[]	[]	professional	2026-10-19 03:44:55.274522+08	t	\N
6338	818	\N	085602	化学工程	\N	0856	[]	[]	professional	2026-10-19 03:44:55.274526+08	t	\N
6339	818	\N	085801	电气工程	\N	0858	[]	[]	professional	2026-10-19 03:44:55.274528+08	t	\N
6340	818	\N	085802	动力工程	\N	0858	[]	[]	professional	2026-10-19 03:44:55.27453+08	t	\N
6341	818	\N	086104	航空交通运输	\N	0861	[]	[]	professional	2026-10-19 03:44:55.274532+08	t	\N
\.


--
-- Data for Name: kaoyan_notices; Type: TABLE DATA; Schema: public; Owner: kaoyan
--

COPY public.kaoyan_notices (id, school_id, school_name, title, notice_type, publish_date, url, source, fetched_at, importance_level, importance_score, importance_reason, deadline_date, events_json, classified_at, is_read, is_starred, read_at, starred_at, content, is_noise, created_at) FROM stdin;
17	5	清华大学	152026.06 【2027】清华大学研究生招生宣传周（直播回放）	公告	\N	https://www.xuetangx.com/live/live2026yjszsxcz/live2026yjszsxcz/31264152/83755097?channel=i.area.home_live_ad	yz.tsinghua.edu.cn	2026-10-19T01:31:40	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:31:40.923903+08
152	624	桂林电子科技大学	光电工程学院	公告	2026-07-06	https://www.guet.edu.cn/dept16	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
150	624	桂林电子科技大学	寒露	公告	2026-10-07	http://www.guet.edu.cn/2026/0930/c6358a160512/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
151	624	桂林电子科技大学	徐华蕊	公告	2026-07-21	http://www.guet.edu.cn/2026/0721/c6535a158283/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
153	624	桂林电子科技大学	​王敬宇	公告	2026-03-12	http://www.guet.edu.cn/2026/0312/c9225a149424/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
154	624	桂林电子科技大学	桂林电子科技大学学报	公告	2026-02-27	http://xb.guet.edu.cn	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
155	624	桂林电子科技大学	广西互联网违法和不良信息举报中心	公告	2026-02-27	https://www.gxjubao.org.cn/ 	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
156	624	桂林电子科技大学	校党委书记徐华蕊、副书记聂慧大年初一慰问春节坚守岗位的教职员工（图）	公告	2026-02-17	http://www.guet.edu.cn/2026/0217/c478a148794/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
29	4	北京科技大学	北京科技大学各培养单位接收2027年推免招生工作方案	公告	2026-09-15	https://yzxc.ustb.edu.cn/xlytm/hdap/f7d7b0f7657b41f6afb6d085416fcd22.htm	yzxc.ustb.edu.cn	2026-10-19T01:31:47	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:31:47.740118+08
30	4	北京科技大学	硕士研究生招生	公告	\N	https://yzxc.ustb.edu.cn/sssbkzn/index.htm	yzxc.ustb.edu.cn	2026-10-19T01:31:47	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:31:47.740118+08
31	4	北京科技大学	博士研究生招生	公告	\N	https://yzxc.ustb.edu.cn/bssbkzn/index.htm	yzxc.ustb.edu.cn	2026-10-19T01:31:47	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:31:47.740118+08
32	4	北京科技大学	港澳台研究生招生	公告	\N	https://yzxc.ustb.edu.cn/gatyjsbkzn/index.htm	yzxc.ustb.edu.cn	2026-10-19T01:31:47	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:31:47.740118+08
33	4	北京科技大学	夏令营/推免	公告	\N	https://yzxc.ustb.edu.cn/xlytm/index.htm	yzxc.ustb.edu.cn	2026-10-19T01:31:47	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:31:47.740118+08
157	624	桂林电子科技大学	祝全体师生员工中秋快乐，阖家幸福！	公告	2025-10-09	http://www.guet.edu.cn/2025/0930/c6577a143095/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
158	624	桂林电子科技大学	小暑	公告	2025-07-07	http://www.guet.edu.cn/2025/0707/c6577a140722/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
159	624	桂林电子科技大学	我校举行2025年党员基本培训第一次集中大课	公告	2025-06-27	https://www.guet.edu.cn/2025/0626/c6356a139961/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
160	624	桂林电子科技大学	夏至	公告	2025-06-20	http://www.guet.edu.cn/2025/0620/c6577a140725/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
161	624	桂林电子科技大学	我校举行2025届毕业典礼暨学位授予仪式	公告	2025-06-20	https://www.guet.edu.cn/2025/0620/c6356a139563/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
162	624	桂林电子科技大学	欢迎报考桂林电子科技大学	公告	2025-06-08	http://www.guet.edu.cn/2025/0608/c6577a140726/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
163	624	桂林电子科技大学	小满	公告	2025-06-04	http://www.guet.edu.cn/2025/0520/c6577a138582/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
164	624	桂林电子科技大学	张文涛	公告	2025-05-09	http://www.guet.edu.cn/2025/0509/c9222a137151/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
165	624	桂林电子科技大学	庆祝“五一”国际劳动节	公告	2025-04-30	http://www.guet.edu.cn/2025/0430/c6577a140728/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
166	624	桂林电子科技大学	立夏	公告	2025-04-30	http://www.guet.edu.cn/2025/0430/c6577a140729/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
167	624	桂林电子科技大学	现任领导0429	公告	2025-04-29	http://www.guet.edu.cn/2023/0103/c6393a136810/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
168	624	桂林电子科技大学	清明	公告	2025-04-21	http://www.guet.edu.cn/2025/0403/c6577a136295/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
169	624	桂林电子科技大学	中华民族一家亲 同心共筑中国梦	公告	2025-04-02	http://www.guet.edu.cn/2025/0328/c6577a135339/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
170	624	桂林电子科技大学	“三八”国际劳动妇女节	公告	2025-03-10	http://www.guet.edu.cn/2025/0306/c6577a134093/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
171	624	桂林电子科技大学	元宵佳节	公告	2025-02-11	http://www.guet.edu.cn/2025/0107/c6577a132737/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
172	624	桂林电子科技大学	新春快乐	公告	2025-02-11	http://www.guet.edu.cn/2025/0107/c6577a132736/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
173	624	桂林电子科技大学	立春	公告	2025-02-02	http://www.guet.edu.cn/2025/0108/c6577a132734/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
174	624	桂林电子科技大学	大寒	公告	2025-01-20	http://www.guet.edu.cn/2025/0107/c6577a132692/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
175	624	桂林电子科技大学	立冬	公告	2025-01-02	http://www.guet.edu.cn/2024/1107/c6577a129830/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
176	624	桂林电子科技大学	元旦快乐	公告	2025-01-02	http://www.guet.edu.cn/2024/1231/c6577a132537/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
177	624	桂林电子科技大学	全国匹克球发展研讨会在我校举行	公告	2024-12-21	https://www.guet.edu.cn/2024/1221/c6356a132124/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
178	624	桂林电子科技大学	李宁杯·首届中国匹克球城市挑战赛在我校开赛	公告	2024-12-21	https://www.guet.edu.cn/2024/1221/c6356a132123/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
179	624	桂林电子科技大学	李宁（中国）体育用品有限公司董事长李宁到校考察	公告	2024-12-19	https://www.guet.edu.cn/2024/1219/c6356a132041/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
180	624	桂林电子科技大学	李宁杯·2024年中国匹克球巡回赛总决赛（CPC-2000）在我校开赛	公告	2024-12-19	https://www.guet.edu.cn/2024/1219/c6356a132024/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
181	624	桂林电子科技大学	首届中国匹克球城市挑战赛和巡回赛总决赛在桂电举行	公告	2024-11-29	https://mp.weixin.qq.com/s/wBXLrnQg3ePP3qGj5ru1VQ	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
182	624	桂林电子科技大学	热烈庆祝中华人民共和国成立75周年！	公告	2024-10-08	http://www.guet.edu.cn/2024/0929/c6577a128380/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
183	624	桂林电子科技大学	热烈欢迎2024级新同学	公告	2024-09-18	http://www.guet.edu.cn/2024/0829/c6577a127034/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
184	624	桂林电子科技大学	中秋快乐 阖家幸福	公告	2024-09-18	http://www.guet.edu.cn/2024/0914/c6577a127634/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
42	696	贵州大学	贵州大学2026年硕士研究生招生调剂缺额信息(二)	调剂	2026-04-13	http://gs.gzu.edu.cn/2026/0413/c11835a268424/page.htm	gs.gzu.edu.cn	2026-10-19T01:37:53	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:37:53.053535+08
185	624	桂林电子科技大学	白露	公告	2024-09-08	http://www.guet.edu.cn/2024/0731/c6577a126647/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
186	624	桂林电子科技大学	关于东南大学王承祥教授学术报告会的预告	公告	2024-08-21	http://www.guet.edu.cn/2024/0822/c6362a126769/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
187	624	桂林电子科技大学	端午安康	公告	2024-06-11	http://www.guet.edu.cn/2024/0606/c6577a124637/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
188	624	桂林电子科技大学	芒种	公告	2024-06-06	http://www.guet.edu.cn/2024/0604/c6577a124421/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
189	624	桂林电子科技大学	立夏	公告	2024-05-06	http://www.guet.edu.cn/2024/0426/c6577a122594/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
190	624	桂林电子科技大学	五四青年节快乐	公告	2024-04-26	http://www.guet.edu.cn/2024/0426/c6577a122592/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
191	624	桂林电子科技大学	劳动最光荣	公告	2024-04-26	http://www.guet.edu.cn/2024/0426/c6577a122593/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
192	624	桂林电子科技大学	清明	公告	2024-04-07	http://www.guet.edu.cn/2024/0403/c6577a121061/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
193	624	桂林电子科技大学	张文涛	公告	2024-03-25	http://www.guet.edu.cn/2023/0104/c491a6874/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
194	624	桂林电子科技大学	桂电晨曦	公告	2024-03-15	http://www.guet.edu.cn/2024/0315/c6577a119660/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
195	624	桂林电子科技大学	桂电掠影	公告	2024-03-15	http://www.guet.edu.cn/2024/0315/c6577a119659/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
54	662	电子科技大学	线上招生宣讲会（回放）	公告	2026-10-14	http://yzconsole.360eol.com/web/pc/school.html?id=387	yz.uestc.edu.cn	2026-10-19T01:38:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:38:02.226737+08
55	662	电子科技大学	电子科技大学公共管理学院2025年研究生招生宣传册	公告	2024-07-15	https://yz.uestc.edu.cn/info/1008/5265.htm	yz.uestc.edu.cn	2026-10-19T01:38:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:38:02.226737+08
56	662	电子科技大学	电子科技大学经济与管理学院2025年研究生招生宣传册	公告	2024-07-15	https://yz.uestc.edu.cn/info/1008/5264.htm	yz.uestc.edu.cn	2026-10-19T01:38:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:38:02.226737+08
57	662	电子科技大学	电子科技大学航空航天学院2025年研究生招生宣传册	公告	2024-07-02	https://yz.uestc.edu.cn/info/1008/5215.htm	yz.uestc.edu.cn	2026-10-19T01:38:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:38:02.226737+08
196	624	桂林电子科技大学	满“新”欢喜遇见你	公告	2024-03-11	https://mp.weixin.qq.com/s/c6Rzuiux3wqFRDEkHaX9CQ	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
197	624	桂林电子科技大学	元宵节	公告	2024-02-26	http://www.guet.edu.cn/2024/0224/c6577a117172/page.htm	www.guet.edu.cn	2026-10-19T01:39:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:25.781929+08
268	273	复旦大学	复旦大学主页	公告	2008-01-13	http://www.fudan.edu.cn/	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
269	273	复旦大学	研究生院	公告	2008-01-13	http://www.gs.fudan.edu.cn	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
270	273	复旦大学	心理健康教育中心	公告	2018-09-25	https://gsao.fudan.edu.cn/_redirect?siteId=65&columnId=15025&articleId=156078	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
271	273	复旦大学	学生就业信息网	公告	2018-09-25	https://gsao.fudan.edu.cn/_redirect?siteId=65&columnId=15025&articleId=156077	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
202	5	清华大学	152026.06 【2027】清华大学研究生招生宣传周（直播回放）	公告	\N	https://www.xuetangx.com/live/live2026yjszsxcz/live2026yjszsxcz/31264152/83755097?channel=i.area.home_live_ad	yz.tsinghua.edu.cn	2026-10-19T01:39:34	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:34.651018+08
272	273	复旦大学	校医院	公告	2018-09-25	https://gsao.fudan.edu.cn/_redirect?siteId=65&columnId=15025&articleId=156076	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
273	273	复旦大学	财务处	公告	2018-09-25	https://gsao.fudan.edu.cn/_redirect?siteId=65&columnId=15025&articleId=156075	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
274	273	复旦大学	信息办	公告	2018-09-25	https://gsao.fudan.edu.cn/_redirect?siteId=65&columnId=15025&articleId=156074	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
275	273	复旦大学	研工部	公告	2018-09-25	https://gsao.fudan.edu.cn/_redirect?siteId=65&columnId=15025&articleId=156073	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
276	273	复旦大学	图书馆	公告	2008-01-13	http://www.library.fudan.edu.cn/	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
277	273	复旦大学	学生职业发展教育服务中心	公告	2008-01-13	http://www.career.fudan.edu.cn/jc/index.jsp	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
278	273	复旦大学	档案馆	公告	2008-01-13	http://www.fda.fudan.edu.cn/	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
279	273	复旦大学	现代教育技术中心	公告	2008-01-13	http://educenter.fudan.edu.cn/	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
280	273	复旦大学	日月光华站	公告	2008-01-13	http://bbs.fudan.edu.cn/	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
281	273	复旦大学	人文复旦	公告	2008-01-13	http://www.rwfd.fudan.edu.cn/	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
282	273	复旦大学	复旦大学出版社	公告	2008-01-13	http://www.fudanpress.com.cn/	gsao.fudan.edu.cn	2026-10-19T01:40:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:02.766144+08
445	224	吉林大学	关于2026年吉林大学研究生会纳新工作的通知	公告	2026-09-09	https://yjsy.jlu.edu.cn/info/1060/6460.htm	yjsy.jlu.edu.cn	2026-10-19T01:41:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:57.115175+08
284	317	南京大学	博士生答辩公示平台	录取	2022-05-06	https://ehallapp.nju.edu.cn/gsapp/sys/dbgsglappecupl/*default/index.do	grawww.nju.edu.cn	2026-10-19T01:40:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:10.004961+08
285	317	南京大学	研究生迎新系统	公告	2023-06-26	https://grawww.nju.edu.cn/_redirect?siteId=24&columnId=994&articleId=12580	grawww.nju.edu.cn	2026-10-19T01:40:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:10.004961+08
446	224	吉林大学	关于公开选拔吉林大学研究生会第二十二届主席团成员及各部门主要负责人的通知	公告	2026-04-30	https://yjsy.jlu.edu.cn/info/1060/6394.htm	yjsy.jlu.edu.cn	2026-10-19T01:41:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:57.115175+08
447	224	吉林大学	关于举办2025年吉林大学“研冠杯”首届匹克球赛的通知	公告	2025-11-06	https://yjsy.jlu.edu.cn/info/1060/6117.htm	yjsy.jlu.edu.cn	2026-10-19T01:41:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:57.115175+08
448	224	吉林大学	吉林大学招生网	公告	\N	http://zsb.jlu.edu.cn/	yjsy.jlu.edu.cn	2026-10-19T01:41:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:57.115175+08
542	5	清华大学	152026.06 【2027】清华大学研究生招生宣传周（直播回放）	公告	\N	https://www.xuetangx.com/live/live2026yjszsxcz/live2026yjszsxcz/31264152/83755097?channel=i.area.home_live_ad	yz.tsinghua.edu.cn	2026-10-19T02:01:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:01:15.323362+08
1987	275	上海交通大学	预推免公示	录取	\N	https://yzb.sjtu.edu.cn/xxgs/ytmgs	yzb.sjtu.edu.cn	2026-10-19T04:58:41	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:41.962472+08
298	245	哈尔滨工业大学	哈尔滨工业大学 2027年 “申请-考核”秋季博士招生的工作通知 2026-09-08	公告	2026-09-08	https://yzb.hit.edu.cn/2026/0908/c22278a401201/page.htm	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
299	245	哈尔滨工业大学	苏州高等研究院2027年博士研究生秋季招生简介 2026-09-30	公告	2026-09-30	https://yzb.hit.edu.cn/2026/0930/c19935a402245/page.htm	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
300	245	哈尔滨工业大学	重庆研究院2027年博士研究生秋季招生简介 2026-09-29	公告	2026-09-29	https://yzb.hit.edu.cn/2026/0929/c19935a402234/page.htm	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
301	245	哈尔滨工业大学	与国家实验室联培—2027年苏州国家实验室博士秋季招生简介 2026-09-20	公告	2026-09-20	https://yzb.hit.edu.cn/2026/0920/c19935a401816/page.htm	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
302	245	哈尔滨工业大学	郑州高等研究院2027年博士研究生秋季招生简介 2026-09-20	公告	2026-09-20	https://yzb.hit.edu.cn/2026/0920/c19935a401805/page.htm	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
303	245	哈尔滨工业大学	与国家实验室联培—2027年鹏城国家实验室博士秋季招生简介 2026-09-16	公告	2026-09-16	https://yzb.hit.edu.cn/2026/0916/c19935a401675/page.htm	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
93	735	西安电子科技大学	2025年博士研究生招生简章及专业目录	简章	\N	https://gr.xidian.edu.cn/info/1072/14464.htm	gr.xidian.edu.cn	2026-10-19T01:38:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:38:09.177694+08
304	245	哈尔滨工业大学	未来工学院2027年博士研究生秋季招生简介 2026-09-11	公告	2026-09-11	https://yzb.hit.edu.cn/2026/0911/c19935a401436/page.htm	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
305	245	哈尔滨工业大学	2027年与军事科学院联合培养博士秋季招生介绍 2026-09-10	公告	2026-09-10	https://yzb.hit.edu.cn/2026/0910/c19935a401353/page.htm	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
237	6	北京大学	北京大学地球与空间科学学院2026年学术博士研究生拟录取公示名单（不含专项计划）	录取	2026-04-29	https://sess.pku.edu.cn/info/1107/31221.htm	admission.pku.edu.cn	2026-10-19T01:39:40	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:40.712561+08
238	6	北京大学	北京大学化学与分子工程学院2026年申请-考核制、留学生博士招生拟录取公示名单	录取	2026-04-27	https://www.chem.pku.edu.cn/tzgg11/ceb0668320844d92b3618a7cf1726628.htm	admission.pku.edu.cn	2026-10-19T01:39:40	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:40.712561+08
306	245	哈尔滨工业大学	与国家实验室联培—2027年启元国家实验室科研计划博士秋季招生简介 2026-09-09	公告	2026-09-09	https://yzb.hit.edu.cn/2026/0909/c19935a401285/page.htm	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
307	245	哈尔滨工业大学	与国家实验室联培—2027年崖州湾国家实验室科研计划博士秋季招生简介 2026-09-08	公告	2026-09-08	https://yzb.hit.edu.cn/2026/0908/c19935a401213/page.htm	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
308	245	哈尔滨工业大学	直播预告 - 2026研究生招生线上宣讲会（5月20日 - 5月28日）	公告	\N	https://yzb.hit.edu.cn/2026/0526/c22289a393138/page.htm	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
239	6	北京大学	北京大学经济学院2026年博士招生拟录取名单公示	录取	2026-04-17	https://econ.pku.edu.cn/jxxm/zsxxfb_20211202144549787517/2c75c4ab924f4fed91694779881e51a0.htm	admission.pku.edu.cn	2026-10-19T01:39:40	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:40.712561+08
240	6	北京大学	北京大学光华管理学院2026年高级管理人员工商管理硕士招生拟录取公示	录取	2026-04-16	https://www.gsm.pku.edu.cn/emba/info/1158/14179.htm	admission.pku.edu.cn	2026-10-19T01:39:40	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:40.712561+08
241	6	北京大学	北京大学未来技术学院2026年“申请-考核制”学术型全日制博士招生拟录取公示名单（不含专项计划）	录取	2026-04-15	https://future.pku.edu.cn/xwzk/543476ceb01a4ed9b264996d10e0a764.htm	admission.pku.edu.cn	2026-10-19T01:39:40	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:40.712561+08
242	6	北京大学	北京大学国际关系学院2026年博士研究生招生拟录取名单公示	录取	2026-04-15	https://www.sis.pku.edu.cn/postgraduate/enrollment89101/08b39ee539704ec19277de1f7b36e8ce.htm	admission.pku.edu.cn	2026-10-19T01:39:40	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:40.712561+08
309	245	哈尔滨工业大学	10月16日19:00 | 哈工大研究生招生线上宣讲会：经济与管理学院MTT中心专场 2026-10-15	公告	2026-10-15	https://mp.weixin.qq.com/s/sVzMEOQtntNJARVNeP_64Q	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
310	245	哈尔滨工业大学	10月15日18:00丨哈工大研究生招生线上宣讲会：重庆研究院、苏州高等研究院、未来工学院 2026-10-14	公告	2026-10-14	https://mp.weixin.qq.com/s/mZrgTy5vs0OQQ-f7a-cfNA	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
311	245	哈尔滨工业大学	10月14日18:30 | 哈工大研究生招生线上宣讲会：郑州高等研究院专场 2026-10-14	公告	2026-10-14	https://mp.weixin.qq.com/s/qzKtM4ReG2rPSypNdTVQCg	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
312	245	哈尔滨工业大学	预告丨哈工大研究生招生线上宣讲会，敬请期待！ 2026-10-14	公告	2026-10-14	https://mp.weixin.qq.com/s/jmu-TuA7srk-An5lnL573w	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
313	245	哈尔滨工业大学	博士招生动态 | 戴通宇教授团队 2026-09-23	公告	2026-09-23	https://mp.weixin.qq.com/s/wBPj8Wj7EjEaAoXVUIkCTw	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
314	245	哈尔滨工业大学	博士招生动态 | 姜巨福教授团队 2026-09-22	公告	2026-09-22	https://mp.weixin.qq.com/s/07pq5_JncG7Y2XMC1TuRfQ	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
315	245	哈尔滨工业大学	逐梦哈工大，研途启新程｜6月12日哈工大研究生招生校园开放日精彩瞬间 查看招生简章	简章	\N	https://mp.weixin.qq.com/s/dsXuJkkOWd9OueOJ9jYIRw	yzb.hit.edu.cn	2026-10-19T01:40:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:25.780669+08
556	4	北京科技大学	硕士研究生招生	公告	\N	https://yzxc.ustb.edu.cn/sssbkzn/index.htm	yzxc.ustb.edu.cn	2026-10-19T02:01:23	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:01:23.332501+08
557	4	北京科技大学	博士研究生招生	公告	\N	https://yzxc.ustb.edu.cn/bssbkzn/index.htm	yzxc.ustb.edu.cn	2026-10-19T02:01:23	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:01:23.332501+08
558	4	北京科技大学	港澳台研究生招生	公告	\N	https://yzxc.ustb.edu.cn/gatyjsbkzn/index.htm	yzxc.ustb.edu.cn	2026-10-19T02:01:23	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:01:23.332501+08
262	275	上海交通大学	上海交通大学中英国际低碳学院招生宣讲活动预告 | 上海 徐州 南京 （4月2日-4月3日）	公告	2025-03-27	https://yzb.sjtu.edu.cn/post/2995	yzb.sjtu.edu.cn	2026-10-19T01:39:52	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:52.795285+08
263	275	上海交通大学	上海交通大学设计学院研究生招生宣传手册（2025）	公告	2024-05-28	https://yzb.sjtu.edu.cn/post/2569	yzb.sjtu.edu.cn	2026-10-19T01:39:52	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:52.795285+08
264	275	上海交通大学	上海交通大学技术转移硕士MTT招生宣传册(2025)	公告	2024-05-22	https://yzb.sjtu.edu.cn/post/2568	yzb.sjtu.edu.cn	2026-10-19T01:39:52	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:52.795285+08
265	275	上海交通大学	上海交通大学安泰金融硕士项目宣传册（2025） 05.22/2024	公告	\N	https://yzb.sjtu.edu.cn/post/2562	yzb.sjtu.edu.cn	2026-10-19T01:39:52	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:52.795285+08
266	275	上海交通大学	上海交通大学环境学院研究生招生宣传手册（2025） 2025年环境学院研究生招生宣传手册.pdf 注：本资料仅供参考，最终招生办法以教育部2025年硕士研究生招生相关政策和学校2025年硕士研究生招生简章为准	简章	2024-05-22	https://yzb.sjtu.edu.cn/post/2566	yzb.sjtu.edu.cn	2026-10-19T01:39:52	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:52.795285+08
267	275	上海交通大学	医学院招生网	公告	2024-04-05	https://www.shsmu.edu.cn/yjsy/zsgz1.htm	yzb.sjtu.edu.cn	2026-10-19T01:39:52	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:39:52.795285+08
559	4	北京科技大学	夏令营/推免	公告	\N	https://yzxc.ustb.edu.cn/xlytm/index.htm	yzxc.ustb.edu.cn	2026-10-19T02:01:23	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:01:23.332501+08
1055	563	湖南大学	复试录取名单	复试	\N	https://gra.hnu.edu.cn/index/xxgk/fslqmd.htm	gra.hnu.edu.cn	2026-10-19T02:06:53	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:06:53.245022+08
1159	326	南京邮电大学	关于公布南京邮电大学2026年硕士研究生复试分数线的通知	复试	2026-03-19	http://yzb.njupt.edu.cn/2026/0319/c7797a298050/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1160	326	南京邮电大学	南京邮电大学2026年硕士研究生招生复试录取工作办法	复试	2026-03-19	http://yzb.njupt.edu.cn/2026/0318/c7797a298033/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1161	326	南京邮电大学	关于南京邮电大学2026年硕士研究生招生考试初试成绩排名查询的通知	初试	2026-03-05	http://yzb.njupt.edu.cn/2026/0305/c7797a297448/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1162	326	南京邮电大学	关于2026年博士研究生招生英语水平考试（笔试）的通知	公告	2026-03-02	http://yzb.njupt.edu.cn/2026/0302/c7798a297270/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1163	326	南京邮电大学	关于2026年硕士研究生招生考试初试成绩公布及相关工作安排的通知	初试	2026-02-26	http://yzb.njupt.edu.cn/2026/0226/c7797a297150/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1164	326	南京邮电大学	2026年招收博士研究生申请考核制实施细则	公告	2025-12-15	http://yzb.njupt.edu.cn/2025/1215/c7798a294413/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1165	326	南京邮电大学	关于2026年申请考核制博士生招生报名工作的通知	报名	2025-12-10	http://yzb.njupt.edu.cn/2025/1208/c7798a293705/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1166	326	南京邮电大学	南京邮电大学2026年博士研究生招生专业目录	目录	2025-12-09	http://yzb.njupt.edu.cn/2025/1209/c7796a293779/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1988	275	上海交通大学	预推免考生登录	公告	\N	http://ga.sjtu.edu.cn/zsgl/ytmgl	yzb.sjtu.edu.cn	2026-10-19T04:58:41	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:41.962472+08
1056	696	贵州大学	贵州大学2027年拟录取推荐免试硕士研究生名单公示网站链接汇总	录取	2026-10-13	http://gs.gzu.edu.cn/2026/1013/c11835a280603/page.htm	gs.gzu.edu.cn	2026-10-19T02:07:48	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:43.763526+08
329	732	西安交通大学	西安交通大学各学院（部、中心）2027年招收推免生实施细...	公告	2026-09-03	https://yz.xjtu.edu.cn/info/1086/4391.htm	yz.xjtu.edu.cn	2026-10-19T01:40:31	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:31.965682+08
330	732	西安交通大学	西安交通大学2026年面向香港、澳门、台湾地区招收硕士研...	公告	2025-12-21	https://yz.xjtu.edu.cn/2026gatsszsml.pdf	yz.xjtu.edu.cn	2026-10-19T01:40:31	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:40:31.965682+08
331	517	华中科技大学	关于校党委对研究生院开展教师队伍管理专项巡视的公告	公告	2026-10-09	https://gs.hust.edu.cn/info/1043/6835.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
332	517	华中科技大学	同济医学院2026级硕士《心理压力与应对》分班名单	公告	2026-10-08	https://gs.hust.edu.cn/info/1039/6833.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
333	517	华中科技大学	关于做好2026年12月研究生毕（结）业相关工作的通知	公告	2026-10-08	https://gs.hust.edu.cn/info/1043/6832.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
334	517	华中科技大学	关于2026年中秋节、国庆节期间研究生课程教学安排的通知	公告	2026-09-14	https://gs.hust.edu.cn/info/1037/6812.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
335	517	华中科技大学	关于启动2027年创新型人才国际合作培养项目实施工作的通知 关于启动2027年创新型人才国际合作培养项目实施工作的通知学校各培养单位： …	公告	2026-07-17	https://gs.hust.edu.cn/info/1038/6793.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
336	517	华中科技大学	关于报送2026年（12月）学位材料的通知 各院（系）：2026年（12月）报送学位材料的截止日期为2026年12月3日，请各学位评定…	公告	2026-07-08	https://gs.hust.edu.cn/info/1042/6831.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
337	517	华中科技大学	关于报送2026年（9月）学位材料的通知	公告	2026-07-08	https://gs.hust.edu.cn/info/1042/6735.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
338	517	华中科技大学	关于报送2026年（6月）学位材料的通知	公告	2026-03-31	https://gs.hust.edu.cn/info/1042/6672.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
339	517	华中科技大学	关于报送2026年（3月）学位材料的通知	公告	2025-12-23	https://gs.hust.edu.cn/info/1042/6606.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
340	517	华中科技大学	关于报送2025年（12月）学位材料的通知	公告	2025-09-25	https://gs.hust.edu.cn/info/1042/6527.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
341	517	华中科技大学	关于报送2025年（9月）学位材料的通知	公告	2025-06-23	https://gs.hust.edu.cn/info/1042/6452.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
342	517	华中科技大学	同济医学院2026级硕士《心理压力与应对》分班名单 请选修《心理压力与应对》课程的研究生，按照附件分班去上课。如确有特殊原因需要调…	公告	2026-09-28	https://gs.hust.edu.cn/info/1039/6833.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
343	517	华中科技大学	同济医学院2026级研究生10月份课程考试通知	公告	2026-09-28	https://gs.hust.edu.cn/info/1039/6819.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
344	517	华中科技大学	同济医学院2026级硕士《急诊医学》考试通知	公告	2026-09-18	https://gs.hust.edu.cn/info/1039/6815.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
345	517	华中科技大学	同济医学院2026级硕士生《急诊医学》上课通知	公告	2026-09-09	https://gs.hust.edu.cn/info/1039/6808.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
346	517	华中科技大学	医学院2026级硕士研究生《自然辩证法概论》上课通知	公告	2026-09-07	https://gs.hust.edu.cn/info/1039/6804.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
347	517	华中科技大学	关于征集高等教育领域学科大模型的通知	公告	2026-09-11	https://ugs.hust.edu.cn/info/1142/7558.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
348	517	华中科技大学	关于做好2026级研究生新生图像信息采集工作的通知	公告	2026-08-31	https://gs.hust.edu.cn/info/1043/6791.htm	gs.hust.edu.cn	2026-10-19T01:41:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:09.127015+08
783	275	上海交通大学	上海交通大学安泰金融硕士项目宣传册（2025） 05.22/2024	公告	\N	https://yzb.sjtu.edu.cn/post/2562	yzb.sjtu.edu.cn	2026-10-19T02:04:07	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:04:07.652902+08
1057	696	贵州大学	2027年全国硕士研究生招生考试贵州大学考点通告（一）	公告	2026-10-08	http://gs.gzu.edu.cn/2026/1008/c11835a280245/page.htm	gs.gzu.edu.cn	2026-10-19T02:07:48	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:43.763526+08
1058	696	贵州大学	贵州大学关于2027年招收退役大学生士兵计划硕士研究生的通知	公告	2026-10-08	http://gs.gzu.edu.cn/2026/1008/c11835a280238/page.htm	gs.gzu.edu.cn	2026-10-19T02:07:48	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:43.763526+08
1059	696	贵州大学	贵州大学关于2027年招收少数民族高层次骨干人才计划硕士研究生的通知	公告	2026-10-08	http://gs.gzu.edu.cn/2026/1008/c11835a280237/page.htm	gs.gzu.edu.cn	2026-10-19T02:07:48	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:43.763526+08
1060	696	贵州大学	贵州大学2027年硕士研究生招生章程	公告	2026-10-08	http://gs.gzu.edu.cn/2026/1008/c11835a280219/page.htm	gs.gzu.edu.cn	2026-10-19T02:07:48	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:43.763526+08
1061	696	贵州大学	贵州大学2027年接收优秀应届本科毕业生免试攻读硕士学位研究生实施办法	公告	2026-09-15	http://gs.gzu.edu.cn/2026/0915/c11835a279487/page.htm	gs.gzu.edu.cn	2026-10-19T02:07:48	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:43.763526+08
1062	696	贵州大学	贵州大学关于2026年硕士研究生录取通知书邮寄相关信息填报的通知	录取	2026-06-15	http://gs.gzu.edu.cn/2026/0615/c11835a275738/page.htm	gs.gzu.edu.cn	2026-10-19T02:07:48	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:43.763526+08
1063	696	贵州大学	关于调整贵州大学2027年硕士研究生招生考试（初试）科目的通知	初试	2026-05-29	http://gs.gzu.edu.cn/2026/0529/c11835a275127/page.htm	gs.gzu.edu.cn	2026-10-19T02:07:48	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:43.763526+08
1064	696	贵州大学	贵州大学2026年硕士研究生招生调剂缺额信息(三)	调剂	2026-04-14	http://gs.gzu.edu.cn/2026/0414/c11835a268502/page.htm	gs.gzu.edu.cn	2026-10-19T02:07:48	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:43.763526+08
1066	662	电子科技大学	招生宣讲会	公告	\N	http://yzconsole.360eol.com/web/adjust/school_detail.html?id=387	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
1067	662	电子科技大学	硕士简章目录	简章	\N	https://yz.uestc.edu.cn/sszs/zsjz.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
360	11	北京理工大学	硕士学位论文盲评系统	公告	\N	http://pyxt.bit.edu.cn/	grd.bit.edu.cn	2026-10-19T01:41:28	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:28.378091+08
1068	662	电子科技大学	博士简章目录	简章	\N	https://yz.uestc.edu.cn/bszs/zsjz.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
826	245	哈尔滨工业大学	直播预告 - 2026研究生招生线上宣讲会（5月20日 - 5月28日）	公告	\N	https://yzb.hit.edu.cn/2026/0526/c22289a393138/page.htm	yzb.hit.edu.cn	2026-10-19T02:04:37	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:04:37.558387+08
833	245	哈尔滨工业大学	逐梦哈工大，研途启新程｜6月12日哈工大研究生招生校园开放日精彩瞬间 查看招生简章	简章	\N	https://mp.weixin.qq.com/s/dsXuJkkOWd9OueOJ9jYIRw	yzb.hit.edu.cn	2026-10-19T02:04:37	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:04:37.558387+08
1069	662	电子科技大学	硕士历年复试分数线	复试	\N	https://yz.uestc.edu.cn/xxcx/sslnfsfsx.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
366	274	同济大学	同济大学2027年招收单独考试攻读硕士研究生...	公告	2026-10-08	https://yz.tongji.edu.cn/info/1012/4248.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
367	274	同济大学	同济大学2027年招收攻读硕士学位研究生招生...	公告	2026-10-08	https://yz.tongji.edu.cn/info/1012/4247.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
368	274	同济大学	同济大学2026年面向港澳台地区拟录取研究生...	录取	2026-06-16	https://yz.tongji.edu.cn/info/1014/4201.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
369	274	同济大学	2026年同济大学面向港澳台地区研究生招生考...	公告	2026-05-22	https://yzbm.tongji.edu.cn/xxgs/gatLq	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
370	274	同济大学	同济大学2026年全国港澳台研究生招生考试初...	公告	2026-04-27	https://yz.tongji.edu.cn/info/1014/4168.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
371	274	同济大学	2026年面向港澳台地区研究生招生考试考场规...	公告	2026-04-08	https://yz.tongji.edu.cn/info/1014/4149.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
372	274	同济大学	2026年面向港澳台地区研究生招生考试同济大...	公告	2026-04-03	https://yz.tongji.edu.cn/info/1014/4140.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
373	274	同济大学	2026年拟录取定向就业博士研究生签订合同通...	录取	2026-07-02	https://yz.tongji.edu.cn/info/1011/4209.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
374	274	同济大学	2026年秋季入学拟录取博士研究生相关事宜的...	录取	2026-06-09	https://yz.tongji.edu.cn/info/1011/4192.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
375	274	同济大学	2026年秋季入学博士研究生录取通知书发放通...	录取	2026-07-09	https://yz.tongji.edu.cn/info/1011/4221.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
376	274	同济大学	2026年拟录取博士生公示信息八	录取	2026-06-30	https://yz.tongji.edu.cn/info/1011/4207.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
377	274	同济大学	2026年拟录取博士生公示信息七	录取	2026-06-25	https://yz.tongji.edu.cn/info/1011/4205.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
378	274	同济大学	2026年拟录取博士生公示信息六	录取	2026-06-22	https://yz.tongji.edu.cn/info/1011/4204.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
379	274	同济大学	2026年拟录取博士生公示信息五	录取	2026-06-16	https://yz.tongji.edu.cn/info/1011/4198.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
380	274	同济大学	同济大学2027年数字经济硕士（MDE）招生简...	公告	2026-10-12	https://yz.tongji.edu.cn/info/1013/4251.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
381	274	同济大学	同济大学2027年工程管理硕士（MEM）招生简...	公告	2026-10-12	https://yz.tongji.edu.cn/info/1013/4250.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
382	274	同济大学	同济大学2026年硕士研究生招生考试工程类...	公告	2026-03-30	https://yz.tongji.edu.cn/info/1013/4139.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
383	274	同济大学	同济大学2025年硕士研究生招生考试工程类...	公告	2025-03-25	https://yz.tongji.edu.cn/info/1013/3870.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
384	274	同济大学	卓越联盟高校研究生招生信息网	公告	2012-09-29	https://yz.tongji.edu.cn/info/1015/1206.htm	yz.tongji.edu.cn	2026-10-19T01:41:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:35.913955+08
1070	662	电子科技大学	电子科技大学关于研究生招生工作的郑重声明	公告	2025-07-07	https://yz.uestc.edu.cn/info/1041/5546.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
1071	662	电子科技大学	电子科技大学2027年硕士研究生招生章程	公告	2026-10-08	https://yz.uestc.edu.cn/info/1081/5968.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
1072	662	电子科技大学	电子科技大学2027年招收攻读硕士学位研究生专业目录	目录	2026-10-08	https://yzbm.uestc.edu.cn/zsml/sszsml/index/2027	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
1073	662	电子科技大学	电子科技大学（代码：10614）2027年全国硕士研究生招生考试网上报名公告	报名	2026-10-08	https://yz.uestc.edu.cn/info/1081/5970.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
1074	662	电子科技大学	电子科技大学报考点（代码：5103）2027年全国硕士研究生招生考试网上报...	公告	2026-10-08	https://yz.uestc.edu.cn/info/1081/5974.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
1075	662	电子科技大学	关于报考我校2027年少数民族高层次骨干人才计划有关事项的说明	公告	2026-10-08	https://yz.uestc.edu.cn/info/1081/5596.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
953	185	大连理工大学	大连理工大学2026年博士研究生拟录取名单公示-增补名单2	录取	\N	https://gs.dlut.edu.cn/info/1173/51462.htm	gs.dlut.edu.cn	2026-10-19T02:06:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:06:02.271203+08
1076	662	电子科技大学	研究生招生管理系统	公告	\N	https://yz.uestc.edu.cn/zsglxtjm.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
1077	662	电子科技大学	【博士】转发：北京中关村学院2026年专项营活动通知 ZGCA AI＋X Camp	公告	2026-09-18	https://yz.uestc.edu.cn/info/1004/5955.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
954	185	大连理工大学	关于2025年基础学科导师创新基金评审结果公示	录取	\N	https://gs.dlut.edu.cn/info/1004/17026.htm	gs.dlut.edu.cn	2026-10-19T02:06:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:06:02.271203+08
955	185	大连理工大学	关于召开2025年首聘研究生导师培训会的通知	公告	\N	https://portal.dlut.edu.cn/tp/index.html#act=sems-tp-nup_28585749&contentid=&ownerid=&website=0&pim_id=11857642000556032	gs.dlut.edu.cn	2026-10-19T02:06:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:06:02.271203+08
956	185	大连理工大学	关于申报2025年研究生导师创新基金的通知	公告	\N	https://gs.dlut.edu.cn/info/1004/16936.htm	gs.dlut.edu.cn	2026-10-19T02:06:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:06:02.271203+08
957	185	大连理工大学	关于开展2025年“1+X学科交叉导师团队” 专项申报工作的通知	公告	\N	https://gs.dlut.edu.cn/info/1004/16256.htm	gs.dlut.edu.cn	2026-10-19T02:06:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:06:02.271203+08
961	185	大连理工大学	博士答辩公告	公告	\N	https://dutgs.dlut.edu.cn/gmis/xw/dbgggs.aspx	gs.dlut.edu.cn	2026-10-19T02:06:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:06:02.271203+08
962	185	大连理工大学	硕士答辩公告	公告	\N	https://dutgs.dlut.edu.cn/gmis/xw/dbggssgs.aspx	gs.dlut.edu.cn	2026-10-19T02:06:02	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:06:02.271203+08
966	224	吉林大学	吉林大学招生网	公告	\N	http://zsb.jlu.edu.cn/	yjsy.jlu.edu.cn	2026-10-19T02:06:09	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:06:09.413002+08
1078	662	电子科技大学	【博士】转发：深圳河套学院“深瞳计划”第三期招募通知	公告	2026-09-17	https://yz.uestc.edu.cn/info/1004/5944.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
1079	662	电子科技大学	【博士】2026年博士生培养有关专项（项目）报名通知汇总	报名	2026-04-22	https://yz.uestc.edu.cn/info/1004/5794.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
1080	662	电子科技大学	【博士】电子科技大学2026年高等研究院校企联合培养博士生项目招生报名...	报名	2026-04-09	https://yz.uestc.edu.cn/info/1204/5978.htm	yz.uestc.edu.cn	2026-10-19T02:07:57	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:07:57.817086+08
1085	735	西安电子科技大学	硕士研究生招生	公告	\N	https://gr.xidian.edu.cn/yjsy/yjszs.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1086	735	西安电子科技大学	博士研究生招生	公告	\N	https://gr.xidian.edu.cn/yjsy/bsyjszs.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1087	735	西安电子科技大学	其他类型招生	公告	\N	https://gr.xidian.edu.cn/yjsy/qtlxzs.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1088	735	西安电子科技大学	关于推荐上报2026年研究生各类课程与教材建设项目的通知	公告	2026-09-17	https://gr.xidian.edu.cn/info/1073/20624.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1089	735	西安电子科技大学	关于开展2024年度、2025年度研究生各类课程与教材建设项目的结题及中期验收工作的通知	公告	2026-09-17	https://gr.xidian.edu.cn/info/1073/20614.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1090	735	西安电子科技大学	关于2026年秋季学期“学术规范与论文写作”、“科学道德与学风”等网上在线课程的开课通知	公告	2026-09-29	https://gr.xidian.edu.cn/info/1073/20794.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
878	11	北京理工大学	硕士学位论文盲评系统	公告	\N	http://pyxt.bit.edu.cn/	grd.bit.edu.cn	2026-10-19T02:05:42	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:05:42.635912+08
411	108	天津大学	关于2026年拟录取博士生修改录取通知书邮寄地址的通知	录取	2026-05-26	https://yzb.tju.edu.cn/./xwzx/tkbs_xw/202605/t20260526_324650.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
412	108	天津大学	【专博录取】2026年专业型博士研究生拟录取名单公示汇总	录取	2026-05-20	https://yzb.tju.edu.cn/./xwzx/tkbs_xw/202605/t20260520_324646.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
413	108	天津大学	【专项录取】天津大学与青海民族大学2026年联合培养博士拟录取名单...	录取	2026-05-24	https://yzb.tju.edu.cn/./xwzx/tkbs_xw/202605/t20260524_324649.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
414	108	天津大学	【专项录取】2026年天津大学-崂山国家实验室联合培养科研经费博士...	录取	2026-05-21	https://yzb.tju.edu.cn/./xwzx/tkbs_xw/202605/t20260521_324647.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
415	108	天津大学	【专项录取】2026年天津大学-怀柔实验室联合培养博士研究生专项计...	录取	2026-05-18	https://yzb.tju.edu.cn/./xwzx/tkbs_xw/202605/t20260518_324644.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
416	108	天津大学	【专项录取】天津大学2026年海南专项博士研究生拟录取名单公示汇总	录取	2026-05-18	https://yzb.tju.edu.cn/./xwzx/tkbs_xw/202605/t20260518_324643.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
417	108	天津大学	天津大学2026年同等学力人员申请博士学位招生简章	简章	2026-04-30	https://yzb.tju.edu.cn/./xwzx/zzxw/202604/t20260430_324629.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
418	108	天津大学	天津大学2026年同等学力人员申请硕士学位招生简章	简章	2026-04-30	https://yzb.tju.edu.cn/./xwzx/zzxw/202604/t20260430_324628.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
419	108	天津大学	天津大学关于2023年同等学力博士、硕士入学有关工作的通知	公告	2023-10-07	https://yzb.tju.edu.cn/./xwzx/zzxw/202310/t20231007_323409.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
420	108	天津大学	关于2023年同等学力硕士、博士录取通知书EMS邮寄单号查询的通知	录取	2023-09-27	https://yzb.tju.edu.cn/./xwzx/zzxw/202309/t20230927_323403.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
421	108	天津大学	2023年以同等学力申请硕士、博士学位人员拟录取名单公示	录取	2023-09-20	https://yzb.tju.edu.cn/./xwzx/zzxw/202309/t20230920_323393.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
422	108	天津大学	天津大学关于2023年同等学力人员申请硕士、博士学位学费标准及收费...	公告	2023-06-13	https://yzb.tju.edu.cn/./xwzx/zzxw/202306/t20230613_323243.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
1091	735	西安电子科技大学	【转发】关于邀请参加2026博士生国际招生面试交流会的通知	公告	2026-09-20	https://gr.xidian.edu.cn/info/1073/20634.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1092	735	西安电子科技大学	关于组织推荐2026年中国科协青年科技人才培育工程博士生专项计划候选人的通知	公告	2026-08-14	https://gr.xidian.edu.cn/info/1073/20444.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
423	108	天津大学	天津大学2023年同等学力人员申请硕士学位招生简章	简章	2023-05-29	https://yzb.tju.edu.cn/./xwzx/zzxw/202305/t20230529_323229.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
424	108	天津大学	天津大学2023年同等学力人员申请博士学位招生简章	简章	2023-05-29	https://yzb.tju.edu.cn/./xwzx/zzxw/202305/t20230529_323226.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
425	108	天津大学	关于2022年同等学力硕士、博士录取通知书EMS邮寄单号查询的通知	录取	2022-10-11	https://yzb.tju.edu.cn/./xwzx/zzxw/202210/t20221011_322682.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
426	108	天津大学	天津大学关于2022年同等学力博士、硕士入学有关工作的通知	公告	2022-09-23	https://yzb.tju.edu.cn/./xwzx/zzxw/202209/t20220923_322632.htm	yzb.tju.edu.cn	2026-10-19T01:41:43	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:43.192115+08
1093	735	西安电子科技大学	关于2026年秋季学期“学术规范与论文写作”、“科学道德与学风”等网上在线课程的开课通知	公告	\N	https://gr.xidian.edu.cn/info/1037/20784.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1094	735	西安电子科技大学	关于2026年春季学期“学术规范与论文写作”、“科学道德与学风”等网上在线课程的开课通知	公告	\N	https://gr.xidian.edu.cn/info/1037/18614.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1095	735	西安电子科技大学	产教融通课《秦创原“四链融合”示范课：关键技术的市场路径》开课通知	公告	\N	https://gr.xidian.edu.cn/info/1037/18394.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1096	735	西安电子科技大学	西安电子科技大学关于受理2026年1月研究生结业申请的通知	公告	\N	https://gr.xidian.edu.cn/info/1037/17604.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1097	735	西安电子科技大学	关于2025年秋季学期“学术规范与论文写作”、“科学道德与学风”等网上在线课程的开课通知	公告	\N	https://gr.xidian.edu.cn/info/1037/17244.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1098	735	西安电子科技大学	西安电子科技大学工商管理、公共管理硕士申请学位相关资料	公告	\N	https://gr.xidian.edu.cn/info/1047/5083.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1099	735	西安电子科技大学	西安电子科技大学申请同等学力硕士学位相关资料	公告	\N	https://gr.xidian.edu.cn/info/1047/5084.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
515	733	西北工业大学	关于2026年博士研究生招生拟录取名单的公示及修改通讯地址的通知2026-06-22	录取	2026-06-11	https://yzb.nwpu.edu.cn/info/1179/10448.htm	yzb.nwpu.edu.cn	2026-10-19T01:42:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:42:32.682291+08
435	185	大连理工大学	大连理工大学2026年博士研究生拟录取名单公示-增补名单2	录取	\N	https://gs.dlut.edu.cn/info/1173/51462.htm	gs.dlut.edu.cn	2026-10-19T01:41:50	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:50.087403+08
436	185	大连理工大学	关于2025年基础学科导师创新基金评审结果公示	录取	\N	https://gs.dlut.edu.cn/info/1004/17026.htm	gs.dlut.edu.cn	2026-10-19T01:41:50	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:50.087403+08
437	185	大连理工大学	关于召开2025年首聘研究生导师培训会的通知	公告	\N	https://portal.dlut.edu.cn/tp/index.html#act=sems-tp-nup_28585749&contentid=&ownerid=&website=0&pim_id=11857642000556032	gs.dlut.edu.cn	2026-10-19T01:41:50	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:50.087403+08
438	185	大连理工大学	关于申报2025年研究生导师创新基金的通知	公告	\N	https://gs.dlut.edu.cn/info/1004/16936.htm	gs.dlut.edu.cn	2026-10-19T01:41:50	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:50.087403+08
439	185	大连理工大学	关于开展2025年“1+X学科交叉导师团队” 专项申报工作的通知	公告	\N	https://gs.dlut.edu.cn/info/1004/16256.htm	gs.dlut.edu.cn	2026-10-19T01:41:50	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:50.087403+08
440	185	大连理工大学	2025年全国研究生招生工作学术研讨及培训会在我校召开	公告	2025-07-09	https://news.dlut.edu.cn/info/1022/122474.htm	gs.dlut.edu.cn	2026-10-19T01:41:50	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:50.087403+08
441	185	大连理工大学	大连理工大学研究生招生工作管理规定（修订）	公告	2026-03-25	https://gs.dlut.edu.cn/info/1031/49702.htm	gs.dlut.edu.cn	2026-10-19T01:41:50	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:50.087403+08
442	185	大连理工大学	大连理工大学2026年博士研究生 复试录取工作办法	复试	2025-11-07	https://gs.dlut.edu.cn/info/1031/48002.htm	gs.dlut.edu.cn	2026-10-19T01:41:50	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:50.087403+08
443	185	大连理工大学	博士答辩公告	公告	\N	https://dutgs.dlut.edu.cn/gmis/xw/dbgggs.aspx	gs.dlut.edu.cn	2026-10-19T01:41:50	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:50.087403+08
444	185	大连理工大学	硕士答辩公告	公告	\N	https://dutgs.dlut.edu.cn/gmis/xw/dbggssgs.aspx	gs.dlut.edu.cn	2026-10-19T01:41:50	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:41:50.087403+08
516	733	西北工业大学	关于2026年普通工程博士（定向就业类型）拟录取名单的公示2026-06-11	录取	2026-06-03	https://yzb.nwpu.edu.cn/info/1179/10438.htm	yzb.nwpu.edu.cn	2026-10-19T01:42:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:42:32.682291+08
517	733	西北工业大学	西北工业大学2026年普通工程博士复试工作方案2026-06-03	复试	2026-05-28	https://yzb.nwpu.edu.cn/info/1179/10428.htm	yzb.nwpu.edu.cn	2026-10-19T01:42:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:42:32.682291+08
518	733	西北工业大学	西北工业大学-汉江实验室2026年联合培养博士研究生专项计划招生公告（二）2026-05-28	公告	2026-05-28	https://yzb.nwpu.edu.cn/info/1179/10398.htm	yzb.nwpu.edu.cn	2026-10-19T01:42:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:42:32.682291+08
519	733	西北工业大学	历年硕士研究生考试复试基本分数线	复试	\N	https://yzb.nwpu.edu.cn/new/sszs/fsfsx.htm	yzb.nwpu.edu.cn	2026-10-19T01:42:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:42:32.682291+08
1100	735	西安电子科技大学	西安电子科技大学专业学位硕士申请学位相关资料	公告	\N	https://gr.xidian.edu.cn/info/1047/5086.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1101	735	西安电子科技大学	西安电子科技大学学术学位硕士申请学位相关资料	公告	\N	https://gr.xidian.edu.cn/info/1047/5087.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1102	735	西安电子科技大学	关于申报2026年秋季优秀博士学位论文资助基金的通知	公告	\N	https://gr.xidian.edu.cn/info/1044/20724.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1103	735	西安电子科技大学	关于对2026年9月申请授位研究生学位论文进行抽查评估的通知	公告	\N	https://gr.xidian.edu.cn/info/1044/20484.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
619	735	西安电子科技大学	2025年博士研究生招生简章及专业目录	简章	\N	https://gr.xidian.edu.cn/info/1072/14464.htm	gr.xidian.edu.cn	2026-10-19T02:02:33	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:02:33.315995+08
1104	735	西安电子科技大学	关于开展2026年度中国人工智能学会博士学位论文激励计划推荐工作的通知	公告	\N	https://gr.xidian.edu.cn/info/1044/20354.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1105	735	西安电子科技大学	关于开展2026年度中国通信学会博士硕士学位论文激励计划推荐工作的通知	公告	\N	https://gr.xidian.edu.cn/info/1044/20194.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1106	735	西安电子科技大学	关于开展2026年度中国指挥与控制学会博士学位论文激励计划推荐工作的通知	公告	\N	https://gr.xidian.edu.cn/info/1044/20094.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1107	735	西安电子科技大学	关于组织推荐2026年中国科协青年科技人才培育工程博士生专项计划候选人的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/20454.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1108	735	西安电子科技大学	关于评选2025年度西安电子科技大学优秀研究生导师及研究生教育与学科建设管理工作先进集体和先进个人的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/19094.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1109	735	西安电子科技大学	关于开展2025年度研究生导师能力提升 “红专计划”明德育人专题论坛的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/19134.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1110	735	西安电子科技大学	关于开展研究生导师“应知应会”考试的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/19104.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1111	735	西安电子科技大学	关于开展 2025 年度研究生导师能力提升 “红专计划”导学关系主题在线研修培训的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/19114.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1112	735	西安电子科技大学	关于开展2025届研究生毕业季“立德树人结硕果，桃李芬芳启新程”育人风采征集展示活动的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/19124.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
537	563	湖南大学	复试录取名单	复试	\N	https://gra.hnu.edu.cn/index/xxgk/fslqmd.htm	gra.hnu.edu.cn	2026-10-19T01:42:38	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:42:38.955391+08
1113	735	西安电子科技大学	关于评选2024年度西安电子科技大学优秀研究生导师及研究生教育与学科建设管理工作先进集体和先进个人的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/15014.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1114	735	西安电子科技大学	2026年国家建设高水平大学公派研究生项目选派通知	公告	\N	https://gr.xidian.edu.cn/info/1040/17964.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1115	735	西安电子科技大学	2025年师生“双一流”海外研修项目报名通知	报名	\N	https://gr.xidian.edu.cn/info/1040/16674.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1116	735	西安电子科技大学	2025年国家建设高水平大学公派研究生项目选派通知	公告	\N	https://gr.xidian.edu.cn/info/1040/14914.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1117	735	西安电子科技大学	【转发】关于邀请参加2025博士生国际招生面试交流会的通知	公告	\N	https://gr.xidian.edu.cn/info/1040/17084.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1118	735	西安电子科技大学	转发：关于参加2024博士生国际招生面试交流会的通知	公告	\N	https://gr.xidian.edu.cn/info/1040/13804.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1119	735	西安电子科技大学	2024年第二批师生“双一流”海外研修项目报名通知	报名	\N	https://gr.xidian.edu.cn/info/1040/13513.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1120	735	西安电子科技大学	2024年国家建设高水平大学公派研究生项目选派通知	公告	\N	https://gr.xidian.edu.cn/info/1040/13265.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1121	735	西安电子科技大学	2024年首批师生“双一流”海外研修项目报名通知	报名	\N	https://gr.xidian.edu.cn/info/1040/13254.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1122	735	西安电子科技大学	2023博士生国际招生面试交流会参会通知	公告	\N	https://gr.xidian.edu.cn/info/1040/13160.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1123	735	西安电子科技大学	2023年第二批师生“双一流”海外研修项目报名通知	报名	\N	https://gr.xidian.edu.cn/info/1040/13029.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1124	735	西安电子科技大学	2027年少数民族高层次骨干人才计划硕士研究生报考说明	公告	\N	https://gr.xidian.edu.cn/info/1074/21034.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1125	735	西安电子科技大学	2027年全国硕士研究生招生考试网上报名公告	报名	\N	https://gr.xidian.edu.cn/info/1074/20864.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1126	735	西安电子科技大学	2027年硕士研究生招生考试自命题科目考试大纲	大纲	\N	https://gr.xidian.edu.cn/info/1074/20824.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1127	735	西安电子科技大学	2027年硕士研究生招生简章	简章	\N	https://gr.xidian.edu.cn/info/1074/20804.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1128	735	西安电子科技大学	2027年接收推荐免试研究生预报名通知	报名	\N	https://gr.xidian.edu.cn/info/1074/20424.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1129	735	西安电子科技大学	西安电子科技大学2026年预选工程博士遴选结果通知	公告	\N	https://gr.xidian.edu.cn/info/1075/20294.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1130	735	西安电子科技大学	关于2026年拟录取博士研究生办理相关事宜的通知	录取	\N	https://gr.xidian.edu.cn/info/1075/20114.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1131	735	西安电子科技大学	2026年博士研究生招生简章及专业目录	简章	\N	https://gr.xidian.edu.cn/info/1072/17664.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1132	735	西安电子科技大学	2026年硕士研究生招生考试自命题科目考试大纲	大纲	\N	https://gr.xidian.edu.cn/info/1072/17324.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1133	735	西安电子科技大学	2026年硕士研究生招生简章	简章	\N	https://gr.xidian.edu.cn/info/1072/17294.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1634	660	四川大学	招生学院(系/所)	公告	\N	https://yz.scu.edu.cn/contact/yxs	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
649	326	南京邮电大学	南启西程 邮谱新篇 | 南京邮电大学2026级研究生招生宣讲会（西安场）即将来袭！	公告	2025-06-24	http://yzb.njupt.edu.cn/2025/0624/c7797a286367/page.htm	yzb.njupt.edu.cn	2026-10-19T02:03:05	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:03:06.158122+08
1134	735	西安电子科技大学	2025年博士研究生招生简章及专业目录	简章	\N	https://gr.xidian.edu.cn/info/1072/14464.htm	gr.xidian.edu.cn	2026-10-19T02:08:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:04.756085+08
1135	326	南京邮电大学	2027年全国硕士研究生入学考试南京邮电大学（3226）报考点网报公告	公告	2026-10-08	http://yzb.njupt.edu.cn/2026/1008/c12466a309298/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1136	326	南京邮电大学	南京邮电大学2027年硕士研究生招生学院及专业方向介绍	公告	2026-10-08	http://yzb.njupt.edu.cn/2026/1008/c7795a309303/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1137	326	南京邮电大学	南京邮电大学2027年接收推荐免试攻读研究生(含直博生)复试录取的通知（第二批次）（持续更新中）	复试	2026-09-25	http://yzb.njupt.edu.cn/2026/0925/c7797a309195/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1138	326	南京邮电大学	2026年博士研究生录取情况	录取	2026-08-31	http://yzb.njupt.edu.cn/2026/0831/c10372a307754/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1139	326	南京邮电大学	2026年博士研究生拟录取名单公示（补录）（公示已结束）	录取	2026-06-25	http://yzb.njupt.edu.cn/2026/0625/c11142a305456/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1140	326	南京邮电大学	南京邮电大学2026年拟录取博士研究生调档等相关通知	录取	2026-06-18	http://yzb.njupt.edu.cn/2026/0617/c7798a305085/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1141	326	南京邮电大学	2026年博士研究生拟录取名单公示（第三批次）（公示已结束）	录取	2026-06-17	http://yzb.njupt.edu.cn/2026/0617/c11142a305082/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1142	326	南京邮电大学	关于2026年硕士研究生录取通知书寄发工作的友情提醒	录取	2026-06-16	http://yzb.njupt.edu.cn/2026/0616/c7797a305005/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1143	326	南京邮电大学	2026年各学院硕士研究生分专业复试分数线及报考录取情况表	复试	2026-06-11	http://yzb.njupt.edu.cn/2026/0529/c7813a302875/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1144	326	南京邮电大学	​邮见未来 研续精彩|南京邮电大学2027年研究生招生线下咨询会来啦	公告	2026-06-10	http://yzb.njupt.edu.cn/2026/0610/c7797a303941/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1145	326	南京邮电大学	关于2026年申请考核制博士生招生第三轮报名工作的通知	报名	2026-06-02	http://yzb.njupt.edu.cn/2026/0602/c7798a303217/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1146	326	南京邮电大学	南启西程，陕耀研途｜南京邮电大学2027年研究生招生宣讲咨询会【西安场】即将启幕！	公告	2026-05-27	http://yzb.njupt.edu.cn/2026/0527/c7797a302745/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1147	326	南京邮电大学	关于2026年硕士研究生师生互选结果查询与录取通知书寄发工作的预通知	录取	2026-05-20	http://yzb.njupt.edu.cn/2026/0520/c7797a302313/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1148	326	南京邮电大学	筑梦南邮 研途丰硕 | 南京邮电大学2027年硕士研究生招生线上宣讲会精彩来袭！	公告	2026-05-20	http://yzb.njupt.edu.cn/2026/0520/c7797a302266/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1037	733	西北工业大学	历年硕士研究生考试复试基本分数线	复试	\N	https://yzb.nwpu.edu.cn/new/sszs/fsfsx.htm	yzb.nwpu.edu.cn	2026-10-19T02:06:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:06:46.964021+08
1149	326	南京邮电大学	南京邮电大学2026年博士研究生招生英语水平考试（笔试）的通知	公告	2026-05-15	http://yzb.njupt.edu.cn/2026/0515/c7798a301973/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1150	326	南京邮电大学	南京邮电大学2026年高校区域技术转移转化中心南京信息通信分中心博士研究生专项招生报名的通知	报名	2026-05-13	http://yzb.njupt.edu.cn/2026/0513/c7798a301830/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1151	326	南京邮电大学	关于延长申请考核制博士生招生第二轮报名时间的通知	报名	2026-05-13	http://yzb.njupt.edu.cn/2026/0513/c7798a301818/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1152	326	南京邮电大学	关于2026年申请考核制博士生招生第二轮报名工作的通知	报名	2026-04-30	http://yzb.njupt.edu.cn/2026/0430/c7798a301299/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1153	326	南京邮电大学	关于南京邮电大学2026级硕士研究生拟录取新生近期工作安排的通知	录取	2026-04-29	http://yzb.njupt.edu.cn/2026/0429/c7797a301134/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1154	326	南京邮电大学	博学致士，南来兴邮｜南京邮电大学2026-2027年博士研究生招生线上宣讲会重磅来袭！	公告	2026-04-20	http://yzb.njupt.edu.cn/2026/0420/c7798a300416/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1155	326	南京邮电大学	各招生学院2026年研究生招生调剂复试录取工作实施细则	复试	2026-04-07	http://yzb.njupt.edu.cn/2026/0319/c7797a298067/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1156	326	南京邮电大学	南京邮电大学2026年硕士研究生招生拟接收调剂专业预告	调剂	2026-04-02	http://yzb.njupt.edu.cn/2026/0402/c7797a299037/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
722	5	清华大学	152026.06 【2027】清华大学研究生招生宣传周（直播回放）	公告	\N	https://www.xuetangx.com/live/live2026yjszsxcz/live2026yjszsxcz/31264152/83755097?channel=i.area.home_live_ad	yz.tsinghua.edu.cn	2026-10-19T02:03:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:03:46.593028+08
1157	326	南京邮电大学	各招生学院2026年研究生招生复试录取工作实施细则	复试	2026-03-20	http://yzb.njupt.edu.cn/2026/0319/c7797a299143/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1158	326	南京邮电大学	南京邮电大学2026年硕士研究生复试考生须知	复试	2026-03-19	http://yzb.njupt.edu.cn/2026/0319/c7797a298058/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1989	275	上海交通大学	硕士考生登录	公告	\N	http://ga.sjtu.edu.cn/ksxt/login.aspx	yzb.sjtu.edu.cn	2026-10-19T04:58:41	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:41.962472+08
1167	326	南京邮电大学	南京邮电大学2026年博士研究生招生章程	公告	2025-12-09	http://yzb.njupt.edu.cn/2025/1209/c7796a293778/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1168	326	南京邮电大学	2026年全国硕士研究生招生考试考场规则	公告	2025-12-07	http://yzb.njupt.edu.cn/2025/1207/c12466a293628/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1169	326	南京邮电大学	南京邮电大学2026年硕士研究生招生考试自命题科目答题纸条形码粘贴说明	公告	2025-12-07	http://yzb.njupt.edu.cn/2025/1202/c12466a293008/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1170	326	南京邮电大学	2026年全国硕士研究生招生考试网上报名阶段的重要提醒	报名	2025-10-17	http://yzb.njupt.edu.cn/2025/1017/c7797a290208/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1171	326	南京邮电大学	2026年全国硕士研究生入学考试南京邮电大学（3226）报考点网报公告	公告	2025-10-09	http://yzb.njupt.edu.cn/2025/1009/c12466a289737/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1172	326	南京邮电大学	南京邮电大学2026年全国硕士研究生招生网上报名公告	报名	2025-10-09	http://yzb.njupt.edu.cn/2025/1009/c7797a289736/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1173	326	南京邮电大学	南京邮电大学2026年硕士研究生初试科目参考教材及考试大纲	大纲	2025-09-30	http://yzb.njupt.edu.cn/2025/0715/c11185a287293/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1174	326	南京邮电大学	南京邮电大学2026年硕士研究生招生专业目录	目录	2025-09-30	http://yzb.njupt.edu.cn/2025/0929/c7795a289588/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1175	326	南京邮电大学	南京邮电大学2026年硕士研究生招生章程	公告	2025-09-30	http://yzb.njupt.edu.cn/2025/0928/c7795a289524/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1176	326	南京邮电大学	各学院2026年接收推荐免试攻读研究生(含直博生)复试录取工作细则	复试	2025-09-19	http://yzb.njupt.edu.cn/2025/0919/c7797a289033/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1177	326	南京邮电大学	南京邮电大学2026年接收直博生招生专业一览表	公告	2025-09-17	http://yzb.njupt.edu.cn/2025/0917/c7800a288894/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1178	326	南京邮电大学	南京邮电大学2026年接收推免生攻读硕士学位招生专业一览表	公告	2025-09-17	http://yzb.njupt.edu.cn/2025/0917/c7800a288893/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1179	326	南京邮电大学	南京邮电大学关于接收2026年推荐免试攻读研究生（含直博生）的通知	公告	2025-09-15	http://yzb.njupt.edu.cn/2025/0915/c7800a288726/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1180	326	南京邮电大学	邮见未来 研续精彩|南京邮电大学2026年研究生招生线下咨询会来啦	公告	2025-08-31	http://yzb.njupt.edu.cn/2025/0829/c7797a287980/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1181	326	南京邮电大学	2025年博士研究生录取情况	录取	2025-08-27	http://yzb.njupt.edu.cn/2026/0831/c10372a307753/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1182	326	南京邮电大学	南京邮电大学2026年硕士研究生招生专业目录（预告版）	目录	2025-07-15	http://yzb.njupt.edu.cn/2025/0715/c7797a287290/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1183	326	南京邮电大学	关于2025年硕士研究生录取通知书寄发工作的友情提醒	录取	2025-07-02	http://yzb.njupt.edu.cn/2025/0702/c7797a286785/page.htm	yzb.njupt.edu.cn	2026-10-19T02:08:46	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:08:46.202451+08
1185	644	重庆邮电大学	重庆邮电大学2027年全国硕士研究生招生考试报名公告	报名	2026-10-08	https://yjs.cqupt.edu.cn/info/1181/15514.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1186	644	重庆邮电大学	重庆邮电大学2027年硕士研究生招生章程	公告	2026-10-01	https://yjs.cqupt.edu.cn/info/1180/15484.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1187	644	重庆邮电大学	重庆邮电大学各招生学院2027年推免复试考核实施细则	复试	2026-09-16	https://yjs.cqupt.edu.cn/info/1180/15444.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1188	644	重庆邮电大学	重庆邮电大学2027年接收优秀应届本科毕业生免试攻读研究生（含直博生）招生录取工作办法	录取	2026-09-16	https://yjs.cqupt.edu.cn/info/1180/15424.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1189	644	重庆邮电大学	精彩回放∣重庆邮电大学2027年研究生招生直播宣讲会成功举办	公告	2026-09-13	https://yjs.cqupt.edu.cn/info/1180/15404.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1190	644	重庆邮电大学	重庆邮电大学关于选拔推荐2026级研究生参加重庆人工智能学院招生培养（第五批）的通知	公告	2026-06-09	https://yjs.cqupt.edu.cn/info/1184/14734.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1191	644	重庆邮电大学	关于开展第二十一届中国研究生电子设计竞赛西南赛区评审工作的通知	公告	2026-06-08	https://yjs.cqupt.edu.cn/info/1184/14724.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1192	644	重庆邮电大学	重庆邮电大学关于选拔推荐2026级研究生参加重庆人工智能学院招生培养（第四批）的通知	公告	2026-05-21	https://yjs.cqupt.edu.cn/info/1184/14624.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1193	644	重庆邮电大学	“华为杯”第二十三届中国研究生数学建模竞赛参赛通知（国甲）	公告	2026-05-07	https://yjs.cqupt.edu.cn/info/1184/14464.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1194	644	重庆邮电大学	重庆邮电大学关于选拔推荐2026级研究生参加重庆人工智能学院招生培养（第三批）的通知	公告	2026-04-22	https://yjs.cqupt.edu.cn/info/1184/14224.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1195	644	重庆邮电大学	关于做好2026年秋季学期博士研究生学位论文答辩及学位授予工作的通知	公告	2026-09-14	https://yjs.cqupt.edu.cn/info/1194/15414.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1196	644	重庆邮电大学	关于做好2026年秋季学期硕士研究生学位论文答辩及学位授予工作的通知	公告	2026-09-04	https://yjs.cqupt.edu.cn/info/1194/15384.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1197	644	重庆邮电大学	关于公布2026年重庆市研究生科研创新项目立项名单的通知	公告	2026-06-29	https://yjs.cqupt.edu.cn/info/1194/14804.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1198	644	重庆邮电大学	关于开展2026年重庆市研究生科研创新项目申报工作的通知	公告	2026-04-30	https://yjs.cqupt.edu.cn/info/1194/14434.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1199	644	重庆邮电大学	关于开展2026年重庆市研究生科研创新项目结题工作的通知	公告	2026-04-21	https://yjs.cqupt.edu.cn/info/1194/14114.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1200	644	重庆邮电大学	2026年吐鲁番市高层次和急需紧缺人才引进公告	公告	2026-04-08	https://yjs.cqupt.edu.cn/info/1191/14054.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1201	644	重庆邮电大学	关于举办全国信息通讯与互联网行业面向2026届高校毕业生秋季招聘活动的通知	公告	2025-10-14	https://yjs.cqupt.edu.cn/info/1191/13334.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1202	644	重庆邮电大学	关于举办全国能源动力行业面向2026届高校毕业生秋季招聘活动的通知	公告	2025-10-13	https://yjs.cqupt.edu.cn/info/1191/13324.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1203	644	重庆邮电大学	关于自动化学院研究生王潇洋的专利公示	录取	2025-06-03	https://yjs.cqupt.edu.cn/info/1191/11784.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1204	644	重庆邮电大学	关于举办重庆市2025届普通高校毕业生管理类网络招聘会的通知	公告	2025-04-23	https://yjs.cqupt.edu.cn/info/1191/11444.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1205	644	重庆邮电大学	各招生学院联系方式	公告	\N	http://yjs.cqupt.edu.cn/info/1183/4923.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1206	644	重庆邮电大学	重邮硕士招生调剂工作方案	调剂	\N	https://yjs.cqupt.edu.cn/info/1180/11254.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1207	644	重庆邮电大学	再次开通重庆邮电大学2024年博士研究生招生报名系统通知	报名	\N	https://yjs.cqupt.edu.cn/info/1179/8254.htm	yjs.cqupt.edu.cn	2026-10-19T02:09:04	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:04.212856+08
1256	5	清华大学	招生综合信息平台	公告	\N	https://yzbm.tsinghua.edu.cn/publish/infors	yz.tsinghua.edu.cn	2026-10-19T02:09:24	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:24.922236+08
1257	5	清华大学	招生信息Admissions	公告	\N	https://yz.tsinghua.edu.cn/zsxx/sszs/jzml.htm	yz.tsinghua.edu.cn	2026-10-19T02:09:24	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:24.922236+08
1258	5	清华大学	最新公告Notice	公告	\N	https://yz.tsinghua.edu.cn/zxgg.htm	yz.tsinghua.edu.cn	2026-10-19T02:09:24	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:24.922236+08
1259	5	清华大学	082026.10 2027年清华大学初步录取强基生的信息校对和网上确认的相关通知	录取	\N	https://yz.tsinghua.edu.cn/info/1024/3276.htm	yz.tsinghua.edu.cn	2026-10-19T02:09:24	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:24.922236+08
1260	5	清华大学	082026.10 清华大学2027年硕士研究生招生专业目录_统招(含招生人数)	目录	\N	https://yzbm.tsinghua.edu.cn/publish/s02/s0203/detail/c0fb8664-255f-4d6f-bf40-a5893e3343ec	yz.tsinghua.edu.cn	2026-10-19T02:09:24	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:24.922236+08
1261	5	清华大学	082026.10 2027年全国硕士研究生招生考试清华大学报考点（1103）公告	公告	\N	https://yz.tsinghua.edu.cn/info/1024/3270.htm	yz.tsinghua.edu.cn	2026-10-19T02:09:24	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:24.922236+08
1262	5	清华大学	082026.10 2027年全国硕士研究生招生考试清华大学（10003）报名公告	报名	\N	https://yz.tsinghua.edu.cn/info/1024/3268.htm	yz.tsinghua.edu.cn	2026-10-19T02:09:24	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:24.922236+08
1263	5	清华大学	082026.10 清华大学2027年硕士研究生招生简章	简章	\N	https://yz.tsinghua.edu.cn/info/1024/3266.htm	yz.tsinghua.edu.cn	2026-10-19T02:09:24	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:24.922236+08
1264	5	清华大学	182026.09 2027年推荐免试直硕、直博生履行正式报名手续的通知及资格复审要求	报名	\N	https://yz.tsinghua.edu.cn/info/1024/3262.htm	yz.tsinghua.edu.cn	2026-10-19T02:09:24	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:24.922236+08
1265	5	清华大学	国际招生 International Admissions	公告	\N	https://yz.tsinghua.edu.cn/zsxx/gjxs/tzgg.htm	yz.tsinghua.edu.cn	2026-10-19T02:09:24	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:24.922236+08
1266	5	清华大学	152026.06 【2027】清华大学研究生招生宣传周（直播回放）	公告	\N	https://www.xuetangx.com/live/live2026yjszsxcz/live2026yjszsxcz/31264152/83755097?channel=i.area.home_live_ad	yz.tsinghua.edu.cn	2026-10-19T02:09:24	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:24.922236+08
1267	6	北京大学	留学生招生	公告	\N	https://admission.pku.edu.cn/zsxx/lxszs/index.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1268	6	北京大学	硕士招生公示	录取	\N	https://admission.pku.edu.cn/xxgk/xxgkssbm/index.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1269	6	北京大学	博士招生公示	录取	\N	https://admission.pku.edu.cn/xxgk/xxgkbsbm/index.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1270	6	北京大学	院系招生公示	录取	\N	https://admission.pku.edu.cn/xxgk/xxgkyxgs/index.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1271	6	北京大学	&#xe603; 硕士招生	公告	\N	https://admission.pku.edu.cn/zsxx/sszs/index.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1272	6	北京大学	&#xe61e; 博士招生	公告	\N	https://admission.pku.edu.cn/zsxx/bszs/index.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1273	6	北京大学	&#xe886; 港澳台招生	公告	\N	https://admission.pku.edu.cn/zsxx/gatzs/index.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1274	6	北京大学	&#xe607; 留学生招生	公告	\N	https://admission.pku.edu.cn/zsxx/lxszs/index.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1275	6	北京大学	北京大学2027年高级管理人员工商管理（EMBA）专业学位硕士研究生招生简章	简章	2026-10-09	https://admission.pku.edu.cn/docs/20261009163855012333.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1276	6	北京大学	2027年全国硕士研究生招生考试北京大学（1101）报考点公告	公告	2026-10-08	https://admission.pku.edu.cn/docs/20261009083412449071.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1277	6	北京大学	附件：2027年研考北京大学（1101）报考点考生上传材料清单	公告	2026-10-08	https://admission.pku.edu.cn/docs/20261009083438232128.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1278	6	北京大学	2027年全国硕士研究生招生考试北京大学（10001）网报公告	公告	2026-10-08	https://admission.pku.edu.cn/docs/20261009151327494248.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1279	6	北京大学	北京大学 2027 年硕士研究生招生简章（校本部）	简章	2026-10-08	https://admission.pku.edu.cn/docs/20261008162609970607.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1280	6	北京大学	北京大学 2026 年高校思想政治工作骨干在职攻读博士学位 专项计划招生说明 （第二批）	公告	2026-06-16	https://admission.pku.edu.cn/tzgg/4048.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1281	6	北京大学	关于核对并确认录取通知书邮寄地址的通知	录取	2026-06-15	https://admission.pku.edu.cn/docs/20260615110827088250.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1282	6	北京大学	北京大学2026年高校思想政治工作骨干在职攻读博士学位专项计划招生说明	公告	2026-05-09	https://admission.pku.edu.cn/tzgg/4011.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1283	6	北京大学	筑梦北大，未名启航 北京大学研究生招生宣讲咨询会（成都场）	公告	2026-05-08	https://admission.pku.edu.cn/docs/20260508113136030813.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1284	6	北京大学	北京大学2026年硕士研究生招生复试基本分数线	复试	2026-03-13	https://admission.pku.edu.cn/docs/20260313100201705627.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1285	6	北京大学	北京大学2026年硕士研究生招生考试初试成绩查询及相关事宜	初试	2026-02-27	https://admission.pku.edu.cn/docs/20260227145642851518.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1286	6	北京大学	北京大学2026年面向香港、澳门、台湾地区招收硕士研究生、博士研究生网上报名事项说明	报名	2025-11-06	https://admission.pku.edu.cn/docs/20251106105459083299.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1287	6	北京大学	北京大学2026年面向香港、澳门、台湾地区招收硕士研究生、博士研究生招生简章（校本部）	简章	2025-11-06	https://admission.pku.edu.cn/docs/20251106104113194034.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1288	6	北京大学	北京大学(10001)关于核对（修改）2026年应试硕士生网报信息项公告	公告	2025-11-04	https://admission.pku.edu.cn/tzgg/1680.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1289	6	北京大学	北京大学2026年外国留学生研究生招生简章（校本部）	简章	2025-10-20	https://admission.pku.edu.cn/docs/20251020095346239221.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1290	6	北京大学	北京大学2026年硕士研究生招生简章（校本部）	简章	2025-10-09	https://admission.pku.edu.cn/docs/20251009101959431969.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1291	6	北京大学	北京大学2025年硕士研究生招生复试基本分数线	复试	2025-03-12	https://admission.pku.edu.cn/docs/20250312160154148797.pdf	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1292	6	北京大学	北京大学关于报考2025年少数民族高层次骨干人才计划有关事项的说明	公告	2024-10-16	https://admission.pku.edu.cn/tzgg/3338.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1293	6	北京大学	关于2021级新生确认录取通知书邮寄地址的通知	录取	2021-06-18	https://admission.pku.edu.cn/tzgg/1889.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1294	6	北京大学	北京市2021年全国硕士研究生招生考试新冠肺炎病毒核酸检测告知书	公告	2020-12-10	https://www.bjeea.cn/html/yk/sszkzc/2020/1210/77238.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1295	6	北京大学	北京市2021年全国硕士研究生招生考试疫情防控考生须知	公告	2020-12-10	https://www.bjeea.cn/html/yk/sszkzc/2020/1210/77237.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1296	6	北京大学	2020级研究生新生报到通知	公告	2020-08-17	https://admission.pku.edu.cn/tzgg/1479.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1297	6	北京大学	关于“申请-考核制”内地博士研究生及港澳台研究生信息确认的通知	公告	2020-06-29	https://admission.pku.edu.cn/tzgg/1451.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1298	6	北京大学	关于新生确认录取通知书邮寄地址的通知	录取	2020-06-23	https://admission.pku.edu.cn/tzgg/1442.htm	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1299	6	北京大学	北京大学2020年硕士研究生招生复试工作Q&A	复试	2020-04-14	https://mp.weixin.qq.com/s/NctDa0TtOwLEke0I28JSDA	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1300	6	北京大学	北京大学2027年硕士研究生招生专业目录（校本部）	目录	2026-10-08	https://admission.pku.edu.cn/zsxx/sszs/zyml/2027/yx/zsml_ss_yx.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1301	6	北京大学	北京大学2027年推荐免试攻读博士学位研究生专业目录(校本部)	目录	2026-09-15	https://admission.pku.edu.cn/zsxx/bszs/bstjms/2027/yx/zsml_bs_tm.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1302	6	北京大学	北京大学2026年博士研究生招生专业目录(校本部、按院系)	目录	2025-10-10	https://admission.pku.edu.cn/zsxx/bszs/bszyml/2026/yx/zsml_bs_yx.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1303	6	北京大学	北京大学2026年博士研究生招生专业目录(校本部、按专业)	目录	2025-10-10	https://admission.pku.edu.cn/zsxx/bszs/bszyml/2026/zy/yjszszy_bs.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1304	6	北京大学	北京大学2026年博士研究生招生专业目录(港澳台)	目录	2025-11-06	https://admission.pku.edu.cn/zsxx/gatzs/gatzyml/2026/bs/zsml_bs_got.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1305	6	北京大学	北京大学2026年硕士研究生招生专业目录(港澳台)	目录	2025-11-06	https://admission.pku.edu.cn/zsxx/gatzs/gatzyml/2026/ss/zsml_ss_got.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1306	6	北京大学	下载：港、澳、台人士申请攻读北京大学硕士/博士学位研究生专家推荐信	公告	2020-09-21	https://admission.pku.edu.cn/docs/20200921114252482211.doc	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1307	6	北京大学	北京大学2026年博士研究生招生专业目录(校本部,留学生,English-taught)	目录	2025-10-20	https://admission.pku.edu.cn/zsxx/lxszs/lxszyml/2026/bs/zsml_bs_lxs_en.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1704	563	湖南大学	湖南大学2027年硕士研究生考试大纲	大纲	2026-10-05	https://gra.hnu.edu.cn/info/1075/10612.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1308	6	北京大学	北京大学2026年硕士研究生招生专业目录(校本部,留学生,中文授课)	目录	2025-10-20	https://admission.pku.edu.cn/zsxx/lxszs/lxszyml/2026/ss/zsml_ss_lxs_cn.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1309	6	北京大学	北京大学2026年硕士研究生招生专业目录(校本部,留学生,English-taught)	目录	2025-10-20	https://admission.pku.edu.cn/zsxx/lxszs/lxszyml/2026/ss/zsml_ss_lxs_en.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1310	6	北京大学	北京大学2026年博士研究生招生专业目录(校本部,留学生,中文授课)	目录	2025-10-20	https://admission.pku.edu.cn/zsxx/lxszs/lxszyml/2026/bs/zsml_bs_lxs_cn.html	admission.pku.edu.cn	2026-10-19T02:09:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:32.990779+08
1317	275	上海交通大学	博士生招生	公告	\N	https://yzb.sjtu.edu.cn/zsjz/bsszs	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1318	275	上海交通大学	硕士生招生	公告	\N	https://yzb.sjtu.edu.cn/zsjz/sszs	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1319	275	上海交通大学	预推免报名	报名	\N	http://ga.sjtu.edu.cn/zsgl/ytmgl/	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1320	275	上海交通大学	夏令营公示	录取	\N	https://yzb.sjtu.edu.cn/xxgs/xlygs	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1321	275	上海交通大学	预推免公示	录取	\N	https://yzb.sjtu.edu.cn/xxgs/ytmgs	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1322	275	上海交通大学	预推免考生登录	公告	\N	http://ga.sjtu.edu.cn/zsgl/ytmgl	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1323	275	上海交通大学	硕士考生登录	公告	\N	http://ga.sjtu.edu.cn/ksxt/login.aspx	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1324	275	上海交通大学	上海交通大学2027年“医工交叉平台”博士研究生招生简章	简章	2026-09-06	https://yzb.sjtu.edu.cn/post/3766	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1325	275	上海交通大学	关于2026年秋季博士研究生录取通知书发放及学号查询的通知	录取	2026-07-23	https://yzb.sjtu.edu.cn/post/3755	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1326	275	上海交通大学	上海交通大学2027级“明志荣誉博士生”招生简章	简章	2026-07-09	https://yzb.sjtu.edu.cn/post/3744	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1327	275	上海交通大学	上海交通大学2027年全日制硕士研究生统考分专业招生计划表（校本部）	公告	2026-10-15	https://yzb.sjtu.edu.cn/post/3808	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1328	275	上海交通大学	上海交通大学 2027年全国硕士研究生招生考试网报公告	公告	2026-10-09	https://yzb.sjtu.edu.cn/post/3797	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1329	275	上海交通大学	上海交通大学2027年硕士研究生招生章程	公告	2026-10-08	https://yzb.sjtu.edu.cn/post/3784	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1330	275	上海交通大学	2027年全国硕士研究生招生考试上海交通大学考点网报公告 （考点代码3105）	公告	2026-10-08	https://yzb.sjtu.edu.cn/post/3795	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1331	275	上海交通大学	关于2026年港澳台研究生录取通知书发放的通知	录取	2026-07-23	https://yzb.sjtu.edu.cn/post/3756	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1332	275	上海交通大学	关于2026年面向港澳台地区研究生录取通知书邮寄地址确认及有关事项的通知	录取	2026-06-26	https://yzb.sjtu.edu.cn/post/3712	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1333	275	上海交通大学	上海交通大学2026年面向港澳台地区研究生招生考试初试成绩查询通知	初试	2026-04-27	https://yzb.sjtu.edu.cn/post/3555	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1334	275	上海交通大学	2026年全国硕士研究生招生考试上海交通大学考点公告	公告	2025-12-15	https://yzb.sjtu.edu.cn/post/3450	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1335	275	上海交通大学	上海交通大学2026年硕士研究生招生考试(初试)自命题科目答题纸条形码粘贴说明	初试	2025-12-13	https://yzb.sjtu.edu.cn/post/3449	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1336	275	上海交通大学	沪2026年全国硕士研究生招生考试（初试）将于12月20日-21日进行，考前提醒请查收！	初试	2025-12-09	https://yzb.sjtu.edu.cn/post/3436	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1337	275	上海交通大学	2026年全国硕士研究生招生考试上海交通大学报考点 网上确认公告（报考点代码：3105）	公告	2025-10-28	https://yzb.sjtu.edu.cn/post/3350	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1338	275	上海交通大学	研考｜上海市2026年全国硕士研究生招生考试报名确认安排及注意事项	报名	2025-10-11	https://yzb.sjtu.edu.cn/post/3331	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1339	275	上海交通大学	普通高等学校招生违规行为处理暂行办法	公告	2017-10-09	https://yzb.sjtu.edu.cn/post/489	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1340	275	上海交通大学	考研作弊已入刑	公告	2017-10-09	https://yzb.sjtu.edu.cn/post/490	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1341	275	上海交通大学	关于上海市2023年全国硕士研究生招生考试部分考生考试地点调整等相关事项的通知	公告	2022-11-30	https://yzb.sjtu.edu.cn/#	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1342	275	上海交通大学	上海交通大学国家电投智慧能源创新学院2026级研究生优才夏令营报名通知	报名	2025-06-27	https://yzb.sjtu.edu.cn/post/3224	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1343	275	上海交通大学	上海交通大学电气工程学院 2026级研究生优才夏令营活动通知	公告	2025-06-26	https://yzb.sjtu.edu.cn/post/3223	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1344	275	上海交通大学	上海交通大学计算机学院2026级优才夏令营活动通知	公告	2025-06-26	https://yzb.sjtu.edu.cn/post/3221	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1345	275	上海交通大学	交大安泰|2026年优才夏令营报名通知	报名	2025-06-26	https://yzb.sjtu.edu.cn/post/3219	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1346	275	上海交通大学	上海交通大学人工智能学院2026年优秀大学生夏令营报名通知	报名	2025-06-26	https://yzb.sjtu.edu.cn/post/3218	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1705	563	湖南大学	湖南大学2027年硕士研究生招生专业目录	目录	2026-10-05	https://gra.hnu.edu.cn/info/1075/10620.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1347	275	上海交通大学	火热报名中！ | 上海交通大学农业与生物学院2026级“优才夏令营” 报名通知	报名	2025-06-26	https://yzb.sjtu.edu.cn/post/3217	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1348	275	上海交通大学	欢迎报考 | 上海交通大学设计学院2026年研究生“优才夏令营”方案	公告	2025-06-26	https://yzb.sjtu.edu.cn/post/3216	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1349	275	上海交通大学	2025年上海交通大学体育系暑期学校招生选拔活动公告	公告	2025-06-26	https://yzb.sjtu.edu.cn/post/3215	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1350	275	上海交通大学	上海交通大学心理学、应用心理专业2026年全国优秀大学生招生夏令营报名通知	报名	2025-06-26	https://yzb.sjtu.edu.cn/post/3214	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1351	275	上海交通大学	上海交通大学凯原法学院第十五届“卓越法律人夏令营”招生简章	简章	2025-06-26	https://yzb.sjtu.edu.cn/post/3213	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1355	275	上海交通大学	上海交通大学安泰金融硕士项目宣传册（2025） 05.22/2024	公告	\N	https://yzb.sjtu.edu.cn/post/2562	yzb.sjtu.edu.cn	2026-10-19T02:09:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:09:45.472957+08
1373	317	南京大学	研究生系统管理平台	公告	2021-08-05	https://ehallapp.nju.edu.cn/gsapp1/sys/yjsemaphome/portal/index.do	grawww.nju.edu.cn	2026-10-19T02:10:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:00.685983+08
1374	317	南京大学	博士生招生网上报名系统	报名	2015-03-09	https://gs.nju.edu.cn/geapp/sys/yjsbmxsd/entrance.do	grawww.nju.edu.cn	2026-10-19T02:10:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:00.685983+08
1375	317	南京大学	接收推荐免试研究生报名系统	报名	2015-03-09	https://gs.nju.edu.cn/geapp/sys/yjsbmxsd/entrance.do	grawww.nju.edu.cn	2026-10-19T02:10:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:00.685983+08
1378	245	哈尔滨工业大学	招生信息 Admission	公告	\N	https://yzb.hit.edu.cn/zsxx/list.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1379	245	哈尔滨工业大学	招生简章 Brochure	简章	\N	https://yzb.hit.edu.cn/zsjz/list.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1380	245	哈尔滨工业大学	硕士招生简章	简章	\N	https://yzb.hit.edu.cn/22281/list.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1381	245	哈尔滨工业大学	博士招生简章	简章	\N	https://yzb.hit.edu.cn/22282/list.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1382	245	哈尔滨工业大学	联培专项招生 JOINT TRAINING	公告	\N	https://yzb.hit.edu.cn/lpzxzs/list.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1383	245	哈尔滨工业大学	宣传目录 Promotion	目录	\N	http://yzb.hit.edu.cn/22288/list.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1384	245	哈尔滨工业大学	招生宣传片	公告	\N	https://yzb.hit.edu.cn/22288/list.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1385	245	哈尔滨工业大学	招生宣传活动	公告	\N	https://yzb.hit.edu.cn/22289/list.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1386	245	哈尔滨工业大学	哈工大研究生招生中英文网站正式焕新上线	公告	\N	https://mp.weixin.qq.com/s/2fDevCgRkR6b4GiqZMAkSg	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1387	245	哈尔滨工业大学	研究生招生校园开放日	公告	\N	https://mp.weixin.qq.com/s/sfKv1db6lXAbN7lAa8c_LQ	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1388	245	哈尔滨工业大学	硕士通知书邮寄地址采集	公告	\N	http://hityzb.hit.edu.cn/zhxy-yjs-zs_v2/tzs/xxtx	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1389	245	哈尔滨工业大学	推免生信息采集系统	公告	\N	http://hityzb.hit.edu.cn/zhxy-yjs-zs_v2/common/login?redirectUrl=/pc/tms/index	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1390	245	哈尔滨工业大学	关于2027年全国推免服务系统接收推免生相关工作的提醒 2026-09-20	公告	2026-09-20	https://yzb.hit.edu.cn/2026/0920/c22276a401841/page.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1391	245	哈尔滨工业大学	哈尔滨工业大学2027年全国硕士研究生招生考试网上报名公告 2026-10-08	报名	2026-10-08	https://yzb.hit.edu.cn/2026/1008/c22276a402442/page.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1392	245	哈尔滨工业大学	关于我校2027年硕士研究生招生考试强军计划考生考试科目调整的公告 2026-08-25	公告	2026-08-25	https://yzb.hit.edu.cn/2026/0825/c22276a400058/page.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1393	245	哈尔滨工业大学	关于哈尔滨工业大学博士研究生招生优秀生源快响行动的通知 2025-06-25	公告	2025-06-25	https://yzb.hit.edu.cn/2025/0624/c22278a392860/page.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1394	245	哈尔滨工业大学	关于延长我校2027年秋季博士招生报名时间的通知 2026-09-23	报名	2026-09-23	https://yzb.hit.edu.cn/2026/0923/c22278a401971/page.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1395	245	哈尔滨工业大学	哈尔滨工业大学 2027年 “硕博连读”秋季博士招生的工作通知 2026-09-08	公告	2026-09-08	https://yzb.hit.edu.cn/2026/0908/c22278a401203/page.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1406	245	哈尔滨工业大学	直播预告 - 2026研究生招生线上宣讲会（5月20日 - 5月28日）	公告	\N	https://yzb.hit.edu.cn/2026/0526/c22289a393138/page.htm	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1413	245	哈尔滨工业大学	逐梦哈工大，研途启新程｜6月12日哈工大研究生招生校园开放日精彩瞬间 查看招生简章	简章	\N	https://mp.weixin.qq.com/s/dsXuJkkOWd9OueOJ9jYIRw	yzb.hit.edu.cn	2026-10-19T02:10:15	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:15.002288+08
1414	732	西安交通大学	2027年全国硕士研究生招生考试西安交通大学（学校代码:10698）网报公告	公告	\N	https://yz.xjtu.edu.cn/info/1082/4420.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1415	732	西安交通大学	2027年全国硕士研究生招生考试西安交通大学（学校代码:10698）网报公告	公告	2026-10-08	https://yz.xjtu.edu.cn/info/1082/4420.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1416	732	西安交通大学	2027年全国硕士研究生招生考试西安交通大学考点（考点代码6111）网报公告	公告	2026-10-08	https://yz.xjtu.edu.cn/info/1082/4419.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1417	732	西安交通大学	西安交通大学2027年“工程硕博士培养改革专项试点” 研究生（全日制）招生简章	简章	2026-09-07	https://yz.xjtu.edu.cn/info/1082/4396.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1418	732	西安交通大学	2027年西安交通大学（10698）研究生招生网报公告三	公告	2026-10-14	https://yz.xjtu.edu.cn/info/1082/4422.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1419	732	西安交通大学	西安交通大学与苏州国家实验室2027年联合培养博士生专项计划招生简章（直博项目）	简章	2026-09-14	https://yz.xjtu.edu.cn/info/1082/4404.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1420	732	西安交通大学	西安交通大学2027年硕士研究生招生章程	公告	\N	https://yz.xjtu.edu.cn/info/1083/4418.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1421	732	西安交通大学	2027年西安交通大学（10698）研究生招生网报公告三	公告	\N	https://yz.xjtu.edu.cn/info/1083/4423.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1422	732	西安交通大学	2027年全国硕士研究生招生考试西安交通大学（学校...	公告	\N	https://yz.xjtu.edu.cn/info/1083/4415.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1423	732	西安交通大学	2027年全国硕士研究生招生考试西安交通大学考点（...	公告	\N	https://yz.xjtu.edu.cn/info/1083/4417.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1424	732	西安交通大学	历年复试线	复试	\N	https://yz.xjtu.edu.cn/index/lnfsx.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1425	732	西安交通大学	西安交通大学2026年博士研究生招生报名	报名	2025-11-03	https://yzbm.xjtu.edu.cn/logon	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1426	732	西安交通大学	西安交通大学2026年博士研究生招生章程	公告	2025-10-17	https://yz.xjtu.edu.cn/info/1084/4285.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1427	732	西安交通大学	西安交通大学2026年博士研究生招生目录	目录	2025-11-03	https://yzbm.xjtu.edu.cn/zsml/bszsml/detailtk/bfo8@yEtRpW1EyxsEKg7eQ==	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1428	732	西安交通大学	西安交通大学2026年思政专项博士综合面试通知（第二批）	公告	2026-07-09	https://yz.xjtu.edu.cn/info/1084/4371.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1429	732	西安交通大学	西安交通大学2027年硕士研究生招生章程	公告	2026-09-30	https://yz.xjtu.edu.cn/info/1085/4408.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1430	732	西安交通大学	西安交通大学2027年硕士研究生招生专业目录(普通招考)	目录	2026-10-08	https://yzbm.xjtu.edu.cn/zsml/sszsml/detailtk/Ppu8Tbrbt8BWT%207TDfLD@g==	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1431	732	西安交通大学	西安交通大学2027年硕士研究生招生考试初试自命题科目考...	初试	2026-10-08	https://yzbm.xjtu.edu.cn/sskmcx/indexjl1M2NcR5toY4p/Ppu8Tbrbt8BWT%207TDfLD@g==	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1432	732	西安交通大学	2027年全国硕士研究生招生考试西安交通大学考点（考点代...	公告	2026-10-08	https://yz.xjtu.edu.cn/info/1085/4414.htm	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1433	732	西安交通大学	西安交通大学2027年推荐免试研究生招生专业目录（博士）	目录	2026-09-21	https://yzbm.xjtu.edu.cn/zsml/bszsml/detailtm/Ppu8Tbrbt8BWT%207TDfLD@g==	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1434	732	西安交通大学	西安交通大学2027年推荐免试研究生招生专业目录（硕士）	目录	2026-09-21	https://yzbm.xjtu.edu.cn/zsml/sszsml/detailtm/Ppu8Tbrbt8BWT%207TDfLD@g==	yz.xjtu.edu.cn	2026-10-19T02:10:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:10:21.832127+08
1437	517	华中科技大学	学位授权点目录	目录	\N	https://gs.hust.edu.cn/pygz/zbjs111/xwsqdml.htm	gs.hust.edu.cn	2026-10-19T02:11:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:00.26678+08
1438	517	华中科技大学	关于2027年毕业研究生学历相片采集的通知	公告	2026-10-12	https://gs.hust.edu.cn/info/1043/6836.htm	gs.hust.edu.cn	2026-10-19T02:11:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:00.26678+08
1457	319	东南大学	东南大学2027年硕士研究生考试招生专业目录及参考书目	目录	2026-10-09	https://gsas.seu.edu.cn/ssmlcx2027/pages/index.html	yzb.seu.edu.cn	2026-10-19T02:11:06	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:06.7682+08
1458	319	东南大学	东南大学2027年硕士研究生招生考试东南大学报考点【3202】 网上报名公告	报名	2026-10-08	http://yzb.seu.edu.cn/2026/1008/c6676a585159/page.htm	yzb.seu.edu.cn	2026-10-19T02:11:06	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:06.7682+08
1459	319	东南大学	东南大学2027年硕士研究生招生章程	公告	2026-10-08	http://yzb.seu.edu.cn/2026/1008/c6676a585158/page.htm	yzb.seu.edu.cn	2026-10-19T02:11:06	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:06.7682+08
1460	319	东南大学	2026年东南大学各院系所复试分数线	复试	2026-09-28	http://yzb.seu.edu.cn/2026/0928/c6674a584558/page.htm	yzb.seu.edu.cn	2026-10-19T02:11:06	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:06.7682+08
1461	319	东南大学	东南大学2027年度国优计划研究生专项面试结果	公告	2026-09-10	http://yzb.seu.edu.cn/2026/0910/c6676a582699/page.htm	yzb.seu.edu.cn	2026-10-19T02:11:06	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:06.7682+08
1462	319	东南大学	东南⼤学2027年度国优计划研究⽣专项科学与技术教育(045117)⾯试结果	公告	2026-09-10	http://yzb.seu.edu.cn/2026/0910/c6689a582711/page.htm	yzb.seu.edu.cn	2026-10-19T02:11:06	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:06.7682+08
1463	319	东南大学	东南大学2027年度国优计划研究生专项学科教学（物理）(045105)面试结果	公告	2026-09-10	http://yzb.seu.edu.cn/2026/0910/c6689a582710/page.htm	yzb.seu.edu.cn	2026-10-19T02:11:06	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:06.7682+08
1464	319	东南大学	东南大学2027年度国优计划研究生专项选拔考核通知	公告	2026-09-07	http://yzb.seu.edu.cn/2026/0907/c6676a582190/page.htm	yzb.seu.edu.cn	2026-10-19T02:11:06	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:06.7682+08
1465	319	东南大学	东南大学各院、系（所）2027年接收推荐免试研究生报名通知汇总	报名	2026-07-07	http://yzb.seu.edu.cn/2026/0707/c6676a575749/page.htm	yzb.seu.edu.cn	2026-10-19T02:11:06	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:06.7682+08
1466	319	东南大学	东南大学2026年硕士研究生录取通知书寄发公告	录取	2026-07-01	http://yzb.seu.edu.cn/2026/0701/c6676a575169/page.htm	yzb.seu.edu.cn	2026-10-19T02:11:06	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:06.7682+08
1467	10	北京航空航天大学	[置顶] 北京航空航天大学关于研究生招生工作的郑重声明	公告	2026-07-31	https://yzb.buaa.edu.cn/info/1036/1308.htm	yzb.buaa.edu.cn	2026-10-19T02:11:14	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:14.641382+08
1468	10	北京航空航天大学	[置顶] 关于招收2027年硕士研究生初试科目的公告（2026年7月31日更新）	初试	2026-07-31	https://yzb.buaa.edu.cn/info/1036/3566.htm	yzb.buaa.edu.cn	2026-10-19T02:11:14	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:14.641382+08
1469	10	北京航空航天大学	关于10月14日温馨提示的学籍学历校验补充通知（2026年10月16日）	公告	2026-10-14	https://yzb.buaa.edu.cn/info/1036/3652.htm	yzb.buaa.edu.cn	2026-10-19T02:11:14	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:14.641382+08
1470	10	北京航空航天大学	北航报考点2026年10月14日温馨提示	公告	2026-10-14	https://yzb.buaa.edu.cn/info/1036/3643.htm	yzb.buaa.edu.cn	2026-10-19T02:11:14	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:14.641382+08
1471	10	北京航空航天大学	报考北航2027年硕士研究生温馨提示（10月14日）	公告	2026-10-16	https://yzb.buaa.edu.cn/info/1036/3641.htm	yzb.buaa.edu.cn	2026-10-19T02:11:14	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:14.641382+08
1472	10	北京航空航天大学	北航报考点（报考点代码：1106）招收2027年学历硕士研究生网上报名公告	报名	2026-10-14	https://yzb.buaa.edu.cn/info/1036/3636.htm	yzb.buaa.edu.cn	2026-10-19T02:11:14	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:14.641382+08
1473	11	北京理工大学	2027-2028学年香港理工大学联合培养博士双学位项目申报通知	公告	\N	https://grd.bit.edu.cn/gjjl/xnlhpyxm/tzgg_xn/ebfdee92f6794d14b1ca292fac712d26.htm	grd.bit.edu.cn	2026-10-19T02:11:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:20.735278+08
1474	11	北京理工大学	【国际交流】2027年寒假世界名校交流项目报名通知	报名	\N	https://grd.bit.edu.cn/gjjl/xnlhpyxm/tzgg_xn/32b158c51e3749fcae5db39813957ca6.htm	grd.bit.edu.cn	2026-10-19T02:11:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:20.735278+08
1475	11	北京理工大学	关于2026年冬季研究生学位论文评阅、学位答辩及申请相关工作的通知	公告	\N	https://grd.bit.edu.cn/xwgz/xwgz2/tzgg_xwgz/09c0299e542749618dfc5320bb63764a.htm	grd.bit.edu.cn	2026-10-19T02:11:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:20.735278+08
1476	11	北京理工大学	关于评定2026年研究生学业奖学金的通知	公告	\N	https://grd.bit.edu.cn/tzgg1/b17a4945f04c4c51afade79d026aa79b.htm	grd.bit.edu.cn	2026-10-19T02:11:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:20.735278+08
1477	11	北京理工大学	硕士学位论文盲评系统	公告	\N	http://pyxt.bit.edu.cn/	grd.bit.edu.cn	2026-10-19T02:11:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:20.735278+08
1478	274	同济大学	同济大学研究生报考服务系统-考生入口	公告	2015-07-14	https://yzbm.tongji.edu.cn/	yz.tongji.edu.cn	2026-10-19T02:11:26	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:26.78392+08
1479	274	同济大学	同济大学研究生招生管理平台-管理员入口	公告	\N	https://yzgl.tongji.edu.cn/	yz.tongji.edu.cn	2026-10-19T02:11:26	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:26.78392+08
1480	274	同济大学	同济大学关于2027年教育部推免服务系统报...	公告	2026-09-21	https://yz.tongji.edu.cn/info/1010/4232.htm	yz.tongji.edu.cn	2026-10-19T02:11:26	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:26.78392+08
1481	274	同济大学	2027年全国硕士研究生招生考试同济大学报考...	公告	2026-10-08	https://yz.tongji.edu.cn/info/1012/4246.htm	yz.tongji.edu.cn	2026-10-19T02:11:26	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:26.78392+08
1482	274	同济大学	同济大学2027年硕士研究生招生考试部分科目...	公告	2026-09-30	https://yz.tongji.edu.cn/info/1012/4241.htm	yz.tongji.edu.cn	2026-10-19T02:11:26	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:26.78392+08
1483	274	同济大学	同济大学2027年硕士研究生招生专业目录（按...	目录	2026-09-30	https://yz.tongji.edu.cn/info/1012/4240.htm	yz.tongji.edu.cn	2026-10-19T02:11:26	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:26.78392+08
1484	274	同济大学	（10月18日更新）同济大学关于2027年报考我...	公告	2026-10-18	https://yz.tongji.edu.cn/info/1012/4259.htm	yz.tongji.edu.cn	2026-10-19T02:11:26	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:26.78392+08
1504	108	天津大学	留学生招生	公告	\N	https://yzb.tju.edu.cn/./zszn/lxszs/	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1505	108	天津大学	2027级推免硕士...	公告	\N	https://sszs.tju.edu.cn/10056/main/user/enrollbook	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1506	108	天津大学	硕士生招生管理系统	公告	\N	https://sszs.tju.edu.cn/10056/user/login/login	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1507	108	天津大学	天津大学关于研究生招生工作的郑重声明	公告	2023-10-09	https://yzb.tju.edu.cn/./xwzx/zxxx/202310/t20231009_323410.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1508	108	天津大学	天津大学2027年推荐优秀应届本科毕业生免试攻读硕士学位和直接攻读...	公告	2026-09-08	https://yzb.tju.edu.cn/./xwzx/zxxx/202609/t20260908_324696.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1509	108	天津大学	天津大学2027年各学院推荐免试攻读研究生招生录取办法汇总	录取	2026-09-14	https://yzb.tju.edu.cn/./xwzx/zxxx/202609/t20260914_324699.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1510	108	天津大学	天津大学2027年“工程硕博士培养改革专项”研究生招生简章	简章	2026-09-01	https://yzb.tju.edu.cn/./xwzx/zxxx/202609/t20260901_324692.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1511	108	天津大学	【申请通道已开通】天津大学利物浦福州联合学院硕士项目招生简章	简章	2026-03-03	https://yzb.tju.edu.cn/./xwzx/zxxx/202603/t20260303_324561.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1512	108	天津大学	关于天津大学2026年部分硕士研究生复试退费安排的通知	复试	2026-04-30	https://yzb.tju.edu.cn/./xwzx/zxxx/202604/t20260430_324631.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1513	108	天津大学	2026级研究生新生入学报到通知	公告	2026-04-30	https://yzb.tju.edu.cn/./xwzx/zxxx/202604/t20260430_324630.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1514	108	天津大学	【申请通道已开通】天津大学利物浦福州联合学院 2027年硕士项目招...	公告	2026-10-14	https://yzb.tju.edu.cn/./xwzx/zxxx/202610/t20261014_324753.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1515	108	天津大学	【专项计划】天津大学医疗机器人与智能系统研究院2025年博士、硕士...	公告	2024-11-27	https://yzb.tju.edu.cn/./xwzx/tkbs_xw/202411/t20241127_324038.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1516	108	天津大学	关于开展2026级科创硕士研究生统招招生工作的通知	公告	2026-03-23	https://yzb.tju.edu.cn/./xwzx/tztg/202603/t20260323_324574.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1517	108	天津大学	关于开展2025年科创硕士研究生统招招生工作的通知	公告	2025-03-19	https://yzb.tju.edu.cn/./xwzx/tztg/202503/t20250319_324164.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1518	108	天津大学	天津大学宣怀学院2025级科创硕士夏令营活动通知	公告	2024-06-07	https://yzb.tju.edu.cn/./xwzx/tztg/202406/t20240607_323819.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1519	108	天津大学	天津大学表层地球系统科学研究院2019年硕士研究生调剂复试安排及名单	复试	2019-03-22	https://yzb.tju.edu.cn/./xwzx/tztg/201903/t20190322_312261.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1520	108	天津大学	天津大学医学工程与转化医学研究院2019级研究生招生夏令营活动通知	公告	2018-05-18	https://yzb.tju.edu.cn/./xwzx/tztg/201805/t20180518_306777.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1521	108	天津大学	天津大学马克思主义学院2018年校内调剂拟录取名单公示	调剂	2018-04-04	https://yzb.tju.edu.cn/./xwzx/tztg/201804/t20180404_304918.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1522	108	天津大学	天津大学马克思主义学院2018年全日制硕士研究生招生校内调剂复试安...	复试	2018-03-27	https://yzb.tju.edu.cn/./xwzx/tztg/201803/t20180327_304623.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1523	108	天津大学	天津大学马克思学院2018年硕士研究生拟录取名单公示（第二批）	录取	2018-03-24	https://yzb.tju.edu.cn/./xwzx/tztg/201803/t20180324_304542.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1524	108	天津大学	天津大学医工院2018年硕士研究生调剂复试成绩及拟录取名单公示（第...	复试	2018-03-24	https://yzb.tju.edu.cn/./xwzx/tztg/201803/t20180324_304539.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1525	108	天津大学	关于有研究生学籍考生及以同等学力报名考生提供证明材料的通知	报名	2026-10-10	https://yzb.tju.edu.cn/./xwzx/tkss_xw/202610/t20261010_324751.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1526	108	天津大学	天津大学2027年少数民族高层次骨干人才计划硕士学位研究生报考注意...	公告	2026-10-08	https://yzb.tju.edu.cn/./xwzx/tkss_xw/202610/t20261008_324748.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1527	108	天津大学	天津大学2027年退役大学生士兵计划硕士学位研究生报考注意事项	公告	2026-10-09	https://yzb.tju.edu.cn/./xwzx/tkss_xw/202610/t20261009_324750.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1528	108	天津大学	天津大学2027年部分考生需提供学历或学籍认证报告等材料的通知	公告	2026-10-09	https://yzb.tju.edu.cn/./xwzx/tkss_xw/202610/t20261009_324749.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1529	108	天津大学	天津市2027年全国硕士研究生招生考试天津大学报考点（代码 1232 ）...	公告	2026-10-08	https://yzb.tju.edu.cn/./xwzx/tkss_xw/202610/t20261008_324745.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1530	108	天津大学	天津大学2027年硕士学位研究生招生简章	简章	2026-10-07	https://yzb.tju.edu.cn/./xwzx/tkss_xw/202610/t20261007_324742.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1531	108	天津大学	天津大学2027年硕士学位研究生招生专业目录及初试考试自命题科目大纲	大纲	2026-10-08	https://yzb.tju.edu.cn/./xwzx/tkss_xw/202610/t20261008_324746.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1532	108	天津大学	天津大学2027年各学院推荐免试攻读硕士学位研究生复试成绩及拟录取...	复试	2026-09-28	https://yzb.tju.edu.cn/./xwzx/tkss_xw/202609/t20260928_324726.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1533	108	天津大学	关于调整我校2027年硕士研究生招生单独考试相关专业初试科目的通知	初试	2026-07-14	https://yzb.tju.edu.cn/./xwzx/tkss_xw/202607/t20260714_324677.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1534	108	天津大学	天津大学2027年博士研究生招生简章	简章	2026-10-08	https://yzb.tju.edu.cn/./xwzx/tkbs_xw/202610/t20261008_324747.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1535	108	天津大学	天津大学关于开展2027年硕博连读研究生选拔的通知	公告	2026-10-12	https://yzb.tju.edu.cn/./xwzx/tkbs_xw/202610/t20261012_324752.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1536	108	天津大学	【2027推免生接收篇】天津大学2027年直博生报名系统开通	报名	2026-09-01	https://yzb.tju.edu.cn/./xwzx/tkbs_xw/202609/t20260901_324691.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1537	108	天津大学	天津大学2026年博士研究生新生入学报到相关事宜通知	公告	2026-06-25	https://yzb.tju.edu.cn/./xwzx/tkbs_xw/202606/t20260625_324668.htm	yzb.tju.edu.cn	2026-10-19T02:11:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:35.435494+08
1554	185	大连理工大学	2021年各学部（学院）硕士研究生复试录取办法公示	复试	\N	http://gs.dlut.edu.cn/info/1173/11367.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1555	185	大连理工大学	大连理工大学2027年“国优计划”专项招生选拔通知	公告	\N	https://gs.dlut.edu.cn/info/1173/51622.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1556	185	大连理工大学	关于2026年硕士研究生学位论文答辩及相关工作安排	公告	\N	https://gs.dlut.edu.cn/info/1206/48652.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1557	185	大连理工大学	关于新增研究生招生专业学费的说明	公告	\N	https://gs.dlut.edu.cn/info/1173/52032.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1558	185	大连理工大学	2026博士学位论文单项\\特别奖学金评选结果公示	录取	\N	https://gs.dlut.edu.cn/info/1206/51992.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1559	185	大连理工大学	关于2027年集成电路学院硕士研究生招生考试参考书目的公告	公告	\N	http://ic.dlut.edu.cn/info/1034/11768.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1560	185	大连理工大学	关于2027届研究生毕业生图像采集报名的通知	报名	\N	https://gs.dlut.edu.cn/info/1089/51902.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1561	185	大连理工大学	关于2026级研究生新生课程免修的补充通知	公告	\N	https://gs.dlut.edu.cn/info/1089/51692.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1562	185	大连理工大学	关于开展2026年优秀博士论文特别奖学金评选工作的通知	公告	\N	https://gs.dlut.edu.cn/info/1206/51652.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1563	185	大连理工大学	关于开展2026年优秀博士论文单项奖学金评选工作的通知	公告	\N	https://gs.dlut.edu.cn/info/1206/51642.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1564	185	大连理工大学	我校各学部（学院）2027年接收推荐免试攻读硕士（博士）学位...	公告	\N	https://gs.dlut.edu.cn/info/1173/51682.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1565	185	大连理工大学	大连理工大学2027年秋季批次硕博连读预报名通知（更新）	报名	\N	https://gs.dlut.edu.cn/info/1173/51602.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1566	185	大连理工大学	关于发放大连理工大学2026年研究生录取通知书的通知	录取	\N	https://gs.dlut.edu.cn/info/1173/51482.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1567	185	大连理工大学	关于2025年基础学科导师创新基金评审结果公示	录取	\N	https://gs.dlut.edu.cn/info/1004/17026.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1568	185	大连理工大学	关于召开2025年首聘研究生导师培训会的通知	公告	\N	https://portal.dlut.edu.cn/tp/index.html#act=sems-tp-nup_28585749&contentid=&ownerid=&website=0&pim_id=11857642000556032	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1569	185	大连理工大学	关于申报2025年研究生导师创新基金的通知	公告	\N	https://gs.dlut.edu.cn/info/1004/16936.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1570	185	大连理工大学	关于开展2025年“1+X学科交叉导师团队” 专项申报工作的通知	公告	\N	https://gs.dlut.edu.cn/info/1004/16256.htm	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1574	185	大连理工大学	博士答辩公告	公告	\N	https://dutgs.dlut.edu.cn/gmis/xw/dbgggs.aspx	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1575	185	大连理工大学	硕士答辩公告	公告	\N	https://dutgs.dlut.edu.cn/gmis/xw/dbggssgs.aspx	gs.dlut.edu.cn	2026-10-19T02:11:44	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:44.209408+08
1579	224	吉林大学	吉林大学招生网	公告	\N	http://zsb.jlu.edu.cn/	yjsy.jlu.edu.cn	2026-10-19T02:11:52	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:11:52.80147+08
1580	592	华南理工大学	华南理工大学2027年全国硕士研究生招生考试网报公告	公告	2026-10-08	http://yz.scut.edu.cn/2026/1008/c30111a636991/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1581	592	华南理工大学	关于公布各院（系）2027年研究生招生预推免接收工作复试方案的通知	复试	2026-09-14	http://yz.scut.edu.cn/2026/0913/c30111a635170/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1582	592	华南理工大学	华南理工大学与英国卡迪夫大学联合培养双硕士学位项目2027年招生简章	简章	2026-09-11	http://yz.scut.edu.cn/2026/0911/c30384a635057/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1583	592	华南理工大学	华南理工大学与法国南特大学联合培养双硕士学位项目2027年招生简章	简章	2026-09-11	http://yz.scut.edu.cn/2026/0911/c30384a635058/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1584	592	华南理工大学	华南理工大学接收2027年推荐免试研究生预报名通知	报名	2026-08-28	http://yz.scut.edu.cn/2026/0828/c30111a633884/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1585	592	华南理工大学	关于催促2026年部分拟录取博士研究生提交档案等材料的通知	录取	2026-07-22	http://yz.scut.edu.cn/2026/0722/c30112a632900/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1586	592	华南理工大学	关于2026年拟录取博士研究生调档函、现实表现复审表、定向就业协议书、组织关系、户口迁移、录取通知书地址校对等事宜的通知	录取	2026-06-26	http://yz.scut.edu.cn/2026/0626/c30112a630893/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1587	592	华南理工大学	关于华南理工大学2026年博士研究生拟录取名单的公示	录取	2026-06-26	http://yz.scut.edu.cn/2026/0625/c30112a630866/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1588	592	华南理工大学	2026年攻读博士学位研究生第二次招生院系复试录取方案	复试	2026-05-21	https://yanzhao.scut.edu.cn/Doctor/FsfaEc.aspx	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1589	592	华南理工大学	华南理工大学2026年面向香港、澳门、台湾地区招收研究生院系复试录取方案	复试	2026-05-12	https://yanzhao.scut.edu.cn/MasterGat/Fsfa.aspx	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1590	592	华南理工大学	华南理工大学2026年“高校思想政治工作骨干在职攻读博士学位”专项计划招生简章	简章	2026-04-28	http://yz.scut.edu.cn/2026/0428/c30384a625797/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1591	592	华南理工大学	华南理工大学2026年攻读博士学位研究生第二次招生通知	公告	2026-04-28	http://yz.scut.edu.cn/2026/0425/c30108a625528/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1592	592	华南理工大学	关于公布华南理工大学2026年“少数民族高层次骨干人才计划”硕士研究生递补复试名单的通知	复试	2026-04-15	http://yz.scut.edu.cn/2026/0415/c30111a624664/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1593	592	华南理工大学	华南理工大学2026年“技术转移”专业学位硕士研究生招生简章	简章	2026-04-03	http://yz.scut.edu.cn/2026/0402/c30111a622414/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1594	592	华南理工大学	华南理工大学2026年硕士研究生招生各院系复试录取方案	复试	2026-03-14	https://yanzhao.scut.edu.cn/open/master/Fsfa.aspx	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1595	592	华南理工大学	华南理工大学2026年硕士研究生招生复试录取办法	复试	2026-03-14	http://yz.scut.edu.cn/2026/0314/c30111a620080/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1596	592	华南理工大学	关于公布2026年“少数民族高层次骨干人才计划”博士研究生双选名单的通知	公告	2026-01-12	http://yz.scut.edu.cn/2026/0112/c30380a617231/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1597	592	华南理工大学	关于公布2026年“少数民族高层次骨干人才计划”博士研究生录取办法的通知	录取	2026-01-09	http://yz.scut.edu.cn/2026/0109/c30380a617082/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1598	592	华南理工大学	全国硕士研究生招生考试华南理工大学考点考场对应课室图	公告	2025-12-19	https://mp.weixin.qq.com/s/8nk8mArTBJtPLji_AEt3vw	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1599	592	华南理工大学	2026年硕士研究生招生考试初试华南理工大学考点考试及入场须知	初试	2025-12-19	https://mp.weixin.qq.com/s/9RT3_mtQl8_W3tNVbaMHeA	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1600	592	华南理工大学	华南理工大学硕士研究生招生考试自命题信封拆封及答题纸条形码粘贴说明	公告	2025-12-18	https://mp.weixin.qq.com/s/6-WO9uND1C--UVzPz8PMvw	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1601	592	华南理工大学	华南理工大学2026年面向香港、澳门、台湾地区招收研究生章程	公告	2025-12-16	http://yz.scut.edu.cn/2025/1215/c30383a614633/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1602	592	华南理工大学	2026年博士研究生(申请考核)各学院（系）复试方案	复试	2025-12-06	https://yanzhao.scut.edu.cn/Doctor/FsfaSqkh.aspx	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1603	592	华南理工大学	2026年博士研究生(硕博连读)各学院（系）复试方案	复试	2025-11-05	https://yanzhao.scut.edu.cn/Doctor/FsfaSbld.aspx	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1604	592	华南理工大学	华南理工大学2026年各招生院系申请考核制实施细则	公告	2025-11-03	https://yanzhao.scut.edu.cn/Doctor/SqkhfaOpen.aspx	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1605	592	华南理工大学	华南理工大学2026年博士研究生招生报考指引	公告	2025-10-24	https://mp.weixin.qq.com/s/MSNCoGErbpD73oVKs6St-A	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1606	592	华南理工大学	华南理工大学2026年博士研究生招生章程及招生专业目录	目录	2025-10-24	http://yz.scut.edu.cn/2025/1020/c30382a606073/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1607	592	华南理工大学	关于开展2026年硕博连读博士研究生选拔和招收工作的通知	公告	2025-10-24	https://www2.scut.edu.cn/graduate/2025/1022/c14562a606392/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1608	592	华南理工大学	关于公示华南理工大学2026年接收推荐免试（含强基转段）研究生名单及公布统考可用计划的通知	录取	2025-10-22	http://yz.scut.edu.cn/2025/1022/c30111a606372/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1609	592	华南理工大学	华南理工大学2026年硕士研究生招生章程及招生专业目录	目录	2025-10-11	http://yz.scut.edu.cn/2025/1009/c30381a604485/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1610	592	华南理工大学	华南理工大学2026年“少数民族高层次骨干人才计划”招收攻读硕士、博士学位研究生招生简章	简章	2025-10-11	http://yz.scut.edu.cn/2025/1011/c30384a604794/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1611	592	华南理工大学	华南理工大学报考点（考点代码4414）2026年全国硕士研究生招生考试公告	公告	2025-10-11	http://yz.scut.edu.cn/2025/1010/c30111a604640/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1612	592	华南理工大学	华南理工大学2026年全国硕士研究生招生考试网报公告	公告	2025-10-10	http://yz.scut.edu.cn/2025/1010/c30111a604635/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1613	592	华南理工大学	关于公布各院（系）2026年研究生招生预推免接收工作复试方案的通知	复试	2025-09-26	http://yz.scut.edu.cn/2025/0913/c30111a602399/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1614	592	华南理工大学	华南理工大学接收2026年推荐免试研究生预报名通知	报名	2025-09-02	http://yz.scut.edu.cn/2025/0902/c30108a600545/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1615	592	华南理工大学	关于催交部分2025年拟录取博士研究生档案等材料的通知	录取	2025-07-21	http://yz.scut.edu.cn/2025/0718/c30112a598652/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1616	592	华南理工大学	关于设计学院调整部分专业（方向）2026年初试科目的通知	初试	2025-06-30	http://yz.scut.edu.cn/2025/0630/c30111a595479/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1617	592	华南理工大学	关于外国语学院050200外国语言文学专业2026年初试自命题科目调整的通知	初试	2025-06-26	http://yz.scut.edu.cn/2025/0626/c30111a595331/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1618	592	华南理工大学	关于机械与汽车工程学院部分专业2026年初试自命题科目调整的通知	初试	2025-06-13	http://yz.scut.edu.cn/2025/0613/c30111a594057/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1619	592	华南理工大学	关于未来技术学院调整2026年硕士研究生招生专业的通知	公告	2025-06-13	http://yz.scut.edu.cn/2025/0611/c30111a593859/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1620	592	华南理工大学	关于微电子学院和集成电路学院2026年初试自命题科目调整的通知	初试	2025-06-06	http://yz.scut.edu.cn/2025/0606/c30111a593441/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1621	592	华南理工大学	共赴新鲤程	公告	2025-06-06	http://yz.scut.edu.cn/2025/0606/c30125a593413/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1622	592	华南理工大学	关于材料科学与工程学院部分专业(方向)2026年初试自命题科目调整的通知	初试	2025-06-04	http://yz.scut.edu.cn/2025/0604/c30111a593184/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1624	592	华南理工大学	关于我校部分专业2026年初试自命题科目调整的通知	初试	2025-05-15	http://yz.scut.edu.cn/2025/0515/c30111a591206/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1625	592	华南理工大学	华南理工大学2025年面向香港、澳门、台湾地区招收研究生院系复试录取方案	复试	2025-05-13	https://yanzhao.scut.edu.cn/MasterGat/Fsfa.aspx	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1626	592	华南理工大学	关于药学、国际商务两个专业暂停招收硕士研究生的通知	公告	2025-05-09	http://yz.scut.edu.cn/2025/0509/c30111a589912/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1627	592	华南理工大学	华南理工大学2025年面向香港、澳门、台湾地区招收研究生复试录取办法	复试	2025-05-09	http://yz.scut.edu.cn/2025/0509/c30113a589847/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1628	592	华南理工大学	华南理工大学2025年攻读博士学位研究生第二次招生通知	公告	2025-04-28	http://yz.scut.edu.cn/2025/0428/c30101a588292/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1629	592	华南理工大学	华南理工大学关于2025年面向香港、澳门、台湾地区招收研究生考试初试成绩查询及相关工作安排的通知	初试	2025-04-27	http://yz.scut.edu.cn/2025/0427/c30113a588174/page.htm	yz.scut.edu.cn	2026-10-19T02:12:08	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
1630	660	四川大学	夏令营&预推免	公告	\N	https://yz.scu.edu.cn/xly	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1631	660	四川大学	推免生（直博）专业目录	目录	\N	https://yz.scu.edu.cn/sszyml/tmsml	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1632	660	四川大学	港澳台硕士招生专业目录	目录	\N	https://yz.scu.edu.cn/ssgat	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1633	660	四川大学	港澳台博士招生专业目录	目录	\N	https://yz.scu.edu.cn/bsgat	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1635	660	四川大学	四川大学2027年硕士研究生网上报名公告【报考我校必读】	报名	2026-10-08	https://yz.scu.edu.cn/zsxx/Details/29e690be-7154-40d2-b361-f564d3bbb969	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1636	660	四川大学	四川大学报考点（望江校区考点5101和江安校区考点5189）2027年全国硕士研究生招生考试网上报名公告	报名	2026-10-08	https://yz.scu.edu.cn/zsxx/Details/f292b80f-a159-4d42-a784-28a5f4e10b77	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1637	660	四川大学	四川大学2027年硕士研究生招生章程	公告	2026-10-08	https://yz.scu.edu.cn/zsxx/Details/a9e04641-aa5f-401f-892e-f069c0f8ecb2	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1638	660	四川大学	四川省2027年全国硕士研究生招生考试网上报名公告	报名	2026-10-08	https://www.sceea.cn/Html/202610/Newsdetail_4975.html	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1639	660	四川大学	四川大学2027年推免生(含直博生)接收人数汇总表	公告	2026-10-08	https://yz.scu.edu.cn/tms/tmsjkgs	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1640	660	四川大学	四川大学2027年“国优计划”专项硕士研究生招生综合评审成绩公示	录取	2026-09-15	https://yz.scu.edu.cn/zsxx/Details/ebad3264-4cc9-41ba-a0f1-8733e3f465b6	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1641	660	四川大学	2027年“四川大学-南方电网”联合培养项目推荐免试研究生招生简章	简章	2026-09-10	https://yz.scu.edu.cn/zsxx/Details/1b2831ad-f372-4084-8462-3b739189cf94	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1642	660	四川大学	四川大学2027年推荐免试研究生招生章程	公告	2026-09-08	https://yz.scu.edu.cn/zsxx/Details/0f4bc2fc-e7d8-455d-b0e3-8ad680196df1	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1643	660	四川大学	四川大学2026年面向香港、澳门、台湾地区招收研究生拟录取名单公示	录取	2026-05-28	https://yz.scu.edu.cn/zsxx/Details/847ddc21-97e3-4e72-b574-3fa0056e7bb0	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1644	660	四川大学	四川大学2026年各院系所博士拟录取名单公示	录取	2026-04-28	https://yz.scu.edu.cn/bsfslq/gstz/4	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1645	660	四川大学	四川大学2026年各院系所硕士研究生拟录取名单公示	录取	2026-03-30	https://yz.scu.edu.cn/ssfslq/gstz/4	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1646	660	四川大学	四川大学2026年推免生(含直博生)拟录取名单公示	录取	2025-10-21	https://yz.scu.edu.cn/tms/yxstmgs	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1647	660	四川大学	四川大学2026年推免生(含直博生)接收人数汇总表	公告	2025-10-09	https://yz.scu.edu.cn/tms/tmsjkgs	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1648	660	四川大学	四川大学2025年各院系所硕士研究生复试成绩公示	复试	2025-03-28	https://yz.scu.edu.cn/ssfslq/gstz/2	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1649	660	四川大学	四川大学2025年硕士研究生入学考试照顾政策审核结果公示	录取	2025-03-19	https://yz.scu.edu.cn/zsxx/Details/670e4319-cf33-488d-afb8-e825b4cf2c2b	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1650	660	四川大学	硕士推免目录	目录	\N	https://yz.scu.edu.cn/sszyml/tmsml	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1651	660	四川大学	港澳台硕士目录	目录	\N	https://yz.scu.edu.cn/ssgat	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1652	660	四川大学	港澳台博士目录	目录	\N	https://yz.scu.edu.cn/bsgat	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1653	660	四川大学	招生单位联系方式	公告	\N	https://yz.scu.edu.cn/contact/yxs	yz.scu.edu.cn	2026-10-19T02:12:18	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:18.886591+08
1654	643	重庆大学	硕士研究生招生章程及专业目录	目录	\N	https://yz.cqu.edu.cn/sszyml/2027/index.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1655	643	重庆大学	博士研究生招生章程及专业目录	目录	\N	https://yz.cqu.edu.cn/bszyml/2026/index.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1656	643	重庆大学	港澳台研究生招生章程及专业目录	目录	\N	https://yz.cqu.edu.cn/gatzyml/2026/index.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1657	643	重庆大学	研究生招生服务系统	公告	\N	https://syk.cqu.edu.cn	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1658	643	重庆大学	2027年全国硕士研究生招生考试重庆大学考点公告..	公告	2026-10-26	https://yz.cqu.edu.cn/./news/2026-10/2603.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1659	643	重庆大学	重庆大学大数据与软件学院2027年推免研究生复试录取工作实施细则..	复试	2026-10-26	https://yz.cqu.edu.cn/./news/2026-09/2600.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1660	643	重庆大学	重庆大学土木工程学院2027年推免研究生复试录取实施细则..	复试	2026-09-26	https://yz.cqu.edu.cn/./news/2026-09/2599.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1661	643	重庆大学	重庆大学自动化学院2027年推免研究生招生录取工作实施细则..	录取	2026-09-25	https://yz.cqu.edu.cn/./news/2026-09/2598.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1662	643	重庆大学	重庆大学人文社会科学高等研究院2027年推免研究生复试工作实施细..	复试	2026-09-25	https://yz.cqu.edu.cn/./news/2026-09/2597.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1663	643	重庆大学	重庆大学数学与统计学院2027年推免研究生招生录取实施细则..	录取	2026-09-25	https://yz.cqu.edu.cn/./news/2026-09/2596.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1664	643	重庆大学	重庆大学2026年高校思想政治工作骨干在职攻读博士学位专项计划报名通知..	报名	2026-05-25	https://yz.cqu.edu.cn/./news/2026-04/2537.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1665	643	重庆大学	重庆大学2026年“少数民族高层次骨干人才计划”博士研究生报名通知..	报名	2026-04-25	https://yz.cqu.edu.cn/./news/2026-04/2532.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1666	643	重庆大学	2027年全国硕士研究生招生考试重庆大学考点公告	公告	2026-01-24	https://yz.cqu.edu.cn/./news/2026-10/2603.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1706	563	湖南大学	关于2026级研究生新生图像补采的通知	公告	2026-09-30	https://gra.hnu.edu.cn/info/1050/10619.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1667	643	重庆大学	重庆大学人文社会科学高等研究院2027年推免研究生复试工作实施细则..	复试	2026-09-25	https://yz.cqu.edu.cn/./news/2026-09/2597.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1668	643	重庆大学	重庆大学计算机学院2027年推免研究生复试录取工作实施细则..	复试	2026-09-25	https://yz.cqu.edu.cn/./news/2026-09/2593.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1669	643	重庆大学	重庆大学美视电影学院2027年推免研究生复试录取工作实施细则..	复试	2026-09-25	https://yz.cqu.edu.cn/./news/2026-09/2591.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1670	643	重庆大学	重庆大学数学与统计学院2026年港澳台研究生复试录取实施细则..	复试	2026-09-25	https://yz.cqu.edu.cn/./news/2026-05/2548.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1671	643	重庆大学	重庆大学计算机学院2026年港澳台研究生复试录取实施细则..	复试	2026-05-25	https://yz.cqu.edu.cn/./news/2026-05/2547.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1672	643	重庆大学	重庆大学土木工程学院2026年港澳台研究生复试录取实施细则..	复试	2026-05-25	https://yz.cqu.edu.cn/./news/2026-05/2546.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1673	643	重庆大学	重庆大学法学院2026年港澳台博士研究生复试录取实施细则..	复试	2026-05-25	https://yz.cqu.edu.cn/./news/2026-05/2545.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1674	643	重庆大学	重庆大学建筑城规学院2026年港澳台研究生复试录取实施细则..	复试	2026-05-25	https://yz.cqu.edu.cn/./news/2026-05/2544.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1675	643	重庆大学	重庆大学电气工程学院2026年港澳台硕士研究生复试录取实施细则..	复试	2026-05-25	https://yz.cqu.edu.cn/./news/2026-05/2543.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1676	643	重庆大学	关于重庆大学2026年面向港澳台地区研究生招生初试合格线及复试相关公告..	复试	2026-05-25	https://yz.cqu.edu.cn/./news/2026-05/2540.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1677	643	重庆大学	关于重庆大学2026年面向港澳台研究生招生初试成绩查询与复核的通知..	初试	2026-05-25	https://yz.cqu.edu.cn/./news/2026-04/2536.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1678	643	重庆大学	2026-03-13重庆大学2026年硕士研究生招生考试初试合格基本分数线	初试	2026-05-25	https://yz.cqu.edu.cn/./news/2026-03/2461.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1679	643	重庆大学	2026-05-29重庆大学2026年面向港澳台地区研究生拟录取名单公示及相关事宜说明	录取	2026-05-25	https://yz.cqu.edu.cn/./news/2026-05/2550.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1680	643	重庆大学	2026-05-09重庆大学2026年硕士研究生拟录取名单公示	录取	2026-03-24	https://yz.cqu.edu.cn/./news/2026-05/2539.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1681	643	重庆大学	2026-03-17重庆大学2026年相关学院硕士研究生招生考试初试合格分数线（二次划线）	初试	2025-12-24	https://yz.cqu.edu.cn/./news/2026-03/2493.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1682	643	重庆大学	2025-12-24重庆大学2026年拟录取推免硕士（直博）研究生名单公示	录取	2025-10-24	https://yz.cqu.edu.cn/./news/2025-12/2418.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1683	643	重庆大学	2025-10-24重庆大学2026年拟录取推免研究生（含直博生）分学院、专业及专项人数统计	录取	2025-10-24	https://yz.cqu.edu.cn/./news/2025-10/2412.html	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1684	643	重庆大学	推免研究生预报名	报名	\N	https://syk.cqu.edu.cn	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1685	643	重庆大学	硕士研究生初试成绩查询	初试	\N	https://syk.cqu.edu.cn/cjcx/	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1686	643	重庆大学	硕士研究生复试查询	复试	\N	https://syk.cqu.edu.cn	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1687	643	重庆大学	拟录取研究生服务系统	录取	\N	https://syk.cqu.edu.cn	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1688	643	重庆大学	博士研究生招生报名	报名	\N	https://syk.cqu.edu.cn/	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1689	643	重庆大学	港澳台研究生招生报名	报名	\N	https://www.gatzs.com.cn/	yz.cqu.edu.cn	2026-10-19T02:12:25	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:25.473915+08
1690	733	西北工业大学	复试分数线	复试	\N	https://yzb.nwpu.edu.cn/new/sszs/fsfsx.htm	yzb.nwpu.edu.cn	2026-10-19T02:12:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:32.951502+08
1691	733	西北工业大学	西北工业大学2027年全国硕士研究生招生考试网报公告2026-10-08	公告	2026-10-07	https://yzb.nwpu.edu.cn/info/1174/10548.htm	yzb.nwpu.edu.cn	2026-10-19T02:12:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:32.951502+08
1692	733	西北工业大学	西北工业大学2027年硕士研究生招生简章2026-10-07	简章	2026-09-04	https://yzb.nwpu.edu.cn/info/1174/10498.htm	yzb.nwpu.edu.cn	2026-10-19T02:12:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:32.951502+08
1693	733	西北工业大学	西北工业大学2027年接收推荐免试研究生预报名的通知2026-09-04	报名	2026-05-29	https://yzb.nwpu.edu.cn/info/1174/10478.htm	yzb.nwpu.edu.cn	2026-10-19T02:12:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:32.951502+08
1694	733	西北工业大学	西北工业大学2026年同等学力人员申请硕士学位注册简章2026-05-29	简章	2026-05-29	https://yzb.nwpu.edu.cn/info/1174/10418.htm	yzb.nwpu.edu.cn	2026-10-19T02:12:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:32.951502+08
1699	733	西北工业大学	历年硕士研究生考试复试基本分数线	复试	\N	https://yzb.nwpu.edu.cn/new/sszs/fsfsx.htm	yzb.nwpu.edu.cn	2026-10-19T02:12:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:32.951502+08
1700	563	湖南大学	各学院研究生招生联系方式	公告	2022-03-18	https://gra.hnu.edu.cn/info/1075/8219.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1701	563	湖南大学	关于报考2027年少数民族高层次骨干人才计划...	公告	2026-10-13	https://gra.hnu.edu.cn/info/1075/10625.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1702	563	湖南大学	2027年全国硕士研究生招生考试湖南大学报考...	公告	2026-10-08	https://gra.hnu.edu.cn/info/1075/10623.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1703	563	湖南大学	湖南大学2027年硕士研究生招生章程	公告	2026-10-05	https://gra.hnu.edu.cn/info/1075/10621.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1707	563	湖南大学	关于报送2026年7月批次学位申请材料的通知	公告	2026-06-23	https://gra.hnu.edu.cn/info/1080/10517.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1708	563	湖南大学	关于报送2026年6月批次学位申请材料的通知	公告	2026-05-07	https://gra.hnu.edu.cn/info/1080/10454.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1709	563	湖南大学	关于开展2026年湖南大学优秀博士、硕士学位...	公告	2026-05-07	https://gra.hnu.edu.cn/info/1080/10453.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1710	563	湖南大学	关于公布湖南大学2023-2024年度学术学位硕士...	公告	2026-04-10	https://gra.hnu.edu.cn/info/1080/10405.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1711	563	湖南大学	关于报送2026年4月批次学位申请材料的通知	公告	2026-03-17	https://gra.hnu.edu.cn/info/1080/10383.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1712	563	湖南大学	关于报送2025年12月批次学位申请材料的通知	公告	2025-11-18	https://gra.hnu.edu.cn/info/1080/10296.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1713	563	湖南大学	关于报送2025年10月增开校学位评定会的通知	公告	2025-09-17	https://gra.hnu.edu.cn/info/1080/10235.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1714	563	湖南大学	关于开展我校学位评定委员会换届工作的通知	公告	2025-09-12	https://gra.hnu.edu.cn/info/1080/10234.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1715	563	湖南大学	关于报送2025年7月批次学位申请材料的通知	公告	2025-06-20	https://gra.hnu.edu.cn/info/1080/10151.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1716	563	湖南大学	湖南大学研究生院劳务派遣岗位招聘公告	公告	2026-09-11	https://gra.hnu.edu.cn/info/1081/10597.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1717	563	湖南大学	关于第78次全国计算机等级考试报名的通知	报名	2026-06-29	https://gra.hnu.edu.cn/info/1081/10528.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1718	563	湖南大学	湖南大学研究生院劳务派遣岗位招聘公告	公告	2026-06-02	https://gra.hnu.edu.cn/info/1081/10493.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1719	563	湖南大学	研究生招生管理系统	公告	\N	https://yjszsxt.hnu.edu.cn/zsxt/login.aspx	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1720	563	湖南大学	博士研究生招生网上报名	报名	\N	https://yjszsxt.hnu.edu.cn/zsxt/bswb/default.aspx	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1721	563	湖南大学	研究生招生信息系统(考生端)	公告	\N	https://yjszsxt.hnu.edu.cn/ksxt/login.aspx	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1722	563	湖南大学	推免生预报名	报名	\N	https://yjszsxt.hnu.edu.cn/zsxt/tmsgl/default.aspx	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1723	563	湖南大学	复试分数线	复试	\N	https://gra.hnu.edu.cn/info/1100/9497.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1724	563	湖南大学	复试录取名单	复试	\N	https://gra.hnu.edu.cn/index/xxgk/fslqmd.htm	gra.hnu.edu.cn	2026-10-19T02:12:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:39.90798+08
1735	662	电子科技大学	招生宣讲会	公告	\N	http://yzconsole.360eol.com/web/adjust/school_detail.html?id=387	yz.uestc.edu.cn	2026-10-19T04:56:54	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:56:54.453088+08
1736	662	电子科技大学	硕士简章目录	简章	\N	https://yz.uestc.edu.cn/sszs/zsjz.htm	yz.uestc.edu.cn	2026-10-19T04:56:54	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:56:54.453088+08
1737	662	电子科技大学	博士简章目录	简章	\N	https://yz.uestc.edu.cn/bszs/zsjz.htm	yz.uestc.edu.cn	2026-10-19T04:56:54	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:56:54.453088+08
1738	662	电子科技大学	硕士历年复试分数线	复试	\N	https://yz.uestc.edu.cn/xxcx/sslnfsfsx.htm	yz.uestc.edu.cn	2026-10-19T04:56:54	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:56:54.453088+08
1745	662	电子科技大学	研究生招生管理系统	公告	\N	https://yz.uestc.edu.cn/zsglxtjm.htm	yz.uestc.edu.cn	2026-10-19T04:56:54	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:56:54.453088+08
1754	735	西安电子科技大学	硕士研究生招生	公告	\N	https://gr.xidian.edu.cn/yjsy/yjszs.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1755	735	西安电子科技大学	博士研究生招生	公告	\N	https://gr.xidian.edu.cn/yjsy/bsyjszs.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1756	735	西安电子科技大学	其他类型招生	公告	\N	https://gr.xidian.edu.cn/yjsy/qtlxzs.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1762	735	西安电子科技大学	关于2026年秋季学期“学术规范与论文写作”、“科学道德与学风”等网上在线课程的开课通知	公告	\N	https://gr.xidian.edu.cn/info/1037/20784.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1763	735	西安电子科技大学	关于2026年春季学期“学术规范与论文写作”、“科学道德与学风”等网上在线课程的开课通知	公告	\N	https://gr.xidian.edu.cn/info/1037/18614.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1764	735	西安电子科技大学	产教融通课《秦创原“四链融合”示范课：关键技术的市场路径》开课通知	公告	\N	https://gr.xidian.edu.cn/info/1037/18394.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1765	735	西安电子科技大学	西安电子科技大学关于受理2026年1月研究生结业申请的通知	公告	\N	https://gr.xidian.edu.cn/info/1037/17604.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1766	735	西安电子科技大学	关于2025年秋季学期“学术规范与论文写作”、“科学道德与学风”等网上在线课程的开课通知	公告	\N	https://gr.xidian.edu.cn/info/1037/17244.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1767	735	西安电子科技大学	西安电子科技大学工商管理、公共管理硕士申请学位相关资料	公告	\N	https://gr.xidian.edu.cn/info/1047/5083.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1768	735	西安电子科技大学	西安电子科技大学申请同等学力硕士学位相关资料	公告	\N	https://gr.xidian.edu.cn/info/1047/5084.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1769	735	西安电子科技大学	西安电子科技大学专业学位硕士申请学位相关资料	公告	\N	https://gr.xidian.edu.cn/info/1047/5086.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1770	735	西安电子科技大学	西安电子科技大学学术学位硕士申请学位相关资料	公告	\N	https://gr.xidian.edu.cn/info/1047/5087.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1771	735	西安电子科技大学	关于申报2026年秋季优秀博士学位论文资助基金的通知	公告	\N	https://gr.xidian.edu.cn/info/1044/20724.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1772	735	西安电子科技大学	关于对2026年9月申请授位研究生学位论文进行抽查评估的通知	公告	\N	https://gr.xidian.edu.cn/info/1044/20484.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1773	735	西安电子科技大学	关于开展2026年度中国人工智能学会博士学位论文激励计划推荐工作的通知	公告	\N	https://gr.xidian.edu.cn/info/1044/20354.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1774	735	西安电子科技大学	关于开展2026年度中国通信学会博士硕士学位论文激励计划推荐工作的通知	公告	\N	https://gr.xidian.edu.cn/info/1044/20194.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1775	735	西安电子科技大学	关于开展2026年度中国指挥与控制学会博士学位论文激励计划推荐工作的通知	公告	\N	https://gr.xidian.edu.cn/info/1044/20094.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1776	735	西安电子科技大学	关于组织推荐2026年中国科协青年科技人才培育工程博士生专项计划候选人的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/20454.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1777	735	西安电子科技大学	关于评选2025年度西安电子科技大学优秀研究生导师及研究生教育与学科建设管理工作先进集体和先进个人的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/19094.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1778	735	西安电子科技大学	关于开展2025年度研究生导师能力提升 “红专计划”明德育人专题论坛的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/19134.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1779	735	西安电子科技大学	关于开展研究生导师“应知应会”考试的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/19104.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1780	735	西安电子科技大学	关于开展 2025 年度研究生导师能力提升 “红专计划”导学关系主题在线研修培训的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/19114.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1781	735	西安电子科技大学	关于开展2025届研究生毕业季“立德树人结硕果，桃李芬芳启新程”育人风采征集展示活动的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/19124.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1782	735	西安电子科技大学	关于评选2024年度西安电子科技大学优秀研究生导师及研究生教育与学科建设管理工作先进集体和先进个人的通知	公告	\N	https://gr.xidian.edu.cn/info/1183/15014.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1783	735	西安电子科技大学	2026年国家建设高水平大学公派研究生项目选派通知	公告	\N	https://gr.xidian.edu.cn/info/1040/17964.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1784	735	西安电子科技大学	2025年师生“双一流”海外研修项目报名通知	报名	\N	https://gr.xidian.edu.cn/info/1040/16674.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1785	735	西安电子科技大学	2025年国家建设高水平大学公派研究生项目选派通知	公告	\N	https://gr.xidian.edu.cn/info/1040/14914.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1786	735	西安电子科技大学	【转发】关于邀请参加2025博士生国际招生面试交流会的通知	公告	\N	https://gr.xidian.edu.cn/info/1040/17084.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1787	735	西安电子科技大学	转发：关于参加2024博士生国际招生面试交流会的通知	公告	\N	https://gr.xidian.edu.cn/info/1040/13804.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1788	735	西安电子科技大学	2024年第二批师生“双一流”海外研修项目报名通知	报名	\N	https://gr.xidian.edu.cn/info/1040/13513.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1789	735	西安电子科技大学	2024年国家建设高水平大学公派研究生项目选派通知	公告	\N	https://gr.xidian.edu.cn/info/1040/13265.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1790	735	西安电子科技大学	2024年首批师生“双一流”海外研修项目报名通知	报名	\N	https://gr.xidian.edu.cn/info/1040/13254.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1791	735	西安电子科技大学	2023博士生国际招生面试交流会参会通知	公告	\N	https://gr.xidian.edu.cn/info/1040/13160.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1792	735	西安电子科技大学	2023年第二批师生“双一流”海外研修项目报名通知	报名	\N	https://gr.xidian.edu.cn/info/1040/13029.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1793	735	西安电子科技大学	2027年少数民族高层次骨干人才计划硕士研究生报考说明	公告	\N	https://gr.xidian.edu.cn/info/1074/21034.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1794	735	西安电子科技大学	2027年全国硕士研究生招生考试网上报名公告	报名	\N	https://gr.xidian.edu.cn/info/1074/20864.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1795	735	西安电子科技大学	2027年硕士研究生招生考试自命题科目考试大纲	大纲	\N	https://gr.xidian.edu.cn/info/1074/20824.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1796	735	西安电子科技大学	2027年硕士研究生招生简章	简章	\N	https://gr.xidian.edu.cn/info/1074/20804.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1797	735	西安电子科技大学	2027年接收推荐免试研究生预报名通知	报名	\N	https://gr.xidian.edu.cn/info/1074/20424.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1798	735	西安电子科技大学	西安电子科技大学2026年预选工程博士遴选结果通知	公告	\N	https://gr.xidian.edu.cn/info/1075/20294.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1799	735	西安电子科技大学	关于2026年拟录取博士研究生办理相关事宜的通知	录取	\N	https://gr.xidian.edu.cn/info/1075/20114.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1800	735	西安电子科技大学	2026年博士研究生招生简章及专业目录	简章	\N	https://gr.xidian.edu.cn/info/1072/17664.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1801	735	西安电子科技大学	2026年硕士研究生招生考试自命题科目考试大纲	大纲	\N	https://gr.xidian.edu.cn/info/1072/17324.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1802	735	西安电子科技大学	2026年硕士研究生招生简章	简章	\N	https://gr.xidian.edu.cn/info/1072/17294.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1803	735	西安电子科技大学	2025年博士研究生招生简章及专业目录	简章	\N	https://gr.xidian.edu.cn/info/1072/14464.htm	gr.xidian.edu.cn	2026-10-19T04:57:00	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:00.475363+08
1804	326	南京邮电大学	硕士历年复试...	复试	\N	https://yzb.njupt.edu.cn/7813/list.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1805	326	南京邮电大学	硕士历年报录...	公告	\N	https://yzb.njupt.edu.cn/7814/list.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1806	326	南京邮电大学	硕士信息公开	公告	\N	https://yzb.njupt.edu.cn/ssxxgk/list.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1808	326	南京邮电大学	2027年全国硕士研究生入学考试南京邮电大学（3226）报考点网报公告	公告	\N	https://yzb.njupt.edu.cn/2026/1008/c7797a309298/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1810	326	南京邮电大学	南京邮电大学2027年接收推荐免试攻读研究生(含直博生)复试录取的通知（第二批次）（持续更新中）	复试	\N	https://yzb.njupt.edu.cn/2026/0925/c7797a309195/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1811	326	南京邮电大学	各学院2027年接收推荐免试攻读研究生(含直博生)复试录取工作细则	复试	2026-09-17	https://yzb.njupt.edu.cn/2026/0917/c7797a308625/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1812	326	南京邮电大学	各学院2027年接收推荐免试攻读研究生(含直博生)复试录取工作细则	复试	\N	https://yzb.njupt.edu.cn/2026/0917/c7797a308625/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1813	326	南京邮电大学	​南京邮电大学2026年全国优秀大学生暑期校园开放日通知信息汇总	公告	2026-07-06	https://yzb.njupt.edu.cn/2026/0630/c7797a305598/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1814	326	南京邮电大学	​南京邮电大学2026年全国优秀大学生暑期校园开放日通知信息汇总	公告	\N	https://yzb.njupt.edu.cn/2026/0630/c7797a305598/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1816	326	南京邮电大学	2026年博士研究生拟录取名单公示（补录）（公示已结束）	录取	\N	https://yzb.njupt.edu.cn/2026/0625/c7798a305456/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1818	326	南京邮电大学	南京邮电大学2026年拟录取博士研究生调档等相关通知	录取	\N	https://yzb.njupt.edu.cn/2026/0617/c7798a305085/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1820	326	南京邮电大学	2026年博士研究生拟录取名单公示（第三批次）（公示已结束）	录取	\N	https://yzb.njupt.edu.cn/2026/0617/c7798a305082/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1822	326	南京邮电大学	关于2026年申请考核制博士生招生第三轮报名工作的通知	报名	\N	https://yzb.njupt.edu.cn/2026/0602/c7798a303217/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1823	326	南京邮电大学	2026年“申请-考核”制博士研究生招生综合考核通知	公告	2026-05-19	https://yzb.njupt.edu.cn/2026/0519/c7798a302259/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1824	326	南京邮电大学	2026年“申请-考核”制博士研究生招生综合考核通知	公告	\N	https://yzb.njupt.edu.cn/2026/0519/c7798a302259/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1825	326	南京邮电大学	MORE 08 2026-10 南京邮电大学2027年硕士研究生招生学院及专业方向介绍	公告	\N	https://yzb.njupt.edu.cn/7795/list.psp	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1826	326	南京邮电大学	南京邮电大学2027年硕士研究生招生学院及专业方向介绍	公告	\N	https://yzb.njupt.edu.cn/2026/1008/c7795a309303/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1827	326	南京邮电大学	南京邮电大学2027年硕士研究生招生专业目录	目录	2026-09-30	https://yzb.njupt.edu.cn/2026/0930/c7795a309245/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1828	326	南京邮电大学	南京邮电大学2027年硕士研究生招生专业目录	目录	\N	https://yzb.njupt.edu.cn/2026/0930/c7795a309245/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1829	326	南京邮电大学	南京邮电大学2027年硕士研究生招生章程	公告	2026-09-30	https://yzb.njupt.edu.cn/2026/0929/c7795a309242/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1830	326	南京邮电大学	南京邮电大学2027年硕士研究生招生章程	公告	\N	https://yzb.njupt.edu.cn/2026/0929/c7795a309242/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1831	326	南京邮电大学	南京邮电大学2026年硕士研究生招生学院及专业方向介绍	公告	2025-10-15	https://yzb.njupt.edu.cn/2025/1015/c7795a290020/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1832	326	南京邮电大学	南京邮电大学2026年硕士研究生招生学院及专业方向介绍	公告	\N	https://yzb.njupt.edu.cn/2025/1015/c7795a290020/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1834	326	南京邮电大学	南京邮电大学2026年硕士研究生招生专业目录	目录	\N	https://yzb.njupt.edu.cn/2025/0929/c7795a289588/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1836	326	南京邮电大学	南京邮电大学2026年博士研究生招生专业目录	目录	\N	https://yzb.njupt.edu.cn/2025/1209/c7796a293779/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1838	326	南京邮电大学	南京邮电大学2026年博士研究生招生章程	公告	\N	https://yzb.njupt.edu.cn/2025/1209/c7796a293778/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1839	326	南京邮电大学	南京邮电大学2025年博士研究生招生专业目录	目录	2024-12-10	https://yzb.njupt.edu.cn/2024/1210/c7796a275943/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1840	326	南京邮电大学	南京邮电大学2025年博士研究生招生专业目录	目录	\N	https://yzb.njupt.edu.cn/2024/1210/c7796a275943/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1841	326	南京邮电大学	南京邮电大学2025年博士研究生招生章程	公告	2024-12-10	https://yzb.njupt.edu.cn/2024/1210/c7796a275942/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1842	326	南京邮电大学	南京邮电大学2025年博士研究生招生章程	公告	\N	https://yzb.njupt.edu.cn/2024/1210/c7796a275942/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1843	326	南京邮电大学	南京邮电大学2025年接收直博生招生专业一览表	公告	2024-09-26	https://yzb.njupt.edu.cn/2024/0925/c7796a270360/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1844	326	南京邮电大学	南京邮电大学2025年接收直博生招生专业一览表	公告	\N	https://yzb.njupt.edu.cn/2024/0925/c7796a270360/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1845	326	南京邮电大学	2026年全国硕士研究生招生考试南京邮电大学 考点（3226）入校须知	公告	2026-10-08	https://yzb.njupt.edu.cn/2025/1218/c12466a294754/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1846	326	南京邮电大学	2026年全国硕士研究生招生考试南京邮电大学 考点（3226）入校须知	公告	2025-12-18	https://yzb.njupt.edu.cn/2025/1218/c12466a294754/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1847	326	南京邮电大学	2026年全国硕士研究生招生考试 南京邮电大学考点（考点代码：3226）考生须知	公告	2025-12-18	https://yzb.njupt.edu.cn/2025/1216/c12466a294518/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1848	326	南京邮电大学	2026年全国硕士研究生招生考试 南京邮电大学考点（考点代码：3226）考生须知	公告	2025-12-16	https://yzb.njupt.edu.cn/2025/1216/c12466a294518/page.htm	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1849	326	南京邮电大学	研究生报考登录	公告	\N	http://yzbm.njupt.edu.cn/logon	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1850	326	南京邮电大学	硕士初试成绩查分	初试	\N	http://yzbm.njupt.edu.cn/sscjcx/index	yzb.njupt.edu.cn	2026-10-19T04:57:35	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:35.236561+08
1871	644	重庆邮电大学	各招生学院联系方式	公告	\N	http://yjs.cqupt.edu.cn/info/1183/4923.htm	yjs.cqupt.edu.cn	2026-10-19T04:57:52	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:52.69541+08
1872	644	重庆邮电大学	重邮硕士招生调剂工作方案	调剂	\N	https://yjs.cqupt.edu.cn/info/1180/11254.htm	yjs.cqupt.edu.cn	2026-10-19T04:57:52	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:52.69541+08
1873	644	重庆邮电大学	再次开通重庆邮电大学2024年博士研究生招生报名系统通知	报名	\N	https://yjs.cqupt.edu.cn/info/1179/8254.htm	yjs.cqupt.edu.cn	2026-10-19T04:57:52	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:57:52.69541+08
1922	5	清华大学	招生综合信息平台	公告	\N	https://yzbm.tsinghua.edu.cn/publish/infors	yz.tsinghua.edu.cn	2026-10-19T04:58:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:21.868876+08
1923	5	清华大学	招生信息Admissions	公告	\N	https://yz.tsinghua.edu.cn/zsxx/sszs/jzml.htm	yz.tsinghua.edu.cn	2026-10-19T04:58:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:21.868876+08
1924	5	清华大学	最新公告Notice	公告	\N	https://yz.tsinghua.edu.cn/zxgg.htm	yz.tsinghua.edu.cn	2026-10-19T04:58:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:21.868876+08
1925	5	清华大学	082026.10 2027年清华大学初步录取强基生的信息校对和网上确认的相关通知	录取	\N	https://yz.tsinghua.edu.cn/info/1024/3276.htm	yz.tsinghua.edu.cn	2026-10-19T04:58:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:21.868876+08
1926	5	清华大学	082026.10 清华大学2027年硕士研究生招生专业目录_统招(含招生人数)	目录	\N	https://yzbm.tsinghua.edu.cn/publish/s02/s0203/detail/c0fb8664-255f-4d6f-bf40-a5893e3343ec	yz.tsinghua.edu.cn	2026-10-19T04:58:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:21.868876+08
1927	5	清华大学	082026.10 2027年全国硕士研究生招生考试清华大学报考点（1103）公告	公告	\N	https://yz.tsinghua.edu.cn/info/1024/3270.htm	yz.tsinghua.edu.cn	2026-10-19T04:58:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:21.868876+08
1928	5	清华大学	082026.10 2027年全国硕士研究生招生考试清华大学（10003）报名公告	报名	\N	https://yz.tsinghua.edu.cn/info/1024/3268.htm	yz.tsinghua.edu.cn	2026-10-19T04:58:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:21.868876+08
1929	5	清华大学	082026.10 清华大学2027年硕士研究生招生简章	简章	\N	https://yz.tsinghua.edu.cn/info/1024/3266.htm	yz.tsinghua.edu.cn	2026-10-19T04:58:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:21.868876+08
1930	5	清华大学	182026.09 2027年推荐免试直硕、直博生履行正式报名手续的通知及资格复审要求	报名	\N	https://yz.tsinghua.edu.cn/info/1024/3262.htm	yz.tsinghua.edu.cn	2026-10-19T04:58:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:21.868876+08
1931	5	清华大学	国际招生 International Admissions	公告	\N	https://yz.tsinghua.edu.cn/zsxx/gjxs/tzgg.htm	yz.tsinghua.edu.cn	2026-10-19T04:58:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:21.868876+08
1932	5	清华大学	152026.06 【2027】清华大学研究生招生宣传周（直播回放）	公告	\N	https://www.xuetangx.com/live/live2026yjszsxcz/live2026yjszsxcz/31264152/83755097?channel=i.area.home_live_ad	yz.tsinghua.edu.cn	2026-10-19T04:58:21	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:21.868876+08
1933	6	北京大学	留学生招生	公告	\N	https://admission.pku.edu.cn/zsxx/lxszs/index.htm	admission.pku.edu.cn	2026-10-19T04:58:27	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:27.722532+08
1934	6	北京大学	硕士招生公示	录取	\N	https://admission.pku.edu.cn/xxgk/xxgkssbm/index.htm	admission.pku.edu.cn	2026-10-19T04:58:27	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:27.722532+08
1935	6	北京大学	博士招生公示	录取	\N	https://admission.pku.edu.cn/xxgk/xxgkbsbm/index.htm	admission.pku.edu.cn	2026-10-19T04:58:27	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:27.722532+08
1936	6	北京大学	院系招生公示	录取	\N	https://admission.pku.edu.cn/xxgk/xxgkyxgs/index.htm	admission.pku.edu.cn	2026-10-19T04:58:27	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:27.722532+08
1937	6	北京大学	&#xe603; 硕士招生	公告	\N	https://admission.pku.edu.cn/zsxx/sszs/index.htm	admission.pku.edu.cn	2026-10-19T04:58:27	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:27.722532+08
1938	6	北京大学	&#xe61e; 博士招生	公告	\N	https://admission.pku.edu.cn/zsxx/bszs/index.htm	admission.pku.edu.cn	2026-10-19T04:58:27	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:27.722532+08
1939	6	北京大学	&#xe886; 港澳台招生	公告	\N	https://admission.pku.edu.cn/zsxx/gatzs/index.htm	admission.pku.edu.cn	2026-10-19T04:58:27	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:27.722532+08
1940	6	北京大学	&#xe607; 留学生招生	公告	\N	https://admission.pku.edu.cn/zsxx/lxszs/index.htm	admission.pku.edu.cn	2026-10-19T04:58:27	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:27.722532+08
1983	275	上海交通大学	博士生招生	公告	\N	https://yzb.sjtu.edu.cn/zsjz/bsszs	yzb.sjtu.edu.cn	2026-10-19T04:58:41	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:41.962472+08
1984	275	上海交通大学	硕士生招生	公告	\N	https://yzb.sjtu.edu.cn/zsjz/sszs	yzb.sjtu.edu.cn	2026-10-19T04:58:41	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:41.962472+08
1985	275	上海交通大学	预推免报名	报名	\N	http://ga.sjtu.edu.cn/zsgl/ytmgl/	yzb.sjtu.edu.cn	2026-10-19T04:58:41	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:41.962472+08
1986	275	上海交通大学	夏令营公示	录取	\N	https://yzb.sjtu.edu.cn/xxgs/xlygs	yzb.sjtu.edu.cn	2026-10-19T04:58:41	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:41.962472+08
2021	275	上海交通大学	上海交通大学安泰金融硕士项目宣传册（2025） 05.22/2024	公告	\N	https://yzb.sjtu.edu.cn/post/2562	yzb.sjtu.edu.cn	2026-10-19T04:58:41	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:58:41.962472+08
2044	245	哈尔滨工业大学	招生信息 Admission	公告	\N	https://yzb.hit.edu.cn/zsxx/list.htm	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2045	245	哈尔滨工业大学	招生简章 Brochure	简章	\N	https://yzb.hit.edu.cn/zsjz/list.htm	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2046	245	哈尔滨工业大学	硕士招生简章	简章	\N	https://yzb.hit.edu.cn/22281/list.htm	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2047	245	哈尔滨工业大学	博士招生简章	简章	\N	https://yzb.hit.edu.cn/22282/list.htm	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2048	245	哈尔滨工业大学	联培专项招生 JOINT TRAINING	公告	\N	https://yzb.hit.edu.cn/lpzxzs/list.htm	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2049	245	哈尔滨工业大学	宣传目录 Promotion	目录	\N	http://yzb.hit.edu.cn/22288/list.htm	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2050	245	哈尔滨工业大学	招生宣传片	公告	\N	https://yzb.hit.edu.cn/22288/list.htm	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2051	245	哈尔滨工业大学	招生宣传活动	公告	\N	https://yzb.hit.edu.cn/22289/list.htm	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2052	245	哈尔滨工业大学	哈工大研究生招生中英文网站正式焕新上线	公告	\N	https://mp.weixin.qq.com/s/2fDevCgRkR6b4GiqZMAkSg	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2053	245	哈尔滨工业大学	研究生招生校园开放日	公告	\N	https://mp.weixin.qq.com/s/sfKv1db6lXAbN7lAa8c_LQ	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2054	245	哈尔滨工业大学	硕士通知书邮寄地址采集	公告	\N	http://hityzb.hit.edu.cn/zhxy-yjs-zs_v2/tzs/xxtx	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2055	245	哈尔滨工业大学	推免生信息采集系统	公告	\N	http://hityzb.hit.edu.cn/zhxy-yjs-zs_v2/common/login?redirectUrl=/pc/tms/index	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2072	245	哈尔滨工业大学	直播预告 - 2026研究生招生线上宣讲会（5月20日 - 5月28日）	公告	\N	https://yzb.hit.edu.cn/2026/0526/c22289a393138/page.htm	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2073	245	哈尔滨工业大学	10月19日18:00 | 哈工大研究生招生线上宣讲会：哈工大里昂数据科学学院专场 2026-10-19	公告	2026-10-19	https://mp.weixin.qq.com/s/RRd3yJu82Cwh_w6UEX4buA	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2079	245	哈尔滨工业大学	逐梦哈工大，研途启新程｜6月12日哈工大研究生招生校园开放日精彩瞬间 查看招生简章	简章	\N	https://mp.weixin.qq.com/s/dsXuJkkOWd9OueOJ9jYIRw	yzb.hit.edu.cn	2026-10-19T04:59:10	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:10.224873+08
2080	732	西安交通大学	2027年全国硕士研究生招生考试西安交通大学（学校代码:10698）网报公告	公告	\N	https://yz.xjtu.edu.cn/info/1082/4420.htm	yz.xjtu.edu.cn	2026-10-19T04:59:17	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:17.296063+08
2086	732	西安交通大学	西安交通大学2027年硕士研究生招生章程	公告	\N	https://yz.xjtu.edu.cn/info/1083/4418.htm	yz.xjtu.edu.cn	2026-10-19T04:59:17	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:17.296063+08
2087	732	西安交通大学	2027年西安交通大学（10698）研究生招生网报公告三	公告	\N	https://yz.xjtu.edu.cn/info/1083/4423.htm	yz.xjtu.edu.cn	2026-10-19T04:59:17	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:17.296063+08
2088	732	西安交通大学	2027年全国硕士研究生招生考试西安交通大学（学校...	公告	\N	https://yz.xjtu.edu.cn/info/1083/4415.htm	yz.xjtu.edu.cn	2026-10-19T04:59:17	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:17.296063+08
2089	732	西安交通大学	2027年全国硕士研究生招生考试西安交通大学考点（...	公告	\N	https://yz.xjtu.edu.cn/info/1083/4417.htm	yz.xjtu.edu.cn	2026-10-19T04:59:17	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:17.296063+08
2090	732	西安交通大学	历年复试线	复试	\N	https://yz.xjtu.edu.cn/index/lnfsx.htm	yz.xjtu.edu.cn	2026-10-19T04:59:17	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:17.296063+08
2103	517	华中科技大学	学位授权点目录	目录	\N	https://gs.hust.edu.cn/pygz/zbjs111/xwsqdml.htm	gs.hust.edu.cn	2026-10-19T04:59:53	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 12:59:53.573106+08
2139	11	北京理工大学	2027-2028学年香港理工大学联合培养博士双学位项目申报通知	公告	\N	https://grd.bit.edu.cn/gjjl/xnlhpyxm/tzgg_xn/ebfdee92f6794d14b1ca292fac712d26.htm	grd.bit.edu.cn	2026-10-19T05:00:14	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:14.675165+08
2140	11	北京理工大学	【国际交流】2027年寒假世界名校交流项目报名通知	报名	\N	https://grd.bit.edu.cn/gjjl/xnlhpyxm/tzgg_xn/32b158c51e3749fcae5db39813957ca6.htm	grd.bit.edu.cn	2026-10-19T05:00:14	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:14.675165+08
2141	11	北京理工大学	关于2026年冬季研究生学位论文评阅、学位答辩及申请相关工作的通知	公告	\N	https://grd.bit.edu.cn/xwgz/xwgz2/tzgg_xwgz/09c0299e542749618dfc5320bb63764a.htm	grd.bit.edu.cn	2026-10-19T05:00:14	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:14.675165+08
2142	11	北京理工大学	关于评定2026年研究生学业奖学金的通知	公告	\N	https://grd.bit.edu.cn/tzgg1/b17a4945f04c4c51afade79d026aa79b.htm	grd.bit.edu.cn	2026-10-19T05:00:14	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:14.675165+08
2143	11	北京理工大学	硕士学位论文盲评系统	公告	\N	http://pyxt.bit.edu.cn/	grd.bit.edu.cn	2026-10-19T05:00:14	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:14.675165+08
2385	563	湖南大学	研究生招生管理系统	公告	\N	https://yjszsxt.hnu.edu.cn/zsxt/login.aspx	gra.hnu.edu.cn	2026-10-19T05:01:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:32.826006+08
2145	274	同济大学	同济大学研究生招生管理平台-管理员入口	公告	\N	https://yzgl.tongji.edu.cn/	yz.tongji.edu.cn	2026-10-19T05:00:22	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:22.670679+08
2170	108	天津大学	留学生招生	公告	\N	https://yzb.tju.edu.cn/./zszn/lxszs/	yzb.tju.edu.cn	2026-10-19T05:00:30	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:30.534985+08
2171	108	天津大学	2027级推免硕士...	公告	\N	https://sszs.tju.edu.cn/10056/main/user/enrollbook	yzb.tju.edu.cn	2026-10-19T05:00:30	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:30.534985+08
2172	108	天津大学	硕士生招生管理系统	公告	\N	https://sszs.tju.edu.cn/10056/user/login/login	yzb.tju.edu.cn	2026-10-19T05:00:30	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:30.534985+08
2220	185	大连理工大学	2021年各学部（学院）硕士研究生复试录取办法公示	复试	\N	http://gs.dlut.edu.cn/info/1173/11367.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2221	185	大连理工大学	大连理工大学2027年“国优计划”专项招生选拔通知	公告	\N	https://gs.dlut.edu.cn/info/1173/51622.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
560	4	北京科技大学	中国研究生招生信息网	公告	\N	http://yz.chsi.com.cn/	yzxc.ustb.edu.cn	2026-10-19T05:01:26	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:01:23.332501+08
2222	185	大连理工大学	关于2026年硕士研究生学位论文答辩及相关工作安排	公告	\N	https://gs.dlut.edu.cn/info/1206/48652.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2223	185	大连理工大学	关于新增研究生招生专业学费的说明	公告	\N	https://gs.dlut.edu.cn/info/1173/52032.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2224	185	大连理工大学	2026博士学位论文单项\\特别奖学金评选结果公示	录取	\N	https://gs.dlut.edu.cn/info/1206/51992.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2225	185	大连理工大学	关于2027年集成电路学院硕士研究生招生考试参考书目的公告	公告	\N	http://ic.dlut.edu.cn/info/1034/11768.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2226	185	大连理工大学	关于2027届研究生毕业生图像采集报名的通知	报名	\N	https://gs.dlut.edu.cn/info/1089/51902.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2227	185	大连理工大学	关于2026级研究生新生课程免修的补充通知	公告	\N	https://gs.dlut.edu.cn/info/1089/51692.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2228	185	大连理工大学	关于开展2026年优秀博士论文特别奖学金评选工作的通知	公告	\N	https://gs.dlut.edu.cn/info/1206/51652.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2229	185	大连理工大学	关于开展2026年优秀博士论文单项奖学金评选工作的通知	公告	\N	https://gs.dlut.edu.cn/info/1206/51642.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2230	185	大连理工大学	我校各学部（学院）2027年接收推荐免试攻读硕士（博士）学位...	公告	\N	https://gs.dlut.edu.cn/info/1173/51682.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2231	185	大连理工大学	大连理工大学2027年秋季批次硕博连读预报名通知（更新）	报名	\N	https://gs.dlut.edu.cn/info/1173/51602.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2232	185	大连理工大学	关于发放大连理工大学2026年研究生录取通知书的通知	录取	\N	https://gs.dlut.edu.cn/info/1173/51482.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2233	185	大连理工大学	关于2025年基础学科导师创新基金评审结果公示	录取	\N	https://gs.dlut.edu.cn/info/1004/17026.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2234	185	大连理工大学	关于召开2025年首聘研究生导师培训会的通知	公告	\N	https://portal.dlut.edu.cn/tp/index.html#act=sems-tp-nup_28585749&contentid=&ownerid=&website=0&pim_id=11857642000556032	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2235	185	大连理工大学	关于申报2025年研究生导师创新基金的通知	公告	\N	https://gs.dlut.edu.cn/info/1004/16936.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2236	185	大连理工大学	关于开展2025年“1+X学科交叉导师团队” 专项申报工作的通知	公告	\N	https://gs.dlut.edu.cn/info/1004/16256.htm	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2240	185	大连理工大学	博士答辩公告	公告	\N	https://dutgs.dlut.edu.cn/gmis/xw/dbgggs.aspx	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2241	185	大连理工大学	硕士答辩公告	公告	\N	https://dutgs.dlut.edu.cn/gmis/xw/dbggssgs.aspx	gs.dlut.edu.cn	2026-10-19T05:00:39	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:39.141314+08
2245	224	吉林大学	吉林大学招生网	公告	\N	http://zsb.jlu.edu.cn/	yjsy.jlu.edu.cn	2026-10-19T05:00:45	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:00:45.876507+08
2296	660	四川大学	夏令营&预推免	公告	\N	https://yz.scu.edu.cn/xly	yz.scu.edu.cn	2026-10-19T05:01:11	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:11.453874+08
2297	660	四川大学	推免生（直博）专业目录	目录	\N	https://yz.scu.edu.cn/sszyml/tmsml	yz.scu.edu.cn	2026-10-19T05:01:11	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:11.453874+08
2298	660	四川大学	港澳台硕士招生专业目录	目录	\N	https://yz.scu.edu.cn/ssgat	yz.scu.edu.cn	2026-10-19T05:01:11	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:11.453874+08
2299	660	四川大学	港澳台博士招生专业目录	目录	\N	https://yz.scu.edu.cn/bsgat	yz.scu.edu.cn	2026-10-19T05:01:11	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:11.453874+08
2300	660	四川大学	招生学院(系/所)	公告	\N	https://yz.scu.edu.cn/contact/yxs	yz.scu.edu.cn	2026-10-19T05:01:11	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:11.453874+08
2316	660	四川大学	硕士推免目录	目录	\N	https://yz.scu.edu.cn/sszyml/tmsml	yz.scu.edu.cn	2026-10-19T05:01:11	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:11.453874+08
2317	660	四川大学	港澳台硕士目录	目录	\N	https://yz.scu.edu.cn/ssgat	yz.scu.edu.cn	2026-10-19T05:01:11	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:11.453874+08
2318	660	四川大学	港澳台博士目录	目录	\N	https://yz.scu.edu.cn/bsgat	yz.scu.edu.cn	2026-10-19T05:01:11	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:11.453874+08
2319	660	四川大学	招生单位联系方式	公告	\N	https://yz.scu.edu.cn/contact/yxs	yz.scu.edu.cn	2026-10-19T05:01:11	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:11.453874+08
2320	643	重庆大学	硕士研究生招生章程及专业目录	目录	\N	https://yz.cqu.edu.cn/sszyml/2027/index.html	yz.cqu.edu.cn	2026-10-19T05:01:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:20.04278+08
2321	643	重庆大学	博士研究生招生章程及专业目录	目录	\N	https://yz.cqu.edu.cn/bszyml/2026/index.html	yz.cqu.edu.cn	2026-10-19T05:01:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:20.04278+08
2322	643	重庆大学	港澳台研究生招生章程及专业目录	目录	\N	https://yz.cqu.edu.cn/gatzyml/2026/index.html	yz.cqu.edu.cn	2026-10-19T05:01:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:20.04278+08
2323	643	重庆大学	研究生招生服务系统	公告	\N	https://syk.cqu.edu.cn	yz.cqu.edu.cn	2026-10-19T05:01:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:20.04278+08
2350	643	重庆大学	推免研究生预报名	报名	\N	https://syk.cqu.edu.cn	yz.cqu.edu.cn	2026-10-19T05:01:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:20.04278+08
2351	643	重庆大学	硕士研究生初试成绩查询	初试	\N	https://syk.cqu.edu.cn/cjcx/	yz.cqu.edu.cn	2026-10-19T05:01:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:20.04278+08
2352	643	重庆大学	硕士研究生复试查询	复试	\N	https://syk.cqu.edu.cn	yz.cqu.edu.cn	2026-10-19T05:01:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:20.04278+08
2353	643	重庆大学	拟录取研究生服务系统	录取	\N	https://syk.cqu.edu.cn	yz.cqu.edu.cn	2026-10-19T05:01:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:20.04278+08
2354	643	重庆大学	博士研究生招生报名	报名	\N	https://syk.cqu.edu.cn/	yz.cqu.edu.cn	2026-10-19T05:01:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:20.04278+08
2355	643	重庆大学	港澳台研究生招生报名	报名	\N	https://www.gatzs.com.cn/	yz.cqu.edu.cn	2026-10-19T05:01:20	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:20.04278+08
2356	733	西北工业大学	复试分数线	复试	\N	https://yzb.nwpu.edu.cn/new/sszs/fsfsx.htm	yzb.nwpu.edu.cn	2026-10-19T05:01:26	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:26.316495+08
2365	733	西北工业大学	历年硕士研究生考试复试基本分数线	复试	\N	https://yzb.nwpu.edu.cn/new/sszs/fsfsx.htm	yzb.nwpu.edu.cn	2026-10-19T05:01:26	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:26.316495+08
2386	563	湖南大学	博士研究生招生网上报名	报名	\N	https://yjszsxt.hnu.edu.cn/zsxt/bswb/default.aspx	gra.hnu.edu.cn	2026-10-19T05:01:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:32.826006+08
34	4	北京科技大学	中国研究生招生信息网	报名	2024-12-17	http://yz.chsi.com.cn/	yzxc.ustb.edu.cn	2026-10-19T05:01:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 09:31:47.740118+08
2387	563	湖南大学	研究生招生信息系统(考生端)	公告	\N	https://yjszsxt.hnu.edu.cn/ksxt/login.aspx	gra.hnu.edu.cn	2026-10-19T05:01:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:32.826006+08
2388	563	湖南大学	推免生预报名	报名	\N	https://yjszsxt.hnu.edu.cn/zsxt/tmsgl/default.aspx	gra.hnu.edu.cn	2026-10-19T05:01:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:32.826006+08
2389	563	湖南大学	复试分数线	复试	\N	https://gra.hnu.edu.cn/info/1100/9497.htm	gra.hnu.edu.cn	2026-10-19T05:01:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:32.826006+08
2390	563	湖南大学	复试录取名单	复试	\N	https://gra.hnu.edu.cn/index/xxgk/fslqmd.htm	gra.hnu.edu.cn	2026-10-19T05:01:32	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 13:01:32.826006+08
2395	592	华南理工大学	关于公示华南理工大学2026年硕士研究生拟录取名单的通知	录取	2026-05-11	http://yz.scut.edu.cn/2026/0511/c30111a626646/page.htm	yz.scut.edu.cn	2026-10-19T07:44:53	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 15:16:36.613653+08
1623	592	华南理工大学	关于公示华南理工大学2025年硕士研究生拟录取名单的通知	录取	2025-05-23	http://yz.scut.edu.cn/2025/0523/c30111a592029/page.htm	yz.scut.edu.cn	2026-10-19T07:44:53	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 10:12:08.160817+08
2397	592	华南理工大学	关于公示华南理工大学2024年硕士研究生拟录取名单的通知	录取	2024-05-27	http://yz.scut.edu.cn/2024/0527/c30111a554473/page.htm	yz.scut.edu.cn	2026-10-19T07:44:53	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 15:16:36.613653+08
2398	592	华南理工大学	华南理工大学2023年硕士研究生拟录取名单公示	录取	2023-05-24	http://yz.scut.edu.cn/2023/0524/c30111a503425/page.htm	yz.scut.edu.cn	2026-10-19T07:44:53	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 15:16:36.613653+08
2391	108	天津大学	天津大学2026年各学院调剂复试成绩及拟录取名单	复试	2026-04-10	https://yzb.tju.edu.cn/xwzx/tkss_xw/202604/t20260410_324595.htm	yzb.tju.edu.cn	2026-10-19T07:48:03	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 15:12:13.942164+08
2392	108	天津大学	天津大学2026年各学院硕士研究生复试成绩及拟录取名单	复试	2026-03-27	https://yzb.tju.edu.cn/xwzx/tkss_xw/202603/t20260327_324583.htm	yzb.tju.edu.cn	2026-10-19T07:48:03	\N	\N	\N	\N	\N	\N	f	f	\N	\N	\N	f	2026-10-19 15:12:13.942164+08
\.


--
-- Data for Name: kaoyan_schools; Type: TABLE DATA; Schema: public; Owner: kaoyan
--

COPY public.kaoyan_schools (id, name, level, province, city, logo_url, intro, tags, official_url, data_source, type, region, created_at, updated_at, enabled, deleted_at) FROM stdin;
3	北京邮电大学	211	北京	\N	\N	\N	["yz_dwdm:10013", "yz_sch_id:367890", "双一流", "博士点"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 00:00:27.521395+08	2026-10-19 23:20:50.886046+08	t	\N
4	北京科技大学	211	北京	\N	\N	\N	["yz_dwdm:10008", "yz_sch_id:367896", "双一流", "博士点"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 00:00:32.530623+08	2026-10-19 23:20:50.886046+08	t	\N
5	清华大学	985	北京	\N	\N	\N	["yz_dwdm:10003", "yz_sch_id:367880", "自主划线", "双一流", "博士点"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 00:00:36.778643+08	2026-10-19 23:20:50.886046+08	t	\N
6	北京大学	985	北京	\N	\N	\N	["yz_dwdm:10001"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.793954+08	2026-10-19 23:20:50.886046+08	t	\N
7	中国人民大学	985	北京	\N	\N	\N	["yz_dwdm:10002"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.803321+08	2026-10-19 23:20:50.886046+08	t	\N
8	北京交通大学	211	北京	\N	\N	\N	["yz_dwdm:10004"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.805465+08	2026-10-19 23:20:50.886046+08	t	\N
9	北京工业大学	211	北京	\N	\N	\N	["yz_dwdm:10005"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.807565+08	2026-10-19 23:20:50.886046+08	t	\N
10	北京航空航天大学	985	北京	\N	\N	\N	["yz_dwdm:10006"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.813055+08	2026-10-19 23:20:50.886046+08	t	\N
11	北京理工大学	985	北京	\N	\N	\N	["yz_dwdm:10007"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.814786+08	2026-10-19 23:20:50.886046+08	t	\N
12	北方工业大学	双非	北京	\N	\N	\N	["yz_dwdm:10009"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.817771+08	2026-10-19 23:20:50.886046+08	t	\N
13	北京化工大学	211	北京	\N	\N	\N	["yz_dwdm:10010"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.818868+08	2026-10-19 23:20:50.886046+08	t	\N
14	北京服装学院	双非	北京	\N	\N	\N	["yz_dwdm:10012"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.820243+08	2026-10-19 23:20:50.886046+08	t	\N
15	北京印刷学院	双非	北京	\N	\N	\N	["yz_dwdm:10015"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.822038+08	2026-10-19 23:20:50.886046+08	t	\N
16	北京石油化工学院	双非	北京	\N	\N	\N	["yz_dwdm:10017"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.844045+08	2026-10-19 23:20:50.886046+08	t	\N
17	北京电子科技学院	双非	北京	\N	\N	\N	["yz_dwdm:10018"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.845582+08	2026-10-19 23:20:50.886046+08	t	\N
18	北京农学院	双非	北京	\N	\N	\N	["yz_dwdm:10020"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.847259+08	2026-10-19 23:20:50.886046+08	t	\N
19	北京协和医学院	双一流	北京	\N	\N	\N	["yz_dwdm:10023"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.848666+08	2026-10-19 23:20:50.886046+08	t	\N
20	首都体育学院	双非	北京	\N	\N	\N	["yz_dwdm:10029"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.849928+08	2026-10-19 23:20:50.886046+08	t	\N
21	北京第二外国语学院	双非	北京	\N	\N	\N	["yz_dwdm:10031"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.851103+08	2026-10-19 23:20:50.886046+08	t	\N
22	北京物资学院	双非	北京	\N	\N	\N	["yz_dwdm:10037"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.852356+08	2026-10-19 23:20:50.886046+08	t	\N
23	外交学院	双一流	北京	\N	\N	\N	["yz_dwdm:10040"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.85345+08	2026-10-19 23:20:50.886046+08	t	\N
24	中国科学技术信息研究所	双非	北京	\N	\N	\N	["yz_dwdm:80901"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.854527+08	2026-10-19 23:20:50.886046+08	t	\N
25	机械科学研究总院(北京机械工业自动化研究所)	双非	北京	\N	\N	\N	["yz_dwdm:82702"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.855584+08	2026-10-19 23:20:50.886046+08	t	\N
26	机械科学研究总院(北京机电研究所)	双非	北京	\N	\N	\N	["yz_dwdm:82703"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.856636+08	2026-10-19 23:20:50.886046+08	t	\N
27	中国航空研究院(北京航空精密机械研究所)	双非	北京	\N	\N	\N	["yz_dwdm:82902"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.85762+08	2026-10-19 23:20:50.886046+08	t	\N
28	中国航空研究院(北京长城计量测试技术研究所)	双非	北京	\N	\N	\N	["yz_dwdm:82932"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.859428+08	2026-10-19 23:20:50.886046+08	t	\N
29	华北计算机系统工程研究所	双非	北京	\N	\N	\N	["yz_dwdm:83001"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.862649+08	2026-10-19 23:20:50.886046+08	t	\N
30	中国兵器科学研究院(中国北方车辆研究所)	双非	北京	\N	\N	\N	["yz_dwdm:83107"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.86395+08	2026-10-19 23:20:50.886046+08	t	\N
31	北京市科学技术研究院资源环境研究所	双非	北京	\N	\N	\N	["yz_dwdm:83702"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.865459+08	2026-10-19 23:20:50.886046+08	t	\N
32	交通运输部公路科学研究所	双非	北京	\N	\N	\N	["yz_dwdm:83902"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.868996+08	2026-10-19 23:20:50.886046+08	t	\N
33	北京生物制品研究所	双非	北京	\N	\N	\N	["yz_dwdm:84504"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.872278+08	2026-10-19 23:20:50.886046+08	t	\N
34	中国科学院大学	双一流	北京	\N	\N	\N	["yz_dwdm:14430"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.87559+08	2026-10-19 23:20:50.886046+08	t	\N
35	中国社会科学院大学	双非	北京	\N	\N	\N	["yz_dwdm:14596"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.876726+08	2026-10-19 23:20:50.886046+08	t	\N
36	中国农业科学院	双非	北京	\N	\N	\N	["yz_dwdm:82101"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.881421+08	2026-10-19 23:20:50.886046+08	t	\N
37	中国地质科学院	双非	北京	\N	\N	\N	["yz_dwdm:82501"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.882896+08	2026-10-19 23:20:50.886046+08	t	\N
38	中国中医科学院	双非	北京	\N	\N	\N	["yz_dwdm:84502"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.886372+08	2026-10-19 23:20:50.886046+08	t	\N
39	军事科学院	双非	北京	\N	\N	\N	["yz_dwdm:92101"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.887461+08	2026-10-19 23:20:50.886046+08	t	\N
40	中国财政科学研究院	双非	北京	\N	\N	\N	["yz_dwdm:81601"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.89686+08	2026-10-19 23:20:50.886046+08	t	\N
41	商务部国际贸易经济合作研究院	双非	北京	\N	\N	\N	["yz_dwdm:82001"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.898543+08	2026-10-19 23:20:50.886046+08	t	\N
42	中国林业科学研究院	双非	北京	\N	\N	\N	["yz_dwdm:82201"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.903023+08	2026-10-19 23:20:50.886046+08	t	\N
43	中国水利水电科学研究院	双非	北京	\N	\N	\N	["yz_dwdm:82301"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.904543+08	2026-10-19 23:20:50.886046+08	t	\N
44	中国电力科学研究院	双非	北京	\N	\N	\N	["yz_dwdm:82302"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.906886+08	2026-10-19 23:20:50.886046+08	t	\N
45	中国建筑科学研究院	双非	北京	\N	\N	\N	["yz_dwdm:82401"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.909818+08	2026-10-19 23:20:50.886046+08	t	\N
46	中国城市规划设计研究院	双非	北京	\N	\N	\N	["yz_dwdm:82402"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.911417+08	2026-10-19 23:20:50.886046+08	t	\N
47	中国建筑设计研究院	双非	北京	\N	\N	\N	["yz_dwdm:82403"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.913937+08	2026-10-19 23:20:50.886046+08	t	\N
48	中国环境科学研究院	双非	北京	\N	\N	\N	["yz_dwdm:82405"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.917692+08	2026-10-19 23:20:50.886046+08	t	\N
49	冶金自动化研究院	双非	北京	\N	\N	\N	["yz_dwdm:82605"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.928129+08	2026-10-19 23:20:50.886046+08	t	\N
50	中国电影艺术研究中心	双非	北京	\N	\N	\N	["yz_dwdm:84202"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.929234+08	2026-10-19 23:20:50.886046+08	t	\N
51	中国疾病预防控制中心	双非	北京	\N	\N	\N	["yz_dwdm:84501"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.930269+08	2026-10-19 23:20:50.886046+08	t	\N
52	国家老年医学中心	双非	北京	\N	\N	\N	["yz_dwdm:84512"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.931486+08	2026-10-19 23:20:50.886046+08	t	\N
53	国家海洋环境预报中心	双非	北京	\N	\N	\N	["yz_dwdm:85304"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.932631+08	2026-10-19 23:20:50.886046+08	t	\N
54	北京工商大学	双非	北京	\N	\N	\N	["yz_dwdm:10011"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.933702+08	2026-10-19 23:20:50.886046+08	t	\N
55	中国农业大学	985	北京	\N	\N	\N	["yz_dwdm:10019"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.93594+08	2026-10-19 23:20:50.886046+08	t	\N
56	中国传媒大学	211	北京	\N	\N	\N	["yz_dwdm:10033"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.938438+08	2026-10-19 23:20:50.886046+08	t	\N
57	中国人民公安大学	双一流	北京	\N	\N	\N	["yz_dwdm:10041"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.940061+08	2026-10-19 23:20:50.886046+08	t	\N
58	中国音乐学院	双一流	北京	\N	\N	\N	["yz_dwdm:10046"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.941081+08	2026-10-19 23:20:50.886046+08	t	\N
59	中国戏曲学院	双非	北京	\N	\N	\N	["yz_dwdm:10049"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.942099+08	2026-10-19 23:20:50.886046+08	t	\N
60	中国政法大学	211	北京	\N	\N	\N	["yz_dwdm:10053"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.943221+08	2026-10-19 23:20:50.886046+08	t	\N
61	中国矿业大学(北京)	211	北京	\N	\N	\N	["yz_dwdm:11413"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.946042+08	2026-10-19 23:20:50.886046+08	t	\N
62	中国石油大学(北京)	211	北京	\N	\N	\N	["yz_dwdm:11414"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.952663+08	2026-10-19 23:20:50.886046+08	t	\N
63	中国地质大学(北京)	211	北京	\N	\N	\N	["yz_dwdm:11415"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.955138+08	2026-10-19 23:20:50.886046+08	t	\N
64	中华女子学院	双非	北京	\N	\N	\N	["yz_dwdm:11149"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.957748+08	2026-10-19 23:20:50.886046+08	t	\N
65	北京国家会计学院	双非	北京	\N	\N	\N	["yz_dwdm:80401"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.965749+08	2026-10-19 23:20:50.886046+08	t	\N
66	国家体育总局体育科学研究所	双非	北京	\N	\N	\N	["yz_dwdm:84601"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.968819+08	2026-10-19 23:20:50.886046+08	t	\N
67	应急管理部国家自然灾害防治研究院	双非	北京	\N	\N	\N	["yz_dwdm:85407"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.973567+08	2026-10-19 23:20:50.886046+08	t	\N
68	国防大学	双非	北京	\N	\N	\N	["yz_dwdm:92001"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.977143+08	2026-10-19 23:20:50.886046+08	t	\N
69	核工业第二研究设计院	双非	北京	\N	\N	\N	["yz_dwdm:82803"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.979787+08	2026-10-19 23:20:50.886046+08	t	\N
70	核工业北京地质研究院	双非	北京	\N	\N	\N	["yz_dwdm:82806"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.988432+08	2026-10-19 23:20:50.886046+08	t	\N
71	核工业北京化工冶金研究院	双非	北京	\N	\N	\N	["yz_dwdm:82807"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:11.99246+08	2026-10-19 23:20:50.886046+08	t	\N
72	中国航空工业规划设计研究院	双非	北京	\N	\N	\N	["yz_dwdm:82920"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.010467+08	2026-10-19 23:20:50.886046+08	t	\N
73	北京橡胶工业研究设计院	双非	北京	\N	\N	\N	["yz_dwdm:83504"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.012769+08	2026-10-19 23:20:50.886046+08	t	\N
74	中国食品发酵工业研究院	双非	北京	\N	\N	\N	["yz_dwdm:83705"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.013952+08	2026-10-19 23:20:50.886046+08	t	\N
75	北京信息科技大学	双非	北京	\N	\N	\N	["yz_dwdm:11232"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.015108+08	2026-10-19 23:20:50.886046+08	t	\N
76	中国电子科技集团有限公司研究生院	双非	北京	\N	\N	\N	["yz_dwdm:83000"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.016251+08	2026-10-19 23:20:50.886046+08	t	\N
77	北京师范大学	985	北京	\N	\N	\N	["yz_dwdm:10027"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.017352+08	2026-10-19 23:20:50.886046+08	t	\N
78	首都师范大学	双一流	北京	\N	\N	\N	["yz_dwdm:10028"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.018593+08	2026-10-19 23:20:50.886046+08	t	\N
79	中国农业机械化科学研究院	双非	北京	\N	\N	\N	["yz_dwdm:82715"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.01957+08	2026-10-19 23:20:50.886046+08	t	\N
80	北京林业大学	211	北京	\N	\N	\N	["yz_dwdm:10022"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.020609+08	2026-10-19 23:20:50.886046+08	t	\N
81	首都医科大学	双一流	北京	\N	\N	\N	["yz_dwdm:10025"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.021623+08	2026-10-19 23:20:50.886046+08	t	\N
82	北京中医药大学	211	北京	\N	\N	\N	["yz_dwdm:10026"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.023827+08	2026-10-19 23:20:50.886046+08	t	\N
83	中国兽医药品监察所	双非	北京	\N	\N	\N	["yz_dwdm:82110"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.02487+08	2026-10-19 23:20:50.886046+08	t	\N
84	中央财经大学	211	北京	\N	\N	\N	["yz_dwdm:10034"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.026017+08	2026-10-19 23:20:50.886046+08	t	\N
85	中国航空研究院	双非	北京	\N	\N	\N	["yz_dwdm:82901"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.028774+08	2026-10-19 23:20:50.886046+08	t	\N
86	中国航空研究院(北京航空材料研究院)	双非	北京	\N	\N	\N	["yz_dwdm:82913"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.030115+08	2026-10-19 23:20:50.886046+08	t	\N
87	中国航空研究院(625所)	双非	北京	\N	\N	\N	["yz_dwdm:82914"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.031294+08	2026-10-19 23:20:50.886046+08	t	\N
88	陆军航空兵学院	双非	北京	\N	\N	\N	["yz_dwdm:92007"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.032418+08	2026-10-19 23:20:50.886046+08	t	\N
89	中国航天科工集团第二研究院	双非	北京	\N	\N	\N	["yz_dwdm:83221"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.033526+08	2026-10-19 23:20:50.886046+08	t	\N
90	中国航天科工集团第三研究院	双非	北京	\N	\N	\N	["yz_dwdm:83241"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.034598+08	2026-10-19 23:20:50.886046+08	t	\N
91	中国航天空气动力技术研究院	双非	北京	\N	\N	\N	["yz_dwdm:83277"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.03675+08	2026-10-19 23:20:50.886046+08	t	\N
92	军事航天部队航天工程大学	双非	北京	\N	\N	\N	["yz_dwdm:92033"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.037849+08	2026-10-19 23:20:50.886046+08	t	\N
93	石油勘探开发科学研究院	双非	北京	\N	\N	\N	["yz_dwdm:83401"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.03909+08	2026-10-19 23:20:50.886046+08	t	\N
94	石油化工科学研究院	双非	北京	\N	\N	\N	["yz_dwdm:86301"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.040291+08	2026-10-19 23:20:50.886046+08	t	\N
95	中国地震局地质研究所	双非	北京	\N	\N	\N	["yz_dwdm:85402"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.041544+08	2026-10-19 23:20:50.886046+08	t	\N
96	华北电力大学	211	北京	\N	\N	\N	["yz_dwdm:10054"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.042792+08	2026-10-19 23:20:50.886046+08	t	\N
97	北京建筑大学	双非	北京	\N	\N	\N	["yz_dwdm:10016"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.043837+08	2026-10-19 23:20:50.886046+08	t	\N
98	中冶集团建筑研究总院	双非	北京	\N	\N	\N	["yz_dwdm:82602"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.045029+08	2026-10-19 23:20:50.886046+08	t	\N
99	中国建筑材料科学研究总院	双非	北京	\N	\N	\N	["yz_dwdm:84901"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.046297+08	2026-10-19 23:20:50.886046+08	t	\N
100	中央民族大学	985	北京	\N	\N	\N	["yz_dwdm:10052"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.047544+08	2026-10-19 23:20:50.886046+08	t	\N
101	北京外国语大学	211	北京	\N	\N	\N	["yz_dwdm:10030"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.048677+08	2026-10-19 23:20:50.886046+08	t	\N
102	国际关系学院	双非	北京	\N	\N	\N	["yz_dwdm:10042"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.049696+08	2026-10-19 23:20:50.886046+08	t	\N
103	对外经济贸易大学	211	北京	\N	\N	\N	["yz_dwdm:10036"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.050941+08	2026-10-19 23:20:50.886046+08	t	\N
104	中国铁道科学研究院	双非	北京	\N	\N	\N	["yz_dwdm:83801"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.052163+08	2026-10-19 23:20:50.886046+08	t	\N
105	中国工程物理研究院	双非	北京	\N	\N	\N	["yz_dwdm:82817"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.053478+08	2026-10-19 23:20:50.886046+08	t	\N
106	北京市市政工程研究院	双非	北京	\N	\N	\N	["yz_dwdm:87111"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.055912+08	2026-10-19 23:20:50.886046+08	t	\N
107	南开大学	985	天津	\N	\N	\N	["yz_dwdm:10055"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.057409+08	2026-10-19 23:20:50.886046+08	t	\N
108	天津大学	985	天津	\N	\N	\N	["yz_dwdm:10056"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.058639+08	2026-10-19 23:20:50.886046+08	t	\N
109	天津科技大学	双非	天津	\N	\N	\N	["yz_dwdm:10057"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.059684+08	2026-10-19 23:20:50.886046+08	t	\N
110	天津工业大学	双一流	天津	\N	\N	\N	["yz_dwdm:10058"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.06071+08	2026-10-19 23:20:50.886046+08	t	\N
111	中国民航大学	双非	天津	\N	\N	\N	["yz_dwdm:10059"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.062147+08	2026-10-19 23:20:50.886046+08	t	\N
112	天津理工大学	双非	天津	\N	\N	\N	["yz_dwdm:10060"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.063215+08	2026-10-19 23:20:50.886046+08	t	\N
113	天津农学院	双非	天津	\N	\N	\N	["yz_dwdm:10061"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.064277+08	2026-10-19 23:20:50.886046+08	t	\N
114	天津医科大学	211	天津	\N	\N	\N	["yz_dwdm:10062"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.065222+08	2026-10-19 23:20:50.886046+08	t	\N
184	辽宁大学	211	辽宁	\N	\N	\N	["yz_dwdm:10140"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.155059+08	2026-10-19 23:20:50.886046+08	t	\N
115	天津中医药大学	双一流	天津	\N	\N	\N	["yz_dwdm:10063"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.066679+08	2026-10-19 23:20:50.886046+08	t	\N
116	天津师范大学	双非	天津	\N	\N	\N	["yz_dwdm:10065"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.067669+08	2026-10-19 23:20:50.886046+08	t	\N
117	天津职业技术师范大学	双非	天津	\N	\N	\N	["yz_dwdm:10066"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.068718+08	2026-10-19 23:20:50.886046+08	t	\N
118	天津体育学院	双非	天津	\N	\N	\N	["yz_dwdm:10071"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.069815+08	2026-10-19 23:20:50.886046+08	t	\N
119	天津音乐学院	双非	天津	\N	\N	\N	["yz_dwdm:10072"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.070923+08	2026-10-19 23:20:50.886046+08	t	\N
120	天津美术学院	双非	天津	\N	\N	\N	["yz_dwdm:10073"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.071951+08	2026-10-19 23:20:50.886046+08	t	\N
121	海军勤务学院	双非	天津	\N	\N	\N	["yz_dwdm:92018"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.073195+08	2026-10-19 23:20:50.886046+08	t	\N
122	武警指挥学院	双非	天津	\N	\N	\N	["yz_dwdm:92037"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.074387+08	2026-10-19 23:20:50.886046+08	t	\N
123	武警后勤学院	双非	天津	\N	\N	\N	["yz_dwdm:92042"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.075405+08	2026-10-19 23:20:50.886046+08	t	\N
124	中国舰船研究院(天津航海仪器研究所)	双非	天津	\N	\N	\N	["yz_dwdm:86211"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.076586+08	2026-10-19 23:20:50.886046+08	t	\N
125	核工业理化工程研究院	双非	天津	\N	\N	\N	["yz_dwdm:82804"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.077722+08	2026-10-19 23:20:50.886046+08	t	\N
126	中国航天科工集团公司第三研究院(8357所)	双非	天津	\N	\N	\N	["yz_dwdm:83245"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.078883+08	2026-10-19 23:20:50.886046+08	t	\N
127	中国航天科工集团第三研究院(8358所)	双非	天津	\N	\N	\N	["yz_dwdm:83246"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.079887+08	2026-10-19 23:20:50.886046+08	t	\N
128	国家海洋技术中心	双非	天津	\N	\N	\N	["yz_dwdm:85305"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.080852+08	2026-10-19 23:20:50.886046+08	t	\N
129	天津外国语大学	双非	天津	\N	\N	\N	["yz_dwdm:10068"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.081957+08	2026-10-19 23:20:50.886046+08	t	\N
130	天津财经大学	双非	天津	\N	\N	\N	["yz_dwdm:10070"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.083526+08	2026-10-19 23:20:50.886046+08	t	\N
131	河北大学	双非	河北	\N	\N	\N	["yz_dwdm:10075"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.084606+08	2026-10-19 23:20:50.886046+08	t	\N
132	河北工程大学	双非	河北	\N	\N	\N	["yz_dwdm:10076"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.085654+08	2026-10-19 23:20:50.886046+08	t	\N
133	河北地质大学	双非	河北	\N	\N	\N	["yz_dwdm:10077"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.08678+08	2026-10-19 23:20:50.886046+08	t	\N
134	华北电力大学(保定)	211	河北	\N	\N	\N	["yz_dwdm:10079"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.088195+08	2026-10-19 23:20:50.886046+08	t	\N
135	河北工业大学	211	河北	\N	\N	\N	["yz_dwdm:10080"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.08977+08	2026-10-19 23:20:50.886046+08	t	\N
136	华北理工大学	双非	河北	\N	\N	\N	["yz_dwdm:10081"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.090827+08	2026-10-19 23:20:50.886046+08	t	\N
137	河北科技大学	双非	河北	\N	\N	\N	["yz_dwdm:10082"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.091977+08	2026-10-19 23:20:50.886046+08	t	\N
138	河北建筑工程学院	双非	河北	\N	\N	\N	["yz_dwdm:10084"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.093146+08	2026-10-19 23:20:50.886046+08	t	\N
139	河北农业大学	双非	河北	\N	\N	\N	["yz_dwdm:10086"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.094336+08	2026-10-19 23:20:50.886046+08	t	\N
140	河北医科大学	双非	河北	\N	\N	\N	["yz_dwdm:10089"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.0953+08	2026-10-19 23:20:50.886046+08	t	\N
141	河北师范大学	双非	河北	\N	\N	\N	["yz_dwdm:10094"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.096489+08	2026-10-19 23:20:50.886046+08	t	\N
142	河北北方学院	双非	河北	\N	\N	\N	["yz_dwdm:10092"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.097644+08	2026-10-19 23:20:50.886046+08	t	\N
143	承德医学院	双非	河北	\N	\N	\N	["yz_dwdm:10093"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.098722+08	2026-10-19 23:20:50.886046+08	t	\N
144	唐山师范学院	双非	河北	\N	\N	\N	["yz_dwdm:10099"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.099874+08	2026-10-19 23:20:50.886046+08	t	\N
145	河北科技师范学院	双非	河北	\N	\N	\N	["yz_dwdm:10798"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.100898+08	2026-10-19 23:20:50.886046+08	t	\N
146	河北金融学院	双非	河北	\N	\N	\N	["yz_dwdm:11420"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.10196+08	2026-10-19 23:20:50.886046+08	t	\N
147	北华航天工业学院	双非	河北	\N	\N	\N	["yz_dwdm:11629"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.103076+08	2026-10-19 23:20:50.886046+08	t	\N
148	中央司法警官学院	双非	河北	\N	\N	\N	["yz_dwdm:11903"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.104131+08	2026-10-19 23:20:50.886046+08	t	\N
149	河北传媒学院	双非	河北	\N	\N	\N	["yz_dwdm:12784"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.105818+08	2026-10-19 23:20:50.886046+08	t	\N
150	中国舰船研究院(邯郸净化设备研究所)	双非	河北	\N	\N	\N	["yz_dwdm:86221"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.106922+08	2026-10-19 23:20:50.886046+08	t	\N
151	中国人民警察大学	双非	河北	\N	\N	\N	["yz_dwdm:11105"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.108059+08	2026-10-19 23:20:50.886046+08	t	\N
152	河北中医药大学	双非	河北	\N	\N	\N	["yz_dwdm:14432"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.109146+08	2026-10-19 23:20:50.886046+08	t	\N
153	石家庄铁道大学	双非	河北	\N	\N	\N	["yz_dwdm:10107"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.110223+08	2026-10-19 23:20:50.886046+08	t	\N
154	山西大学	双一流	山西	\N	\N	\N	["yz_dwdm:10108"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.11141+08	2026-10-19 23:20:50.886046+08	t	\N
155	太原科技大学	双非	山西	\N	\N	\N	["yz_dwdm:10109"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.112506+08	2026-10-19 23:20:50.886046+08	t	\N
156	中北大学	双非	山西	\N	\N	\N	["yz_dwdm:10110"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.114838+08	2026-10-19 23:20:50.886046+08	t	\N
157	太原理工大学	211	山西	\N	\N	\N	["yz_dwdm:10112"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.116593+08	2026-10-19 23:20:50.886046+08	t	\N
158	山西农业大学	双非	山西	\N	\N	\N	["yz_dwdm:10113"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.117732+08	2026-10-19 23:20:50.886046+08	t	\N
159	山西医科大学	双非	山西	\N	\N	\N	["yz_dwdm:10114"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.1188+08	2026-10-19 23:20:50.886046+08	t	\N
160	长治医学院	双非	山西	\N	\N	\N	["yz_dwdm:10117"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.119821+08	2026-10-19 23:20:50.886046+08	t	\N
161	山西师范大学	双非	山西	\N	\N	\N	["yz_dwdm:10118"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.120786+08	2026-10-19 23:20:50.886046+08	t	\N
162	太原师范学院	双非	山西	\N	\N	\N	["yz_dwdm:10119"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.121833+08	2026-10-19 23:20:50.886046+08	t	\N
163	山西大同大学	双非	山西	\N	\N	\N	["yz_dwdm:10120"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.122964+08	2026-10-19 23:20:50.886046+08	t	\N
164	山西财经大学	双非	山西	\N	\N	\N	["yz_dwdm:10125"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.124033+08	2026-10-19 23:20:50.886046+08	t	\N
165	山西中医药大学	双非	山西	\N	\N	\N	["yz_dwdm:10809"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.125117+08	2026-10-19 23:20:50.886046+08	t	\N
166	运城学院	双非	山西	\N	\N	\N	["yz_dwdm:10123"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.12752+08	2026-10-19 23:20:50.886046+08	t	\N
167	中国兵器科学研究院(中国北方自动控制技术研究所)	双非	山西	\N	\N	\N	["yz_dwdm:83106"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.128502+08	2026-10-19 23:20:50.886046+08	t	\N
255	哈尔滨学院	双非	黑龙江	\N	\N	\N	["yz_dwdm:10234"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.263183+08	2026-10-19 23:20:50.886046+08	t	\N
168	中国辐射防护研究院	双非	山西	\N	\N	\N	["yz_dwdm:82808"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.129641+08	2026-10-19 23:20:50.886046+08	t	\N
169	中国日用化学工业研究院	双非	山西	\N	\N	\N	["yz_dwdm:83704"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.130907+08	2026-10-19 23:20:50.886046+08	t	\N
170	山西省中医药研究院	双非	山西	\N	\N	\N	["yz_dwdm:87401"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.133391+08	2026-10-19 23:20:50.886046+08	t	\N
171	内蒙古大学	211	内蒙古	\N	\N	\N	["yz_dwdm:10126"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.134958+08	2026-10-19 23:20:50.886046+08	t	\N
172	内蒙古科技大学	双非	内蒙古	\N	\N	\N	["yz_dwdm:10127"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.136231+08	2026-10-19 23:20:50.886046+08	t	\N
173	内蒙古工业大学	双非	内蒙古	\N	\N	\N	["yz_dwdm:10128"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.137438+08	2026-10-19 23:20:50.886046+08	t	\N
174	内蒙古农业大学	双非	内蒙古	\N	\N	\N	["yz_dwdm:10129"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.138544+08	2026-10-19 23:20:50.886046+08	t	\N
175	内蒙古医科大学	双非	内蒙古	\N	\N	\N	["yz_dwdm:10132"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.139667+08	2026-10-19 23:20:50.886046+08	t	\N
176	内蒙古师范大学	双非	内蒙古	\N	\N	\N	["yz_dwdm:10135"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.140899+08	2026-10-19 23:20:50.886046+08	t	\N
177	内蒙古民族大学	双非	内蒙古	\N	\N	\N	["yz_dwdm:10136"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.141998+08	2026-10-19 23:20:50.886046+08	t	\N
178	赤峰大学	双非	内蒙古	\N	\N	\N	["yz_dwdm:10138"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.143234+08	2026-10-19 23:20:50.886046+08	t	\N
179	内蒙古财经大学	双非	内蒙古	\N	\N	\N	["yz_dwdm:10139"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.149127+08	2026-10-19 23:20:50.886046+08	t	\N
180	呼伦贝尔学院	双非	内蒙古	\N	\N	\N	["yz_dwdm:10819"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.150262+08	2026-10-19 23:20:50.886046+08	t	\N
181	呼和浩特民族学院	双非	内蒙古	\N	\N	\N	["yz_dwdm:11709"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.151283+08	2026-10-19 23:20:50.886046+08	t	\N
182	内蒙古艺术学院	双非	内蒙古	\N	\N	\N	["yz_dwdm:14531"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.152852+08	2026-10-19 23:20:50.886046+08	t	\N
284	上海音乐学院	双一流	上海	\N	\N	\N	["yz_dwdm:10278"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.302492+08	2026-10-19 23:20:50.886046+08	t	\N
183	中国兵器科学研究院(内蒙古金属材料研究所)	双非	内蒙古	\N	\N	\N	["yz_dwdm:83102"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.153982+08	2026-10-19 23:20:50.886046+08	t	\N
185	大连理工大学	985	辽宁	\N	\N	\N	["yz_dwdm:10141"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.1564+08	2026-10-19 23:20:50.886046+08	t	\N
186	沈阳工业大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10142"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.158024+08	2026-10-19 23:20:50.886046+08	t	\N
187	沈阳航空航天大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10143"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.159334+08	2026-10-19 23:20:50.886046+08	t	\N
188	沈阳理工大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10144"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.160581+08	2026-10-19 23:20:50.886046+08	t	\N
189	东北大学	985	辽宁	\N	\N	\N	["yz_dwdm:10145"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.161703+08	2026-10-19 23:20:50.886046+08	t	\N
190	辽宁科技大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10146"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.163863+08	2026-10-19 23:20:50.886046+08	t	\N
191	辽宁工程技术大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10147"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.166232+08	2026-10-19 23:20:50.886046+08	t	\N
192	辽宁石油化工大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10148"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.168315+08	2026-10-19 23:20:50.886046+08	t	\N
193	沈阳化工大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10149"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.170612+08	2026-10-19 23:20:50.886046+08	t	\N
194	沈阳医学院	双非	辽宁	\N	\N	\N	["yz_dwdm:10164"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.173103+08	2026-10-19 23:20:50.886046+08	t	\N
195	鞍山师范学院	双非	辽宁	\N	\N	\N	["yz_dwdm:10169"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.17522+08	2026-10-19 23:20:50.886046+08	t	\N
196	中国刑事警察学院	双非	辽宁	\N	\N	\N	["yz_dwdm:10175"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.177543+08	2026-10-19 23:20:50.886046+08	t	\N
197	沈阳体育学院	双非	辽宁	\N	\N	\N	["yz_dwdm:10176"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.178893+08	2026-10-19 23:20:50.886046+08	t	\N
198	沈阳音乐学院	双非	辽宁	\N	\N	\N	["yz_dwdm:10177"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.179969+08	2026-10-19 23:20:50.886046+08	t	\N
199	鲁迅美术学院	双非	辽宁	\N	\N	\N	["yz_dwdm:10178"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.182132+08	2026-10-19 23:20:50.886046+08	t	\N
200	沈阳工程学院	双非	辽宁	\N	\N	\N	["yz_dwdm:11632"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.184597+08	2026-10-19 23:20:50.886046+08	t	\N
201	海军大连舰艇学院	双非	辽宁	\N	\N	\N	["yz_dwdm:92014"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.189127+08	2026-10-19 23:20:50.886046+08	t	\N
202	机械科学研究总院(沈阳铸造研究所)	双非	辽宁	\N	\N	\N	["yz_dwdm:82705"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.193612+08	2026-10-19 23:20:50.886046+08	t	\N
203	中国舰船研究院(大连测控技术研究所)	双非	辽宁	\N	\N	\N	["yz_dwdm:86220"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.1948+08	2026-10-19 23:20:50.886046+08	t	\N
204	中国航空研究院(601所)	双非	辽宁	\N	\N	\N	["yz_dwdm:82903"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.195928+08	2026-10-19 23:20:50.886046+08	t	\N
205	中国航空研究院(606所)	双非	辽宁	\N	\N	\N	["yz_dwdm:82905"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.197175+08	2026-10-19 23:20:50.886046+08	t	\N
206	中国航空研究院(626所)	双非	辽宁	\N	\N	\N	["yz_dwdm:82929"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.20023+08	2026-10-19 23:20:50.886046+08	t	\N
207	沈阳化工研究院	双非	辽宁	\N	\N	\N	["yz_dwdm:83503"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.201386+08	2026-10-19 23:20:50.886046+08	t	\N
208	辽宁工业大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10154"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.202441+08	2026-10-19 23:20:50.886046+08	t	\N
209	辽宁中医药大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10162"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.203413+08	2026-10-19 23:20:50.886046+08	t	\N
210	辽宁师范大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10165"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.204555+08	2026-10-19 23:20:50.886046+08	t	\N
211	中共辽宁省委党校	双非	辽宁	\N	\N	\N	["yz_dwdm:89621"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.20555+08	2026-10-19 23:20:50.886046+08	t	\N
212	中国医科大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10159"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.206744+08	2026-10-19 23:20:50.886046+08	t	\N
213	大连工业大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10152"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.208592+08	2026-10-19 23:20:50.886046+08	t	\N
214	沈阳师范大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10166"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.210224+08	2026-10-19 23:20:50.886046+08	t	\N
215	锦州医科大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10160"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.211406+08	2026-10-19 23:20:50.886046+08	t	\N
216	大连医科大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10161"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.212627+08	2026-10-19 23:20:50.886046+08	t	\N
217	东北财经大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10173"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.213694+08	2026-10-19 23:20:50.886046+08	t	\N
218	大连交通大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10150"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.214831+08	2026-10-19 23:20:50.886046+08	t	\N
219	大连海事大学	211	辽宁	\N	\N	\N	["yz_dwdm:10151"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.21594+08	2026-10-19 23:20:50.886046+08	t	\N
220	大连海洋大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10158"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.217599+08	2026-10-19 23:20:50.886046+08	t	\N
221	沈阳建筑大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10153"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.219499+08	2026-10-19 23:20:50.886046+08	t	\N
222	大连民族大学	双非	辽宁	\N	\N	\N	["yz_dwdm:12026"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.220581+08	2026-10-19 23:20:50.886046+08	t	\N
223	大连外国语大学	双非	辽宁	\N	\N	\N	["yz_dwdm:10172"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.221653+08	2026-10-19 23:20:50.886046+08	t	\N
224	吉林大学	985	吉林	\N	\N	\N	["yz_dwdm:10183"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.222799+08	2026-10-19 23:20:50.886046+08	t	\N
225	延边大学	211	吉林	\N	\N	\N	["yz_dwdm:10184"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.223875+08	2026-10-19 23:20:50.886046+08	t	\N
226	长春理工大学	双非	吉林	\N	\N	\N	["yz_dwdm:10186"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.224926+08	2026-10-19 23:20:50.886046+08	t	\N
227	东北电力大学	双非	吉林	\N	\N	\N	["yz_dwdm:10188"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.225968+08	2026-10-19 23:20:50.886046+08	t	\N
228	长春工业大学	双非	吉林	\N	\N	\N	["yz_dwdm:10190"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.227066+08	2026-10-19 23:20:50.886046+08	t	\N
229	吉林建筑大学	双非	吉林	\N	\N	\N	["yz_dwdm:10191"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.228762+08	2026-10-19 23:20:50.886046+08	t	\N
230	吉林化工大学	双非	吉林	\N	\N	\N	["yz_dwdm:10192"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.229855+08	2026-10-19 23:20:50.886046+08	t	\N
231	吉林农业大学	双非	吉林	\N	\N	\N	["yz_dwdm:10193"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.230909+08	2026-10-19 23:20:50.886046+08	t	\N
232	长春中医药大学	双非	吉林	\N	\N	\N	["yz_dwdm:10199"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.231873+08	2026-10-19 23:20:50.886046+08	t	\N
233	东北师范大学	211	吉林	\N	\N	\N	["yz_dwdm:10200"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.233043+08	2026-10-19 23:20:50.886046+08	t	\N
234	吉林工程技术师范学院	双非	吉林	\N	\N	\N	["yz_dwdm:10204"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.234187+08	2026-10-19 23:20:50.886046+08	t	\N
235	吉林体育学院	双非	吉林	\N	\N	\N	["yz_dwdm:10208"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.235273+08	2026-10-19 23:20:50.886046+08	t	\N
236	吉林艺术学院	双非	吉林	\N	\N	\N	["yz_dwdm:10209"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.236342+08	2026-10-19 23:20:50.886046+08	t	\N
237	长春工程学院	双非	吉林	\N	\N	\N	["yz_dwdm:11437"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.237415+08	2026-10-19 23:20:50.886046+08	t	\N
238	中共吉林省委党校(吉林省行政学院)	双非	吉林	\N	\N	\N	["yz_dwdm:89622"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.239919+08	2026-10-19 23:20:50.886046+08	t	\N
239	吉林师范大学	双非	吉林	\N	\N	\N	["yz_dwdm:10203"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.241146+08	2026-10-19 23:20:50.886046+08	t	\N
240	吉林财经大学	双非	吉林	\N	\N	\N	["yz_dwdm:10207"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.242281+08	2026-10-19 23:20:50.886046+08	t	\N
241	吉林外国语大学	双非	吉林	\N	\N	\N	["yz_dwdm:10964"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.244871+08	2026-10-19 23:20:50.886046+08	t	\N
242	长春师范大学	双非	吉林	\N	\N	\N	["yz_dwdm:10205"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.245936+08	2026-10-19 23:20:50.886046+08	t	\N
243	空军航空大学	双非	吉林	\N	\N	\N	["yz_dwdm:92021"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.247119+08	2026-10-19 23:20:50.886046+08	t	\N
244	黑龙江大学	双非	黑龙江	\N	\N	\N	["yz_dwdm:10212"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.248364+08	2026-10-19 23:20:50.886046+08	t	\N
245	哈尔滨工业大学	985	黑龙江	\N	\N	\N	["yz_dwdm:10213"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.250745+08	2026-10-19 23:20:50.886046+08	t	\N
246	哈尔滨理工大学	双非	黑龙江	\N	\N	\N	["yz_dwdm:10214"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.251939+08	2026-10-19 23:20:50.886046+08	t	\N
247	哈尔滨工程大学	211	黑龙江	\N	\N	\N	["yz_dwdm:10217"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.253075+08	2026-10-19 23:20:50.886046+08	t	\N
248	黑龙江科技大学	双非	黑龙江	\N	\N	\N	["yz_dwdm:10219"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.25422+08	2026-10-19 23:20:50.886046+08	t	\N
249	东北石油大学	双非	黑龙江	\N	\N	\N	["yz_dwdm:10220"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.255374+08	2026-10-19 23:20:50.886046+08	t	\N
250	佳木斯大学	双非	黑龙江	\N	\N	\N	["yz_dwdm:10222"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.256515+08	2026-10-19 23:20:50.886046+08	t	\N
251	黑龙江八一农垦大学	双非	黑龙江	\N	\N	\N	["yz_dwdm:10223"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.257639+08	2026-10-19 23:20:50.886046+08	t	\N
252	东北农业大学	211	黑龙江	\N	\N	\N	["yz_dwdm:10224"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.258593+08	2026-10-19 23:20:50.886046+08	t	\N
253	东北林业大学	211	黑龙江	\N	\N	\N	["yz_dwdm:10225"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.259589+08	2026-10-19 23:20:50.886046+08	t	\N
254	牡丹江师范学院	双非	黑龙江	\N	\N	\N	["yz_dwdm:10233"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.262069+08	2026-10-19 23:20:50.886046+08	t	\N
256	哈尔滨体育学院	双非	黑龙江	\N	\N	\N	["yz_dwdm:10242"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.265909+08	2026-10-19 23:20:50.886046+08	t	\N
257	齐齐哈尔医学院	双非	黑龙江	\N	\N	\N	["yz_dwdm:11230"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.267644+08	2026-10-19 23:20:50.886046+08	t	\N
258	黑龙江东方学院	双非	黑龙江	\N	\N	\N	["yz_dwdm:11446"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.268884+08	2026-10-19 23:20:50.886046+08	t	\N
259	黑龙江工程学院	双非	黑龙江	\N	\N	\N	["yz_dwdm:11802"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.270083+08	2026-10-19 23:20:50.886046+08	t	\N
260	哈尔滨音乐学院	双非	黑龙江	\N	\N	\N	["yz_dwdm:14560"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.271201+08	2026-10-19 23:20:50.886046+08	t	\N
261	黑龙江省中医药科学院	双非	黑龙江	\N	\N	\N	["yz_dwdm:87801"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.272386+08	2026-10-19 23:20:50.886046+08	t	\N
262	黑龙江省社会科学院	双非	黑龙江	\N	\N	\N	["yz_dwdm:87802"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.27355+08	2026-10-19 23:20:50.886046+08	t	\N
263	黑龙江省科学院石油化学研究院	双非	黑龙江	\N	\N	\N	["yz_dwdm:87804"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.275063+08	2026-10-19 23:20:50.886046+08	t	\N
264	机械科学研究总院(哈尔滨焊接研究所)	双非	黑龙江	\N	\N	\N	["yz_dwdm:82706"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.276139+08	2026-10-19 23:20:50.886046+08	t	\N
265	中国地震局工程力学研究所	双非	黑龙江	\N	\N	\N	["yz_dwdm:85406"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.277971+08	2026-10-19 23:20:50.886046+08	t	\N
266	中国舰船研究院(哈尔滨船舶锅炉涡轮机研究所)	双非	黑龙江	\N	\N	\N	["yz_dwdm:86209"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.279698+08	2026-10-19 23:20:50.886046+08	t	\N
267	中国航空研究院(627所)	双非	黑龙江	\N	\N	\N	["yz_dwdm:82928"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.280929+08	2026-10-19 23:20:50.886046+08	t	\N
268	黑龙江中医药大学	双非	黑龙江	\N	\N	\N	["yz_dwdm:10228"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.282265+08	2026-10-19 23:20:50.886046+08	t	\N
269	中共黑龙江省委党校	双非	黑龙江	\N	\N	\N	["yz_dwdm:89623"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.283948+08	2026-10-19 23:20:50.886046+08	t	\N
270	哈尔滨师范大学	双非	黑龙江	\N	\N	\N	["yz_dwdm:10231"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.285288+08	2026-10-19 23:20:50.886046+08	t	\N
271	哈尔滨医科大学	双非	黑龙江	\N	\N	\N	["yz_dwdm:10226"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.286411+08	2026-10-19 23:20:50.886046+08	t	\N
272	牡丹江医科大学	双非	黑龙江	\N	\N	\N	["yz_dwdm:10229"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.287555+08	2026-10-19 23:20:50.886046+08	t	\N
273	复旦大学	985	上海	\N	\N	\N	["yz_dwdm:10246"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.288743+08	2026-10-19 23:20:50.886046+08	t	\N
274	同济大学	985	上海	\N	\N	\N	["yz_dwdm:10247"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.289855+08	2026-10-19 23:20:50.886046+08	t	\N
275	上海交通大学	985	上海	\N	\N	\N	["yz_dwdm:10248"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.290929+08	2026-10-19 23:20:50.886046+08	t	\N
276	华东理工大学	211	上海	\N	\N	\N	["yz_dwdm:10251"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.292119+08	2026-10-19 23:20:50.886046+08	t	\N
277	上海理工大学	双非	上海	\N	\N	\N	["yz_dwdm:10252"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.293204+08	2026-10-19 23:20:50.886046+08	t	\N
278	上海海事大学	双非	上海	\N	\N	\N	["yz_dwdm:10254"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.296203+08	2026-10-19 23:20:50.886046+08	t	\N
279	东华大学	211	上海	\N	\N	\N	["yz_dwdm:10255"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.297385+08	2026-10-19 23:20:50.886046+08	t	\N
280	上海电力大学	双非	上海	\N	\N	\N	["yz_dwdm:10256"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.298478+08	2026-10-19 23:20:50.886046+08	t	\N
281	上海应用技术大学	双非	上海	\N	\N	\N	["yz_dwdm:10259"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.299512+08	2026-10-19 23:20:50.886046+08	t	\N
282	上海海洋大学	双一流	上海	\N	\N	\N	["yz_dwdm:10264"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.30051+08	2026-10-19 23:20:50.886046+08	t	\N
283	上海海关学院	双非	上海	\N	\N	\N	["yz_dwdm:10274"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.301502+08	2026-10-19 23:20:50.886046+08	t	\N
285	上海戏剧学院	双非	上海	\N	\N	\N	["yz_dwdm:10279"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.30361+08	2026-10-19 23:20:50.886046+08	t	\N
286	上海立信会计金融学院	双非	上海	\N	\N	\N	["yz_dwdm:11047"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.305734+08	2026-10-19 23:20:50.886046+08	t	\N
287	上海电机学院	双非	上海	\N	\N	\N	["yz_dwdm:11458"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.306793+08	2026-10-19 23:20:50.886046+08	t	\N
288	上海杉达学院	双非	上海	\N	\N	\N	["yz_dwdm:11833"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.307921+08	2026-10-19 23:20:50.886046+08	t	\N
289	上海政法学院	双非	上海	\N	\N	\N	["yz_dwdm:11835"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.309075+08	2026-10-19 23:20:50.886046+08	t	\N
290	上海商学院	双非	上海	\N	\N	\N	["yz_dwdm:12050"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.310154+08	2026-10-19 23:20:50.886046+08	t	\N
291	上海国家会计学院	双非	上海	\N	\N	\N	["yz_dwdm:80402"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.311322+08	2026-10-19 23:20:50.886046+08	t	\N
292	上海社会科学院	双非	上海	\N	\N	\N	["yz_dwdm:87903"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.312531+08	2026-10-19 23:20:50.886046+08	t	\N
293	机械科学研究总院(上海材料研究所)	双非	上海	\N	\N	\N	["yz_dwdm:82707"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.327643+08	2026-10-19 23:20:50.886046+08	t	\N
294	上海船舶运输科学研究所	双非	上海	\N	\N	\N	["yz_dwdm:83901"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.328778+08	2026-10-19 23:20:50.886046+08	t	\N
295	电信科学技术研究院(第一研究所)	双非	上海	\N	\N	\N	["yz_dwdm:84002"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.330304+08	2026-10-19 23:20:50.886046+08	t	\N
296	上海生物制品研究所	双非	上海	\N	\N	\N	["yz_dwdm:84505"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.331904+08	2026-10-19 23:20:50.886046+08	t	\N
297	中国舰船研究院(上海船舶设备研究所)	双非	上海	\N	\N	\N	["yz_dwdm:86207"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.334376+08	2026-10-19 23:20:50.886046+08	t	\N
298	中国舰船研究院(上海船用柴油机研究所)	双非	上海	\N	\N	\N	["yz_dwdm:86208"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.337174+08	2026-10-19 23:20:50.886046+08	t	\N
299	中国舰船研究院(上海船舶电子设备研究所)	双非	上海	\N	\N	\N	["yz_dwdm:86219"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.33841+08	2026-10-19 23:20:50.886046+08	t	\N
300	中国航空研究院(640所)	双非	上海	\N	\N	\N	["yz_dwdm:82937"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.340811+08	2026-10-19 23:20:50.886046+08	t	\N
301	上海航天技术研究院	双非	上海	\N	\N	\N	["yz_dwdm:83285"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.343+08	2026-10-19 23:20:50.886046+08	t	\N
302	上海化工研究院	双非	上海	\N	\N	\N	["yz_dwdm:83502"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.345654+08	2026-10-19 23:20:50.886046+08	t	\N
303	中国舰船研究院(中国船舶及海洋工程设计研究院)	双非	上海	\N	\N	\N	["yz_dwdm:86206"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.347769+08	2026-10-19 23:20:50.886046+08	t	\N
304	上海国际问题研究院	双非	上海	\N	\N	\N	["yz_dwdm:87902"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.350163+08	2026-10-19 23:20:50.886046+08	t	\N
305	上海中医药大学	双非	上海	\N	\N	\N	["yz_dwdm:10268"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.352541+08	2026-10-19 23:20:50.886046+08	t	\N
306	上海师范大学	双非	上海	\N	\N	\N	["yz_dwdm:10270"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.356225+08	2026-10-19 23:20:50.886046+08	t	\N
307	上海外国语大学	211	上海	\N	\N	\N	["yz_dwdm:10271"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.358387+08	2026-10-19 23:20:50.886046+08	t	\N
308	上海财经大学	211	上海	\N	\N	\N	["yz_dwdm:10272"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.361783+08	2026-10-19 23:20:50.886046+08	t	\N
309	中国医药工业研究总院	双非	上海	\N	\N	\N	["yz_dwdm:85901"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.364151+08	2026-10-19 23:20:50.886046+08	t	\N
310	上海第二工业大学	双非	上海	\N	\N	\N	["yz_dwdm:12044"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.366441+08	2026-10-19 23:20:50.886046+08	t	\N
311	上海科技大学	双一流	上海	\N	\N	\N	["yz_dwdm:14423"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.368795+08	2026-10-19 23:20:50.886046+08	t	\N
312	华东师范大学	985	上海	\N	\N	\N	["yz_dwdm:10269"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.370988+08	2026-10-19 23:20:50.886046+08	t	\N
313	华东政法大学	双非	上海	\N	\N	\N	["yz_dwdm:10276"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.373122+08	2026-10-19 23:20:50.886046+08	t	\N
314	上海对外经贸大学	双非	上海	\N	\N	\N	["yz_dwdm:10273"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.375229+08	2026-10-19 23:20:50.886046+08	t	\N
315	上海工程技术大学	双非	上海	\N	\N	\N	["yz_dwdm:10856"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.377812+08	2026-10-19 23:20:50.886046+08	t	\N
316	上海核工程研究设计院	双非	上海	\N	\N	\N	["yz_dwdm:82805"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.379428+08	2026-10-19 23:20:50.886046+08	t	\N
317	南京大学	985	江苏	\N	\N	\N	["yz_dwdm:10284"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.380602+08	2026-10-19 23:20:50.886046+08	t	\N
318	苏州大学	211	江苏	\N	\N	\N	["yz_dwdm:10285"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.382854+08	2026-10-19 23:20:50.886046+08	t	\N
319	东南大学	985	江苏	\N	\N	\N	["yz_dwdm:10286"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.383897+08	2026-10-19 23:20:50.886046+08	t	\N
320	南京航空航天大学	211	江苏	\N	\N	\N	["yz_dwdm:10287"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.384956+08	2026-10-19 23:20:50.886046+08	t	\N
321	南京理工大学	211	江苏	\N	\N	\N	["yz_dwdm:10288"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.387287+08	2026-10-19 23:20:50.886046+08	t	\N
322	江苏科技大学	双非	江苏	\N	\N	\N	["yz_dwdm:10289"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.388406+08	2026-10-19 23:20:50.886046+08	t	\N
323	中国矿业大学	211	江苏	\N	\N	\N	["yz_dwdm:10290"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.389426+08	2026-10-19 23:20:50.886046+08	t	\N
324	南京工业大学	双非	江苏	\N	\N	\N	["yz_dwdm:10291"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.390668+08	2026-10-19 23:20:50.886046+08	t	\N
325	常州大学	双非	江苏	\N	\N	\N	["yz_dwdm:10292"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.391762+08	2026-10-19 23:20:50.886046+08	t	\N
326	南京邮电大学	双一流	江苏	\N	\N	\N	["yz_dwdm:10293"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.392755+08	2026-10-19 23:20:50.886046+08	t	\N
327	盐城工学院	双非	江苏	\N	\N	\N	["yz_dwdm:10305"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.393795+08	2026-10-19 23:20:50.886046+08	t	\N
328	淮阴师范学院	双非	江苏	\N	\N	\N	["yz_dwdm:10323"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.395677+08	2026-10-19 23:20:50.886046+08	t	\N
329	盐城师范学院	双非	江苏	\N	\N	\N	["yz_dwdm:10324"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.397713+08	2026-10-19 23:20:50.886046+08	t	\N
330	江苏警官学院	双非	江苏	\N	\N	\N	["yz_dwdm:10329"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.399084+08	2026-10-19 23:20:50.886046+08	t	\N
331	南京体育学院	双非	江苏	\N	\N	\N	["yz_dwdm:10330"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.400223+08	2026-10-19 23:20:50.886046+08	t	\N
332	南京艺术学院	双非	江苏	\N	\N	\N	["yz_dwdm:10331"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.401823+08	2026-10-19 23:20:50.886046+08	t	\N
333	苏州工学院	双非	江苏	\N	\N	\N	["yz_dwdm:10333"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.403025+08	2026-10-19 23:20:50.886046+08	t	\N
334	常州工学院	双非	江苏	\N	\N	\N	["yz_dwdm:11055"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.404254+08	2026-10-19 23:20:50.886046+08	t	\N
335	南京工程学院	双非	江苏	\N	\N	\N	["yz_dwdm:11276"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.405806+08	2026-10-19 23:20:50.886046+08	t	\N
336	南京晓庄学院	双非	江苏	\N	\N	\N	["yz_dwdm:11460"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.406784+08	2026-10-19 23:20:50.886046+08	t	\N
534	湖北医药学院	双非	湖北	\N	\N	\N	["yz_dwdm:10929"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.734519+08	2026-10-19 23:20:50.886046+08	t	\N
337	中国舰船研究院(江苏自动化研究所)	双非	江苏	\N	\N	\N	["yz_dwdm:86210"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.407944+08	2026-10-19 23:20:50.886046+08	t	\N
338	江苏省中国科学院植物研究所	双非	江苏	\N	\N	\N	["yz_dwdm:88001"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.40904+08	2026-10-19 23:20:50.886046+08	t	\N
339	江苏省血吸虫病防治研究所	双非	江苏	\N	\N	\N	["yz_dwdm:88002"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.410045+08	2026-10-19 23:20:50.886046+08	t	\N
340	网络空间部队第五十六研究所	双非	江苏	\N	\N	\N	["yz_dwdm:92103"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.410999+08	2026-10-19 23:20:50.886046+08	t	\N
341	国网电力科学研究院	双非	江苏	\N	\N	\N	["yz_dwdm:82303"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.412142+08	2026-10-19 23:20:50.886046+08	t	\N
342	南京水利科学研究院	双非	江苏	\N	\N	\N	["yz_dwdm:82306"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.413296+08	2026-10-19 23:20:50.886046+08	t	\N
343	中国航空研究院(609所)	双非	江苏	\N	\N	\N	["yz_dwdm:82927"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.414491+08	2026-10-19 23:20:50.886046+08	t	\N
344	中国舰船研究院(中国船舶科学研究中心)	双非	江苏	\N	\N	\N	["yz_dwdm:86205"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.415604+08	2026-10-19 23:20:50.886046+08	t	\N
345	江苏大学	双非	江苏	\N	\N	\N	["yz_dwdm:10299"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.416677+08	2026-10-19 23:20:50.886046+08	t	\N
346	江苏师范大学	双非	江苏	\N	\N	\N	["yz_dwdm:10320"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.41778+08	2026-10-19 23:20:50.886046+08	t	\N
347	江苏理工学院	双非	江苏	\N	\N	\N	["yz_dwdm:11463"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.418845+08	2026-10-19 23:20:50.886046+08	t	\N
348	江苏海洋大学	双非	江苏	\N	\N	\N	["yz_dwdm:11641"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.419896+08	2026-10-19 23:20:50.886046+08	t	\N
349	中共江苏省委党校	双非	江苏	\N	\N	\N	["yz_dwdm:89632"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.420984+08	2026-10-19 23:20:50.886046+08	t	\N
350	中国药科大学	211	江苏	\N	\N	\N	["yz_dwdm:10316"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.422191+08	2026-10-19 23:20:50.886046+08	t	\N
351	苏州科技大学	双非	江苏	\N	\N	\N	["yz_dwdm:10332"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.423338+08	2026-10-19 23:20:50.886046+08	t	\N
352	金陵科技学院	双非	江苏	\N	\N	\N	["yz_dwdm:13573"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.424312+08	2026-10-19 23:20:50.886046+08	t	\N
353	南京师范大学	211	江苏	\N	\N	\N	["yz_dwdm:10319"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.425406+08	2026-10-19 23:20:50.886046+08	t	\N
354	南京农业大学	211	江苏	\N	\N	\N	["yz_dwdm:10307"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.426663+08	2026-10-19 23:20:50.886046+08	t	\N
355	南京林业大学	双一流	江苏	\N	\N	\N	["yz_dwdm:10298"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.431316+08	2026-10-19 23:20:50.886046+08	t	\N
356	南京医科大学	双非	江苏	\N	\N	\N	["yz_dwdm:10312"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.43291+08	2026-10-19 23:20:50.886046+08	t	\N
357	徐州医科大学	双非	江苏	\N	\N	\N	["yz_dwdm:10313"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.433948+08	2026-10-19 23:20:50.886046+08	t	\N
358	南京中医药大学	双非	江苏	\N	\N	\N	["yz_dwdm:10315"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.435442+08	2026-10-19 23:20:50.886046+08	t	\N
359	南京财经大学	双非	江苏	\N	\N	\N	["yz_dwdm:10327"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.436534+08	2026-10-19 23:20:50.886046+08	t	\N
360	南京信息工程大学	双一流	江苏	\N	\N	\N	["yz_dwdm:10300"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.439131+08	2026-10-19 23:20:50.886046+08	t	\N
361	徐州工程学院	双非	江苏	\N	\N	\N	["yz_dwdm:11998"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.440277+08	2026-10-19 23:20:50.886046+08	t	\N
362	陆军工程大学	双非	江苏	\N	\N	\N	["yz_dwdm:92004"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.441661+08	2026-10-19 23:20:50.886046+08	t	\N
363	浙江大学	985	浙江	\N	\N	\N	["yz_dwdm:10335"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.442777+08	2026-10-19 23:20:50.886046+08	t	\N
364	杭州电子科技大学	双非	浙江	\N	\N	\N	["yz_dwdm:10336"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.444041+08	2026-10-19 23:20:50.886046+08	t	\N
365	浙江工业大学	双非	浙江	\N	\N	\N	["yz_dwdm:10337"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.445278+08	2026-10-19 23:20:50.886046+08	t	\N
366	浙江理工大学	双非	浙江	\N	\N	\N	["yz_dwdm:10338"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.446455+08	2026-10-19 23:20:50.886046+08	t	\N
367	浙江海洋大学	双非	浙江	\N	\N	\N	["yz_dwdm:10340"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.447607+08	2026-10-19 23:20:50.886046+08	t	\N
368	浙江农林大学	双非	浙江	\N	\N	\N	["yz_dwdm:10341"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.448787+08	2026-10-19 23:20:50.886046+08	t	\N
369	温州医科大学	双非	浙江	\N	\N	\N	["yz_dwdm:10343"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.450169+08	2026-10-19 23:20:50.886046+08	t	\N
370	浙江中医药大学	双非	浙江	\N	\N	\N	["yz_dwdm:10344"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.451237+08	2026-10-19 23:20:50.886046+08	t	\N
371	浙江师范大学	双非	浙江	\N	\N	\N	["yz_dwdm:10345"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.45234+08	2026-10-19 23:20:50.886046+08	t	\N
372	杭州师范大学	双非	浙江	\N	\N	\N	["yz_dwdm:10346"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.453328+08	2026-10-19 23:20:50.886046+08	t	\N
373	台州学院	双非	浙江	\N	\N	\N	["yz_dwdm:10350"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.454835+08	2026-10-19 23:20:50.886046+08	t	\N
374	丽水学院	双非	浙江	\N	\N	\N	["yz_dwdm:10352"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.455954+08	2026-10-19 23:20:50.886046+08	t	\N
375	中国美术学院	双非	浙江	\N	\N	\N	["yz_dwdm:10355"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.45718+08	2026-10-19 23:20:50.886046+08	t	\N
376	浙江万里学院	双非	浙江	\N	\N	\N	["yz_dwdm:10876"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.459004+08	2026-10-19 23:20:50.886046+08	t	\N
377	宁波工程学院	双非	浙江	\N	\N	\N	["yz_dwdm:11058"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.460056+08	2026-10-19 23:20:50.886046+08	t	\N
378	浙江警察学院	双非	浙江	\N	\N	\N	["yz_dwdm:11483"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.461098+08	2026-10-19 23:20:50.886046+08	t	\N
379	衢州学院	双非	浙江	\N	\N	\N	["yz_dwdm:11488"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.46228+08	2026-10-19 23:20:50.886046+08	t	\N
380	浙江传媒学院	双非	浙江	\N	\N	\N	["yz_dwdm:11647"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.463408+08	2026-10-19 23:20:50.886046+08	t	\N
381	浙江树人学院	双非	浙江	\N	\N	\N	["yz_dwdm:11842"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.46444+08	2026-10-19 23:20:50.886046+08	t	\N
382	浙江越秀外国语学院	双非	浙江	\N	\N	\N	["yz_dwdm:12792"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.46564+08	2026-10-19 23:20:50.886046+08	t	\N
383	自然资源部第二海洋研究所	双非	浙江	\N	\N	\N	["yz_dwdm:85302"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.466773+08	2026-10-19 23:20:50.886046+08	t	\N
384	中国舰船研究院(杭州应用声学研究所)	双非	浙江	\N	\N	\N	["yz_dwdm:86204"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.467837+08	2026-10-19 23:20:50.886046+08	t	\N
385	浙江工商大学	双非	浙江	\N	\N	\N	["yz_dwdm:10353"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.468989+08	2026-10-19 23:20:50.886046+08	t	\N
386	浙江科技大学	双非	浙江	\N	\N	\N	["yz_dwdm:11057"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.470137+08	2026-10-19 23:20:50.886046+08	t	\N
387	中国计量大学	双非	浙江	\N	\N	\N	["yz_dwdm:10356"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.471342+08	2026-10-19 23:20:50.886046+08	t	\N
388	浙大宁波理工学院	双非	浙江	\N	\N	\N	["yz_dwdm:13022"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.472454+08	2026-10-19 23:20:50.886046+08	t	\N
389	湖州师范大学	双非	浙江	\N	\N	\N	["yz_dwdm:10347"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.473678+08	2026-10-19 23:20:50.886046+08	t	\N
390	浙江财经大学	双非	浙江	\N	\N	\N	["yz_dwdm:11482"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.474798+08	2026-10-19 23:20:50.886046+08	t	\N
605	广州体育学院	双非	广东	\N	\N	\N	["yz_dwdm:10585"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.825043+08	2026-10-19 23:20:50.886046+08	t	\N
391	浙江外国语学院	双非	浙江	\N	\N	\N	["yz_dwdm:14275"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.475991+08	2026-10-19 23:20:50.886046+08	t	\N
392	安徽大学	211	安徽	\N	\N	\N	["yz_dwdm:10357"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.477007+08	2026-10-19 23:20:50.886046+08	t	\N
393	中国科学技术大学	985	安徽	\N	\N	\N	["yz_dwdm:10358"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.478057+08	2026-10-19 23:20:50.886046+08	t	\N
394	合肥工业大学	211	安徽	\N	\N	\N	["yz_dwdm:10359"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.479102+08	2026-10-19 23:20:50.886046+08	t	\N
395	安徽工业大学	双非	安徽	\N	\N	\N	["yz_dwdm:10360"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.481292+08	2026-10-19 23:20:50.886046+08	t	\N
396	安徽理工大学	双非	安徽	\N	\N	\N	["yz_dwdm:10361"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.482405+08	2026-10-19 23:20:50.886046+08	t	\N
397	安徽工程大学	双非	安徽	\N	\N	\N	["yz_dwdm:10363"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.483548+08	2026-10-19 23:20:50.886046+08	t	\N
398	安徽农业大学	双非	安徽	\N	\N	\N	["yz_dwdm:10364"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.484731+08	2026-10-19 23:20:50.886046+08	t	\N
399	安徽医科大学	双非	安徽	\N	\N	\N	["yz_dwdm:10366"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.485766+08	2026-10-19 23:20:50.886046+08	t	\N
400	蚌埠医科大学	双非	安徽	\N	\N	\N	["yz_dwdm:10367"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.48684+08	2026-10-19 23:20:50.886046+08	t	\N
401	皖南医科大学	双非	安徽	\N	\N	\N	["yz_dwdm:10368"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.488034+08	2026-10-19 23:20:50.886046+08	t	\N
402	皖西学院	双非	安徽	\N	\N	\N	["yz_dwdm:10376"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.490515+08	2026-10-19 23:20:50.886046+08	t	\N
403	滁州学院	双非	安徽	\N	\N	\N	["yz_dwdm:10377"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.491805+08	2026-10-19 23:20:50.886046+08	t	\N
404	宿州学院	双非	安徽	\N	\N	\N	["yz_dwdm:10379"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.49288+08	2026-10-19 23:20:50.886046+08	t	\N
405	合肥师范学院	双非	安徽	\N	\N	\N	["yz_dwdm:14098"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.495642+08	2026-10-19 23:20:50.886046+08	t	\N
406	马鞍山矿山研究院	双非	安徽	\N	\N	\N	["yz_dwdm:82604"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.498633+08	2026-10-19 23:20:50.886046+08	t	\N
407	安徽中医药大学	双非	安徽	\N	\N	\N	["yz_dwdm:10369"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.500336+08	2026-10-19 23:20:50.886046+08	t	\N
408	安徽师范大学	双非	安徽	\N	\N	\N	["yz_dwdm:10370"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.501363+08	2026-10-19 23:20:50.886046+08	t	\N
409	安徽财经大学	双非	安徽	\N	\N	\N	["yz_dwdm:10378"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.502353+08	2026-10-19 23:20:50.886046+08	t	\N
410	安徽建筑大学	双非	安徽	\N	\N	\N	["yz_dwdm:10878"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.503637+08	2026-10-19 23:20:50.886046+08	t	\N
411	安徽科技工程大学	双非	安徽	\N	\N	\N	["yz_dwdm:10879"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.505339+08	2026-10-19 23:20:50.886046+08	t	\N
412	阜阳师范大学	双非	安徽	\N	\N	\N	["yz_dwdm:10371"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.506536+08	2026-10-19 23:20:50.886046+08	t	\N
413	安庆师范大学	双非	安徽	\N	\N	\N	["yz_dwdm:10372"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.507743+08	2026-10-19 23:20:50.886046+08	t	\N
414	淮北师范大学	双非	安徽	\N	\N	\N	["yz_dwdm:10373"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.508905+08	2026-10-19 23:20:50.886046+08	t	\N
415	厦门大学	985	福建	\N	\N	\N	["yz_dwdm:10384"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.512007+08	2026-10-19 23:20:50.886046+08	t	\N
416	华侨大学	双非	福建	\N	\N	\N	["yz_dwdm:10385"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.513594+08	2026-10-19 23:20:50.886046+08	t	\N
417	福州大学	211	福建	\N	\N	\N	["yz_dwdm:10386"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.51485+08	2026-10-19 23:20:50.886046+08	t	\N
418	福建理工大学	双非	福建	\N	\N	\N	["yz_dwdm:10388"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.517141+08	2026-10-19 23:20:50.886046+08	t	\N
419	福建农林大学	双非	福建	\N	\N	\N	["yz_dwdm:10389"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.519558+08	2026-10-19 23:20:50.886046+08	t	\N
420	集美大学	双非	福建	\N	\N	\N	["yz_dwdm:10390"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.525697+08	2026-10-19 23:20:50.886046+08	t	\N
421	福建医科大学	双非	福建	\N	\N	\N	["yz_dwdm:10392"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.526697+08	2026-10-19 23:20:50.886046+08	t	\N
422	福建中医药大学	双非	福建	\N	\N	\N	["yz_dwdm:10393"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.52952+08	2026-10-19 23:20:50.886046+08	t	\N
423	福建师范大学	双非	福建	\N	\N	\N	["yz_dwdm:10394"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.530784+08	2026-10-19 23:20:50.886046+08	t	\N
424	闽江大学	双非	福建	\N	\N	\N	["yz_dwdm:10395"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.533071+08	2026-10-19 23:20:50.886046+08	t	\N
425	武夷学院	双非	福建	\N	\N	\N	["yz_dwdm:10397"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.537782+08	2026-10-19 23:20:50.886046+08	t	\N
426	宁德师范学院	双非	福建	\N	\N	\N	["yz_dwdm:10398"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.539089+08	2026-10-19 23:20:50.886046+08	t	\N
427	泉州师范学院	双非	福建	\N	\N	\N	["yz_dwdm:10399"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.540176+08	2026-10-19 23:20:50.886046+08	t	\N
428	厦门理工学院	双非	福建	\N	\N	\N	["yz_dwdm:11062"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.541217+08	2026-10-19 23:20:50.886046+08	t	\N
429	三明学院	双非	福建	\N	\N	\N	["yz_dwdm:11311"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.54236+08	2026-10-19 23:20:50.886046+08	t	\N
430	龙岩学院	双非	福建	\N	\N	\N	["yz_dwdm:11312"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.547665+08	2026-10-19 23:20:50.886046+08	t	\N
431	莆田学院	双非	福建	\N	\N	\N	["yz_dwdm:11498"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.54875+08	2026-10-19 23:20:50.886046+08	t	\N
432	福建江夏学院	双非	福建	\N	\N	\N	["yz_dwdm:13763"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.549825+08	2026-10-19 23:20:50.886046+08	t	\N
433	厦门国家会计学院	双非	福建	\N	\N	\N	["yz_dwdm:80403"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.550925+08	2026-10-19 23:20:50.886046+08	t	\N
434	自然资源部第三海洋研究所	双非	福建	\N	\N	\N	["yz_dwdm:85303"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.552065+08	2026-10-19 23:20:50.886046+08	t	\N
435	闽南师范大学	双非	福建	\N	\N	\N	["yz_dwdm:10402"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.553181+08	2026-10-19 23:20:50.886046+08	t	\N
436	南昌大学	211	江西	\N	\N	\N	["yz_dwdm:10403"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.554432+08	2026-10-19 23:20:50.886046+08	t	\N
437	华东交通大学	双非	江西	\N	\N	\N	["yz_dwdm:10404"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.555457+08	2026-10-19 23:20:50.886046+08	t	\N
438	东华理工大学	双非	江西	\N	\N	\N	["yz_dwdm:10405"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.556584+08	2026-10-19 23:20:50.886046+08	t	\N
439	南昌航空大学	双非	江西	\N	\N	\N	["yz_dwdm:10406"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.557719+08	2026-10-19 23:20:50.886046+08	t	\N
440	江西理工大学	双非	江西	\N	\N	\N	["yz_dwdm:10407"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.559523+08	2026-10-19 23:20:50.886046+08	t	\N
441	景德镇陶瓷大学	双非	江西	\N	\N	\N	["yz_dwdm:10408"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.564445+08	2026-10-19 23:20:50.886046+08	t	\N
442	江西农业大学	双非	江西	\N	\N	\N	["yz_dwdm:10410"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.565825+08	2026-10-19 23:20:50.886046+08	t	\N
443	江西中医药大学	双非	江西	\N	\N	\N	["yz_dwdm:10412"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.567091+08	2026-10-19 23:20:50.886046+08	t	\N
444	赣南医科大学	双非	江西	\N	\N	\N	["yz_dwdm:10413"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.56823+08	2026-10-19 23:20:50.886046+08	t	\N
445	江西师范大学	双非	江西	\N	\N	\N	["yz_dwdm:10414"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.569307+08	2026-10-19 23:20:50.886046+08	t	\N
446	上饶师范学院	双非	江西	\N	\N	\N	["yz_dwdm:10416"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.570399+08	2026-10-19 23:20:50.886046+08	t	\N
447	宜春学院	双非	江西	\N	\N	\N	["yz_dwdm:10417"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.571536+08	2026-10-19 23:20:50.886046+08	t	\N
448	九江学院	双非	江西	\N	\N	\N	["yz_dwdm:11843"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.572677+08	2026-10-19 23:20:50.886046+08	t	\N
449	陆军步兵学院	双非	江西	\N	\N	\N	["yz_dwdm:92006"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.573666+08	2026-10-19 23:20:50.886046+08	t	\N
450	中国航空研究院(602所)	双非	江西	\N	\N	\N	["yz_dwdm:82938"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.574732+08	2026-10-19 23:20:50.886046+08	t	\N
451	江西财经大学	双非	江西	\N	\N	\N	["yz_dwdm:10421"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.575706+08	2026-10-19 23:20:50.886046+08	t	\N
452	江西科技师范大学	双非	江西	\N	\N	\N	["yz_dwdm:11318"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.576792+08	2026-10-19 23:20:50.886046+08	t	\N
453	江西水利电力大学	双非	江西	\N	\N	\N	["yz_dwdm:11319"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.579468+08	2026-10-19 23:20:50.886046+08	t	\N
454	赣南师范大学	双非	江西	\N	\N	\N	["yz_dwdm:10418"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.580564+08	2026-10-19 23:20:50.886046+08	t	\N
455	山东大学	985	山东	\N	\N	\N	["yz_dwdm:10422"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.582968+08	2026-10-19 23:20:50.886046+08	t	\N
456	中国海洋大学	985	山东	\N	\N	\N	["yz_dwdm:10423"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.585936+08	2026-10-19 23:20:50.886046+08	t	\N
457	山东科技大学	双非	山东	\N	\N	\N	["yz_dwdm:10424"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.587647+08	2026-10-19 23:20:50.886046+08	t	\N
458	中国石油大学(华东)	211	山东	\N	\N	\N	["yz_dwdm:10425"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.588721+08	2026-10-19 23:20:50.886046+08	t	\N
459	青岛科技大学	双非	山东	\N	\N	\N	["yz_dwdm:10426"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.589699+08	2026-10-19 23:20:50.886046+08	t	\N
460	济南大学	双非	山东	\N	\N	\N	["yz_dwdm:10427"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.590779+08	2026-10-19 23:20:50.886046+08	t	\N
461	青岛理工大学	双非	山东	\N	\N	\N	["yz_dwdm:10429"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.591801+08	2026-10-19 23:20:50.886046+08	t	\N
462	山东建筑大学	双非	山东	\N	\N	\N	["yz_dwdm:10430"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.592759+08	2026-10-19 23:20:50.886046+08	t	\N
463	齐鲁工业大学	双非	山东	\N	\N	\N	["yz_dwdm:10431"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.594452+08	2026-10-19 23:20:50.886046+08	t	\N
464	山东理工大学	双非	山东	\N	\N	\N	["yz_dwdm:10433"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.595547+08	2026-10-19 23:20:50.886046+08	t	\N
465	济宁医学院	双非	山东	\N	\N	\N	["yz_dwdm:10443"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.597093+08	2026-10-19 23:20:50.886046+08	t	\N
466	德州学院	双非	山东	\N	\N	\N	["yz_dwdm:10448"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.59819+08	2026-10-19 23:20:50.886046+08	t	\N
467	山东航空学院	双非	山东	\N	\N	\N	["yz_dwdm:10449"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.599342+08	2026-10-19 23:20:50.886046+08	t	\N
468	泰山学院	双非	山东	\N	\N	\N	["yz_dwdm:10453"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.600429+08	2026-10-19 23:20:50.886046+08	t	\N
469	山东体育学院	双非	山东	\N	\N	\N	["yz_dwdm:10457"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.601631+08	2026-10-19 23:20:50.886046+08	t	\N
470	山东艺术学院	双非	山东	\N	\N	\N	["yz_dwdm:10458"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.602778+08	2026-10-19 23:20:50.886046+08	t	\N
471	枣庄学院	双非	山东	\N	\N	\N	["yz_dwdm:10904"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.604505+08	2026-10-19 23:20:50.886046+08	t	\N
472	山东工艺美术学院	双非	山东	\N	\N	\N	["yz_dwdm:10908"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.605599+08	2026-10-19 23:20:50.886046+08	t	\N
473	潍坊学院	双非	山东	\N	\N	\N	["yz_dwdm:11067"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.606799+08	2026-10-19 23:20:50.886046+08	t	\N
474	山东交通学院	双非	山东	\N	\N	\N	["yz_dwdm:11510"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.608027+08	2026-10-19 23:20:50.886046+08	t	\N
475	中国兵器科学研究院(山东非金属材料研究所)	双非	山东	\N	\N	\N	["yz_dwdm:83115"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.608974+08	2026-10-19 23:20:50.886046+08	t	\N
476	自然资源部第一海洋研究所	双非	山东	\N	\N	\N	["yz_dwdm:85301"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.610086+08	2026-10-19 23:20:50.886046+08	t	\N
477	山东农业大学	双非	山东	\N	\N	\N	["yz_dwdm:10434"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.611796+08	2026-10-19 23:20:50.886046+08	t	\N
478	山东第二医科大学	双非	山东	\N	\N	\N	["yz_dwdm:10438"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.612902+08	2026-10-19 23:20:50.886046+08	t	\N
479	山东第一医科大学	双非	山东	\N	\N	\N	["yz_dwdm:10439"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.614036+08	2026-10-19 23:20:50.886046+08	t	\N
480	山东医药大学	双非	山东	\N	\N	\N	["yz_dwdm:10440"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.615271+08	2026-10-19 23:20:50.886046+08	t	\N
481	山东中医药大学	双非	山东	\N	\N	\N	["yz_dwdm:10441"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.616437+08	2026-10-19 23:20:50.886046+08	t	\N
482	山东师范大学	双非	山东	\N	\N	\N	["yz_dwdm:10445"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.617694+08	2026-10-19 23:20:50.886046+08	t	\N
483	曲阜师范大学	双非	山东	\N	\N	\N	["yz_dwdm:10446"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.618888+08	2026-10-19 23:20:50.886046+08	t	\N
484	青岛农业大学	双非	山东	\N	\N	\N	["yz_dwdm:10435"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.619905+08	2026-10-19 23:20:50.886046+08	t	\N
485	山东财经大学	双非	山东	\N	\N	\N	["yz_dwdm:10456"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.621018+08	2026-10-19 23:20:50.886046+08	t	\N
486	山东政法学院	双非	山东	\N	\N	\N	["yz_dwdm:14100"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.622068+08	2026-10-19 23:20:50.886046+08	t	\N
487	海军航空大学	双非	山东	\N	\N	\N	["yz_dwdm:92016"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.624461+08	2026-10-19 23:20:50.886046+08	t	\N
488	华北水利水电大学	双非	河南	\N	\N	\N	["yz_dwdm:10078"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.625734+08	2026-10-19 23:20:50.886046+08	t	\N
489	郑州大学	211	河南	\N	\N	\N	["yz_dwdm:10459"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.628355+08	2026-10-19 23:20:50.886046+08	t	\N
490	河南理工大学	双非	河南	\N	\N	\N	["yz_dwdm:10460"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.630095+08	2026-10-19 23:20:50.886046+08	t	\N
491	郑州轻工业大学	双非	河南	\N	\N	\N	["yz_dwdm:10462"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.631348+08	2026-10-19 23:20:50.886046+08	t	\N
492	河南工业大学	双非	河南	\N	\N	\N	["yz_dwdm:10463"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.63256+08	2026-10-19 23:20:50.886046+08	t	\N
493	河南科技大学	双非	河南	\N	\N	\N	["yz_dwdm:10464"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.633519+08	2026-10-19 23:20:50.886046+08	t	\N
494	中原工学院	双非	河南	\N	\N	\N	["yz_dwdm:10465"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.634619+08	2026-10-19 23:20:50.886046+08	t	\N
495	河南农业大学	双非	河南	\N	\N	\N	["yz_dwdm:10466"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.635732+08	2026-10-19 23:20:50.886046+08	t	\N
496	河南科技学院	双非	河南	\N	\N	\N	["yz_dwdm:10467"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.636741+08	2026-10-19 23:20:50.886046+08	t	\N
497	河南中医药大学	双非	河南	\N	\N	\N	["yz_dwdm:10471"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.637975+08	2026-10-19 23:20:50.886046+08	t	\N
498	河南医药大学	双非	河南	\N	\N	\N	["yz_dwdm:10472"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.639361+08	2026-10-19 23:20:50.886046+08	t	\N
499	河南大学	双非	河南	\N	\N	\N	["yz_dwdm:10475"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.640446+08	2026-10-19 23:20:50.886046+08	t	\N
500	安阳师范学院	双非	河南	\N	\N	\N	["yz_dwdm:10479"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.642113+08	2026-10-19 23:20:50.886046+08	t	\N
501	南阳师范学院	双非	河南	\N	\N	\N	["yz_dwdm:10481"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.643448+08	2026-10-19 23:20:50.886046+08	t	\N
502	洛阳师范学院	双非	河南	\N	\N	\N	["yz_dwdm:10482"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.64475+08	2026-10-19 23:20:50.886046+08	t	\N
503	郑州航空工业管理学院	双非	河南	\N	\N	\N	["yz_dwdm:10485"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.646355+08	2026-10-19 23:20:50.886046+08	t	\N
504	平顶山学院	双非	河南	\N	\N	\N	["yz_dwdm:10919"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.647894+08	2026-10-19 23:20:50.886046+08	t	\N
505	河南城建学院	双非	河南	\N	\N	\N	["yz_dwdm:11765"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.650253+08	2026-10-19 23:20:50.886046+08	t	\N
506	机械科学研究总院(郑州机械研究所)	双非	河南	\N	\N	\N	["yz_dwdm:82708"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.655342+08	2026-10-19 23:20:50.886046+08	t	\N
507	中国舰船研究院(郑州机电工程研究所)	双非	河南	\N	\N	\N	["yz_dwdm:86213"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.658537+08	2026-10-19 23:20:50.886046+08	t	\N
508	中国舰船研究院(洛阳船舶材料研究所)	双非	河南	\N	\N	\N	["yz_dwdm:86214"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.663832+08	2026-10-19 23:20:50.886046+08	t	\N
509	中国航空研究院(014中心)	双非	河南	\N	\N	\N	["yz_dwdm:82907"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.668837+08	2026-10-19 23:20:50.886046+08	t	\N
510	中国航空研究院(613所)	双非	河南	\N	\N	\N	["yz_dwdm:82908"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.677118+08	2026-10-19 23:20:50.886046+08	t	\N
511	中国烟草总公司郑州烟草研究院	双非	河南	\N	\N	\N	["yz_dwdm:83708"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.682619+08	2026-10-19 23:20:50.886046+08	t	\N
512	河南师范大学	双非	河南	\N	\N	\N	["yz_dwdm:10476"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.68378+08	2026-10-19 23:20:50.886046+08	t	\N
513	河南财经政法大学	双非	河南	\N	\N	\N	["yz_dwdm:10484"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.686399+08	2026-10-19 23:20:50.886046+08	t	\N
514	信阳师范大学	双非	河南	\N	\N	\N	["yz_dwdm:10477"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.690375+08	2026-10-19 23:20:50.886046+08	t	\N
515	网络空间部队信息工程大学	双非	河南	\N	\N	\N	["yz_dwdm:92034"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.695437+08	2026-10-19 23:20:50.886046+08	t	\N
516	武汉大学	985	湖北	\N	\N	\N	["yz_dwdm:10486"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.710967+08	2026-10-19 23:20:50.886046+08	t	\N
517	华中科技大学	985	湖北	\N	\N	\N	["yz_dwdm:10487"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.712436+08	2026-10-19 23:20:50.886046+08	t	\N
518	武汉科技大学	双非	湖北	\N	\N	\N	["yz_dwdm:10488"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.714104+08	2026-10-19 23:20:50.886046+08	t	\N
519	长江大学	双非	湖北	\N	\N	\N	["yz_dwdm:10489"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.715142+08	2026-10-19 23:20:50.886046+08	t	\N
520	武汉工程大学	双非	湖北	\N	\N	\N	["yz_dwdm:10490"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.716266+08	2026-10-19 23:20:50.886046+08	t	\N
521	中国地质大学(武汉)	211	湖北	\N	\N	\N	["yz_dwdm:10491"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.717404+08	2026-10-19 23:20:50.886046+08	t	\N
522	武汉纺织大学	双非	湖北	\N	\N	\N	["yz_dwdm:10495"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.718449+08	2026-10-19 23:20:50.886046+08	t	\N
523	武汉轻工大学	双非	湖北	\N	\N	\N	["yz_dwdm:10496"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.719446+08	2026-10-19 23:20:50.886046+08	t	\N
524	武汉理工大学	211	湖北	\N	\N	\N	["yz_dwdm:10497"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.720442+08	2026-10-19 23:20:50.886046+08	t	\N
525	湖北工业大学	双非	湖北	\N	\N	\N	["yz_dwdm:10500"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.721521+08	2026-10-19 23:20:50.886046+08	t	\N
526	黄冈师范学院	双非	湖北	\N	\N	\N	["yz_dwdm:10514"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.722534+08	2026-10-19 23:20:50.886046+08	t	\N
527	湖北文理学院	双非	湖北	\N	\N	\N	["yz_dwdm:10519"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.724508+08	2026-10-19 23:20:50.886046+08	t	\N
528	武汉体育学院	双非	湖北	\N	\N	\N	["yz_dwdm:10522"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.725738+08	2026-10-19 23:20:50.886046+08	t	\N
529	湖北美术学院	双非	湖北	\N	\N	\N	["yz_dwdm:10523"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.726843+08	2026-10-19 23:20:50.886046+08	t	\N
530	湖北汽车工业学院	双非	湖北	\N	\N	\N	["yz_dwdm:10525"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.72871+08	2026-10-19 23:20:50.886046+08	t	\N
531	湖北工程学院	双非	湖北	\N	\N	\N	["yz_dwdm:10528"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.729902+08	2026-10-19 23:20:50.886046+08	t	\N
532	湖北理工学院	双非	湖北	\N	\N	\N	["yz_dwdm:10920"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.731001+08	2026-10-19 23:20:50.886046+08	t	\N
533	湖北科技学院	双非	湖北	\N	\N	\N	["yz_dwdm:10927"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.731989+08	2026-10-19 23:20:50.886046+08	t	\N
535	武汉音乐学院	双非	湖北	\N	\N	\N	["yz_dwdm:11524"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.735792+08	2026-10-19 23:20:50.886046+08	t	\N
536	机械科学研究总院(武汉材料保护研究所)	双非	湖北	\N	\N	\N	["yz_dwdm:82709"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.737101+08	2026-10-19 23:20:50.886046+08	t	\N
537	武汉生物制品研究所	双非	湖北	\N	\N	\N	["yz_dwdm:84506"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.738496+08	2026-10-19 23:20:50.886046+08	t	\N
538	中国地震局地震研究所	双非	湖北	\N	\N	\N	["yz_dwdm:85404"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.740201+08	2026-10-19 23:20:50.886046+08	t	\N
539	中国舰船研究院(武汉数字工程研究所)	双非	湖北	\N	\N	\N	["yz_dwdm:86202"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.741361+08	2026-10-19 23:20:50.886046+08	t	\N
540	中国舰船研究院(武汉船用电力推进装置研究所)	双非	湖北	\N	\N	\N	["yz_dwdm:86215"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.742592+08	2026-10-19 23:20:50.886046+08	t	\N
541	中国舰船研究院(华中光电技术研究所)	双非	湖北	\N	\N	\N	["yz_dwdm:86216"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.744164+08	2026-10-19 23:20:50.886046+08	t	\N
542	中国舰船研究院(武汉船舶通信研究所)	双非	湖北	\N	\N	\N	["yz_dwdm:86217"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.745401+08	2026-10-19 23:20:50.886046+08	t	\N
543	中国舰船研究院(武汉第二船舶设计研究所)	双非	湖北	\N	\N	\N	["yz_dwdm:86218"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.746971+08	2026-10-19 23:20:50.886046+08	t	\N
544	长江科学院	双非	湖北	\N	\N	\N	["yz_dwdm:82305"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.748032+08	2026-10-19 23:20:50.886046+08	t	\N
545	湖北省社会科学院	双非	湖北	\N	\N	\N	["yz_dwdm:88701"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.749155+08	2026-10-19 23:20:50.886046+08	t	\N
546	武汉安全环保研究院	双非	湖北	\N	\N	\N	["yz_dwdm:82609"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.750253+08	2026-10-19 23:20:50.886046+08	t	\N
547	中国航空研究院(610所)	双非	湖北	\N	\N	\N	["yz_dwdm:82961"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.75199+08	2026-10-19 23:20:50.886046+08	t	\N
548	航天动力技术研究院(42所)	双非	湖北	\N	\N	\N	["yz_dwdm:83258"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.753637+08	2026-10-19 23:20:50.886046+08	t	\N
549	武汉邮电科学研究院	双非	湖北	\N	\N	\N	["yz_dwdm:84011"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.754866+08	2026-10-19 23:20:50.886046+08	t	\N
550	中国舰船研究院(中国舰船研究设计中心)	双非	湖北	\N	\N	\N	["yz_dwdm:86203"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.756224+08	2026-10-19 23:20:50.886046+08	t	\N
551	湖北中医药大学	双非	湖北	\N	\N	\N	["yz_dwdm:10507"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.757296+08	2026-10-19 23:20:50.886046+08	t	\N
552	湖北大学	双非	湖北	\N	\N	\N	["yz_dwdm:10512"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.758694+08	2026-10-19 23:20:50.886046+08	t	\N
553	湖北师范大学	双非	湖北	\N	\N	\N	["yz_dwdm:10513"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.759816+08	2026-10-19 23:20:50.886046+08	t	\N
554	湖北民族大学	双非	湖北	\N	\N	\N	["yz_dwdm:10517"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.760979+08	2026-10-19 23:20:50.886046+08	t	\N
555	华中师范大学	211	湖北	\N	\N	\N	["yz_dwdm:10511"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.762006+08	2026-10-19 23:20:50.886046+08	t	\N
556	华中农业大学	211	湖北	\N	\N	\N	["yz_dwdm:10504"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.765082+08	2026-10-19 23:20:50.886046+08	t	\N
557	中南财经政法大学	211	湖北	\N	\N	\N	["yz_dwdm:10520"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.766667+08	2026-10-19 23:20:50.886046+08	t	\N
558	中南民族大学	双非	湖北	\N	\N	\N	["yz_dwdm:10524"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.767848+08	2026-10-19 23:20:50.886046+08	t	\N
559	海军工程大学	双非	湖北	\N	\N	\N	["yz_dwdm:92013"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.769008+08	2026-10-19 23:20:50.886046+08	t	\N
560	信息支援部队工程大学	双非	湖北	\N	\N	\N	["yz_dwdm:92035"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.770267+08	2026-10-19 23:20:50.886046+08	t	\N
561	湘潭大学	双一流	湖南	\N	\N	\N	["yz_dwdm:10530"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.771453+08	2026-10-19 23:20:50.886046+08	t	\N
562	吉首大学	双非	湖南	\N	\N	\N	["yz_dwdm:10531"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.772604+08	2026-10-19 23:20:50.886046+08	t	\N
563	湖南大学	985	湖南	\N	\N	\N	["yz_dwdm:10532"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.773825+08	2026-10-19 23:20:50.886046+08	t	\N
564	中南大学	985	湖南	\N	\N	\N	["yz_dwdm:10533"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.774867+08	2026-10-19 23:20:50.886046+08	t	\N
565	湖南科技大学	双非	湖南	\N	\N	\N	["yz_dwdm:10534"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.775952+08	2026-10-19 23:20:50.886046+08	t	\N
566	长沙理工大学	双非	湖南	\N	\N	\N	["yz_dwdm:10536"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.777269+08	2026-10-19 23:20:50.886046+08	t	\N
567	湖南农业大学	双非	湖南	\N	\N	\N	["yz_dwdm:10537"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.778621+08	2026-10-19 23:20:50.886046+08	t	\N
568	中南林业科技大学	双非	湖南	\N	\N	\N	["yz_dwdm:10538"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.779858+08	2026-10-19 23:20:50.886046+08	t	\N
569	湖南中医药大学	双非	湖南	\N	\N	\N	["yz_dwdm:10541"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.78115+08	2026-10-19 23:20:50.886046+08	t	\N
570	湖南师范大学	211	湖南	\N	\N	\N	["yz_dwdm:10542"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.782225+08	2026-10-19 23:20:50.886046+08	t	\N
571	衡阳师范学院	双非	湖南	\N	\N	\N	["yz_dwdm:10546"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.78329+08	2026-10-19 23:20:50.886046+08	t	\N
572	邵阳学院	双非	湖南	\N	\N	\N	["yz_dwdm:10547"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.784317+08	2026-10-19 23:20:50.886046+08	t	\N
573	湖南文理学院	双非	湖南	\N	\N	\N	["yz_dwdm:10549"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.785466+08	2026-10-19 23:20:50.886046+08	t	\N
574	湖南科技学院	双非	湖南	\N	\N	\N	["yz_dwdm:10551"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.786442+08	2026-10-19 23:20:50.886046+08	t	\N
575	湖南人文科技学院	双非	湖南	\N	\N	\N	["yz_dwdm:10553"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.788303+08	2026-10-19 23:20:50.886046+08	t	\N
576	长沙学院	双非	湖南	\N	\N	\N	["yz_dwdm:11077"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.789513+08	2026-10-19 23:20:50.886046+08	t	\N
577	湖南工程学院	双非	湖南	\N	\N	\N	["yz_dwdm:11342"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.790665+08	2026-10-19 23:20:50.886046+08	t	\N
578	湖南城市学院	双非	湖南	\N	\N	\N	["yz_dwdm:11527"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.79216+08	2026-10-19 23:20:50.886046+08	t	\N
579	湖南财政经济学院	双非	湖南	\N	\N	\N	["yz_dwdm:11532"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.793232+08	2026-10-19 23:20:50.886046+08	t	\N
580	湖南第一师范学院	双非	湖南	\N	\N	\N	["yz_dwdm:12034"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.7952+08	2026-10-19 23:20:50.886046+08	t	\N
581	长沙矿冶研究院	双非	湖南	\N	\N	\N	["yz_dwdm:82603"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.796622+08	2026-10-19 23:20:50.886046+08	t	\N
582	中国航空研究院(608所)	双非	湖南	\N	\N	\N	["yz_dwdm:82925"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.798073+08	2026-10-19 23:20:50.886046+08	t	\N
583	长沙矿山研究院	双非	湖南	\N	\N	\N	["yz_dwdm:86404"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.799195+08	2026-10-19 23:20:50.886046+08	t	\N
584	湖南省中医药研究院	双非	湖南	\N	\N	\N	["yz_dwdm:88801"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.800313+08	2026-10-19 23:20:50.886046+08	t	\N
585	湖南理工大学	双非	湖南	\N	\N	\N	["yz_dwdm:10543"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.801381+08	2026-10-19 23:20:50.886046+08	t	\N
586	湖南工商大学	双非	湖南	\N	\N	\N	["yz_dwdm:10554"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.802428+08	2026-10-19 23:20:50.886046+08	t	\N
587	国防科技大学	985	湖南	\N	\N	\N	["yz_dwdm:92002"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.803556+08	2026-10-19 23:20:50.886046+08	t	\N
588	湖南工业大学	双非	湖南	\N	\N	\N	["yz_dwdm:11535"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.804742+08	2026-10-19 23:20:50.886046+08	t	\N
589	中山大学	985	广东	\N	\N	\N	["yz_dwdm:10558"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.805933+08	2026-10-19 23:20:50.886046+08	t	\N
590	暨南大学	211	广东	\N	\N	\N	["yz_dwdm:10559"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.80713+08	2026-10-19 23:20:50.886046+08	t	\N
591	汕头大学	双非	广东	\N	\N	\N	["yz_dwdm:10560"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.808374+08	2026-10-19 23:20:50.886046+08	t	\N
592	华南理工大学	985	广东	\N	\N	\N	["yz_dwdm:10561"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.809681+08	2026-10-19 23:20:50.886046+08	t	\N
593	华南农业大学	双非	广东	\N	\N	\N	["yz_dwdm:10564"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.810837+08	2026-10-19 23:20:50.886046+08	t	\N
594	广东海洋大学	双非	广东	\N	\N	\N	["yz_dwdm:10566"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.812118+08	2026-10-19 23:20:50.886046+08	t	\N
595	广州医科大学	双一流	广东	\N	\N	\N	["yz_dwdm:10570"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.81322+08	2026-10-19 23:20:50.886046+08	t	\N
596	广东医科大学	双非	广东	\N	\N	\N	["yz_dwdm:10571"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.814355+08	2026-10-19 23:20:50.886046+08	t	\N
597	广州中医药大学	双一流	广东	\N	\N	\N	["yz_dwdm:10572"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.815376+08	2026-10-19 23:20:50.886046+08	t	\N
598	广东药科大学	双非	广东	\N	\N	\N	["yz_dwdm:10573"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.816529+08	2026-10-19 23:20:50.886046+08	t	\N
599	韶关学院	双非	广东	\N	\N	\N	["yz_dwdm:10576"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.817652+08	2026-10-19 23:20:50.886046+08	t	\N
600	惠州学院	双非	广东	\N	\N	\N	["yz_dwdm:10577"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.81954+08	2026-10-19 23:20:50.886046+08	t	\N
601	韩山师范学院	双非	广东	\N	\N	\N	["yz_dwdm:10578"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.820743+08	2026-10-19 23:20:50.886046+08	t	\N
602	岭南师范学院	双非	广东	\N	\N	\N	["yz_dwdm:10579"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.821974+08	2026-10-19 23:20:50.886046+08	t	\N
603	肇庆学院	双非	广东	\N	\N	\N	["yz_dwdm:10580"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.822964+08	2026-10-19 23:20:50.886046+08	t	\N
604	嘉应学院	双非	广东	\N	\N	\N	["yz_dwdm:10582"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.824012+08	2026-10-19 23:20:50.886046+08	t	\N
606	广州美术学院	双非	广东	\N	\N	\N	["yz_dwdm:10586"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.82884+08	2026-10-19 23:20:50.886046+08	t	\N
607	星海音乐学院	双非	广东	\N	\N	\N	["yz_dwdm:10587"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.83107+08	2026-10-19 23:20:50.886046+08	t	\N
608	仲恺农业工程学院	双非	广东	\N	\N	\N	["yz_dwdm:11347"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.832121+08	2026-10-19 23:20:50.886046+08	t	\N
609	广东省心血管病研究所	双非	广东	\N	\N	\N	["yz_dwdm:88911"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.840279+08	2026-10-19 23:20:50.886046+08	t	\N
610	广东省社会科学院	双非	广东	\N	\N	\N	["yz_dwdm:88901"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.860281+08	2026-10-19 23:20:50.886046+08	t	\N
668	西华大学	双非	四川	\N	\N	\N	["yz_dwdm:10623"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.988313+08	2026-10-19 23:20:50.886046+08	t	\N
611	广东技术师范大学	双非	广东	\N	\N	\N	["yz_dwdm:10588"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.861885+08	2026-10-19 23:20:50.886046+08	t	\N
612	广东财经大学	双非	广东	\N	\N	\N	["yz_dwdm:10592"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.862962+08	2026-10-19 23:20:50.886046+08	t	\N
613	广东金融学院	双非	广东	\N	\N	\N	["yz_dwdm:11540"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.865463+08	2026-10-19 23:20:50.886046+08	t	\N
614	广东石油化工学院	双非	广东	\N	\N	\N	["yz_dwdm:11656"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.866539+08	2026-10-19 23:20:50.886046+08	t	\N
615	广东工业大学	双非	广东	\N	\N	\N	["yz_dwdm:11845"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.867711+08	2026-10-19 23:20:50.886046+08	t	\N
616	广东外语外贸大学	双非	广东	\N	\N	\N	["yz_dwdm:11846"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.868895+08	2026-10-19 23:20:50.886046+08	t	\N
617	中共广东省委党校	双非	广东	\N	\N	\N	["yz_dwdm:86406"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.87003+08	2026-10-19 23:20:50.886046+08	t	\N
618	东莞理工学院	双非	广东	\N	\N	\N	["yz_dwdm:11819"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.871835+08	2026-10-19 23:20:50.886046+08	t	\N
619	南方科技大学	双一流	广东	\N	\N	\N	["yz_dwdm:14325"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.872892+08	2026-10-19 23:20:50.886046+08	t	\N
620	华南师范大学	211	广东	\N	\N	\N	["yz_dwdm:10574"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.873892+08	2026-10-19 23:20:50.886046+08	t	\N
621	南方医科大学	双非	广东	\N	\N	\N	["yz_dwdm:12121"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.875068+08	2026-10-19 23:20:50.886046+08	t	\N
622	广西大学	211	广西	\N	\N	\N	["yz_dwdm:10593"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.876138+08	2026-10-19 23:20:50.886046+08	t	\N
623	广西科技大学	双非	广西	\N	\N	\N	["yz_dwdm:10594"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.879246+08	2026-10-19 23:20:50.886046+08	t	\N
624	桂林电子科技大学	双非	广西	\N	\N	\N	["yz_dwdm:10595"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.881039+08	2026-10-19 23:20:50.886046+08	t	\N
625	桂林理工大学	双非	广西	\N	\N	\N	["yz_dwdm:10596"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.882174+08	2026-10-19 23:20:50.886046+08	t	\N
626	广西医科大学	双非	广西	\N	\N	\N	["yz_dwdm:10598"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.883987+08	2026-10-19 23:20:50.886046+08	t	\N
627	右江民族医学院	双非	广西	\N	\N	\N	["yz_dwdm:10599"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.885137+08	2026-10-19 23:20:50.886046+08	t	\N
628	广西中医药大学	双非	广西	\N	\N	\N	["yz_dwdm:10600"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.886204+08	2026-10-19 23:20:50.886046+08	t	\N
629	桂林医科大学	双非	广西	\N	\N	\N	["yz_dwdm:10601"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.887205+08	2026-10-19 23:20:50.886046+08	t	\N
630	广西师范大学	双非	广西	\N	\N	\N	["yz_dwdm:10602"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.888651+08	2026-10-19 23:20:50.886046+08	t	\N
631	南宁师范大学	双非	广西	\N	\N	\N	["yz_dwdm:10603"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.889918+08	2026-10-19 23:20:50.886046+08	t	\N
632	广西民族大学	双非	广西	\N	\N	\N	["yz_dwdm:10608"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.891077+08	2026-10-19 23:20:50.886046+08	t	\N
633	玉林师范学院	双非	广西	\N	\N	\N	["yz_dwdm:10606"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.892198+08	2026-10-19 23:20:50.886046+08	t	\N
634	广西艺术学院	双非	广西	\N	\N	\N	["yz_dwdm:10607"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.893347+08	2026-10-19 23:20:50.886046+08	t	\N
635	广西财经学院	双非	广西	\N	\N	\N	["yz_dwdm:11548"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.89444+08	2026-10-19 23:20:50.886046+08	t	\N
636	贺州学院	双非	广西	\N	\N	\N	["yz_dwdm:11838"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.896462+08	2026-10-19 23:20:50.886046+08	t	\N
637	陆军特种作战学院	双非	广西	\N	\N	\N	["yz_dwdm:92008"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.898065+08	2026-10-19 23:20:50.886046+08	t	\N
638	海南大学	211	海南	\N	\N	\N	["yz_dwdm:10589"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.899138+08	2026-10-19 23:20:50.886046+08	t	\N
639	海南热带海洋学院	双非	海南	\N	\N	\N	["yz_dwdm:11100"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.90177+08	2026-10-19 23:20:50.886046+08	t	\N
640	海南师范大学	双非	海南	\N	\N	\N	["yz_dwdm:11658"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.902859+08	2026-10-19 23:20:50.886046+08	t	\N
641	海南医科大学	双非	海南	\N	\N	\N	["yz_dwdm:11810"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.903952+08	2026-10-19 23:20:50.886046+08	t	\N
642	三亚学院	双非	海南	\N	\N	\N	["yz_dwdm:13892"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.906211+08	2026-10-19 23:20:50.886046+08	t	\N
643	重庆大学	985	重庆	\N	\N	\N	["yz_dwdm:10611"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.907477+08	2026-10-19 23:20:50.886046+08	t	\N
644	重庆邮电大学	双非	重庆	\N	\N	\N	["yz_dwdm:10617"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.90929+08	2026-10-19 23:20:50.886046+08	t	\N
645	重庆交通大学	双非	重庆	\N	\N	\N	["yz_dwdm:10618"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.910722+08	2026-10-19 23:20:50.886046+08	t	\N
646	重庆医科大学	双非	重庆	\N	\N	\N	["yz_dwdm:10631"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.912399+08	2026-10-19 23:20:50.886046+08	t	\N
647	西南大学	211	重庆	\N	\N	\N	["yz_dwdm:10635"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.91479+08	2026-10-19 23:20:50.886046+08	t	\N
648	重庆师范大学	双非	重庆	\N	\N	\N	["yz_dwdm:10637"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.922126+08	2026-10-19 23:20:50.886046+08	t	\N
649	重庆文理学院	双非	重庆	\N	\N	\N	["yz_dwdm:10642"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.928863+08	2026-10-19 23:20:50.886046+08	t	\N
650	重庆三峡科技大学	双非	重庆	\N	\N	\N	["yz_dwdm:10643"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.940316+08	2026-10-19 23:20:50.886046+08	t	\N
651	长江师范学院	双非	重庆	\N	\N	\N	["yz_dwdm:10647"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.942768+08	2026-10-19 23:20:50.886046+08	t	\N
652	四川外国语大学	双非	重庆	\N	\N	\N	["yz_dwdm:10650"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.945329+08	2026-10-19 23:20:50.886046+08	t	\N
653	西南政法大学	双非	重庆	\N	\N	\N	["yz_dwdm:10652"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.947626+08	2026-10-19 23:20:50.886046+08	t	\N
654	重庆科技大学	双非	重庆	\N	\N	\N	["yz_dwdm:11551"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.950112+08	2026-10-19 23:20:50.886046+08	t	\N
655	四川美术学院	双非	重庆	\N	\N	\N	["yz_dwdm:10655"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.952377+08	2026-10-19 23:20:50.886046+08	t	\N
656	重庆中医药学院	双非	重庆	\N	\N	\N	["yz_dwdm:14830"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.956101+08	2026-10-19 23:20:50.886046+08	t	\N
657	重庆理工大学	双非	重庆	\N	\N	\N	["yz_dwdm:11660"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.958377+08	2026-10-19 23:20:50.886046+08	t	\N
658	重庆工商大学	双非	重庆	\N	\N	\N	["yz_dwdm:11799"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.961952+08	2026-10-19 23:20:50.886046+08	t	\N
659	联勤保障部队工程大学	双非	重庆	\N	\N	\N	["yz_dwdm:92036"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.963852+08	2026-10-19 23:20:50.886046+08	t	\N
660	四川大学	985	四川	\N	\N	\N	["yz_dwdm:10610"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.965228+08	2026-10-19 23:20:50.886046+08	t	\N
661	西南交通大学	211	四川	\N	\N	\N	["yz_dwdm:10613"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.966566+08	2026-10-19 23:20:50.886046+08	t	\N
662	电子科技大学	985	四川	\N	\N	\N	["yz_dwdm:10614"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.968945+08	2026-10-19 23:20:50.886046+08	t	\N
663	西南石油大学	双一流	四川	\N	\N	\N	["yz_dwdm:10615"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.970942+08	2026-10-19 23:20:50.886046+08	t	\N
664	成都理工大学	双一流	四川	\N	\N	\N	["yz_dwdm:10616"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.973315+08	2026-10-19 23:20:50.886046+08	t	\N
665	西南科技大学	双非	四川	\N	\N	\N	["yz_dwdm:10619"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.977402+08	2026-10-19 23:20:50.886046+08	t	\N
666	成都信息工程大学	双非	四川	\N	\N	\N	["yz_dwdm:10621"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.983302+08	2026-10-19 23:20:50.886046+08	t	\N
667	四川轻化工大学	双非	四川	\N	\N	\N	["yz_dwdm:10622"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.986593+08	2026-10-19 23:20:50.886046+08	t	\N
669	中国民用航空飞行学院	双非	四川	\N	\N	\N	["yz_dwdm:10624"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.993766+08	2026-10-19 23:20:50.886046+08	t	\N
670	四川农业大学	211	四川	\N	\N	\N	["yz_dwdm:10626"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.99504+08	2026-10-19 23:20:50.886046+08	t	\N
671	西昌学院	双非	四川	\N	\N	\N	["yz_dwdm:10628"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.996316+08	2026-10-19 23:20:50.886046+08	t	\N
672	川北医学院	双非	四川	\N	\N	\N	["yz_dwdm:10634"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:12.998847+08	2026-10-19 23:20:50.886046+08	t	\N
673	绵阳师范学院	双非	四川	\N	\N	\N	["yz_dwdm:10639"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.00039+08	2026-10-19 23:20:50.886046+08	t	\N
674	内江师范学院	双非	四川	\N	\N	\N	["yz_dwdm:10640"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.002871+08	2026-10-19 23:20:50.886046+08	t	\N
675	宜宾学院	双非	四川	\N	\N	\N	["yz_dwdm:10641"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.005045+08	2026-10-19 23:20:50.886046+08	t	\N
676	乐山师范学院	双非	四川	\N	\N	\N	["yz_dwdm:10649"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.007194+08	2026-10-19 23:20:50.886046+08	t	\N
677	成都体育学院	双非	四川	\N	\N	\N	["yz_dwdm:10653"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.009463+08	2026-10-19 23:20:50.886046+08	t	\N
678	四川音乐学院	双非	四川	\N	\N	\N	["yz_dwdm:10654"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.011518+08	2026-10-19 23:20:50.886046+08	t	\N
679	攀枝花学院	双非	四川	\N	\N	\N	["yz_dwdm:11360"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.014228+08	2026-10-19 23:20:50.886046+08	t	\N
680	中国兵器科学研究院(西南技术物理研究所)	双非	四川	\N	\N	\N	["yz_dwdm:83105"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.017329+08	2026-10-19 23:20:50.886046+08	t	\N
681	中国兵器科学研究院(西南自动化研究所)	双非	四川	\N	\N	\N	["yz_dwdm:83114"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.02522+08	2026-10-19 23:20:50.886046+08	t	\N
682	电信科学技术研究院(第五研究所)	双非	四川	\N	\N	\N	["yz_dwdm:84004"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.027851+08	2026-10-19 23:20:50.886046+08	t	\N
683	四川省社会科学院	双非	四川	\N	\N	\N	["yz_dwdm:89101"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.0321+08	2026-10-19 23:20:50.886046+08	t	\N
684	核工业西南物理研究院	双非	四川	\N	\N	\N	["yz_dwdm:82809"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.033573+08	2026-10-19 23:20:50.886046+08	t	\N
685	中国航空研究院(611所)	双非	四川	\N	\N	\N	["yz_dwdm:82906"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.04133+08	2026-10-19 23:20:50.886046+08	t	\N
686	中国航空研究院(624所)	双非	四川	\N	\N	\N	["yz_dwdm:82910"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.044648+08	2026-10-19 23:20:50.886046+08	t	\N
687	四川师范大学	双非	四川	\N	\N	\N	["yz_dwdm:10636"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.047105+08	2026-10-19 23:20:50.886046+08	t	\N
688	四川警察学院	双非	四川	\N	\N	\N	["yz_dwdm:12212"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.049788+08	2026-10-19 23:20:50.886046+08	t	\N
689	中共四川省委党校	双非	四川	\N	\N	\N	["yz_dwdm:89651"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.053827+08	2026-10-19 23:20:50.886046+08	t	\N
690	中国核动力研究设计院	双非	四川	\N	\N	\N	["yz_dwdm:82802"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.05952+08	2026-10-19 23:20:50.886046+08	t	\N
691	西华师范大学	双非	四川	\N	\N	\N	["yz_dwdm:10638"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.069584+08	2026-10-19 23:20:50.886046+08	t	\N
692	西南医科大学	双非	四川	\N	\N	\N	["yz_dwdm:10632"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.073527+08	2026-10-19 23:20:50.886046+08	t	\N
693	成都中医药大学	双非	四川	\N	\N	\N	["yz_dwdm:10633"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.077027+08	2026-10-19 23:20:50.886046+08	t	\N
694	西南财经大学	211	四川	\N	\N	\N	["yz_dwdm:10651"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.078508+08	2026-10-19 23:20:50.886046+08	t	\N
695	西南民族大学	双非	四川	\N	\N	\N	["yz_dwdm:10656"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.07978+08	2026-10-19 23:20:50.886046+08	t	\N
696	贵州大学	211	贵州	\N	\N	\N	["yz_dwdm:10657"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.080888+08	2026-10-19 23:20:50.886046+08	t	\N
697	贵州医科大学	双非	贵州	\N	\N	\N	["yz_dwdm:10660"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.082111+08	2026-10-19 23:20:50.886046+08	t	\N
698	遵义医科大学	双非	贵州	\N	\N	\N	["yz_dwdm:10661"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.083417+08	2026-10-19 23:20:50.886046+08	t	\N
699	贵州中医药大学	双非	贵州	\N	\N	\N	["yz_dwdm:10662"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.084589+08	2026-10-19 23:20:50.886046+08	t	\N
700	贵州师范大学	双非	贵州	\N	\N	\N	["yz_dwdm:10663"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.085719+08	2026-10-19 23:20:50.886046+08	t	\N
701	遵义师范学院	双非	贵州	\N	\N	\N	["yz_dwdm:10664"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.086881+08	2026-10-19 23:20:50.886046+08	t	\N
702	铜仁学院	双非	贵州	\N	\N	\N	["yz_dwdm:10665"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.088115+08	2026-10-19 23:20:50.886046+08	t	\N
703	黔南民族师范学院	双非	贵州	\N	\N	\N	["yz_dwdm:10670"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.089445+08	2026-10-19 23:20:50.886046+08	t	\N
704	贵州财经大学	双非	贵州	\N	\N	\N	["yz_dwdm:10671"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.090713+08	2026-10-19 23:20:50.886046+08	t	\N
705	贵州民族大学	双非	贵州	\N	\N	\N	["yz_dwdm:10672"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.091768+08	2026-10-19 23:20:50.886046+08	t	\N
706	贵阳学院	双非	贵州	\N	\N	\N	["yz_dwdm:10976"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.093557+08	2026-10-19 23:20:50.886046+08	t	\N
707	贵州师范学院	双非	贵州	\N	\N	\N	["yz_dwdm:14223"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.095711+08	2026-10-19 23:20:50.886046+08	t	\N
708	中国航天科工集团第十研究院	双非	贵州	\N	\N	\N	["yz_dwdm:83286"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.096996+08	2026-10-19 23:20:50.886046+08	t	\N
709	云南大学	211	云南	\N	\N	\N	["yz_dwdm:10673"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.098091+08	2026-10-19 23:20:50.886046+08	t	\N
710	昆明理工大学	双非	云南	\N	\N	\N	["yz_dwdm:10674"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.099357+08	2026-10-19 23:20:50.886046+08	t	\N
711	云南农业大学	双非	云南	\N	\N	\N	["yz_dwdm:10676"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.100468+08	2026-10-19 23:20:50.886046+08	t	\N
712	西南林业大学	双非	云南	\N	\N	\N	["yz_dwdm:10677"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.101463+08	2026-10-19 23:20:50.886046+08	t	\N
713	昆明医科大学	双非	云南	\N	\N	\N	["yz_dwdm:10678"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.103014+08	2026-10-19 23:20:50.886046+08	t	\N
714	大理大学	双非	云南	\N	\N	\N	["yz_dwdm:10679"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.104065+08	2026-10-19 23:20:50.886046+08	t	\N
715	云南中医药大学	双非	云南	\N	\N	\N	["yz_dwdm:10680"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.105113+08	2026-10-19 23:20:50.886046+08	t	\N
716	云南师范大学	双非	云南	\N	\N	\N	["yz_dwdm:10681"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.106081+08	2026-10-19 23:20:50.886046+08	t	\N
717	曲靖师范学院	双非	云南	\N	\N	\N	["yz_dwdm:10684"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.107896+08	2026-10-19 23:20:50.886046+08	t	\N
718	红河学院	双非	云南	\N	\N	\N	["yz_dwdm:10687"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.109019+08	2026-10-19 23:20:50.886046+08	t	\N
719	云南财经大学	双非	云南	\N	\N	\N	["yz_dwdm:10689"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.110109+08	2026-10-19 23:20:50.886046+08	t	\N
720	云南民族大学	双非	云南	\N	\N	\N	["yz_dwdm:10691"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.111139+08	2026-10-19 23:20:50.886046+08	t	\N
721	云南艺术学院	双非	云南	\N	\N	\N	["yz_dwdm:10690"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.113242+08	2026-10-19 23:20:50.886046+08	t	\N
722	玉溪师范学院	双非	云南	\N	\N	\N	["yz_dwdm:11390"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.114918+08	2026-10-19 23:20:50.886046+08	t	\N
723	云南警官学院	双非	云南	\N	\N	\N	["yz_dwdm:11392"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.116518+08	2026-10-19 23:20:50.886046+08	t	\N
724	昆明学院	双非	云南	\N	\N	\N	["yz_dwdm:11393"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.11781+08	2026-10-19 23:20:50.886046+08	t	\N
725	中国兵器科学研究院(昆明物理研究所)	双非	云南	\N	\N	\N	["yz_dwdm:83104"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.119678+08	2026-10-19 23:20:50.886046+08	t	\N
726	昆明贵金属研究所	双非	云南	\N	\N	\N	["yz_dwdm:86401"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.120675+08	2026-10-19 23:20:50.886046+08	t	\N
727	西藏农牧大学	双非	西藏	\N	\N	\N	["yz_dwdm:10693"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.121752+08	2026-10-19 23:20:50.886046+08	t	\N
728	西藏大学	211	西藏	\N	\N	\N	["yz_dwdm:10694"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.12287+08	2026-10-19 23:20:50.886046+08	t	\N
729	西藏民族大学	双非	西藏	\N	\N	\N	["yz_dwdm:10695"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.123885+08	2026-10-19 23:20:50.886046+08	t	\N
730	西藏藏医药大学	双非	西藏	\N	\N	\N	["yz_dwdm:10696"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.12495+08	2026-10-19 23:20:50.886046+08	t	\N
731	西北大学	211	陕西	\N	\N	\N	["yz_dwdm:10697"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.12657+08	2026-10-19 23:20:50.886046+08	t	\N
732	西安交通大学	985	陕西	\N	\N	\N	["yz_dwdm:10698"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.129219+08	2026-10-19 23:20:50.886046+08	t	\N
733	西北工业大学	985	陕西	\N	\N	\N	["yz_dwdm:10699"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.130477+08	2026-10-19 23:20:50.886046+08	t	\N
734	西安理工大学	双非	陕西	\N	\N	\N	["yz_dwdm:10700"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.131643+08	2026-10-19 23:20:50.886046+08	t	\N
735	西安电子科技大学	211	陕西	\N	\N	\N	["yz_dwdm:10701"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.133207+08	2026-10-19 23:20:50.886046+08	t	\N
736	西安工业大学	双非	陕西	\N	\N	\N	["yz_dwdm:10702"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.134305+08	2026-10-19 23:20:50.886046+08	t	\N
737	西安建筑科技大学	双非	陕西	\N	\N	\N	["yz_dwdm:10703"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.136604+08	2026-10-19 23:20:50.886046+08	t	\N
738	西安科技大学	双非	陕西	\N	\N	\N	["yz_dwdm:10704"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.137676+08	2026-10-19 23:20:50.886046+08	t	\N
739	西安石油大学	双非	陕西	\N	\N	\N	["yz_dwdm:10705"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.138789+08	2026-10-19 23:20:50.886046+08	t	\N
740	陕西科技大学	双非	陕西	\N	\N	\N	["yz_dwdm:10708"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.13977+08	2026-10-19 23:20:50.886046+08	t	\N
741	宝鸡文理学院	双非	陕西	\N	\N	\N	["yz_dwdm:10721"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.140869+08	2026-10-19 23:20:50.886046+08	t	\N
742	咸阳师范学院	双非	陕西	\N	\N	\N	["yz_dwdm:10722"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.141933+08	2026-10-19 23:20:50.886046+08	t	\N
743	西安体育学院	双非	陕西	\N	\N	\N	["yz_dwdm:10727"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.144427+08	2026-10-19 23:20:50.886046+08	t	\N
744	西安音乐学院	双非	陕西	\N	\N	\N	["yz_dwdm:10728"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.145577+08	2026-10-19 23:20:50.886046+08	t	\N
745	西安美术学院	双非	陕西	\N	\N	\N	["yz_dwdm:10729"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.146867+08	2026-10-19 23:20:50.886046+08	t	\N
746	西安文理学院	双非	陕西	\N	\N	\N	["yz_dwdm:11080"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.147944+08	2026-10-19 23:20:50.886046+08	t	\N
747	商洛学院	双非	陕西	\N	\N	\N	["yz_dwdm:11396"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.148944+08	2026-10-19 23:20:50.886046+08	t	\N
748	安康学院	双非	陕西	\N	\N	\N	["yz_dwdm:11397"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.149924+08	2026-10-19 23:20:50.886046+08	t	\N
749	西安医学院	双非	陕西	\N	\N	\N	["yz_dwdm:11840"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.150841+08	2026-10-19 23:20:50.886046+08	t	\N
750	西京学院	双非	陕西	\N	\N	\N	["yz_dwdm:12715"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.151804+08	2026-10-19 23:20:50.886046+08	t	\N
751	中国兵器科学研究院(西安近代化学研究所)	双非	陕西	\N	\N	\N	["yz_dwdm:83101"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.152855+08	2026-10-19 23:20:50.886046+08	t	\N
752	中国兵器科学研究院(西安应用光学研究所)	双非	陕西	\N	\N	\N	["yz_dwdm:83103"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.154118+08	2026-10-19 23:20:50.886046+08	t	\N
753	中国兵器科学研究院(西安机电信息研究所)	双非	陕西	\N	\N	\N	["yz_dwdm:83109"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.155267+08	2026-10-19 23:20:50.886046+08	t	\N
754	中国兵器科学研究院(陕西应用物理化学研究所)	双非	陕西	\N	\N	\N	["yz_dwdm:83110"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.156481+08	2026-10-19 23:20:50.886046+08	t	\N
755	中国兵器科学研究院(陕西机械电器研究所)	双非	陕西	\N	\N	\N	["yz_dwdm:83111"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.157749+08	2026-10-19 23:20:50.886046+08	t	\N
756	中国兵器科学研究院(陕西青华机电研究所)	双非	陕西	\N	\N	\N	["yz_dwdm:83112"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.161334+08	2026-10-19 23:20:50.886046+08	t	\N
757	中国兵器科学研究院(西安电子工程研究所)	双非	陕西	\N	\N	\N	["yz_dwdm:83113"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.162594+08	2026-10-19 23:20:50.886046+08	t	\N
758	西安微电子技术研究所	双非	陕西	\N	\N	\N	["yz_dwdm:83276"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.16371+08	2026-10-19 23:20:50.886046+08	t	\N
759	电信科学技术研究院(第四研究所)	双非	陕西	\N	\N	\N	["yz_dwdm:84003"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.165605+08	2026-10-19 23:20:50.886046+08	t	\N
760	中国舰船研究院(西安精密机械研究所)	双非	陕西	\N	\N	\N	["yz_dwdm:86212"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.166663+08	2026-10-19 23:20:50.886046+08	t	\N
761	西安热工研究院	双非	陕西	\N	\N	\N	["yz_dwdm:82304"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.167704+08	2026-10-19 23:20:50.886046+08	t	\N
762	中国航空研究院(603所)	双非	陕西	\N	\N	\N	["yz_dwdm:82904"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.168799+08	2026-10-19 23:20:50.886046+08	t	\N
763	中国航空研究院(623所)	双非	陕西	\N	\N	\N	["yz_dwdm:82909"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.169987+08	2026-10-19 23:20:50.886046+08	t	\N
764	中国航空研究院(630所)	双非	陕西	\N	\N	\N	["yz_dwdm:82911"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.171126+08	2026-10-19 23:20:50.886046+08	t	\N
765	中国航空研究院(631所)	双非	陕西	\N	\N	\N	["yz_dwdm:82912"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.172314+08	2026-10-19 23:20:50.886046+08	t	\N
766	中国航空研究院(618所)	双非	陕西	\N	\N	\N	["yz_dwdm:82936"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.173653+08	2026-10-19 23:20:50.886046+08	t	\N
767	陕西中医药大学	双非	陕西	\N	\N	\N	["yz_dwdm:10716"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.1748+08	2026-10-19 23:20:50.886046+08	t	\N
768	陕西师范大学	211	陕西	\N	\N	\N	["yz_dwdm:10718"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.175958+08	2026-10-19 23:20:50.886046+08	t	\N
769	陕西理工大学	双非	陕西	\N	\N	\N	["yz_dwdm:10720"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.17721+08	2026-10-19 23:20:50.886046+08	t	\N
770	中共陕西省委党校	双非	陕西	\N	\N	\N	["yz_dwdm:89661"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.178382+08	2026-10-19 23:20:50.886046+08	t	\N
771	西北农林科技大学	985	陕西	\N	\N	\N	["yz_dwdm:10712"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.179794+08	2026-10-19 23:20:50.886046+08	t	\N
772	中国航天科技集团公司第五研究院(504所)	双非	陕西	\N	\N	\N	["yz_dwdm:83269"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.180993+08	2026-10-19 23:20:50.886046+08	t	\N
773	西安财经大学	双非	陕西	\N	\N	\N	["yz_dwdm:11560"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.182215+08	2026-10-19 23:20:50.886046+08	t	\N
774	西北政法大学	双非	陕西	\N	\N	\N	["yz_dwdm:10726"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.183354+08	2026-10-19 23:20:50.886046+08	t	\N
775	中国航天科工集团第二研究院(16所)	双非	陕西	\N	\N	\N	["yz_dwdm:83233"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.184534+08	2026-10-19 23:20:50.886046+08	t	\N
776	航天动力技术研究院	双非	陕西	\N	\N	\N	["yz_dwdm:83256"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.185665+08	2026-10-19 23:20:50.886046+08	t	\N
777	西安邮电大学	双非	陕西	\N	\N	\N	["yz_dwdm:11664"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.186903+08	2026-10-19 23:20:50.886046+08	t	\N
778	西安外国语大学	双非	陕西	\N	\N	\N	["yz_dwdm:10724"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.188268+08	2026-10-19 23:20:50.886046+08	t	\N
779	西安工程大学	双非	陕西	\N	\N	\N	["yz_dwdm:10709"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.189507+08	2026-10-19 23:20:50.886046+08	t	\N
780	空军工程大学	双非	陕西	\N	\N	\N	["yz_dwdm:92022"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.190681+08	2026-10-19 23:20:50.886046+08	t	\N
781	火箭军工程大学	双非	陕西	\N	\N	\N	["yz_dwdm:92031"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.191913+08	2026-10-19 23:20:50.886046+08	t	\N
782	武警工程大学	双非	陕西	\N	\N	\N	["yz_dwdm:92038"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.193236+08	2026-10-19 23:20:50.886046+08	t	\N
783	兰州大学	985	甘肃	\N	\N	\N	["yz_dwdm:10730"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.194433+08	2026-10-19 23:20:50.886046+08	t	\N
784	兰州理工大学	双非	甘肃	\N	\N	\N	["yz_dwdm:10731"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.195393+08	2026-10-19 23:20:50.886046+08	t	\N
785	兰州交通大学	双非	甘肃	\N	\N	\N	["yz_dwdm:10732"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.196593+08	2026-10-19 23:20:50.886046+08	t	\N
786	甘肃农业大学	双非	甘肃	\N	\N	\N	["yz_dwdm:10733"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.197913+08	2026-10-19 23:20:50.886046+08	t	\N
787	甘肃中医药大学	双非	甘肃	\N	\N	\N	["yz_dwdm:10735"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.199154+08	2026-10-19 23:20:50.886046+08	t	\N
788	西北师范大学	双非	甘肃	\N	\N	\N	["yz_dwdm:10736"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.20033+08	2026-10-19 23:20:50.886046+08	t	\N
789	兰州城市学院	双非	甘肃	\N	\N	\N	["yz_dwdm:10737"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.201435+08	2026-10-19 23:20:50.886046+08	t	\N
790	陇东学院	双非	甘肃	\N	\N	\N	["yz_dwdm:10738"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.202659+08	2026-10-19 23:20:50.886046+08	t	\N
791	天水师范大学	双非	甘肃	\N	\N	\N	["yz_dwdm:10739"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.203823+08	2026-10-19 23:20:50.886046+08	t	\N
792	河西学院	双非	甘肃	\N	\N	\N	["yz_dwdm:10740"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.20498+08	2026-10-19 23:20:50.886046+08	t	\N
793	兰州财经大学	双非	甘肃	\N	\N	\N	["yz_dwdm:10741"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.20607+08	2026-10-19 23:20:50.886046+08	t	\N
794	西北民族大学	双非	甘肃	\N	\N	\N	["yz_dwdm:10742"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.207302+08	2026-10-19 23:20:50.886046+08	t	\N
795	甘肃政法大学	双非	甘肃	\N	\N	\N	["yz_dwdm:11406"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.208505+08	2026-10-19 23:20:50.886046+08	t	\N
796	兰州生物制品研究所	双非	甘肃	\N	\N	\N	["yz_dwdm:84507"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.209814+08	2026-10-19 23:20:50.886046+08	t	\N
797	中国地震局兰州地震研究所	双非	甘肃	\N	\N	\N	["yz_dwdm:85403"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.210986+08	2026-10-19 23:20:50.886046+08	t	\N
798	中国航天科技集团公司第五研究院(510所)	双非	甘肃	\N	\N	\N	["yz_dwdm:83271"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.212131+08	2026-10-19 23:20:50.886046+08	t	\N
799	青海大学	211	青海	\N	\N	\N	["yz_dwdm:10743"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.213447+08	2026-10-19 23:20:50.886046+08	t	\N
800	青海师范大学	双非	青海	\N	\N	\N	["yz_dwdm:10746"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.214458+08	2026-10-19 23:20:50.886046+08	t	\N
801	青海民族大学	双非	青海	\N	\N	\N	["yz_dwdm:10748"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.215579+08	2026-10-19 23:20:50.886046+08	t	\N
802	宁夏大学	211	宁夏	\N	\N	\N	["yz_dwdm:10749"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.216628+08	2026-10-19 23:20:50.886046+08	t	\N
803	宁夏医科大学	双非	宁夏	\N	\N	\N	["yz_dwdm:10752"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.217771+08	2026-10-19 23:20:50.886046+08	t	\N
804	宁夏师范大学	双非	宁夏	\N	\N	\N	["yz_dwdm:10753"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.218977+08	2026-10-19 23:20:50.886046+08	t	\N
805	北方民族大学	双非	宁夏	\N	\N	\N	["yz_dwdm:11407"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.220106+08	2026-10-19 23:20:50.886046+08	t	\N
806	宁夏理工学院	双非	宁夏	\N	\N	\N	["yz_dwdm:12544"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.222261+08	2026-10-19 23:20:50.886046+08	t	\N
807	新疆大学	211	新疆	\N	\N	\N	["yz_dwdm:10755"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.223413+08	2026-10-19 23:20:50.886046+08	t	\N
808	塔里木大学	双非	新疆	\N	\N	\N	["yz_dwdm:10757"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.224462+08	2026-10-19 23:20:50.886046+08	t	\N
809	新疆农业大学	双非	新疆	\N	\N	\N	["yz_dwdm:10758"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.225491+08	2026-10-19 23:20:50.886046+08	t	\N
810	石河子大学	211	新疆	\N	\N	\N	["yz_dwdm:10759"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.226561+08	2026-10-19 23:20:50.886046+08	t	\N
811	新疆医科大学	双非	新疆	\N	\N	\N	["yz_dwdm:10760"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.228982+08	2026-10-19 23:20:50.886046+08	t	\N
812	新疆师范大学	双非	新疆	\N	\N	\N	["yz_dwdm:10762"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.230159+08	2026-10-19 23:20:50.886046+08	t	\N
813	喀什大学	双非	新疆	\N	\N	\N	["yz_dwdm:10763"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.231452+08	2026-10-19 23:20:50.886046+08	t	\N
814	伊犁师范大学	双非	新疆	\N	\N	\N	["yz_dwdm:10764"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.232632+08	2026-10-19 23:20:50.886046+08	t	\N
815	新疆财经大学	双非	新疆	\N	\N	\N	["yz_dwdm:10766"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.233804+08	2026-10-19 23:20:50.886046+08	t	\N
816	新疆艺术学院	双非	新疆	\N	\N	\N	["yz_dwdm:10768"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.235239+08	2026-10-19 23:20:50.886046+08	t	\N
817	新疆工程学院	双非	新疆	\N	\N	\N	["yz_dwdm:10994"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.23635+08	2026-10-19 23:20:50.886046+08	t	\N
818	昌吉学院	双非	新疆	\N	\N	\N	["yz_dwdm:10997"]	\N	yz.chsi.com.cn	\N	\N	2026-10-19 02:14:13.237347+08	2026-10-19 23:20:50.886046+08	t	\N
\.


--
-- Data for Name: kaoyan_scorelines; Type: TABLE DATA; Schema: public; Owner: kaoyan
--

COPY public.kaoyan_scorelines (id, school_id, major_id, year, total_line, politics_line, english_line, math_line, major_line, national_line, retest_line, line_type, source, created_at, enabled, deleted_at) FROM stdin;
\.


--
-- Name: kaoyan_admissions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: kaoyan
--

SELECT pg_catalog.setval('public.kaoyan_admissions_id_seq', 27, true);


--
-- Name: kaoyan_colleges_id_seq; Type: SEQUENCE SET; Schema: public; Owner: kaoyan
--

SELECT pg_catalog.setval('public.kaoyan_colleges_id_seq', 1, false);


--
-- Name: kaoyan_majors_id_seq; Type: SEQUENCE SET; Schema: public; Owner: kaoyan
--

SELECT pg_catalog.setval('public.kaoyan_majors_id_seq', 6341, true);


--
-- Name: kaoyan_notices_id_seq; Type: SEQUENCE SET; Schema: public; Owner: kaoyan
--

SELECT pg_catalog.setval('public.kaoyan_notices_id_seq', 2400, true);


--
-- Name: kaoyan_schools_id_seq; Type: SEQUENCE SET; Schema: public; Owner: kaoyan
--

SELECT pg_catalog.setval('public.kaoyan_schools_id_seq', 818, true);


--
-- Name: kaoyan_scorelines_id_seq; Type: SEQUENCE SET; Schema: public; Owner: kaoyan
--

SELECT pg_catalog.setval('public.kaoyan_scorelines_id_seq', 1, false);


--
-- Name: kaoyan_admissions kaoyan_admissions_pkey; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_admissions
    ADD CONSTRAINT kaoyan_admissions_pkey PRIMARY KEY (id);


--
-- Name: kaoyan_colleges kaoyan_colleges_pkey; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_colleges
    ADD CONSTRAINT kaoyan_colleges_pkey PRIMARY KEY (id);


--
-- Name: kaoyan_majors kaoyan_majors_pkey; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_majors
    ADD CONSTRAINT kaoyan_majors_pkey PRIMARY KEY (id);


--
-- Name: kaoyan_notices kaoyan_notices_pkey; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_notices
    ADD CONSTRAINT kaoyan_notices_pkey PRIMARY KEY (id);


--
-- Name: kaoyan_schools kaoyan_schools_pkey; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_schools
    ADD CONSTRAINT kaoyan_schools_pkey PRIMARY KEY (id);


--
-- Name: kaoyan_scorelines kaoyan_scorelines_pkey; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_scorelines
    ADD CONSTRAINT kaoyan_scorelines_pkey PRIMARY KEY (id);


--
-- Name: kaoyan_admissions uq_admission; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_admissions
    ADD CONSTRAINT uq_admission UNIQUE (school_id, major_id, year);


--
-- Name: kaoyan_colleges uq_college; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_colleges
    ADD CONSTRAINT uq_college UNIQUE (school_id, name);


--
-- Name: kaoyan_majors uq_major; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_majors
    ADD CONSTRAINT uq_major UNIQUE (school_id, code, name);


--
-- Name: kaoyan_notices uq_notice; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_notices
    ADD CONSTRAINT uq_notice UNIQUE (school_name, title, publish_date);


--
-- Name: kaoyan_schools uq_school_name; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_schools
    ADD CONSTRAINT uq_school_name UNIQUE (name);


--
-- Name: kaoyan_scorelines uq_scoreline; Type: CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_scorelines
    ADD CONSTRAINT uq_scoreline UNIQUE (school_id, major_id, year, line_type);


--
-- Name: idx_admissions_year; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX idx_admissions_year ON public.kaoyan_admissions USING btree (year, school_id);


--
-- Name: idx_majors_school; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX idx_majors_school ON public.kaoyan_majors USING btree (school_id);


--
-- Name: idx_majors_subject_code; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX idx_majors_subject_code ON public.kaoyan_majors USING btree (subject_code);


--
-- Name: idx_notices_deadline; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX idx_notices_deadline ON public.kaoyan_notices USING btree (deadline_date) WHERE (deadline_date IS NOT NULL);


--
-- Name: idx_notices_importance; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX idx_notices_importance ON public.kaoyan_notices USING btree (importance_level, publish_date DESC);


--
-- Name: idx_notices_read; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX idx_notices_read ON public.kaoyan_notices USING btree (is_read, publish_date DESC);


--
-- Name: idx_notices_school; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX idx_notices_school ON public.kaoyan_notices USING btree (school_id, publish_date DESC);


--
-- Name: idx_notices_starred; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX idx_notices_starred ON public.kaoyan_notices USING btree (is_starred);


--
-- Name: idx_notices_title_trgm; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX idx_notices_title_trgm ON public.kaoyan_notices USING gin (title public.gin_trgm_ops);


--
-- Name: idx_schools_region; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX idx_schools_region ON public.kaoyan_schools USING btree (province, city);


--
-- Name: idx_scorelines_year; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX idx_scorelines_year ON public.kaoyan_scorelines USING btree (year, school_id);


--
-- Name: ix_fk_kaoyan_admissions_major_id; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX ix_fk_kaoyan_admissions_major_id ON public.kaoyan_admissions USING btree (major_id);


--
-- Name: ix_fk_kaoyan_majors_college_id; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX ix_fk_kaoyan_majors_college_id ON public.kaoyan_majors USING btree (college_id);


--
-- Name: ix_fk_kaoyan_scorelines_major_id; Type: INDEX; Schema: public; Owner: kaoyan
--

CREATE INDEX ix_fk_kaoyan_scorelines_major_id ON public.kaoyan_scorelines USING btree (major_id);


--
-- Name: kaoyan_colleges trg_audit_kaoyan_colleges; Type: TRIGGER; Schema: public; Owner: kaoyan
--

CREATE TRIGGER trg_audit_kaoyan_colleges AFTER INSERT OR DELETE OR UPDATE ON public.kaoyan_colleges FOR EACH ROW EXECUTE FUNCTION public.fn_audit_log();


--
-- Name: kaoyan_majors trg_audit_kaoyan_majors; Type: TRIGGER; Schema: public; Owner: kaoyan
--

CREATE TRIGGER trg_audit_kaoyan_majors AFTER INSERT OR DELETE OR UPDATE ON public.kaoyan_majors FOR EACH ROW EXECUTE FUNCTION public.fn_audit_log();


--
-- Name: kaoyan_schools trg_audit_kaoyan_schools; Type: TRIGGER; Schema: public; Owner: kaoyan
--

CREATE TRIGGER trg_audit_kaoyan_schools AFTER INSERT OR DELETE OR UPDATE ON public.kaoyan_schools FOR EACH ROW EXECUTE FUNCTION public.fn_audit_log();


--
-- Name: kaoyan_schools trg_schools_updated; Type: TRIGGER; Schema: public; Owner: kaoyan
--

CREATE TRIGGER trg_schools_updated BEFORE UPDATE ON public.kaoyan_schools FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: kaoyan_admissions kaoyan_admissions_major_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_admissions
    ADD CONSTRAINT kaoyan_admissions_major_id_fkey FOREIGN KEY (major_id) REFERENCES public.kaoyan_majors(id) ON DELETE CASCADE;


--
-- Name: kaoyan_admissions kaoyan_admissions_school_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_admissions
    ADD CONSTRAINT kaoyan_admissions_school_id_fkey FOREIGN KEY (school_id) REFERENCES public.kaoyan_schools(id) ON DELETE CASCADE;


--
-- Name: kaoyan_colleges kaoyan_colleges_school_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_colleges
    ADD CONSTRAINT kaoyan_colleges_school_id_fkey FOREIGN KEY (school_id) REFERENCES public.kaoyan_schools(id) ON DELETE CASCADE;


--
-- Name: kaoyan_majors kaoyan_majors_college_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_majors
    ADD CONSTRAINT kaoyan_majors_college_id_fkey FOREIGN KEY (college_id) REFERENCES public.kaoyan_colleges(id) ON DELETE SET NULL;


--
-- Name: kaoyan_majors kaoyan_majors_school_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_majors
    ADD CONSTRAINT kaoyan_majors_school_id_fkey FOREIGN KEY (school_id) REFERENCES public.kaoyan_schools(id) ON DELETE CASCADE;


--
-- Name: kaoyan_notices kaoyan_notices_school_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_notices
    ADD CONSTRAINT kaoyan_notices_school_id_fkey FOREIGN KEY (school_id) REFERENCES public.kaoyan_schools(id) ON DELETE SET NULL;


--
-- Name: kaoyan_scorelines kaoyan_scorelines_major_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_scorelines
    ADD CONSTRAINT kaoyan_scorelines_major_id_fkey FOREIGN KEY (major_id) REFERENCES public.kaoyan_majors(id) ON DELETE CASCADE;


--
-- Name: kaoyan_scorelines kaoyan_scorelines_school_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: kaoyan
--

ALTER TABLE ONLY public.kaoyan_scorelines
    ADD CONSTRAINT kaoyan_scorelines_school_id_fkey FOREIGN KEY (school_id) REFERENCES public.kaoyan_schools(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict RBlXhaCLB5bdV6ewnLPsv2NyqZPu9G0HStfPqNfqVbMp4rB203J3tHL4rKpGR82

