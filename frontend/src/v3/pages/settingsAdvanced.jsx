/* ============================================================
   settingsAdvanced.jsx —— 设置页「个人资料」与「金币激励」分区（W6）
   ------------------------------------------------------------
   拆成独立模块而不是继续往 Settings.jsx 里堆：设置页主文件已 2000+ 行，
   这两个分区的状态机（草稿 diff / 偏好即时保存 / 签到与兑换）各自独立，
   放一起会让任何一处改动都要回归整页。

   诚实原则（本轮整改铁律）：
   * 所有数字都来自 /api/gamification 与 /api/profile，前端不写死任何奖励值；
   * 后端返回 state='empty' 时显示引导空态，不画"0 金币 + 假里程碑"；
   * 偏好项必须在前端真被消费（见 useProfilePrefs 落到 <html data-*>），
     加了不生效的开关一律不许出现在这里。
   ============================================================ */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BLOCKED_LABEL, CHECKIN_KIND_LABEL, FRAME_CLASS, coinsApi, profileApi } from '../../api/gamification'
import {
  Alert,
  AnimatedNumber,
  Badge,
  Button,
  Card,
  CardHead,
  Chip,
  Empty,
  Field,
  Input,
  Progress,
  Segmented,
  Select,
  Skeleton,
  Switch,
  Textarea,
  toast,
  toastErr,
  toastOk,
  toastWarn,
} from '../ui'
import { Book, Calendar, Check, List, RefreshCw, Sparkles, Star, Target, Trophy, Zap } from '../icons'
import { applyProfilePrefs } from '../../hooks/useProfilePrefs'
import '../styles/gamification-v3.css'

/** 取 ISO 日期的「MM-DD」片段；空值返回「—」。 */
const fmtDay = (iso) => (iso ? iso.slice(5) : '—')
/** 将 ISO 字符串格式化为本地时间；空值返回「—」。 */
const fmtDateTime = (iso) => (iso ? new Date(iso).toLocaleString('zh-CN', { hour12: false }) : '—')
const MONTH_CN = { sm: '紧凑', md: '标准', lg: '宽松' }

/**
 * GET /api/profile 的**嵌套**结构里抽出「可编辑基线」。
 * 注意不对称（后端契约）：GET 返回 {account, profile, coins, options} 嵌套，
 * PUT 返回的是**扁平** profile_dict + ignored_pref_keys，两者不同构，
 * 所以保存成功后一律走 reload() 重新拿嵌套全量，绝不把 PUT 响应直接塞进 data。
 */
function profileBase(d) {
  return {
    display_name: d?.account?.display_name || '',
    bio: d?.profile?.bio || '',
    grade: d?.profile?.grade || '',
    major: d?.profile?.major || '',
    avatar_kind: d?.profile?.avatar_kind || 'initials',
    avatar_value: d?.profile?.avatar_value || 'teal',
    // 后端只会回传**已解锁**的佩戴项（被回收的自动脱落），空串 = 未佩戴 / 卸下
    avatar_frame: d?.profile?.avatar_frame || '',
    avatar_title: d?.profile?.avatar_title || '',
  }
}

/* ------------------------------------------------------------------ */
/* 个人资料                                                            */
/* ------------------------------------------------------------------ */
/** 头像预览：根据 kind 渲染外链图片 / 内置表情 / 首字色块，叠加头像框与称号。 */
function AvatarPreview({ profile }) {
  const kind = profile?.avatar_kind || 'initials'
  const value = profile?.avatar_value || 'teal'
  const frame = profile?.avatar_frame
  const frameClass = frame ? FRAME_CLASS[frame.replace('frame_', '')] || '' : ''
  const name = profile?.display_name || profile?.username || '学'
  const title = profile?.title_label

  const body =
    kind === 'url' && value ? (
      <img
        src={value}
        alt=""
        onError={(e) => {
          e.currentTarget.style.display = 'none'
        }}
      />
    ) : kind === 'preset' ? (
      value || '🦉'
    ) : (
      name.slice(0, 1)
    )

  return (
    <div className="v3-profile-head">
      <div
        className={`v3-profile-avatar v3-profile-avatar--${kind === 'initials' ? value || 'teal' : 'teal'} ${frameClass}`}
        aria-label="当前头像"
      >
        {body}
      </div>
      <div className="v3-profile-meta">
        <span className="v3-profile-meta__name">{name}</span>
        <span className="v3-gami-muted">
          {profile?.username ? `@${profile.username}` : ''}
          {profile?.grade ? ` · ${profile.grade}` : ''}
          {profile?.major ? ` · ${profile.major}` : ''}
        </span>
        {title ? <span className="v3-profile-title">{title}</span> : null}
        {profile?.bio ? <span className="v3-gami-muted">{profile.bio}</span> : null}
      </div>
    </div>
  )
}

