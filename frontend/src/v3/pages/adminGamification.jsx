/* ============================================================
   adminGamification.jsx —— 管理台「激励运营」（W6）
   ------------------------------------------------------------
   挂在 UserAdmin 的标签页里（账号列表 / 安全审计 / 角色权限 / 激励运营）。
   分成四块：大盘、规则与参数、商品、发放审计。每块只对自己那组接口负责，
   改单价不会连带把商品表拖进来重渲染。

   为什么没有"删除商品"：物理删除会让历史流水指向不存在的商品，审计断链；
   后端也只提供上下架（is_active），这里就不做假删除按钮。
   ============================================================ */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { coinsApi } from '../../api/gamification'
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHead,
  Chip,
  Dialog,
  Empty,
  Field,
  Input,
  Pager,
  Select,
  Skeleton,
  Switch,
  Tabs,
  Tile,
  toastErr,
  toastOk,
} from '../ui'
import {
  BarChart3,
  Check,
  Gauge,
  List,
  Plus,
  RefreshCw,
  Settings,
  SlidersHorizontal,
  Trophy,
  Zap,
} from '../icons'
import '../styles/gamification-v3.css'

const KIND_LABEL = {
  makeup_card: '补签卡',
  boost: '加成卡',
  avatar_frame: '头像框',
  title: '称号',
}
const DIRECTION_LABEL = { earn: '发放', spend: '消耗', adjust: '调整' }
const ITEM_KINDS = ['makeup_card', 'boost', 'avatar_frame', 'title']

