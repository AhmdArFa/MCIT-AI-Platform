'use client'

import { useState } from 'react'
import { Download, FileImage, FileSpreadsheet, FileText, Loader2, Presentation, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { LibraryFile, filesApi, formatBytes } from '@/lib/api/studio'
import { useFilePanel } from '@/lib/stores/file-panel-store'
import { cn } from '@/lib/utils'

const KIND_LABEL: Record<string, string> = {
  report: 'Report',
  presentation: 'Presentation',
  infographic: 'Sketchnote',
  spreadsheet: 'Spreadsheet',
}

export function FileGlyph({ format, className }: { format: string; className?: string }) {
  const f = format.toLowerCase()
  const Icon = ['pptx', 'ppt', 'odp'].includes(f)
    ? Presentation
    : ['xlsx', 'xls', 'csv', 'ods'].includes(f)
      ? FileSpreadsheet
      : ['png', 'svg', 'jpg', 'jpeg', 'webp'].includes(f)
        ? FileImage
        : FileText
  return (
    <span className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-primary', className)}>
      <Icon className="h-[18px] w-[18px]" />
    </span>
  )
}

export function FileCard({
  file,
  onDelete,
  onDownload,
  className,
  openable = true,
  openAsUser,
}: {
  file: LibraryFile
  onDelete?: (id: string) => void
  onDownload?: (file: LibraryFile) => Promise<void>
  className?: string
  openable?: boolean
  openAsUser?: string
}) {
  const [busy, setBusy] = useState(false)
  const openPanel = useFilePanel((s) => s.open)

  const download = async () => {
    setBusy(true)
    try {
      await (onDownload ? onDownload(file) : filesApi.download(file))
    } catch {
      toast.error('Download failed')
    } finally {
      setBusy(false)
    }
  }

  const meta = [
    KIND_LABEL[file.kind] ?? file.kind,
    file.theme === 'dark' || file.theme === 'light' ? (file.theme === 'dark' ? 'Dark' : 'Light') : null,
    file.format.toUpperCase(),
    formatBytes(file.size),
    file.version && file.version > 1 ? `v${file.version}` : null,
    file.notebook_name || null,
  ].filter(Boolean)

  return (
    <div className={cn('group flex items-center gap-3 rounded-xl border bg-card px-3 py-2.5 transition-colors hover:bg-muted/60', className)}>
      <FileGlyph format={file.format} />
      <button
        type="button"
        onClick={() => openable && openPanel(file.id, openAsUser)}
        className="flex min-w-0 flex-1 flex-col text-left disabled:cursor-default"
        disabled={!openable}
        aria-label={`Open ${file.filename}`}
      >
        <span className="truncate text-sm font-medium">{file.filename}</span>
        <span className="truncate text-xs text-muted-foreground">{meta.join(' · ')}</span>
      </button>
      <button type="button" onClick={download} aria-label={`Download ${file.filename}`} className="rounded-md p-1.5 text-muted-foreground hover:bg-background hover:text-foreground">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
      </button>
      {onDelete && (
        <button
          type="button"
          onClick={() => onDelete(file.id)}
          aria-label={`Delete ${file.filename}`}
          className="rounded-md p-1.5 text-muted-foreground opacity-0 hover:bg-background hover:text-destructive focus:opacity-100 group-hover:opacity-100"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      )}
    </div>
  )
}