/** 个人资料分区：维护草稿 diff，按改动键提交 PATCH，偏好即时保存并落到 <html data-*>。 */
export function ProfilePanel({ profileState }) {
  const { data, loading, error, reload, setData } = profileState
  const [draft, setDraft] = useState({})
  const [saving, setSaving] = useState(false)
  const [avatarTab, setAvatarTab] = useState('initials')

  useEffect(() => {
    if (!data) return
    setDraft(profileBase(data))
    setAvatarTab(data.profile?.avatar_kind || 'initials')
  }, [data])

  const prefs = data?.profile?.prefs || {}
  const unlocked = data?.profile?.unlocked || { frames: [], titles: [] }
  // 422 门禁：后端只接受 profile.unlocked.frames/.titles 里的 code，未解锁的候选根本不给选
  const frames = (data?.profile?.frame_catalog || []).filter((f) => unlocked.frames.includes(f.code))
  const titles = (data?.profile?.title_catalog || []).filter((t) => unlocked.titles.includes(t.code))
  const set = useCallback((key) => (e) => setDraft((d) => ({ ...d, [key]: e?.target ? e.target.value : e })), [])

  const dirty = useMemo(() => {
    if (!data) return false
    const base = profileBase(data)
    return Object.keys(base).some((k) => (draft[k] || '') !== base[k])
  }, [data, draft])

  const save = useCallback(async () => {
    if (!dirty) {
      toast('没有需要保存的修改')
      return
    }
    setSaving(true)
    try {
      // 只提交真正改过的键（后端 PATCH 语义）：全量回传会把没动过的头像组合
      // 重新校验一遍，平白多出 422 面；空串对 frame/title 表示「卸下」(200→null)
      const base = profileBase(data)
      const body = {}
      Object.keys(base).forEach((k) => {
        if ((draft[k] || '') !== base[k]) body[k] = draft[k] ?? ''
      })
      if (body.display_name !== undefined && !String(body.display_name).trim()) {
        toastErr('显示名不能为空白（后端会拒绝 422，这里先拦住）')
        return
      }
      await profileApi.update(body)
      await reload() // PUT 是扁平结构，不能直接 setData(res)，见 profileBase 注释
      toastOk('资料已保存')
    } catch (e) {
      toastErr(e?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }, [data, draft, dirty, reload])

  const savePref = useCallback(async (key, value) => {
    const nextPrefs = { ...prefs, [key]: value }
    setData((d) => (d ? { ...d, profile: { ...d.profile, prefs: nextPrefs } } : d))
    applyProfilePrefs(nextPrefs)
    try {
      const res = await profileApi.update({ prefs: { [key]: value } })
      // 白名单外键后端不报错、只回 ignored_pref_keys —— 出现即说明前端控件已失效，必须暴露而不是静默
      if (res?.ignored_pref_keys?.length) {
        toastWarn(`后端偏好白名单不含：${res.ignored_pref_keys.join('、')}（该控件已失效，请报告）`)
        await reload()
      }
    } catch (e) {
      toastErr(e?.message || '偏好保存失败，已恢复')
      await reload()
    }
  }, [prefs, setData, reload])

  if (loading && !data) {
    return (
      <div className="v3-gami-stack">
        <Skeleton height={92} />
        <Skeleton height={180} />
      </div>
    )
  }
  if (error && !data) {
    return (
      <Card>
        <Alert tone="danger" icon={<Target size={18} />}>
          {error}（后端未启动或接口 /api/profile 尚未挂载时会出现这条提示）
        </Alert>
        <div className="v3-gami-inline" style={{ marginTop: 12 }}>
          <Button variant="outline" icon={<RefreshCw size={14} />} onClick={reload}>
            重试
          </Button>
        </div>
      </Card>
    )
  }

  const preview = {
    ...data?.profile,
    ...draft,
    display_name: draft.display_name || data?.account?.display_name,
    username: data?.account?.username,
    title_label: (data?.profile?.title_catalog || []).find((t) => t.code === draft.avatar_title)?.title,
    // 头像框样式取商品 payload.frame（管理员自定义商品码也对得上 CSS class），
    // 目录查不到再回落「去 frame_ 前缀」的种子命名约定
    avatar_frame:
      (data?.profile?.frame_catalog || []).find((f) => f.code === draft.avatar_frame)?.frame ||
      draft.avatar_frame,
  }

  return (
    <div className="v3-gami-stack">
      <Card variant="aurora">
        <CardHead
          icon={<Sparkles size={16} />}
          title="对外展示"
          sub="头像、称号与简介会出现在设置页与个人中心；称号需先在金币商店兑换"
        />
        <AvatarPreview profile={preview} />
      </Card>

      <Card>
        <CardHead
          icon={<Star size={16} />}
          title="头像"
          sub="首字色块 / 内置表情 / 外链图片，三种都离线可用（外链需你自己保证图片可访问）"
        />
        <div className="v3-gami-stack" style={{ gap: 12 }}>
          <Segmented
            ariaLabel="头像类型"
            value={avatarTab}
            onChange={(v) => {
              setAvatarTab(v)
              setDraft((d) => ({
                ...d,
                avatar_kind: v,
                avatar_value:
                  v === 'initials'
                    ? 'teal'
                    : v === 'preset'
                      ? data?.options?.avatar_presets?.[0] || '🦉'
                      : '',
              }))
            }}
            options={[
              { value: 'initials', label: '首字色块' },
              { value: 'preset', label: '内置表情' },
              { value: 'url', label: '图片链接' },
            ]}
          />

          {avatarTab === 'initials' ? (
            <div className="v3-avatar-picker" role="group" aria-label="头像配色">
              {(data?.options?.avatar_colors || []).map((c) => (
                <button
                  type="button"
                  key={c}
                  className={`v3-avatar-chip v3-profile-avatar--${c}`}
                  aria-pressed={draft.avatar_value === c}
                  aria-label={`配色 ${c}`}
                  onClick={() => setDraft((d) => ({ ...d, avatar_value: c }))}
                >
                  {(draft.display_name || data?.account?.display_name || '学').slice(0, 1)}
                </button>
              ))}
            </div>
          ) : null}

          {avatarTab === 'preset' ? (
            <div className="v3-avatar-picker" role="group" aria-label="内置头像">
              {(data?.options?.avatar_presets || []).map((p) => (
                <button
                  type="button"
                  key={p}
                  className="v3-avatar-chip"
                  aria-pressed={draft.avatar_value === p}
                  aria-label={`头像 ${p}`}
                  onClick={() => setDraft((d) => ({ ...d, avatar_value: p }))}
                >
                  {p}
                </button>
              ))}
            </div>
          ) : null}

          {avatarTab === 'url' ? (
            <Field label="图片地址" hint="仅支持 http(s) 完整链接；后端会拒绝 javascript: 等危险协议">
              <Input
                value={draft.avatar_value || ''}
                onChange={set('avatar_value')}
                placeholder="https://cdn.example.com/avatar.png"
              />
            </Field>
          ) : null}

          <div className="v3-gami-grid">
            <Field label="头像框" hint="未解锁的头像框可在「金币激励 - 商店」兑换">
              <Select value={draft.avatar_frame || ''} onChange={set('avatar_frame')} aria-label="头像框">
                <option value="">不使用</option>
                {frames.map((f) => (
                  <option key={f.code} value={f.code}>
                    {f.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="称号" hint="称号同样需先兑换；卸下请选「不佩戴」">
              <Select value={draft.avatar_title || ''} onChange={set('avatar_title')} aria-label="称号">
                <option value="">不佩戴</option>
                {titles.map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        </div>
      </Card>

      <Card>
        <CardHead
          icon={<Book size={16} />}
          title="基本信息"
          sub="目标院校与初试科目在「目标与概览」里配置，这里只放个人标识"
        />
        <div className="v3-gami-grid">
          <Field label="显示名" hint="最长 64 字，不能为空白">
            <Input value={draft.display_name || ''} onChange={set('display_name')} maxLength={64} />
          </Field>
          <Field label="届数 / 年级" hint="仅展示用，例如 2027 届">
            <Input value={draft.grade || ''} onChange={set('grade')} maxLength={20} placeholder="2027 届" />
          </Field>
          <Field label="专业方向" hint="自由文本；专业课清单以「目标与概览」为准">
            <Input
              value={draft.major || ''}
              onChange={set('major')}
              maxLength={60}
              placeholder="例如 电子信息 · 集成电路"
            />
          </Field>
        </div>
        <Field label="简介" hint={`最长 200 字（已写 ${(draft.bio || '').length} 字）`}>
          <Textarea
            rows={3}
            value={draft.bio || ''}
            onChange={set('bio')}
            maxLength={200}
            placeholder="一句话说明你的备考主线"
          />
        </Field>
        <div className="v3-gami-inline" style={{ marginTop: 12 }}>
          <Button onClick={save} loading={saving} disabled={!dirty} icon={<Check size={14} />}>
            保存修改
          </Button>
          {dirty ? <Badge tone="warning">有未保存的修改</Badge> : <Badge tone="outline">已是最新</Badge>}
        </div>
      </Card>

      <Card>
        <CardHead
          icon={<Zap size={16} />}
          title="界面偏好"
          sub="开关即时生效并写入服务器（换设备登录同样生效）；每一项都在前端真有消费点"
        />
        <div>
          <div className="v3-pref-row">
            <div>
              <div className="v3-pref-row__label">减少动效</div>
              <div className="v3-pref-row__hint">关闭全站过渡与动画（对晕动敏感或低配设备有用）</div>
            </div>
            <Switch
              checked={!!prefs.reduce_motion}
              onChange={(v) => savePref('reduce_motion', v)}
              label="减少动效"
            />
          </div>
          <div className="v3-pref-row">
            <div>
              <div className="v3-pref-row__label">紧凑布局</div>
              <div className="v3-pref-row__hint">收紧设置页与管理台的间距，一屏看更多内容</div>
            </div>
            <Switch
              checked={!!prefs.compact_mode}
              onChange={(v) => savePref('compact_mode', v)}
              label="紧凑布局"
            />
          </div>
          <div className="v3-pref-row">
            <div>
              <div className="v3-pref-row__label">字号密度</div>
              <div className="v3-pref-row__hint">整站根字号：紧凑 14px / 标准 16px / 宽松 17px</div>
            </div>
            <Select
              aria-label="字号密度"
              value={prefs.font_scale || 'md'}
              onChange={(e) => savePref('font_scale', e.target.value)}
            >
              {Object.entries(MONTH_CN).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </Select>
          </div>
          <div className="v3-pref-row">
            <div>
              <div className="v3-pref-row__label">周起始日</div>
              <div className="v3-pref-row__hint">影响「金币激励 - 签到日历」的排布</div>
            </div>
            <Select
              aria-label="周起始日"
              value={prefs.week_start || 'mon'}
              onChange={(e) => savePref('week_start', e.target.value)}
            >
              <option value="mon">周一</option>
              <option value="sun">周日</option>
            </Select>
          </div>
          <div className="v3-pref-row">
            <div>
              <div className="v3-pref-row__label">金币到账提示</div>
              <div className="v3-pref-row__hint">
                进入金币分区时，若本次同步真有新发放才提示（不发假提示）
              </div>
            </div>
            <Switch
              checked={prefs.coin_toast !== false}
              onChange={(v) => savePref('coin_toast', v)}
              label="金币到账提示"
            />
          </div>
          <div className="v3-pref-row">
            <div>
              <div className="v3-pref-row__label">签到日历天数</div>
              <div className="v3-pref-row__hint">回看多远：7~120 天</div>
            </div>
            <Select
              aria-label="签到日历天数"
              value={String(prefs.calendar_days || 35)}
              onChange={(e) => savePref('calendar_days', Number(e.target.value))}
            >
              {[14, 35, 60, 120].map((d) => (
                <option key={d} value={d}>
                  近 {d} 天
                </option>
              ))}
            </Select>
          </div>
        </div>
      </Card>

      <Card>
        <CardHead
          icon={<Target size={16} />}
          title="账号信息（只读）"
          sub="改密码、邮箱验证、注销请到「账号与安全」"
        />
        <div className="v3-gami-grid">
          <div className="v3-coin-stat">
            <span className="v3-coin-stat__label">登录名</span>
            <span className="v3-coin-stat__value">{data?.account?.username || '—'}</span>
          </div>
          <div className="v3-coin-stat">
            <span className="v3-coin-stat__label">角色</span>
            <span className="v3-coin-stat__value">
              {data?.account?.role === 'admin' ? '管理员' : '普通用户'}
            </span>
          </div>
          <div className="v3-coin-stat">
            <span className="v3-coin-stat__label">邮箱</span>
            <span className="v3-coin-stat__value">{data?.account?.email || '未绑定'}</span>
            <span className="v3-coin-stat__hint">
              {data?.account?.email
                ? data.account.email_verified
                  ? '已验证'
                  : '未验证，找回密码功能不可用'
                : ''}
            </span>
          </div>
          <div className="v3-coin-stat">
            <span className="v3-coin-stat__label">注册时间</span>
            <span className="v3-coin-stat__value" style={{ fontSize: 14 }}>
              {fmtDateTime(data?.account?.created_at)}
            </span>
          </div>
          <div className="v3-coin-stat">
            <span className="v3-coin-stat__label">最近登录</span>
            <span className="v3-coin-stat__value" style={{ fontSize: 14 }}>
              {fmtDateTime(data?.account?.last_login_at)}
            </span>
          </div>
        </div>
      </Card>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* 金币激励                                                            */
/* ------------------------------------------------------------------ */
function CheckinStrip({ days = [], weekStart = 'mon', cards = 0, onMakeup, busyDate }) {
  const [showAll, setShowAll] = useState(false)
  const list = showAll ? days : days.slice(-14)
  // week_start 偏好在这里**真被消费**：每列一周、共 7 行，首行 = 周起始日。
  // 首日之前垫空格子对齐（否则这个开关就是个死控件）。
  const firstDow = list.length ? new Date(`${list[0].date}T00:00:00`).getDay() : 0
  const offset = weekStart === 'sun' ? firstDow : (firstDow + 6) % 7
  return (
    <div>
      <div className="v3-checkin-strip" role="list" aria-label="签到日历">
        {Array.from({ length: offset }, (_, i) => (
          <div key={`pad-${i}`} className="v3-checkin-cell v3-checkin-cell--pad" aria-hidden="true" />
        ))}
        {list.map((d) => {
          const makeupable = !d.checked && d.is_active && !d.is_effective && d.kind !== 'makeup'
          const cls = ['v3-checkin-cell']
          if (d.kind === 'manual') cls.push('v3-checkin-cell--manual')
          else if (d.kind === 'makeup') cls.push('v3-checkin-cell--makeup')
          else if (d.is_effective) cls.push('v3-checkin-cell--effective')
          else if (d.is_active) cls.push('v3-checkin-cell--missed')
          if (makeupable) cls.push('v3-checkin-cell--button')
          if (d.date === days[days.length - 1]?.date) cls.push('v3-checkin-cell--today')
          return (
            <button
              type="button"
              key={d.date}
              role="listitem"
              className={cls.join(' ')}
              disabled={!makeupable || cards <= 0 || !!busyDate}
              onClick={() => (makeupable ? onMakeup(d.date) : undefined)}
              title={
                `${d.date}｜` +
                (d.kind
                  ? CHECKIN_KIND_LABEL[d.kind] || d.kind
                  : d.is_active
                    ? '有学习痕迹但未签到'
                    : '没有学习记录') +
                (makeupable ? (cards > 0 ? '（点一下用补签卡补上）' : '（需要补签卡）') : '')
              }
              aria-label={`${d.date} ${d.checked ? '已签到' : '未签到'}`}
            >
              <span className="v3-checkin-cell__day">{fmtDay(d.date)}</span>
              <span>{d.kind === 'makeup' ? '补' : d.checked ? '✓' : d.is_active ? '·' : ''}</span>
            </button>
          )
        })}
      </div>
      <div className="v3-gami-inline" style={{ marginTop: 8 }}>
        <span className="v3-gami-muted">
          日历每列一周、共 7 行，首行 = {weekStart === 'sun' ? '周日' : '周一'}（在「个人资料 -
          界面偏好」可改，改这里排版会跟着变）·
          有效学习日自动计入连续签到，无需手点；点灰色格子可用补签卡补窗口期内的漏签
        </span>
        {days.length > 14 ? (
          <Chip active={showAll} onClick={() => setShowAll((v) => !v)}>
            {showAll ? '只看近两周' : `看近 ${days.length} 天`}
          </Chip>
        ) : null}
      </div>
    </div>
  )
}

function LedgerList({ rows = [], loading }) {
  if (loading) return <Skeleton height={120} />
  if (!rows.length) {
    return (
      <Empty
        icon={<List size={26} />}
        title="还没有金币流水"
        text="去背单词、复习错题或刷题，回到这一页同步就会按规则发放。"
      />
    )
  }
  return (
    <div className="v3-coin-ledger">
      {rows.map((r) => {
        const sign = r.coins > 0 ? '+' : ''
        const tone =
          r.coins > 0
            ? 'v3-coin-ledger__coins--plus'
            : r.coins < 0
              ? 'v3-coin-ledger__coins--minus'
              : 'v3-coin-ledger__coins--zero'
        return (
          <div className="v3-coin-ledger__row" key={r.id}>
            <div>
              <div className="v3-coin-ledger__title">{r.title || r.rule_code}</div>
              <div className="v3-coin-ledger__meta">
                {r.biz_date} · {r.rule_code}
                {r.meta?.unit_price ? ` · 单价 ${r.meta.unit_price}` : ''}
                {r.meta?.reason ? ` · ${r.meta.reason}` : ''}
              </div>
            </div>
            <div className={`v3-coin-ledger__coins ${tone}`}>{r.coins === 0 ? '—' : `${sign}${r.coins}`}</div>
          </div>
        )
      })}
    </div>
  )
}

function ShopGrid({ shop, onRedeem, busyCode }) {
  if (!shop) return <Skeleton height={140} />
  return (
    <div className="v3-coin-shop">
      {shop.items.map((it) => (
        <div className={`v3-coin-item ${it.owned ? 'v3-coin-item--owned' : ''}`} key={it.code}>
          <div className="v3-coin-item__head">
            <span className="v3-coin-item__name">{it.name}</span>
            <Badge tone={it.kind === 'makeup_card' ? 'primary' : it.kind === 'boost' ? 'warning' : 'outline'}>
              {it.kind === 'makeup_card'
                ? '补签卡'
                : it.kind === 'boost'
                  ? '加成'
                  : it.kind === 'avatar_frame'
                    ? '头像框'
                    : '称号'}
            </Badge>
          </div>
          <span className="v3-coin-item__desc">{it.description}</span>
          <div className="v3-gami-inline" style={{ justifyContent: 'space-between' }}>
            <span className="v3-coin-item__cost">{it.cost_coins} 币</span>
            <Button
              size="sm"
              variant={it.blocked === 'owned' ? 'ghost' : 'primary'}
              disabled={!!it.blocked && it.blocked !== 'insufficient'}
              loading={busyCode === it.code}
              onClick={() => onRedeem(it)}
            >
              {it.blocked ? BLOCKED_LABEL[it.blocked] || '不可兑换' : '兑换'}
            </Button>
          </div>
          {it.monthly_limit ? (
            <span className="v3-gami-muted">
              本月 {it.used_this_month}/{it.monthly_limit} 次
            </span>
          ) : null}
        </div>
      ))}
    </div>
  )
}

function RulesTable({ rules }) {
  if (!rules) return <Skeleton height={160} />
  return (
    <div className="v3-ops-scrolly">
      <table className="v3-coin-rules">
        <thead>
          <tr>
            <th>途径</th>
            <th>一次的定义</th>
            <th>金币</th>
            <th>单日上限</th>
          </tr>
        </thead>
        <tbody>
          {(rules.rules || []).map((r) => (
            <tr key={r.rule_code}>
              <td>{r.label}</td>
              <td>
                {r.kind === 'batch'
                  ? `每 ${r.per_units} ${r.unit_label || '个'}`
                  : r.kind === 'per_item'
                    ? `每 1 ${r.unit_label || '个'}`
                    : '每天 1 次'}
              </td>
              <td className="v3-gami-num">+{r.coins}</td>
              <td className="v3-gami-num">
                {r.daily_cap} 次（{r.daily_cap * r.coins} 币）
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="v3-gami-muted" style={{ marginTop: 8 }}>
        全局单日上限 {rules.settings?.daily_earn_cap} 币；连续签到里程碑：
        {(rules.milestones || []).map((m) => `${m.days} 天 +${m.coins}`).join('、') || '未配置'}。
        金币只用于商店兑换，不影响等级 —— 等级看「成长积分」（/api/growth 口径）。
      </p>
    </div>
  )
}

export function CoinsPanel({ coinToast = true, weekStart = 'mon', calendarDays = 35 }) {
  const [summary, setSummary] = useState(null)
  const [cal, setCal] = useState(null)
  const [shop, setShop] = useState(null)
  const [ledger, setLedger] = useState(null)
  const [rules, setRules] = useState(null)
  const [loading, setLoading] = useState(true)
  const [ledgerLoading, setLedgerLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyCheckin, setBusyCheckin] = useState(false)
  const [busyCode, setBusyCode] = useState('')
  const [busyDate, setBusyDate] = useState('')
  const [page, setPage] = useState(1)
  const didSync = useRef(false)

  // 核心四路（总览/日历/商店/规则）一起刷；流水分页独立刷，
  // 避免翻一页流水就重跑一次 sync（会重复触发同步 toast）。
  const loadCore = useCallback(
    async ({ sync: doSync = false } = {}) => {
      setLoading(true)
      setError('')
      try {
        if (doSync) {
          const r = await coinsApi.sync()
          if (r?.granted_coins > 0 && coinToast) {
            toastOk(`今日学习已折算 +${r.granted_coins} 金币`)
          }
        }
        const [s, c, sh, rl] = await Promise.all([
          coinsApi.summary(),
          coinsApi.calendar(calendarDays),
          coinsApi.shop(),
          coinsApi.rules(),
        ])
        setSummary(s)
        setCal(c)
        setShop(sh)
        setRules(rl)
      } catch (e) {
        setError(e?.message || '金币数据加载失败')
      } finally {
        setLoading(false)
      }
    },
    [calendarDays, coinToast],
  )

  const loadLedger = useCallback(() => {
    setLedgerLoading(true)
    coinsApi
      .ledger({ page, page_size: 10 })
      .then(setLedger)
      .catch((e) => toastErr(e?.message || '流水加载失败'))
      .finally(() => setLedgerLoading(false))
  }, [page])

  useEffect(() => {
    // 进入分区时同步一次（幂等，重复调只补差额）；偏好到位导致的依赖变化不重复 sync
    const needSync = !didSync.current
    didSync.current = true
    loadCore({ sync: needSync })
  }, [loadCore])

  useEffect(() => {
    loadLedger()
  }, [loadLedger])

  const refresh = useCallback(() => Promise.all([loadCore(), loadLedger()]), [loadCore, loadLedger])

  const doCheckin = async () => {
    setBusyCheckin(true)
    try {
      const r = await coinsApi.checkin()
      toastOk(`签到成功 +${r.coins} 金币 · 连续 ${r.checkin_streak} 天`)
      await refresh()
    } catch (e) {
      toastErr(e?.message || '签到失败')
    } finally {
      setBusyCheckin(false)
    }
  }

  const doMakeup = async (date) => {
    setBusyDate(date)
    try {
      const r = await coinsApi.makeup(date)
      toastOk(`已用补签卡补上 ${date}（连续 ${r.checkin_streak} 天）`)
      await refresh()
    } catch (e) {
      toastErr(e?.message || '补签失败')
    } finally {
      setBusyDate('')
    }
  }

  const doRedeem = async (item) => {
    if (!item.affordable && item.blocked === 'insufficient') {
      toastWarn(`还差 ${item.cost_coins - (shop?.balance || 0)} 金币`)
      return
    }
    setBusyCode(item.code)
    try {
      const r = await coinsApi.redeem(item.code)
      toastOk(`已兑换「${r.name}」，余额 ${r.balance}`)
      await refresh()
    } catch (e) {
      toastErr(e?.message || '兑换失败')
    } finally {
      setBusyCode('')
    }
  }

  if (loading && !summary) {
    return (
      <div className="v3-gami-stack">
        <Skeleton height={120} />
        <Skeleton height={200} />
      </div>
    )
  }
  if (error && !summary) {
    return (
      <Card>
        <Alert tone="danger">{error}</Alert>
        <div className="v3-gami-inline" style={{ marginTop: 12 }}>
          <Button variant="outline" icon={<RefreshCw size={14} />} onClick={() => loadCore({ sync: true })}>
            重试
          </Button>
        </div>
      </Card>
    )
  }

  const today = summary?.today || {}
  const streak = summary?.streak || {}
  const acct = summary?.account || {}
  const isEmpty = summary?.state === 'empty'
  const checkinBase = summary?.checkin_base_coins

  // 空态引导里的数字取自后端规则，规则没到位就不报数（不写死奖励值）
  const earnHint = (() => {
    const rs = rules?.rules || []
    const w = rs.find((r) => r.rule_code === 'word_review')
    const e = rs.find((r) => r.rule_code === 'error_review')
    const parts = []
    if (w) parts.push(`背 ${w.per_units} 个单词（+${w.coins} 币）`)
    if (e) parts.push(`复习 ${e.per_units} 道错题（+${e.coins} 币）`)
    return parts.length
      ? `今天先${parts.join('或')}，回这一页点「按今日学习同步」就会到账。`
      : '先去背单词 / 复习错题 / 刷题，回这一页点「按今日学习同步」就会按规则到账。'
  })()

  return (
    <div className="v3-gami-stack">
      <Card variant="aurora">
        <CardHead
          icon={<Trophy size={16} />}
          title="金币中心"
          sub="金币由后端按你的真实学习痕迹折算（客户端报不出任何数值），可攒可花"
          actions={
            <Badge tone={acct.boost_active ? 'warning' : 'outline'}>
              {/* 倍率取后端全局参数 boost_multiplier，不写死 ×1.5 */}
              {acct.boost_active ? `加成中 ×${rules?.settings?.boost_multiplier ?? ''}` : '无加成'}
            </Badge>
          }
        />
        <div className="v3-coin-hero">
          <div className="v3-coin-balance">
            <span className="v3-coin-balance__unit">可用金币</span>
            <span className="v3-coin-balance__value">
              <AnimatedNumber value={acct.balance || 0} />
            </span>
            <span className="v3-gami-muted">
              累计获得 {acct.total_earned || 0} · 已花 {acct.total_spent || 0} · 补签卡{' '}
              {acct.makeup_cards || 0} 张
            </span>
            <div className="v3-gami-inline" style={{ marginTop: 6 }}>
              <Button
                variant={today.checked ? 'outline' : 'primary'}
                disabled={today.checked || !today.is_active}
                loading={busyCheckin}
                onClick={doCheckin}
                icon={<Calendar size={14} />}
              >
                {/* 签到币数取后端 checkin_base_coins（管理员可改），不写死 +5 */}
                {today.checked
                  ? '今天已签到'
                  : today.is_active
                    ? `签到${checkinBase ? ` +${checkinBase}` : ''}`
                    : '今天还没有学习痕迹'}
              </Button>
              <Button
                variant="ghost"
                onClick={() => loadCore({ sync: true })}
                icon={<RefreshCw size={14} />}
                loading={loading}
              >
                按今日学习同步
              </Button>
            </div>
          </div>
          <div className="v3-coin-stats">
            <div className="v3-coin-stat">
              <span className="v3-coin-stat__label">今日发放 / 上限</span>
              <span className="v3-coin-stat__value">
                {today.earned ?? 0} / {today.cap ?? '—'}
              </span>
              <Progress value={today.cap ? ((today.earned || 0) / today.cap) * 100 : 0} />
              <span className="v3-coin-stat__hint">
                还能再拿 {today.remaining ?? 0} 币（顶到上限会如实提示，不静默吞掉）
              </span>
            </div>
            <div className="v3-coin-stat">
              <span className="v3-coin-stat__label">连续签到</span>
              <span className="v3-coin-stat__value">{streak.checkin_days ?? 0} 天</span>
              <span className="v3-coin-stat__hint">
                {streak.next_milestone
                  ? `下个里程碑 ${streak.next_milestone.days} 天 +${streak.next_milestone.coins} 币`
                  : '里程碑已全部达成'}
              </span>
            </div>
            <div className="v3-coin-stat">
              <span className="v3-coin-stat__label">连续学习（首页 KPI 同口径）</span>
              <span className="v3-coin-stat__value">{streak.study_days ?? 0} 天</span>
              <span className="v3-coin-stat__hint">历史最长 {streak.study_longest ?? 0} 天</span>
            </div>
            <div className="v3-coin-stat">
              <span className="v3-coin-stat__label">今天</span>
              <span className="v3-coin-stat__value">
                {today.is_effective ? '有效学习日' : today.is_active ? '有学习痕迹' : '还没开始'}
              </span>
              <span className="v3-coin-stat__hint">{streak.study_rule || ''}</span>
            </div>
          </div>
          {/* 两条 streak 是后端既定事实（checkin_days 与 study_days 口径不同），同屏并列 + 官方口径说明，避免「首页7天/金币页3天」式的错觉 */}
          {streak.note ? (
            <p className="v3-gami-muted" style={{ marginTop: 8 }}>
              {streak.note}
            </p>
          ) : null}
        </div>
        {isEmpty ? (
          <Alert tone="info" icon={<Sparkles size={18} />} className="v3-gami-sectionhead">
            还没有金币。这不是 Bug：新账号必须真做过事才有奖励（零数据不预置流水，也不发「欢迎奖励」）。
            {earnHint}
          </Alert>
        ) : null}
      </Card>

      <Card>
        <CardHead
          icon={<Calendar size={16} />}
          title="签到日历"
          sub="绿=有效学习日（自动计入）· 蓝=手动签到 · 紫=补签"
        />
        <CheckinStrip
          days={cal?.days || []}
          weekStart={weekStart}
          cards={acct.makeup_cards || 0}
          onMakeup={doMakeup}
          busyDate={busyDate}
        />
      </Card>

      <Card>
        <CardHead
          icon={<Zap size={16} />}
          title="金币商店"
          sub="只上架系统真能兑现的权益：补签卡、加成卡、头像框、称号"
          actions={<Badge tone="primary">余额 {shop?.balance ?? 0}</Badge>}
        />
        <ShopGrid shop={shop} onRedeem={doRedeem} busyCode={busyCode} />
      </Card>

      <Card>
        <CardHead
          icon={<List size={16} />}
          title="金币流水"
          sub="每一笔都可回溯到具体规则与单位"
          actions={
            <div className="v3-gami-inline">
              <Button
                size="sm"
                variant="ghost"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </Button>
              <span className="v3-gami-muted">
                第 {page} / {ledger?.total_pages || 1} 页
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={!ledger || page >= ledger.total_pages}
                onClick={() => setPage((p) => p + 1)}
              >
                下一页
              </Button>
            </div>
          }
        />
        <LedgerList rows={ledger?.items || []} loading={ledgerLoading} />
      </Card>

      <Card>
        <CardHead
          icon={<Target size={16} />}
          title="怎么算的"
          sub="规则来自后端（管理员可调），这里展示的是当前生效值"
        />
        <RulesTable rules={rules} />
      </Card>
    </div>
  )
}

/** 轻量金币条：给概览分区/主控层复用（只读，不带商店逻辑）。
 *  两条 streak（连续学习 = 首页口径 / 连续签到）都展示，避免只显一条造成页面间"打架"。 */
export function CoinStrip() {
  const [summary, setSummary] = useState(null)
  const [hidden, setHidden] = useState(false)
  useEffect(() => {
    let alive = true
    coinsApi
      .summary()
      .then((d) => {
        if (alive) setSummary(d)
      })
      .catch(() => {
        if (alive) setHidden(true)
      })
    return () => {
      alive = false
    }
  }, [])
  if (hidden || !summary) return null
  const t = summary.today || {}
  return (
    <div className="v3-gami-inline" style={{ justifyContent: 'space-between' }}>
      <span className="v3-gami-muted">
        <Trophy size={13} /> 金币 {summary.account?.balance ?? 0}
        {' · 连续学习 '}
        {summary.streak?.study_days ?? 0} 天（首页同口径）
        {' · 连续签到 '}
        {summary.streak?.checkin_days ?? 0} 天{t.checked ? ' · 今日已签到' : ''}
      </span>
      {!t.checked && t.is_active ? (
        <Chip
          onClick={() =>
            coinsApi
              .checkin()
              .then(() => coinsApi.summary().then(setSummary))
              .catch((e) => toastErr(e?.message || '签到失败'))
          }
        >
          点一下签到
        </Chip>
      ) : null}
    </div>
  )
}
