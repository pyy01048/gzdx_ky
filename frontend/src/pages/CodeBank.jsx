import React, { useCallback, useEffect, useRef, useState } from 'react'
import { request } from '../api/client'
import { Empty, toastOk, toastErr, focusAndScroll } from '../components/UI'
import { LoadingState, ErrorState } from '../components/States'
import { Map as MapIcon, FileText, Activity, Plus, RefreshCw } from '../components/Icon'
import './CodeBank.css'

/* 难度色取语义令牌（--*-ink 是浅底上的可读变体），不再散写十六进制 */
const DIFF_COLOR = { easy: 'var(--success-ink)', medium: 'var(--warn-ink)', hard: 'var(--danger-ink)' }
const DIFF_CN = { easy: '简单', medium: '中等', hard: '困难' }
/* 考频等级 → 星级。旧实现用 '重点'.repeat(n) 拼字符串，n=4 时页面上会出现
   「重点重点重点重点+」，既是文案 bug 也让筛选按钮无法一眼读懂。 */
const STARS = (n) => '★'.repeat(Math.min(5, Math.max(0, Number(n) || 0))) + '☆'.repeat(Math.max(0, 5 - (Number(n) || 0)))
/* 后端响应在入口处归一：这一页所有区块都直接 `.items.map()` / `.length`，
   而 HTTP 200 + `null` / 缺键的响应壳是完全可能的（老后端进程、字段改名）。
   实测：`request` 返回 null 时 `subjects.length` 直接把整页崩成白屏。 */
const toArr = (v) => (Array.isArray(v) ? v : [])
const toObj = (v) => (v && typeof v === 'object' ? v : null)

