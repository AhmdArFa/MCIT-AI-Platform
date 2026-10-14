'use client'

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, Maximize2, Minimize2, PencilLine, Eye, X, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { FileGlyph } from '@/components/files/FileCard'
import { OFFICE_FORMATS, LibraryFile, filesApi, officeApi } from '@/lib/api/studio'
import { useFilePanel } from '@/lib/stores/file-panel-store'
import { useTheme } from '@/lib/stores/theme-store'
import { cn } from '@/lib/utils'

type DocsApi = { DocEditor: new (id: string, config: Record<string, unknown>) => { destroyEditor: () => void } }

declare global {
  interface Window {
    DocsAPI?: DocsApi
  }
}

const scriptLoads = new Map<string, Promise<void>>()

function loadDocsApi(publicUrl: string): Promise<void> {
  const src = `${publicUrl.replace(/\/$/, '')}/web-apps/apps/api/documents/api.js`
  if (window.DocsAPI) return Promise.resolve()
  const existing = scriptLoads.get(src)
  if (existing) return existing
  const p = new Promise<void>((resolve, reject) => {
    const el = document.createElement('script')
    el.src = src
    el.async = true
    el.onload = () => resolve()
    el.onerror = () => {
      scriptLoads.delete(src)
      reject(new Error('The office viewer could not be reached'))
    }
    document.head.appendChild(el)
  })
  scriptLoads.set(src, p)
  return p
}

/** ONLYOFFICE Docs, the only viewer/editor for office files. */
function OfficeFrame({ file, mode, ownerId }: { file: LibraryFile; mode: 'view' | 'edit'; ownerId: string | null }) {
  const { isDark } = useTheme()
  const holder = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const elementId = `office-${file.id}`

  useEffect(() => {
    let editor: { destroyEditor: () => void } | null = null
    let cancelled = false
    setLoading(true)
    setError(null)
    ;(async () => {
      try {
        const { public_url, config } = await officeApi.config(file.id, mode, isDark ? 'dark' : 'light', ownerId)
        await loadDocsApi(public_url)
        if (cancelled || !window.DocsAPI || !holder.current) return
        holder.current.innerHTML = `<div id="${elementId}"></div>`
        editor = new window.DocsAPI.DocEditor(elementId, config)
        setLoading(false)
      } catch (e) {
        const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(msg || (e as Error).message || 'The office viewer is unavailable')
        setLoading(false)
      }
    })()
    return () => {
      cancelled = true
      try {
        editor?.destroyEditor()
      } catch {
        /* already gone */
      }
    }
  }, [file.id, file.version, mode, isDark, elementId, ownerId])

  return (
    <div className="relative h-full w-full">
      {loading && !error && (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Opening {file.filename}
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center">
          <p className="text-sm font-medium">{error}</p>
          <p className="text-xs text-muted-foreground">You can still download the file.</p>
        </div>
      )}
      <div ref={holder} className="h-full w-full [&>div]:h-full [&_iframe]:h-full" />
    </div>
  )
}

/** Images and vector files preview inline. */
function ImageFrame({ file, ownerId }: { file: LibraryFile; ownerId: string | null }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let revoke: string | null = null
    filesApi
      .blob(file.id, ownerId)
      .then((b) => {
        revoke = URL.createObjectURL(b)
        setUrl(revoke)
      })
      .catch(() => toast.error('Could not load the preview'))
    return () => {
      if (revoke) URL.revokeObjectURL(revoke)
    }
  }, [file.id, file.version, ownerId])
  return (
    <div className="flex h-full items-start justify-center overflow-auto bg-muted/40 p-6">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {url ? <img src={url} alt={file.title} className="max-w-full rounded-md shadow-lg" /> : <Loader2 className="mt-10 h-5 w-5 animate-spin text-muted-foreground" />}
    </div>
  )
}

export function FilePanelHost() {
  const { fileId, ownerId, fullscreen, close, toggleFullscreen } = useFilePanel()
  const [mode, setMode] = useState<'view' | 'edit'>('view')
  const { data: file } = useQuery({
    queryKey: ['library-file', ownerId, fileId],
    queryFn: () => filesApi.get(fileId as string, ownerId),
    enabled: !!fileId,
  })

  useEffect(() => setMode('view'), [fileId, ownerId])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && close()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [close])

  if (!fileId) return null
  const office = !!file && OFFICE_FORMATS.has(file.format)
  const editable = !!file && ['docx', 'xlsx', 'pptx', 'csv', 'odt', 'ods', 'odp'].includes(file.format)

  return (
    <aside
      aria-label="File viewer"
      className={cn(
        'z-40 flex flex-col border-l border-border bg-background',
        fullscreen ? 'fixed inset-0' : 'relative h-full w-[min(56vw,980px)] shrink-0'
      )}
    >
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
        {file && <FileGlyph format={file.format} />}
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{file?.filename ?? 'Loading…'}</span>
        {editable && (
          <Button size="sm" variant="ghost" onClick={() => setMode((m) => (m === 'view' ? 'edit' : 'view'))}>
            {mode === 'view' ? <PencilLine className="mr-1.5 h-4 w-4" /> : <Eye className="mr-1.5 h-4 w-4" />}
            {mode === 'view' ? 'Edit' : 'View'}
          </Button>
        )}
        {file && (
          <Button size="icon" variant="ghost" aria-label="Download" onClick={() => filesApi.download(file, ownerId)}>
            <Download className="h-4 w-4" />
          </Button>
        )}
        <Button size="icon" variant="ghost" aria-label={fullscreen ? 'Exit full screen' : 'Full screen'} onClick={toggleFullscreen}>
          {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
        </Button>
        <Button size="icon" variant="ghost" aria-label="Close" onClick={close}>
          <X className="h-4 w-4" />
        </Button>
      </header>
      <div className="min-h-0 flex-1">
        {!file ? null : office ? <OfficeFrame file={file} mode={mode} ownerId={ownerId} /> : <ImageFrame file={file} ownerId={ownerId} />}
      </div>
    </aside>
  )
}
