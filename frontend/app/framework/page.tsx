'use client'

import { useState, useEffect } from 'react'

type FrameworkType = 'playwright' | 'appium' | 'api' | 'fullstack'
type Language = 'typescript' | 'javascript' | 'python'

interface CrawlProgress {
  phase: string
  percent: number
  message: string
  pages_found: number
  elements_found: number
}

interface FrameworkSession {
  session_id: string
  status: string
  structure?: any
  download_url?: string
  progress?: CrawlProgress
  stats?: {
    pages_discovered: number
    page_objects_generated: number
    tests_generated: number
    total_elements: number
    duration_ms: number
  }
}

interface SavedRequirement {
  id: string
  title: string
  description: string
  route?: string
}

const FEATURES = [
  { id: 'page_object_model', label: 'Page Object Model', default: true },
  { id: 'ci_cd', label: 'CI/CD Pipelines', default: true },
  { id: 'docker', label: 'Docker Support', default: true },
  { id: 'allure', label: 'Allure Reporting', default: false },
  { id: 'env_configs', label: 'Environment Configs', default: true },
  { id: 'browserstack', label: 'BrowserStack Integration', default: false },
  { id: 'github_actions', label: 'GitHub Actions', default: false },
  { id: 'jenkins', label: 'Jenkins Pipeline', default: false },
]

