import React, { lazy, Suspense, useEffect } from 'react'
import { Routes, Route, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import useStore from './store/useStore'
import { useTheme } from './components/UI'
import { Segmented } from './v3/ui'
import { LoadingState } from './v3/ui'
import { hydrate } from './api/sync'
import { AuthProvider, RequireAuth, RequireAdmin, useAuth } from './auth/AuthContext'
import AppShellV3, { AdminLayout } from './v3/shell'
import { ADMIN_LEGACY_REDIRECTS, KAOYAN_TABS } from './nav/navConfig'

/* 路由级代码分割：按页面懒加载，减小首屏主包体积 */
const Dashboard = lazy(() => import('./v3/pages/Dashboard'))
// 今日聚合中枢：跨模块动态聚合 + 行动航线（数据层见 api/hub.js）
const Hub = lazy(() => import('./v3/pages/Hub'))
const Tasks = lazy(() => import('./v3/pages/Tasks'))
const KbMap = lazy(() => import('./v3/pages/KbMap'))
const KnowledgeArticle = lazy(() => import('./v3/pages/KnowledgeArticle'))
const Library = lazy(() => import('./v3/pages/Library'))
const Notebook = lazy(() => import('./v3/pages/Notebook'))
const Assistant = lazy(() => import('./v3/pages/Assistant'))
const Pan = lazy(() => import('./v3/pages/Pan'))
const Words = lazy(() => import('./v3/pages/Words'))
const Cards = lazy(() => import('./v3/pages/Cards'))
const Settings = lazy(() => import('./v3/pages/Settings'))
const CodeBank = lazy(() => import('./v3/pages/CodeBank'))
const Quiz = lazy(() => import('./v3/pages/Quiz'))
const QuizBank = lazy(() => import('./v3/pages/QuizBank'))
const LearnerProfile = lazy(() => import('./v3/pages/LearnerProfile'))
const SubjectManager = lazy(() => import('./v3/pages/SubjectManager'))
const UserAdmin = lazy(() => import('./v3/pages/UserAdmin'))
const Documents = lazy(() => import('./v3/pages/Documents'))
const KnowledgeBaseImport = lazy(() => import('./v3/pages/KnowledgeBaseImport'))
const ModelTraining = lazy(() => import('./v3/pages/ModelTraining'))
const Planner = lazy(() => import('./v3/pages/Planner'))
const KaoyanGuide = lazy(() => import('./v3/pages/KaoyanGuide'))
const KaoyanSchools = lazy(() => import('./v3/pages/KaoyanSchools'))
const NoticeCenter = lazy(() => import('./v3/pages/NoticeCenter'))
const KaoyanSchoolDetail = lazy(() => import('./v3/pages/KaoyanSchoolDetail'))
const KaoyanCompare = lazy(() => import('./v3/pages/KaoyanCompare'))
const KaoyanAnalysis = lazy(() => import('./v3/pages/KaoyanAnalysis'))
const KaoyanRecommend = lazy(() => import('./v3/pages/KaoyanRecommend'))
const KaoyanImport = lazy(() => import('./v3/pages/KaoyanImport'))
const KaoyanMap = lazy(() => import('./v3/pages/KaoyanMap'))
const KaoyanScatter = lazy(() => import('./v3/pages/KaoyanScatter'))
const KaoyanAssistant = lazy(() => import('./v3/pages/KaoyanAssistant'))
const PlanPage = lazy(() => import('./v3/pages/PlanPage'))
const GrowthPage = lazy(() => import('./v3/pages/GrowthPage'))
const ErrorReview = lazy(() => import('./v3/pages/ErrorReview'))
const QualityDashboard = lazy(() => import('./v3/pages/QualityDashboard'))
const Insights = lazy(() => import('./v3/pages/Insights'))
// S7：全站收藏夹 + 学习轨迹
const Favorites = lazy(() => import('./v3/pages/Favorites'))
const LearningTimeline = lazy(() => import('./v3/pages/LearningTimeline'))
// 数据中心：逐域接口体检（数据页为什么是空的，在这里能直接看到）
const DataCenter = lazy(() => import('./v3/pages/DataCenter'))
// 院校采集源：选择哪些院校参与采集 / 数据源目录（管理工作台入口）
const KaoyanCrawlSources = lazy(() => import('./v3/pages/KaoyanCrawlSources'))
// 真题中心：独立索引页（按年份/套卷），点入后复用 Quiz 的深链练习
const ExamCenter = lazy(() => import('./v3/pages/ExamCenter'))
// 模考中心：蓝图 → 发起 → 答题 → 交卷 → 报告（P0-3）
const ExamMock = lazy(() => import('./v3/pages/ExamMock'))
const Login = lazy(() => import('./v3/pages/Login'))
const ForceChangePassword = lazy(() => import('./v3/pages/ForceChangePassword'))
const Forbidden = lazy(() => import('./v3/pages/Forbidden'))
// Glass Lab：毛玻璃交互式页面（后端零依赖的纯前端动效演示页）
const GlassLab = lazy(() => import('./v3/pages/GlassLab'))

function PageFallback() {
  return <LoadingState text="页面加载中…" />
}

/* 改版前的管理页路径 → /admin/*，带上查询串，旧书签与外链不丢参数 */
function LegacyRedirect({ to }) {
  const { search, hash } = useLocation()
  return <Navigate to={`${to}${search}${hash}`} replace />
}

// D7: 考研择校模块分组布局（嵌套路由 + 各页面懒加载）
// 择校模块内 Tab 导航（复用 Segmented/.seg，零新增样式），Tab 清单由 navConfig 派生，与顶栏下拉同源
const Textbooks = lazy(() => import('./v3/pages/Textbooks'))
const KaoyanModuleLayout = () => {
  const location = useLocation()
  const navigate = useNavigate()
  /* 当前 tab：取「最长前缀匹配」，避免模块主页 /kaoyan 吞掉 /kaoyan/schools/:id 等子路由。
     管理类页面（原 /kaoyan/import）已归口 /admin，不再占用择校 Tab；
     匹配不到时不强行高亮「择校中心」，避免当前位置误导。 */
  const currentTab = KAOYAN_TABS
    .filter((t) => location.pathname === t.value || location.pathname.startsWith(t.value + '/'))
    .sort((a, b) => b.value.length - a.value.length)[0]?.value || ''
  return (
    <div>
      {/* dogfood ISSUE-007：11 个 tab 在窄屏下曾被压缩成逐字竖排；
          超宽时整条横向滚动，按钮永不收缩换行（样式见 global.css .seg-scroll）。 */}
      <div className="seg-scroll">
        <Segmented options={KAOYAN_TABS} value={currentTab} onChange={(v) => navigate(v)} />
      </div>
      <Outlet />
    </div>
  )
}

/* 登录后的应用壳：只有通过 RequireAuth 才挂载，hydrate 因此总带着有效会话；
   换账号重新登录时壳重新挂载，数据随之重新拉取。 */
function AppShell() {
  const { status } = useAuth()
  useEffect(() => {
    /* 访客（公开壳）不回填个人数据域——那些接口全部需要登录，
       未登录时打过去只会收集一屏 401；登录后 status 变 ready 再拉取。 */
    if (status === 'ready') hydrate()
  }, [status])
  return (
    <AppShellV3>
      <Suspense fallback={<PageFallback />}>
        <Outlet />
      </Suspense>
    </AppShellV3>
  )
}

/* 管理后台：沿用同一套 Aurora v3 外壳，子导航由 v3 AdminLayout 渲染 */
function AdminShell() {
  return (
    <AdminLayout>
      <Suspense fallback={<PageFallback />}>
        <Outlet />
      </Suspense>
    </AdminLayout>
  )
}

/* 访客落地：未登录访问 / 直达「院校库」（信息量最大的公开页）；登录用户照常看仪表盘 */
function GuestHome() {
  const { user, status } = useAuth()
  if (status === 'loading') return <PageFallback />
  if (!user) return <Navigate to="/kaoyan" replace />
  return <Dashboard />
}

export default function App() {
  const theme = useStore((s) => s.settings.theme)
  // V7.0 P0-1：主题写入收敛到 useResolvedTheme（内部委托自 useTheme），全应用仅此一处订阅
  useTheme(theme)

  return (
    <ErrorBoundary>
    <AuthProvider>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/force-change-password" element={<ForceChangePassword />} />
          {/* ── 公开壳（2026-10-19 访客模式）：未登录可浏览共享数据 ──
              院校库/通知/教材/知识图谱/真题索引对访客只读开放（后端 access_policy 白名单），
              顶栏右上角提供「登录」；个人数据页仍在下方 <RequireAuth> 壳内，
              访客直达会被礼貌地送去登录，登录后回到原页。 */}
          <Route element={<AppShell />}>
            <Route path="/403" element={<Forbidden />} />
            <Route path="/glass" element={<GlassLab />} />
            {/* 数据质量旧书签兼容：早期侧栏入口用过 /data-quality */}
            <Route path="/data-quality" element={<Navigate to="/admin/quality" replace />} />
            <Route path="/" element={<GuestHome />} />
            <Route path="/textbooks" element={<Textbooks />} />
            <Route path="/knowledge" element={<KbMap />} />
            <Route path="/knowledge/:id" element={<KnowledgeArticle />} />
            <Route path="/exam" element={<ExamCenter />} />
            <Route path="/kaoyan" element={<KaoyanModuleLayout />}>
              <Route index element={<KaoyanSchools />} />
              <Route path="guide" element={<KaoyanGuide />} />
              <Route path="notices" element={<NoticeCenter />} />
              <Route path="schools" element={<KaoyanSchools />} />
              <Route path="schools/:id" element={<KaoyanSchoolDetail />} />
              <Route path="compare" element={<KaoyanCompare />} />
              <Route path="analysis" element={<KaoyanAnalysis />} />
              <Route path="map" element={<KaoyanMap />} />
              <Route path="scatter" element={<KaoyanScatter />} />
              <Route path="recommend" element={<KaoyanRecommend />} />
              {/* 个人数据：规划/成长/择校 AI 问答仍需登录 */}
              <Route path="plan" element={<RequireAuth><PlanPage /></RequireAuth>} />
              <Route path="growth" element={<RequireAuth><GrowthPage /></RequireAuth>} />
              <Route path="assistant" element={<RequireAuth><KaoyanAssistant /></RequireAuth>} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
          <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          {/* 「/」已由公开壳的 GuestHome 承接：访客→院校库，登录用户→仪表盘 */}
          {/* 今日中枢：私域数据聚合页，访客无个人数据可聚合，故放在登录壳内 */}
          <Route path="/hub" element={<Hub />} />
          <Route path="/tasks" element={<Tasks />} />
          {/* 知识图谱：KbMap 为唯一主体。
              原「知识点全景」(/panorama) 与知识地图数据源完全相同（同 taxonomyApi.subjects/tree/coverage，
              同为 1067 知识点），且其唯一独有的「结构化覆盖概览」已是 KbMap「结构化覆盖体检」的子集
              （KbMap 多出分块列与扫描件统计）→ 判定 100% 冗余，下线并重定向（docx/25 §D）。
              组件与路由一并废除，保留旧路径重定向避免历史书签 404。 */}
          {/* 教材目录 / 知识图谱（含阅读页）：已迁公开壳，访客可浏览 */}
          <Route path="/panorama" element={<Navigate to="/knowledge" replace />} />
          <Route path="/kbmap" element={<Navigate to="/knowledge" replace />} />
          {/* 学习统计：科目正确率 / 近7天趋势 / 错题标签 / 学习时长（聚合自 /api/stats/overview） */}
          <Route path="/insights" element={<Insights />} />
          {/* 学习文库：IMA 知识库资料按 初试/复试 + 科目 + 知识/试题/单词 浏览 */}
          <Route path="/library" element={<Library />} />
          <Route path="/quiz" element={<Quiz />} />
          {/* 模考中心：独立于 /exam 真题索引，个人模考数据放在登录壳内 */}
          <Route path="/exam-mock" element={<ExamMock />} />
          {/* 真题练习深链：做题会写个人答题记录，仍在登录壳内；索引页 /exam 已迁公开壳 */}
          {/* 静态前缀必须先于动态参数路由声明，避免 /exam/year/2024 被当成 year=year&paper=2024 */}
          <Route path="/exam/year/:year" element={<Quiz />} />
          <Route path="/exam/paper/:paper" element={<Quiz />} />
          <Route path="/exam/:year/:paper" element={<Quiz />} />
          <Route path="/exam/:year/:paper/:qno" element={<Quiz />} />
          {/* 冗余页清理（docx/22 D3/D4 + docx/25 §D/E）：
              旧 /exam-frequency、/analysis 只保留重定向，避免历史书签 404。 */}
          <Route path="/exam-frequency" element={<Navigate to="/knowledge" replace />} />
          <Route path="/analysis" element={<Navigate to="/" replace />} />
          {/* /subjects、/profile 曾经整段失效：上面那条「冗余页清理」注释一直没闭合，
              吞掉了这四行路由，直到下一段注释结束才恢复。于是 Layout 标题写着
              「科目管理」「学习画像」，点进去却被兜底路由弹回首页。
              /subjects 更早是重定向到 /settings?tab=subjects，但 Settings 不读 tab 参数，
              且只有「备考科目勾选」，没有 SubjectManager 的章节/题型 CRUD。 */}
          <Route path="/profile" element={<LearnerProfile />} />
          {/* 错题复盘：错因分布 / 薄弱知识点 / 单题 AI 归因与知识点挂接（5+1 的第 5 个模块主页） */}
          <Route path="/error-review" element={<ErrorReview />} />
          {/* 旧入口兼容：/errors 与 /cuoti 早期用过，重定向到新页，避免历史链接失效 */}
          <Route path="/errors" element={<Navigate to="/error-review" replace />} />
          <Route path="/cuoti" element={<Navigate to="/error-review" replace />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/notebook" element={<Notebook />} />
          <Route path="/planner" element={<Planner />} />
          <Route path="/assistant" element={<Assistant />} />
          <Route path="/pan" element={<Pan />} />
          <Route path="/words" element={<Words />} />
          <Route path="/cards" element={<Cards />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/codebank" element={<CodeBank />} />
          {/* S7：收藏夹与学习轨迹 */}
          <Route path="/favorites" element={<Favorites />} />
          <Route path="/timeline" element={<LearningTimeline />} />
          {/* 择校模块（/kaoyan）路由已整体迁至公开壳：访客可浏览院校库/通知/分析，
              plan/growth/assistant 三个个人页在公开壳内单独包 RequireAuth */}
          {/* 管理后台：一切 CRUD / 采集 / 训练 / 体检归口 /admin，非管理员手输 URL 落 403 页 */}
          <Route path="/admin" element={<RequireAdmin><AdminShell /></RequireAdmin>}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={<DataCenter />} />
            {/* 用户管理：账号 CRUD / 角色 / 禁用 / 重置密码（与设置页「账号与安全」同一组件） */}
            <Route path="users" element={<UserAdmin />} />
            <Route path="subjects" element={<SubjectManager />} />
            <Route path="quiz-bank" element={<QuizBank />} />
            {/* 评测与数据质量：eval_runs 历史 + 语料体检（数字全部来自库内聚合） */}
            <Route path="quality" element={<QualityDashboard />} />
            {/* 院校数据管理 = 采集中心（定向采集 / 国家线回填 / 公告采集 / 采集历史） */}
            <Route path="schools" element={<KaoyanImport />} />
            <Route path="crawl-sources" element={<KaoyanCrawlSources />} />
            <Route path="kb-import" element={<KnowledgeBaseImport />} />
            <Route path="model" element={<ModelTraining />} />
            <Route path="*" element={<Navigate to="overview" replace />} />
          </Route>
          {ADMIN_LEGACY_REDIRECTS.map(([from, to]) => (
            <Route key={from} path={from} element={<LegacyRedirect to={to} />} />
          ))}
          {/* 兜底 404 已移到公开壳：访客未知路径不再被弹去登录 */}
          </Route>
        </Routes>
      </Suspense>
    </AuthProvider>
  </ErrorBoundary>
  )
}
