import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import {
  Alert, Badge, Button, Card, CardHead, Chip, Dialog, Empty, Input, LoadingState,
  PageHeader, Pager, Segmented, Select, Spinner,
} from '../ui'
import {
  ArrowRight, BarChart3, Flame, InfoCircle, RefreshCw, Search,
} from '../icons'
import { Reveal } from '../motion'
import '../styles/kaoyan-core-v3.css'

/* ==========================================================================
   工学学科评估 · Aurora v3（119 分片 / data-assets/工学院校评价库）
   数据契约：/kaoyan/school-eval/{schools,schools/:id,disciplines,disciplines/:code/rank}
   口径纪律（源 README §3，页面必须呈现，不得省略）：
   - 第四轮只公布前 70%：未上榜≠差，文案「未上榜/未公布」
   - 0838/0839 未列入第四轮；第五轮未官方公开，不编造
   - joint 两地联合 / institute 科研院所单列：分组展示，不与普通高校混排
   - heat_tag 主观估算；data_status=3 补充院校待核验
   院校主档仅 329 行：一次拉全量后本地筛选/排序/分页（筛选零等待）；
   学科榜单按 code 服务端查询。空态即交付：接口无数据时显示 Empty，不造演示数据。
   ========================================================================== */

const DEFAULT_PAGE_SIZE = 24
const API_PAGE = 200 // 后端 MAX_PAGE_SIZE

const GRADE_TONE = (g) => {
  if (!g) return 'outline'
  if (g.startsWith('A')) return 'success'
  if (g.startsWith('B')) return 'primary'
  return 'warning'
}
const SCOPE_LABEL = { normal: '高校', joint: '两地联合', institute: '科研院所' }
const UNIT_LABEL = { 1: '高校', 2: '科研院所', 3: '军队院校' }

/* 985/211 本身即双一流建设高校，再挂一枚「双一流」是重复信息；
   只有层级看不出来的双非双一流才补这枚徽章（与院校库列表口径一致）。 */
const showDoubleFirst = (s) => Boolean(s?.is_double_first) && !s.is_985 && !s.is_211

const SORTS = [
  { value: 'eval_cnt', label: '上榜学科数' },
  { value: 'a_cnt', label: 'A 类学科数' },
  { value: 'bp_cnt', label: 'B+ 及以上数' },
  { value: 'name', label: '校名' },
]

const normProvince = (p) => String(p || '')
  .replace(/(壮族|回族|维吾尔)?自治区$/, '')
  .replace(/(省|市)$/, '')
  .trim() || '未知'

/* 卡片标题下已有「省市 · 单位类型」，上面一排徽标也已是 985/211/双一流/自划线；
   而库内简介首句固定是「××大学位于××××，985工程、211工程、双一流、34所自划线。」
   ——整句都在复述这两处已有信息，白占了卡片唯一一行描述。
   只在首句很短（≤60 字）且确含「位于」时剥离，避免误删实质内容。 */
function introBody(text) {
  const t = String(text || '').replace(/\s+/g, ' ').trim()
  const stop = t.indexOf('。')
  if (stop > 0 && stop <= 60 && t.slice(0, stop).includes('位于')) {
    return t.slice(stop + 1).trim()
  }
  return t
}

