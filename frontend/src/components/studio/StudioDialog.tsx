'use client'

import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Circle, FileSpreadsheet, FileText, Loader2, PenTool, Presentation, X } from 'lucide-react'

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { FileCard } from '@/components/files/FileCard'
import { TutAvatar } from '@/components/tut/TutAvatar'
import { followJob, JobEvent, LibraryFile, PresetId, PresetMode, StudioPreset, studioApi } from '@/lib/api/studio'
import { cn } from '@/lib/utils'

const LOOK: Record<PresetId, { icon: typeof FileText; swatch: (mode: PresetMode) => string[] }> = {
  presentation: { icon: Presentation, swatch: (m) => (m === 'dark' ? ['#0B0D12', '#141823', '#C9A227'] : ['#FFFFFF', '#F4F5F8', '#8A6D12']) },
  report: { icon: FileText, swatch: (m) => (m === 'dark' ? ['#0B0D12', '#141823', '#C9A227'] : ['#FFFFFF', '#F4F5F8', '#8A6D12']) },
  sketchnote: { icon: PenTool, swatch: () => ['#FBF7EE', '#F1E6C8', '#3D6E8C'] },
  noir_sheet: { icon: FileSpreadsheet, swatch: () => ['#0B0D12', '#141823', '#C9A227'] },
}

const FALLBACK: StudioPreset[] = [
  { id: 'presentation', name: 'Presentation', description: 'A briefing deck with charts and speaker notes.', modes: ['dark', 'light'], outputs: ['pptx', 'pdf'], ready: true },
  { id: 'report', name: 'Report', description: 'A structured report with findings and recommendations.', modes: ['dark', 'light'], outputs: ['docx', 'pdf'], ready: true },
  { id: 'sketchnote', name: 'Sketchnote infographic', description: 'A hand-drawn style one-page visual summary.', modes: ['light'], outputs: ['svg', 'pdf', 'png'], ready: true },
  { id: 'noir_sheet', name: 'Noir spreadsheet', description: 'The notebook data as a styled dark workbook.', modes: ['dark'], outputs: ['xlsx'], ready: true },
]

interface Step {
  id: string
  title: string
  status: 'running' | 'done' | 'error'
  notes: string[]
}

function steps(events: JobEvent[]): Step[] {
  const list: Step[] = []
  for (const ev of events) {
    if (ev.type === 'step') {
      const existing = list.find((s) => s.id === ev.id)
      if (existing) existing.status = ev.status
      else list.push({ id: ev.id, title: ev.title || 'Working', status: ev.status, notes: [] })
    } else if (ev.type === 'progress') {
      const target = list.find((s) => s.id === ev.step_id) ?? list[list.length - 1]
      target?.notes.push(ev.message)
    }
  }
  return list
}

function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-muted-foreground">{hint}</span>}
    </div>
  )
}