export default function CodeBank() {
  const [tab, setTab] = useState('panorama') // panorama | list | strategy
  const [subjects, setSubjects] = useState([])
  const [subject, setSubject] = useState('')
  const [pano, setPano] = useState(null)
  const [list, setList] = useState(null)
  const [strategy, setStrategy] = useState(null)
  const [detail, setDetail] = useState(null)
  const [filters, setFilters] = useState({ q: '', difficulty: '', tag: '', min_frequency: 0 })
  const [showAdd, setShowAdd] = useState(false)
  const [newSub, setNewSub] = useState({ name: '', direction: '' })
  const [lang, setLang] = useState('')
  /* 三态：此前所有请求都 `.catch(() => {})`，空库/后端不可达时整页只剩大片空白，
     用户既看不出「没数据」也看不出「加载失败」。 */
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reloadKey, setReloadKey] = useState(0)
  /* 手动刷新结果提示：null | 'queued'（已点击，等 loading 起来）| 'running'（请求中）
     列表加载由 effect 驱动，无法直接 await，这里用状态机在 loading 落回 false 时判成败。 */
  const pendingRefresh = useRef(null)
  const addNameRef = useRef(null)

  const loadSubjects = useCallback(() => {
    request('/codebank/subjects').then((d) => setSubjects(toArr(d))).catch(() => {})
  }, [])
  useEffect(() => { loadSubjects() }, [loadSubjects])

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError('')
    const fail = (e) => { if (alive) { setError(e?.message || '请求失败') } }
    const done = () => { if (alive) setLoading(false) }
    if (tab === 'panorama') {
      setPano(null)
      request('/codebank/panorama', { params: subject ? { subject } : {} })
        .then((d) => { if (alive) setPano(toObj(d) ? { ...d, items: toArr(d.items) } : { items: [] }) })
        .catch(fail).finally(done)
    } else if (tab === 'strategy') {
      setStrategy(null)
      request('/codebank/exam-strategy')
        .then((d) => {
          if (!alive) return
          setStrategy(toObj(d)
            ? { ...d, top_questions: toArr(d.top_questions), by_subject: toArr(d.by_subject) }
            : { top_questions: [], by_subject: [] })
        })
        .catch(fail).finally(done)
    } else {
      setList(null)
      const params = {}
      if (subject) params.subject = subject
      if (filters.q) params.q = filters.q
      if (filters.difficulty) params.difficulty = filters.difficulty
      if (filters.tag) params.tag = filters.tag
      if (filters.min_frequency) params.min_frequency = filters.min_frequency
      request('/codebank/questions', { params })
        .then((d) => { if (alive) setList(toObj(d) ? { ...d, items: toArr(d.items) } : { items: [] }) })
        .catch(fail).finally(done)
    }
    return () => { alive = false }
  }, [tab, subject, filters, reloadKey])

  /* 手动刷新的成败提示：点击 → queued；loading 起来 → running；loading 落回 false 时结算 */
  useEffect(() => {
    if (!pendingRefresh.current) return
    if (loading) { pendingRefresh.current = 'running'; return }
    if (pendingRefresh.current !== 'running') return
    pendingRefresh.current = null
    if (error) toastErr(`刷新失败：${error}`)
    else toastOk('题库数据已刷新')
  }, [loading, error])

  const hasFilters = Boolean(filters.q || filters.difficulty || filters.tag || filters.min_frequency)

  const openDetail = (id) => {
    request('/codebank/questions/' + id).then((d) => {
      setDetail(toObj(d) ? {
        ...d,
        tags: toArr(d.tags),
        examples: toArr(d.examples),
        languages: toArr(d.languages),
        appear_years: toArr(d.appear_years),
      } : null)
      setLang(toArr(d?.languages)[0] || '')
    }).catch(() => {})
  }
  const addSubject = () => {
    if (!newSub.name.trim()) {
      toastErr('请填写科目名称后再添加')
      focusAndScroll(addNameRef.current)
      return
    }
    request('/codebank/subjects', { method: 'POST', body: newSub })
      .then(r => {
        if (r?.added) {
          loadSubjects()
          setNewSub({ name: '', direction: '' })
          setShowAdd(false)
          toastOk('科目已添加')
          setReloadKey((k) => k + 1)
        } else {
          toastErr(r?.message || '科目已存在')
        }
      })
      .catch((e) => toastErr(`添加失败：${e?.message || '请求失败'}`))
  }

  return (
    <div className="cb-wrap">
      <header className="cb-hero">
        <div>
          <h1>复试代码题库</h1>
          {/* 科目名从题库数据来：此前写死「数学/数电/模电/信号/光学/408」，
              后端加减科目页面感知不到，空库时还在宣称存在这些科目。 */}
          <p>
            LeetCode 式刷题 · 知识点全景 · 考频分析 ——{' '}
            {subjects.length
              ? `${subjects.length} 个科目：${subjects.slice(0, 6).map((s) => s.name).join('、')}${subjects.length > 6 ? ' 等' : ''}`
              : '当前还没有科目，添加后即可按科目整理复试题'}
          </p>
        </div>
        <div className="cb-hero-actions">
          <button className="btn ghost" onClick={() => { pendingRefresh.current = 'queued'; setReloadKey((k) => k + 1) }} disabled={loading}>
            <RefreshCw size={14} /> 刷新
          </button>
          <button className="btn primary" onClick={() => setShowAdd(true)}>
            <Plus size={14} /> 添加科目
          </button>
        </div>
      </header>

      <div className="cb-subjects">
        <button className={`cb-chip ${subject === '' ? 'on' : ''}`} onClick={() => setSubject('')}>全部</button>
        {subjects.map(s => (
          <button key={s.id} className={`cb-chip ${subject === s.name ? 'on' : ''}`}
            title={`${s.direction || ''} · ${s.question_count} 题`}
            onClick={() => setSubject(s.name)}>{s.name}<em>{s.question_count}</em></button>
        ))}
      </div>

      <div className="cb-tabs" role="tablist">
        {[
          ['panorama', '知识点全景', <MapIcon size={14} key="i" />],
          ['list', '题库列表', <FileText size={14} key="i" />],
          ['strategy', '考频分析', <Activity size={14} key="i" />],
        ].map(([k, label, ico]) => (
          <button key={k} role="tab" aria-selected={tab === k}
            className={`cb-tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>
            {ico}{label}
          </button>
        ))}
      </div>

      {loading && (
        <div className="card cb-state">
          <LoadingState text="正在读取代码题库…" rows={4} />
        </div>
      )}
      {!loading && error && (
        <div className="card cb-state">
          <ErrorState
            title="代码题库加载失败"
            message={error}
            onRetry={() => setReloadKey((k) => k + 1)}
            retryText="重新加载"
          />
        </div>
      )}

      {/* ---------- 知识点全景 ---------- */}
      {!loading && !error && tab === 'panorama' && pano && (
        pano.items.length ? (
          <div className="cb-pano">
            {pano.items.map(it => (
              <button key={it.tag} className="cb-pano-card" onClick={() => { setFilters(f => ({ ...f, tag: it.tag })); setTab('list') }}>
                <div className="cb-pano-tag">{it.tag}</div>
                <div className="cb-pano-meta">{it.subject} · {it.total} 题</div>
                <div className="cb-pano-freq">{STARS(Math.round(it.avg_frequency))}</div>
                {it.hot && <div className="cb-pano-hot">最热：{it.hot.title}</div>}
              </button>
            ))}
          </div>
        ) : (
          <div className="card cb-state">
            <Empty
              icon={<MapIcon size={40} />}
              title="还没有知识点数据"
              desc="先添加科目并录入题目，系统会按标签自动汇总成知识点全景。"
              action={<button className="btn primary" onClick={() => setShowAdd(true)}>添加科目</button>}
            />
          </div>
        )
      )}

      {/* ---------- 题库列表 ---------- */}
      {!loading && !error && tab === 'list' && (
        <>
          <div className="cb-filters">
            <input className="cb-search" placeholder="搜索题目标题/题面…" aria-label="搜索题目标题或题面" value={filters.q}
              onChange={e => setFilters(f => ({ ...f, q: e.target.value }))} />
            {[['', '全部难度'], ['easy', '简单'], ['medium', '中等'], ['hard', '困难']].map(([v, l]) => (
              <button key={v || 'all'} className={`cb-chip ${filters.difficulty === v ? 'on' : ''}`}
                onClick={() => setFilters(f => ({ ...f, difficulty: v }))}>{l}</button>
            ))}
            {[0, 4, 5].map(n => (
              <button key={n} className={`cb-chip ${filters.min_frequency === n ? 'on' : ''}`}
                onClick={() => setFilters(f => ({ ...f, min_frequency: n }))}>
                {n === 0 ? '不限考频' : `考频≥${'★'.repeat(n)}`}
              </button>
            ))}
          </div>
          {list && list.items.length === 0 ? (
            <div className="card cb-state">
              <Empty
                icon={<FileText size={40} />}
                title={hasFilters ? '当前筛选下没有题目' : '题库还是空的'}
                desc={hasFilters
                  ? '清空关键词 / 难度 / 考频后即可看到全部题目。'
                  : '添加科目后即可开始整理复试题；题目录入后这里会自动按考点与考频汇总。'}
                action={hasFilters
                  ? <button className="btn ghost" onClick={() => setFilters({ q: '', difficulty: '', tag: '', min_frequency: 0 })}>清空筛选</button>
                  : <button className="btn primary" onClick={() => setShowAdd(true)}>添加科目</button>}
              />
            </div>
          ) : (
            <div className="table-container">
              <table className="cb-table">
                <thead><tr><th>#</th><th>题目</th><th>科目</th><th>难度</th><th>考频</th><th>年份</th></tr></thead>
                <tbody>
                  {(list?.items || []).map(q => (
                    <tr key={q.id} onClick={() => openDetail(q.id)} role="button" tabIndex={0}
                      aria-label={`查看题目详情：${q.title}`}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDetail(q.id) } }}>
                      <td>{q.id}</td>
                      <td className="cb-title">{q.title}</td>
                      <td>{q.subject}</td>
                      <td><em style={{ color: DIFF_COLOR[q.difficulty], fontStyle: 'normal' }}>{DIFF_CN[q.difficulty]}</em></td>
                      <td className="cb-freq">{STARS(q.frequency)}</td>
                      <td className="cb-years">{(q.appear_years || []).join('/') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ---------- 考频分析 ---------- */}
      {!loading && !error && tab === 'strategy' && strategy
        && strategy.top_questions.length === 0 && strategy.by_subject.length === 0 && (
          <div className="card cb-state">
            <Empty
              icon={<Activity size={40} />}
              title="还没有考频数据"
              desc="题目积累后，系统会按出现年份与标签统计高频题和科目分布。"
              action={<button className="btn primary" onClick={() => setTab('list')}>去题库列表</button>}
            />
          </div>
        )}
      {!loading && !error && tab === 'strategy' && strategy
        && (strategy.top_questions.length > 0 || strategy.by_subject.length > 0) && (
        <div className="cb-strategy">
          <h3>高频题 TOP10（按考频标注）</h3>
          <div className="cb-top-grid">
            {strategy.top_questions.map((q, i) => (
              <button key={q.id} className="cb-top-card" onClick={() => openDetail(q.id)}>
                <em className={`cb-top-rank ${i < 3 ? 'hot' : ''}`}>{i + 1}</em>
                <div>
                  <div className="cb-title">{q.title}</div>
                  <div className="cb-pano-meta">{q.subject} · <em style={{ color: DIFF_COLOR[q.difficulty], fontStyle: 'normal' }}>{DIFF_CN[q.difficulty]}</em> · {(q.appear_years || []).join('/') || '—'}</div>
                </div>
                <span className="cb-freq">{STARS(q.frequency)}</span>
              </button>
            ))}
          </div>
          <h3>科目分布（题数 × 平均考频）</h3>
          <div className="cb-dist">
            {strategy.by_subject.map(s => (
              <div key={s.subject} className="cb-dist-row">
                <span className="cb-dist-name">{s.subject}</span>
                <span className="cb-dist-bar"><i style={{ width: `${Math.min(100, s.count * 12)}%` }} /></span>
                <span className="cb-dist-num">{s.count} 题 · 均{s.avg_frequency}重点</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ---------- 详情弹层 ---------- */}
      {detail && (
        <div className="cb-mask" onClick={() => setDetail(null)}>
          <article className="cb-detail" onClick={e => e.stopPropagation()}>
            <header className="cb-detail-head">
              <div>
                <span className={`cb-diff ${detail.difficulty}`}>{DIFF_CN[detail.difficulty]}</span>
                <strong>{detail.title}</strong>
                <span className="cb-freq">{STARS(detail.frequency)}</span>
              </div>
              <button className="cb-close" onClick={() => setDetail(null)}>关闭</button>
            </header>
            <div className="cb-detail-meta">
              {detail.subject} · {(detail.tags || []).map(t => <code key={t}>{t}</code>)}
              {detail.appear_years?.length > 0 && <span> · 出现年份：{detail.appear_years.join('/')}</span>}
            </div>
            <pre className="cb-statement">{detail.statement}</pre>
            {detail.input_desc && <p className="cb-io"><b>输入：</b>{detail.input_desc}</p>}
            {detail.output_desc && <p className="cb-io"><b>输出：</b>{detail.output_desc}</p>}
            {(detail.examples || []).map((ex, i) => (
              <div key={i} className="cb-example">
                <div>示例 {i + 1}</div>
                <pre>{ex.input}</pre>
                <pre className="out">{ex.output}</pre>
              </div>
            ))}
            {detail.hint && <div className="cb-hint">提示 提示：{detail.hint}</div>}
            {detail.languages?.length > 0 && (
              <>
                <div className="cb-langs">
                  {detail.languages.map(l => (
                    <button key={l} className={`cb-chip ${lang === l ? 'on' : ''}`} onClick={() => setLang(l)}>{l}</button>
                  ))}
                </div>
                <pre className="cb-code">{TEMPLATE(detail, lang)}</pre>
              </>
            )}
            <div className="cb-note">本地自测：复制模板到本地 IDE 运行；上机判题与提交记录将在后续版本接入。</div>
          </article>
        </div>
      )}

      {/* ---------- 添加科目弹层 ---------- */}
      {showAdd && (
        <div className="cb-mask" onClick={() => setShowAdd(false)}>
          <div className="cb-detail cb-add-panel" onClick={e => e.stopPropagation()}>
            <h3>添加科目模块</h3>
            <input className="cb-search" placeholder="科目名，如：光纤通信 / 嵌入式 / 复试英语口语" aria-label="科目名"
              ref={addNameRef}
              value={newSub.name} onChange={e => setNewSub(s => ({ ...s, name: e.target.value }))} />
            <input className="cb-search" placeholder="方向（可选），如：复试·通信" aria-label="方向（可选）"
              value={newSub.direction} onChange={e => setNewSub(s => ({ ...s, direction: e.target.value }))} />
            <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-3)' }}>
              <button className="cb-chip on" onClick={addSubject}>确认添加</button>
              <button className="cb-chip" onClick={() => setShowAdd(false)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* 按语言返回入门模板（题库暂不存逐题模板，统一起步骨架，降低维护成本） */
function TEMPLATE(detail, lang) {
  const skeletons = {
    'C++': '#include <bits/stdc++.h>\nusing namespace std;\nint main() {\n    // 在此实现\n    return 0;\n}',
    'Python': 'def solve():\n    # 在此实现\n    pass\n\nif __name__ == "__main__":\n    print(solve())',
    'C': '#include <stdio.h>\nint main() {\n    /* 在此实现 */\n    return 0;\n}',
    'Java': 'public class Main {\n    public static void main(String[] args) {\n        // 在此实现\n    }\n}',
  }
  return skeletons[lang] || '// 选择语言'
}