/* -------------------------------------------------------------------------- */
/* 详情弹窗（院校卡片 / 榜单校名共用）                                          */
/* -------------------------------------------------------------------------- */
function EvalDetailDialog({ schoolId, onClose }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    if (!schoolId) return undefined
    let dead = false
    setData(null); setErr('')
    kaoyanApi.evalSchoolDetail(schoolId)
      .then((d) => { if (!dead) setData(d) })
      .catch((e) => { if (!dead) setErr(e?.message || '加载失败') })
    return () => { dead = true }
  }, [schoolId])

  const intro = introBody(data?.intro)

  return (
    <Dialog open={!!schoolId} onClose={onClose} wide
      title={data ? data.name : '院校评估详情'}
      sub={data ? `${normProvince(data.province)}${data.city ? ` · ${data.city}` : ''} · ${UNIT_LABEL[data.unit_type] || '招生单位'}` : ''}
      footer={data?.kaoyan_school_id ? (
        <Link className="v3-btn v3-btn--filled" to={`/kaoyan/schools/${data.kaoyan_school_id}`} onClick={onClose}>
          查看招生数据 <ArrowRight size={15} />
        </Link>
      ) : null}
    >
      {err ? <Alert tone="danger">{err}</Alert> : null}
      {!data && !err ? <LoadingState text="加载评估明细…" /> : null}
      {data ? (
        <div className="v3-stack" style={{ gap: 16 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {data.is_985 ? <Badge tone="primary">985</Badge> : null}
            {data.is_211 ? <Badge tone="primary">211</Badge> : null}
            {showDoubleFirst(data) ? <Badge tone="success">双一流</Badge> : null}
            {data.is_self_marked ? <Badge tone="warning">自划线</Badge> : null}
            {data.data_status === 3 ? <Badge tone="danger" title={data.verify_note || ''}>待核验</Badge> : null}
            {data.heat_tag ? <Badge tone="outline" title={data.heat_note || '主观估算，仅供参考'}><Flame size={11} /> 热度·{data.heat_tag}</Badge> : null}
          </div>
          {intro ? <p className="v3-body" style={{ margin: 0 }}>{intro}</p> : null}
          {data.evaluation ? (
            <div>
              <div className="v3-eyebrow">客观评价</div>
              <p className="v3-body" style={{ margin: '4px 0 0' }}>{data.evaluation}</p>
            </div>
          ) : null}
          {data.feature ? (
            <div>
              <div className="v3-eyebrow">报考特色</div>
              <p className="v3-body" style={{ margin: '4px 0 0' }}>{data.feature}</p>
            </div>
          ) : null}
          {Array.isArray(data.strengths) && data.strengths.length ? (
            <div>
              <div className="v3-eyebrow">优势学科</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                {/* strengths_json 是对象数组 [{code,name,grade,double_first}]，不是字符串数组 */}
                {data.strengths.map((s) => (
                  <Badge key={s.code || s.name} tone={GRADE_TONE(s.grade)}>
                    {s.name} {s.grade}{s.double_first ? ' · 双一流' : ''}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}
          <div>
            <div className="v3-eyebrow">第四轮学科评估（{data.evals?.length || 0} 个上榜）</div>
            {data.evals?.length ? (
              <div className="v3-stack" style={{ gap: 4, marginTop: 6 }}>
                {data.evals.map((e) => (
                  <div key={e.discipline_code} className="v3-row" style={{ justifyContent: 'space-between', gap: 8 }}>
                    <span className="v3-body">{e.discipline_code} {e.discipline_name}</span>
                    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                      {e.eval_scope !== 'normal' ? <Badge tone="outline">{SCOPE_LABEL[e.eval_scope] || e.eval_scope}</Badge> : null}
                      <Badge tone={GRADE_TONE(e.grade)}>{e.grade}</Badge>
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="v3-caption" style={{ margin: '6px 0 0' }}>未上榜/未公布：不代表学科差，可能未参评或位于未公布的后 30%。</p>
            )}
          </div>
          {data.double_first_disciplines?.length ? (
            <div>
              <div className="v3-eyebrow">第二轮双一流建设学科（工学）</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                {data.double_first_disciplines.map((s) => (
                  <Badge key={s.discipline_code} tone="gradient">{s.discipline_code} {s.discipline_name}</Badge>
                ))}
              </div>
            </div>
          ) : null}
          {Array.isArray(data.industry_tags) && data.industry_tags.length ? (
            <div>
              <div className="v3-eyebrow">行业标签</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
                {data.industry_tags.map((t) => <Badge key={t} tone="outline">{t}</Badge>)}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </Dialog>
  )
}

/* -------------------------------------------------------------------------- */
/* 院校总览                                                                    */
/* -------------------------------------------------------------------------- */
function SchoolCard({ s, onOpen }) {
  const desc = introBody(s.intro)
  return (
    <Card interactive className="v3-stack" style={{ gap: 10, padding: 16, height: '100%' }} role="button" tabIndex={0}
      onClick={() => onOpen(s.id)}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(s.id) } }}
      aria-label={`查看 ${s.name} 评估详情`}>
      <div className="v3-row" style={{ justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <div>
          <div className="v3-title" style={{ fontWeight: 600 }}>{s.name}</div>
          <div className="v3-caption">{normProvince(s.province)}{s.city ? ` · ${s.city}` : ''} · {UNIT_LABEL[s.unit_type] || '—'}</div>
        </div>
        {s.heat_tag ? <Badge tone="outline" title={s.heat_note || '主观估算，仅供参考'}><Flame size={11} /> {s.heat_tag}</Badge> : null}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
        {s.is_985 ? <Badge tone="primary">985</Badge> : null}
        {s.is_211 ? <Badge tone="primary">211</Badge> : null}
        {showDoubleFirst(s) ? <Badge tone="success">双一流</Badge> : null}
        {s.is_self_marked ? <Badge tone="warning">自划线</Badge> : null}
        {s.data_status === 3 ? <Badge tone="danger">待核验</Badge> : null}
      </div>
      <p className="v3-caption" style={{ margin: 0, minHeight: 32 }}>
        {desc ? (desc.length > 72 ? `${desc.slice(0, 72)}…` : desc) : '暂无院校简介'}
      </p>
      <div className="v3-row" style={{ gap: 18 }}>
        <span className="v3-caption"><b style={{ fontSize: 16 }}>{s.eval_cnt}</b> 上榜学科</span>
        <span className="v3-caption"><b style={{ fontSize: 16, color: 'var(--v3-success, inherit)' }}>{s.a_cnt}</b> A 类</span>
        <span className="v3-caption"><b style={{ fontSize: 16 }}>{s.bp_cnt}</b> B+ 及以上</span>
      </div>
      {Array.isArray(s.industry_tags) && s.industry_tags.length ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
          {s.industry_tags.slice(0, 3).map((t) => <Badge key={t} tone="outline">{t}</Badge>)}
        </div>
      ) : null}
    </Card>
  )
}

function SchoolsView({ schools, onOpen }) {
  const [q, setQ] = useState('')
  const [province, setProvince] = useState('')
  const [unitType, setUnitType] = useState('')
  const [flags, setFlags] = useState({ is_985: false, is_211: false, is_double_first: false, is_self_marked: false })
  const [sort, setSort] = useState('eval_cnt')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const gridRef = useRef(null)

  const provinces = useMemo(
    () => [...new Set(schools.map((s) => normProvince(s.province)))].sort((a, b) => a.localeCompare(b, 'zh')),
    [schools],
  )
  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase()
    const list = schools.filter((s) => {
      if (kw && !String(s.name).toLowerCase().includes(kw)) return false
      if (province && normProvince(s.province) !== province) return false
      if (unitType && s.unit_type !== Number(unitType)) return false
      return Object.entries(flags).every(([k, on]) => !on || s[k])
    })
    list.sort((a, b) => (sort === 'name'
      ? String(a.name).localeCompare(String(b.name), 'zh')
      : (b[sort] - a[sort]) || String(a.name).localeCompare(String(b.name), 'zh')))
    return list
  }, [schools, q, province, unitType, flags, sort])

  useEffect(() => { setPage(1) }, [q, province, unitType, flags, sort])
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const cur = Math.min(page, pages)
  const items = filtered.slice((cur - 1) * pageSize, cur * pageSize)

  const toggle = (k) => setFlags((p) => ({ ...p, [k]: !p[k] }))
  const hasFilter = Boolean(q.trim() || province || unitType || Object.values(flags).some(Boolean))
  const resetFilters = () => {
    setQ('')
    setProvince('')
    setUnitType('')
    setFlags({ is_985: false, is_211: false, is_double_first: false, is_self_marked: false })
    setSort('eval_cnt')
  }

  return (
    <div className="v3-stack" style={{ gap: 14 }}>
      <Card style={{ padding: 14 }}>
        <div className="v3-stack" style={{ gap: 10 }}>
          <div className="v3-row" style={{ gap: 10, flexWrap: 'wrap' }}>
            <Input icon={<Search size={15} />} placeholder="搜索校名…" value={q}
              onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 260 }} aria-label="搜索校名" />
            {/* W5-1：筛选下拉换成全站统一的主题化 Select，并给出紧凑宽度，
                让「搜索 + 省份 + 类型 + 排序」排成一行工具条而不是一条一个 */}
            <Select value={province} onChange={(e) => setProvince(e.target.value)} aria-label="省份"
              style={{ width: 150 }}
              options={[{ value: '', label: '全部省份' }, ...provinces.map((p) => ({ value: p, label: p }))]} />
            <Select value={unitType} onChange={(e) => setUnitType(e.target.value)} aria-label="单位类型"
              style={{ width: 150 }}
              options={[{ value: '', label: '全部类型' }, { value: '1', label: '高校' }, { value: '2', label: '科研院所' }, { value: '3', label: '军队院校' }]} />
            <Select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="排序" style={{ width: 150 }} options={SORTS} />
          </div>
          <div className="v3-row" style={{ gap: 8, flexWrap: 'wrap' }}>
            <Chip active={flags.is_985} onClick={() => toggle('is_985')}>985</Chip>
            <Chip active={flags.is_211} onClick={() => toggle('is_211')}>211</Chip>
            <Chip active={flags.is_double_first} onClick={() => toggle('is_double_first')}>双一流</Chip>
            <Chip active={flags.is_self_marked} onClick={() => toggle('is_self_marked')}>自划线</Chip>
            <span className="v3-caption" style={{ marginLeft: 'auto' }}>共 {filtered.length} 所</span>
          </div>
        </div>
      </Card>

      {items.length ? (
        /* 翻页/换排序时整组重挂载，让卡片按既有 Reveal 节奏再入场一次，
           给「内容确实换了」一个视觉信号；筛选不重挂载，避免边打字边闪。 */
        <div key={`${cur}-${sort}`} className="kyv3-school-grid" ref={gridRef}>
          {items.map((s, i) => (
            <Reveal key={s.id} delay={Math.min(i, 10) * 24} style={{ height: '100%' }}>
              <SchoolCard s={s} onOpen={onOpen} />
            </Reveal>
          ))}
        </div>
      ) : (
        <Empty
          icon={<Search size={22} />}
          title={schools.length ? '没有符合条件的院校' : '评估数据暂未就绪'}
          text={schools.length
            ? '试试放宽筛选条件或清空关键词。'
            : '学科评估数据正在整理中，请稍后再来查看。'}
          action={hasFilter ? <Button variant="tonal" onClick={resetFilters}>清空筛选</Button> : null}
        />
      )}

      <Pager
        page={cur}
        pageSize={pageSize}
        total={filtered.length}
        unit="所"
        containerRef={gridRef}
        onChange={setPage}
        onPageSizeChange={(n) => { setPageSize(n); setPage(1) }}
      />
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* 按学科选校                                                                  */
/* -------------------------------------------------------------------------- */
function RankGroup({ title, hint, entries, onOpen }) {
  if (!entries.length) return null
  return (
    <Card>
      <CardHead icon={<BarChart3 size={16} />} title={title} sub={hint} />
      <div className="v3-stack" style={{ gap: 2, padding: '4px 0' }}>
        {entries.map((e, i) => (
          <div key={`${e.school_name}-${e.grade}`} className="v3-row kyv3-rank-row"
            style={{ justifyContent: 'space-between', gap: 10, padding: '7px 4px' }}>
            <span className="v3-row" style={{ gap: 10, minWidth: 0 }}>
              <span className="v3-caption" style={{ width: 30, textAlign: 'right', flexShrink: 0 }}>{i + 1}</span>
              <Badge tone={GRADE_TONE(e.grade)}>{e.grade}</Badge>
              {e.ky_school_id ? (
                <button type="button" className="kyv3-rank-name" onClick={() => onOpen(e.ky_school_id)}
                  title="查看院校评估详情">{e.school_name}</button>
              ) : (
                <span className="v3-body">{e.school_name}</span>
              )}
            </span>
            <span className="v3-row" style={{ gap: 5, flexShrink: 0 }}>
              {e.province ? <span className="v3-caption">{normProvince(e.province)}</span> : null}
              {e.is_985 ? <Badge tone="primary">985</Badge> : null}
              {e.is_211 ? <Badge tone="outline">211</Badge> : null}
              {showDoubleFirst(e) ? <Badge tone="success">双一流</Badge> : null}
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
}

function RankView({ disciplines, code, onCode, onOpen }) {
  const [rank, setRank] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!code) { setRank(null); return undefined }
    let dead = false
    setLoading(true); setErr(''); setRank(null)
    kaoyanApi.evalDisciplineRank(code)
      .then((d) => { if (!dead) setRank(d) })
      .catch((e) => { if (!dead) { setErr(e?.message || '加载失败'); setRank(null) } })
      .finally(() => { if (!dead) setLoading(false) })
    return () => { dead = true }
  }, [code])

  const options = useMemo(() => disciplines.map((d) => ({
    value: d.code,
    label: `${d.code} ${d.name}（${d.degree_type === 2 ? '专硕' : '学硕'} · ${d.school_cnt} 所）`,
  })), [disciplines])

  return (
    <div className="v3-stack" style={{ gap: 14 }}>
      <Card style={{ padding: 14 }}>
        <div className="v3-row" style={{ gap: 10, flexWrap: 'wrap' }}>
          <Select value={code} onChange={(e) => onCode(e.target.value)} aria-label="选择学科"
            options={[{ value: '', label: '选择工学学科…' }, ...options]} style={{ minWidth: 320 }} />
          {loading ? <span className="v3-caption" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Spinner size={13} /> 加载榜单</span> : null}
        </div>
      </Card>

      {err ? <Alert tone="danger">{err}</Alert> : null}
      {!code ? (
        <Empty icon={<BarChart3 size={22} />} title="按学科选校"
          text="选择一个工学学科，查看教育部第四轮学科评估榜单（A+ 到 C-），两地联合与科研院所单独分组。" />
      ) : null}
      {rank && rank.discipline?.note ? <Alert tone="info" icon={<InfoCircle size={15} />}>{rank.discipline.note}</Alert> : null}
      {rank && rank.total === 0 ? (
        <Empty icon={<InfoCircle size={22} />} title="该学科未公布第四轮评估结果"
          text={rank.discipline?.note || '未上榜/未公布不代表学科差；第五轮结果未官方公开。'} />
      ) : null}
      {rank && rank.total > 0 ? (
        <div key={rank.discipline.code} className="v3-stack v3-anim-in" style={{ gap: 14 }}>
          <div className="v3-caption">
            {rank.discipline.code} {rank.discipline.name} · 共 {rank.total} 家上榜（仅公布前 70%）
          </div>
          <RankGroup title="高校榜单" hint="按评估等级排序（A+ → C-）" entries={rank.groups.normal || []} onOpen={onOpen} />
          <RankGroup title="两地联合评估" hint="统一实体参评，校区共享结果；招生时各校区独立" entries={rank.groups.joint || []} onOpen={onOpen} />
          <RankGroup title="科研院所单列" hint="与高校分开排名，不可直接混排比较" entries={rank.groups.institute || []} onOpen={onOpen} />
        </div>
      ) : null}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* 页面主体                                                                    */
/* -------------------------------------------------------------------------- */
export default function KaoyanSchoolEval() {
  const [params, setParams] = useSearchParams()
  const view = params.get('view') === 'rank' ? 'rank' : 'schools'
  const code = params.get('disc') || ''
  const [schools, setSchools] = useState([])
  const [disciplines, setDisciplines] = useState([])
  const [caveats, setCaveats] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [detailId, setDetailId] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let dead = false
    setLoading(true); setErr('')
    ;(async () => {
      // 主档 329 行：并行拉全量分页 + 学科字典（无瀑布）
      const first = await kaoyanApi.evalSchools({ page: 1, page_size: API_PAGE })
      const restPages = Math.ceil((first.total || 0) / API_PAGE)
      const [rest, disc] = await Promise.all([
        Promise.all(Array.from({ length: Math.max(0, restPages - 1) }, (_, i) =>
          kaoyanApi.evalSchools({ page: i + 2, page_size: API_PAGE }))),
        kaoyanApi.evalDisciplines(),
      ])
      if (dead) return
      setSchools([...(first.items || []), ...rest.flatMap((r) => r.items || [])])
      setDisciplines(disc.items || [])
      setCaveats(first.caveats || disc.caveats || [])
    })()
      .catch((e) => { if (!dead) setErr(e?.message || '加载失败') })
      .finally(() => { if (!dead) setLoading(false) })
    return () => { dead = true }
  }, [reloadKey])

  const setView = useCallback((v) => {
    setParams((p) => {
      const n = new URLSearchParams(p)
      if (v === 'rank') n.set('view', 'rank'); else n.delete('view')
      return n
    }, { replace: true })
  }, [setParams])
  const setCode = useCallback((c) => {
    setParams((p) => {
      const n = new URLSearchParams(p)
      if (c) { n.set('view', 'rank'); n.set('disc', c) } else n.delete('disc')
      return n
    }, { replace: true })
  }, [setParams])
  const openDetail = useCallback((id) => setDetailId(id), [])

  return (
    <div className="v3-stack" style={{ gap: 16 }}>
      <PageHeader
        eyebrow="择校 · 08 工学"
        title="学科评估"
        sub="教育部第四轮学科评估 · 第二轮双一流建设学科 · 官方一手来源"
        actions={(
          <Segmented
            ariaLabel="视图切换"
            value={view}
            onChange={setView}
            options={[{ value: 'schools', label: '院校总览' }, { value: 'rank', label: '按学科选校' }]}
          />
        )}
      />

      {err ? (
        <Alert tone="danger" icon={<RefreshCw size={15} />}>
          {err} <Button variant="text" size="sm" onClick={() => setReloadKey((k) => k + 1)}>重试</Button>
        </Alert>
      ) : null}

      {loading ? <LoadingState text="加载学科评估数据…" /> : err && !schools.length ? null : (
        <div key={view} className="v3-anim-in">
          {view === 'schools'
            ? <SchoolsView schools={schools} onOpen={openDetail} />
            : <RankView disciplines={disciplines} code={code} onCode={setCode} onOpen={openDetail} />}
        </div>
      )}

      {caveats.length ? (
        <Alert tone="info" icon={<InfoCircle size={15} />}>
          <div className="v3-stack" style={{ gap: 3 }}>
            <b>数据口径说明</b>
            {caveats.map((c) => <span key={c} className="v3-caption">{c}</span>)}
            <span className="v3-caption">来源：教育部第四轮学科评估官方 PDF（2017-12）+ 第二轮双一流名单（2022-02），双源交叉核验。</span>
          </div>
        </Alert>
      ) : null}

      <EvalDetailDialog schoolId={detailId} onClose={() => setDetailId(null)} />
    </div>
  )
}
