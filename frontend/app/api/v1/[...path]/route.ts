import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8005'

async function proxyRequest(request: NextRequest, path: string[]) {
  const targetPath = `/api/v1/${path.join('/')}`
  const targetUrl = `${BACKEND_URL}${targetPath}`

  try {
    const contentType = request.headers.get('content-type') || ''
    const fetchOptions: RequestInit = { method: request.method }

    if (request.method !== 'GET' && request.method !== 'HEAD') {
      if (contentType.includes('multipart/form-data')) {
        // Stream multipart body directly — converting to URLSearchParams drops files and non-string fields
        fetchOptions.body = await request.formData() as any
      } else if (contentType.includes('application/json')) {
        fetchOptions.body = JSON.stringify(await request.json())
        fetchOptions.headers = { 'Content-Type': 'application/json' }
      } else {
        fetchOptions.body = await request.text()
      }
    }

    const response = await fetch(targetUrl, fetchOptions)
    const responseContentType = response.headers.get('Content-Type') || ''

    // Handle binary responses (Excel, images, etc.)
    if (
      responseContentType.includes('application/vnd.openxmlformats') ||
      responseContentType.includes('application/octet-stream') ||
      responseContentType.includes('image/') ||
      responseContentType.includes('application/pdf')
    ) {
      const binaryData = await response.arrayBuffer()
      return new NextResponse(binaryData, {
        status: response.status,
        headers: {
          'Content-Type': responseContentType,
          'Content-Disposition': response.headers.get('Content-Disposition') || '',
        },
      })
    }

    const responseData = await response.text()
    try {
      const jsonData = JSON.parse(responseData)
      return NextResponse.json(jsonData, { status: response.status })
    } catch {
      return new NextResponse(responseData, {
        status: response.status,
        headers: { 'Content-Type': responseContentType || 'text/plain' },
      })
    }
  } catch {
    return NextResponse.json({ error: 'Service unavailable' }, { status: 502 })
  }
}

export async function GET(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params
  return proxyRequest(request, path)
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params
  return proxyRequest(request, path)
}

export async function PUT(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params
  return proxyRequest(request, path)
}

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params
  return proxyRequest(request, path)
}

export async function PATCH(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params
  return proxyRequest(request, path)
}
