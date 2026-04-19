'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useRouter } from 'next/navigation'

// ── Pipeline stage definitions ─────────────────────────────────────────────────

const PIPELINE_STAGES = [
  { key: 'generating',      label: 'Generating Test Cases', agent: 'A0',     generateOnly: true },
  { key: 'env_check',       label: 'Environment Check',     agent: 'A13' },
  { key: 'planning',        label: 'Planning',               agent: 'A10' },
  { key: 'seeding',         label: 'Data Seeding',           agent: 'A12' },
  { key: 'ingestion',       label: 'Ingestion',              agent: 'A1' },
  { key: 'intent',          label: 'Intent Analysis',        agent: 'A2+A3' },
  { key: 'executing',       label: 'Executing',              agent: 'A4' },
  { key: 'failure_analysis',label: 'Failure Analysis',       agent: 'A5+A6' },
  { key: 'reporting',       label: 'Building Report',        agent: 'A8' },
  { key: 'reflection',      label: 'Reflection',             agent: 'A10' },
] as const

type StageKey = typeof PIPELINE_STAGES[number]['key']
type StageStatus = 'waiting' | 'running' | 'complete' | 'error'

const STAGE_ORDER: StageKey[] = PIPELINE_STAGES.map(s => s.key)

// ── Types ──────────────────────────────────────────────────────────────────────

interface ReviewRequest {
  run_id: string
  test_case_id: string
  source_agent: string
  reason: string
  confidence?: number
  description?: string
}

