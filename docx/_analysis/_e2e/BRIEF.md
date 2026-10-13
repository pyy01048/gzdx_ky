# 考研学习平台前端 · 真实浏览器走查简报（共享）

## 目标
对考研学习平台前端做**真实浏览器走查**，找出用户实际会遇到的问题。这是质量验收，不是代码审查。
**严禁修改任何项目代码**（`D:\平台\frontend` 下任何文件都不要改）。只在 `D:\平台\docx\_analysis\_e2e\` 下新建你自己的脚本。

## 环境（都已就绪，直接可用）
- 后端 API：`http://127.0.0.1:8000`（245 条路由，OpenAPI：`http://127.0.0.1:8000/openapi.json`）
- 前端 dev server：`http://127.0.0.1:5173`（**已在运行，不要重启、不要 npm install**；哈希路由如 `http://127.0.0.1:5173/#/library`）
- 真库：`D:\平台\database\kaoyan.db`

## 现成脚手架（直接 import，别自己重写浏览器启动逻辑）
文件：`D:\平台\docx\_analysis\_e2e\harness.mjs`

```js
import { launch, openPage, shot, api, dump } from './harness.mjs'
// launch(): 启动 headless chromium，已带 --no-proxy-server（本机 http_proxy 会干扰，务必用它）
// openPage(browser, '/xxx', { waitMs: 3000 }) → { page, consoleMsgs, pageErrors, failedReqs, apiCalls, state, navErr, url }
//   - state.head 是页面可见文本前 400 字，state.rootLen 是渲染文本长度（0/极小 = 白屏）
//   - consoleMsgs 收集 console 的 error/warning
//   - pageErrors 收集未捕获异常；failedReqs 收集失败请求；apiCalls 收集所有 /api/ 请求及状态码
// shot(page, 'name.png', { fullPage: true }) → 截图存到 D:\平台\docx\_analysis\e2e-shots\
// api('/api/xxx') → 直接调后端接口，返回 {status, json, text}（用于交叉验证页面数据真假）
// dump(obj) → 格式化 JSON
```

脚本写到 `D:\平台\docx\_analysis\_e2e\<你的模块名>.mjs`，用 `node <你的模块名>.mjs` 运行（工作目录切到 `_e2e`）。
截图命名：`e2e-shots/<模块名>-01.png` 等，中文文件名可以，但建议用英文/拼音前缀避免乱码。

## 每个页面必须回答
1. 页面能正常渲染吗？（有无白屏、ErrorBoundary 报错、加载卡住）
2. 浏览器控制台有无 **error**？（把真实报错原文贴出来，不要只写"有报错"）
3. 页面上的数据是真的吗？（用 `api()` 调后端接口，与页面显示的数字/条目核对）
4. **核心交互能用吗？**（见下方各模块重点）—— 必须真的点，不能只看渲染
5. 有没有明显设计/交互缺陷（文字溢出、布局错乱、点击无反应、加载不出来、按钮点了没反馈）

## 证据要求（硬性）
- 每条结论必须有证据：截图路径 或 接口响应原文 或 控制台报错原文。
- **没验证的就写"未验证"，禁止臆测**。
- 严重程度分级：**致命**（功能不可用）/ **严重**（数据错误/接口 500）/ **一般**（体验问题）/ **轻微**（美观）。
- 每条问题给：严重程度 + 页面 + 复现步骤 + 实际现象（带证据）+ 期望表现 + 初步根因（前端/后端/数据）。
- 交互类问题要贴出你点击的元素文本/选择器，以及点击后 DOM 是否能观察到变化。

## 输出
1. 把原始证据写到 `D:\平台\docx\_analysis\_e2e\<模块名>-report.md`（含上述问题列表 + 证据）。
2. **回给我（team lead）一份简短总结**：模块名、是否可用、问题数量（按严重程度分）、TOP 3 最严重问题（一句话 + 证据路径）。不要贴大段原文。

## 常见坑
- 本机设了 `http_proxy=http://127.0.0.1:55844`：curl 访问本机端口会被代理搞坏。测本机端口用 `curl --noproxy '*'`，或直接用 `api()`（node fetch 不走环境代理）。
- 页面是懒加载 + `hydrate()` 拉数据，渲染后要等 2–4 秒再采集；等不到的要用 `waitFor` 记录超时。
- dev server 是受管后台任务，长时间不访问可能冷启动，首次导航给足超时。
