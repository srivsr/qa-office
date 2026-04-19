'use client'

import { useState, useRef, useEffect } from 'react'
import { api } from '@/lib/api'
import ReactMarkdown from 'react-markdown'
import TestRunner from './TestRunner'

interface Message {
  id?: string
  role: 'user' | 'assistant'
  content: string
  citations?: any[]
  artifacts?: any[]
  downloadUrl?: string
}

interface ChatInterfaceProps {
  projectId: string
  sessionId: string | null
  onSessionChange: (id: string) => void
}

export default function ChatInterface({ projectId, sessionId, onSessionChange }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showTestRunner, setShowTestRunner] = useState(false)
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (sessionId) {
      loadMessages()
    } else {
      setMessages([])
    }
  }, [sessionId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const loadMessages = async () => {
    if (!sessionId) return
    try {
      const data = await api.chat.getMessages(sessionId)
      setMessages(data)
    } catch (err) {
      console.error('Failed to load messages:', err)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const userMessage: Message = { role: 'user', content: input }
    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    try {
      const response = await api.chat.send(input, projectId, sessionId || undefined)

      if (!sessionId) {
        onSessionChange(response.session_id)
      }

      const assistantMessage: Message = {
        role: 'assistant',
        content: response.message,
        citations: response.citations,
        artifacts: response.artifacts
      }
      setMessages((prev) => [...prev, assistantMessage])
    } catch (err: any) {
      const errorMessage: Message = {
        role: 'assistant',
        content: `Error: ${err.message}`
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setUploadedFile(e.target.files[0])
    }
  }

  const clearFile = () => {
    setUploadedFile(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const examplePrompts = [
    "Generate test cases for user login functionality",
    "Analyze coverage gaps for the payment module",
    "Create a test strategy for the shopping cart feature",
    "What are common defect patterns in checkout flows?",
    "Help me prepare for a QA interview on API testing"
  ]

  // Show TestRunner modal
  if (showTestRunner) {
    return (
      <div className="flex-1 flex flex-col bg-gray-900 p-4 overflow-y-auto">
        <TestRunner onClose={() => setShowTestRunner(false)} />
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col bg-gray-900">
      <div className="p-4 border-b border-gray-700">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-white font-semibold">QA Intelligence Chat</h2>
            <p className="text-gray-400 text-sm">Ask me anything about QA, testing, or your project</p>
          </div>
          <button
            onClick={() => setShowTestRunner(true)}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 flex items-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Run E2E Tests
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full">
            <h3 className="text-2xl font-bold text-white mb-4">How can I help you today?</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-2xl">
              {examplePrompts.map((prompt, index) => (
                <button
                  key={index}
                  onClick={() => setInput(prompt)}
                  className="text-left p-3 bg-gray-800 rounded-lg text-gray-300 hover:bg-gray-700 transition"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((message, index) => (
            <div
              key={index}
              className={`chat-message flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-3xl rounded-lg p-4 ${
                  message.role === 'user'
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-100'
                }`}
              >
                <div className="prose prose-invert max-w-none">
                  <ReactMarkdown>{message.content}</ReactMarkdown>
                </div>

                {message.citations && message.citations.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-gray-700">
                    <p className="text-sm text-gray-400 mb-2">Sources:</p>
                    <div className="flex flex-wrap gap-2">
                      {message.citations.map((citation, idx) => (
                        <span
                          key={idx}
                          className="text-xs bg-gray-700 px-2 py-1 rounded"
                        >
                          [{citation.type.toUpperCase()}:{citation.id.slice(0, 8)}]
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {message.artifacts && message.artifacts.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-gray-700">
                    <p className="text-sm text-gray-400 mb-2">Generated Artifacts:</p>
                    <div className="space-y-2">
                      {message.artifacts.map((artifact, idx) => (
                        <div key={idx} className="text-xs bg-gray-700 px-3 py-2 rounded">
                          <span className="text-blue-400">{artifact.type}</span>
                          {artifact.data?.length && (
                            <span className="text-gray-400 ml-2">
                              ({artifact.data.length} items)
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))
        )}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-800 rounded-lg p-4">
              <div className="flex space-x-2">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form onSubmit={handleSubmit} className="p-4 border-t border-gray-700">
        {/* File Upload Indicator */}
        {uploadedFile && (
          <div className="mb-2 flex items-center gap-2 text-sm">
            <span className="bg-blue-600 text-white px-2 py-1 rounded flex items-center gap-1">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              {uploadedFile.name}
            </span>
            <button
              type="button"
              onClick={clearFile}
              className="text-gray-400 hover:text-white"
            >
              ✕
            </button>
          </div>
        )}

        <div className="flex gap-2">
          {/* File Upload Button */}
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept=".xlsx,.xls,.json,.pdf,.txt,.md"
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="px-3 py-3 bg-gray-700 text-gray-300 rounded-lg hover:bg-gray-600 transition"
            title="Upload requirements file"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
            </svg>
          </button>

          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about requirements, test cases, coverage, defects..."
            className="flex-1 px-4 py-3 bg-gray-800 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  )
}
