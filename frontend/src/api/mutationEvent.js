/**
 * 统一的「数据已变更」事件名。
 *
 * client.js 在任何**非 GET** 请求成功（2xx）后派发该事件；
 * 订阅方（api/hub.js 的聚合缓存）据此失效自己的快照，
 * 避免「刚答完题 / 打完卡，回到中枢 45s 内还看到旧数字」。
 *
 * 单独成文件的原因：client.js 与 hub.js 需要共享同一个字符串，
 * 但不能互相 import（hub → client 已存在；client → hub 会成环）。
 */
export const MUTATION_EVENT = 'kaoyan:mutation'

/**
 * 订阅方（/hub 页面）合并突发写入后的静默刷新延迟。
 * 连续背单词/连点打卡时事件会高频到达，防抖把「第一次有效数据」
 * 压到用户停顿 ~2.5s 后只刷一次，而不是每个动作 4 条请求。
 */
export const MUTATION_REFRESH_DELAY = 2500

