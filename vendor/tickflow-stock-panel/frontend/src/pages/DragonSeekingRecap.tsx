import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Play, Sparkles } from 'lucide-react'
import { toast } from '@/components/Toast'

import { api, type Candidate, type RecapHistoryItem } from '@/lib/api'
import { useBrandTheme, type BrandTheme } from '@/lib/brand'
import { useECharts } from '@/pages/backtest/charts/useECharts'
import type { EChartsOption } from 'echarts'

type RecapThemeColors = {
  pageBg: string
  pageText: string
  pageMuted: string
  border: string
  surface: string
  accent: string
  accentSoft: string
  accentBorder: string
  chartTooltip: string
  chartGrid: string
  chartAxis: string
  chartLegend: string
  chartSeriesPrimary: string
  chartSeriesSecondary: string
}

const RECAP_THEME_COLORS: Record<BrandTheme['id'], RecapThemeColors> = {
  helix: {
    pageBg: '#0a0b0e',
    pageText: '#d1d5db',
    pageMuted: '#8b9bb4',
    border: 'rgba(255,255,255,0.08)',
    surface: 'rgba(17,19,24,0.95)',
    accent: '#8B5CF6',
    accentSoft: 'rgba(139,92,246,0.18)',
    accentBorder: 'rgba(139,92,246,0.55)',
    chartTooltip: 'rgba(17,19,24,0.95)',
    chartGrid: '#1f2937',
    chartAxis: '#1f2937',
    chartLegend: '#8b9bb4',
    chartSeriesPrimary: '#f43f5e',
    chartSeriesSecondary: '#3b82f6',
  },
  pulsar: {
    pageBg: '#0a0b0e',
    pageText: '#d1d5db',
    pageMuted: '#9bb7ad',
    border: 'rgba(61,214,140,0.16)',
    surface: 'rgba(12,17,14,0.95)',
    accent: '#3DD68C',
    accentSoft: 'rgba(61,214,140,0.16)',
    accentBorder: 'rgba(61,214,140,0.48)',
    chartTooltip: 'rgba(12,17,14,0.96)',
    chartGrid: '#24352d',
    chartAxis: '#2f463b',
    chartLegend: '#9bb7ad',
    chartSeriesPrimary: '#3DD68C',
    chartSeriesSecondary: '#22d3ee',
  },
  vanta: {
    pageBg: '#09090b',
    pageText: '#f4f4f5',
    pageMuted: '#a1a1aa',
    border: 'rgba(255,255,255,0.12)',
    surface: 'rgba(12,12,14,0.96)',
    accent: '#FAFAFA',
    accentSoft: 'rgba(250,250,250,0.08)',
    accentBorder: 'rgba(250,250,250,0.30)',
    chartTooltip: 'rgba(12,12,14,0.96)',
    chartGrid: '#2a2a2d',
    chartAxis: '#3f3f46',
    chartLegend: '#a1a1aa',
    chartSeriesPrimary: '#f4f4f5',
    chartSeriesSecondary: '#cbd5e1',
  },
  aurora: {
    pageBg: '#071014',
    pageText: '#dbeafe',
    pageMuted: '#94a3b8',
    border: 'rgba(34,211,238,0.14)',
    surface: 'rgba(8,16,20,0.95)',
    accent: '#22D3EE',
    accentSoft: 'rgba(34,211,238,0.14)',
    accentBorder: 'rgba(34,211,238,0.44)',
    chartTooltip: 'rgba(8,16,20,0.96)',
    chartGrid: '#16333c',
    chartAxis: '#20414d',
    chartLegend: '#94a3b8',
    chartSeriesPrimary: '#22D3EE',
    chartSeriesSecondary: '#60a5fa',
  },
}

interface PortfolioItem {
  code: string
  name: string
  buy_date: string
  buy_price: number
  shares: number
  sector: string
}

interface TradeLogItem {
  code: string
  name: string
  buy_date: string
  buy_price: number
  sell_date: string
  sell_price: number
  shares: number
  pnl: number
  pnl_pct: number
}

interface LiveStockData {
  price: number
  change: number
  turnover: number
}

