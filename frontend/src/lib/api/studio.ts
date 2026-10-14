import { apiClient } from './client'

export interface LibraryFile {
  id: string
  filename: string
  format: string
  kind: string
  title: string
  notebook_id?: string | null
  notebook_name?: string
  theme?: string
  preset?: string
  engine?: string
  size: number
  created: string
  updated?: string | null
  version?: number
}

export type PresetId = 'presentation' | 'report' | 'sketchnote' | 'noir_sheet'
export type PresetMode = 'dark' | 'light'

export interface StudioPreset {
  id: PresetId
  name: string
  description: string
  modes: PresetMode[]
  outputs: string[]
  ready: boolean
}

export type JobEvent =
  | { seq: number; type: 'step'; id: string; title?: string; kind?: string; status: 'running' | 'done' | 'error' }
  | { seq: number; type: 'progress'; step_id: string | null; message: string }
  | { seq: number; type: 'usage'; input_tokens: number; output_tokens: number; reasoning_tokens: number; calls: number; final?: boolean }
  | { seq: number; type: 'file'; file: LibraryFile }
  | { seq: number; type: 'message'; content: string }
  | { seq: number; type: 'error'; message: string }

export interface JobSnapshot {
  id: string
  kind: string
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  usage: { input_tokens: number; output_tokens: number; reasoning_tokens: number; calls: number }
  events: JobEvent[]
}

export interface StudioJobRequest {
  notebook_id: string
  preset: PresetId
  mode: PresetMode
  slide_count?: number
  length?: 'short' | 'medium' | 'long'
  audience?: string
  instructions?: string | null
  model_id?: string | null
}

export const studioApi = {
  presets: async () => (await apiClient.get<{ presets: StudioPreset[] }>('/studio/presets')).data.presets,
  start: async (body: StudioJobRequest) => (await apiClient.post<{ id: string; status: string }>('/studio/jobs', body)).data,
  poll: async (id: string, after = -1) =>
    (await apiClient.get<JobSnapshot>(`/studio/jobs/${id}`, { params: { after } })).data,
  cancel: async (id: string) => {
    await apiClient.post(`/studio/jobs/${id}/cancel`)
  },
}

/** Poll a Studio job until it finishes, delivering new events as they arrive. */
export async function followJob(
  jobId: string,
  onEvents: (events: JobEvent[], snap: JobSnapshot) => void,
  intervalMs = 1000
): Promise<JobSnapshot> {
  let after = -1
  for (;;) {
    await new Promise((r) => setTimeout(r, intervalMs))
    const snap = await studioApi.poll(jobId, after)
    if (snap.events.length) {
      after = snap.events[snap.events.length - 1].seq
      onEvents(snap.events, snap)
    }
    if (snap.status !== 'running') return snap
  }
}

export const filesApi = {
  list: async (notebookId?: string) =>
    (await apiClient.get<LibraryFile[]>('/studio/files', { params: notebookId ? { notebook_id: notebookId } : {} })).data,
  get: async (id: string, ownerId?: string | null) =>
    (await apiClient.get<LibraryFile>(`/studio/files/${id}`, { headers: ownerId ? { 'X-MCIT-Act-As': ownerId } : {} })).data,
  blob: async (id: string, ownerId?: string | null) =>
    (await apiClient.get(`/studio/files/${id}/download`, { params: { inline: true }, responseType: 'blob', headers: ownerId ? { 'X-MCIT-Act-As': ownerId } : {} })).data as Blob,
  remove: async (id: string) => {
    await apiClient.delete(`/studio/files/${id}`)
  },
  download: async (file: LibraryFile, ownerId?: string | null) => {
    const blob = (await apiClient.get(`/studio/files/${file.id}/download`, { responseType: 'blob', headers: ownerId ? { 'X-MCIT-Act-As': ownerId } : {} })).data as Blob
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = file.filename
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  },
}

export interface OfficeConfig {
  public_url: string
  editable: boolean
  config: Record<string, unknown>
}

export const OFFICE_FORMATS = new Set(['docx', 'doc', 'odt', 'rtf', 'xlsx', 'xls', 'ods', 'csv', 'pptx', 'ppt', 'odp', 'pdf'])

export const officeApi = {
  settings: async () => (await apiClient.get<{ enabled: boolean; public_url: string }>('/office/settings')).data,
  config: async (fileId: string, mode: 'view' | 'edit', theme: 'dark' | 'light', ownerId?: string | null) =>
    (await apiClient.get<OfficeConfig>(`/office/config/${fileId}`, { params: { mode, theme }, headers: ownerId ? { 'X-MCIT-Act-As': ownerId } : {} })).data,
}

export interface UsageRow {
  model: string
  provider: string
  model_id: string | null
  requests: number
  input_tokens: number
  output_tokens: number
  reasoning_tokens: number
  errors: number
  last_used: string | null
}

export interface UsageEvent {
  model: string
  provider: string
  feature: string
  input_tokens: number
  output_tokens: number
  reasoning_tokens: number
  error: string | null
  created: string
}

export const usageApi = {
  summary: async () => (await apiClient.get<{ models: UsageRow[] }>('/usage/summary')).data.models,
  recent: async (limit = 40) => (await apiClient.get<{ events: UsageEvent[] }>('/usage/recent', { params: { limit } })).data.events,
}

export function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function formatTokens(n: number | null | undefined) {
  if (n == null) return '—'
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}K`
  return `${(n / 1_000_000).toFixed(1)}M`
}
