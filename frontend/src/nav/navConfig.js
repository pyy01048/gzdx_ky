/* 全站唯一导航源：routeTree 单一事实源。
   顶栏下拉 / 移动端抽屉 / 面包屑 / 相关功能 / Ctrl+K 命令面板 / 设置页界面自定义
   全部从 routeTree 派生。新增页面只改这一处。 */
import { Home, Folder, Book, FileText, Target } from '../components/Icon'

/* 分组元数据（顺序 = 顶栏顺序） */
const GROUPS = [
  { key: 'today', title: '今日', icon: Home },
  { key: 'learn', title: '学习', icon: Folder },
  { key: 'practice', title: '练习', icon: Book },
  { key: 'review', title: '复盘', icon: FileText },
  { key: 'school', title: '择校', icon: Target },
]

/* routeTree 节点构造助手：title 从 h1 派生，减少重复 */
function node(label, h1, parent, group, opts = {}) {
  const hh = h1 || label
  return {
    label,
    h1: hh,
    title: opts.title || `${hh} · 硕途考研`,
    parent: parent ?? null,
    group: group || null,
    public: opts.public ?? false,
    roles: opts.roles ?? [],
    lazy: opts.lazy ?? null,
    kw: opts.kw ?? [],
    desc: opts.desc ?? '',
    exact: opts.exact ?? false,
    legacy: opts.legacy ?? null,
    redirect: opts.redirect ?? null,
    nav: opts.nav ?? false,
    children: [],
  }
}

/* routeTree: 全站唯一路由源。覆盖全部 85 路由 + 3 新路由（/alumni /contribute /admin/experiences）。
   parent 字段表达父子关系，children 由 parent 反向派生（构建时一次性计算）。
   lazy 字段是 dynamic import，构建时确定，无运行时副作用。 */
