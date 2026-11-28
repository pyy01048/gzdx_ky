import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { request } from '../../api/client'
import { kaoyanApi } from '../../api/kaoyanApi'
import { useAuth } from '../../auth/AuthContext'
import {
  Alert, Badge, Button, Card, CardHead, Chip, Empty, IconButton, Input, PageHeader,
  Select, Skeleton, Spinner, toastErr, toastOk, cx,
} from '../ui'
import {
  AlertCircle, ArrowRight, BookOpen, Calendar, GraduationCap, RefreshCw, Search,
  Sparkles, Trophy,
} from '../icons'

/* ============================================================================
 * 上岸经验广场（Alumni）
 *
 * 公开浏览已审核通过的上岸经验卡，按院校 / 专业 / 年份筛选。
 * 数据源：GET /api/experiences?school_id=&major_id=&year=&status=approved
 * 提交入口：登录且 role=alumni 时显示「我要分享」按钮，跳转 /contribute。
 * ========================================================================== */

const PAGE_SIZE = 12

const STATUS_META = {
  approved: { label: '已审核', tone: 'success' },
  pending: { label: '待审核', tone: 'warning' },
  rejected: { label: '已驳回', tone: 'danger' },
}

function fmtDate(s) {
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString('zh-CN')
}

function numOrNull(v) {
  const s = String(v ?? '').trim()
  if (!s) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

/* 依据 evidence_json 渲染为键值对列表；后端可能返回对象或字符串，均容错 */
function evidenceEntries(ev) {
  if (!ev) return []
  if (typeof ev === 'string') return ev.trim() ? [['详情', ev]] : []
  if (Array.isArray(ev)) return ev.filter(Boolean).map((v, i) => [`依据 ${i + 1}`, String(v)])
  if (typeof ev === 'object') {
    return Object.entries(ev)
      .filter(([, v]) => v != null && String(v).trim() !== '')
      .map(([k, v]) => [k, String(v)])
  }
  return []
}

function ExperienceCard({ item, schoolMap }) {
  const schoolName = schoolMap[item.school_id] || item.school_name || `院校 #${item.school_id || '?'}`
  const majorName = item.major_name || (item.major_id ? `专业 #${item.major_id}` : '未指定')
  const evidence = evidenceEntries(item.evidence_json || item.evidence)
  return (
    <Card variant="tonal" className="alumni-card">
      <CardHead
        icon={<GraduationCap size={17} />}
        title={(
          <span className="alumni-card__title">
            {schoolName}
            <Badge tone="outline" className="alumni-card__year">{item.year || '—'} 届</Badge>
          </span>
        )}
        sub={`${majorName}${item.score != null ? ` · 总分 ${item.score}` : ''}`}
        actions={item.status && item.status !== 'approved' ? (
          <Badge tone={STATUS_META[item.status]?.tone}>{STATUS_META[item.status]?.label || item.status}</Badge>
        ) : null}
      />

      {item.content ? (
        <p className="alumni-card__content">{item.content}</p>
      ) : null}

      {item.methodology ? (
        <div className="alumni-card__section">
          <div className="alumni-card__label"><BookOpen size={13} /> 方法论</div>
          <p className="alumni-card__text">{item.methodology}</p>
        </div>
      ) : null}

      {evidence.length > 0 ? (
        <div className="alumni-card__section">
          <div className="alumni-card__label"><Sparkles size={13} /> 备考依据</div>
          <dl className="alumni-card__evidence">
            {evidence.map(([k, v], i) => (
              <div key={i} className="alumni-card__ev-row">
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      <div className="alumni-card__foot">
        {item.author_name ? <span className="alumni-card__author">分享者：{item.author_name}</span> : null}
        {item.created_at ? <span className="alumni-card__date"><Calendar size={12} /> {fmtDate(item.created_at)}</span> : null}
      </div>
    </Card>
  )
}

export default function Alumni() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { user } = useAuth()

  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [schools, setSchools] = useState([])
  const [schoolsLoading, setSchoolsLoading] = useState(false)

  const schoolId = searchParams.get('school_id') || ''
  const majorId = searchParams.get('major_id') || ''
  const year = searchParams.get('year') || ''
  const page = Math.max(1, Number(searchParams.get('page')) || 1)

  const [draftSchool, setDraftSchool] = useState(schoolId)
  const [draftMajor, setDraftMajor] = useState(majorId)
  const [draftYear, setDraftYear] = useState(year)

  const reqRef = useRef(0)

  /* 院校候选：进入页面时拉一次（首页 200 条已覆盖主流院校） */
  const loadSchools = useCallback(async () => {
    setSchoolsLoading(true)
    try {
      const d = await kaoyanApi.schools({ page_size: 200, page: 1 })
      const items = Array.isArray(d) ? d : (d?.items || [])
      setSchools(items)
    } catch {
      setSchools([])
    } finally {
      setSchoolsLoading(false)
    }
  }, [])

  const load = useCallback(async () => {
    const requestId = ++reqRef.current
    setLoading(true)
    setError('')
    try {
      const params = { status: 'approved', page, page_size: PAGE_SIZE }
      if (schoolId) params.school_id = schoolId
      if (majorId) params.major_id = majorId
      if (year) params.year = year
      const d = await request('/experiences', { params })
      if (requestId !== reqRef.current) return
      const items = Array.isArray(d) ? d : (d?.items || [])
      setRows(items)
      setTotal(Array.isArray(d) ? items.length : (Number(d?.total) || items.length))
    } catch (e) {
      if (requestId === reqRef.current) setError(e?.message || '经验卡加载失败')
      setRows([])
      setTotal(0)
    } finally {
      if (requestId === reqRef.current) setLoading(false)
    }
  }, [schoolId, majorId, year, page])

  useEffect(() => { loadSchools() }, [loadSchools])
  useEffect(() => { load() }, [load])

  const schoolMap = useMemo(() => {
    const m = {}
    schools.forEach((s) => { m[s.id] = s.name })
    return m
  }, [schools])

  const schoolOptions = useMemo(
    () => [{ value: '', label: '全部院校' }, ...schools.map((s) => ({ value: String(s.id), label: s.name }))],
    [schools],
  )

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const curPage = Math.min(page, totalPages)

  const applyFilters = () => {
    const next = new URLSearchParams(searchParams)
    ;['school_id', 'major_id', 'year', 'page'].forEach((k) => next.delete(k))
    if (draftSchool) next.set('school_id', draftSchool)
    if (draftMajor) next.set('major_id', draftMajor)
    if (draftYear) next.set('year', draftYear)
    setSearchParams(next)
  }

  const resetFilters = () => {
    setDraftSchool('')
    setDraftMajor('')
    setDraftYear('')
    const next = new URLSearchParams(searchParams)
    ;['school_id', 'major_id', 'year', 'page'].forEach((k) => next.delete(k))
    setSearchParams(next)
  }

  const gotoPage = (p) => {
    const next = new URLSearchParams(searchParams)
    if (p > 1) next.set('page', String(p))
    else next.delete('page')
    setSearchParams(next)
  }

  const refresh = async () => {
    await load()
    toastOk('已刷新经验列表')
  }

  const activeFilterCount = [schoolId, majorId, year].filter(Boolean).length
  const isAlumni = user?.role === 'alumni'

  const header = (
    <PageHeader
      eyebrow="ALUMNI · 上岸经验广场"
      title="上岸经验"
      sub="已上岸前辈的实战经验 · 院校 / 专业 / 分数 / 方法论 / 备考依据"
      actions={(
        <>
          {isAlumni ? (
            <Button variant="gradient" icon={<GraduationCap size={16} />} onClick={() => navigate('/contribute')}>
              我要分享
            </Button>
          ) : null}
          <IconButton label="刷新列表" icon={<RefreshCw size={17} />} onClick={refresh} disabled={loading} />
        </>
      )}
    />
  )

  if (loading && rows.length === 0) {
    return (
      <div className="v3-stack alumni-page">
        {header}
        <Card>
          <Skeleton height={48} />
        </Card>
        <div className="alumni-grid">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} variant="tonal">
              <Skeleton height={20} width="60%" />
              <div style={{ height: 10 }} />
              <Skeleton height={12} width="80%" />
              <Skeleton height={12} width="70%" />
              <div style={{ height: 10 }} />
              <Skeleton height={48} />
            </Card>
          ))}
        </div>
      </div>
    )
  }

  if (error && rows.length === 0) {
    return (
      <div className="v3-stack alumni-page">
        {header}
        <Card>
          <Empty
            icon={<AlertCircle size={26} />}
            title="经验卡加载失败"
            text={error}
            action={<Button variant="tonal" icon={<RefreshCw size={16} />} onClick={load}>重新加载</Button>}
          />
        </Card>
      </div>
    )
  }

  return (
    <div className="v3-stack alumni-page">
      {header}

      <Alert tone="info" icon={<GraduationCap size={18} />}>
        <p>本页展示经管理员审核通过的上岸经验卡，包含院校、专业、年份、分数、方法论与备考依据，供择校与备考参考。</p>
      </Alert>

      {/* 筛选区 */}
      <Card className="alumni-filter">
        <div className="alumni-filter__row">
          <Select
            className="alumni-filter__school"
            aria-label="按院校筛选"
            value={draftSchool}
            onChange={(e) => setDraftSchool(e.target.value)}
            options={schoolOptions}
            disabled={schoolsLoading}
          />
          <Input
            type="number"
            placeholder="专业 ID"
            aria-label="按专业 ID 筛选"
            value={draftMajor}
            onChange={(e) => setDraftMajor(e.target.value)}
            className="alumni-filter__major"
          />
          <Input
            type="number"
            placeholder="年份，如 2025"
            aria-label="按年份筛选"
            value={draftYear}
            onChange={(e) => setDraftYear(e.target.value)}
            className="alumni-filter__year"
          />
          <Button icon={<Search size={15} />} onClick={applyFilters}>筛选</Button>
          {activeFilterCount > 0 ? (
            <Button variant="text" onClick={resetFilters}>清除</Button>
          ) : null}
        </div>
        <div className="alumni-filter__hint">
          {loading ? <span><Spinner size={12} /> 加载中…</span> : `共 ${total} 条经验 · 第 ${curPage}/${totalPages} 页`}
          {activeFilterCount > 0 ? <Badge tone="primary">{activeFilterCount} 项筛选</Badge> : null}
        </div>
      </Card>

      {/* 列表 */}
      {rows.length === 0 ? (
        <Card>
          <Empty
            icon={<GraduationCap size={26} />}
            title={activeFilterCount > 0 ? '没有匹配的经验' : '还没有上岸经验'}
            text={activeFilterCount > 0
              ? '当前筛选条件下没有已审核经验，试试清除筛选或换一组条件。'
              : '已上岸用户提交并经管理员审核后，经验卡会出现在这里。'}
            action={activeFilterCount > 0 ? (
              <Button variant="tonal" onClick={resetFilters}>清除筛选</Button>
            ) : isAlumni ? (
              <Button variant="gradient" icon={<GraduationCap size={16} />} onClick={() => navigate('/contribute')}>
                我来分享经验 <ArrowRight size={15} />
              </Button>
            ) : null}
          />
        </Card>
      ) : (
        <>
          <div className="alumni-grid">
            {rows.map((item) => (
              <ExperienceCard key={item.id} item={item} schoolMap={schoolMap} />
            ))}
          </div>

          {totalPages > 1 ? (
            <nav className="alumni-pager" aria-label="经验卡分页">
              <button type="button" aria-label="上一页" disabled={curPage <= 1} onClick={() => gotoPage(curPage - 1)}>«</button>
              <span className="alumni-pager__info">第 {curPage} / {totalPages} 页 · 共 {total} 条</span>
              <button type="button" aria-label="下一页" disabled={curPage >= totalPages} onClick={() => gotoPage(curPage + 1)}>»</button>
            </nav>
          ) : null}
        </>
      )}

      <p className="alumni-footnote">
        经验卡由已上岸用户提交，经管理员审核后公开展示。内容仅供参考，正式招生信息以目标院校研究生院官网为准。
      </p>
    </div>
  )
}
