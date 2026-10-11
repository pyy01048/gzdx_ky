/**
 * ID类型工具函数
 * 处理前端生成的字符串uid和后端返回的数字id
 */

/**
 * 判断id是否为纯数字
 */
export const isNumericId = (id) => /^\d+$/.test(String(id))

/**
 * 转换为API可用的id
 * 数字保留为数字，字符串原样传递
 */
export const toApiId = (id) => {
  if (id === null || id === undefined) return id
  return isNumericId(id) ? Number(id) : id
}

/**
 * 比较两个id是否相等（兼容数字和字符串）
 */
export const idEqual = (a, b) => String(a) === String(b)