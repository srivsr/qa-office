'use client'

import { useState } from 'react'
import Link from 'next/link'
import ChatInterface from '@/components/ChatInterface'
import Sidebar from '@/components/Sidebar'

const NAV_ITEMS = [
  { href: '/dashboard', label: 'Dashboard', icon: '📊' },
  { href: '/', label: 'AI Chat', icon: '💬' },
  { href: '/execute', label: 'Run Tests', icon: '🎯' },
  { href: '/reports', label: 'Reports', icon: '📈' },
  { href: '/framework', label: 'Framework', icon: '🏗️' },
]

export default function Home() {
  const [selectedProject, setSelectedProject] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)

  return (
    <main className="flex h-screen bg-[#0a0a0f]">
      {/* Navigation Bar */}
      <nav className="fixed top-0 left-0 right-0 h-14 bg-[#111118] border-b border-white/10 z-50 flex items-center px-4">
        <div className="flex items-center gap-2 mr-8">
          <span className="text-xl">🧪</span>
          <span className="font-bold text-white">QA-OS</span>
        </div>
        <div className="flex gap-1">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`px-4 py-2 rounded-lg text-sm flex items-center gap-2 transition-colors ${
                item.href === '/'
                  ? 'bg-blue-500/20 text-blue-400'
                  : 'text-gray-400 hover:bg-white/10 hover:text-white'
              }`}
            >
              <span>{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </div>
      </nav>

      {/* Main Content */}
      <div className="flex w-full pt-14">
        <Sidebar
          selectedProject={selectedProject}
          onSelectProject={setSelectedProject}
          onNewChat={() => setSessionId(null)}
        />
        <div className="flex-1 flex flex-col">
          {selectedProject ? (
            <ChatInterface
              projectId={selectedProject}
              sessionId={sessionId}
              onSessionChange={setSessionId}
            />
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <h1 className="text-4xl font-bold text-white mb-4">QA-OS</h1>
                <p className="text-gray-400 text-lg mb-8">
                  AI-Powered Test Orchestration Platform
                </p>
                <p className="text-gray-500 mb-6">
                  Select or create a project to get started
                </p>
                <div className="flex gap-4 justify-center">
                  <Link
                    href="/dashboard"
                    className="px-6 py-3 rounded-xl bg-blue-500 hover:bg-blue-600 text-white font-medium transition-colors"
                  >
                    Go to Dashboard
                  </Link>
                  <Link
                    href="/execute"
                    className="px-6 py-3 rounded-xl bg-white/10 hover:bg-white/20 text-white font-medium transition-colors"
                  >
                    Run Tests
                  </Link>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  )
}