export function DragonSeekingRecap() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['recapAllData'],
    queryFn: () => api.recapAll(),
  })

  const recapRun = useMutation({
    mutationFn: () => api.recapRun(),
    onSuccess: (res) => {
      refetch()
      if (res.ok) {
        toast(`复盘完成 (exit code: 0)`, 'success')
      } else {
        toast(`复盘失败 (exit code: ${res.returncode})`, 'error')
      }
    },
  })

  const history = data?.history ?? []
  const calibrationData = data?.calibration ?? []
  const uziAuditData = data?.uzi_audit ?? []

  const [brandTheme] = useBrandTheme()
  const recapTheme = RECAP_THEME_COLORS[brandTheme.id]

  const [selectedDate, setSelectedDate] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [scoreFilter, setScoreFilter] = useState('all')
  const [simStockCode, setSimStockCode] = useState('')
  const [simOpenType, setSimOpenType] = useState('ideal')
  const [simVolType, setSimVolType] = useState('met')
  const [simTrendType, setSimTrendType] = useState('breakout')
  const [simTimePhase, setSimTimePhase] = useState('real')
  const [liveData, setLiveData] = useState<Record<string, LiveStockData>>({})
  const [ledgerTab, setLedgerTab] = useState<'portfolio' | 'log'>('portfolio')
  const [cash, setCash] = useState(1_000_000)
  const [portfolio, setPortfolio] = useState<PortfolioItem[]>([])
  const [tradeLog, setTradeLog] = useState<TradeLogItem[]>([])
  const [currentTime, setCurrentTime] = useState('0900')

  useEffect(() => {
    try {
      const storedCash = localStorage.getItem('rtk_recap_cash')
      const storedPortfolio = localStorage.getItem('rtk_recap_portfolio')
      const storedLog = localStorage.getItem('rtk_recap_log')
      if (storedCash !== null) {
        const parsedCash = Number(storedCash)
        if (Number.isFinite(parsedCash)) setCash(parsedCash)
      }
      if (storedPortfolio) {
        const parsedPortfolio = JSON.parse(storedPortfolio) as unknown
        if (Array.isArray(parsedPortfolio)) setPortfolio(parsedPortfolio as PortfolioItem[])
      }
      if (storedLog) {
        const parsedLog = JSON.parse(storedLog) as unknown
        if (Array.isArray(parsedLog)) setTradeLog(parsedLog as TradeLogItem[])
      }
    } catch {
      // keep defaults
    }
  }, [])

  useEffect(() => {
    localStorage.setItem('rtk_recap_cash', String(cash))
    localStorage.setItem('rtk_recap_portfolio', JSON.stringify(portfolio))
    localStorage.setItem('rtk_recap_log', JSON.stringify(tradeLog))
  }, [cash, portfolio, tradeLog])

  useEffect(() => {
    const timer = setInterval(() => {
      const now = new Date()
      const h = String(now.getHours()).padStart(2, '0')
      const m = String(now.getMinutes()).padStart(2, '0')
      setCurrentTime(h + m)
    }, 10_000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (history.length > 0 && !selectedDate) setSelectedDate(history[0].date)
  }, [history, selectedDate])

  const currentRecap = useMemo<RecapHistoryItem | null>(() => {
    if (!selectedDate) return null
    return history.find(item => item.date === selectedDate) ?? null
  }, [history, selectedDate])

  const topCandidates = useMemo<Candidate[]>(() => {
    if (!currentRecap) return []
    return currentRecap.candidates.slice(0, 5)
  }, [currentRecap])

  useEffect(() => {
    if (topCandidates.length > 0 && !topCandidates.some(c => c.code === simStockCode)) {
      setSimStockCode(topCandidates[0].code)
    }
  }, [topCandidates, simStockCode])

  const needleAngle = useMemo(() => {
    if (!currentRecap) return 0
    const s = currentRecap.market.sentiment
    if (s === '极度活跃') return 70
    if (s === '活跃') return 35
    if (s === '低迷降温') return -35
    if (s === '恐慌冰点') return -70
    return 0
  }, [currentRecap])

  const sentimentColorClass = useMemo(() => {
    if (!currentRecap) return 'text-yellow-500'
    const s = currentRecap.market.sentiment
    if (s === '极度活跃') return 'text-danger'
    if (s === '活跃') return 'text-red-400'
    if (s === '低迷降温') return 'text-green-400'
    if (s === '恐慌冰点') return 'text-success'
    return 'text-yellow-500'
  }, [currentRecap])

  const activeTimePhase = useMemo(() => {
    const hhmm = simTimePhase === 'real' ? currentTime : simTimePhase
    const t = parseInt(hhmm, 10)
    if (t < 915) return { name: '集合竞价未开始', warning: '开盘竞价尚未开启。', dotClass: 'bg-muted', textClass: 'text-muted', bgClass: 'border-border bg-elevated/40' }
    if (t <= 919) return { name: '虚假申报/试盘阶段', warning: '当前为主力虚假试盘时段。', dotClass: 'bg-warning animate-ping', textClass: 'text-warning', bgClass: 'border-warning/30 bg-warning/5' }
    if (t <= 924) return { name: '真实申报阶段', warning: '当前为真实资金申报阶段。', dotClass: 'bg-danger animate-pulse', textClass: 'text-danger', bgClass: 'border-danger/30 bg-danger/5' }
    if (t <= 929) return { name: '集合竞价定价定格', warning: '定价已出，核对开盘量能。', dotClass: 'bg-success animate-pulse', textClass: 'text-success', bgClass: 'border-success/30 bg-success/5' }
    return { name: '已正式开盘交易中', warning: '已开市。', dotClass: 'bg-blue-500', textClass: 'text-blue-400', bgClass: 'border-blue-900/30 bg-blue-900/5' }
  }, [simTimePhase, currentTime])

  const filteredCandidates = useMemo<Candidate[]>(() => {
    if (!currentRecap) return []
    let list = currentRecap.candidates
    if (searchQuery) {
      const q = searchQuery.toLowerCase().trim()
      list = list.filter(c => c.name.toLowerCase().includes(q) || c.code.includes(q) || c.sector.toLowerCase().includes(q) || (c.concept && c.concept.toLowerCase().includes(q)))
    }
    if (scoreFilter === 'high') list = list.filter(c => c.score >= 100)
    else if (scoreFilter === 'mid') list = list.filter(c => c.score >= 80 && c.score < 100)
    else if (scoreFilter === 'low') list = list.filter(c => c.score < 80)
    return list
  }, [currentRecap, searchQuery, scoreFilter])

  const getScoreClass = (score: number) => {
    if (score >= 100) return 'bg-danger/20 text-danger border-danger/55'
    if (score >= 80) return 'bg-warning/20 text-warning border-warning/55'
    return 'bg-elevated text-gray-500 border-border'
  }

  const simResult = useMemo(() => {
    if (!currentRecap || !simStockCode) return { decision: '等待数据', badge: '等待', color: 'text-muted', border: 'border-border text-muted', reason: '请选择一个目标股进行判定。' }
    const c = currentRecap.candidates.find(item => item.code === simStockCode)
    if (!c) return { decision: '等待数据', badge: '等待', color: 'text-muted', border: 'border-border text-muted', reason: '标的未找到。' }
    const open = simOpenType
    const vol = simVolType
    const trend = simTrendType
    if (trend === 'weak') return { decision: '放弃操作 / 观望', badge: '观望', color: 'text-muted', border: 'border-border text-muted', reason: '【开盘承接走弱】开盘后无量下探且跌破分时均线。' }
    if (open === 'fever') return trend === 'limit_up'
      ? { decision: '打板排单 (极轻仓)', badge: '高风险买', color: 'text-warning', border: 'border-warning/50 text-warning', reason: '【超高开秒板】竞价高开超 6% 甚至接近涨停。' }
      : { decision: '放弃操作 / 避雷', badge: '避雷', color: 'text-success', border: 'border-success/50 text-success', reason: '【高烧防闷杀】高开超 6% 以上开盘，若无秒板则易高开低走。' }
    if (open === 'ideal') {
      if (vol === 'met' && trend === 'breakout') return { decision: '理想买点 (半路/加仓)', badge: '黄金买点', color: 'text-danger', border: 'border-danger/50 text-danger', reason: '【分歧换手突破】竞价放量达标且开在理想区间。' }
      if (vol === 'met' && trend === 'limit_up') return { decision: '强力打板 (确认点)', badge: '强力买点', color: 'text-danger', border: 'border-danger/50 text-danger', reason: '【强势秒板确认】竞价放量且承接强。' }
      if (vol === 'not_met' && trend === 'breakout') return { decision: '轻仓试探', badge: '温和买点', color: 'text-warning', border: 'border-warning/50 text-warning', reason: '【缩量高开换手】竞价成交量偏小。' }
    }
    if (open === 'low') {
      if (trend === 'low_bounce' && vol === 'met') return { decision: '弱转强突破打板', badge: '反包买点', color: 'text-red-400', border: 'border-red-400/50 text-red-400', reason: '【经典弱转强】低开但竞价量能爆量达标。' }
      return { decision: '放弃操作', badge: '放弃', color: 'text-muted', border: 'border-border text-muted', reason: '【低开低走走弱】没有放量翻红。' }
    }
    return { decision: '轻仓观察', badge: '观察', color: 'text-warning', border: 'border-warning/50 text-warning', reason: '【温和状态】明日表现中规中矩。' }
  }, [currentRecap, simStockCode, simOpenType, simVolType, simTrendType])

  const currentUziAudit = useMemo(() => {
    if (!selectedDate) return [] as NonNullable<typeof uziAuditData>
    const list = uziAuditData.filter(item => item.date === selectedDate)
    const candidateCodes = topCandidates.map(c => c.code)
    return list.filter(item => candidateCodes.includes(item.code)).sort((a, b) => candidateCodes.indexOf(a.code) - candidateCodes.indexOf(b.code)).slice(0, 5)
  }, [uziAuditData, selectedDate, topCandidates])

  const isUziOnline = useMemo(() => currentUziAudit.some(item => item.report_path && item.report_path !== ''), [currentUziAudit])

  const getPrefix = (code: string) => {
    if (code.startsWith('6') || code.startsWith('9')) return 'sh'
    if (code.startsWith('8')) return 'bj'
    return 'sz'
  }

  const isVolMet = (c: Candidate) => {
    const item = liveData[c.code]
    if (!item) return false
    const targetVol = c.float_mcap * c.turnover * 10
    return item.turnover >= targetVol
  }

  const isSignalMet = (c: Candidate) => {
    const item = liveData[c.code]
    if (!item) return false
    return item.change >= 2.0 && item.change <= 5.0 && isVolMet(c)
  }

  const fillSimulatorFromLive = (dataMap: Record<string, LiveStockData>) => {
    if (!simStockCode || !dataMap[simStockCode]) return
    const quote = dataMap[simStockCode]
    const change = quote.change
    if (change >= 6.0) setSimOpenType('fever')
    else if (change >= 2.0 && change <= 5.0) setSimOpenType('ideal')
    else if (change >= 0.0 && change < 2.0) setSimOpenType('mild')
    else setSimOpenType('low')
    const c = topCandidates.find(item => item.code === simStockCode)
    if (c) {
      const targetVol = c.float_mcap * c.turnover * 10
      setSimVolType(quote.turnover >= targetVol ? 'met' : 'not_met')
    }
  }

  const fetchLiveQuotes = () => {
    if (topCandidates.length === 0) return
    const prefixedCodes = topCandidates.map(c => getPrefix(c.code) + c.code)
    const url = 'https://qt.gtimg.cn/q=' + prefixedCodes.join(',')
    const oldScript = document.getElementById('tencent-quotes-script')
    if (oldScript) oldScript.remove()
    const script = document.createElement('script')
    script.id = 'tencent-quotes-script'
    script.src = url
    script.onload = () => {
      const updatedData: Record<string, LiveStockData> = { ...liveData }
      const win = window as unknown as Record<string, string | undefined>
      topCandidates.forEach(c => {
        const varName = 'v_' + getPrefix(c.code) + c.code
        const rawVal = win[varName]
        if (rawVal) {
          const vals = rawVal.split('~')
          if (vals.length >= 38) {
            updatedData[c.code] = {
              price: parseFloat(vals[3]),
              change: parseFloat(vals[32]),
              turnover: parseFloat(vals[37]),
            }
          }
        }
      })
      setLiveData(updatedData)
      fillSimulatorFromLive(updatedData)
      toast('实时竞价数据刷新成功', 'success')
    }
    script.onerror = () => toast('获取腾讯财经数据失败', 'error')
    document.head.appendChild(script)
  }

  useEffect(() => {
    if (simStockCode && liveData[simStockCode]) fillSimulatorFromLive(liveData)
  }, [simStockCode, liveData])

  const getValuationPrice = (code: string, buyPrice: number) => {
    if (!currentRecap) return buyPrice
    const c = currentRecap.candidates.find(item => item.code === code)
    return c ? c.price : buyPrice
  }

  const getFloatingPnl = (holding: PortfolioItem) => {
    const price = getValuationPrice(holding.code, holding.buy_price)
    return holding.shares * (price - holding.buy_price)
  }

  const getFloatingPnlPct = (holding: PortfolioItem) => {
    const price = getValuationPrice(holding.code, holding.buy_price)
    return ((price - holding.buy_price) / holding.buy_price) * 100
  }

  const getPnlColor = (holding: PortfolioItem) => (getFloatingPnl(holding) >= 0 ? 'text-danger' : 'text-success')

  const getExitAdvice = (holding: PortfolioItem) => {
    if (!currentRecap) return { text: '监控中', color: 'border-border text-muted' }
    const isZt = currentRecap.candidates.some(item => item.code === holding.code)
    if (holding.buy_date === selectedDate) return { text: '今日建仓 / 持股中', color: 'border-warning/30 text-warning bg-warning/5' }
    if (isZt) return { text: '连板晋级 / 建议持有', color: 'border-danger/30 text-danger bg-danger/5' }
    return { text: '断板走弱 / 建议平仓', color: 'border-success/30 text-success bg-success/5' }
  }

  const buyStock = (stock: Candidate, price: number) => {
    if (portfolio.some(item => item.code === stock.code)) {
      toast('持仓中已存在该股', 'error')
      return
    }
    const posSize = 200_000
    const actualCost = Math.min(posSize, cash)
    if (actualCost <= 0) {
      toast('可用资金不足，无法建仓', 'error')
      return
    }
    const shares = Math.floor(actualCost / price / 100) * 100
    if (shares <= 0) {
      toast('可用资金不足以买入一手', 'error')
      return
    }
    const totalCost = shares * price
    setCash(prev => prev - totalCost)
    setPortfolio(prev => [...prev, { code: stock.code, name: stock.name, buy_date: selectedDate, buy_price: price, shares, sector: stock.sector }])
    toast(`以 ${price.toFixed(2)}元 买入 ${stock.name} ${shares}股`, 'success')
  }

  const sellStock = (code: string, price: number) => {
    const idx = portfolio.findIndex(item => item.code === code)
    if (idx === -1) return
    const item = portfolio[idx]
    const revenue = item.shares * price
    setCash(prev => prev + revenue)
    const pnl = revenue - item.shares * item.buy_price
    const pnl_pct = (pnl / (item.shares * item.buy_price)) * 100
    setTradeLog(prev => [...prev, { code: item.code, name: item.name, buy_date: item.buy_date, buy_price: item.buy_price, sell_date: selectedDate, sell_price: price, shares: item.shares, pnl, pnl_pct }])
    setPortfolio(prev => prev.filter(h => h.code !== code))
  }

  const triggerSell = (holding: PortfolioItem) => {
    const price = getValuationPrice(holding.code, holding.buy_price)
    if (window.confirm(`确认以今日收盘估值 ${price.toFixed(2)}元 进行虚拟平仓吗？`)) sellStock(holding.code, price)
  }

  const resetLedger = () => {
    if (window.confirm('确认清空模拟交易账本吗？所有持仓与历史记录将被重置。')) {
      setCash(1_000_000)
      setPortfolio([])
      setTradeLog([])
    }
  }

  const chartOption = useMemo<EChartsOption>(() => {
    if (history.length === 0) return {}
    const last15 = [...history].slice(0, 15).reverse()
    const labels = last15.map(item => item.date.substring(5))
    const rates = last15.map(item => item.market.promotion_rate)
    const luCounts = last15.map(item => item.market.limit_ups)
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, backgroundColor: recapTheme.chartTooltip, borderColor: recapTheme.border, textStyle: { color: recapTheme.pageText, fontSize: 10, fontFamily: 'Fira Code' } },
      legend: { data: ['1进2晋级率 (%)', '总涨停数'], textStyle: { color: recapTheme.chartLegend, fontSize: 9, fontFamily: 'Fira Code' }, top: 0 },
      grid: { top: '15%', left: '3%', right: '3%', bottom: '5%', containLabel: true },
      xAxis: [{ type: 'category', data: labels, axisLine: { lineStyle: { color: recapTheme.chartAxis } }, axisLabel: { color: recapTheme.chartLegend, fontSize: 8, fontFamily: 'Fira Code' } }],
      yAxis: [
        { type: 'value', name: '晋级率', position: 'left', axisLine: { show: true, lineStyle: { color: recapTheme.chartSeriesPrimary } }, axisLabel: { color: recapTheme.chartSeriesPrimary, fontSize: 8, fontFamily: 'Fira Code', formatter: '{value}%' }, splitLine: { lineStyle: { color: recapTheme.chartGrid } } },
        { type: 'value', name: '总涨停', position: 'right', axisLine: { show: true, lineStyle: { color: recapTheme.chartSeriesSecondary } }, axisLabel: { color: recapTheme.chartSeriesSecondary, fontSize: 8, fontFamily: 'Fira Code' }, splitLine: { show: false } },
      ],
      series: [
        { name: '1进2晋级率 (%)', type: 'line', yAxisIndex: 0, data: rates, itemStyle: { color: recapTheme.chartSeriesPrimary }, lineStyle: { width: 1.5 }, smooth: true },
        { name: '总涨停数', type: 'line', yAxisIndex: 1, data: luCounts, itemStyle: { color: recapTheme.chartSeriesSecondary }, lineStyle: { width: 1, type: 'dashed' }, smooth: true },
      ],
    }
  }, [history, recapTheme])

  const trendChartRef = useECharts(chartOption, [history, brandTheme.id])

  if (isLoading) {
    return <div className="flex h-screen items-center justify-center text-muted" style={{ background: recapTheme.pageBg, color: recapTheme.pageMuted }}><div className="flex flex-col items-center gap-3"><div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" /><div className="text-xs">加载复盘数据库中...</div></div></div>
  }

  if (history.length === 0) {
    return <div className="flex h-screen items-center justify-center text-muted" style={{ background: recapTheme.pageBg, color: recapTheme.pageMuted }}><div className="text-center p-8"><p className="text-sm">暂无复盘历史数据。</p><button onClick={() => refetch()} className="mt-4 px-4 py-2 bg-primary text-white rounded text-xs hover:bg-primary/90">重试拉取</button></div></div>
  }

  const availableDates = history.map(item => item.date)
  const pageStyle = { background: recapTheme.pageBg, color: recapTheme.pageText }

  return (
    <div className="min-h-screen p-6 font-sans selection:bg-danger/25" style={pageStyle}>
      <header className="flex flex-col md:flex-row justify-between items-start md:items-center border-b pb-4 mb-8 gap-4" style={{ borderColor: recapTheme.border }}>
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-3" style={{ color: recapTheme.pageText }}>
            <Sparkles className="h-6 w-6 text-danger" />
            <span style={{ color: recapTheme.pageText }}>寻龙诀 · A股 1进2接力复盘控制台</span>
          </h1>
          <p className="text-xs mt-1 uppercase tracking-wide font-mono" style={{ color: recapTheme.pageMuted }}>1进2 连板接力分析控制台</p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold" style={{ color: recapTheme.pageMuted }}>竞价时段模拟:</span>
            <select value={simTimePhase} onChange={e => setSimTimePhase(e.target.value)} className="border rounded px-3 py-1.5 text-xs focus:outline-none font-mono" style={{ background: recapTheme.surface, borderColor: recapTheme.border, color: recapTheme.pageText }}>
              <option value="real">系统实时时间</option>
              <option value="915">模拟 09:17 (虚假试盘)</option>
              <option value="920">模拟 09:22 (真实竞价)</option>
              <option value="925">模拟 09:26 (竞价定格)</option>
              <option value="930">模拟 09:35 (盘中交易)</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold" style={{ color: recapTheme.pageMuted }}>选择复盘日期:</span>
            <select value={selectedDate} onChange={e => setSelectedDate(e.target.value)} className="border rounded px-3 py-1.5 text-xs focus:outline-none font-mono" style={{ background: recapTheme.surface, borderColor: recapTheme.border, color: recapTheme.pageText }}>
              {availableDates.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          <button
            onClick={() => recapRun.mutate()}
            disabled={recapRun.isPending}
            className="flex items-center gap-1.5 border text-xs font-bold uppercase tracking-wider font-mono px-3 py-1.5 rounded transition-all active:scale-[0.97] disabled:opacity-50"
            style={{
              borderColor: recapRun.isPending ? 'rgba(255,255,255,0.08)' : recapTheme.accentBorder,
              background: recapRun.isPending ? 'rgba(255,255,255,0.03)' : recapTheme.accentSoft,
              color: recapRun.isPending ? recapTheme.pageMuted : recapTheme.accent,
            }}
          >
            <Play className="h-3 w-3" />
            {recapRun.isPending ? '复盘运行中...' : '手工触发复盘'}
          </button>
          <div className="border text-xs font-bold uppercase tracking-wider font-mono px-3 py-1.5 rounded" style={{ borderColor: recapTheme.accentBorder, background: recapTheme.accentSoft, color: recapTheme.accent }}>连板接力模式</div>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <div className="rounded border p-6 flex flex-col justify-between" style={{ background: recapTheme.surface, borderColor: recapTheme.border }}>
          <div>
            <div className="border-b pb-2 mb-4" style={{ borderColor: recapTheme.border }}><span className="text-xs font-semibold" style={{ color: recapTheme.pageMuted }}>市场短线情绪</span></div>
            <div className="py-4 relative flex flex-col items-center">
              <svg viewBox="0 0 120 70" className="w-36 h-20">
                <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="rgba(255,255,255,0.03)" strokeWidth="8" strokeLinecap="square" />
                <path d="M 14 60 A 46 46 0 0 1 106 60" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="1" strokeDasharray="2,2" />
                <line x1="10" y1="60" x2="16" y2="60" stroke="#10b981" strokeWidth="1.5" />
                <line x1="20" y1="38" x2="25" y2="41" stroke="#3b82f6" strokeWidth="1" />
                <line x1="38" y1="20" x2="41" y2="25" stroke="#64748b" strokeWidth="1" />
                <line x1="60" y1="10" x2="60" y2="17" stroke="#64748b" strokeWidth="1.5" />
                <line x1="82" y1="20" x2="79" y2="25" stroke="#f59e0b" strokeWidth="1" />
                <line x1="100" y1="38" x2="95" y2="41" stroke="#e11d48" strokeWidth="1" />
                <line x1="104" y1="60" x2="110" y2="60" stroke="#e11d48" strokeWidth="1.5" />
                <line x1="60" y1="60" x2="60" y2="16" stroke="#f43f5e" strokeWidth="1.5" strokeLinecap="square" style={{ transform: `rotate(${needleAngle}deg)`, transformOrigin: '60px 60px' }} className="transition-transform duration-500 ease-out" />
                <circle cx="60" cy="60" r="5" fill="#111318" stroke="#f43f5e" strokeWidth="1" />
                <circle cx="60" cy="60" r="2" fill="#ffffff" />
              </svg>
              <div className={`text-2xl font-bold mt-2 uppercase tracking-wide ${sentimentColorClass}`}>{currentRecap?.market.sentiment}</div>
            </div>
            <div className="space-y-2 border-t pt-3 text-xs font-mono" style={{ borderColor: recapTheme.border }}>
              <div className="flex justify-between items-center"><span style={{ color: recapTheme.pageMuted }}>全市场涨停家数</span><span style={{ color: recapTheme.pageText }} className="font-bold">{currentRecap?.market.limit_ups}</span></div>
              <div className="flex justify-between items-center"><span style={{ color: recapTheme.pageMuted }}>全市场跌停家数</span><span style={{ color: recapTheme.pageText }} className="font-bold">{currentRecap?.market.limit_downs}</span></div>
            </div>
          </div>
          <div className="border-t pt-3 mt-3" style={{ borderColor: recapTheme.border }}>
            <span className="text-xs font-semibold block mb-2" style={{ color: recapTheme.pageMuted }}>量化胜率校验 / 历史晋级率回测</span>
            <div className="space-y-1.5 text-xs font-mono">
              {calibrationData.map(cal => <div key={cal.score_range} className="flex justify-between items-center"><span className="text-gray-500">{cal.bucket_name.split(' ')[0]} ({cal.score_range}分)</span><span className={`font-bold ${cal.win_rate >= 15 ? 'text-danger' : 'text-gray-400'}`}>{cal.win_rate.toFixed(2)}% <span className="text-gray-500 font-normal">({cal.promoted_count}/{cal.total_count})</span></span></div>)}
            </div>
          </div>
        </div>

        <div className="lg:col-span-2 rounded border p-6 flex flex-col justify-between" style={{ background: recapTheme.surface, borderColor: recapTheme.border }}>
          <div className="flex justify-between items-center border-b pb-2 mb-4" style={{ borderColor: recapTheme.border }}>
            <span className="text-xs font-semibold" style={{ color: recapTheme.pageMuted }}>1进2 晋级率与总涨停家数历史趋势</span>
            <span className="text-xs uppercase tracking-wider font-semibold font-mono" style={{ color: recapTheme.pageMuted }}>最近15个交易日</span>
          </div>
          <div className="h-[210px] w-full relative"><div ref={trendChartRef} className="h-full w-full" /></div>
          <div className="grid grid-cols-2 gap-4 border-t pt-3 text-xs font-mono" style={{ borderColor: recapTheme.border }}>
            <div className="flex justify-between"><span style={{ color: recapTheme.pageMuted }}>今日1进2晋级率</span><span className="text-danger font-bold">{currentRecap?.market.promotion_rate.toFixed(2)}%</span></div>
            <div className="flex justify-between"><span style={{ color: recapTheme.pageMuted }}>两市总成交额</span><span style={{ color: recapTheme.pageText }} className="font-bold">{currentRecap?.market.total_turnover.toFixed(1)} 亿</span></div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-6">
        {[
          ['上证指数', '000001', currentRecap?.market.sh_price, currentRecap?.market.sh_change],
          ['深证成指', '399001', currentRecap?.market.sz_price, currentRecap?.market.sz_change],
          ['创业板指', '399006', currentRecap?.market.cy_price, currentRecap?.market.cy_change],
        ].map(([label, code, price, chg]) => (
          <div key={String(code)} className="rounded border p-5 flex flex-col justify-between" style={{ background: recapTheme.surface, borderColor: recapTheme.border }}>
            <div className="flex justify-between items-center text-xs uppercase" style={{ color: recapTheme.pageMuted }}><span>{label}</span><span className="font-mono text-xs text-gray-500">{code}</span></div>
            <div className="mt-2 flex justify-between items-baseline"><span className="text-lg font-bold font-mono" style={{ color: recapTheme.pageText }}>{Number(price ?? 0).toFixed(2)}</span><span className={`text-xs font-bold font-mono ${(Number(chg ?? 0)) >= 0 ? 'text-danger' : 'text-success'}`}>{Number(chg ?? 0) >= 0 ? '+' : ''}{Number(chg ?? 0).toFixed(2)}%</span></div>
          </div>
        ))}
        <div className="rounded border p-5 flex flex-col justify-between" style={{ background: recapTheme.surface, borderColor: recapTheme.border }}>
          <div className="flex justify-between items-center text-xs uppercase" style={{ color: recapTheme.pageMuted }}><span>北向资金流向</span><span className="px-1 text-xs font-semibold" style={{ border: `1px solid ${recapTheme.border}`, background: recapTheme.accentSoft, color: recapTheme.accent }}>净买入</span></div>
          <div className="mt-2 flex justify-between items-baseline"><span className="text-lg font-bold font-mono" style={{ color: recapTheme.pageText }}>{((currentRecap ? ((currentRecap.market.hgt_flow ?? 0) + (currentRecap.market.sgt_flow ?? 0)) : 0) >= 0 ? '+' : '')}{(currentRecap ? ((currentRecap.market.hgt_flow ?? 0) + (currentRecap.market.sgt_flow ?? 0)) : 0).toFixed(2)}亿</span><span className="text-xs font-mono" style={{ color: recapTheme.pageMuted }}>沪:{(currentRecap?.market.hgt_flow ?? 0).toFixed(1)} 深:{(currentRecap?.market.sgt_flow ?? 0).toFixed(1)}</span></div>
        </div>
      </div>

      <div className="rounded border p-6 md:p-8 mb-6" style={{ background: recapTheme.surface, borderColor: recapTheme.border }}>
        <div className="border-b pb-2 mb-4 flex justify-between items-center" style={{ borderColor: recapTheme.border }}>
          <span className="text-xs font-semibold" style={{ color: recapTheme.pageMuted }}>重点关注首板标的</span>
          <span className="text-xs font-bold uppercase tracking-wider font-mono" style={{ color: recapTheme.accent }}>接力因子前五强</span>
        </div>
        <div className="space-y-3">
          {topCandidates.map((c, idx) => (
            <div key={c.code} className="py-4 first:pt-0 last:pb-0">
              <div className="flex flex-col md:flex-row gap-5 border p-4 md:p-5 rounded" style={{ borderColor: recapTheme.border, background: 'rgba(11,13,18,0.5)' }}>
                <div className="w-full md:w-1/3 flex flex-col justify-between gap-4">
                  <div className="flex justify-between items-start gap-3">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className={`text-xs px-2 py-0.5 font-bold border rounded ${idx === 0 ? 'bg-danger/20 text-danger border-danger/55' : 'bg-elevated text-gray-400 border-border'}`}>NO.{idx + 1}</span>
                      <div className="min-w-0"><span className="block text-sm font-semibold truncate" style={{ color: recapTheme.pageText }}>{c.name}</span><span className="block text-xs text-gray-400 font-mono truncate">{c.code}</span></div>
                    </div>
                    <div className="flex flex-wrap justify-end gap-2">
                      <span className="text-xs text-yellow-500 font-bold border border-yellow-500/15 px-2 py-0.5 bg-yellow-500/5 font-mono">接力指数 {c.score}</span>
                      {c.pred_prob !== null && c.pred_prob !== undefined && <span className="text-xs text-danger font-bold border border-danger/15 px-2 py-0.5 bg-danger/5 font-mono">预估晋级率 {(c.pred_prob * 100).toFixed(1)}%</span>}
                      <button onClick={() => buyStock(c, c.price)} className="bg-danger/20 border border-danger/50 text-danger hover:bg-danger hover:text-white px-2 py-0.5 text-xs font-semibold rounded select-none transition-all active:scale-[0.96]">模拟买入</button>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mt-1 text-xs font-mono">
                    <div className="bg-[#08090a]/50 border border-border/50 p-2 rounded"><div className="text-gray-500">首次封板时间</div><div className="text-white font-medium mt-0.5">{c.first_seal_time_formatted}</div></div>
                    <div className="bg-[#08090a]/50 border border-border/50 p-2 rounded"><div className="text-gray-500">日内炸板次数</div><div className={`text-white font-medium mt-0.5 ${c.blown_count >= 2 ? 'text-warning font-semibold' : ''}`}>{c.blown_count}</div></div>
                    <div className="bg-[#08090a]/50 border border-border/50 p-2 rounded"><div className="text-gray-500">日内换手率</div><div className="text-white font-medium mt-0.5">{c.turnover.toFixed(2)}%</div></div>
                    <div className="bg-[#08090a]/50 border border-border/50 p-2 rounded"><div className="text-gray-500">流通市值</div><div className="text-white font-medium mt-0.5">{c.float_mcap.toFixed(2)} 亿</div></div>
                  </div>
                  <div className="text-xs mt-1 font-semibold uppercase tracking-wide" style={{ color: recapTheme.pageMuted }}>所属行业: <span className="text-gray-300 normal-case">{c.sector}</span></div>
                </div>
                <div className="w-full md:w-2/3 p-5 border rounded flex flex-col justify-center gap-2.5 min-h-[150px]" style={{ background: recapTheme.accentSoft, borderColor: recapTheme.border }}>
                  <div className="flex items-center justify-between"><span className="text-xs uppercase tracking-wider font-semibold" style={{ color: recapTheme.pageMuted }}>操作建议</span><span className="text-xs text-danger font-bold uppercase tracking-wider font-mono">INTRADAY PLAYBOOK</span></div>
                  <div className="text-sm leading-7 font-mono border-l-2 border-l-danger/50 pl-3 whitespace-pre-line" style={{ color: recapTheme.pageText }}>{c.playbook}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        <div className="lg:col-span-2 rounded border p-6 md:p-8 flex flex-col justify-between" style={{ background: recapTheme.surface, borderColor: recapTheme.border }}>
          <div>
            <div className="border-b pb-2 mb-4 flex justify-between items-center gap-4" style={{ borderColor: recapTheme.border }}>
              <span className="text-xs font-semibold" style={{ color: recapTheme.pageMuted }}>次日竞价监控哨 / 量化上车标准</span>
              <div className="flex gap-2"><button onClick={fetchLiveQuotes} className="bg-danger/20 border border-danger text-danger hover:bg-danger hover:text-white px-2 py-1 text-xs font-bold rounded transition-all active:scale-[0.97] uppercase tracking-wider font-mono">刷新今日实时竞价 (09:25后生效)</button></div>
            </div>
            <div className={`mb-3 border p-3 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 transition-all duration-300 rounded ${activeTimePhase.bgClass}`}>
              <div className="flex items-center gap-2"><span className={`w-2.5 h-2.5 rounded-full ${activeTimePhase.dotClass}`} /><span className="text-xs font-bold text-white font-mono">竞价哨口监控状态: {activeTimePhase.name}</span></div>
              <p className={`text-xs font-semibold leading-relaxed ${activeTimePhase.textClass}`}>{activeTimePhase.warning}</p>
            </div>
            <div className="space-y-2">
              {topCandidates.map(c => (
                <div key={c.code + '-target'} onClick={() => setSimStockCode(c.code)} role="button" tabIndex={0} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') setSimStockCode(c.code) }} className={`border p-4 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 cursor-pointer transition-all duration-200 select-none rounded focus:outline-none ${simStockCode === c.code ? 'border-danger bg-danger/5' : 'border-border bg-[#0e1013]/60 hover:border-danger/30'}`}>
                  <div className="w-full sm:w-1/4"><h4 className="text-sm font-extrabold text-white flex items-center gap-1.5"><span className={`w-1.5 h-1.5 rounded-full ${simStockCode === c.code ? 'bg-danger animate-pulse' : 'bg-gray-600'}`} />{c.name}</h4><p className="text-xs text-gray-500 font-mono mt-0.5">{c.code} · {c.sector}</p></div>
                  <div className="w-full sm:w-1/2 grid grid-cols-3 gap-2 text-xs font-mono">
                    <div><div className="text-gray-500">昨日收盘</div><div className="text-danger font-bold mt-0.5">{c.price.toFixed(2)}元</div></div>
                    <div><div className="text-gray-500">理想开盘 (2%~5%)</div><div className="text-warning font-bold mt-0.5">{(c.price * 1.02).toFixed(2)} ~ {(c.price * 1.05).toFixed(2)}元</div>{liveData[c.code] && <div className="mt-1 pt-1 border-t border-border/40"><span className="text-gray-600">实际开盘: </span><span className={`font-bold ${liveData[c.code].change >= 0 ? 'text-danger' : 'text-success'}`}>{liveData[c.code].change >= 0 ? '+' : ''}{liveData[c.code].change.toFixed(2)}%</span></div>}</div>
                    <div><div className="text-gray-500">目标竞价额 (10%昨成交)</div><div className="text-red-400 font-bold mt-0.5">&gt;{(c.float_mcap * c.turnover * 10).toFixed(0)}万</div>{liveData[c.code] && <div className="mt-1 pt-1 border-t border-border/40"><span className="text-gray-600">实际竞价: </span><span className={`font-bold ${isVolMet(c) ? 'text-danger' : 'text-gray-400'}`}>{liveData[c.code].turnover.toFixed(0)}万</span></div>}</div>
                  </div>
                  <div className="w-full sm:w-1/4 text-right text-xs text-gray-400 leading-normal flex flex-col items-end gap-1"><span className="font-semibold">{c.score >= 115 ? '高溢价高要求，爆量高开为强' : '弱转强首选，高开回踩支撑进场'}</span>{liveData[c.code] && <div className="mt-2">{isSignalMet(c) ? <span className="bg-danger/10 text-danger border border-danger/55 px-2 py-0.5 font-bold rounded animate-pulse">🚀 竞价强承接 (达标)</span> : <span className="bg-elevated text-gray-500 border border-border px-2 py-0.5 rounded font-medium">未达标</span>}</div>}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="text-xs text-gray-500 mt-4 border-t border-border/40 pt-2">* 使用说明：点击上方股票行可直接聚焦右侧决策模拟器。</div>
        </div>

        <div className="rounded border p-6 md:p-8 flex flex-col justify-between" style={{ background: recapTheme.surface, borderColor: recapTheme.border }}>
          <div>
            <div className="border-b pb-2 mb-4" style={{ borderColor: recapTheme.border }}><span className="text-xs font-semibold" style={{ color: recapTheme.pageMuted }}>1进2 实战上车决策器 / 模拟判定</span></div>
            <div className="space-y-3">
              <div><label className="text-gray-500 text-xs block font-semibold mb-1">选择目标股:</label><select value={simStockCode} onChange={e => setSimStockCode(e.target.value)} aria-label="选择目标股" className="w-full bg-elevated border border-border rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-danger font-mono">{topCandidates.map(c => <option key={c.code + '-sim'} value={c.code}>{c.name} ({c.code})</option>)}</select></div>
              <div><label className="text-gray-500 text-xs block font-semibold mb-1">明日 09:25 开盘涨幅:</label><select value={simOpenType} onChange={e => setSimOpenType(e.target.value)} aria-label="明日开盘涨幅" className="w-full bg-elevated border border-border rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-danger"><option value="fever">高烧低走区 (高开 &gt;6% 或一字板)</option><option value="ideal">理想溢价区 (高开 2% ~ 5%)</option><option value="mild">温和试探区 (高开 0% ~ 2%)</option><option value="low">低开分歧区 (平开或低开 &lt;0%)</option></select></div>
              <div><label className="text-gray-500 text-xs block font-semibold mb-1">明日 09:25 竞价成交额:</label><select value={simVolType} onChange={e => setSimVolType(e.target.value)} aria-label="明日竞价成交额" className="w-full bg-elevated border border-border rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-danger"><option value="met">放量达标 (达到或超出目标值)</option><option value="not_met">缩量未达标 (低于目标值)</option></select></div>
              <div><label className="text-gray-500 text-xs block font-semibold mb-1">开盘前15分钟分时走势:</label><select value={simTrendType} onChange={e => setSimTrendType(e.target.value)} aria-label="开盘走势" className="w-full bg-elevated border border-border rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-danger"><option value="breakout">高开下探不破分时均线，放量突破开盘价</option><option value="limit_up">开盘爆量单边直线拉升，极速封死二板</option><option value="weak">冲高后无量下杀，跌破均线且不翻红</option><option value="low_bounce">低开震荡后强力翻红，放量突破昨日收盘价</option></select></div>
            </div>
          </div>
          <div className="mt-4 p-3 border border-border bg-[#08090a]/50 rounded text-xs"><div className={`flex justify-between items-center font-bold mb-1 ${simResult.color}`}><span>决策判定: {simResult.decision}</span><span className={`text-[10px] uppercase tracking-wide border px-1 rounded ${simResult.border}`}>{simResult.badge}</span></div><p className="text-gray-400 leading-relaxed font-mono mt-1">{simResult.reason}</p></div>
        </div>
      </div>

      <div className="rounded border p-6 md:p-8 mb-6" style={{ background: recapTheme.surface, borderColor: recapTheme.border }}>
        <div className="border-b pb-2 mb-4 flex justify-between items-center gap-4" style={{ borderColor: recapTheme.border }}>
          <span className="text-[#9aa8be] text-xs font-semibold">■ UZI 智能评委席报告 / UZI JURY AUDIT REPORT</span>
          <div className="flex items-center gap-2"><span className={`text-xs px-2 py-0.5 border rounded font-semibold ${isUziOnline ? 'border-green-950 bg-green-950/20 text-green-400' : 'border-warning/30 bg-warning/5 text-warning'}`}>{isUziOnline ? '大模型智能评审模式' : '本地财务规则模拟'}</span><span className="text-xs text-danger font-bold uppercase tracking-wider font-mono">JURY AUDIT PANEL</span></div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
          {currentUziAudit.map(u => (
            <div key={u.code} className="bg-[#0b0d12]/50 p-4 border border-border rounded flex flex-col justify-between gap-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.03)]">
              <div>
                <div className="flex justify-between items-start border-b border-border/40 pb-3"><div><h4 className="text-sm font-semibold text-white">{u.name}</h4><p className="text-xs text-gray-500 font-mono mt-0.5">{u.code} · <span className="normal-case text-gray-400">{u.sector}</span></p></div><div className="inline-flex items-center justify-center px-2 py-0.5 border border-border bg-[#11131c]/50 text-danger text-lg font-extrabold rounded">{u.average_score.toFixed(1)}<span className="text-xs ml-0.5">分</span></div></div>
                <div className="mt-3 space-y-2 text-xs"><div className="flex justify-between items-center"><span className="text-gray-500">巴菲特 (价值流派)</span><span className={`font-bold ${u.val_vote === '多头' ? 'text-danger' : u.val_vote === '空头' ? 'text-success' : 'text-gray-500'}`}>{u.val_vote}</span></div><div className="flex justify-between items-center"><span className="text-gray-500">赵老哥 (游资接力)</span><span className={`font-bold ${u.mom_vote === '多头' ? 'text-danger' : u.mom_vote === '空头' ? 'text-success' : 'text-gray-500'}`}>{u.mom_vote}</span></div><div className="flex justify-between items-center border-t border-border/40 pt-2 mt-2"><span className="text-gray-500">大空头 (排雷评级)</span><span className={`font-bold ${u.risk_level === '安全' ? 'text-success' : 'text-danger'}`}>{u.risk_level}</span></div></div>
              </div>
              <div className="text-xs text-gray-300 bg-[#0e1117]/80 p-3.5 border border-border rounded leading-6 font-mono max-h-[140px] overflow-y-auto">{u.summary}</div>
              {u.report_path && <div className="mt-1"><a href={u.report_path} target="_blank" rel="noreferrer" className="block w-full text-center bg-[#11131c]/60 border border-border text-danger hover:bg-[#151923] hover:text-white py-1.5 text-xs font-bold rounded transition-all active:scale-[0.96]">查看 UZI 深度诊断报告</a></div>}
            </div>
          ))}
        </div>
      </div>

      <div className="rounded border p-6 md:p-8 mb-6" style={{ background: recapTheme.surface, borderColor: recapTheme.border }}>
        <div className="border-b border-border/40 pb-2 mb-4 flex justify-between items-center"><span className="text-[#8b9bb4] text-xs font-semibold">模拟实战交易账本 / PORTFOLIO & LEDGER</span><span className="text-xs text-warning font-bold uppercase tracking-wider font-mono">MOCK PAPER TRADING JOURNAL</span></div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            <div className="flex gap-4 border-b border-border/40 pb-2 text-xs font-semibold"><button onClick={() => setLedgerTab('portfolio')} className={`pb-1 px-1 uppercase tracking-wider ${ledgerTab === 'portfolio' ? 'text-danger border-b-2 border-danger' : 'text-[#8b9bb4]'}`}>当前持仓 ({portfolio.length})</button><button onClick={() => setLedgerTab('log')} className={`pb-1 px-1 uppercase tracking-wider ${ledgerTab === 'log' ? 'text-danger border-b-2 border-danger' : 'text-[#8b9bb4]'}`}>交易日志 ({tradeLog.length})</button></div>
            {ledgerTab === 'portfolio' ? <div className="space-y-2">{portfolio.length === 0 ? <div className="text-center py-8 text-gray-600 text-xs">暂无持仓股。可在下方股票池中点击“买入”或顶部五强中点击“模拟买入”进行建仓。</div> : portfolio.map(p => <div key={p.code} className="bg-[#08090a]/50 p-4 border border-border rounded flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4"><div className="w-full sm:w-1/4"><h5 className="text-xs font-bold text-white flex items-center gap-1.5"><span className="w-1.5 h-1.5 bg-danger rounded-full animate-pulse" />{p.name}</h5><p className="text-[10px] text-gray-500 font-mono mt-0.5">{p.code} · {p.sector}</p></div><div className="w-full sm:w-1/2 grid grid-cols-4 gap-2 text-xs font-mono"><div><div className="text-gray-600">建仓日期/均价</div><div className="text-white mt-0.5">{p.buy_date.substring(5)} / {p.buy_price.toFixed(2)}</div></div><div><div className="text-gray-600">持股股数/市值</div><div className="text-white mt-0.5">{p.shares}股 / {(p.shares * getValuationPrice(p.code, p.buy_price)).toFixed(0)}</div></div><div><div className="text-gray-600">今日估值/盈亏</div><div className={`mt-0.5 font-semibold ${getPnlColor(p)}`}>{getValuationPrice(p.code, p.buy_price).toFixed(2)} / {getFloatingPnl(p) >= 0 ? '+' : ''}{getFloatingPnl(p).toFixed(0)}</div></div><div><div className="text-gray-600">盈亏比例</div><div className={`mt-0.5 font-bold ${getPnlColor(p)}`}>{getFloatingPnlPct(p) >= 0 ? '+' : ''}{getFloatingPnlPct(p).toFixed(2)}%</div></div></div><div className="w-full sm:w-1/4 flex flex-col items-end gap-1.5"><span className={`text-[10px] px-2 py-0.5 border rounded ${getExitAdvice(p).color}`}>{getExitAdvice(p).text}</span><button onClick={() => triggerSell(p)} className="bg-danger/20 border border-danger text-danger hover:bg-danger hover:text-white px-3 py-1 text-xs font-bold rounded transition-all active:scale-[0.96]">虚拟平仓</button></div></div>)}</div> : <div className="overflow-x-auto max-h-[300px] pr-1">{tradeLog.length === 0 ? <div className="text-center py-8 text-gray-600 text-xs">暂无历史平仓记录。</div> : <table className="w-full text-left text-xs border-collapse"><thead><tr className="border-b border-border/40 text-gray-500 font-bold uppercase tracking-wider bg-[#08090a]/50"><th className="py-2 px-2">代码</th><th className="py-2 px-2">名称</th><th className="py-2 px-2">建仓日期/均价</th><th className="py-2 px-2">平仓日期/均价</th><th className="py-2 px-2 text-right">股数</th><th className="py-2 px-2 text-right">实现盈亏</th><th className="py-2 px-2 text-right">盈亏比</th></tr></thead><tbody>{tradeLog.map(log => <tr key={log.buy_date + '-' + log.code} className="border-b border-border/20"><td className="py-2 px-2 font-mono text-gray-400">{log.code}</td><td className="py-2 px-2 font-bold text-white">{log.name}</td><td className="py-2 px-2 font-mono">{log.buy_date.substring(5)} / {log.buy_price.toFixed(2)}</td><td className="py-2 px-2 font-mono">{log.sell_date.substring(5)} / {log.sell_price.toFixed(2)}</td><td className="py-2 px-2 text-right font-mono text-white">{log.shares}</td><td className={`py-2 px-2 text-right font-mono font-bold ${log.pnl >= 0 ? 'text-danger' : 'text-success'}`}>{log.pnl >= 0 ? '+' : ''}{log.pnl.toFixed(0)}</td><td className={`py-2 px-2 text-right font-mono font-bold ${log.pnl >= 0 ? 'text-danger' : 'text-success'}`}>{log.pnl >= 0 ? '+' : ''}{log.pnl_pct.toFixed(2)}%</td></tr>)}</tbody></table>}</div>}
          </div>
          <div className="border-l border-border/40 pl-6 flex flex-col justify-between gap-4">
            <div>
              <div className="border-b border-border/40 pb-2 mb-4"><span className="text-[#8b9bb4] text-xs font-semibold">模拟持仓绩效面板</span></div>
              <div className="space-y-3 font-mono text-xs"><div className="flex justify-between items-center"><span className="text-[#8b9bb4]">总资产 (可用+持仓)</span><span className="text-white font-extrabold text-sm">{(cash + portfolio.reduce((sum, item) => sum + item.shares * getValuationPrice(item.code, item.buy_price), 0)).toFixed(0)} 元</span></div><div className="flex justify-between items-center"><span className="text-[#8b9bb4]">可用现金</span><span className="text-white font-bold">{cash.toFixed(0)} 元</span></div><div className="flex justify-between items-center"><span className="text-[#8b9bb4]">持仓估算市值</span><span className="text-white font-bold">{portfolio.reduce((sum, item) => sum + item.shares * getValuationPrice(item.code, item.buy_price), 0).toFixed(0)} 元</span></div><div className="flex justify-between items-center border-t border-border/40 pt-2"><span className="text-[#8b9bb4]">账户累计盈亏</span><span className={`font-extrabold ${(cash + portfolio.reduce((sum, item) => sum + item.shares * getValuationPrice(item.code, item.buy_price), 0) - 1_000_000) >= 0 ? 'text-danger' : 'text-success'}`}>{(cash + portfolio.reduce((sum, item) => sum + item.shares * getValuationPrice(item.code, item.buy_price), 0) - 1_000_000) >= 0 ? '+' : ''}{(cash + portfolio.reduce((sum, item) => sum + item.shares * getValuationPrice(item.code, item.buy_price), 0) - 1_000_000).toFixed(0)} 元</span></div><div className="flex justify-between items-center"><span className="text-[#8b9bb4]">账户累计收益率</span><span className="font-extrabold text-danger">{((cash + portfolio.reduce((sum, item) => sum + item.shares * getValuationPrice(item.code, item.buy_price), 0) - 1_000_000) / 10_000).toFixed(2)}%</span></div><div className="flex justify-between items-center border-t border-border/40 pt-2"><span className="text-[#8b9bb4]">模拟交易胜率</span><span className="text-warning font-bold">{tradeLog.length === 0 ? '0.00' : ((tradeLog.filter(item => item.pnl > 0).length / tradeLog.length) * 100).toFixed(2)}%</span></div><div className="flex justify-between items-center"><span className="text-[#8b9bb4]">已结平仓笔数</span><span className="text-white font-medium">{tradeLog.length} 笔</span></div></div>
            </div>
            <div className="flex gap-2"><button onClick={resetLedger} className="w-full border border-border hover:border-danger hover:text-danger py-1.5 text-xs font-bold rounded transition-all text-[#8b9bb4] active:scale-[0.98]">重置模拟账户账本</button></div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="rounded border p-6 flex flex-col justify-between" style={{ background: recapTheme.surface, borderColor: recapTheme.border }}>
          <div className="border-b border-border/40 pb-2 mb-4"><span className="text-[#8b9bb4] text-xs font-semibold">热门涨停行业板块</span></div>
          <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">{(currentRecap?.market.sector_ranking ?? []).map(sec => <div key={sec.name} className="bg-[#08090a]/50 p-3 border border-border rounded flex justify-between items-center hover:border-danger/25 transition-colors duration-200"><div><h4 className="text-xs font-bold text-white">{sec.name}</h4><p className="text-[10px] text-gray-500 mt-0.5">领涨龙头: {sec.leader}</p></div><div className="text-right"><span className="text-lg font-bold text-danger font-mono">{sec.count}</span><span className="text-[10px] text-[#8b9bb4] block uppercase tracking-wide">涨停数</span></div></div>)}</div>
        </div>

        <div className="lg:col-span-2 rounded border p-6 flex flex-col justify-between" style={{ background: recapTheme.surface, borderColor: recapTheme.border }}>
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center border-b border-border/40 pb-2 mb-4 gap-4">
            <span className="text-[#8b9bb4] text-xs font-semibold">首板候选股票池 (共 {currentRecap?.candidates.length ?? 0} 只)</span>
            <div className="flex gap-2 w-full sm:w-auto">
              <input id="candidate-search" type="text" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="过滤代码/简称/行业..." aria-label="搜索候选股票" className="bg-[#08090a]/50 border border-border rounded px-2 py-1 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-danger font-mono w-full sm:w-40" />
              <select value={scoreFilter} onChange={e => setScoreFilter(e.target.value)} aria-label="按接力指数筛选" className="bg-[#08090a]/50 border border-border rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-danger font-mono"><option value="all">全部接力指数</option><option value="high">黄金接力 (&gt;=100)</option><option value="mid">强势潜力 (80-99)</option><option value="low">弱势股 (&lt;80)</option></select>
            </div>
          </div>
          <div className="overflow-x-auto max-h-[350px] pr-1">
            <table className="w-full text-left text-xs border-collapse">
              <thead><tr className="border-b border-border/40 text-gray-500 font-bold uppercase tracking-wider bg-[#08090a]/50"><th className="py-2.5 px-3">代码</th><th className="py-2.5 px-3">简称</th><th className="py-2.5 px-3 text-right">最新价</th><th className="py-2.5 px-3 text-right">换手</th><th className="py-2.5 px-3 text-right">首次封板</th><th className="py-2.5 px-3 text-center">炸板</th><th className="py-2.5 px-3 text-right">封单资金</th><th className="py-2.5 px-3 text-right">封单比</th><th className="py-2.5 px-3 text-right">流通市值</th><th className="py-2.5 px-3">所属行业</th><th className="py-2.5 px-3">题材归因</th><th className="py-2.5 px-3 text-center">接力指数</th></tr></thead>
              <tbody>{filteredCandidates.map(c => <tr key={c.code} className="border-b border-border/20 hover:bg-elevated/20 transition-colors"><td className="py-2 px-3 font-mono text-gray-400">{c.code}</td><td className="py-2 px-3"><div className="flex items-center justify-between gap-2"><span className="font-bold text-white">{c.name}</span><button onClick={() => buyStock(c, c.price)} className="bg-danger/10 border border-danger/40 text-danger hover:bg-danger hover:text-white px-1.5 py-0.5 text-xs font-semibold rounded select-none transition-all active:scale-[0.95]">买入</button></div></td><td className="py-2 px-3 text-right font-mono text-danger font-semibold">{c.price.toFixed(2)}</td><td className="py-2 px-3 text-right font-mono">{c.turnover.toFixed(2)}%</td><td className="py-2 px-3 text-right font-mono">{c.first_seal_time_formatted}</td><td className={`py-2 px-3 text-center font-mono ${c.blown_count >= 2 ? 'text-warning font-bold' : 'text-gray-500'}`}>{c.blown_count}</td><td className="py-2 px-3 text-right font-mono text-warning">{c.seal_funds.toFixed(1)}万</td><td className={`py-2 px-3 text-right font-mono ${(c.seal_ratio ?? 0) >= 3.0 ? 'text-red-400 font-semibold' : 'text-gray-500'}`}>{(c.seal_ratio ?? 0).toFixed(2)}%</td><td className="py-2 px-3 text-right font-mono">{c.float_mcap.toFixed(1)}亿</td><td className="py-2 px-3 text-gray-300">{c.sector}</td><td className="py-2 px-3 text-gray-500 max-w-[120px] truncate" title={c.concept ?? '暂无归因'}>{c.concept ?? '暂无归因'}</td><td className="py-2 px-3 text-center"><span className={`font-mono px-2 py-0.5 text-xs font-bold border rounded ${getScoreClass(c.score)}`}>{c.score}</span></td></tr>)}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
DragonSeekingRecap.displayName = 'DragonSeekingRecap'
