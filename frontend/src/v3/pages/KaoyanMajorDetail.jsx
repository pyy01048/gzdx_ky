import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import { useAuth } from '../../auth/AuthContext'
import {
  Alert, Badge, Button, Card, CardHead, Chip, Empty, LoadingState, PageHeader,
} from '../ui'
import {
  ArrowRight, BookOpen, CheckCircle2, ChevronLeft, ExternalLink, GraduationCap,
  InfoCircle, Layers,
} from '../icons'
import '../styles/kaoyan-core-v3.css'

const RESOURCE_TYPE_LABELS = {
  textbook: '教材',
  syllabus: '考试大纲',
  outline: '复习提纲',
  notes: '笔记',
  courseware: '课件',
  past_paper: '真题资料',
  link: '资料链接',
  other: '其他资源',
}
const VERIFICATION_LABELS = {
  verified: '已核验',
  unverified: '待核验',
  rejected: '已拒绝',
}

/** 把任意输入规整为正整数 ID，非法值返回空串。 */
export function positiveId(value) {
  return /^\d+$/.test(String(value || '')) && Number(value) > 0 ? Number(value) : ''
}

/** 拼接专业详情页路径，任一 ID 非正整数则返回空串以阻止跳转。 */
export function buildMajorDetailPath({ majorId, schoolId, subjectId }) {
  if (!positiveId(majorId)) return ''
  const params = new URLSearchParams()
  if (positiveId(schoolId)) params.set('school_id', String(schoolId))
  params.set('major_id', String(majorId))
  if (positiveId(subjectId)) params.set('subject_id', String(subjectId))
  return `/kaoyan/majors/${majorId}?${params}`
}

export function buildMajorPracticePath({ schoolId, majorId, subjectId }) {
  if (![schoolId, majorId, subjectId].every(positiveId)) return ''
  return `/quiz?tab=engineering08&school_id=${schoolId}&major_id=${majorId}&subject_id=${subjectId}`
}

export function safeExternalUrl(value) {
  if (!value || typeof value !== 'string') return ''
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) ? url.href : ''
  } catch {
    return ''
  }
}

function listText(value) {
  if (Array.isArray(value)) return value.filter(Boolean).join('、')
  return value ? String(value) : ''
}

function sourceText(source) {
  if (!source || typeof source !== 'object' || Array.isArray(source)) return '来源未标注'
  const named = source.source_name || source.name || source.provider || source.method
  if (named) return String(named)
  const entries = Object.entries(source).filter(([, value]) => value != null && value !== '')
  return entries.length ? entries.map(([key, value]) => `${key}: ${String(value)}`).join('；') : '来源未标注'
}

function Fact({ label, children }) {
  return (
    <div className="kyv3-fact">
      <span>{label}</span>
      <b>{children || '未收录'}</b>
    </div>
  )
}

function ExternalResourceLink({ url, children }) {
  const href = safeExternalUrl(url)
  return href ? (
    <a href={href} target="_blank" rel="noreferrer" className="v3-btn v3-btn--ghost v3-btn--sm">
      {children} <ExternalLink size={14} aria-hidden="true" />
    </a>
  ) : null
}

