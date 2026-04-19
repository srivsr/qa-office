'use client'

import { useState, useRef, useEffect } from 'react'
import { useRouter } from 'next/navigation'

type InputMode = 'existing' | 'generate'

interface TestCase {
  requirement_id: string
  title: string
  description?: string
  technique?: string
  steps: string[]
  expected_result: string
  test_data?: Record<string, any>
}

interface TestResult {
  test_case_id: string
  title: string
  status: string
  technique?: string
  execution_time_ms?: number
  failure_reason?: string
  screenshot_url?: string
}

interface TestSession {
  session_id: string
  status: string
  message: string
  total_requirements: number
  total_test_cases: number
  download_url?: string
  summary?: {
    total: number
    passed: number
    failed: number
    pass_rate: string
    cost_usd?: number
    total_time_sec?: number
    generation_time_sec?: number
    execution_time_sec?: number
    tokens_input?: number
    tokens_output?: number
  }
}

interface SavedRun {
  id: string
  name: string
  environment: string
  status: string
  started_at: string | null
  finished_at: string | null
  summary: {
    total_test_cases?: number
    app_url?: string
    passed?: number
    failed?: number
    pass_rate?: string
  }
}

export default function ExecutePage() {
  const router = useRouter()
  const [appUrl, setAppUrl] = useState('')
  const [appName, setAppName] = useState('')

  // Mode: use existing test cases vs generate from requirements
  const [inputMode, setInputMode] = useState<InputMode>('existing')

  // Existing mode: file upload
  const [file, setFile] = useState<File | null>(null)

  // Generate mode: plain English description
  const [requirementsDescription, setRequirementsDescription] = useState('')

  const [maxWorkers, setMaxWorkers] = useState(4)
  const [parallel, setParallel] = useState(true)
  const [screenshots, setScreenshots] = useState(true)
  const [executionMode, setExecutionMode] = useState<'page_check' | 'scriptless' | 'scripted'>('page_check')
  const [openaiApiKey, setOpenaiApiKey] = useState('')

  // Authentication settings
  const [authEnabled, setAuthEnabled] = useState(false)
  const [authType, setAuthType] = useState<'clerk' | 'jwt' | 'ui'>('clerk')
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')

  const [loading, setLoading] = useState(false)
  const [session, setSession] = useState<TestSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [testCases, setTestCases] = useState<TestCase[]>([])
  const [results, setResults] = useState<TestResult[]>([])
  const [activeTab, setActiveTab] = useState<'summary' | 'testcases' | 'results'>('summary')
  const [expandedCase, setExpandedCase] = useState<number | null>(null)

  // Saved runs state
  const [savedRuns, setSavedRuns] = useState<SavedRun[]>([])
  const [showSavedRuns, setShowSavedRuns] = useState(false)
  const [loadingSavedRuns, setLoadingSavedRuns] = useState(false)
  const [rerunningId, setRerunningId] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const reqFileInputRef = useRef<HTMLInputElement>(null)
  const [reqFileName, setReqFileName] = useState<string | null>(null)

  useEffect(() => {
    fetchSavedRuns()
  }, [])

  const fetchSavedRuns = async () => {
    setLoadingSavedRuns(true)
    try {
      const res = await fetch('/api/v1/test-runner/saved-runs')
      if (res.ok) {
        const data = await res.json()
        setSavedRuns(data.runs || [])
      }
    } catch (err) {
      console.error('Failed to fetch saved runs:', err)
    } finally {
      setLoadingSavedRuns(false)
    }
  }

  const handleRerun = async (runId: string) => {
    setRerunningId(runId)
    setError(null)

    try {
      const formData = new FormData()
      if (appUrl) formData.append('app_url', appUrl)
      formData.append('parallel', String(parallel))
      formData.append('max_workers', String(maxWorkers))
      formData.append('headless', 'true')
      formData.append('auth_enabled', String(authEnabled))
      formData.append('auth_type', authType)
      if (authEmail) formData.append('auth_email', authEmail)
      if (authPassword) formData.append('auth_password', authPassword)

      const res = await fetch(`/api/v1/test-runner/rerun/${runId}`, {
        method: 'POST',
        body: formData
      })

      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Failed to start rerun')
      }

      const data: TestSession = await res.json()
      setSession(data)
      setShowSavedRuns(false)
      pollStatus(data.session_id)

    } catch (err: any) {
      setError(err.message || 'Failed to rerun tests')
    } finally {
      setRerunningId(null)
    }
  }

  useEffect(() => {
    if (session?.status === 'completed' && session?.session_id) {
      fetchTestCases(session.session_id)
      fetchResults(session.session_id)
    }
  }, [session?.status, session?.session_id])

  const fetchTestCases = async (sessionId: string) => {
    try {
      const res = await fetch(`/api/v1/test-runner/test-cases/${sessionId}`)
      if (res.ok) {
        const data = await res.json()
        setTestCases(data.test_cases || [])
      }
    } catch (err) {
      console.error('Failed to fetch test cases:', err)
    }
  }

  const fetchResults = async (sessionId: string) => {
    try {
      const res = await fetch(`/api/v1/test-runner/results/${sessionId}`)
      if (res.ok) {
        const data = await res.json()
        setResults(data.results || [])
      }
    } catch (err) {
      console.error('Failed to fetch results:', err)
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0])
    }
  }

  const handleSubmit = async () => {
    if (!appUrl) {
      setError('Application URL is required')
      return
    }

    if (inputMode === 'existing' && !file) {
      setError('Please upload a test cases file')
      return
    } else if (inputMode === 'generate' && !requirementsDescription.trim()) {
      setError('Please describe your requirements')
      return
    }

    setLoading(true)
    setError(null)
    setSession(null)

    try {
      const formData = new FormData()
      formData.append('app_url', appUrl)
      formData.append('app_name', appName || 'Application')
      formData.append('parallel', String(parallel))
      formData.append('max_workers', String(maxWorkers))
      formData.append('headless', 'true')
      formData.append('input_mode', inputMode)

      formData.append('auth_enabled', String(authEnabled))
      formData.append('auth_type', authType)
      if (authEmail) formData.append('auth_email', authEmail)
      if (authPassword) formData.append('auth_password', authPassword)

      formData.append('execution_mode', executionMode)
      if (openaiApiKey) formData.append('openai_api_key', openaiApiKey)

      if (inputMode === 'existing' && file) {
        formData.append('file', file)
      } else if (inputMode === 'generate') {
        formData.append('requirements_text', requirementsDescription.trim())
      }

      const res = await fetch('/api/v1/test-runner/run', {
        method: 'POST',
        body: formData
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `Server error ${res.status}: Failed to start test execution`)
      }

      const data = await res.json()
      router.push(`/run/${data.run_id}`)

    } catch (err: any) {
      setError(err.message || 'An error occurred')
    } finally {
      setLoading(false)
    }
  }

  const pollStatus = async (sessionId: string) => {
    const maxAttempts = 240
    let attempts = 0

    const poll = async () => {
      if (attempts >= maxAttempts) {
        setLoading(false)
        try {
          const runsRes = await fetch('/api/v1/test-runner/saved-runs')
          if (runsRes.ok) {
            const runsData = await runsRes.json()
            const completedRun = (runsData.runs || []).find((r: any) => r.id === sessionId)
            if (completedRun) {
              setError(null)
              setLoading(false)
              fetchSavedRuns()
              return
            }
          }
        } catch (_) {}
        setError('Run is taking longer than expected. Check "Saved Runs" — the backend may still complete shortly.')
        return
      }

      try {
        const res = await fetch(`/api/v1/test-runner/status/${sessionId}`)
        if (res.ok) {
          const data = await res.json()
          setSession(prev => prev ? { ...prev, ...data } : data)

          if (data.status === 'completed' || data.status === 'error' || data.status === 'failed') {
            setLoading(false)
            if (data.status === 'error' || data.status === 'failed') {
              setError(data.message || 'Test execution failed')
            }
            return
          }

          if (data.summary && data.summary.total > 0) {
            setLoading(false)
            return
          }
        } else {
          console.error('Status check failed:', res.status)
        }
      } catch (err) {
        console.error('Polling error:', err)
      }

      attempts++
      setTimeout(poll, 5000)
    }

    poll()
  }

  const handleDownload = async () => {
    if (session?.session_id) {
      try {
        const downloadUrl = session.download_url || `/api/v1/test-runner/download/${session.session_id}`
        const response = await fetch(downloadUrl)

        if (!response.ok) {
          throw new Error(`Download failed: ${response.status}`)
        }

        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `test_results_${session.session_id}.xlsx`
        document.body.appendChild(a)
        a.click()
        window.URL.revokeObjectURL(url)
        document.body.removeChild(a)
      } catch (error) {
        console.error('Download error:', error)
        alert('Failed to download Excel file')
      }
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white p-8">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold mb-2">End-to-End Test Runner</h1>
            <p className="text-gray-400">Execute automated tests with AI-powered analysis</p>
          </div>
          <button
            onClick={() => {
              setShowSavedRuns(!showSavedRuns)
              if (!showSavedRuns) fetchSavedRuns()
            }}
            className="px-4 py-2 rounded-lg bg-purple-500/20 border border-purple-500/50 text-purple-400 hover:bg-purple-500/30 transition-colors flex items-center gap-2"
          >
            <span>📚</span>
            {showSavedRuns ? 'Hide Saved Runs' : `Saved Runs (${savedRuns.length})`}
          </button>
        </div>

        {/* Saved Runs Panel */}
        {showSavedRuns && (
          <div className="mb-8 p-6 rounded-2xl bg-purple-500/10 border border-purple-500/30">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold flex items-center gap-2">
                <span>📚</span>
                Saved Test Runs
                <span className="text-sm font-normal text-gray-400">(Re-run without LLM cost!)</span>
              </h2>
              <button
                onClick={fetchSavedRuns}
                className="text-sm text-purple-400 hover:text-purple-300"
              >
                🔄 Refresh
              </button>
            </div>

            {loadingSavedRuns ? (
              <div className="text-center py-8">
                <div className="w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full animate-spin mx-auto mb-2"></div>
                <p className="text-gray-400">Loading saved runs...</p>
              </div>
            ) : savedRuns.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                <span className="text-4xl mb-2 block">📭</span>
                <p>No saved test runs yet.</p>
                <p className="text-sm">Run tests once to save them for future re-runs.</p>
              </div>
            ) : (
              <div className="space-y-3 max-h-80 overflow-y-auto">
                {savedRuns.map((run) => (
                  <div
                    key={run.id}
                    className="p-4 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-medium">{run.name}</span>
                          <span className={`text-xs px-2 py-0.5 rounded ${
                            run.status === 'completed'
                              ? 'bg-green-500/20 text-green-400'
                              : run.status === 'error'
                              ? 'bg-red-500/20 text-red-400'
                              : 'bg-yellow-500/20 text-yellow-400'
                          }`}>
                            {run.status}
                          </span>
                        </div>
                        <div className="text-sm text-gray-400 flex items-center gap-4">
                          <span>🧪 {run.summary?.total_test_cases || '?'} test cases</span>
                          <span>🌐 {run.environment}</span>
                          {run.started_at && (
                            <span>📅 {new Date(run.started_at).toLocaleDateString()}</span>
                          )}
                        </div>
                        {run.summary?.passed !== undefined && (
                          <div className="text-xs text-gray-500 mt-1">
                            ✅ {run.summary.passed} passed | ❌ {run.summary.failed} failed | {run.summary.pass_rate}
                          </div>
                        )}
                      </div>
                      <button
                        onClick={() => handleRerun(run.id)}
                        disabled={rerunningId === run.id}
                        className="px-4 py-2 rounded-lg bg-green-500 hover:bg-green-600 disabled:bg-gray-500 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors flex items-center gap-2"
                      >
                        {rerunningId === run.id ? (
                          <>
                            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                            Re-running...
                          </>
                        ) : (
                          <>
                            <span>🔄</span>
                            Re-run
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <p className="text-xs text-gray-500 mt-4 text-center">
              💡 Re-running uses saved test cases - no LLM generation cost!
            </p>
          </div>
        )}

        {/* Step 1: Target Application */}
        <div className="mb-8 p-6 rounded-2xl bg-white/5 border border-white/10">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-blue-500 text-center text-sm">1</span>
            Target Application
          </h2>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-2">Application URL *</label>
              <input
                type="url"
                value={appUrl}
                onChange={(e) => setAppUrl(e.target.value)}
                placeholder="https://app.example.com"
                className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-2">Application Name</label>
              <input
                type="text"
                value={appName}
                onChange={(e) => setAppName(e.target.value)}
                placeholder="My Application"
                className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>
        </div>

        {/* Step 2: Requirements Input */}
        <div className="mb-8 p-6 rounded-2xl bg-white/5 border border-white/10">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-blue-500 text-center text-sm">2</span>
            Requirements Input
          </h2>

          {/* Mode Selector */}
          <div className="flex gap-3 mb-6">
            {[
              { id: 'existing', icon: '📄', label: 'Use existing test cases', desc: 'Upload xlsx/csv/txt' },
              { id: 'generate', icon: '✨', label: 'Generate from requirements', desc: 'Type or upload .txt / .md' },
            ].map((mode) => (
              <button
                key={mode.id}
                onClick={() => setInputMode(mode.id as InputMode)}
                className={`flex-1 px-4 py-3 rounded-xl text-left transition-colors border ${
                  inputMode === mode.id
                    ? 'bg-blue-500/20 border-blue-500/50 text-blue-400'
                    : 'bg-white/5 border-white/10 text-gray-400 hover:bg-white/10'
                }`}
              >
                <div className="flex items-center gap-2 mb-0.5">
                  <span>{mode.icon}</span>
                  <span className="font-medium text-sm">{mode.label}</span>
                </div>
                <p className="text-xs text-gray-500 pl-6">{mode.desc}</p>
              </button>
            ))}
          </div>

          {/* Input based on mode */}
          {inputMode === 'existing' && (
            <div
              onClick={() => fileInputRef.current?.click()}
              className="border-2 border-dashed border-white/20 rounded-xl p-8 text-center cursor-pointer hover:border-blue-500/50 transition-colors"
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.csv,.txt"
                onChange={handleFileChange}
                className="hidden"
              />
              {file ? (
                <div>
                  <span className="text-4xl mb-2 block">📄</span>
                  <p className="text-white font-medium">{file.name}</p>
                  <p className="text-gray-500 text-sm">Click to change file</p>
                </div>
              ) : (
                <div>
                  <span className="text-4xl mb-2 block">📤</span>
                  <p className="text-gray-400">Drop files here or click to upload</p>
                  <p className="text-gray-500 text-sm mt-1">
                    Supports: Excel (.xlsx), CSV, Text (.txt)
                  </p>
                </div>
              )}
            </div>
          )}

          {inputMode === 'generate' && (
            <div className="space-y-3">
              {/* Upload requirements file */}
              <div className="flex items-center gap-3">
                <input
                  ref={reqFileInputRef}
                  type="file"
                  accept=".txt,.md"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (!f) return
                    setReqFileName(f.name)
                    const reader = new FileReader()
                    reader.onload = (ev) => setRequirementsDescription(ev.target?.result as string ?? '')
                    reader.readAsText(f)
                  }}
                />
                <button
                  type="button"
                  onClick={() => reqFileInputRef.current?.click()}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/5 border border-white/10 hover:bg-white/10 transition-colors text-sm text-gray-300"
                >
                  <span>📎</span> Upload requirements file
                </button>
                {reqFileName && (
                  <div className="flex items-center gap-2 text-sm text-blue-400">
                    <span>📄 {reqFileName}</span>
                    <button
                      type="button"
                      onClick={() => {
                        setReqFileName(null)
                        setRequirementsDescription('')
                        if (reqFileInputRef.current) reqFileInputRef.current.value = ''
                      }}
                      className="text-gray-500 hover:text-red-400 transition-colors"
                    >
                      ✕
                    </button>
                  </div>
                )}
              </div>

              {/* Textarea — populated by file or typed directly */}
              <textarea
                value={requirementsDescription}
                onChange={(e) => {
                  setRequirementsDescription(e.target.value)
                  if (reqFileName) setReqFileName(null)
                }}
                placeholder="Describe your requirements in plain English...&#10;&#10;Example:&#10;The app has a login page where users enter email and password. After login, they see a dashboard with their profile. There is a settings page to update name and email. Users can log out from the top nav."
                rows={8}
                className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 focus:border-blue-500 focus:outline-none resize-none"
              />
            </div>
          )}
        </div>

        {/* Step 3: Authentication (for protected apps) */}
        <div className="mb-8 p-6 rounded-2xl bg-white/5 border border-white/10">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-blue-500 text-center text-sm">3</span>
            Authentication
            <span className="text-xs text-gray-500 font-normal">(for protected apps like Clerk)</span>
          </h2>

          <label className="flex items-center gap-3 p-3 rounded-lg bg-white/5 border border-white/10 cursor-pointer hover:bg-white/10 transition-colors mb-4">
            <input
              type="checkbox"
              checked={authEnabled}
              onChange={(e) => setAuthEnabled(e.target.checked)}
              className="w-4 h-4"
            />
            <div>
              <span className="text-sm font-medium">Enable Authentication</span>
              <p className="text-xs text-gray-500">Login before running tests (required for Clerk-protected routes)</p>
            </div>
          </label>

          {authEnabled && (
            <div className="space-y-4 pl-4 border-l-2 border-blue-500/30">
              <div>
                <label className="block text-sm text-gray-400 mb-2">Auth Type</label>
                <div className="flex gap-2">
                  {[
                    { id: 'clerk', label: 'Clerk', desc: 'Clerk authentication' },
                    { id: 'jwt', label: 'JWT', desc: 'API login + token' },
                    { id: 'ui', label: 'Generic UI', desc: 'Form-based login' },
                  ].map((type) => (
                    <button
                      key={type.id}
                      onClick={() => setAuthType(type.id as any)}
                      className={`px-4 py-2 rounded-lg text-sm transition-colors ${
                        authType === type.id
                          ? 'bg-blue-500/20 border border-blue-500/50 text-blue-400'
                          : 'bg-white/5 border border-white/10 text-gray-400 hover:bg-white/10'
                      }`}
                    >
                      {type.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-2">Test User Email</label>
                  <input
                    type="email"
                    value={authEmail}
                    onChange={(e) => setAuthEmail(e.target.value)}
                    placeholder="test@example.com"
                    className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 focus:border-blue-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-2">Test User Password</label>
                  <input
                    type="password"
                    value={authPassword}
                    onChange={(e) => setAuthPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 focus:border-blue-500 focus:outline-none"
                  />
                </div>
              </div>

              <p className="text-xs text-gray-500">
                Create a test user in your {authType === 'clerk' ? 'Clerk dashboard' : 'application'} for automated testing.
              </p>
            </div>
          )}
        </div>

        {/* Step 4: Execution Configuration */}
        <div className="mb-8 p-6 rounded-2xl bg-white/5 border border-white/10">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-blue-500 text-center text-sm">4</span>
            Execution Configuration
          </h2>

          <div className="space-y-3">
            {/* Execution Mode */}
            <div className="p-3 rounded-lg bg-white/5 border border-white/10">
              <p className="text-sm text-gray-400 mb-3">Execution Engine</p>
              <div className="flex gap-2">
                {[
                  { id: 'page_check', icon: '⚡', label: 'Page Check', desc: 'Regex Playwright, no AI. Fast, no API key needed.' },
                  { id: 'scriptless', icon: '🤖', label: 'Scriptless AI', desc: 'AI reads DOM per step live. Needs OpenAI key.' },
                  { id: 'scripted',   icon: '📝', label: 'Scripted AI',  desc: 'AI generates .py script saved to disk. Needs OpenAI key.' },
                ].map((mode) => (
                  <button
                    key={mode.id}
                    onClick={() => setExecutionMode(mode.id as any)}
                    title={mode.desc}
                    className={`flex-1 px-3 py-2 rounded-xl text-left border transition-colors ${
                      executionMode === mode.id
                        ? 'bg-blue-500/20 border-blue-500/50 text-blue-400'
                        : 'bg-white/5 border-white/10 text-gray-400 hover:bg-white/10'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-0.5">
                      <span>{mode.icon}</span>
                      <span className="font-medium text-sm">{mode.label}</span>
                    </div>
                    <p className="text-xs text-gray-500 pl-5">{mode.desc}</p>
                  </button>
                ))}
              </div>

              {(executionMode === 'scriptless' || executionMode === 'scripted') && (
                <div className="mt-3 pl-1">
                  <label className="block text-xs text-gray-400 mb-1">OpenAI API Key *</label>
                  <input
                    type="password"
                    value={openaiApiKey}
                    onChange={(e) => setOpenaiApiKey(e.target.value)}
                    placeholder="sk-..."
                    className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 focus:border-blue-500 focus:outline-none text-sm"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Required for {executionMode} mode. Not stored — sent only for this run.
                  </p>
                </div>
              )}
            </div>

            {/* Parallel Execution */}
            <label className="flex items-center gap-3 p-3 rounded-lg bg-white/5 border border-white/10 cursor-pointer hover:bg-white/10 transition-colors">
              <input
                type="checkbox"
                checked={parallel}
                onChange={(e) => setParallel(e.target.checked)}
                className="w-4 h-4"
              />
              <span className="text-sm">Parallel Execution</span>
            </label>

            {parallel && (
              <div className="ml-7 p-3 rounded-lg bg-blue-500/10 border border-blue-500/30">
                <label className="block text-xs text-gray-400 mb-2">Max Workers (1-10)</label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min="1"
                    max="10"
                    value={maxWorkers}
                    onChange={(e) => setMaxWorkers(Number(e.target.value))}
                    className="flex-1"
                  />
                  <span className="text-sm font-medium text-blue-400 w-6">{maxWorkers}</span>
                </div>
                <p className="text-xs text-gray-500 mt-1">Run up to {maxWorkers} tests simultaneously</p>
              </div>
            )}

            {/* Capture Screenshots */}
            <label className="flex items-center gap-3 p-3 rounded-lg bg-white/5 border border-white/10 cursor-pointer hover:bg-white/10 transition-colors">
              <input
                type="checkbox"
                checked={screenshots}
                onChange={(e) => setScreenshots(e.target.checked)}
                className="w-4 h-4"
              />
              <span className="text-sm">Capture Screenshots</span>
            </label>
          </div>
        </div>

        {/* Error Message */}
        {error && (
          <div className="mb-4 p-4 rounded-xl bg-red-500/20 border border-red-500/50 text-red-400">
            {error}
          </div>
        )}

        {/* Session Status */}
        {session && (
          <div className="mb-4 p-6 rounded-2xl bg-white/5 border border-white/10">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                {session.status === 'completed' ? (
                  <span className="text-2xl">✅</span>
                ) : session.status === 'error' ? (
                  <span className="text-2xl">❌</span>
                ) : (
                  <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                )}
                <div>
                  <p className="font-semibold capitalize">{session.status}</p>
                  <p className="text-sm text-gray-400">
                    {session.total_requirements} requirements | {session.total_test_cases} test cases
                  </p>
                </div>
              </div>

              {session.status === 'completed' && (
                <div className="flex items-center gap-3">
                  {session.summary?.cost_usd != null && (
                    <div className="text-xs text-center">
                      <p className="text-yellow-400 font-semibold">${session.summary.cost_usd.toFixed(4)}</p>
                      <p className="text-gray-500">AI Cost</p>
                    </div>
                  )}
                  {session.summary?.total_time_sec != null && (
                    <div className="text-xs text-center">
                      <p className="text-cyan-400 font-semibold">{session.summary.total_time_sec}s</p>
                      <p className="text-gray-500">Total Time</p>
                    </div>
                  )}
                  <button
                    onClick={handleDownload}
                    className="px-4 py-2 rounded-lg bg-green-500 hover:bg-green-600 text-white font-medium transition-colors flex items-center gap-2"
                  >
                    <span>📥</span> Download Excel
                  </button>
                </div>
              )}
            </div>

            {session.summary && (
              <div className="grid grid-cols-4 gap-4 mb-4 p-4 rounded-xl bg-white/5">
                <div className="text-center">
                  <p className="text-2xl font-bold">{session.summary.total}</p>
                  <p className="text-xs text-gray-500">Total</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-green-400">{session.summary.passed}</p>
                  <p className="text-xs text-gray-500">Passed</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-red-400">{session.summary.failed}</p>
                  <p className="text-xs text-gray-500">Failed</p>
                </div>
                <div className="text-center">
                  <p className="text-2xl font-bold text-blue-400">{session.summary.pass_rate}</p>
                  <p className="text-xs text-gray-500">Pass Rate</p>
                </div>
              </div>
            )}

            {session.status === 'completed' && (
              <>
                <div className="flex gap-2 mb-4 border-b border-white/10 pb-2">
                  {[
                    { id: 'summary', label: 'Summary', icon: '📊' },
                    { id: 'testcases', label: `Test Cases (${testCases.length})`, icon: '🧪' },
                    { id: 'results', label: `Results (${results.length})`, icon: '📋' },
                  ].map((tab) => (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id as any)}
                      className={`px-4 py-2 rounded-lg text-sm flex items-center gap-2 transition-colors ${
                        activeTab === tab.id
                          ? 'bg-blue-500/20 text-blue-400'
                          : 'text-gray-400 hover:bg-white/5'
                      }`}
                    >
                      <span>{tab.icon}</span>
                      {tab.label}
                    </button>
                  ))}
                </div>

                {activeTab === 'testcases' && (
                  <div className="max-h-96 overflow-y-auto space-y-2">
                    {testCases.length === 0 ? (
                      <p className="text-gray-500 text-center py-4">No test cases available</p>
                    ) : (
                      testCases.map((tc, idx) => (
                        <div
                          key={idx}
                          className="p-3 rounded-lg bg-white/5 border border-white/10 cursor-pointer hover:bg-white/10"
                          onClick={() => setExpandedCase(expandedCase === idx ? null : idx)}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="text-xs px-2 py-1 rounded bg-blue-500/20 text-blue-400">
                                {tc.requirement_id}
                              </span>
                              <span className="font-medium text-sm">{tc.title}</span>
                            </div>
                            <span className="text-xs px-2 py-1 rounded bg-purple-500/20 text-purple-400">
                              {tc.technique || 'general'}
                            </span>
                          </div>

                          {expandedCase === idx && (
                            <div className="mt-3 pt-3 border-t border-white/10 text-sm">
                              {tc.description && (
                                <p className="text-gray-400 mb-2">{tc.description}</p>
                              )}
                              <div className="mb-2">
                                <p className="text-gray-500 text-xs mb-1">Steps:</p>
                                <ol className="list-decimal list-inside text-gray-300 space-y-1">
                                  {tc.steps?.map((step, i) => (
                                    <li key={i}>{step}</li>
                                  ))}
                                </ol>
                              </div>
                              <div>
                                <p className="text-gray-500 text-xs mb-1">Expected Result:</p>
                                <p className="text-gray-300">{tc.expected_result}</p>
                              </div>
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                )}

                {activeTab === 'results' && (
                  <div className="max-h-96 overflow-y-auto space-y-2">
                    {results.length === 0 ? (
                      <p className="text-gray-500 text-center py-4">No results available</p>
                    ) : (
                      results.map((r, idx) => (
                        <div
                          key={idx}
                          className={`p-3 rounded-lg border ${
                            r.status === 'passed' || r.status === 'pass'
                              ? 'bg-green-500/10 border-green-500/30'
                              : 'bg-red-500/10 border-red-500/30'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 flex-1 min-w-0">
                              {r.technique && (
                                <span className="text-xs px-2 py-1 rounded bg-purple-500/20 text-purple-400 shrink-0">
                                  {r.technique}
                                </span>
                              )}
                              <span className="font-medium text-sm truncate">{r.title || r.test_case_id}</span>
                            </div>
                            <div className="flex items-center gap-2 shrink-0 ml-2">
                              {r.execution_time_ms && (
                                <span className="text-xs text-gray-500">{r.execution_time_ms}ms</span>
                              )}
                              <span className={`text-xs px-2 py-1 rounded font-medium ${
                                r.status === 'passed' || r.status === 'pass'
                                  ? 'bg-green-500/20 text-green-400'
                                  : 'bg-red-500/20 text-red-400'
                              }`}>
                                {r.status.toUpperCase()}
                              </span>
                            </div>
                          </div>
                          {r.failure_reason && (
                            <p className="text-red-400 text-xs mt-2">{r.failure_reason}</p>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                )}

                {activeTab === 'summary' && (() => {
                  const TECHNIQUE_META: Record<string, { label: string; color: string }> = {
                    positive:              { label: 'EP Positive',  color: 'bg-green-500/20 text-green-400 border-green-500/30' },
                    ep_positive:           { label: 'EP Positive',  color: 'bg-green-500/20 text-green-400 border-green-500/30' },
                    equivalence_partition: { label: 'EP Negative',  color: 'bg-orange-500/20 text-orange-400 border-orange-500/30' },
                    ep_negative:           { label: 'EP Negative',  color: 'bg-orange-500/20 text-orange-400 border-orange-500/30' },
                    negative:              { label: 'Negative',     color: 'bg-red-500/20 text-red-400 border-red-500/30' },
                    boundary:              { label: 'BVA',          color: 'bg-blue-500/20 text-blue-400 border-blue-500/30' },
                    bva:                   { label: 'BVA',          color: 'bg-blue-500/20 text-blue-400 border-blue-500/30' },
                    security:              { label: 'Security',     color: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' },
                    usability:             { label: 'Usability',    color: 'bg-purple-500/20 text-purple-400 border-purple-500/30' },
                    ctd:                   { label: 'CTD',          color: 'bg-pink-500/20 text-pink-400 border-pink-500/30' },
                  }

                  const counts: Record<string, number> = {}
                  testCases.forEach(tc => {
                    const key = (tc.technique || 'general').toLowerCase()
                    counts[key] = (counts[key] || 0) + 1
                  })

                  const passByTechnique: Record<string, number> = {}
                  results.forEach(r => {
                    const key = (r.technique || 'general').toLowerCase()
                    if (r.status === 'passed' || r.status === 'pass') {
                      passByTechnique[key] = (passByTechnique[key] || 0) + 1
                    }
                  })

                  const total = testCases.length || 1

                  return (
                    <div className="space-y-3">
                      {session.summary?.total_time_sec != null && (
                        <div className="grid grid-cols-4 gap-2 p-3 rounded-lg bg-white/5 border border-white/10 mb-4">
                          <div className="text-center">
                            <p className="text-sm font-semibold text-cyan-400">{session.summary.generation_time_sec}s</p>
                            <p className="text-xs text-gray-500">AI Generation</p>
                          </div>
                          <div className="text-center">
                            <p className="text-sm font-semibold text-blue-400">{session.summary.execution_time_sec}s</p>
                            <p className="text-xs text-gray-500">Test Execution</p>
                          </div>
                          <div className="text-center">
                            <p className="text-sm font-semibold text-purple-400">{(session.summary.tokens_input || 0) + (session.summary.tokens_output || 0)}</p>
                            <p className="text-xs text-gray-500">Tokens Used</p>
                          </div>
                          <div className="text-center">
                            <p className="text-sm font-semibold text-yellow-400">${(session.summary.cost_usd || 0).toFixed(4)}</p>
                            <p className="text-xs text-gray-500">Cost</p>
                          </div>
                        </div>
                      )}
                      <p className="text-sm text-gray-400 mb-3">Test cases by technique:</p>
                      {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([key, count]) => {
                        const meta = TECHNIQUE_META[key] || { label: key, color: 'bg-gray-500/20 text-gray-400 border-gray-500/30' }
                        const passed = passByTechnique[key] || 0
                        const pct = Math.round((count / total) * 100)
                        return (
                          <div key={key}>
                            <div className="flex items-center justify-between mb-1">
                              <span className={`text-xs px-2 py-1 rounded border ${meta.color}`}>{meta.label}</span>
                              <span className="text-xs text-gray-400">
                                {count} tests {results.length > 0 && `· ${passed} passed`}
                              </span>
                            </div>
                            <div className="w-full bg-white/10 rounded-full h-1.5">
                              <div className="bg-blue-500 h-1.5 rounded-full transition-all" style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        )
                      })}
                      {Object.keys(counts).length === 0 && (
                        <p className="text-gray-500 text-center py-4 text-sm">No test case data yet</p>
                      )}
                    </div>
                  )
                })()}
              </>
            )}
          </div>
        )}

        {/* Submit Button */}
        <button
          onClick={handleSubmit}
          disabled={loading}
          className="w-full py-4 rounded-xl bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-600 hover:to-cyan-600 disabled:opacity-50 disabled:cursor-not-allowed font-semibold text-lg transition-all"
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
              Running Tests...
            </span>
          ) : (
            '🚀 Start Test Run'
          )}
        </button>
      </div>
    </div>
  )
}