export const routeTree = {
  // ── 今日分组 ──
  '/': node('今日中枢', '今日中枢', null, 'today', { public: true, exact: true, nav: true, desc: '首页 · 跨模块聚合 · 先做什么', kw: ['hub', 'dashboard', '中枢', '今日', '首页', '主页', '聚合', '仪表盘', 'jinri', 'zhongshu', 'home', 'yibiaopan'], lazy: () => import('../v3/pages/Hub') }),
  '/hub': node('今日中枢', '今日中枢', '/', 'today', { public: true, desc: '今日中枢（与 / 同页）', kw: ['hub'], lazy: () => import('../v3/pages/Hub') }),
  '/tasks': node('任务打卡', null, '/', 'today', { nav: true, desc: '今日任务与打卡', kw: ['task', '任务', '待办', 'todo', 'renwu', 'daka'], lazy: () => import('../v3/pages/Tasks') }),
  '/planner': node('学习计划', null, '/', 'today', { nav: true, desc: '规划与连续打卡', kw: ['planner', '计划', '规划', 'jihua', 'plan'], lazy: () => import('../v3/pages/Planner') }),
  '/profile': node('学习画像', null, '/', 'today', { nav: true, desc: '学习数据与薄弱点', kw: ['profile', '画像', 'huaxiang'], lazy: () => import('../v3/pages/LearnerProfile') }),

  // ── 学习分组 ──
  '/library': node('知识库', null, null, 'learn', { public: true, nav: true, desc: '学习文库 · 文档知识库 · 资料与图谱', kw: ['library', 'knowledge', '文库', '知识库', '文档', '资料', 'wenku', 'ima', 'document'], lazy: () => import('../v3/pages/KnowledgeHome') }),
  '/textbooks': node('教材目录', null, null, 'learn', { public: true, nav: true, desc: '教材章节目录', kw: ['textbook', '教材', 'jiaocai', '目录'], lazy: () => import('../v3/pages/Textbooks') }),
  '/pan': node('网盘联动', null, null, 'learn', { nav: true, desc: '云盘与同步', kw: ['pan', '网盘', '云盘', 'wangpan', 'cloud'], lazy: () => import('../v3/pages/Pan') }),
  '/knowledge': node('知识图谱', '知识地图', null, 'learn', { public: true, nav: true, desc: '科目→章节→知识点纵览与掌握度', kw: ['knowledge', '知识图谱', '知识地图', '考点', 'zhishi', 'map', 'kbmap'], lazy: () => import('../v3/pages/KbMap') }),
  '/knowledge/:id': node('知识点详情', null, '/knowledge', 'learn', { public: true, lazy: () => import('../v3/pages/KnowledgeArticle') }),
  '/tools': node('复试工具箱', '学习工具箱', null, 'learn', { public: true, nav: true, desc: '代码上机 · 进制计算器 · 外部工具目录', kw: ['tools', '工具箱', '复试', '工具', '进制', '计算器', 'codebank', 'oj', 'gongju', 'binji', 'jisuanqi'], lazy: () => import('../v3/pages/Tools') }),

  // ── 练习分组 ──
  '/quiz': node('刷题中心', null, null, 'practice', { nav: true, desc: '题库与错题强化', kw: ['quiz', '刷题', 'shuati', 'test'], lazy: () => import('../v3/pages/Quiz') }),
  '/personal-question-bank': node('我的题库', null, null, 'practice', { nav: true, desc: '个人题库 · 自建题 · 掌握状态', kw: ['personal', 'question-bank', '我的题库', '个人题库', 'tiku'], lazy: () => import('../v3/pages/PersonalQuestionBank') }),
  '/exam': node('真题中心', null, null, 'practice', { public: true, nav: true, desc: '按年份/卷种做真题与整卷模考', kw: ['exam', '真题', 'zhenti', '模考', 'paper'], lazy: () => import('../v3/pages/ExamCenter') }),
  '/exam/year/:year': node('真题练习', null, '/exam', 'practice', { lazy: () => import('../v3/pages/Quiz') }),
  '/exam/paper/:paper': node('真题练习', null, '/exam', 'practice', { lazy: () => import('../v3/pages/Quiz') }),
  '/exam/:year/:paper': node('真题练习', null, '/exam', 'practice', { lazy: () => import('../v3/pages/Quiz') }),
  '/exam/:year/:paper/:qno': node('真题练习', null, '/exam', 'practice', { lazy: () => import('../v3/pages/Quiz') }),
  '/exam-mock': node('模考中心', null, null, 'practice', { desc: '蓝图 → 发起 → 答题 → 交卷 → 报告', kw: ['mock', '模考'], lazy: () => import('../v3/pages/ExamMock') }),
  '/cards': node('记忆卡片', null, null, 'practice', { nav: true, desc: 'Anki 式间隔复习', kw: ['card', '卡片', 'kapian', 'flash'], lazy: () => import('../v3/pages/Cards') }),
  '/words': node('单词记忆', null, null, 'practice', { nav: true, desc: '单词背诵与发音', kw: ['word', '单词', 'danci', 'vocab'], lazy: () => import('../v3/pages/Words') }),

  // ── 复盘分组 ──
  '/error-review': node('错题复盘', null, null, 'review', { nav: true, desc: '错因分布 · 薄弱知识点 · AI 归因分析', kw: ['error', 'review', '错题', '复盘', 'cuoti', 'fupan'], lazy: () => import('../v3/pages/ErrorReview') }),
  '/error-review/:id': node('错题详情', null, '/error-review', 'review', { lazy: () => import('../v3/pages/ErrorDetail') }),
  '/notebook': node('错题本', null, null, 'review', { nav: true, desc: '错题录入 · 间隔复习（拍照 OCR 收录）', kw: ['notebook', '错题本', 'cuoti', 'error'], lazy: () => import('../v3/pages/Notebook') }),
  '/insights': node('学习统计', null, null, 'review', { nav: true, desc: '答题量与正确率趋势', kw: ['insight', '统计', 'tongji', 'stats'], lazy: () => import('../v3/pages/Insights') }),
  '/favorites': node('我的收藏', null, null, 'review', { nav: true, desc: '收藏的题目与资料', kw: ['favorite', '收藏', 'shoucang', 'star'], lazy: () => import('../v3/pages/Favorites') }),
  '/timeline': node('学习轨迹', null, null, 'review', { nav: true, desc: '按时间回看学习记录', kw: ['timeline', '轨迹', 'guiji', 'history'], lazy: () => import('../v3/pages/LearningTimeline') }),

  // ── 择校分组 ──
  '/kaoyan': node('院校库', null, null, 'school', { public: true, exact: true, nav: true, desc: '全国院校 · 专业 · 通知', kw: ['kaoyan', '择校', 'zexiao', '院校', 'yuanxiao', 'schools'], lazy: () => import('../v3/pages/KaoyanSchools') }),
  '/kaoyan/guide': node('择校数据中心', null, '/kaoyan', 'school', { public: true, lazy: () => import('../v3/pages/KaoyanGuide') }),
  '/kaoyan/notices': node('通知中心', null, '/kaoyan', 'school', { public: true, nav: true, desc: '简章/复试/报名/初试 · 改考雷达', kw: ['notice', '通知', '公告', '简章', 'tongzhi', 'gonggao'], lazy: () => import('../v3/pages/NoticeCenter') }),
  '/kaoyan/schools': node('院校库', null, '/kaoyan', 'school', { public: true, lazy: () => import('../v3/pages/KaoyanSchools') }),
  '/kaoyan/schools/:id': node('院校详情', null, '/kaoyan/schools', 'school', { public: true, lazy: () => import('../v3/pages/KaoyanSchoolDetail') }),
  '/kaoyan/majors/:id': node('专业详情', null, '/kaoyan', 'school', { public: true, lazy: () => import('../v3/pages/KaoyanMajorDetail') }),
  '/kaoyan/compare': node('院校对比', null, '/kaoyan', 'school', { public: true, nav: true, desc: '同年分数与招生数据横向比较', kw: ['compare', '对比', 'duibi', '院校对比'], lazy: () => import('../v3/pages/KaoyanCompare') }),
  '/kaoyan/analysis': node('分数分析', null, '/kaoyan', 'school', { public: true, nav: true, desc: '近五年分数线与招生趋势', kw: ['analysis', '分析', '趋势', '分数线', 'fenxi', 'qushi'], lazy: () => import('../v3/pages/KaoyanAnalysis') }),
  '/kaoyan/map': node('区域热力', null, '/kaoyan', 'school', { public: true, nav: true, desc: '按省份比较院校与录取数据', kw: ['map', '地图', '热力', '省份', 'ditu', 'reli'], lazy: () => import('../v3/pages/KaoyanMap') }),
  '/kaoyan/scatter': node('招生分布', null, '/kaoyan', 'school', { public: true, nav: true, desc: '招生规模与录取均分散点', kw: ['scatter', '散点', '招生', 'sandi', 'zhaosheng'], lazy: () => import('../v3/pages/KaoyanScatter') }),
  '/kaoyan/recommend': node('择校推荐', null, '/kaoyan', 'school', { public: true, nav: true, desc: '按分数与目标筛选院校', kw: ['recommend', '推荐', 'tuijian', '智能择校'], lazy: () => import('../v3/pages/KaoyanRecommend') }),
  '/kaoyan/recommend/:schoolId': node('推荐依据详情', null, '/kaoyan/recommend', 'school', { public: true, lazy: () => import('../v3/pages/KaoyanRecommendDetail') }),
  '/kaoyan/school-eval': node('学科评估', '工学学科评估', '/kaoyan', 'school', { public: true, nav: true, desc: '教育部第四轮学科评估 · 双一流 · 按学科选校', kw: ['eval', '评估', '学科', '双一流', 'pinggu', 'xueke', 'rank', '排名'], lazy: () => import('../v3/pages/KaoyanSchoolEval') }),
  '/kaoyan/plan': node('考研规划', null, '/kaoyan', 'school', { public: true, nav: true, desc: '18 节点关键日程与阶段规划', kw: ['plan', '规划', '日程', '时间节点', 'guihua'], lazy: () => import('../v3/pages/PlanPage') }),
  '/kaoyan/growth': node('成长体系', null, '/kaoyan', 'school', { lazy: () => import('../v3/pages/GrowthPage') }),
  '/kaoyan/assistant': node('择校 AI 助手', null, '/kaoyan', 'school', { lazy: () => import('../v3/pages/KaoyanAssistant') }),

  // ── 上岸经验（新路由） ──
  '/alumni': node('上岸经验', null, null, 'school', { public: true, nav: true, desc: '已上岸学长学姐的经验卡', kw: ['alumni', '上岸', '经验', 'shangyan', 'jingyan'], lazy: () => import('../v3/pages/Alumni') }),
  '/contribute': node('经验投稿', null, null, 'school', { roles: ['alumni'], nav: true, desc: 'alumni 投递结构化经验卡', kw: ['contribute', '投稿', '投稿经验', 'touga'], lazy: () => import('../v3/pages/Contribute') }),

  // ── 通用入口（NAV_OTHER） ──
  '/assistant': node('AI 助手', null, null, 'other', { nav: true, desc: '问答与 RAG 检索', kw: ['assistant', 'ai', '助手', '问答', 'zhushou', 'chat'], lazy: () => import('../v3/pages/Assistant') }),
  '/assistant/answers/:id': node('AI 回答详情', null, '/assistant', 'other', { lazy: () => import('../v3/pages/AssistantAnswer') }),
  '/settings': node('设置', null, null, 'other', { nav: true, desc: '偏好、管理入口与数据管理', kw: ['setting', '设置', '偏好', '管理', 'shezhi', 'config'], lazy: () => import('../v3/pages/Settings') }),

  // ── 管理后台 ──
  '/admin': node('管理后台', null, null, 'admin', { roles: ['admin'] }),
  '/admin/overview': node('数据中心', null, '/admin', 'admin', { roles: ['admin'], nav: true, legacy: '/data-center', desc: '数据域计数与接口体检', kw: ['data', '数据中心', '接口', 'shuju'], lazy: () => import('../v3/pages/DataCenter') }),
  '/admin/users': node('用户管理', null, '/admin', 'admin', { roles: ['admin'], nav: true, legacy: '/users', desc: '账号 · 角色 · 重置密码', kw: ['user', '用户', '账号', 'yonghu', 'users'], lazy: () => import('../v3/pages/UserAdmin') }),
  '/admin/subjects': node('科目管理', null, '/admin', 'admin', { roles: ['admin'], nav: true, legacy: '/subjects', desc: '科目 · 章节 · 题型', kw: ['subject', '科目', 'kemu'], lazy: () => import('../v3/pages/SubjectManager') }),
  '/admin/quiz-bank': node('题库管理', null, '/admin', 'admin', { roles: ['admin'], nav: true, legacy: '/quiz-bank', desc: '真题地图 · 章节刷题', kw: ['bank', '题库', 'tiku'], lazy: () => import('../v3/pages/QuizBank') }),
  '/admin/quiz-review': node('题库复核', null, '/admin', 'admin', { roles: ['admin'], nav: true, legacy: '/quiz-review', desc: '隔离题修复上架 · 低置信确认', kw: ['review', '复核', '错题', '隔离', 'fuhe'], lazy: () => import('../v3/pages/QuizReview') }),
  '/admin/quality': node('数据质量', null, '/admin', 'admin', { roles: ['admin'], nav: true, legacy: '/quality', desc: '识别口径与语料体检', kw: ['quality', '评测', '质量', 'zhiliang', 'eval'], lazy: () => import('../v3/pages/QualityDashboard') }),
  '/admin/schools': node('院校数据管理', null, '/admin', 'admin', { roles: ['admin'], nav: true, legacy: '/kaoyan/import', desc: '定向采集 · 国家线回填 · 公告采集', kw: ['import', '导入', '院校数据', 'daoru', 'notice', '公告'], lazy: () => import('../v3/pages/KaoyanImport') }),
  '/admin/crawl-sources': node('院校采集源', null, '/admin', 'admin', { roles: ['admin'], nav: true, legacy: '/crawl-sources', desc: '选择参与采集的院校 · 数据源目录', kw: ['crawl', '采集', '爬取', 'caiji', 'paqu'], lazy: () => import('../v3/pages/KaoyanCrawlSources') }),
  '/admin/kb-import': node('知识库导入', null, '/admin', 'admin', { roles: ['admin'], nav: true, legacy: '/kb-import', desc: '按类型导入知识图谱与题库', kw: ['import', '导入', '知识库', 'daoru'], lazy: () => import('../v3/pages/KnowledgeBaseImport') }),
  '/admin/model': node('模型训练', null, '/admin', 'admin', { roles: ['admin'], nav: true, legacy: '/model-training', desc: '答疑模型 LoRA 训练', kw: ['train', 'lora', '模型', '训练', 'xunlian'], lazy: () => import('../v3/pages/ModelTraining') }),
  '/admin/caliber': node('数据口径与接口体检', null, '/admin', 'admin', { roles: ['admin'], desc: '今日中枢的调试/对账信息', kw: ['caliber', '口径', '体检'], lazy: () => import('../v3/pages/Caliber') }),
  '/admin/experiences': node('经验卡审核', null, '/admin', 'admin', { roles: ['admin'], nav: true, desc: '审核 alumni 提交的经验卡', kw: ['experience', '经验卡', '审核', 'shenhe'], lazy: () => import('../v3/pages/AdminExperiences') }),

  // ── 认证 / 壳外 ──
  '/login': node('登录', '把考研的每一步，放在同一张地图上。', null, 'auth', { public: true, title: '登录 · 硕途考研', lazy: () => import('../v3/pages/Login') }),
  '/force-change-password': node('首次登录 · 修改密码', null, null, 'auth', { public: true, lazy: () => import('../v3/pages/ForceChangePassword') }),
  '/verify-email': node('邮箱验证', null, null, 'auth', { public: true, lazy: () => import('../v3/pages/VerifyEmail') }),
  '/reset-password': node('重置密码', null, null, 'auth', { public: true, lazy: () => import('../v3/pages/ResetPassword') }),
  '/onboarding': node('初始化引导', null, null, 'auth', { lazy: () => import('../v3/pages/Onboarding') }),
  '/403': node('无权访问', null, null, 'auth', { public: true, lazy: () => import('../v3/pages/Forbidden') }),

  // ── 沉浸式全屏 ──
  '/studio/quiz': node('刷题全屏', null, null, 'immersive', { lazy: () => import('../immersive/QuizStudio') }),
  '/studio/subject/:subject': node('科目复习全屏', null, null, 'immersive', { lazy: () => import('../immersive/SubjectReview') }),

  // ── 可达但不在导航的页面（重定向 / 旧路径兼容） ──
  '/glass': node('毛玻璃实验室', null, null, 'misc', { public: true, lazy: () => import('../v3/pages/GlassLab') }),
  '/codebank': node('复试代码题库', null, null, 'misc', { public: true, lazy: () => import('../v3/pages/CodeBank') }),
  '/documents': node('文档知识库', null, null, 'misc', { public: true, redirect: '/library?view=documents' }),
  '/panorama': node('知识点全景', null, null, 'misc', { redirect: '/knowledge' }),
  '/kbmap': node('知识地图', null, null, 'misc', { redirect: '/knowledge' }),
  '/exam-frequency': node('真题频率', null, null, 'misc', { redirect: '/knowledge' }),
  '/analysis': node('分析', null, null, 'misc', { redirect: '/' }),
  '/errors': node('错题', null, null, 'misc', { redirect: '/error-review' }),
  '/cuoti': node('错题', null, null, 'misc', { redirect: '/error-review' }),
  '/data-quality': node('数据质量', null, null, 'misc', { redirect: '/admin/quality' }),
}

