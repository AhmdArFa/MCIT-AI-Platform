import { apiClient } from './client'
import type { SessionUser } from '@/lib/stores/auth-store'
import type { LibraryFile, UsageEvent, UsageRow } from './studio'

export interface UserOverview {
  user: SessionUser
  counts: { notebooks: number; sources: number; notes: number; chats: number; podcasts: number; generations: number }
  usage: { requests: number; input_tokens: number; output_tokens: number }
  storage_bytes: number
}

export interface AdminChat {
  id: string
  title: string
  notebook_id: string | null
  notebook_name: string
  message_count: number
  created: string
  updated: string
}

export interface AuditEvent {
  id: string
  action: string
  actor: string | null
  target: string | null
  detail: Record<string, unknown>
  created: string
}

export type ServiceState = { state: 'up' | 'down' | 'degraded' | 'not_configured'; status?: number; error?: string }

export interface Monitoring {
  services: Record<string, ServiceState>
  engines: { id: string; name: string; role: string; available: boolean; version: string }[]
  jobs: Record<string, number>
  totals: {
    users: number
    active_users: number
    requests: number
    input_tokens: number
    output_tokens: number
    generations: number
    chats: number
    notebooks: number
  }
  users: UserOverview[]
  audit: AuditEvent[]
}

export const adminApi = {
  users: async () => (await apiClient.get<{ users: UserOverview[] }>('/admin/users')).data.users,
  user: async (id: string) => (await apiClient.get<UserOverview>(`/admin/users/${encodeURIComponent(id)}`)).data,
  create: async (body: { username: string; password: string; display_name?: string; role: 'admin' | 'user' }) =>
    (await apiClient.post<SessionUser>('/admin/users', body)).data,
  update: async (id: string, body: { display_name?: string; role?: 'admin' | 'user'; active?: boolean }) =>
    (await apiClient.patch<SessionUser>(`/admin/users/${encodeURIComponent(id)}`, body)).data,
  resetPassword: async (id: string, password: string) => {
    await apiClient.post(`/admin/users/${encodeURIComponent(id)}/password`, { password })
  },
  remove: async (id: string) => {
    await apiClient.delete(`/admin/users/${encodeURIComponent(id)}`)
  },
  chats: async (id: string) => (await apiClient.get<{ chats: AdminChat[] }>(`/admin/users/${encodeURIComponent(id)}/chats`)).data.chats,
  chat: async (id: string, sessionId: string) =>
    (
      await apiClient.get<{ messages: { role: 'user' | 'assistant'; content: string }[] }>(
        `/admin/users/${encodeURIComponent(id)}/chats/${encodeURIComponent(sessionId)}`
      )
    ).data.messages,
  generations: async (id: string) =>
    (await apiClient.get<{ files: LibraryFile[] }>(`/admin/users/${encodeURIComponent(id)}/generations`)).data.files,
  usage: async (id: string, days = 30) =>
    (await apiClient.get<{ models: UsageRow[]; recent: UsageEvent[] }>(`/admin/users/${encodeURIComponent(id)}/usage`, { params: { days } })).data,
  activity: async (id: string) =>
    (await apiClient.get<{ events: AuditEvent[] }>(`/admin/users/${encodeURIComponent(id)}/activity`)).data.events,
  monitoring: async () => (await apiClient.get<Monitoring>('/admin/monitoring')).data,
  /** Download a file from a user's library (admin acting on their behalf). */
  downloadAs: async (userId: string, file: LibraryFile) => {
    const res = await apiClient.get(`/studio/files/${file.id}/download`, {
      responseType: 'blob',
      headers: { 'X-MCIT-Act-As': userId },
    })
    const url = URL.createObjectURL(res.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = file.filename
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  },
}

export const accountApi = {
  changePassword: async (current_password: string, new_password: string) => {
    await apiClient.post('/auth/password', { current_password, new_password })
  },
  agentToken: async () => (await apiClient.post<{ token: string; expires_at: string; mcp_url: string }>('/auth/agent-token')).data,
}

export const tutApi = {
  /** Public URL of the Tut Agent app, from runtime config. */
  url: async () => (await apiClient.get<{ tut_agent_url?: string }>('/config')).data.tut_agent_url || '',
  connection: async () => (await apiClient.get<{ connected: boolean }>('/tut/connection')).data.connected,
  connect: async (key: string) => (await apiClient.put('/tut/connection', { key })).data,
  disconnect: async () => (await apiClient.delete('/tut/connection')).data,
}
