import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import type { ECharts, EChartsOption } from 'echarts'

/**
 * ECharts 实例管理 Hook — 自动初始化/resize/销毁。
 * 返回 ref 绑定到容器 div，和 setOption 方法。
 */
export function useECharts(
  option: EChartsOption | null,
  deps: any[] = [],
) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null)
  const chartRef = useCallback((node: HTMLDivElement | null) => {
    setContainer(node)
  }, [])
  const instanceRef = useRef<ECharts | null>(null)

  useLayoutEffect(() => {
    if (!container) return

    const instance = echarts.init(container, undefined, { renderer: 'canvas' })
    instanceRef.current = instance

    if (option) {
      instance.setOption(option, { notMerge: true })
    }

    const handleResize = () => instance.resize()
    window.addEventListener('resize', handleResize)

    const resizeObserver = typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(() => instance.resize())
    resizeObserver?.observe(container)

    return () => {
      resizeObserver?.disconnect()
      window.removeEventListener('resize', handleResize)
      instance.dispose()
      if (instanceRef.current === instance) {
        instanceRef.current = null
      }
    }
  }, [container])

  useLayoutEffect(() => {
    if (!instanceRef.current || !option || !container) return
    instanceRef.current.setOption(option, { notMerge: true })
  }, [container, option, ...deps])

  return chartRef
}
