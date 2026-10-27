import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App'
import './styles/global.css'
import './styles/v2-design.css'
import './styles/kbimport.css'
import './styles/polish.css'
/* 设计令牌：单一事实来源（src/design/design-tokens.json）。
   2026-10 迁移收尾已完成：
     · global.css 的旧 :root / [data-theme='dark'] 变量块已删除（190 行）
     · 全项目 1871 处旧变量引用已替换为新令牌名
     · tokens.css 末尾的「旧变量兼容桥」已删除
   现全站颜色/间距/圆角/动效均由此文件唯一定义，改令牌改 design-tokens.json。 */
import './styles/tokens.css'
/* Aurora v3（2026-10-21 全站视觉重写）：仅新增 --v3-* 命名空间与 .v3-* 组件，
   与旧样式并行存在，旧页面迁完一批即可删一批旧 CSS。 */
import './v3/styles/tokens.css'
import './v3/styles/base.css'
import './v3/styles/motion.css'
import './v3/styles/components.css'
import './v3/styles/shell.css'
import './v3/styles/pages.css'
import './v3/styles/assistant.css'
import './v3/styles/documents.css'
import './v3/styles/legacy-bridge.css'
/* 顶部导航样式 src/styles/nav.css 暂不在此处全局引入：
   其中的 .main-area / .breadcrumb 会覆盖 global.css 的现有规则，
   而当前 Layout 仍是侧边栏版式，全局引入会立刻改变线上观感。
   等 Layout 改造为顶栏时，由 Layout.jsx 局部 import './styles/nav.css'。 */

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>
)
