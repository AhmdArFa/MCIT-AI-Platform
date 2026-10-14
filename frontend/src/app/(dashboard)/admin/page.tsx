'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import { AppShell } from '@/components/layout/AppShell'
import { AdminGate, StatCard, actionLabel, when } from '@/components/admin/AdminParts'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { adminApi, ServiceState } from '@/lib/api/admin'
import { formatBytes, formatTokens } from '@/lib/api/studio'
import { cn } from '@/lib/utils'

const SERVICE_NAMES: Record<string, string> = {
  database: 'Database',
  language_models: 'Language models',
  speech: 'Speech (podcasts)',
  office_viewer: 'Office viewer',
  tut_agent: 'Tut Agent',
}

const STATE_TEXT: Record<ServiceState['state'], string> = {
  up: 'Running',
  degraded: 'Responding with errors',
  down: 'Not reachable',
  not_configured: 'Not configured',
}

function NewUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient()
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<'user' | 'admin'>('user')
  const [saving, setSaving] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      await adminApi.create({ username, password, display_name: displayName, role })
      toast.success(`Account ${username} created`)
      qc.invalidateQueries({ queryKey: ['admin-monitoring'] })
      setUsername('')
      setDisplayName('')
      setPassword('')
      setRole('user')
      onOpenChange(false)
    } catch (err) {
      toast.error((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Could not create the account')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>New account</DialogTitle>
            <DialogDescription>Share the username and password with the person directly. They can change the password later.</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="nu-username">Username</Label>
            <Input id="nu-username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" placeholder="e.g. sara.hassan" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="nu-name">Display name</Label>
            <Input id="nu-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="Sara Hassan" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="nu-password">Password</Label>
            <Input id="nu-password" type="text" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Role</Label>
            <div className="flex rounded-lg bg-muted p-1">
              {(['user', 'admin'] as const).map((r) => (
                <button key={r} type="button" onClick={() => setRole(r)} aria-pressed={role === r} className={cn('flex-1 rounded-md px-3 py-1.5 text-sm', role === r ? 'bg-background font-medium shadow-sm' : 'text-muted-foreground')}>
                  {r === 'user' ? 'Member' : 'Administrator'}
                </button>
              ))}
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={saving || !username.trim() || password.length < 4}>Create account</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export default function AdminPage() {
  const { data, isLoading, refetch, isFetching } = useQuery({ queryKey: ['admin-monitoring'], queryFn: adminApi.monitoring, refetchInterval: 30000 })
  const [creating, setCreating] = useState(false)
  const [q, setQ] = useState('')
  const users = useMemo(
    () => (data?.users ?? []).filter((u) => !q || `${u.user.username} ${u.user.display_name}`.toLowerCase().includes(q.toLowerCase())),
    [data, q]
  )
  const names = useMemo(() => Object.fromEntries((data?.users ?? []).map((u) => [u.user.id, u.user.username])), [data])

  return (
    <AdminGate>
      <AppShell>
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
            <div className="flex items-end justify-between gap-4">
              <div className="flex flex-col gap-1">
                <h1 className="text-2xl font-semibold tracking-tight">Admin console</h1>
                <p className="text-sm text-muted-foreground">Accounts, per-user workspaces and platform health.</p>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
                  <RefreshCw className={cn('mr-1.5 h-4 w-4', isFetching && 'animate-spin')} /> Refresh
                </Button>
                <Button size="sm" onClick={() => setCreating(true)}>
                  <Plus className="mr-1.5 h-4 w-4" /> New account
                </Button>
              </div>
            </div>

            {isLoading || !data ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : (
              <Tabs defaultValue="users" className="flex flex-col gap-4">
                <TabsList className="self-start">
                  <TabsTrigger value="users">Users</TabsTrigger>
                  <TabsTrigger value="monitoring">Monitoring</TabsTrigger>
                  <TabsTrigger value="activity">Activity</TabsTrigger>
                </TabsList>

                <TabsContent value="users" className="flex flex-col gap-4">
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    <StatCard label="Accounts" value={data.totals.users} hint={`${data.totals.active_users} active`} />
                    <StatCard label="Notebooks" value={data.totals.notebooks} />
                    <StatCard label="Chats" value={data.totals.chats} />
                    <StatCard label="Generated files" value={data.totals.generations} />
                  </div>
                  <Input placeholder="Search accounts" value={q} onChange={(e) => setQ(e.target.value)} className="max-w-xs" aria-label="Search accounts" />
                  <div className="overflow-x-auto rounded-xl border border-border">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                        <tr>
                          {['Account', 'Role', 'Notebooks', 'Chats', 'Files', 'Tokens', 'Storage', 'Last sign-in'].map((h) => (
                            <th key={h} className="px-4 py-2.5 font-medium">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {users.map((u) => (
                          <tr key={u.user.id} className="border-t border-border hover:bg-muted/40">
                            <td className="px-4 py-3">
                              <Link href={`/admin/users/${encodeURIComponent(u.user.id)}`} className="flex flex-col hover:underline">
                                <span className="font-medium">{u.user.display_name || u.user.username}</span>
                                <span className="text-xs text-muted-foreground">
                                  {u.user.username}
                                  {!u.user.active && ' · disabled'}
                                </span>
                              </Link>
                            </td>
                            <td className="px-4 py-3">{u.user.role === 'admin' ? 'Administrator' : 'Member'}</td>
                            <td className="px-4 py-3 tabular-nums">{u.counts.notebooks}</td>
                            <td className="px-4 py-3 tabular-nums">{u.counts.chats}</td>
                            <td className="px-4 py-3 tabular-nums">{u.counts.generations}</td>
                            <td className="px-4 py-3 tabular-nums">{formatTokens(u.usage.input_tokens + u.usage.output_tokens)}</td>
                            <td className="px-4 py-3 tabular-nums">{formatBytes(u.storage_bytes)}</td>
                            <td className="px-4 py-3 text-muted-foreground">{when(u.user.last_login)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </TabsContent>

                <TabsContent value="monitoring" className="flex flex-col gap-6">
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    <StatCard label="MCIT AI requests" value={formatTokens(data.totals.requests)} hint="Tut Agent usage is tracked separately" />
                    <StatCard label="Input tokens" value={formatTokens(data.totals.input_tokens)} />
                    <StatCard label="Output tokens" value={formatTokens(data.totals.output_tokens)} />
                    <StatCard label="Background jobs" value={Object.values(data.jobs).reduce((a, b) => a + b, 0)} hint={Object.entries(data.jobs).map(([k, v]) => `${v} ${k}`).join(' · ') || 'None queued'} />
                  </div>
                  <section className="flex flex-col gap-2">
                    <h2 className="text-sm font-semibold">Services</h2>
                    <div className="grid gap-2 md:grid-cols-2">
                      {Object.entries(data.services).map(([key, s]) => (
                        <div key={key} className="flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3">
                          <span className="text-sm font-medium">{SERVICE_NAMES[key] ?? key}</span>
                          <span className={cn('text-sm', s.state === 'up' ? 'text-foreground' : s.state === 'not_configured' ? 'text-muted-foreground' : 'text-destructive')}>
                            {STATE_TEXT[s.state]}
                          </span>
                        </div>
                      ))}
                    </div>
                  </section>
                  <section className="flex flex-col gap-2">
                    <h2 className="text-sm font-semibold">Craft engines</h2>
                    <div className="grid gap-2 md:grid-cols-3">
                      {data.engines.map((e) => (
                        <div key={e.id} className="flex flex-col gap-0.5 rounded-xl border border-border bg-card px-4 py-3">
                          <span className="text-sm font-medium">{e.name}</span>
                          <span className="text-xs text-muted-foreground">{e.role}</span>
                          <span className={cn('text-xs', e.available ? 'text-foreground' : 'text-destructive')}>
                            {e.available ? e.version || 'Installed' : 'Not installed'}
                          </span>
                        </div>
                      ))}
                    </div>
                  </section>
                </TabsContent>

                <TabsContent value="activity">
                  <div className="overflow-x-auto rounded-xl border border-border">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/60 text-left text-xs text-muted-foreground">
                        <tr>
                          {['When', 'Event', 'By', 'Account'].map((h) => (
                            <th key={h} className="px-4 py-2.5 font-medium">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.audit.map((a) => (
                          <tr key={a.id} className="border-t border-border">
                            <td className="px-4 py-2.5 text-muted-foreground">{when(a.created)}</td>
                            <td className="px-4 py-2.5">{actionLabel(a.action)}</td>
                            <td className="px-4 py-2.5">{a.actor ? names[a.actor] ?? '—' : String(a.detail?.username ?? '—')}</td>
                            <td className="px-4 py-2.5">{a.target ? names[a.target] ?? '—' : '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </TabsContent>
              </Tabs>
            )}
          </div>
        </div>
        <NewUserDialog open={creating} onOpenChange={setCreating} />
      </AppShell>
    </AdminGate>
  )
}
