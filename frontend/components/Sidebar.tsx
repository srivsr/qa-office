'use client'

import { useState, useEffect } from 'react'
import { useUser, useClerk, useAuth } from '@clerk/nextjs'

const API_URL = '/api/v1'

interface Project {
  id: string
  name: string
  domain?: string
}

interface SidebarProps {
  selectedProject: string | null
  onSelectProject: (id: string) => void
  onNewChat: () => void
}

export default function Sidebar({ selectedProject, onSelectProject, onNewChat }: SidebarProps) {
  const { user, isLoaded } = useUser()
  const { signOut } = useClerk()
  const { getToken } = useAuth()
  const [projects, setProjects] = useState<Project[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [projectName, setProjectName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // Load projects - first from localStorage for instant display, then sync with backend
  useEffect(() => {
    // Load from localStorage immediately for instant display
    const saved = localStorage.getItem('qa-os-projects')
    if (saved) {
      try {
        const savedProjects = JSON.parse(saved)
        if (Array.isArray(savedProjects) && savedProjects.length > 0) {
          setProjects(savedProjects)
        }
      } catch (e) {
        console.error('Failed to parse localStorage projects:', e)
      }
    }

    if (user) {
      loadProjects()
    }
  }, [user])

  const loadProjects = async () => {
    try {
      setLoading(true)
      const token = await getToken()
      // removed debug log
      const response = await fetch(`${API_URL}/projects`, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })
      if (response.ok) {
        const data = await response.json()
        // Only update if backend returns data - don't overwrite with empty array
        if (Array.isArray(data) && data.length > 0) {
          setProjects(data)
          localStorage.setItem('qa-os-projects', JSON.stringify(data))
        } else {
          // Backend returned empty - keep localStorage data if it exists
          const saved = localStorage.getItem('qa-os-projects')
          if (saved) {
            const savedProjects = JSON.parse(saved)
            if (Array.isArray(savedProjects) && savedProjects.length > 0) {
              setProjects(savedProjects)
              // Try to sync localStorage projects to backend
              syncLocalProjectsToBackend(savedProjects, token)
            }
          }
        }
      } else {
        const saved = localStorage.getItem('qa-os-projects')
        if (saved) setProjects(JSON.parse(saved))
      }
    } catch (err) {
      console.error('Failed to load projects:', err)
      const saved = localStorage.getItem('qa-os-projects')
      if (saved) setProjects(JSON.parse(saved))
    } finally {
      setLoading(false)
    }
  }

  const syncLocalProjectsToBackend = async (localProjects: Project[], token: string | null) => {
    // Sync localStorage projects to backend (in case db was reset)
    for (const project of localProjects) {
      try {
        await fetch(`${API_URL}/projects`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ name: project.name, domain: project.domain })
        })
      } catch (e) {
      }
    }
  }

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!projectName.trim()) return

    try {
      const token = await getToken()
      const response = await fetch(`${API_URL}/projects`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name: projectName.trim() })
      })
      if (response.ok) {
        const newProject = await response.json()
        const updated = [...projects, newProject]
        setProjects(updated)
        localStorage.setItem('qa-os-projects', JSON.stringify(updated))
        onSelectProject(newProject.id)
      } else {
        const errText = await response.text()
        // Fallback to localStorage
        const newProject: Project = {
          id: Date.now().toString(),
          name: projectName.trim()
        }
        const updated = [...projects, newProject]
        setProjects(updated)
        localStorage.setItem('qa-os-projects', JSON.stringify(updated))
        onSelectProject(newProject.id)
      }
    } catch (err) {
      console.error('Create project error:', err)
      // Fallback to localStorage
      const newProject: Project = {
        id: Date.now().toString(),
        name: projectName.trim()
      }
      const updated = [...projects, newProject]
      setProjects(updated)
      localStorage.setItem('qa-os-projects', JSON.stringify(updated))
      onSelectProject(newProject.id)
    }

    setShowCreate(false)
    setProjectName('')
  }

  if (!isLoaded) {
    return (
      <div className="w-64 bg-gray-800 p-4 flex flex-col">
        <h2 className="text-xl font-bold text-white mb-6">QA-OS</h2>
        <p className="text-gray-400">Loading...</p>
      </div>
    )
  }

  return (
    <div className="w-64 bg-gray-800 p-4 flex flex-col">
      <h2 className="text-xl font-bold text-white mb-2">QA-OS</h2>
      {user && (
        <p className="text-gray-400 text-sm mb-4 truncate">{user.emailAddresses[0]?.emailAddress}</p>
      )}

      <button
        onClick={() => { onNewChat(); }}
        className="bg-blue-600 text-white px-4 py-2 rounded mb-4 hover:bg-blue-700"
      >
        + New Chat
      </button>

      <div className="flex-1 overflow-y-auto">
        <div className="flex justify-between items-center mb-2">
          <h3 className="text-gray-400 text-sm uppercase">Projects</h3>
          <button
            onClick={() => setShowCreate(true)}
            className="text-blue-400 text-sm hover:text-blue-300"
          >
            + Add
          </button>
        </div>

        {showCreate && (
          <form onSubmit={handleCreateProject} className="mb-4">
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="Project name"
              className="w-full px-3 py-2 bg-gray-700 rounded text-white mb-2"
            />
            <button type="submit" className="w-full bg-green-600 text-white px-3 py-1 rounded text-sm">
              Create
            </button>
          </form>
        )}

        <ul className="space-y-1">
          {projects.map((project) => (
            <li key={project.id}>
              <button
                onClick={() => onSelectProject(project.id)}
                className={`w-full text-left px-3 py-2 rounded ${
                  selectedProject === project.id
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-300 hover:bg-gray-700'
                }`}
              >
                {project.name}
              </button>
            </li>
          ))}
        </ul>

        {projects.length === 0 && (
          <p className="text-gray-500 text-sm mt-2">No projects yet. Create one to get started.</p>
        )}
      </div>

      <div className="mt-4 pt-4 border-t border-gray-700">
        <button
          onClick={() => signOut()}
          className="w-full text-left text-gray-400 hover:text-white text-sm"
        >
          Sign Out
        </button>
      </div>
    </div>
  )
}