export default function KaoyanMajorDetail() {
  const { id } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const { user } = useAuth()
  const ownerKey = user?.id == null ? 'guest' : String(user.id)
  const [reloadToken, setReloadToken] = useState(0)
  const [state, setState] = useState({ status: 'loading', data: null, error: '', notFound: false })
  const majorId = positiveId(id)
  const queryMajorId = positiveId(searchParams.get('major_id'))
  const querySchoolId = positiveId(searchParams.get('school_id'))
  const querySubjectId = positiveId(searchParams.get('subject_id'))
  const invalidQuery = ['major_id', 'school_id', 'subject_id'].some((key) => (
    searchParams.get(key) && !positiveId(searchParams.get(key))
  ))
  const mismatchedMajor = queryMajorId && queryMajorId !== majorId

  useEffect(() => {
    if (!majorId || invalidQuery || mismatchedMajor) {
      setState({
        status: 'error',
        data: null,
        notFound: false,
        error: !majorId || invalidQuery
          ? '链接中的专业或范围参数格式无效'
          : '链接中的 major_id 与专业路径不一致',
      })
      return undefined
    }
    const controller = new AbortController()
    let alive = true
    setState({ status: 'loading', data: null, error: '', notFound: false })
    const params = {}
    if (querySchoolId) params.school_id = querySchoolId
    if (querySubjectId) params.subject_id = querySubjectId
    kaoyanApi.majorDetail(majorId, params, { signal: controller.signal })
      .then((data) => {
        if (alive) setState({ status: 'ready', data, error: '', notFound: false })
      })
      .catch((error) => {
        if (!alive || error?.name === 'AbortError') return
        setState({
          status: 'error',
          data: null,
          notFound: Number(error?.status) === 404,
          error: error?.message || '专业详情加载失败',
        })
      })
    return () => {
      alive = false
      controller.abort()
    }
  }, [majorId, ownerKey, querySchoolId, querySubjectId, invalidQuery, mismatchedMajor, reloadToken])

  const data = state.data
  const matchedSubjects = useMemo(() => (
    Array.isArray(data?.matched_subjects) ? data.matched_subjects : []
  ), [data])
  const activeSubject = matchedSubjects.find((item) => item.id === querySubjectId)
    || matchedSubjects.find((item) => item.id === data?.selected_subject_id)
    || matchedSubjects[0]
    || null
  const practicePath = buildMajorPracticePath({
    schoolId: data?.school?.id,
    majorId: data?.major?.id,
    subjectId: activeSubject?.id,
  })
  const resources = Array.isArray(data?.resource_pack?.items) ? data.resource_pack.items : []
  const activeResources = activeSubject
    ? resources.filter((item) => item.subject_id === activeSubject.id)
    : []

  const selectSubject = useCallback((subjectId) => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous)
      next.set('major_id', String(data.major.id))
      next.set('school_id', String(data.school.id))
      next.set('subject_id', String(subjectId))
      return next
    }, { replace: true })
  }, [data?.major?.id, data?.school?.id, setSearchParams])

  if (state.status === 'loading') {
    return <div className="kyv3-page"><LoadingState text="正在加载专业详情…" /></div>
  }

  if (state.status !== 'ready' || !data?.major || !data?.school) {
    return (
      <div className="kyv3-page">
        <Link className="v3-btn v3-btn--ghost" to="/kaoyan/schools">
          <ChevronLeft size={16} aria-hidden="true" /> 返回院校库
        </Link>
        <Card style={{ marginTop: 16 }}>
          <Empty
            title={state.notFound ? '专业详情不存在或不在当前范围' : '专业详情加载失败'}
            text={state.error || '请检查链接中的院校、专业和科目参数。'}
            action={<Button onClick={() => setReloadToken((value) => value + 1)}>重试</Button>}
          />
        </Card>
      </div>
    )
  }

  const { major, school, discipline, resource_pack: resourcePack } = data
  const location = [school.province, school.city].filter(Boolean).join(' · ')

  return (
    <div className="kyv3-page">
      <Link className="v3-btn v3-btn--ghost v3-btn--sm" to={`/kaoyan/schools/${school.id}`}>
        <ChevronLeft size={15} aria-hidden="true" /> 返回{school.name}
      </Link>

      <PageHeader
        eyebrow="ENGINEERING 08 · 专业实体"
        title={major.name}
        sub={[school.name, location, discipline?.name].filter(Boolean).join(' · ')}
        actions={practicePath ? (
          <Link className="v3-btn v3-btn--filled" to={practicePath}>
            进入该科练习 <ArrowRight size={16} aria-hidden="true" />
          </Link>
        ) : (
          <Button disabled>暂无可进入的匹配科目</Button>
        )}
      />

      <Card>
        <CardHead
          icon={<GraduationCap size={18} aria-hidden="true" />}
          title="专业基本信息"
          sub="仅展示招生目录中的显式字段，不按院校或专业名称推断学院。"
        />
        <div className="kyv3-facts">
          <Fact label="专业代码">{major.code}</Fact>
          <Fact label="学位类型">{major.degree_type}</Fact>
          <Fact label="所属学科">{discipline ? `${discipline.code} ${discipline.name}` : major.subject_code}</Fact>
          <Fact label="所属院校"><Link to={`/kaoyan/schools/${school.id}`}>{school.name}</Link></Fact>
          <Fact label="所在地">{location}</Fact>
          <Fact label="研究方向">{major.research_direction}</Fact>
          <Fact label="院校层级">{school.level}</Fact>
          <Fact label="院校数据来源">{school.data_source}</Fact>
        </div>
        <Alert tone="info" icon={<InfoCircle size={18} />}>
          学院归属未做名称推断；学校级教材关系也不会自动视为该专业指定教材。
        </Alert>
      </Card>

      <Card style={{ marginTop: 16 }}>
        <CardHead
          icon={<Layers size={18} aria-hidden="true" />}
          title="专业匹配科目"
          sub="仅采用 207 中 match_status=matched 且已关联 subjects 的记录。"
          actions={<Badge tone="primary">当前可见题目 {Number(data.question_count_total) || 0}</Badge>}
        />
        {matchedSubjects.length ? (
          <>
            <div className="kyv3-subject-chips" aria-label="选择匹配科目">
              {matchedSubjects.map((subject) => (
                <Chip
                  key={subject.id}
                  active={activeSubject?.id === subject.id}
                  aria-pressed={activeSubject?.id === subject.id}
                  aria-label={`${subject.name}，可见题 ${subject.question_count}`}
                  onClick={() => selectSubject(subject.id)}
                >
                  <code>{subject.code || '科目'}</code>
                  <span>{subject.short_name || subject.name}</span>
                  <span>可见题 {subject.question_count}</span>
                </Chip>
              ))}
            </div>
            {activeSubject ? (
              <div className="kyv3-soft-note" style={{ marginTop: 12 }}>
                当前科目：<b>{activeSubject.name}</b>
                {activeSubject.exam_subject_codes?.length ? ` · 目录代码 ${activeSubject.exam_subject_codes.join('、')}` : ''}
                {activeSubject.exam_subject_names?.length ? ` · 目录名称 ${activeSubject.exam_subject_names.join('、')}` : ''}
                {activeSubject.confidence != null ? ` · 匹配置信度 ${Math.round(activeSubject.confidence * 100)}%` : ''}
                {` · 匹配来源 ${activeSubject.match_sources?.length || 0} 条`}
              </div>
            ) : null}
          </>
        ) : (
          <Empty
            title="暂无已匹配的考试科目"
            text="207 目录中没有该专业的 matched 记录；ambiguous 或 unmatched 记录不会被当作可练习科目。"
          />
        )}
      </Card>

      <Card style={{ marginTop: 16 }}>
        <CardHead
          icon={<BookOpen size={18} aria-hidden="true" />}
          title={activeSubject ? `${activeSubject.name} · 教材与资源包` : '教材与资源包'}
          sub="只展示 210 中显式登记的专业—科目资源，按核验状态与排序展示。"
        />
        {resourcePack?.status === 'migration_pending' ? (
          <Alert tone="warning" icon={<InfoCircle size={18} />}>
            专业资源表尚未执行 210 迁移，当前没有可展示的资源；不会用学校级教材数据兜底。
          </Alert>
        ) : !activeSubject ? (
          <Empty title="暂无资源范围" text="请先选择已匹配的考试科目。" />
        ) : activeResources.length ? (
          <div className="kyv3-major-list">
            {activeResources.map((resource) => {
              const resourceUrl = safeExternalUrl(resource.url)
              const sourceUrl = safeExternalUrl(resource.source_url)
              const textbook = resource.textbook
              return (
                <article key={resource.id} className="kyv3-major-list__item" style={{ padding: '14px 0', borderBottom: '1px solid var(--v3-border, rgba(127,127,127,.18))' }}>
                  <div className="v3-row" style={{ justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                    <strong>{resource.title}</strong>
                    <div className="v3-row" style={{ gap: 6, flexWrap: 'wrap' }}>
                      <Badge>{RESOURCE_TYPE_LABELS[resource.resource_type] || resource.resource_type}</Badge>
                      <Badge tone={resource.verification_status === 'verified' ? 'success' : undefined}>
                        {VERIFICATION_LABELS[resource.verification_status] || resource.verification_status}
                      </Badge>
                      <Badge>{resource.visibility === 'personal' ? '我的私有资源' : '公开资源'}</Badge>
                    </div>
                  </div>
                  {textbook ? (
                    <p className="v3-caption" style={{ marginTop: 8 }}>
                      教材：{[textbook.title, textbook.authors && listText(textbook.authors), textbook.publisher,
                        textbook.edition && `${textbook.edition}版`, textbook.isbn && `ISBN ${textbook.isbn}`]
                        .filter(Boolean).join(' · ')}
                    </p>
                  ) : null}
                  {resource.description ? <p style={{ margin: '8px 0' }}>{resource.description}</p> : null}
                  <div className="v3-row" style={{ justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                    <span className="v3-caption">来源：{sourceText(resource.source)}</span>
                    <div className="v3-row">
                      {resourceUrl ? <ExternalResourceLink url={resourceUrl}>打开资源</ExternalResourceLink> : null}
                      {sourceUrl ? <ExternalResourceLink url={sourceUrl}>查看来源</ExternalResourceLink> : null}
                    </div>
                  </div>
                </article>
              )
            })}
          </div>
        ) : (
          <Empty
            title="该科目暂无专业级教材或资源"
            text="尚未在 210 中登记可公开或仅自己可见的资源。textbook_schools 只证明学校使用过教材，不能证明该专业指定。"
          />
        )}
        {resourcePack?.status === 'ready' && resources.length === 0 ? (
          <div className="v3-row" style={{ marginTop: 12 }}>
            <CheckCircle2 size={16} aria-hidden="true" />
            <span className="v3-caption">资源数据隔离已生效：公开资源或当前用户私有资源。</span>
          </div>
        ) : null}
      </Card>
    </div>
  )
}
