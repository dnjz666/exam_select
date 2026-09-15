import { useCallback, useEffect, useRef, useState } from 'react'

/** 防抖值：输入框 → 后端换算/覆盖率统计之间不做无意义的连打请求。 */
export function useDebouncedValue<T>(value: T, delay = 350): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export interface AsyncState<T> {
  data: T | null
  error: unknown
  loading: boolean
  reload: () => void
}

/**
 * 极简异步请求 hook。
 *
 * 刻意不引入 react-query：本项目的服务端状态很轻（元数据 + 一次推荐 + 一张志愿表），
 * 多一个依赖就多一份供应链与版本面。所有写操作都走 `api.*` 并显式回灌状态。
 */
export function useAsync<T>(factory: () => Promise<T>, deps: readonly unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)
  const factoryRef = useRef(factory)
  factoryRef.current = factory

  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    factoryRef
      .current()
      .then((result) => {
        if (!alive) return
        setData(result)
      })
      .catch((caught: unknown) => {
        if (!alive) return
        setError(caught)
      })
      .finally(() => {
        if (!alive) return
        setLoading(false)
      })
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce((value) => value + 1), [])
  return { data, error, loading, reload }
}

/** 元素滚动到视野内（风险面板点"定位到该志愿"时用）。 */
export function scrollToElement(id: string): void {
  const element = document.getElementById(id)
  if (element) element.scrollIntoView({ behavior: 'smooth', block: 'center' })
}
