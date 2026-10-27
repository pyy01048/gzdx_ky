/* 考研择校数据中心 API client
   统一复用 client.js 的 request（含认证头注入与 401 处理） */
import { request } from './client'

export const kaoyanApi = {
  subjects: () => request('/kaoyan/subjects'),
  schools: (params) => request('/kaoyan/schools', { params }),
  // 热度榜 TOP N（对标 txkyer 首页热度榜；热度为后端派生代理指标）
  hot: (params) => request('/kaoyan/analysis/hot', { params }),
  schoolDetail: (id) => request('/kaoyan/schools/' + id),
  schoolMajors: (id) => request('/kaoyan/schools/' + id + '/majors'),
  // M3-4: 招生计划聚合（院系→专业→拟招人数→考试科目，单次调用）
  schoolEnrollmentPlan: (id, params) => request('/kaoyan/schools/' + id + '/enrollment-plan', { params }),
  schoolScores: (id) => request('/kaoyan/schools/' + id + '/scores'),
  schoolAdmissions: (id) => request('/kaoyan/schools/' + id + '/admissions'),
  // V14: 逐人录取分数明细（txkyer 择校宝 2026 拟录取分析 / 公告名单 OCR）
  schoolAdmissionDetails: (id, params) => request('/kaoyan/schools/' + id + '/admissions/details', { params }),
  trend: (params) => request('/kaoyan/analysis/trend', { params }),
  compare: (schoolIds) => request('/kaoyan/analysis/compare', { params: { school_ids: schoolIds } }),
  // V10: 全局通知流（搜索/类型过滤/分页）
  noticesFeed: (params) => request('/kaoyan/notices/feed', { params }),
  // V10: 改考雷达（列表/统计/扫描）
  reforms: (params) => request('/kaoyan/reforms', { params }),
  reformStats: () => request('/kaoyan/reforms/stats'),
  reformScan: (payload) => request('/kaoyan/reforms/scan', { method: 'POST', body: payload }),
  // V10: 分数全景（多年明细/趋势/国家线差值）
  scoreDetail: (id, params) => request('/kaoyan/analysis/score-detail/' + id, { params }),
  // V10: 择校自动调整（冲稳保+理由）
  autoAdjust: (payload) => request('/kaoyan/analysis/auto-adjust', { method: 'POST', body: payload }),
  // D1: 增强推荐（多维权重）
  recommend: (params) => request('/kaoyan/analysis/recommend', { params }),
  // D4: 自然语言择校问答引擎
  assistantQuery: (question) =>
    request('/kaoyan/assistant/query', { method: 'POST', params: { question } }),
  // D3: 设为目标院校
  setGoal: (schoolId, targetScore) =>
    request('/kaoyan/analysis/recommend/' + schoolId + '/set-goal', {
      method: 'POST',
      params: { target_score: targetScore },
    }),
  // D5: 区域热力图数据
  heatmap: (params) => request('/kaoyan/analysis/heatmap', { params }),
  // D6: 招生散点图数据
  scatter: (params) => request('/kaoyan/analysis/scatter', { params }),
  // 择校库里真实存在的年份（下拉候选唯一来源，不在前端写死）
  dataYears: () => request('/kaoyan/analysis/years'),
  // V9 任务完善项: 择校数据分析聚合（业务课二TOP15/数英科目/专业对比/学院招生/专业课分数）
  dashboardAnalysis: () => request('/kaoyan/analysis/dashboard'),
  // F1: 考研 18 节点里程碑 + 阶段→月→周→日 三层规划
  milestones: (year) => request('/plan/milestones', { params: { year } }),
  generatePlan: (year) => request('/plan/generate', { method: 'POST', params: { year } }),
  roadmap: (year) => request('/plan/roadmap', { params: { year } }),
  // F2: 成长体系（等级/徽章/积分/成就）
  growthSummary: () => request('/growth/summary'),
  growthBadges: () => request('/growth/badges'),
  growthAchievements: () => request('/growth/achievements'),
  stats: () => request('/kaoyan/stats'),
  // C1: 触发爬虫
  runSpider: (provinces, allProvinces) =>
    request('/kaoyan/spider/run', {
      method: 'POST',
      params: { provinces: provinces || '', all_provinces: allProvinces || false },
    }),
  // T5: 定向采集（engineering 工科代码集 / national_line 国家线 / notices 公告）
  refresh: (params) => request('/kaoyan/collection/refresh', { method: 'POST', params, timeout: 300000 }),
  // T5: 院校公告列表 + 类型分布
  schoolNotices: (id, params) => request(`/kaoyan/schools/${id}/notices`, { params }),
  // V16 单校公告随时爬取（详情页按钮）
  crawlSchoolNotices: (id) => request('/kaoyan/notices/crawl', { method: 'POST', params: { school_id: id } }),
  noticeTypeStats: () => request('/kaoyan/notices/types'),
  // T6: 跨校公告聚合（首页公告栏）+ 最近 N 天更新概览
  // params: { limit, since, notice_type, keyword, school_id, order_by }
  notices: (params) => request('/kaoyan/notices', { params }),
  noticeUpdates: (params) => request('/kaoyan/notices/updates', { params }),

  // ---- 通知已读标记（/api/notices，单用户设计）----
  // 未读统计（全局角标数据源）：{ total, unread, read, starred, important_unread, by_type, by_school }
  noticeUnreadStats: async () => {
    try { return await request('/notices/unread-stats') } catch { /* 旧部署缺此路由时下面兜底 */ }
    const d = await request('/kaoyan/notices', { params: { limit: 200 } })
    const items = d.items || []
    return {
      total: d.total ?? items.length,
      unread: items.filter((x) => !x.is_read).length,
      read: items.filter((x) => x.is_read).length,
      starred: items.filter((x) => x.is_starred).length,
      important_unread: 0,
      important_total: 0,
      urgent_unread: 0,
      by_type: d.stats?.by_type || {},
    }
  },
  // 通知列表：params { unread_only, starred_only, notice_type, school_id, keyword, page, page_size }
  // guest=true 时直接走公共聚合接口，避免访客先打个人端点吃一次 401
  noticeList: async (params = {}, { guest = false } = {}) => {
    if (!guest) {
      try { return await request('/notices/list', { params }) } catch { /* 旧部署缺 /notices/list 时走聚合通知接口 */ }
    }
    const page = Number(params.page) || 1
    const size = Number(params.page_size) || 20
    // 已读/加星是本地状态，只能拉取后过滤，无法服务端翻页；其余筛选都支持 offset
    const hasLocalFilter = params.unread_only || params.starred_only
    const d = await request('/kaoyan/notices', {
      params: {
        limit: hasLocalFilter ? 200 : size,
        offset: hasLocalFilter ? 0 : (page - 1) * size,
        notice_type: params.notice_type || undefined,
        school_id: params.school_id || undefined,
        keyword: params.keyword || undefined,
      },
    })
    let items = d.items || []
    if (params.unread_only) items = items.filter((x) => !x.is_read)
    if (params.starred_only) items = items.filter((x) => x.is_starred)
    return {
      items: hasLocalFilter ? items.slice((page - 1) * size, page * size) : items,
      // 服务端 total 才是筛选后的总数；仅本地已读/加星过滤时以过滤结果为准
      total: hasLocalFilter ? items.length : (d.total ?? items.length),
      by_type_total: d.stats?.by_type || {},
      page,
      page_size: size,
    }
  },
  // 通知中心统计卡：总数/未读/星标/覆盖院校 + 四类分计数（2026-10-19）
  noticeStats: async ({ guest = false } = {}) => {
    if (guest) return request('/kaoyan/notices/stats')
    try { return await request('/notices/stats') } catch { /* 旧部署缺此路由时下面兜底 */ }
    const d = await request('/kaoyan/notices', { params: { limit: 200 } })
    const items = d.items || []
    const byType = d.stats?.by_type || {}
    return {
      total: d.total ?? items.length,
      unread: items.filter((x) => !x.is_read).length,
      starred: items.filter((x) => x.is_starred).length,
      schools_covered: d.stats?.school_count || 0,
      by_type: Object.entries(byType).map(([type, total]) => ({ type, total, unread: total })),
    }
  },
  // 单条标记已读 / 取消已读
  markNoticeRead: (id, isRead = true) =>
    request(`/notices/${id}/read`, { method: 'POST', body: { is_read: isRead } }),
  // 批量标记：{ notice_ids } | { school_id } | { notice_type } | { all: true }
  batchMarkNoticeRead: (payload) =>
    request('/notices/batch-read', { method: 'POST', body: payload }),
  // 单条加星 / 取消加星
  starNotice: (id, starred = true) =>
    request(`/notices/${id}/star`, { method: 'POST', body: { is_starred: starred } }),
  // 批量加星
  batchStarNotice: (noticeIds, starred = true) =>
    request('/notices/batch-star', {
      method: 'POST',
      body: { notice_ids: noticeIds, is_starred: starred },
    }),
  // C5: 采集历史
  collectionRuns: (params) => request('/kaoyan/collection/runs', { params }),
  // D1: 数据源注册中心（研招网 / 省考试院 / 院校研究生院 / 聚合站）
  dataSources: (params) => request('/kaoyan/datasources', { params }),
  // 院校采集开关：哪些院校参与采集、哪些排除
  crawlTargets: (params) => request('/kaoyan/crawl-targets', { params }),
  toggleCrawlTarget: (payload) => request('/kaoyan/crawl-targets/toggle', { method: 'POST', body: payload }),
  bulkCrawlTargets: (payload) => request('/kaoyan/crawl-targets/bulk', { method: 'POST', body: payload }),
  resetCrawlTargets: () => request('/kaoyan/crawl-targets/reset', { method: 'POST', body: { confirm: true } }),
}
