'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'

interface TestRun {
  id: string
  name: string
  project_id: string
  status: string
  total: number
  passed: number
  failed: number
  skipped: number
  pass_rate: number
  started_at: string
  finished_at: string
}

interface AISummary {
  summary: string
  key_findings: string[]
  recommendations: string[]
}

interface TrendData {
  date: string
  total: number
  passed: number
  failed: number
  pass_rate: number
}

export default function ReportsPage() {
  const [runs, setRuns] = useState<TestRun[]>([])
  const [selectedRun, setSelectedRun] = useState<TestRun | null>(null)
  const [aiSummary, setAiSummary] = useState<AISummary | null>(null)
  const [trend, setTrend] = useState<TrendData[]>([])
  const [loading, setLoading] = useState(true)
  const [summaryLoading, setSummaryLoading] = useState(false)

  useEffect(() => {
    fetchRuns()
    fetchTrend()
  }, [])

  const fetchRuns = async () => {
    try {
      const res = await fetch('/api/v1/reports/runs?limit=20')
      if (res.ok) {
        const data = await res.json()
        setRuns(data)
        if (data.length > 0) {
          setSelectedRun(data[0])
          fetchAISummary(data[0].id)
        }
      }
    } catch (error) {
      console.error('Failed to fetch runs:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchTrend = async () => {
    try {
      const res = await fetch('/api/v1/reports/analytics/trend?days=14')
      if (res.ok) {
        const data = await res.json()
        setTrend(data)
      }
    } catch (error) {
      console.error('Failed to fetch trend:', error)
    }
  }

  const fetchAISummary = async (runId: string) => {
    setSummaryLoading(true)
    try {
      const res = await fetch(`/api/v1/reports/runs/${runId}/ai-summary`)
      if (res.ok) {
        const data = await res.json()
        setAiSummary(data)
      }
    } catch (error) {
      console.error('Failed to fetch AI summary:', error)
    } finally {
      setSummaryLoading(false)
    }
  }

  const handleRunSelect = (run: TestRun) => {
    setSelectedRun(run)
    setAiSummary(null)
    fetchAISummary(run.id)
  }

  const handleExport = async (format: string) => {
    if (!selectedRun) return

    try {
      const res = await fetch(`/api/v1/reports/runs/${selectedRun.id}/export/${format}`)
      if (res.ok) {
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `report_${selectedRun.id}.${format === 'excel' ? 'xlsx' : format}`
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error('Export failed:', error)
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed': return '✓'
      case 'running': return '◐'
      case 'failed': return '✗'
      default: return '○'
    }
  }

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed': return 'text-green-400'
      case 'running': return 'text-blue-400'
      case 'failed': return 'text-red-400'
      default: return 'text-gray-400'
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white">
      <div className="flex">
        {/* Sidebar - Run List */}
        <div className="w-80 border-r border-white/10 h-screen overflow-y-auto">
          <div className="p-4 border-b border-white/10">
            <h2 className="text-lg font-semibold">Test Runs</h2>
          </div>

          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full"></div>
            </div>
          ) : (
            <div className="p-2">
              {runs.map((run) => (
                <button
                  key={run.id}
                  onClick={() => handleRunSelect(run)}
                  className={`w-full p-3 rounded-xl text-left transition-colors mb-2 ${
                    selectedRun?.id === run.id
                      ? 'bg-blue-500/20 border border-blue-500/50'
                      : 'bg-white/5 hover:bg-white/10 border border-transparent'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className={getStatusColor(run.status)}>{getStatusIcon(run.status)}</span>
                    <span className="font-medium truncate">{run.name}</span>
                  </div>
                  <div className="flex justify-between text-xs text-gray-500">
                    <span>{new Date(run.started_at).toLocaleDateString()}</span>
                    <span className={run.pass_rate >= 80 ? 'text-green-400' : run.pass_rate >= 50 ? 'text-yellow-400' : 'text-red-400'}>
                      {run.pass_rate.toFixed(0)}%
                    </span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Main Content */}
        <div className="flex-1 p-8 overflow-y-auto h-screen">
          {selectedRun ? (
            <>
              {/* Header */}
              <div className="flex justify-between items-start mb-6">
                <div>
                  <h1 className="text-2xl font-bold mb-1">{selectedRun.name}</h1>
                  <p className="text-gray-400 text-sm">
                    {new Date(selectedRun.started_at).toLocaleString()}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleExport('excel')}
                    className="px-4 py-2 rounded-lg bg-white/10 hover:bg-white/20 transition-colors text-sm"
                  >
                    Export Excel
                  </button>
                  <button
                    onClick={() => handleExport('html')}
                    className="px-4 py-2 rounded-lg bg-white/10 hover:bg-white/20 transition-colors text-sm"
                  >
                    Export HTML
                  </button>
                </div>
              </div>

              {/* Metric Cards */}
              <div className="grid grid-cols-4 gap-4 mb-6">
                <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                  <p className="text-3xl font-bold">{selectedRun.total}</p>
                  <p className="text-sm text-gray-500">Total Tests</p>
                </div>
                <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                  <p className="text-3xl font-bold text-green-400">{selectedRun.passed}</p>
                  <p className="text-sm text-gray-500">Passed</p>
                </div>
                <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                  <p className="text-3xl font-bold text-red-400">{selectedRun.failed}</p>
                  <p className="text-sm text-gray-500">Failed</p>
                </div>
                <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                  <p className={`text-3xl font-bold ${selectedRun.pass_rate >= 80 ? 'text-green-400' : selectedRun.pass_rate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {selectedRun.pass_rate.toFixed(1)}%
                  </p>
                  <p className="text-sm text-gray-500">Pass Rate</p>
                </div>
              </div>

              {/* AI Summary */}
              <div className="p-6 rounded-2xl bg-gradient-to-br from-purple-500/10 to-blue-500/10 border border-purple-500/20 mb-6">
                <div className="flex items-center gap-2 mb-4">
                  <span className="text-xl">🤖</span>
                  <h2 className="text-lg font-semibold">AI Analysis</h2>
                </div>

                {summaryLoading ? (
                  <div className="flex items-center gap-2 text-gray-400">
                    <div className="animate-spin w-4 h-4 border-2 border-purple-500 border-t-transparent rounded-full"></div>
                    <span>Analyzing test results...</span>
                  </div>
                ) : aiSummary ? (
                  <div className="space-y-4">
                    <p className="text-gray-300">{aiSummary.summary}</p>

                    {aiSummary.key_findings.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-gray-400 mb-2">Key Findings</h3>
                        <ul className="list-disc list-inside text-sm text-gray-300 space-y-1">
                          {aiSummary.key_findings.map((finding, idx) => (
                            <li key={idx}>{finding}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {aiSummary.recommendations.length > 0 && (
                      <div>
                        <h3 className="text-sm font-semibold text-gray-400 mb-2">Recommendations</h3>
                        <ul className="list-disc list-inside text-sm text-gray-300 space-y-1">
                          {aiSummary.recommendations.map((rec, idx) => (
                            <li key={idx}>{rec}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-gray-500">No analysis available</p>
                )}
              </div>

              {/* Trend Chart Placeholder */}
              {trend.length > 0 && (
                <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
                  <h2 className="text-lg font-semibold mb-4">14-Day Trend</h2>
                  <div className="flex items-end gap-1 h-32">
                    {trend.map((day, idx) => (
                      <div key={idx} className="flex-1 flex flex-col items-center gap-1">
                        <div
                          className="w-full bg-gradient-to-t from-green-500 to-emerald-400 rounded-t"
                          style={{ height: `${day.pass_rate}%` }}
                        ></div>
                        <span className="text-xs text-gray-500 rotate-45 origin-left">
                          {day.date.slice(5)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-gray-500">
              <span className="text-6xl mb-4">📊</span>
              <p>Select a test run to view details</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
