/**
 * 界面自定义：侧边导航分组 / 「其他」入口 / 仪表盘区块 / 统计卡 / 全部模块
 * 的显隐与排序。偏好只存本机浏览器（见 hooks/useUiLayout.js 的取舍说明）。
 */
import React from 'react'
import {
  useUiLayout, toggleHidden, moveInOrder, resetUiLayout,
  DASH_SECTIONS, STAT_CARDS,
} from '../hooks/useUiLayout'
import { NAV_MODULES, NAV_OTHER } from '../components/Layout'
import { MODULES } from '../pages/Dashboard'
import { toast } from './UI'

/** 一个可配置列表：ids 决定支持隐藏/排序的项，orderKey 为空表示只隐藏不排序 */
function Group({ title, sub, items, idOf, labelOf, layout, hiddenKey, orderKey }) {
  const hiddenSet = layout[hiddenKey] || []
  const order = layout[orderKey] || []
  const ordered = order.length
    ? [...items].sort((a, b) => {
      const ia = order.indexOf(idOf(a)); const ib = order.indexOf(idOf(b))
      return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib)
    })
    : items
  const allIds = items.map(idOf)
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title">{title}</div>
          {sub && <div className="card-sub">{sub}</div>}
        </div>
        <span className="badge neutral">已隐藏 {hiddenSet.length}</span>
      </div>
      <div>
        {ordered.map((it) => {
          const id = idOf(it)
          const off = hiddenSet.includes(id)
          return (
            <div key={id} className="row" style={{ justifyContent: 'space-between', padding: '4px 0' }}>
              <label className="row" style={{ gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={!off}
                  onChange={() => toggleHidden(hiddenKey, id)}
                  aria-label={`${labelOf(it)} 显示`}
                />
                <span style={{ opacity: off ? 0.45 : 1 }}>{labelOf(it)}</span>
              </label>
              {orderKey && (
                <span className="row" style={{ gap: 4 }}>
                  <button
                    className="btn ghost sm"
                    onClick={() => moveInOrder(orderKey, id, 'up', allIds)}
                    aria-label={`${labelOf(it)} 上移`}
                  >↑</button>
                  <button
                    className="btn ghost sm"
                    onClick={() => moveInOrder(orderKey, id, 'down', allIds)}
                    aria-label={`${labelOf(it)} 下移`}
                  >↓</button>
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function UiCustomize() {
  const layout = useUiLayout()
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="card-title">界面自定义</div>
          <div className="card-sub">
            勾选显示/隐藏，↑↓ 调整顺序；偏好仅保存在本机浏览器，不影响其他设备
          </div>
        </div>
        <button
          className="btn outline"
          onClick={() => { resetUiLayout(); toast('界面布局已恢复默认') }}
        >恢复默认布局</button>
      </div>

      <div className="stack">
        <Group
          title="侧边导航分组" sub="隐藏的分组不再出现在侧边栏；页面本身仍可通过 Ctrl+K 或直达链接进入"
          items={NAV_MODULES} idOf={(m) => m.key} labelOf={(m) => m.title}
          layout={layout} hiddenKey="navHidden" orderKey="navOrder"
        />
        <Group
          title="侧边「其他」入口" sub="这一组只支持隐藏（顺序固定）"
          items={NAV_OTHER} idOf={(n) => n.to} labelOf={(n) => n.label}
          layout={layout} hiddenKey="otherHidden" orderKey=""
        />
        <Group
          title="仪表盘区块" sub="这一组只支持隐藏（版面成对排布，顺序固定）"
          items={DASH_SECTIONS} idOf={(s) => s.id} labelOf={(s) => s.label}
          layout={layout} hiddenKey="dashHidden" orderKey=""
        />
        <Group
          title="仪表盘统计卡" items={STAT_CARDS}
          idOf={(c) => c.id} labelOf={(c) => c.label}
          layout={layout} hiddenKey="statsHidden" orderKey="statsOrder"
        />
        <Group
          title="仪表盘「全部模块」入口"
          items={MODULES} idOf={(m) => m.id} labelOf={(m) => m.label}
          layout={layout} hiddenKey="modsHidden" orderKey="modsOrder"
        />
      </div>
    </section>
  )
}
