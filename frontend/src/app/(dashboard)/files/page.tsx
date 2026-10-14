'use client'

import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, Search } from 'lucide-react'
import { toast } from 'sonner'

import { AppShell } from '@/components/layout/AppShell'
import { FileCard } from '@/components/files/FileCard'
import { filesApi } from '@/lib/api/studio'
import { cn } from '@/lib/utils'

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'presentation', label: 'Presentations' },
  { id: 'report', label: 'Reports' },
  { id: 'infographic', label: 'Sketchnotes' },
  { id: 'spreadsheet', label: 'Spreadsheets' },
]

export default function FilesPage() {
  const qc = useQueryClient()
  const { data: files = [], isLoading } = useQuery({ queryKey: ['studio-files'], queryFn: () => filesApi.list(), refetchInterval: 10000 })
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')

  const shown = useMemo(
    () =>
      files.filter(
        (f) =>
          (filter === 'all' || f.kind === filter) &&
          (!q || `${f.filename} ${f.notebook_name ?? ''}`.toLowerCase().includes(q.toLowerCase()))
      ),
    [files, filter, q]
  )

  const remove = async (id: string) => {
    try {
      await filesApi.remove(id)
      qc.invalidateQueries({ queryKey: ['studio-files'] })
    } catch {
      toast.error('Could not delete the file')
    }
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-semibold tracking-tight">Files</h1>
            <p className="text-sm text-muted-foreground">
              Everything Studio and Tut Agent produced for you. Open a file to view it, or edit it in the office viewer.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex rounded-lg bg-muted p-1" role="tablist" aria-label="File type">
              {FILTERS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  role="tab"
                  aria-selected={filter === f.id}
                  onClick={() => setFilter(f.id)}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-sm transition-colors',
                    filter === f.id ? 'bg-background font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <div className="relative ml-auto">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search files"
                aria-label="Search files"
                className="h-9 w-64 rounded-lg border bg-background pl-9 pr-3 text-sm outline-none focus:border-foreground/30"
              />
            </div>
          </div>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading files…</p>
          ) : shown.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed py-16 text-center">
              <FolderOpen className="h-6 w-6 text-muted-foreground" />
              <p className="text-sm font-medium">No files yet</p>
              <p className="text-sm text-muted-foreground">Open a notebook and use Studio, or ask Tut Agent.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              {shown.map((f) => (
                <FileCard key={f.id} file={f} onDelete={remove} />
              ))}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  )
}
