const API_URL = '/api/v1'

let token: string | null = null

export function setToken(t: string) {
  token = t
  if (typeof window !== 'undefined') {
    localStorage.setItem('qa-os-token', t)
  }
}

export function getToken(): string | null {
  if (token) return token
  if (typeof window !== 'undefined') {
    token = localStorage.getItem('qa-os-token')
  }
  return token
}

async function fetchAPI(endpoint: string, options: RequestInit = {}) {
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(options.headers || {})
  }

  const t = getToken()
  if (t) {
    (headers as Record<string, string>)['Authorization'] = `Bearer ${t}`
  }

  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(error.detail || 'Request failed')
  }

  return response.json()
}

export const api = {
  auth: {
    login: (email: string, password: string) =>
      fetchAPI('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password })
      }),
    signup: (email: string, password: string, name: string) =>
      fetchAPI('/auth/signup', {
        method: 'POST',
        body: JSON.stringify({ email, password, name })
      })
  },

  projects: {
    list: () => fetchAPI('/projects'),
    create: (name: string, description?: string, domain?: string) =>
      fetchAPI('/projects', {
        method: 'POST',
        body: JSON.stringify({ name, description, domain })
      }),
    get: (id: string) => fetchAPI(`/projects/${id}`),
    delete: (id: string) => fetchAPI(`/projects/${id}`, { method: 'DELETE' })
  },

  chat: {
    send: (message: string, projectId: string, sessionId?: string) =>
      fetchAPI('/chat', {
        method: 'POST',
        body: JSON.stringify({ message, project_id: projectId, session_id: sessionId })
      }),
    getSessions: (projectId: string) =>
      fetchAPI(`/chat/sessions?project_id=${projectId}`),
    getMessages: (sessionId: string) =>
      fetchAPI(`/chat/sessions/${sessionId}/messages`)
  },

  requirements: {
    list: (projectId: string) => fetchAPI(`/requirements?project_id=${projectId}`),
    create: (projectId: string, data: any) =>
      fetchAPI(`/requirements?project_id=${projectId}`, {
        method: 'POST',
        body: JSON.stringify(data)
      })
  },

  testCases: {
    list: (projectId: string) => fetchAPI(`/test-cases?project_id=${projectId}`),
    get: (id: string) => fetchAPI(`/test-cases/${id}`)
  },

  interview: {
    getPrep: (topic: string, difficulty?: string) =>
      fetchAPI('/interview', {
        method: 'POST',
        body: JSON.stringify({ topic, difficulty })
      }),
    getTopics: () => fetchAPI('/interview/topics')
  },

  learning: {
    getLesson: (topic: string, level?: string) =>
      fetchAPI('/learning/lesson', {
        method: 'POST',
        body: JSON.stringify({ topic, level })
      }),
    getCurriculum: () => fetchAPI('/learning/curriculum')
  }
}
