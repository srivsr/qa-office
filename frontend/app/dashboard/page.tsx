'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'

interface QuickAction {
  title: string
  description: string
  icon: string
  href: string
  color: string
}

interface TestRun {
  id: string
  name: string
  status: string
  passed: number
  failed: number
  total: number
  started_at: string
}


const quickActions: QuickAction[] = [
  {
    title: 'Run E2E Tests',
    description: 'Execute end-to-end tests',
    icon: '🎯',
    href: '/execute',
    color: 'from-blue-500 to-cyan-500'
  },
  {
    title: 'Generate Tests',
    description: 'AI-powered test generation',
    icon: '✨',
    href: '/execute',
    color: 'from-purple-500 to-pink-500'
  },
  {
    title: 'View Reports',
    description: 'Analytics and insights',
    icon: '📊',
    href: '/reports',
    color: 'from-green-500 to-emerald-500'
  },
  {
    title: 'Framework Gen',
    description: 'Create test frameworks',
    icon: '🏗️',
    href: '/framework',
    color: 'from-orange-500 to-amber-500'
  }
]

export default function DashboardPage() {
  const [runs, setRuns] = useState<TestRun[]>([])
  const [coverage, setCoverage] = useState({ percentage: 0, total: 0, covered: 0 })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchDashboardData()
  }, [])

  const fetchDashboardData = async () => {
    try {
      const res = await fetch('/api/v1/test-runner/saved-runs')
      if (res.ok) {
        const data = await res.json()
        const mapped: TestRun[] = (data.runs || []).map((s: any) => ({
          id: s.id,
          name: s.name || 'Test Run',
          status: s.status,
          passed: s.summary?.passed || 0,
          failed: s.summary?.failed || 0,
          total: s.summary?.total_test_cases || 0,
          started_at: s.started_at || new Date().toISOString(),
        }))
        setRuns(mapped)
      }
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error)
    } finally {
      setLoading(false)
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

  const getPassRate = (run: TestRun) => {
    if (run.total === 0) return 0
    return Math.round((run.passed / run.total) * 100)
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold mb-2">Dashboard</h1>
          <p className="text-gray-400">Welcome to QA-OS - Your AI-Powered Test Platform</p>
        </div>

        {/* Quick Actions */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {quickActions.map((action) => (
            <Link
              key={action.title}
              href={action.href}
              className="group p-6 rounded-2xl bg-white/5 border border-white/10 hover:border-white/20 transition-all hover:scale-[1.02]"
            >
              <div className={`text-4xl mb-4 w-14 h-14 rounded-xl bg-gradient-to-br ${action.color} flex items-center justify-center`}>
                {action.icon}
              </div>
              <h3 className="text-lg font-semibold mb-1 group-hover:text-blue-400 transition-colors">
                {action.title}
              </h3>
              <p className="text-sm text-gray-400">{action.description}</p>
            </Link>
          ))}
        </div>

        {/* Recent Runs & Analytics */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Recent Runs */}
          <div className="lg:col-span-2 p-6 rounded-2xl bg-white/5 border border-white/10">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-semibold">Recent Test Runs</h2>
              <Link href="/reports" className="text-sm text-blue-400 hover:text-blue-300">
                View All →
              </Link>
            </div>

            {loading ? (
              <div className="flex items-center justify-center h-48">
                <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full"></div>
              </div>
            ) : runs.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-gray-500">
                <span className="text-4xl mb-2">🧪</span>
                <p>No test runs yet</p>
                <Link href="/execute" className="mt-2 text-blue-400 text-sm hover:underline">
                  Run your first test →
                </Link>
              </div>
            ) : (
              <div className="space-y-3">
                {runs.map((run) => (
                  <Link
                    key={run.id}
                    href={`/run/${run.id}`}
                    className="flex items-center justify-between p-4 rounded-xl bg-white/5 hover:bg-white/10 transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <div className={`w-2 h-2 rounded-full ${run.status === 'completed' ? 'bg-green-400' : run.status === 'running' ? 'bg-blue-400 animate-pulse' : 'bg-red-400'}`}></div>
                      <div>
                        <p className="font-medium">{run.name}</p>
                        <p className="text-sm text-gray-500">
                          {new Date(run.started_at).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-6">
                      <div className="text-right">
                        <p className="text-sm">
                          <span className="text-green-400">{run.passed}</span>
                          <span className="text-gray-500"> / </span>
                          <span className="text-red-400">{run.failed}</span>
                          <span className="text-gray-500"> / </span>
                          <span>{run.total}</span>
                        </p>
                        <p className="text-xs text-gray-500">pass / fail / total</p>
                      </div>
                      <div className="w-16 text-right">
                        <p className={`font-bold ${getPassRate(run) >= 80 ? 'text-green-400' : getPassRate(run) >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
                          {getPassRate(run)}%
                        </p>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* Coverage & Stats */}
          <div className="space-y-6">
            {/* Coverage Card */}
            <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
              <h3 className="text-lg font-semibold mb-4">Test Coverage</h3>
              <div className="flex items-center justify-center">
                <div className="relative w-32 h-32">
                  <svg className="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
                    <circle
                      cx="50"
                      cy="50"
                      r="40"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="8"
                      className="text-white/10"
                    />
                    <circle
                      cx="50"
                      cy="50"
                      r="40"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="8"
                      strokeDasharray={`${coverage.percentage * 2.51} 251`}
                      className="text-emerald-500"
                      strokeLinecap="round"
                    />
                  </svg>
                  <div className="absolute inset-0 flex items-center justify-center">
                    <span className="text-2xl font-bold">{coverage.percentage}%</span>
                  </div>
                </div>
              </div>
              <div className="mt-4 text-center text-sm text-gray-400">
                {coverage.covered} of {coverage.total} requirements covered
              </div>
            </div>

            {/* Quick Stats */}
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 rounded-xl bg-white/5 border border-white/10 text-center">
                <p className="text-3xl font-bold text-blue-400">{runs.length}</p>
                <p className="text-xs text-gray-500">Total Runs</p>
              </div>
              <div className="p-4 rounded-xl bg-white/5 border border-white/10 text-center">
                <p className="text-3xl font-bold text-green-400">
                  {runs.reduce((sum, r) => sum + r.passed, 0)}
                </p>
                <p className="text-xs text-gray-500">Tests Passed</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
