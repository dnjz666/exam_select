import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { useProfileStore, isProfileComplete } from './store/profile'
import { usePlanStore } from './store/plan'
import { Disclaimer } from './components/Disclaimer'
import { provinceLabel } from './lib/labels'

const NAV = [
  { to: '/profile', label: '建档向导', description: '省份 → 选考 → 成绩 → 偏好' },
  { to: '/recommend', label: '推荐列表', description: '冲稳保垫 + 证据链' },
  { to: '/plan', label: '志愿表', description: '排序 · 梯度 · 风险' },
  { to: '/report', label: '报告', description: '可打印 · 含依据' },
  { to: '/chat', label: '对话', description: '名师口吻追问' },
]

/**
 * 应用外壳。
 *
 * 首屏即建档向导（AGENTS.md §8.1：不做落地页/轮播图），因此根路由 `/` 重定向到 `/profile`。
 * 顶部条常驻显示"档案是否齐全"，因为 `missing_fields` 非空时必须阻止进入推荐（§8.1）。
 */
export function Shell() {
  const profile = useProfileStore()
  const planId = usePlanStore((state) => state.planId)
  const location = useLocation()
  const complete = isProfileComplete(profile.student)

  return (
    <div className="flex min-h-full flex-col">
      <header className="no-print sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="app-shell flex flex-wrap items-center gap-x-6 gap-y-2 py-3">
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold text-slate-900">高考志愿填报智能体</span>
            <span className="text-xs text-slate-400">位次法 · 可解释 · 可回测</span>
          </div>

          <nav className="flex flex-wrap items-center gap-1" aria-label="主导航">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                title={item.description}
                className={({ isActive }) =>
                  [
                    'rounded-lg px-3 py-1.5 text-sm transition',
                    isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100',
                  ].join(' ')
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3 text-xs">
            {profile.province && (
              <span className="chip-slate">
                {provinceLabel(profile.province)} · {profile.subjects.length}/3 门选考
              </span>
            )}
            {profile.rank ? <span className="chip-slate">位次 {profile.rank.toLocaleString('zh-CN')}</span> : null}
            <span className={complete ? 'chip bg-emerald-100 text-emerald-800' : 'chip bg-amber-100 text-amber-800'}>
              {complete ? '档案已完整' : '档案未完成'}
            </span>
            {planId && <span className="chip-slate">志愿表 {planId.slice(-6)}</span>}
          </div>
        </div>
      </header>

      <main className="app-shell flex-1 py-6">
        <Outlet />
      </main>

      {location.pathname !== '/report' && (
        <footer className="no-print mt-8 border-t border-slate-200 bg-white py-6">
          <div className="app-shell space-y-3">
            <Disclaimer />
          </div>
        </footer>
      )}
    </div>
  )
}