// 派生 children：从 parent 反向计算
for (const [path, n] of Object.entries(routeTree)) {
  if (n.parent && routeTree[n.parent]) {
    routeTree[n.parent].children.push(path)
  }
}

/* ── 从 routeTree 派生所有现有导出（保持导出名与签名不变，消费方零改动） ── */

export const ADMIN_ROOT = '/admin'

// MODULES: 顶栏分组导航（today/learn/practice/review/school）
export const MODULES = GROUPS.map((g) => ({
  key: g.key,
  title: g.title,
  icon: g.icon,
  items: Object.entries(routeTree)
    .filter(([p, n]) => n.group === g.key && n.nav && !n.redirect)
    .map(([p, n]) => ({
      to: p,
      label: n.label,
      exact: n.exact || false,
      desc: n.desc,
      kw: n.kw,
      public: n.public,
    })),
}))

// NAV_OTHER: 通用入口（AI 助手 / 设置）
export const NAV_OTHER = Object.entries(routeTree)
  .filter(([p, n]) => n.group === 'other' && n.nav)
  .map(([p, n]) => ({ to: p, label: n.label, desc: n.desc, kw: n.kw, public: n.public }))

// NAV_ADMIN: 管理后台导航（带 roles=['admin'] 与 legacy 重定向）
export const NAV_ADMIN = Object.entries(routeTree)
  .filter(([p, n]) => n.group === 'admin' && n.nav)
  .map(([p, n]) => ({
    to: p,
    legacy: n.legacy,
    label: n.label,
    desc: n.desc,
    kw: n.kw,
    roles: n.roles,
  }))

