import React, { useEffect, useState } from 'react'
import { systemApi } from '../api/client'

/**
 * 手机访问卡片：把电脑当服务器时，让用户一眼看到该用哪个地址、
 * 并直接扫码在手机上打开。
 *
 * 后端 /api/access-info 会算出局域网 IP、二维码、以及"为什么连不上"的排查提示。
 */
export default function LanAccessCard() {
  const [info, setInfo] = useState(null)
  const [status, setStatus] = useState('loading')
  const [isPhone, setIsPhone] = useState(false)

  const load = () => {
    setStatus('loading')
    systemApi.accessInfo()
      .then((d) => { setInfo(d); setStatus('ok') })
      .catch(() => setStatus('error'))
  }

  useEffect(() => {
    setIsPhone(/Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent))
    load()
  }, [])

  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text)
      setInfo((s) => ({ ...s, _copied: text }))
      setTimeout(() => setInfo((s) => ({ ...s, _copied: '' })), 1800)
    } catch {
      // 剪贴板不可用（非 HTTPS 的局域网访问常见）：提示手输
      setInfo((s) => ({ ...s, _copied: 'FAIL' }))
      setTimeout(() => setInfo((s) => ({ ...s, _copied: '' })), 1800)
    }
  }

  if (status === 'loading') {
    return <section className="card"><div className="card-body"><div className="loading-inline">读取网络信息…</div></div></section>
  }
  if (status === 'error' || !info) {
    return (
      <section className="card">
        <div className="card-head"><div><div className="card-title">手机访问</div></div></div>
        <div className="card-body">
          <div className="empty-hint">读取失败，请确认后端已启动。</div>
          <button className="btn ghost" onClick={load}>重试</button>
        </div>
      </section>
    )
  }

  const lanReady = info.exposed && info.lan_url

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <div className="card-title">手机 / 平板访问</div>
          <div className="card-sub">
            把电脑当服务器，手机连同一 WiFi 即可打开，用来整理错题、拍照 OCR
          </div>
        </div>
      </div>
      <div className="card-body">
        <div className="lan-grid">
          <div className="lan-info">
            <div className="lan-row">
              <span className="lan-label">本机</span>
              <code className="lan-url">{info.local_url}</code>
              <button className="btn-xs" onClick={() => copy(info.local_url)}>复制</button>
            </div>

            <div className="lan-row">
              <span className="lan-label">局域网</span>
              {lanReady
                ? <code className="lan-url strong">{info.lan_url}</code>
                : <span className="lan-url muted">未开放（HOST={info.host}）</span>}
              {lanReady && <button className="btn-xs" onClick={() => copy(info.lan_url)}>复制</button>}
            </div>

            <div className="lan-row">
              <span className="lan-label">访问密码</span>
              <span className={`kb-pill ${info.auth_enabled ? 'ok' : 'mid'}`}>
                {info.auth_enabled ? '已开启' : '未设置'}
              </span>
            </div>

            {info.all_ips && info.all_ips.length > 1 && (
              <div className="lan-multi">
                <div className="lan-label">多网卡，上面的不通可试：</div>
                {info.all_ips.map((it) => (
                  <div key={it.ip} className="lan-row">
                    <code className="lan-url">{`http://${it.ip}:${info.port}`}</code>
                    <span className="lan-src">{it.source}</span>
                  </div>
                ))}
              </div>
            )}

            {info._copied && (
              <div className="lan-copied">
                {info._copied === 'FAIL' ? '复制失败，请手动输入地址' : '已复制到剪贴板'}
              </div>
            )}
          </div>

          <div className="lan-qr">
            {info.qr_svg ? (
              <>
                <img src={info.qr_svg} alt="手机访问二维码" width="150" height="150" />
                <div className="lan-qr-hint">手机扫码直接打开</div>
              </>
            ) : (
              <div className="lan-qr-empty">
                {lanReady ? '二维码不可用' : '开放局域网访问后显示二维码'}
              </div>
            )}
          </div>
        </div>

        {isPhone && (
          <div className="lan-note ok">
            📱 你正在手机上访问本平台，可以直接用「错题本 → 拍照收录」整理错题。
          </div>
        )}

        {info.tips && info.tips.length > 0 && (
          <details className="lan-tips">
            <summary>连不上？点这里看排查提示（{info.tips.length} 条）</summary>
            <ul>
              {info.tips.map((t, i) => (
                <li key={i}>{t.replace(/\*\*/g, '')}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </section>
  )
}
