'use client'

import { useState, useRef } from 'react'
import Link from 'next/link'

interface TestSession {
  session_id: string
  status: string
  message: string
  total_requirements: number
  total_test_cases: number
  download_url?: string
  results_summary?: {
    total: number
    passed: number
    failed: number
    pass_rate: string
  }
}

interface TestRunnerProps {
  onClose?: () => void
}

type ExecutionMode = 'page_check' | 'scriptless' | 'scripted'

export default function TestRunner({ onClose }: TestRunnerProps) {
  const [appUrl, setAppUrl] = useState('')
  const [appName, setAppName] = useState('')
  const [requirementsText, setRequirementsText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [session, setSession] = useState<TestSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [parallel, setParallel] = useState(true)
  const [embedScreenshots, setEmbedScreenshots] = useState(false)
  const [executionMode, setExecutionMode] = useState<ExecutionMode>('page_check')
  const [openaiApiKey, setOpenaiApiKey] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0])
      setRequirementsText('') // Clear text when file is selected
    }
  }

  const handleRun = async () => {
    if (!appUrl) {
      setError('Please enter the application URL')
      return
    }

    if (!file && !requirementsText.trim()) {
      setError('Please upload a requirements file or enter requirements text')
      return
    }

    setIsLoading(true)
    setError(null)
    setSession(null)

    try {
      const formData = new FormData()
      formData.append('app_url', appUrl)
      formData.append('app_name', appName || 'Application')
      formData.append('parallel', parallel.toString())
      formData.append('embed_screenshots', embedScreenshots.toString())
      formData.append('execution_mode', executionMode)
      formData.append('headless', 'true')
      if (openaiApiKey) formData.append('openai_api_key', openaiApiKey)

      if (file) {
        formData.append('file', file)
      } else {
        formData.append('requirements_text', requirementsText)
      }

      const response = await fetch('/api/v1/test-runner/run', {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Test execution failed')
      }

      const data: TestSession = await response.json()
      setSession(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }

  const handleDownload = async () => {
    if (!session?.session_id) return

    try {
      const response = await fetch(`/api/v1/test-runner/download/${session.session_id}`)
      if (!response.ok) throw new Error('Download failed')

      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${appName.replace(/\s/g, '_')}_test_results.xlsx`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch (err: any) {
      setError(err.message)
    }
  }

  const sampleRequirements = `REQ-001: Landing Page
- Hero section displays correctly
- Login button is clickable
- Navigation links work

REQ-002: User Dashboard
- Stats cards show correct data
- Recent activity is displayed
- Charts render properly

REQ-003: Chat Feature
- Message input works
- AI responses are received
- Conversation history loads`

  return (
    <div className="bg-gray-800 rounded-lg p-6 max-w-4xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-xl font-bold text-white">Quick Test Runner</h2>
          <p className="text-gray-400 text-sm">
            Run tests quickly. <Link href="/execute" className="text-blue-400 hover:underline">Open full page</Link> for more options.
          </p>
        </div>
        {onClose && (
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl">
            ✕
          </button>
        )}
      </div>

      {/* App Configuration */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        <div>
          <label className="block text-sm text-gray-400 mb-1">Application URL</label>
          <input
            type="text"
            value={appUrl}
            onChange={(e) => setAppUrl(e.target.value)}
            placeholder="http://localhost:3001"
            className="w-full px-3 py-2 bg-gray-700 rounded text-white"
          />
        </div>
        <div>
          <label className="block text-sm text-gray-400 mb-1">Application Name</label>
          <input
            type="text"
            value={appName}
            onChange={(e) => setAppName(e.target.value)}
            placeholder="My Application"
            className="w-full px-3 py-2 bg-gray-700 rounded text-white"
          />
        </div>
      </div>

      {/* Requirements Input */}
      <div className="mb-6">
        <label className="block text-sm text-gray-400 mb-2">Requirements</label>

        {/* File Upload */}
        <div className="flex items-center gap-4 mb-3">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".xlsx,.xls,.json,.pdf,.txt,.md,.docx,.doc"
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-4 py-2 bg-gray-700 text-white rounded hover:bg-gray-600 flex items-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            Upload Requirements File
          </button>
          {file && (
            <span className="text-green-400">
              ✓ {file.name}
            </span>
          )}
          <span className="text-gray-500 text-sm">
            (Excel, Word, JSON, PDF, or Text)
          </span>
        </div>

        {/* Or text input */}
        <div className="text-gray-500 text-sm mb-2">— OR enter requirements below —</div>

        <textarea
          value={requirementsText}
          onChange={(e) => {
            setRequirementsText(e.target.value)
            setFile(null) // Clear file when text is entered
          }}
          placeholder={sampleRequirements}
          rows={8}
          className="w-full px-3 py-2 bg-gray-700 rounded text-white font-mono text-sm"
        />

        <button
          onClick={() => setRequirementsText(sampleRequirements)}
          className="mt-2 text-sm text-blue-400 hover:text-blue-300"
        >
          Load sample requirements
        </button>
      </div>

      {/* Options */}
      <div className="mb-6">
        <label className="block text-sm text-gray-400 mb-2">Execution Mode</label>
        <div className="flex gap-3 mb-4">
          {[
            { id: 'page_check', label: '⚡ Page Check', desc: 'Regex Playwright, no AI (fastest)' },
            { id: 'scriptless',  label: '🤖 Scriptless AI', desc: 'AI reads DOM per step live' },
            { id: 'scripted',    label: '📝 Scripted AI', desc: 'AI generates .py script to disk' },
          ].map((mode) => (
            <button
              key={mode.id}
              title={mode.desc}
              onClick={() => setExecutionMode(mode.id as ExecutionMode)}
              className={`px-4 py-2 rounded-lg text-sm transition-colors ${
                executionMode === mode.id
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              {mode.label}
            </button>
          ))}
        </div>
        {(executionMode === 'scriptless' || executionMode === 'scripted') && (
          <div className="mb-3">
            <label className="block text-xs text-gray-400 mb-1">OpenAI API Key *</label>
            <input
              type="password"
              value={openaiApiKey}
              onChange={(e) => setOpenaiApiKey(e.target.value)}
              placeholder="sk-..."
              className="w-full px-3 py-2 bg-gray-700 rounded text-white text-sm"
            />
            <p className="text-xs text-gray-500 mt-1">Required for {executionMode} mode.</p>
          </div>
        )}
        <div className="flex gap-6">
          <label className="flex items-center gap-2 text-gray-300">
            <input
              type="checkbox"
              checked={parallel}
              onChange={(e) => setParallel(e.target.checked)}
              className="rounded"
            />
            Parallel Execution
          </label>
          <label className="flex items-center gap-2 text-gray-300">
            <input
              type="checkbox"
              checked={embedScreenshots}
              onChange={(e) => setEmbedScreenshots(e.target.checked)}
              className="rounded"
            />
            Embed Screenshots in Excel
          </label>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-900/50 border border-red-500 text-red-200 px-4 py-3 rounded mb-4">
          {error}
        </div>
      )}

      {/* Run Button */}
      <button
        onClick={handleRun}
        disabled={isLoading}
        className="w-full py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-semibold"
      >
        {isLoading ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            Running Tests...
          </span>
        ) : (
          '🚀 Run Tests'
        )}
      </button>

      {/* Results */}
      {session && (
        <div className="mt-6 bg-gray-700 rounded-lg p-4">
          <h3 className="text-lg font-semibold text-white mb-3">Test Results</h3>

          <div className="grid grid-cols-4 gap-4 mb-4">
            <div className="bg-gray-600 rounded p-3 text-center">
              <div className="text-2xl font-bold text-white">{session.total_requirements}</div>
              <div className="text-sm text-gray-300">Requirements</div>
            </div>
            <div className="bg-gray-600 rounded p-3 text-center">
              <div className="text-2xl font-bold text-white">{session.total_test_cases}</div>
              <div className="text-sm text-gray-300">Test Cases</div>
            </div>
            {session.results_summary && (
              <>
                <div className="bg-green-900/50 rounded p-3 text-center">
                  <div className="text-2xl font-bold text-green-400">{session.results_summary.passed}</div>
                  <div className="text-sm text-gray-300">Passed</div>
                </div>
                <div className="bg-red-900/50 rounded p-3 text-center">
                  <div className="text-2xl font-bold text-red-400">{session.results_summary.failed}</div>
                  <div className="text-sm text-gray-300">Failed</div>
                </div>
              </>
            )}
          </div>

          {session.results_summary && (
            <div className="text-center mb-4">
              <span className="text-gray-400">Pass Rate: </span>
              <span className="text-xl font-bold text-white">{session.results_summary.pass_rate}</span>
            </div>
          )}

          <button
            onClick={handleDownload}
            className="w-full py-2 bg-green-600 text-white rounded hover:bg-green-700 flex items-center justify-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Download Excel Report
          </button>
        </div>
      )}
    </div>
  )
}