export const ADMIN_LEGACY_REDIRECTS = NAV_ADMIN.filter((e) => e.legacy).map((e) => [e.legacy, e.to])
export const NAV_MODULES = MODULES

// ROUTE_META: 路由元信息（document.title 与 H1），从 routeTree 派生
export const ROUTE_META = {}
for (const [path, n] of Object.entries(routeTree)) {
  if (n.redirect) continue
  ROUTE_META[path] = { title: n.title, h1: n.h1 }
}

// CRUMB_BY_PATH: 面包屑名称映射（精确匹配）
const CRUMB_BY_PATH = new Map(
  Object.entries(routeTree)
    .filter(([p, n]) => !p.includes(':') && !p.includes('?'))
    .map(([p, n]) => [p, n.label])
)

// CRUMB_PREFIX: 面包屑前缀匹配（动态参数路由 + /kaoyan/guide 特殊处理）
const CRUMB_PREFIX = [
  ...Object.entries(routeTree)
    .filter(([p]) => p.includes('/:'))
    .map(([p, n]) => [p.substring(0, p.indexOf('/:')) + '/', n.label]),
  ['/kaoyan/guide', '择校数据中心'],
].sort((a, b) => b[0].length - a[0].length)

/* crumbs(pathname): 从 routeTree 派生完整面包屑链（根 → L1 分组 → L2 列表 → L3 详情）。
   纯函数，幂等。未登记路由返回 [{to:'/',label:'硕途'}]。 */