export default function FrameworkPage() {
  const [appUrl, setAppUrl] = useState('')
  const [appName, setAppName] = useState('')
  const [frameworkType, setFrameworkType] = useState<FrameworkType>('playwright')
  const [language, setLanguage] = useState<Language>('typescript')
  const [features, setFeatures] = useState<string[]>(
    FEATURES.filter(f => f.default).map(f => f.id)
  )
  const [requirementsText, setRequirementsText] = useState('')

  const [loading, setLoading] = useState(false)
  const [session, setSession] = useState<FrameworkSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<CrawlProgress | null>(null)
  const [requirements, setRequirements] = useState<SavedRequirement[]>([])
  const [selectedRequirements, setSelectedRequirements] = useState<string[]>([])
  const [activeTab, setActiveTab] = useState<'config' | 'requirements'>('config')

  // Fetch saved requirements on mount
  useEffect(() => {
    fetchRequirements()
  }, [])

  const fetchRequirements = async () => {
    try {
      const res = await fetch('/api/v1/requirements')
      if (res.ok) {
        const data = await res.json()
        setRequirements(data.requirements || data || [])
      }
    } catch (err) {
      console.error('Failed to fetch requirements:', err)
    }
  }

  const toggleRequirement = (id: string) => {
    setSelectedRequirements(prev =>
      prev.includes(id) ? prev.filter(r => r !== id) : [...prev, id]
    )
  }

  const toggleFeature = (id: string) => {
    setFeatures(prev =>
      prev.includes(id)
        ? prev.filter(f => f !== id)
        : [...prev, id]
    )
  }

  const handleGenerate = async () => {
    if (!appUrl) {
      setError('Application URL is required')
      return
    }

    setLoading(true)
    setError(null)
    setSession(null)
    setProgress(null)

    // Build requirements text from selected requirements
    let reqText = requirementsText
    if (selectedRequirements.length > 0) {
      const selectedReqs = requirements.filter(r => selectedRequirements.includes(r.id))
      const reqLines = selectedReqs.map(r => `${r.title}: ${r.description}${r.route ? ` (${r.route})` : ''}`)
      reqText = reqLines.join('\n') + (requirementsText ? '\n' + requirementsText : '')
    }

    try {
      const res = await fetch('/api/v1/framework/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          app_url: appUrl,
          app_name: appName || 'my-app',
          framework_type: frameworkType,
          language: language,
          features: features,
          requirements_text: reqText || null
        })
      })

      if (!res.ok) {
        throw new Error('Failed to start framework generation')
      }

      const data = await res.json()
      setSession(data)

      // Poll for progress and status
      pollProgress(data.session_id)

    } catch (err: any) {
      setError(err.message || 'An error occurred')
      setLoading(false)
    }
  }

  const pollProgress = async (sessionId: string) => {
    const maxAttempts = 60  // 2 minutes max
    let attempts = 0

    const poll = async () => {
      if (attempts >= maxAttempts) {
        setLoading(false)
        return
      }

      try {
        // Poll progress endpoint for detailed crawl info
        const progressRes = await fetch(`/api/v1/framework/${sessionId}/progress`)
        if (progressRes.ok) {
          const progressData = await progressRes.json()
          setProgress({
            phase: progressData.phase,
            percent: progressData.percent,
            message: progressData.message,
            pages_found: progressData.pages_found,
            elements_found: progressData.elements_found
          })

          if (progressData.status === 'completed' || progressData.status === 'error') {
            // Get final status with structure
            const statusRes = await fetch(`/api/v1/framework/${sessionId}/status`)
            if (statusRes.ok) {
              const statusData = await statusRes.json()
              setSession(statusData)
            }
            setLoading(false)
            return
          }
        }
      } catch (err) {
        console.error('Polling error:', err)
      }

      attempts++
      setTimeout(poll, 1000)  // Poll every second for smoother progress
    }

    poll()
  }

  const handleDownload = () => {
    if (session?.download_url) {
      window.open(session.download_url, '_blank')
    }
  }

  const renderFileTree = (node: any, level = 0) => {
    if (!node) return null

    const indent = level * 16
    const isDir = node.type === 'directory'

    return (
      <div key={node.name} style={{ marginLeft: indent }}>
        <div className="flex items-center gap-2 py-1 text-sm">
          <span>{isDir ? '📁' : '📄'}</span>
          <span className={isDir ? 'font-medium text-blue-400' : 'text-gray-300'}>
            {node.name}
          </span>
        </div>
        {isDir && node.children?.map((child: any) => renderFileTree(child, level + 1))}
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white p-8">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold mb-2">Framework Generator</h1>
          <p className="text-gray-400">Generate a production-ready test framework from your requirements</p>
        </div>

        <div className="grid grid-cols-2 gap-8">
          {/* Left Panel - Tabs */}
          <div className="space-y-6">
            {/* Tab Buttons */}
            <div className="flex gap-2 p-1 bg-white/5 rounded-xl">
              <button
                onClick={() => setActiveTab('config')}
                className={`flex-1 py-2 px-4 rounded-lg transition-colors ${
                  activeTab === 'config'
                    ? 'bg-blue-500 text-white'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                Configuration
              </button>
              <button
                onClick={() => setActiveTab('requirements')}
                className={`flex-1 py-2 px-4 rounded-lg transition-colors ${
                  activeTab === 'requirements'
                    ? 'bg-blue-500 text-white'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                Requirements ({selectedRequirements.length})
              </button>
            </div>

            {activeTab === 'config' ? (
              <>
            {/* Application */}
            <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
              <h2 className="text-lg font-semibold mb-4">Application</h2>
              <div className="space-y-4">
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
                    placeholder="my-app"
                    className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 focus:border-blue-500 focus:outline-none"
                  />
                </div>
              </div>
            </div>

            {/* Framework Type */}
            <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
              <h2 className="text-lg font-semibold mb-4">Framework Type</h2>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { id: 'playwright', label: 'Playwright (Web)', icon: '🎭' },
                  { id: 'appium', label: 'Appium (Mobile)', icon: '📱' },
                  { id: 'api', label: 'API Testing', icon: '🔌' },
                  { id: 'fullstack', label: 'Full Stack', icon: '🚀' },
                ].map((fw) => (
                  <button
                    key={fw.id}
                    onClick={() => setFrameworkType(fw.id as FrameworkType)}
                    className={`p-4 rounded-xl text-left transition-colors ${
                      frameworkType === fw.id
                        ? 'bg-blue-500/20 border-2 border-blue-500/50'
                        : 'bg-white/5 border border-white/10 hover:bg-white/10'
                    }`}
                  >
                    <span className="text-2xl block mb-2">{fw.icon}</span>
                    <span className="font-medium">{fw.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Language */}
            <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
              <h2 className="text-lg font-semibold mb-4">Language</h2>
              <div className="flex gap-3">
                {[
                  { id: 'typescript', label: 'TypeScript' },
                  { id: 'javascript', label: 'JavaScript' },
                  { id: 'python', label: 'Python' },
                ].map((lang) => (
                  <button
                    key={lang.id}
                    onClick={() => setLanguage(lang.id as Language)}
                    className={`flex-1 py-3 rounded-xl text-center transition-colors ${
                      language === lang.id
                        ? 'bg-purple-500/20 border-2 border-purple-500/50'
                        : 'bg-white/5 border border-white/10 hover:bg-white/10'
                    }`}
                  >
                    {lang.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Features */}
            <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
              <h2 className="text-lg font-semibold mb-4">Features</h2>
              <div className="grid grid-cols-2 gap-2">
                {FEATURES.map((feature) => (
                  <label
                    key={feature.id}
                    className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
                      features.includes(feature.id)
                        ? 'bg-green-500/20 border border-green-500/50'
                        : 'bg-white/5 border border-white/10 hover:bg-white/10'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={features.includes(feature.id)}
                      onChange={() => toggleFeature(feature.id)}
                      className="w-4 h-4"
                    />
                    <span className="text-sm">{feature.label}</span>
                  </label>
                ))}
              </div>
            </div>
              </>
            ) : (
              /* Requirements Tab */
              <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
                <h2 className="text-lg font-semibold mb-4">Link Requirements to Framework</h2>
                <p className="text-sm text-gray-400 mb-4">
                  Select requirements to include in framework generation. Page Objects will be created based on requirement routes.
                </p>

                {requirements.length === 0 ? (
                  <div className="text-center py-8 text-gray-500">
                    <p>No requirements found.</p>
                    <p className="text-sm mt-2">Add requirements in the Requirements page first.</p>
                  </div>
                ) : (
                  <div className="space-y-2 max-h-[400px] overflow-y-auto">
                    {requirements.map((req) => (
                      <label
                        key={req.id}
                        className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
                          selectedRequirements.includes(req.id)
                            ? 'bg-blue-500/20 border border-blue-500/50'
                            : 'bg-white/5 border border-white/10 hover:bg-white/10'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={selectedRequirements.includes(req.id)}
                          onChange={() => toggleRequirement(req.id)}
                          className="w-4 h-4 mt-1"
                        />
                        <div className="flex-1">
                          <div className="font-medium">{req.title}</div>
                          <div className="text-sm text-gray-400 line-clamp-2">{req.description}</div>
                          {req.route && (
                            <div className="text-xs text-blue-400 mt-1">Route: {req.route}</div>
                          )}
                        </div>
                      </label>
                    ))}
                  </div>
                )}

                {/* Additional requirements text */}
                <div className="mt-4">
                  <label className="block text-sm text-gray-400 mb-2">Additional Requirements (optional)</label>
                  <textarea
                    value={requirementsText}
                    onChange={(e) => setRequirementsText(e.target.value)}
                    placeholder="Add any additional requirements here..."
                    rows={4}
                    className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 focus:border-blue-500 focus:outline-none resize-none"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Preview & Actions */}
          <div className="space-y-6">
            {/* Crawl Progress */}
            {loading && progress && (
              <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
                <h2 className="text-lg font-semibold mb-4">Crawling Application...</h2>

                {/* Progress Bar */}
                <div className="mb-4">
                  <div className="flex justify-between text-sm text-gray-400 mb-2">
                    <span>{progress.phase}</span>
                    <span>{progress.percent}%</span>
                  </div>
                  <div className="w-full h-2 bg-white/10 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-blue-500 to-cyan-500 transition-all duration-300"
                      style={{ width: `${progress.percent}%` }}
                    />
                  </div>
                  <p className="text-sm text-gray-400 mt-2">{progress.message}</p>
                </div>

                {/* Crawl Stats */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="p-3 rounded-lg bg-white/5">
                    <div className="text-2xl font-bold text-blue-400">{progress.pages_found}</div>
                    <div className="text-sm text-gray-400">Pages Found</div>
                  </div>
                  <div className="p-3 rounded-lg bg-white/5">
                    <div className="text-2xl font-bold text-green-400">{progress.elements_found}</div>
                    <div className="text-sm text-gray-400">Elements Found</div>
                  </div>
                </div>
              </div>
            )}

            {/* Preview */}
            <div className="p-6 rounded-2xl bg-white/5 border border-white/10 h-[400px] overflow-y-auto">
              <h2 className="text-lg font-semibold mb-4">Generated Structure Preview</h2>

              {session?.structure ? (
                <div className="font-mono text-sm">
                  {renderFileTree(session.structure)}
                </div>
              ) : loading ? (
                <div className="flex flex-col items-center justify-center h-64 text-gray-500">
                  <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mb-4"></div>
                  <p>Generating framework...</p>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-64 text-gray-500">
                  <span className="text-4xl mb-2">📁</span>
                  <p>Click Generate to preview structure</p>
                </div>
              )}
            </div>

            {/* Generation Stats */}
            {session?.stats && (
              <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                <h3 className="font-semibold mb-3">Generation Summary</h3>
                <div className="grid grid-cols-4 gap-2 text-center">
                  <div>
                    <div className="text-xl font-bold text-blue-400">{session.stats.pages_discovered}</div>
                    <div className="text-xs text-gray-400">Pages</div>
                  </div>
                  <div>
                    <div className="text-xl font-bold text-purple-400">{session.stats.page_objects_generated}</div>
                    <div className="text-xs text-gray-400">Page Objects</div>
                  </div>
                  <div>
                    <div className="text-xl font-bold text-green-400">{session.stats.tests_generated}</div>
                    <div className="text-xs text-gray-400">Tests</div>
                  </div>
                  <div>
                    <div className="text-xl font-bold text-cyan-400">{session.stats.total_elements}</div>
                    <div className="text-xs text-gray-400">Elements</div>
                  </div>
                </div>
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="p-4 rounded-xl bg-red-500/20 border border-red-500/50 text-red-400">
                {error}
              </div>
            )}

            {/* Status */}
            {session && (
              <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                <div className="flex items-center gap-3">
                  {session.status === 'completed' ? (
                    <span className="text-xl">✅</span>
                  ) : session.status === 'error' ? (
                    <span className="text-xl">❌</span>
                  ) : (
                    <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
                  )}
                  <span className="capitalize">{session.status}</span>
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-4">
              <button
                onClick={handleGenerate}
                disabled={loading}
                className="flex-1 py-4 rounded-xl bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-600 hover:to-cyan-600 disabled:opacity-50 disabled:cursor-not-allowed font-semibold transition-all"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                    Generating...
                  </span>
                ) : (
                  '🔄 Generate'
                )}
              </button>

              {session?.status === 'completed' && (
                <button
                  onClick={handleDownload}
                  className="flex-1 py-4 rounded-xl bg-green-500 hover:bg-green-600 font-semibold transition-colors"
                >
                  📥 Download ZIP
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