interface RunStatus {
  run_id: string
  status: string
  stage: string
  sub_stage: string | null
  message: string | null
  total_test_cases: number
  passed: number
  failed: number
  pass_rate: string | null
  paused_count: number
  review_request: ReviewRequest | null
  download_url: string | null
  summary: {
    total: number
    passed: number
    failed: number
    pass_rate: string
    paused_count: number
    patterns: string[]
    alerts: Array<{ alert_type: string; module: string; signal: string; severity: string; recommendation: string }>
  } | null
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function getStageStatus(key: StageKey, subStage: string | null, overallStage: string): StageStatus {
  if (overallStage === 'complete') return 'complete'
  if (overallStage === 'error' && subStage === key) return 'error'

  const currentIdx = STAGE_ORDER.indexOf(subStage as StageKey)
  const thisIdx = STAGE_ORDER.indexOf(key)

  if (currentIdx < 0) return 'waiting'
  if (thisIdx < currentIdx) return 'complete'
  if (thisIdx === currentIdx) return 'running'
  return 'waiting'
}

// ── Stage icon ─────────────────────────────────────────────────────────────────

function StageIcon({ status }: { status: StageStatus }) {
  if (status === 'complete') {
    return (
      <div className="w-8 h-8 rounded-full bg-green-500/20 border-2 border-green-500 flex items-center justify-center shrink-0">
        <svg className="w-4 h-4 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
        </svg>
      </div>
    )
  }
  if (status === 'error') {
    return (
      <div className="w-8 h-8 rounded-full bg-red-500/20 border-2 border-red-500 flex items-center justify-center shrink-0">
        <svg className="w-4 h-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </div>
    )
  }
  if (status === 'running') {
    return (
      <div className="w-8 h-8 rounded-full bg-blue-500/20 border-2 border-blue-500 flex items-center justify-center shrink-0">
        <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }
  return (
    <div className="w-8 h-8 rounded-full bg-white/5 border-2 border-white/20 flex items-center justify-center shrink-0">
      <div className="w-2 h-2 rounded-full bg-white/30" />
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function RunPage() {
  const params = useParams()
  const router = useRouter()
  const runId = params?.id as string

  const [status, setStatus] = useState<RunStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reviewing, setReviewing] = useState(false)
  const [reviewError, setReviewError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchStatus = useCallback(async (): Promise<RunStatus | null> => {
    if (!runId) return null
    try {
      const res = await fetch(`/api/v1/test-runner/status/${runId}`)
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.detail || `Error ${res.status}`)
        return null
      }
      const data: RunStatus = await res.json()
      setStatus(data)
      setError(null)
      return data
    } catch (err: any) {
      setError(err.message || 'Failed to fetch status')
      return null
    }
  }, [runId])

  // Poll every 2s while run is active
  useEffect(() => {
    let cancelled = false

    const schedule = async () => {
      const data = await fetchStatus()
      if (!cancelled && data && !['completed', 'error'].includes(data.status)) {
        pollRef.current = setTimeout(schedule, 2000)
      }
    }

    schedule()

    return () => {
      cancelled = true
      if (pollRef.current) clearTimeout(pollRef.current)
    }
  }, [fetchStatus])

  const submitReview = async (decision: string, agentTarget?: string) => {
    if (!runId) return
    setReviewing(true)
    setReviewError(null)
    try {
      const res = await fetch(`/api/v1/test-runner/review/${runId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, agent_target: agentTarget }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setReviewError(data.detail || 'Failed to submit review')
        return
      }
      await fetchStatus()
    } catch (err: any) {
      setReviewError(err.message || 'Failed to submit review')
    } finally {
      setReviewing(false)
    }
  }

  const isTerminal = status?.status === 'completed' || status?.status === 'error'
  const isHitlPending = status?.stage === 'hitl_pending'
  const subStage = status?.sub_stage ?? null
  const overallStage = status?.stage ?? 'queued'

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white p-8">
      <div className="max-w-3xl mx-auto">

        {/* Header */}
        <div className="mb-8 flex items-start justify-between">
          <div>
            <button
              onClick={() => router.back()}
              className="text-gray-500 hover:text-gray-300 text-sm mb-3 flex items-center gap-1 transition-colors"
            >
              ← Back
            </button>
            <h1 className="text-2xl font-bold mb-1">Run Pipeline</h1>
            <p className="text-gray-500 text-sm font-mono">{runId}</p>
          </div>
          {isTerminal && status?.status === 'completed' && status.download_url && (
            <a
              href={status.download_url}
              className="px-4 py-2 rounded-lg bg-green-500 hover:bg-green-600 text-white text-sm font-medium transition-colors flex items-center gap-2"
            >
              <span>📥</span> Download Report
            </a>
          )}
        </div>

        {/* Fetch error */}
        {error && (
          <div className="mb-6 p-4 rounded-xl bg-red-500/20 border border-red-500/50 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* ── SECTION 1: Live Pipeline View ─────────────────────────────────── */}
        <div className="mb-6 p-6 rounded-2xl bg-white/5 border border-white/10">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <span>⚡</span> Pipeline
            </h2>
            {status && (
              <span className={`text-xs px-3 py-1 rounded-full font-medium ${
                status.status === 'completed' ? 'bg-green-500/20 text-green-400 border border-green-500/30' :
                status.status === 'error'     ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                status.status === 'hitl_pending' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' :
                'bg-blue-500/20 text-blue-400 border border-blue-500/30'
              }`}>
                {status.status === 'hitl_pending' ? '⏸ Awaiting Review' :
                 status.status === 'completed'    ? '✓ Complete' :
                 status.status === 'error'        ? '✗ Failed' :
                 '● Running'}
              </span>
            )}
          </div>

          {/* Timeline */}
          <div className="relative">
            {/* Vertical connector line */}
            <div className="absolute left-[15px] top-4 bottom-4 w-0.5 bg-white/10" />

            <div className="space-y-0">
              {PIPELINE_STAGES.map((stage, idx) => {
                const stageStatus = getStageStatus(stage.key, subStage, overallStage)
                const isLast = idx === PIPELINE_STAGES.length - 1

                return (
                  <div key={stage.key} className="relative flex items-start gap-4 py-3">
                    {/* Icon sits on the line */}
                    <div className="relative z-10">
                      <StageIcon status={stageStatus} />
                    </div>

                    {/* Label */}
                    <div className={`flex-1 pt-1 ${stageStatus === 'waiting' ? 'opacity-40' : ''}`}>
                      <div className="flex items-center gap-2">
                        <span className={`text-sm font-medium ${
                          stageStatus === 'complete' ? 'text-green-400' :
                          stageStatus === 'running'  ? 'text-blue-300' :
                          stageStatus === 'error'    ? 'text-red-400' :
                          'text-gray-400'
                        }`}>
                          {stage.label}
                        </span>
                        <span className="text-xs text-gray-600 font-mono">{stage.agent}</span>
                        {(stage as any).generateOnly && (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400">generate mode</span>
                        )}
                      </div>
                      {stageStatus === 'running' && (
                        <p className="text-xs text-blue-400/70 mt-0.5 animate-pulse">Processing…</p>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Live counts */}
          {status && (status.total_test_cases > 0 || status.passed > 0 || status.failed > 0) && (
            <div className="mt-6 grid grid-cols-3 gap-3 pt-4 border-t border-white/10">
              <div className="text-center p-3 rounded-xl bg-white/5">
                <p className="text-2xl font-bold">{status.total_test_cases}</p>
                <p className="text-xs text-gray-500 mt-0.5">Total</p>
              </div>
              <div className="text-center p-3 rounded-xl bg-green-500/10">
                <p className="text-2xl font-bold text-green-400">{status.passed}</p>
                <p className="text-xs text-gray-500 mt-0.5">Passed</p>
              </div>
              <div className="text-center p-3 rounded-xl bg-red-500/10">
                <p className="text-2xl font-bold text-red-400">{status.failed}</p>
                <p className="text-xs text-gray-500 mt-0.5">Failed</p>
              </div>
            </div>
          )}

          {/* Error message */}
          {status?.status === 'error' && status.message && (
            <div className="mt-4 p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
              {status.message}
            </div>
          )}

          {/* Complete summary */}
          {status?.status === 'completed' && status.summary && (
            <div className="mt-4 space-y-3">
              {status.summary.pass_rate && (
                <div className="p-3 rounded-xl bg-green-500/10 border border-green-500/20 flex items-center justify-between">
                  <span className="text-sm text-green-300 font-medium">Pass Rate</span>
                  <span className="text-lg font-bold text-green-400">{status.summary.pass_rate}</span>
                </div>
              )}
              {status.summary.patterns?.length > 0 && (
                <div className="p-3 rounded-xl bg-white/5 border border-white/10">
                  <p className="text-xs text-gray-400 mb-2 font-medium">Patterns Detected</p>
                  <ul className="space-y-1">
                    {status.summary.patterns.map((p, i) => (
                      <li key={i} className="text-xs text-gray-300 flex items-start gap-1.5">
                        <span className="text-blue-400 mt-0.5">•</span> {p}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {status.summary.alerts?.length > 0 && (
                <div className="p-3 rounded-xl bg-yellow-500/10 border border-yellow-500/20">
                  <p className="text-xs text-yellow-400 mb-2 font-medium">⚠ Proactive Alerts</p>
                  {status.summary.alerts.map((a, i) => (
                    <div key={i} className="mb-2 last:mb-0">
                      <p className="text-xs font-medium text-yellow-300">[{a.severity.toUpperCase()}] {a.module}</p>
                      <p className="text-xs text-gray-400">{a.signal}</p>
                      {a.recommendation && (
                        <p className="text-xs text-gray-500 mt-0.5">→ {a.recommendation}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── SECTION 2: HITL Review Panel ──────────────────────────────────── */}
        {isHitlPending && status?.review_request && (
          <div className="p-6 rounded-2xl bg-yellow-500/10 border border-yellow-500/30">
            <h2 className="text-lg font-semibold mb-1 flex items-center gap-2 text-yellow-300">
              <span>⏸</span> Human Review Required
            </h2>
            <p className="text-xs text-gray-500 mb-5">
              The pipeline is paused. Review the details below and choose an action.
            </p>

            {/* Review details card */}
            <div className="p-4 rounded-xl bg-white/5 border border-white/10 mb-5 space-y-3">

              {/* Test case */}
              <div className="flex items-start gap-3">
                <span className="text-xs text-gray-500 w-24 shrink-0 pt-0.5">Test Case</span>
                <span className="text-sm font-mono text-blue-300">
                  {status.review_request.test_case_id}
                </span>
              </div>

              {/* Description if present */}
              {status.review_request.description && (
                <div className="flex items-start gap-3">
                  <span className="text-xs text-gray-500 w-24 shrink-0 pt-0.5">Description</span>
                  <span className="text-sm text-gray-300">{status.review_request.description}</span>
                </div>
              )}

              {/* Source agent */}
              <div className="flex items-start gap-3">
                <span className="text-xs text-gray-500 w-24 shrink-0 pt-0.5">Triggered By</span>
                <span className="text-xs px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 font-mono">
                  {status.review_request.source_agent}
                </span>
              </div>

              {/* Confidence */}
              {status.review_request.confidence != null && (
                <div className="flex items-start gap-3">
                  <span className="text-xs text-gray-500 w-24 shrink-0 pt-0.5">Confidence</span>
                  <div className="flex items-center gap-2">
                    <div className="w-24 h-1.5 bg-white/10 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-yellow-400"
                        style={{ width: `${Math.round((status.review_request.confidence ?? 0) * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-yellow-300 font-mono">
                      {Math.round((status.review_request.confidence ?? 0) * 100)}%
                    </span>
                  </div>
                </div>
              )}

              {/* Reason */}
              <div className="flex items-start gap-3">
                <span className="text-xs text-gray-500 w-24 shrink-0 pt-0.5">Reason</span>
                <span className="text-sm text-gray-300">{status.review_request.reason}</span>
              </div>
            </div>

            {/* Review error */}
            {reviewError && (
              <div className="mb-4 p-3 rounded-xl bg-red-500/20 border border-red-500/40 text-red-400 text-sm">
                {reviewError}
              </div>
            )}

            {/* Action buttons */}
            <div className="flex gap-3">
              <button
                onClick={() => submitReview('approve')}
                disabled={reviewing}
                className="flex-1 py-3 rounded-xl bg-green-500 hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold text-sm transition-colors flex items-center justify-center gap-2"
              >
                {reviewing ? (
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : (
                  <span>✓</span>
                )}
                Approve
              </button>

              <button
                onClick={() => submitReview('reject')}
                disabled={reviewing}
                className="flex-1 py-3 rounded-xl bg-red-500/20 border border-red-500/50 hover:bg-red-500/30 disabled:opacity-50 disabled:cursor-not-allowed text-red-400 font-semibold text-sm transition-colors flex items-center justify-center gap-2"
              >
                <span>✗</span>
                Reject
              </button>

              <button
                onClick={() => submitReview('back', 'A2')}
                disabled={reviewing}
                className="flex-1 py-3 rounded-xl bg-purple-500/20 border border-purple-500/50 hover:bg-purple-500/30 disabled:opacity-50 disabled:cursor-not-allowed text-purple-400 font-semibold text-sm transition-colors flex items-center justify-center gap-2"
              >
                <span>↩</span>
                Send back to Intent Analysis
              </button>
            </div>
          </div>
        )}

        {/* Loading state — no status yet */}
        {!status && !error && (
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
              <p className="text-gray-500 text-sm">Loading run status…</p>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
