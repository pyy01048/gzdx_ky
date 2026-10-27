/* 备考科目配置 —— 全局共享 Hook（单一数据源）
 *
 * 各页的科目下拉、筛选项、进度分母都从这里取，避免每页各写一套科目列表
 * （原本 Analysis/Pan/Planner 各有一份硬编码，口径互相不一致且改了不生效）。
 *
 * 数据源是 GET /api/goals/subjects（后端 services/subject_config.py），
 * 与「设置 → 备考科目」是同一份配置，改设置即刻改筛选。
 *
 * 后端不可达时**不编造科目**：科目会直接进入进度分母、筛选下拉和 AI 画像，
 * 凭空一套就等于替所有用户假设了专业方向。调用方按两态给文案：
 *   ready=false            → 配置还没取到（首次加载中 / 后端不可达）
 *   ready=true 且 exam=[]  → 已连通但用户尚未配置，引导去「设置 → 备考科目」
 */
import { useEffect, useState } from 'react'
import { goalsApi } from '../api/client'

/* 长科目名做成分/下拉标签时的简称（仅显示，存值和请求参数一律用全称） */
const SHORT_LABELS = {
  数字电子技术: '数电',
  模拟电子技术: '模电',
  计算机学科专业基础408: '408',
  光学与工程光学: '光学',
  真题综合: '真题',
}

export function subjectLabel(name) {
  return SHORT_LABELS[name] || name
}

/** 全局快照（模块级）：所有调用方共享同一份配置。初始为「还没取到配置」。 */
let snapshot = {
  exam: [],
  support: [],
  allKnown: [],
  usingDefault: true,
  ready: false,
}
let version = 0
const listeners = new Set()

function publish() {
  listeners.forEach((fn) => fn())
}

function applyConfig(d) {
  /* 残缺体（两个字段都不存在，多半是异常响应）保留上一份口径；
     但「字段存在且为空数组」是合法答复：用户真的还没配置科目，不能当成故障。 */
  const hasExam = Array.isArray(d && d.exam_subjects)
  const hasSupport = Array.isArray(d && d.support_subjects)
  if (!hasExam && !hasSupport) return snapshot
  const exam = hasExam ? d.exam_subjects : []
  const known = Array.isArray(d.all_known) ? d.all_known : []
  const knownSet = new Set(known)
  snapshot = {
    exam,
    /* 只保留 taxonomy 认识的支撑科目：后端已归一化，这里再防一次脏值 */
    support: (hasSupport ? d.support_subjects : [])
      .filter((s) => !knownSet.size || knownSet.has(s)),
    allKnown: known,
    usingDefault: !!(d && d.using_default),
    ready: true,
  }
  version += 1
  publish()
  return snapshot
}

/** 拉取科目配置。并发调用复用同一个 in-flight Promise；已就绪则不再请求。 */
let inflight = null
export function refreshSubjectConfig(force = false) {
  if (inflight) return inflight
  if (snapshot.ready && !force) return Promise.resolve(snapshot)
  inflight = Promise.resolve()
    .then(() => goalsApi.subjects())
    .then(applyConfig)
    .catch(() => snapshot)
    .finally(() => {
      inflight = null
    })
  return inflight
}

/**
 * @returns {{exam:string[], support:string[], active:string[], allKnown:string[],
 *            usingDefault:boolean, ready:boolean, version:number}}
 *          exam=考试科目（计入进度），support=支撑科目（可查资料出题不计进度），active=两者并集
 */
export function useSubjectConfig() {
  const [tick, setTick] = useState(version)

  useEffect(() => {
    const fn = () => setTick(version)
    listeners.add(fn)
    return () => {
      listeners.delete(fn)
    }
  }, [])

  useEffect(() => {
    refreshSubjectConfig()
  }, [])

  return { ...snapshot, active: [...snapshot.exam, ...snapshot.support], version: tick }
}

export default useSubjectConfig
