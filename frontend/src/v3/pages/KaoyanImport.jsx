import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { kaoyanApi } from '../../api/kaoyanApi'
import {
  Alert, Badge, Button, Card, CardHead, Empty, PageHeader, Progress, SectionHead, Skeleton,
  toastErr, toastOk,
} from '../ui'
import {
  BarChart3, BellRing, BookOpen, CheckCircle2, Clock, Copy, Crosshair, Database,
  FileText, Flag, RefreshCw, Rocket, School, Tag,
} from '../icons'
import '../styles/admin-ops-v3.css'

/* ============================================================================
   数据管理 · 采集中心（Aurora v3）
   三条真实采集链路：工科定向采集 / 国家线回填 / 公告采集。
   采集历史直接读取 /api/kaoyan/collection/runs（后端返回裸数组）。
   ========================================================================== */

const COLLECT_SOURCES = [
  {
    key: 'engineering',
    label: '工科定向采集',
    icon: Crosshair,
    desc: '研招网 07/08 门类院校增量 + 电子 / 通信 / 408 / 光学 / 电气 / AI 专业代码集过滤。耗时较长，2–5s/页礼貌延迟。',
    hint: '全量采集 · 手动触发',
  },
  {
    key: 'national_line',
    label: '国家线回填',
    icon: Flag,
    desc: '官方核实的历年国家线（A 区 工学 / 电子信息）回填 kaoyan_scorelines，补齐「超国家线差值」标注的数据底座。',
    hint: '官方静态数据 · 轻量',
  },
  {
    key: 'notices',
    label: '公告采集',
    icon: BellRing,
    desc: '各校研究生院官网公告列表页（招生公告 / 简章 / 复试 / 调剂 / 录取），仅采集 robots 允许的站点。',
    hint: '研究生院官网 · 增量',
  },
]

const RUN_SOURCE_LABEL = {
  engineering: '工科定向采集',
  national_line: '国家线回填',
  notices: '公告采集',
  spider_yz: '研招网爬虫',
}

const RUN_STATUS = {
  success: { label: '成功', tone: 'success' },
  failed: { label: '失败', tone: 'danger' },
  running: { label: '运行中', tone: 'warning' },
  partial: { label: '部分成功', tone: 'warning' },
  blocked: { label: '已阻断', tone: 'warning' },
}

const fmtRunTime = (v) => (v ? String(v).slice(0, 19).replace('T', ' ') : '—')
const sourceLabel = (source) => RUN_SOURCE_LABEL[source] || source || '未知来源'