const ROOT_CRUMB = { to: '/', label: '硕途' }

function matchRoutePattern(pattern, pathname) {
  const pp = pattern.split('/')
  const pa = pathname.split('/')
  if (pp.length !== pa.length) return false
  for (let i = 0; i < pp.length; i++) {
    if (pp[i].startsWith(':')) continue
    if (pp[i] !== pa[i]) return false
  }
  return true
}

function matchRoutePath(pathname) {
  if (routeTree[pathname]) return pathname
  const paths = Object.keys(routeTree).sort((a, b) => b.length - a.length)
  for (const p of paths) {
    if (p.includes(':') && matchRoutePattern(p, pathname)) return p
  }
  return null
}

export function crumbs(pathname) {
  const matched = matchRoutePath(pathname)
  if (!matched) return [ROOT_CRUMB]
  const chain = []
  let path = matched
  while (path && routeTree[path]) {
    const n = routeTree[path]
    chain.unshift({ to: path, label: path === '/' ? ROOT_CRUMB.label : n.label })
    path = n.parent
  }
  if (chain.length === 0 || chain[0].to !== '/') {
    chain.unshift(ROOT_CRUMB)
  }
  return chain
}

/** 路由元信息读取：未登记的路由回落到面包屑名（仍只有一个 title 出口）。 */
export function routeMeta(pathname) {
  const hit = ROUTE_META[pathname]
  if (hit) return hit
  const name = crumbName(pathname)
  return { title: `${name} · 硕途考研`, h1: name }
}