function Segmented<T extends string>({ value, options, onChange, disabled }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; disabled?: boolean }) {
  return (
    <div className="flex rounded-lg bg-muted p-1" role="radiogroup">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={cn('flex-1 rounded-md px-3 py-1.5 text-sm transition-colors', value === o.value ? 'bg-background font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground')}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

interface StudioDialogProps {
  notebookId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function StudioDialog({ notebookId, open, onOpenChange }: StudioDialogProps) {
  const qc = useQueryClient()
  const { data: presets = FALLBACK } = useQuery({ queryKey: ['studio-presets'], queryFn: studioApi.presets, enabled: open })
  const [preset, setPreset] = useState<PresetId>('presentation')
  const [mode, setMode] = useState<PresetMode>('dark')
  const [slideCount, setSlideCount] = useState(10)
  const [length, setLength] = useState<'short' | 'medium' | 'long'>('medium')
  const [audience, setAudience] = useState('senior leadership')
  const [instructions, setInstructions] = useState('')
  const [events, setEvents] = useState<JobEvent[]>([])
  const [files, setFiles] = useState<LibraryFile[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const running = jobId !== null

  const current = presets.find((p) => p.id === preset)
  useEffect(() => {
    if (current && !current.modes.includes(mode)) setMode(current.modes[0])
  }, [current, mode])

  const timeline = useMemo(() => steps(events), [events])

  const generate = async () => {
    setEvents([])
    setFiles([])
    setMessage(null)
    setError(null)
    try {
      const job = await studioApi.start({
        notebook_id: notebookId,
        preset,
        mode,
        slide_count: slideCount,
        length,
        audience,
        instructions: instructions.trim() || null,
      })
      setJobId(job.id)
      await followJob(job.id, (evs) => {
        setEvents((e) => [...e, ...evs])
        for (const ev of evs) {
          if (ev.type === 'file') setFiles((f) => (f.some((x) => x.id === ev.file.id) ? f : [...f, ev.file]))
          if (ev.type === 'message') setMessage(ev.content)
          if (ev.type === 'error') setError(ev.message)
        }
      })
      qc.invalidateQueries({ queryKey: ['studio-files'] })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'The job could not start')
    } finally {
      setJobId(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto rounded-2xl sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg font-semibold">
            <TutAvatar size={24} /> Studio
          </DialogTitle>
          <DialogDescription>Tut Agent writes from this notebook and the Craft engines build the file.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-6 md:grid-cols-[1fr_1fr]">
          <div className="flex flex-col gap-5">
            <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="What to create">
              {presets.map((p) => {
                const look = LOOK[p.id]
                const Icon = look.icon
                const sw = look.swatch(p.id === preset ? mode : p.modes[0])
                return (
                  <button
                    key={p.id}
                    type="button"
                    role="radio"
                    aria-checked={preset === p.id}
                    disabled={running || !p.ready}
                    onClick={() => setPreset(p.id)}
                    className={cn(
                      'flex flex-col gap-2 rounded-xl border p-3 text-left transition-colors disabled:opacity-50',
                      preset === p.id ? 'border-primary/60 bg-muted' : 'hover:bg-muted/50'
                    )}
                  >
                    <div className="flex h-9 overflow-hidden rounded-md border border-border">
                      <span className="flex-[3]" style={{ background: sw[0] }} />
                      <span className="flex-[2]" style={{ background: sw[1] }} />
                      <span className="flex-1" style={{ background: sw[2] }} />
                    </div>
                    <span className="flex items-center gap-2 text-sm font-medium">
                      <Icon className="h-4 w-4 text-primary" /> {p.name}
                    </span>
                    <span className="text-xs text-muted-foreground">{p.description}</span>
                    {!p.ready && <span className="text-[11px] text-muted-foreground">Engines not installed</span>}
                  </button>
                )
              })}
            </div>

            {current && current.modes.length > 1 && (
              <Field label="Style">
                <Segmented value={mode} onChange={setMode} disabled={running} options={[{ value: 'dark', label: 'Dark' }, { value: 'light', label: 'Light' }]} />
              </Field>
            )}

            {preset === 'presentation' && (
              <Field label={`Slides: ${slideCount}`} hint="Cover and closing slides are added.">
                <input type="range" min={4} max={20} value={slideCount} disabled={running} onChange={(e) => setSlideCount(Number(e.target.value))} className="accent-[var(--primary)]" aria-label="Number of slides" />
              </Field>
            )}
            {preset === 'report' && (
              <Field label="Length">
                <Segmented value={length} onChange={setLength} disabled={running} options={[{ value: 'short', label: 'Short' }, { value: 'medium', label: 'Medium' }, { value: 'long', label: 'Long' }]} />
              </Field>
            )}

            <Field label="Audience">
              <Input value={audience} onChange={(e) => setAudience(e.target.value)} disabled={running} />
            </Field>
            <Field label="Instructions for Tut Agent" hint="Optional: focus, sections to include, figures to highlight.">
              <Textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} disabled={running} rows={3} />
            </Field>

            <div className="flex gap-2">
              <Button onClick={generate} disabled={running || !current?.ready} className="h-10 flex-1 rounded-xl">
                {running && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {running ? 'Working' : events.length ? 'Create again' : 'Create'}
              </Button>
              {running && jobId && (
                <Button variant="outline" className="h-10 rounded-xl" onClick={() => studioApi.cancel(jobId)}>
                  Stop
                </Button>
              )}
            </div>
          </div>

          <div className="flex min-h-[420px] flex-col gap-3 rounded-2xl border border-border bg-muted/40 p-4" aria-live="polite">
            {!events.length && !running && (
              <div className="m-auto flex max-w-xs flex-col items-center gap-3 text-center text-sm text-muted-foreground">
                <TutAvatar size={48} />
                Progress and finished files appear here.
              </div>
            )}
            {timeline.length > 0 && (
              <ol className="flex flex-col gap-3">
                {timeline.map((s) => (
                  <li key={s.id} className="flex gap-3">
                    <span className="mt-0.5">
                      {s.status === 'running' ? (
                        <Loader2 className="h-4 w-4 animate-spin text-primary" />
                      ) : s.status === 'done' ? (
                        <Check className="h-4 w-4 text-primary" />
                      ) : s.status === 'error' ? (
                        <X className="h-4 w-4 text-destructive" />
                      ) : (
                        <Circle className="h-4 w-4 text-muted-foreground" />
                      )}
                    </span>
                    <div className="flex min-w-0 flex-col gap-1">
                      <span className="text-sm font-medium">{s.title}</span>
                      {s.notes.map((n, i) => (
                        <span key={i} className="text-xs text-muted-foreground">{n}</span>
                      ))}
                    </div>
                  </li>
                ))}
              </ol>
            )}
            {files.length > 0 && (
              <div className="flex flex-col gap-2">
                {files.map((f) => (
                  <FileCard key={f.id} file={f} />
                ))}
              </div>
            )}
            {message && <p className="text-sm">{message}</p>}
            {error && <p role="alert" className="rounded-lg border border-destructive/30 px-3 py-2 text-sm text-destructive">{error}</p>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
