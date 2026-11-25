import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { cx, Ic, useMedia, Progress } from './lib'
import { ChevronLeft, ChevronRight, Layers, X } from '../v3/icons'
import './immersive.css'

/**
 * 沉浸式全屏布局壳：无侧边栏，顶部极简条，左右可收起的 rail，主区滚动。
 * 移动端 rail 变抽屉（带遮罩）。所有内容作用域在 .immersive。
 *
 * props:
 *  title / subtitle        顶栏标题
 *  subject                 科目 chip 文本
 *  onBack / backTo         返回（backTo 为路径时用 navigate）
 *  progress (0-100)        顶栏进度条
 *  progressLabel
 *  left / leftTitle        左栏内容与标题（可选）
 *  right / rightTitle      右栏内容与标题（可选）
 *  leftIcon / rightIcon    顶栏切换按钮图标
 *  actions                 顶栏右侧操作区
 *  hideChrome              完全隐藏顶栏（极少用）
 */
export default function ImmersiveLayout({
  title, subtitle, subject,
  onBack, backTo = -1,
  progress, progressLabel,
  left, leftTitle = '目录', leftWidth = 264,
  right, rightTitle = '详情', rightWidth = 300,
  leftIcon = Layers, rightIcon,
  actions, children, hideChrome = false,
  defaultLeftOpen, defaultRightOpen = false,
}) {
  const navigate = useNavigate()
  const isMobile = useMedia('(max-width: 960px)')
  const [leftOpen, setLeftOpen] = useState(defaultLeftOpen ?? (!isMobile && !!left))
  const [rightOpen, setRightOpen] = useState(defaultRightOpen ?? (!isMobile && !!right))

  // 切到移动端时自动收起侧栏，避免挡住内容
  useEffect(() => {
    if (isMobile) { setLeftOpen(false); setRightOpen(false) }
  }, [isMobile])

  const handleBack = () => {
    if (typeof onBack === 'function') { onBack(); return }
    if (typeof backTo === 'number') { navigate(backTo); return }
    navigate(backTo)
  }

  return (
    <div className="immersive">
      {!hideChrome && (
        <header className="im-topbar">
          <div className="im-topbar__left">
            <button className="im-iconbtn" onClick={handleBack} aria-label="返回" title="返回">
              <Ic of={ChevronLeft} size={20} />
            </button>
            <div className="im-topbar__title">
              <b>{title}</b>
              {subtitle && <span>{subtitle}</span>}
            </div>
            {subject && (
              <span className="im-chip im-chip--accent" style={{ marginLeft: 4 }}>{subject}</span>
            )}
          </div>

          {typeof progress === 'number' && (
            <div className="im-topbar__progress" title={progressLabel}>
              <Progress value={progress} />
            </div>
          )}

          <div className="im-topbar__spacer" />

          {left && (
            <button
              className={cx('im-btn', 'im-btn--sm', leftOpen && 'im-btn--primary')}
              onClick={() => setLeftOpen(v => !v)}
              aria-pressed={leftOpen}
            >
              <Ic of={leftIcon} size={15} /> {leftTitle}
            </button>
          )}
          {right && (
            <button
              className={cx('im-btn', 'im-btn--sm', rightOpen && 'im-btn--primary')}
              onClick={() => setRightOpen(v => !v)}
              aria-pressed={rightOpen}
            >
              {rightIcon ? <Ic of={rightIcon} size={15} /> : <Ic of={ChevronRight} size={15} />} {rightTitle}
            </button>
          )}
          {actions}
          <button className="im-iconbtn" onClick={handleBack} aria-label="关闭全屏" title="关闭全屏" style={{ marginLeft: 2 }}>
            <Ic of={X} size={19} />
          </button>
        </header>
      )}

      <div className="im-body">
        {left && (
          <>
            <aside
              className={cx('im-rail', 'im-rail--left', !leftOpen && 'is-collapsed')}
              style={{ width: leftWidth }}
            >
              <div className="im-rail__head">
                <span>{leftTitle}</span>
                {isMobile && (
                  <button className="im-iconbtn" style={{ width: 26, height: 26 }} onClick={() => setLeftOpen(false)} aria-label="关闭目录">
                    <Ic of={X} size={15} />
                  </button>
                )}
              </div>
              <div className="im-rail__body">{left}</div>
            </aside>
            {isMobile && leftOpen && <div className="im-rail__scrim" onClick={() => setLeftOpen(false)} />}
          </>
        )}

        <main className="im-main im-anim">{children}</main>

        {right && (
          <>
            <aside
              className={cx('im-rail', 'im-rail--right', !rightOpen && 'is-collapsed')}
              style={{ width: rightWidth }}
            >
              <div className="im-rail__head">
                <span>{rightTitle}</span>
                {isMobile && (
                  <button className="im-iconbtn" style={{ width: 26, height: 26 }} onClick={() => setRightOpen(false)} aria-label="关闭详情">
                    <Ic of={X} size={15} />
                  </button>
                )}
              </div>
              <div className="im-rail__body">{right}</div>
            </aside>
            {isMobile && rightOpen && <div className="im-rail__scrim" onClick={() => setRightOpen(false)} />}
          </>
        )}
      </div>
    </div>
  )
}