// MOBILE_TABS: 移动端底部 Tab（与桌面侧栏分组用同一套词）
export const MOBILE_TABS = [
  { to: '/', group: 'today', icon: Home },
  { to: '/knowledge', group: 'learn', icon: Folder },
  { to: '/quiz', group: 'practice', icon: Book },
  { to: '/error-review', group: 'review', icon: FileText },
  { to: '/kaoyan', group: 'school', icon: Target },
].map((t) => ({ ...t, label: routeMeta(t.to).h1 }))

export const GUEST_TAB_LANDING = { '/': '/kaoyan' }

// ALL_ENTRIES: 命令面板与面包屑用的扁平清单
export const ALL_ENTRIES = [
  ...MODULES.flatMap((m) => m.items.map((it) => ({ ...it, group: m.title }))),
  ...NAV_OTHER.map((it) => ({ ...it, group: '通用' })),
  ...NAV_ADMIN.map((it) => ({ ...it, group: '管理' })),
]

export const isAdminPath = (to) => to === ADMIN_ROOT || to.startsWith(`${ADMIN_ROOT}/`)
export const entriesFor = (isAdmin) => (isAdmin ? ALL_ENTRIES : ALL_ENTRIES.filter((e) => !isAdminPath(e.to)))

export function crumbParent(path) {
  return path !== ADMIN_ROOT && isAdminPath(path) ? { to: ADMIN_ROOT, label: '管理后台' } : null
}