const num = (v, fallback = 0) => {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

/* ------------------------------------------------------------------ */
/* 大盘                                                                */
/* ------------------------------------------------------------------ */
function OpsOverview({ days, setDays }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    setErr('')
    coinsApi.admin
      .overview(days)
      .then(setData)
      .catch((e) => setErr(e?.message || '大盘数据加载失败'))
      .finally(() => setLoading(false))
  }, [days])

  useEffect(() => {
    load()
  }, [load])

  const peak = useMemo(() => Math.max(1, ...(data?.per_day || []).map((d) => num(d.coins))), [data])

  return (
    <Card>
      <CardHead
        icon={<Gauge size={16} />}
        title="发放大盘"
        sub="金币通胀要看两个数：单日发放总额、持币人数。异常拉高通常意味着某条规则被调飞了"
        actions={
          <div className="v3-gami-inline">
            <Select
              aria-label="统计窗口"
              value={String(days)}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              {[7, 14, 30, 60, 90].map((d) => (
                <option key={d} value={d}>
                  近 {d} 天
                </option>
              ))}
            </Select>
            <Button size="sm" variant="outline" icon={<RefreshCw size={14} />} onClick={load}>
              刷新
            </Button>
          </div>
        }
      />
      {loading && !data ? <Skeleton height={200} /> : null}
      {err ? <Alert tone="danger">{err}</Alert> : null}
      {data ? (
        <>
          <div className="v3-ops-kpis">
            <div className="v3-ops-kpi">
              <div className="v3-ops-kpi__label">窗口内发放</div>
              <div className="v3-ops-kpi__value">{data.total_earned}</div>
            </div>
            <div className="v3-ops-kpi">
              <div className="v3-ops-kpi__label">窗口内消耗</div>
              <div className="v3-ops-kpi__value">{data.total_spent}</div>
            </div>
            <div className="v3-ops-kpi">
              <div className="v3-ops-kpi__label">参与人数</div>
              <div className="v3-ops-kpi__value">{data.participants}</div>
            </div>
            <div className="v3-ops-kpi">
              <div className="v3-ops-kpi__label">开户数</div>
              <div className="v3-ops-kpi__value">{data.accounts}</div>
            </div>
            <div className="v3-ops-kpi">
              <div className="v3-ops-kpi__label">还有余额的人</div>
              <div className="v3-ops-kpi__value">{data.holders}</div>
            </div>
          </div>
          {data.per_day?.length ? (
            <div className="v3-ops-trend" role="img" aria-label="每日发放金币柱状图">
              {data.per_day.map((d) => (
                <div
                  className="v3-ops-trend__bar"
                  key={d.date}
                  style={{ height: `${Math.max(4, (num(d.coins) / peak) * 100)}%` }}
                  title={`${d.date} 发放 ${d.coins} 币 / ${d.users} 人`}
                >
                  <span>{d.date.slice(5)}</span>
                </div>
              ))}
            </div>
          ) : (
            <Empty
              icon={<BarChart3 size={26} />}
              title="窗口内还没有发放记录"
              text="新用户完成一次学习并同步后才会产生数据。"
            />
          )}

          <div className="v3-gami-grid" style={{ marginTop: 16 }}>
            <div>
              <div className="v3-pref-row__label">按规则</div>
              <table className="v3-ops-table">
                <thead>
                  <tr>
                    <th>规则</th>
                    <th>金币</th>
                    <th>笔数</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.per_rule || []).map((r) => (
                    <tr key={r.rule_code}>
                      <td>{r.label}</td>
                      <td className="v3-gami-num">{r.coins}</td>
                      <td className="v3-gami-num">{r.rows}</td>
                    </tr>
                  ))}
                  {!(data.per_rule || []).length ? (
                    <tr>
                      <td colSpan={3}>—</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
            <div>
              <div className="v3-pref-row__label">商品兑换排行</div>
              <table className="v3-ops-table">
                <thead>
                  <tr>
                    <th>商品</th>
                    <th>次数</th>
                    <th>回收金币</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.top_items || []).map((i) => (
                    <tr key={i.code}>
                      <td>{i.name}</td>
                      <td className="v3-gami-num">{i.count}</td>
                      <td className="v3-gami-num">{i.coins}</td>
                    </tr>
                  ))}
                  {!(data.top_items || []).length ? (
                    <tr>
                      <td colSpan={3}>还没有人兑换</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : null}
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* 规则与全局参数                                                       */
/* ------------------------------------------------------------------ */
function OpsRules() {
  const [rules, setRules] = useState(null)
  const [settings, setSettings] = useState(null)
  const [err, setErr] = useState('')
  const [savingCode, setSavingCode] = useState('')
  const [milestones, setMilestones] = useState([])
  const [capForm, setCapForm] = useState({})

  const load = useCallback(() => {
    setErr('')
    Promise.all([coinsApi.admin.rules(), coinsApi.admin.settings()])
      .then(([r, s]) => {
        setRules(r.items || [])
        setSettings(s.values || {})
        setCapForm({
          daily_earn_cap: s.values?.daily_earn_cap,
          checkin_base_coins: s.values?.checkin_base_coins,
          makeup_window_days: s.values?.makeup_window_days,
          makeup_monthly_limit: s.values?.makeup_monthly_limit,
          boost_hours: s.values?.boost_hours,
          boost_multiplier: s.values?.boost_multiplier,
          admin_adjust_max: s.values?.admin_adjust_max,
        })
        setMilestones(
          Object.entries(s.values?.streak_milestones || {}).map(([days, coins]) => ({ days, coins })),
        )
      })
      .catch((e) => setErr(e?.message || '规则加载失败'))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const patchRule = async (rule, fields) => {
    setSavingCode(rule.rule_code)
    try {
      const next = await coinsApi.admin.updateRule(rule.rule_code, fields)
      setRules((rows) => rows.map((r) => (r.rule_code === next.rule_code ? next : r)))
      toastOk(`${next.label} 已更新`)
    } catch (e) {
      toastErr(e?.message || '更新失败')
    } finally {
      setSavingCode('')
    }
  }

  const saveSettings = async () => {
    try {
      const values = { ...capForm }
      if (milestones.length) {
        const map = milestones.reduce((acc, m) => {
          const d = num(m.days)
          const c = num(m.coins)
          if (d > 0 && c > 0) acc[String(d)] = c
          return acc
        }, {})
        // 后端拒绝空里程碑映射（422「里程碑需是映射」）——这里先拦住，不拿服务器报错当校验
        if (!Object.keys(map).length) {
          toastErr('里程碑至少要留一档有效（天数 > 0 且金币 > 0）；全部删光等于清空配置，后端不允许')
          return
        }
        values.streak_milestones = map
      }
      const res = await coinsApi.admin.updateSettings(values)
      setSettings(res.values || {})
      if (res.values?.streak_milestones) {
        setMilestones(Object.entries(res.values.streak_milestones).map(([days, coins]) => ({ days, coins })))
      }
      toastOk('全局参数已保存')
    } catch (e) {
      toastErr(e?.message || '保存失败')
    }
  }

  if (!rules && !err) return <Skeleton height={240} />
  return (
    <div className="v3-gami-stack">
      {err ? <Alert tone="danger">{err}</Alert> : null}
      <Card>
        <CardHead
          icon={<SlidersHorizontal size={16} />}
          title="获取规则"
          sub="单价只在这里改：后端按 kind 折算（batch=满 N 个行为算一次），客户端无法自行报价"
          actions={
            <Button size="sm" variant="outline" icon={<RefreshCw size={14} />} onClick={load}>
              重载
            </Button>
          }
        />
        <div className="v3-ops-scrolly">
          <table className="v3-ops-table">
            <thead>
              <tr>
                <th>规则</th>
                <th>口径</th>
                <th>计量 N</th>
                <th>单价</th>
                <th>单日次数</th>
                <th>启用</th>
              </tr>
            </thead>
            <tbody>
              {(rules || []).map((r) => (
                <RuleRow
                  key={r.rule_code}
                  rule={r}
                  busy={savingCode === r.rule_code}
                  onSave={(fields) => patchRule(r, fields)}
                />
              ))}
            </tbody>
          </table>
        </div>
        <p className="v3-gami-muted" style={{ marginTop: 8 }}>
          「单日次数」填 0 等于停发该规则但不删历史流水。规则与学习台账字段的映射固定在 后端{' '}
          <code>services/gamification.py</code>，改口径需要发版，不在这里放开。
        </p>
      </Card>

      <Card>
        <CardHead
          icon={<Settings size={16} />}
          title="全局参数"
          sub="日上限 / 签到基础币 / 里程碑 / 补签窗口 / 加成倍率"
        />
        <div className="v3-ops-form">
          {[
            ['daily_earn_cap', '单日发放上限'],
            ['checkin_base_coins', '签到基础金币'],
            ['makeup_window_days', '补签窗口（天）'],
            ['makeup_monthly_limit', '每月补签上限'],
            ['boost_hours', '加成时长（小时）'],
            ['boost_multiplier', '加成倍率'],
            ['admin_adjust_max', '单次人工调整上限'],
          ].map(([key, label]) => (
            <Field key={key} label={label}>
              <Input
                type="number"
                step={key === 'boost_multiplier' ? '0.1' : '1'}
                value={capForm[key] ?? ''}
                onChange={(e) => setCapForm((f) => ({ ...f, [key]: e.target.value }))}
              />
            </Field>
          ))}
        </div>
        <div style={{ marginTop: 12 }}>
          <div className="v3-pref-row__label">连续签到里程碑</div>
          <div className="v3-gami-inline" style={{ marginTop: 6 }}>
            {milestones.map((m, i) => (
              <span className="v3-gami-inline" key={`ms-${i}`} style={{ gap: 4 }}>
                <Input
                  type="number"
                  style={{ width: 72 }}
                  aria-label={`第 ${i + 1} 档天数`}
                  value={m.days}
                  onChange={(e) =>
                    setMilestones((rows) =>
                      rows.map((r, j) => (j === i ? { ...r, days: e.target.value } : r)),
                    )
                  }
                />
                天 +
                <Input
                  type="number"
                  style={{ width: 72 }}
                  aria-label={`第 ${i + 1} 档金币`}
                  value={m.coins}
                  onChange={(e) =>
                    setMilestones((rows) =>
                      rows.map((r, j) => (j === i ? { ...r, coins: e.target.value } : r)),
                    )
                  }
                />
                币<Chip onClick={() => setMilestones((rows) => rows.filter((_, j) => j !== i))}>删</Chip>
              </span>
            ))}
            <Chip onClick={() => setMilestones((rows) => [...rows, { days: '', coins: '' }])}>加一档</Chip>
          </div>
        </div>
        <div className="v3-gami-inline" style={{ marginTop: 12 }}>
          <Button icon={<Check size={14} />} onClick={saveSettings}>
            保存全局参数
          </Button>
          {settings ? <Badge tone="outline">当前日上限 {settings.daily_earn_cap}</Badge> : null}
        </div>
      </Card>
    </div>
  )
}

function RuleRow({ rule, onSave, busy }) {
  const [perUnits, setPerUnits] = useState(rule.per_units)
  const [coins, setCoins] = useState(rule.coins)
  const [cap, setCap] = useState(rule.daily_cap)
  const [active, setActive] = useState(rule.is_active)
  const dirty =
    num(perUnits) !== rule.per_units ||
    num(coins) !== rule.coins ||
    num(cap) !== rule.daily_cap ||
    active !== rule.is_active

  return (
    <tr>
      <td>
        <div>{rule.label}</div>
        <div className="v3-gami-muted">
          {rule.rule_code} · {rule.kind}
        </div>
      </td>
      <td>
        {rule.kind === 'batch'
          ? `每 N ${rule.unit_label || ''}`
          : rule.kind === 'per_item'
            ? `每个 ${rule.unit_label || ''}`
            : '每日一次'}
      </td>
      <td>
        <Input
          className="v3-ops-table__num"
          type="number"
          min={1}
          max={200}
          disabled={rule.kind !== 'batch' || busy}
          value={perUnits}
          aria-label={`${rule.label} 计量单位`}
          onChange={(e) => setPerUnits(e.target.value)}
        />
      </td>
      <td>
        <Input
          className="v3-ops-table__num"
          type="number"
          min={0}
          max={500}
          disabled={busy}
          value={coins}
          aria-label={`${rule.label} 单价`}
          onChange={(e) => setCoins(e.target.value)}
        />
      </td>
      <td>
        <Input
          className="v3-ops-table__num"
          type="number"
          min={0}
          max={50}
          disabled={busy}
          value={cap}
          aria-label={`${rule.label} 单日次数上限`}
          onChange={(e) => setCap(e.target.value)}
        />
      </td>
      <td>
        <div className="v3-gami-inline">
          <Switch checked={active} onChange={setActive} label={`${rule.label} 启用`} />
          <Button
            size="sm"
            variant={dirty ? 'primary' : 'ghost'}
            disabled={!dirty}
            loading={busy}
            onClick={() =>
              onSave({
                per_units: num(perUnits, rule.per_units),
                coins: num(coins, rule.coins),
                daily_cap: num(cap, rule.daily_cap),
                is_active: active,
              })
            }
          >
            保存
          </Button>
        </div>
      </td>
    </tr>
  )
}

/* ------------------------------------------------------------------ */
/* 商品                                                                */
/* ------------------------------------------------------------------ */
const EMPTY_ITEM = {
  code: '',
  name: '',
  kind: 'avatar_frame',
  cost_coins: 200,
  description: '',
  monthly_limit: 0,
  payload: '{}',
  sort_order: 0,
}

function OpsItems() {
  const [items, setItems] = useState(null)
  const [err, setErr] = useState('')
  const [editor, setEditor] = useState(null)
  const [formErr, setFormErr] = useState('')
  const [busyCode, setBusyCode] = useState('')

  const load = useCallback(() => {
    setErr('')
    coinsApi.admin
      .items()
      .then((d) => setItems(d.items || []))
      .catch((e) => setErr(e?.message || '商品加载失败'))
  }, [])
  useEffect(() => {
    load()
  }, [load])

  const submit = async () => {
    setFormErr('')
    let payload = {}
    try {
      payload = editor.payload ? JSON.parse(editor.payload) : {}
    } catch {
      setFormErr('权益参数不是合法 JSON，例如 {"frame":"custom"}')
      return
    }
    try {
      await coinsApi.admin.upsertItem({
        code: editor.code.trim(),
        name: editor.name.trim(),
        kind: editor.kind,
        cost_coins: num(editor.cost_coins),
        description: editor.description || '',
        monthly_limit: num(editor.monthly_limit),
        sort_order: num(editor.sort_order),
        payload,
        // 后端 ItemBody.is_active 缺省时 model_dump 会带 None 进来（bool(None)=False 会把商品
        // 悄悄下架），所以这里**永远显式回传**当前状态：编辑=维持原上下架，新增=直接上架。
        is_active: editor.is_active ?? true,
      })
      setEditor(null)
      load()
      toastOk('商品已保存')
    } catch (e) {
      setFormErr(e?.message || '保存失败')
    }
  }

  const toggle = async (item) => {
    setBusyCode(item.code)
    try {
      await coinsApi.admin.toggleItem(item.code, !item.is_active)
      load()
      toastOk(item.is_active ? '已下架' : '已上架')
    } catch (e) {
      toastErr(e?.message || '操作失败')
    } finally {
      setBusyCode('')
    }
  }

  return (
    <Card>
      <CardHead
        icon={<Trophy size={16} />}
        title="金币商店商品"
        sub="四种可兑现权益：补签卡 / 加成卡 / 头像框 / 称号。新增其它类型需要后端先实现发货逻辑，这里刻意不放开"
        actions={
          <div className="v3-gami-inline">
            <Button size="sm" variant="outline" icon={<RefreshCw size={14} />} onClick={load}>
              刷新
            </Button>
            <Button
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => {
                setFormErr('')
                setEditor({ ...EMPTY_ITEM })
              }}
            >
              新增商品
            </Button>
          </div>
        }
      />
      {err ? <Alert tone="danger">{err}</Alert> : null}
      {!items ? <Skeleton height={160} /> : null}
      {items && !items.length ? (
        <Empty
          title="还没有商品"
          text="后端默认商品会在首次访问时自动播种；若为空说明播种失败，请查看服务端日志。"
        />
      ) : null}
      {items?.length ? (
        <div className="v3-ops-scrolly">
          <table className="v3-ops-table">
            <thead>
              <tr>
                <th>商品</th>
                <th>类型</th>
                <th>价格</th>
                <th>月限购</th>
                <th>参数</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.code}>
                  <td>
                    <div>{it.name}</div>
                    <div className="v3-gami-muted">{it.code}</div>
                  </td>
                  <td>{KIND_LABEL[it.kind] || it.kind}</td>
                  <td className="v3-gami-num">{it.cost_coins}</td>
                  <td className="v3-gami-num">{it.monthly_limit || '不限'}</td>
                  <td>
                    <code className="v3-gami-muted">{JSON.stringify(it.payload || {})}</code>
                  </td>
                  <td>
                    {it.is_active ? <Badge tone="success">在售</Badge> : <Badge tone="outline">已下架</Badge>}
                  </td>
                  <td>
                    <div className="v3-gami-inline">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setFormErr('')
                          setEditor({ ...it, payload: JSON.stringify(it.payload || {}) })
                        }}
                      >
                        编辑
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        loading={busyCode === it.code}
                        onClick={() => toggle(it)}
                      >
                        {it.is_active ? '下架' : '上架'}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <Dialog
        open={!!editor}
        title={editor?.code ? `编辑商品 · ${editor.code}` : '新增商品'}
        sub="改价立即生效；已在流水里的历史价格不受影响（流水里存的是实扣数额）"
        onClose={() => setEditor(null)}
        footer={
          <>
            <Button variant="text" onClick={() => setEditor(null)}>
              取消
            </Button>
            <Button onClick={submit} disabled={!editor?.code?.trim() || !editor?.name?.trim()}>
              保存
            </Button>
          </>
        }
      >
        {editor ? (
          <div className="v3-gami-stack" style={{ gap: 10 }}>
            {formErr ? <Alert tone="danger">{formErr}</Alert> : null}
            <div className="v3-ops-form">
              <Field label="商品码" hint="唯一键，例如 frame_ocean">
                <Input
                  value={editor.code}
                  disabled={!!items?.find((i) => i.code === editor.code)}
                  onChange={(e) => setEditor({ ...editor, code: e.target.value })}
                />
              </Field>
              <Field label="名称">
                <Input value={editor.name} onChange={(e) => setEditor({ ...editor, name: e.target.value })} />
              </Field>
              <Field label="类型">
                <Select value={editor.kind} onChange={(e) => setEditor({ ...editor, kind: e.target.value })}>
                  {ITEM_KINDS.map((k) => (
                    <option key={k} value={k}>
                      {KIND_LABEL[k]}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="价格（金币）">
                <Input
                  type="number"
                  min={0}
                  value={editor.cost_coins}
                  onChange={(e) => setEditor({ ...editor, cost_coins: e.target.value })}
                />
              </Field>
              <Field label="每月限购" hint="0=不限">
                <Input
                  type="number"
                  min={0}
                  value={editor.monthly_limit}
                  onChange={(e) => setEditor({ ...editor, monthly_limit: e.target.value })}
                />
              </Field>
              <Field label="排序">
                <Input
                  type="number"
                  value={editor.sort_order}
                  onChange={(e) => setEditor({ ...editor, sort_order: e.target.value })}
                />
              </Field>
            </div>
            <Field label="说明" hint="写清楚「怎么兑现」，避免空头承诺">
              <Input
                value={editor.description || ''}
                onChange={(e) => setEditor({ ...editor, description: e.target.value })}
              />
            </Field>
            <Field
              label="权益参数 JSON"
              hint='头像框 {"frame":"ocean"}；称号 {"title":"锲而不舍"}；加成 {"multiplier":1.5,"hours":24}'
            >
              <Input
                value={editor.payload}
                onChange={(e) => setEditor({ ...editor, payload: e.target.value })}
              />
            </Field>
          </div>
        ) : null}
      </Dialog>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* 发放审计                                                            */
/* ------------------------------------------------------------------ */
function OpsLedger() {
  const [rows, setRows] = useState(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [userId, setUserId] = useState('')
  const [direction, setDirection] = useState('')
  const [rule, setRule] = useState('')
  const [err, setErr] = useState('')
  const [adjustOpen, setAdjustOpen] = useState(false)
  const [adjustForm, setAdjustForm] = useState({ user_id: '', coins: '', reason: '' })
  const [adjustErr, setAdjustErr] = useState('')
  const [adjusting, setAdjusting] = useState(false)
  // 单次人工调整绝对值上限是后端全局参数 admin_adjust_max（默认 2000），拉来在前端先拦
  const [adjustMax, setAdjustMax] = useState(2000)
  useEffect(() => {
    let alive = true
    coinsApi.admin
      .settings()
      .then((s) => {
        if (alive && num(s?.values?.admin_adjust_max) > 0) setAdjustMax(num(s.values.admin_adjust_max))
      })
      .catch(() => {
        /* 拿不到就用默认值，后端仍会把关 */
      })
    return () => {
      alive = false
    }
  }, [])

  const load = useCallback(() => {
    setErr('')
    coinsApi.admin
      .ledger({
        page,
        page_size: pageSize,
        ...(userId.trim() ? { user_id: num(userId.trim()) } : {}),
        ...(direction ? { direction } : {}),
        ...(rule.trim() ? { rule_code: rule.trim() } : {}),
      })
      .then(setRows)
      .catch((e) => setErr(e?.message || '流水加载失败'))
  }, [page, pageSize, userId, direction, rule])

  useEffect(() => {
    load()
  }, [load])

  const doAdjust = async () => {
    setAdjustErr('')
    if (!adjustForm.user_id.trim() || !adjustForm.coins.trim()) {
      setAdjustErr('用户 ID 与数额都要填')
      return
    }
    const coins = num(adjustForm.coins)
    const reason = adjustForm.reason.trim()
    // 与后端 admin/adjust 校验同口径：数额非零、|coins| ≤ admin_adjust_max、原因 ≥ 4 字
    if (!coins) {
      setAdjustErr('调整数额不能为 0')
      return
    }
    if (Math.abs(coins) > adjustMax) {
      setAdjustErr(`单次调整不得超过 ${adjustMax} 币（全局参数 admin_adjust_max）`)
      return
    }
    if (reason.length < 4) {
      setAdjustErr('原因至少 4 个字，审计要能看懂')
      return
    }
    setAdjusting(true)
    try {
      const r = await coinsApi.admin.adjust({
        user_id: num(adjustForm.user_id),
        coins,
        reason,
      })
      toastOk(`已调整 ${r.coins} 币，该用户余额 ${r.balance}`)
      setAdjustOpen(false)
      setAdjustForm({ user_id: '', coins: '', reason: '' })
      load()
    } catch (e) {
      setAdjustErr(e?.message || '调整失败')
    } finally {
      setAdjusting(false)
    }
  }

  return (
    <Card>
      <CardHead
        icon={<List size={16} />}
        title="发放审计"
        sub="每一笔都可回溯到规则、日期与操作者；人工调整必须填原因"
        actions={
          <Button size="sm" icon={<Zap size={14} />} onClick={() => setAdjustOpen(true)}>
            人工调整
          </Button>
        }
      />
      <div className="v3-ops-form" style={{ marginBottom: 10 }}>
        <Field label="用户 ID">
          <Input
            value={userId}
            onChange={(e) => {
              setUserId(e.target.value)
              setPage(1)
            }}
            placeholder="按用户过滤"
          />
        </Field>
        <Field label="规则码">
          <Input
            value={rule}
            onChange={(e) => {
              setRule(e.target.value)
              setPage(1)
            }}
            placeholder="如 word_review"
          />
        </Field>
        <Field label="方向">
          <Select
            value={direction}
            onChange={(e) => {
              setDirection(e.target.value)
              setPage(1)
            }}
          >
            <option value="">全部</option>
            {Object.entries(DIRECTION_LABEL).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {err ? <Alert tone="danger">{err}</Alert> : null}
      {!rows ? <Skeleton height={180} /> : null}
      {rows && !rows.items?.length ? (
        <Empty
          icon={<List size={26} />}
          title="没有符合条件的流水"
          text="换个筛选条件，或等新用户先产生学习行为。"
        />
      ) : null}
      {rows?.items?.length ? (
        <>
          <div className="v3-ops-scrolly">
            <table className="v3-ops-table">
              <thead>
                <tr>
                  <th>用户</th>
                  <th>归属日</th>
                  <th>规则</th>
                  <th>标题</th>
                  <th>金币</th>
                  <th>方向</th>
                </tr>
              </thead>
              <tbody>
                {rows.items.map((r) => (
                  <tr key={r.id}>
                    <td>
                      {r.username || '—'}
                      <span className="v3-gami-muted"> #{r.user_id}</span>
                    </td>
                    <td>{r.biz_date}</td>
                    <td>
                      <code>{r.rule_code}</code>
                    </td>
                    <td>{r.title}</td>
                    <td className="v3-gami-num">{r.coins > 0 ? `+${r.coins}` : r.coins}</td>
                    <td>{DIRECTION_LABEL[r.direction] || r.direction}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager
            page={rows.page}
            pageSize={rows.page_size}
            total={rows.total}
            totalPages={rows.total_pages}
            onChange={setPage}
            onPageSizeChange={(n) => {
              setPageSize(n)
              setPage(1)
            }}
            unit="条流水"
          />
        </>
      ) : null}

      <Dialog
        open={adjustOpen}
        title="人工调整金币"
        sub="用于补偿异常或收回误发；操作者 ID 与原因会写进流水，不可撤销（只能再调一次对冲）"
        onClose={() => setAdjustOpen(false)}
        footer={
          <>
            <Button variant="text" onClick={() => setAdjustOpen(false)}>
              取消
            </Button>
            <Button variant="danger" loading={adjusting} onClick={doAdjust}>
              确认调整
            </Button>
          </>
        }
      >
        <div className="v3-gami-stack" style={{ gap: 10 }}>
          {adjustErr ? <Alert tone="danger">{adjustErr}</Alert> : null}
          <div className="v3-ops-form">
            <Field label="用户 ID">
              <Input
                type="number"
                value={adjustForm.user_id}
                onChange={(e) => setAdjustForm({ ...adjustForm, user_id: e.target.value })}
              />
            </Field>
            <Field label="金币数额" hint={`正数发放 / 负数收回 · 绝对值 ≤ ${adjustMax}`}>
              <Input
                type="number"
                value={adjustForm.coins}
                onChange={(e) => setAdjustForm({ ...adjustForm, coins: e.target.value })}
              />
            </Field>
          </div>
          <Field label="原因" hint="至少 4 个字，审计要看懂">
            <Input
              value={adjustForm.reason}
              onChange={(e) => setAdjustForm({ ...adjustForm, reason: e.target.value })}
            />
          </Field>
        </div>
      </Dialog>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* 对外：标签页 + 用户详情卡                                            */
/* ------------------------------------------------------------------ */
export default function GamificationOps() {
  const [tab, setTab] = useState('overview')
  const [days, setDays] = useState(14)

  return (
    <div className="v3-gami-stack">
      <Tabs
        ariaLabel="激励运营视图"
        value={tab}
        onChange={setTab}
        options={[
          { value: 'overview', label: '发放大盘', icon: <Gauge size={14} /> },
          { value: 'rules', label: '规则与参数', icon: <SlidersHorizontal size={14} /> },
          { value: 'items', label: '商店商品', icon: <Trophy size={14} /> },
          { value: 'ledger', label: '发放审计', icon: <List size={14} /> },
        ]}
      />
      {tab === 'overview' ? <OpsOverview days={days} setDays={setDays} /> : null}
      {tab === 'rules' ? <OpsRules /> : null}
      {tab === 'items' ? <OpsItems /> : null}
      {tab === 'ledger' ? <OpsLedger /> : null}
      <Alert tone="info" icon={<Trophy size={18} />}>
        口径提醒：金币（本页面）只做激励兑换，等级与徽章仍由成长积分驱动（<code>/api/growth</code>）。
        两者不是同一个数，也不应该互相换算 —— 这是刻意设计，避免"为了刷等级刷题库"。
      </Alert>
    </div>
  )
}

/** 用户详情里的激励卡片（UserAdmin 详情抽屉复用） */
export function GamificationUserCard({ userId }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  // 不用 window.prompt（脱离 ui kit、移动端难用）：走平台 Dialog，口径与审计页一致
  const [adjust, setAdjust] = useState(null) // { coins, reason }
  const [adjustErr, setAdjustErr] = useState('')

  const load = useCallback(() => {
    if (!userId) return
    setErr('')
    coinsApi.admin
      .user(userId)
      .then(setData)
      .catch((e) => setErr(e?.message || '激励数据加载失败'))
  }, [userId])

  useEffect(() => {
    load()
  }, [load])

  const openAdjust = (coins) => {
    setAdjustErr('')
    setAdjust({ coins, reason: '' })
  }

  const submitAdjust = async () => {
    const coins = num(adjust.coins)
    const reason = adjust.reason.trim()
    if (!coins) {
      setAdjustErr('数额不能为 0')
      return
    }
    if (Math.abs(coins) > 2000) {
      setAdjustErr('单次调整默认不得超过 2000 币（后端参数 admin_adjust_max，超限会被拒绝）')
      return
    }
    if (reason.length < 4) {
      setAdjustErr('原因至少 4 个字，审计要能看懂')
      return
    }
    setBusy(true)
    try {
      const r = await coinsApi.admin.adjust({ user_id: userId, coins, reason })
      toastOk(`已调整，余额 ${r.balance}`)
      setAdjust(null)
      load()
    } catch (e) {
      setAdjustErr(e?.message || '调整失败')
    } finally {
      setBusy(false)
    }
  }

  if (!userId) return null
  if (err) return <Alert tone="danger">{err}</Alert>
  if (!data) return <Skeleton height={120} />
  return (
    <Tile span={12} as="section">
      <CardHead
        icon={<Trophy size={16} />}
        title="激励与签到"
        sub="来自 /api/gamification/admin"
        actions={
          <Button size="sm" variant="ghost" icon={<RefreshCw size={14} />} onClick={load}>
            刷新
          </Button>
        }
      />
      <div className="v3-ops-kpis">
        <div className="v3-ops-kpi">
          <div className="v3-ops-kpi__label">金币余额</div>
          <div className="v3-ops-kpi__value">{data.account?.balance}</div>
        </div>
        <div className="v3-ops-kpi">
          <div className="v3-ops-kpi__label">累计获得</div>
          <div className="v3-ops-kpi__value">{data.account?.total_earned}</div>
        </div>
        <div className="v3-ops-kpi">
          <div className="v3-ops-kpi__label">连续签到</div>
          <div className="v3-ops-kpi__value">{data.checkin_streak}</div>
        </div>
        <div className="v3-ops-kpi">
          <div className="v3-ops-kpi__label">连续学习</div>
          <div className="v3-ops-kpi__value">{data.study_streak}</div>
        </div>
        <div className="v3-ops-kpi">
          <div className="v3-ops-kpi__label">补签卡</div>
          <div className="v3-ops-kpi__value">{data.account?.makeup_cards}</div>
        </div>
      </div>
      <div className="v3-gami-inline" style={{ marginTop: 10 }}>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => openAdjust(50)}>
          发放 50
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => openAdjust(-50)}>
          收回 50
        </Button>
        <span className="v3-gami-muted">
          最近 {data.recent_ledger?.length || 0} 笔流水，最近签到 {data.checkins?.[0]?.biz_date || '无'}
        </span>
      </div>
      {data.recent_ledger?.length ? (
        <div className="v3-coin-ledger" style={{ marginTop: 8 }}>
          {data.recent_ledger.slice(0, 6).map((r) => (
            <div className="v3-coin-ledger__row" key={r.id}>
              <div>
                <div className="v3-coin-ledger__title">{r.title}</div>
                <div className="v3-coin-ledger__meta">
                  {r.biz_date} · {r.rule_code}
                </div>
              </div>
              <div
                className={`v3-coin-ledger__coins ${r.coins > 0 ? 'v3-coin-ledger__coins--plus' : 'v3-coin-ledger__coins--minus'}`}
              >
                {r.coins > 0 ? `+${r.coins}` : r.coins}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="v3-gami-muted" style={{ marginTop: 8 }}>
          该用户还没有金币流水（零数据 = 诚实空态，不发新手奖励）。
        </p>
      )}

      <Dialog
        open={!!adjust}
        title={`人工调整金币 · 用户 #${userId}`}
        sub="原因会写进审计流水并记操作者；不可撤销（只能再调一次对冲）。正数发放 / 负数收回"
        onClose={() => setAdjust(null)}
        footer={
          <>
            <Button variant="text" onClick={() => setAdjust(null)}>
              取消
            </Button>
            <Button variant="danger" loading={busy} onClick={submitAdjust}>
              确认调整
            </Button>
          </>
        }
      >
        {adjust ? (
          <div className="v3-gami-stack" style={{ gap: 10 }}>
            {adjustErr ? <Alert tone="danger">{adjustErr}</Alert> : null}
            <Field label="金币数额" hint="正数发放 / 负数收回 · 默认单次绝对值 ≤ 2000">
              <Input
                type="number"
                value={adjust.coins}
                onChange={(e) => setAdjust({ ...adjust, coins: e.target.value })}
              />
            </Field>
            <Field label="原因" hint="至少 4 个字，审计要看懂">
              <Input
                value={adjust.reason}
                onChange={(e) => setAdjust({ ...adjust, reason: e.target.value })}
                placeholder="如：活动误发回收 / 竞赛补偿"
              />
            </Field>
          </div>
        ) : null}
      </Dialog>
    </Tile>
  )
}
