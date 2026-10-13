/**
 * 全局错误边界组件 V3.1
 * 捕获子组件的渲染错误，显示友好的错误页面，防止整个应用白屏。
 *
 * V3.1 变更（白屏整改）：
 *   ① 新增「重试」按钮 —— 只重置边界状态并强制重挂子树，不做整页 reload，
 *      保留 SPA 路由与 store 上下文，比 window.location.reload 更轻；
 *   ② 新增「返回首页」按钮 —— 直接写 location.hash，不依赖 Router 上下文
 *      （若崩溃源就是 Router 自身，useNavigate 同样不可用，hash 永远跳得出去）；
 *   ③ 重试计数 >= 2 时提示转人工，避免用户在必然复现的崩溃上反复点击。
 *
 * 使用方式：
 * <ErrorBoundary>
 *   <App />
 * </ErrorBoundary>
 */
import React from 'react'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      retries: 0,
    }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary] 组件渲染错误:', error, errorInfo)
    this.setState({ errorInfo })
  }

  /* 重试：重置边界状态 + 递增 retries。
     retries 同时作为子树的 remount key —— 崩溃时子组件的内部 state 可能已损坏，
     仅把 hasError 置 false 只会原样再崩一次；换 key 强制重挂才是有效重试。 */
  handleRetry = () => {
    this.setState((s) => ({
      hasError: false,
      error: null,
      errorInfo: null,
      retries: s.retries + 1,
    }))
  }

  /* 返回首页：直接写 hash。错误边界挂在 Router 内层，若崩溃源就是 Router 本身，
     useNavigate 同样不可用；hash 写入不依赖任何 React 上下文，永远跳得出去。 */
  handleHome = () => {
    window.location.hash = '#/'
  }

  handleReload = () => {
    window.location.reload()
  }

  handleCopyError = () => {
    const errorText = `错误信息: ${this.state.error?.message}\n组件栈: ${this.state.errorInfo?.componentStack}`
    navigator.clipboard?.writeText(errorText).then(() => {
      alert('错误信息已复制到剪贴板')
    }).catch(() => {
      // 降级方案
      const textarea = document.createElement('textarea')
      textarea.value = errorText
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      alert('错误信息已复制到剪贴板')
    })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <div className="error-boundary-content">
            <div className="error-boundary-icon">⚠️</div>
            <h2 className="error-boundary-title">页面出了点问题</h2>
            <p className="error-boundary-desc">
              很抱歉，页面在渲染时遇到了错误。您可以尝试重试或返回首页，也可以复制错误信息反馈给开发者。
            </p>
            {this.state.retries >= 2 && (
              <p className="error-boundary-desc">
                已重试 {this.state.retries} 次仍未恢复，建议返回首页或刷新页面；若反复出现，请复制错误信息反馈。
              </p>
            )}
            {this.state.error && (
              <div className="error-boundary-detail">
                <strong>错误信息：</strong>
                <code>{this.state.error.message}</code>
              </div>
            )}
            <div className="error-boundary-actions">
              <button className="btn primary" onClick={this.handleRetry}>
                重试
              </button>
              <button className="btn" onClick={this.handleHome}>
                返回首页
              </button>
              <button className="btn" onClick={this.handleReload}>
                刷新页面
              </button>
              <button className="btn" onClick={this.handleCopyError}>
                复制错误信息
              </button>
            </div>
          </div>
        </div>
      )
    }

    // retries 变化时换 key 强制重挂子树，让「重试」真正重新初始化子组件
    return (
      <React.Fragment key={this.state.retries}>
        {this.props.children}
      </React.Fragment>
    )
  }
}

export default ErrorBoundary
