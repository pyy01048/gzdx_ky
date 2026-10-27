import { taxonomyApi } from './client'

/**
 * 科目清单的唯一取法：GET /api/taxonomy/subjects → 去重后的科目名数组。
 *
 * 各页此前各写一套（有的干脆写死「数学/英语/政治/专业课」），后果是后端新增科目
 * 时页面看不到，而用户从假选项里选中的科目会被原样写进数据。
 *
 * 单独成模块（而不是放 api/client.js）的原因：测试会整体 mock api/client，
 * helper 放在 client.js 里就会绑到真实 taxonomyApi，绕过注入点。
 *
 * 与 hooks/useSubjectConfig 的分工：这里返回**系统里有题目数据的科目**，
 * useSubjectConfig 返回**用户已配置的备考科目**（/api/goals/subjects）。
 */
export async function fetchSubjectNames() {
  const r = await taxonomyApi.subjects()
  const items = Array.isArray(r) ? r : (r && (r.subjects || r.items)) || []
  const names = []
  for (const x of items) {
    const n = String((x && x.subject) || '').trim()
    if (n && !names.includes(n)) names.push(n)
  }
  return names
}