export function crumbName(path) {
  const hit = CRUMB_BY_PATH.get(path)
  if (hit) return hit
  const pre = CRUMB_PREFIX.find(([p]) => path.startsWith(p))
  return pre ? pre[1] : '页面'
}

export const RELATED = {
  '/tasks': ['/knowledge', '/planner', '/error-review'],
  '/knowledge': ['/library', '/quiz', '/error-review'],
  '/library': ['/knowledge', '/quiz', '/textbooks'],
  '/quiz': ['/error-review', '/knowledge', '/cards'],
  '/admin/quiz-bank': ['/quiz', '/knowledge', '/error-review'],
  '/error-review': ['/notebook', '/quiz', '/knowledge'],
  '/assistant': ['/error-review', '/knowledge', '/kaoyan/recommend'],
  '/kaoyan/recommend': ['/kaoyan', '/kaoyan/compare', '/kaoyan/analysis'],
  '/notebook': ['/quiz', '/knowledge', '/error-review'],
  '/insights': ['/quiz', '/error-review', '/notebook'],
  '/documents': ['/knowledge', '/pan', '/assistant'],
  '/pan': ['/library', '/assistant', '/settings'],
  '/planner': ['/tasks', '/knowledge', '/error-review'],
  '/settings': ['/pan', '/library', '/assistant'],
  '/admin/overview': ['/library', '/quiz', '/error-review'],
  '/admin/crawl-sources': ['/admin/schools', '/kaoyan', '/admin/overview'],
  '/admin/subjects': ['/admin/quiz-bank', '/knowledge', '/settings'],
}

// KAOYAN_TABS: 择校模块内 Tab（与顶栏「择校」下拉同源）
export const KAOYAN_TABS = MODULES.find((m) => m.key === 'school').items.map((it) => ({ value: it.to, label: it.label }))

export function visibleModules(layout) {
  const hidden = new Set(layout?.navHidden || [])
  const order = layout?.navOrder || []
  const idx = new Map(order.map((k, i) => [k, i]))
  const rank = (m) => (idx.has(m.key) ? idx.get(m.key) : order.length + MODULES.indexOf(m))
  return MODULES.filter((m) => !hidden.has(m.key)).sort((a, b) => rank(a) - rank(b))
}

export function visibleOther(layout) {
  const hidden = new Set(layout?.otherHidden || [])
  return NAV_OTHER.filter((n) => !hidden.has(n.to))
}

export function visibleModulesFor(modules, isGuest) {
  if (!isGuest) return modules
  return modules
    .map((m) => ({ ...m, items: m.items.filter((it) => it.public) }))
    .filter((m) => m.items.length > 0)
}