export default function KaoyanImport() {
  const navigate = useNavigate()
  const [stats, setStats] = useState(null)
  const [subjects, setSubjects] = useState([])
  const [noticeStats, setNoticeStats] = useState(null)
  const [runs, setRuns] = useState([])
  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [lastSync, setLastSync] = useState(null)
  const [busy, setBusy] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [lastResult, setLastResult] = useState(null)

  const seqRef = useRef(0)
  const mountedRef = useRef(true)
  const collectRef = useRef(null)

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const loadAll = useCallback(async ({ quiet = false } = {}) => {
    const seq = ++seqRef.current
    if (quiet) setRefreshing(true)
    else setLoading(true)

    const [statsR, subjectsR, noticesR, runsR] = await Promise.allSettled([
      kaoyanApi.stats(),
      kaoyanApi.subjects(),
      kaoyanApi.noticeTypeStats(),
      kaoyanApi.collectionRuns(),
    ])
    if (!mountedRef.current || seq !== seqRef.current) return { ok: false, stale: true }

    const nextErrors = {}
    if (statsR.status === 'fulfilled') setStats(statsR.value || null)
    else nextErrors.stats = statsR.reason?.message || '无法读取数据概览'

    if (subjectsR.status === 'fulfilled') {
      setSubjects(Array.isArray(subjectsR.value) ? subjectsR.value : [])
    } else {
      setSubjects([])
      nextErrors.subjects = subjectsR.reason?.message || '无法读取学科覆盖'
    }

    if (noticesR.status === 'fulfilled') setNoticeStats(noticesR.value || null)
    else nextErrors.notices = noticesR.reason?.message || '无法读取公告类型分布'

    if (runsR.status === 'fulfilled') {
      // 后端 /kaoyan/collection/runs 实测返回裸数组；同时兼容对象包裹的旧部署
      const d = runsR.value
      setRuns(Array.isArray(d) ? d : (d?.runs || d?.items || []))
    } else {
      nextErrors.runs = runsR.reason?.message || '无法读取采集历史'
    }

    setErrors(nextErrors)
    setLoading(false)
    setRefreshing(false)
    if (statsR.status === 'fulfilled' || subjectsR.status === 'fulfilled'
      || noticesR.status === 'fulfilled' || runsR.status === 'fulfilled') {
      setLastSync(new Date())
    }
    return { ok: Object.keys(nextErrors).length === 0, stale: false }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  const manualRefresh = async () => {
    const res = await loadAll({ quiet: true })
    if (res.stale) return
    if (res.ok) toastOk('采集数据已刷新')
    else toastErr('部分数据刷新失败，请查看对应区块提示')
  }

  /* 采集中显示真实已等待秒数，不伪造进度百分比 */
  useEffect(() => {
    if (!busy) {
      setElapsed(0)
      return undefined
    }
    const startedAt = Date.now()
    setElapsed(0)
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [busy])

  const runCollect = async (source) => {
    if (busy) return
    setBusy(source)
    setLastResult(null)
    try {
      const result = await kaoyanApi.refresh({ source, dry_run: false })
      setLastResult({ source, ok: true, data: result, at: new Date() })
      toastOk(`${sourceLabel(source)} 采集完成`)
      await loadAll({ quiet: true })
    } catch (e) {
      setLastResult({ source, ok: false, error: e?.message || '采集失败', at: new Date() })
      toastErr(`采集失败：${e?.message || e}`)
    } finally {
      if (mountedRef.current) setBusy('')
    }
  }

  const noticeTypes = useMemo(() => {
    const entries = Object.entries(noticeStats?.by_type || {})
    return entries
      .map(([type, count]) => ({ type, count: Number(count) || 0 }))
      .sort((a, b) => b.count - a.count)
  }, [noticeStats])

  const noticeMax = noticeTypes.reduce((max, item) => Math.max(max, item.count), 0)

  const subjectList = useMemo(() => {
    const seen = new Set()
    return (Array.isArray(subjects) ? subjects : []).filter((item) => {
      const key = item?.code ?? item?.name
      if (key == null || seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [subjects])

  const resultText = useMemo(() => {
    if (!lastResult?.ok) return ''
    try {
      return JSON.stringify(lastResult.data?.results?.[0] ?? lastResult.data, null, 2)
    } catch {
      return String(lastResult.data)
    }
  }, [lastResult])

  const resultPreview = resultText.slice(0, 1500)
  const resultTruncated = resultText.length > 1500

  const copyResult = async () => {
    if (!resultText) return
    try {
      await navigator.clipboard.writeText(resultText)
      toastOk('采集结果已复制')
    } catch {
      toastErr('复制失败，请手动选择结果文本')
    }
  }

  const showInitialSkeleton = loading && !stats && !errors.stats
  const collectDisabled = !!busy

  return (
    <div className="v3-ops v3-ki">
      <PageHeader
        eyebrow="数据管理 / 采集中心"
        title="采集中心"
        sub="工科定向采集 · 国家线回填 · 公告采集 · 采集历史。所有采集任务由后端同步执行，并遵守 robots.txt 与礼貌延迟。"
        actions={(
          <>
            <Button variant="ghost" icon={<RefreshCw size={15} />} loading={refreshing} onClick={manualRefresh}>
              刷新
            </Button>
            <Button
              variant="outline"
              icon={<School size={15} />}
              onClick={() => navigate('/admin/crawl-sources')}
            >
              院校采集源
            </Button>
            <Button
              variant="filled"
              icon={<Rocket size={15} />}
              onClick={() => collectRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            >
              立即采集
            </Button>
          </>
        )}
      />

      {errors.stats && (
        <Alert tone="danger">
          <div className="v3-ops-inline">
            <span>数据概览读取失败：{errors.stats}</span>
            <Button size="sm" variant="outline" onClick={manualRefresh}>重试</Button>
          </div>
        </Alert>
      )}

      {/* 数据概览 */}
      <div className="v3-ops-stats v3-ops-stats--5">
        {[
          { label: '院校', value: stats?.school_count, icon: School, hint: '择校库院校总数', tone: 'primary' },
          { label: '专业', value: stats?.major_count, icon: BookOpen, hint: '专业方向记录', tone: 'info' },
          { label: '招生记录', value: stats?.admission_records, icon: FileText, hint: '历年招生数据', tone: 'success' },
          { label: '分数线记录', value: stats?.scoreline_records, icon: BarChart3, hint: '历年分数线', tone: 'warning' },
          {
            label: '公告',
            value: noticeStats?.total,
            icon: BellRing,
            hint: noticeTypes.length ? `${noticeTypes.length} 种公告类型` : '公告采集总量',
            tone: 'muted',
          },
        ].map((item) => {
          const Icon = item.icon
          return (
            <div className={`v3-ops-stat is-${item.tone}`} key={item.label}>
              <div className="v3-ops-stat__head">
                <span className="v3-ops-stat__label"><Icon size={14} />{item.label}</span>
              </div>
              <div className="v3-ops-stat__value">
                {showInitialSkeleton
                  ? <Skeleton width={72} height={28} />
                  : (item.value == null ? '—' : Number(item.value).toLocaleString('zh-CN'))}
              </div>
              <div className="v3-ops-stat__hint">{item.hint}</div>
            </div>
          )
        })}
      </div>

      {lastSync && (
        <div className="v3-ops-caption v3-ki-sync">
          最后同步 {lastSync.toLocaleTimeString('zh-CN', { hour12: false })} · 采集完成后会自动刷新统计与历史
        </div>
      )}

      {/* 定向采集：主操作区 */}
      <div ref={collectRef} className="v3-ki-collect-anchor">
        <SectionHead
          title="定向采集"
          icon={<Rocket size={16} />}
          sub="点击立即采集，后端同步执行；耗时任务请保持页面打开"
          actions={<Badge tone="soft">三条真实采集链路</Badge>}
        />

        <div className="v3-ki-collect-grid">
          {COLLECT_SOURCES.map((source) => {
            const Icon = source.icon
            const running = busy === source.key
            return (
              <Card
                key={source.key}
                className={`v3-ki-collect ${running ? 'is-running' : ''} ${busy && !running ? 'is-blocked' : ''}`}
              >
                <div className="v3-ki-collect__top">
                  <span className="v3-ki-collect__icon"><Icon size={20} /></span>
                  <Badge tone={running ? 'primary' : 'outline'}>{running ? '采集中' : source.hint}</Badge>
                </div>
                <h3>{source.label}</h3>
                <p>{source.desc}</p>
                <div className="v3-ki-collect__foot">
                  <Button
                    variant={running ? 'tonal' : 'filled'}
                    icon={<Rocket size={14} />}
                    loading={running}
                    disabled={collectDisabled && !running}
                    onClick={() => runCollect(source.key)}
                  >
                    {running ? '采集中…' : '立即采集'}
                  </Button>
                  <span className="v3-ops-caption">
                    {running ? `已等待 ${elapsed}s` : 'POST /kaoyan/collection/refresh'}
                  </span>
                </div>
                {running && (
                  <div className="v3-ki-busy">
                    <Progress indeterminate height={5} gradient />
                    <span>后端正在执行，最长等待 5 分钟；时间来自本页真实计时。</span>
                  </div>
                )}
              </Card>
            )
          })}
        </div>
      </div>

      {/* 最近一次采集结果 */}
      {lastResult && (
        <Card className={`v3-ki-result ${lastResult.ok ? 'is-ok' : 'is-error'}`}>
          <CardHead
            icon={lastResult.ok ? <CheckCircle2 size={17} /> : <BellRing size={17} />}
            title={lastResult.ok ? '最近一次采集结果' : '最近一次采集失败'}
            sub={`${sourceLabel(lastResult.source)} · ${lastResult.at.toLocaleTimeString('zh-CN', { hour12: false })}`}
            actions={lastResult.ok ? (
              <Button variant="ghost" size="sm" icon={<Copy size={14} />} onClick={copyResult}>
                复制结果
              </Button>
            ) : null}
          />
          {lastResult.ok ? (
            <>
              <pre className="v3-ki-result__pre">{resultPreview || '（后端未返回结果体）'}</pre>
              {resultTruncated && (
                <div className="v3-ops-caption">仅展示前 1500 字符，点击「复制结果」可获取完整 JSON。</div>
              )}
            </>
          ) : (
            <Alert tone="danger">{lastResult.error}</Alert>
          )}
        </Card>
      )}

      {/* 公告类型 & 学科覆盖 */}
      <div className="v3-ops-grid-2">
        <Card>
          <CardHead
            icon={<Tag size={17} />}
            title="公告类型分布"
            sub={noticeStats?.total != null ? `共 ${Number(noticeStats.total).toLocaleString('zh-CN')} 条公告` : '来自 /kaoyan/notices/types'}
            actions={<Badge tone="outline">{noticeTypes.length} 类</Badge>}
          />
          {errors.notices ? (
            <Alert tone="warning">
              <div className="v3-ops-inline">
                <span>{errors.notices}</span>
                <Button size="sm" variant="outline" onClick={manualRefresh}>重试</Button>
              </div>
            </Alert>
          ) : showInitialSkeleton ? (
            <div className="v3-ki-bars">
              {[0, 1, 2, 3].map((i) => <Skeleton key={i} height={34} radius={8} />)}
            </div>
          ) : noticeTypes.length ? (
            <div className="v3-ki-bars">
              {noticeTypes.map((item) => (
                <div className="v3-ki-type-row" key={item.type}>
                  <div className="v3-ki-type-row__top">
                    <span>{item.type}</span>
                    <b>{item.count.toLocaleString('zh-CN')}</b>
                  </div>
                  <div className="v3-ki-type-row__bar">
                    <span style={{ width: `${noticeMax ? Math.max(3, Math.round(item.count / noticeMax * 100)) : 0}%` }} />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty
              icon={<BellRing size={24} />}
              title="暂无公告数据"
              text="触发一次公告采集后，这里会按公告类型展示真实分布。"
              action={(
                <Button size="sm" variant="outline" onClick={() => runCollect('notices')} disabled={collectDisabled}>
                  采集公告
                </Button>
              )}
            />
          )}
        </Card>

        <Card>
          <CardHead
            icon={<BookOpen size={17} />}
            title="已覆盖学科"
            sub="来自 /kaoyan/subjects 的真实学科清单"
            actions={<Badge tone="outline">{subjectList.length} 个</Badge>}
          />
          {errors.subjects ? (
            <Alert tone="warning">
              <div className="v3-ops-inline">
                <span>{errors.subjects}</span>
                <Button size="sm" variant="outline" onClick={manualRefresh}>重试</Button>
              </div>
            </Alert>
          ) : subjectList.length ? (
            <div className="v3-ki-subjects">
              {subjectList.map((item, idx) => (
                <span className="v3-ki-subject" key={`${item.code ?? item.name}-${idx}`}>
                  <b>{item.name || item.code}</b>
                  {item.code != null && <span>{item.code}</span>}
                </span>
              ))}
            </div>
          ) : (
            <Empty
              icon={<Database size={24} />}
              title="暂无学科数据"
              text="学科清单为空时，请先完成院校与专业数据导入。"
            />
          )}
        </Card>
      </div>

      {/* 周期任务说明 */}
      <div className="v3-ki-weekly">
        <span className="v3-ki-weekly__icon"><Clock size={18} /></span>
        <div>
          <b>周期任务</b>
          <p>
            每周一 06:00 自动执行轻量增量（国家线新年份回填 + 公告列表前 10 所）。
            工科研招网全量采集不进周期任务（耗时长），需要时点上方「工科定向采集」手动触发。
            全部采集遵守 robots.txt 与 2–5s 随机延迟。
          </p>
        </div>
      </div>

      {/* 采集历史 */}
      <Card>
        <CardHead
          icon={<Database size={17} />}
          title="采集历史"
          sub="最近 20 条 · 数据来自 kaoyan_collection_runs（含每周自动任务）"
          actions={(
            <Button variant="ghost" size="sm" icon={<RefreshCw size={14} />} loading={refreshing} onClick={manualRefresh}>
              刷新
            </Button>
          )}
        />
        {errors.runs && !runs.length ? (
          <Alert tone="danger">
            <div className="v3-ops-inline">
              <span>采集历史读取失败：{errors.runs}</span>
              <Button size="sm" variant="outline" onClick={manualRefresh}>重试</Button>
            </div>
          </Alert>
        ) : showInitialSkeleton ? (
          <div className="v3-ki-history-skeleton">
            {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} height={40} radius={8} />)}
          </div>
        ) : runs.length === 0 ? (
          <Empty
            icon={<Clock size={26} />}
            title="暂无采集记录"
            text="上方触发一次采集后，历史会记录在这里（含每周自动任务）。"
            action={(
              <Button
                variant="filled"
                icon={<Rocket size={14} />}
                onClick={() => collectRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
              >
                去触发采集
              </Button>
            )}
          />
        ) : (
          <div className="v3-table-wrap">
            <table className="v3-table v3-ki-history-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>来源</th>
                  <th className="v3-ki-hide-sm">范围</th>
                  <th className="v3-ki-hide-sm">行数</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(0, 20).map((run, idx) => {
                  const st = RUN_STATUS[run.status] || { label: run.status || '未知', tone: 'outline' }
                  return (
                    <tr key={run.id ?? `${run.created_at}-${idx}`}>
                      <td className="v3-ops-mono v3-ki-run-time">{fmtRunTime(run.created_at)}</td>
                      <td><Badge tone="soft">{sourceLabel(run.source)}</Badge></td>
                      <td className="v3-ki-hide-sm v3-ops-muted">{run.scope || '—'}</td>
                      <td className="v3-ki-hide-sm v3-ops-mono">{run.row_count == null ? '—' : Number(run.row_count).toLocaleString('zh-CN')}</td>
                      <td><Badge tone={st.tone}>{st.label}</Badge></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {errors.runs && runs.length > 0 && (
          <div className="v3-ops-caption v3-ki-history-warn">
            本次刷新历史失败：{errors.runs}。上表为上一次成功读取的数据。
          </div>
        )}
      </Card>
    </div>
  )
}
