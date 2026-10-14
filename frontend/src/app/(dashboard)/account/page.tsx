'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, KeyRound } from 'lucide-react'
import { toast } from 'sonner'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { accountApi, tutApi } from '@/lib/api/admin'
import { useAuth } from '@/lib/hooks/use-auth'

function Section({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-border bg-card p-6">
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  )
}

export default function AccountPage() {
  const queryClient = useQueryClient()
  const { data: tutConnected = false } = useQuery({ queryKey: ['tut-connection'], queryFn: tutApi.connection })
  const { user, isAdmin } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [token, setToken] = useState<{ token: string; expires_at: string; mcp_url: string } | null>(null)
  const [tutKey, setTutKey] = useState('')

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (next !== confirm) return toast.error('The new passwords do not match')
    setSaving(true)
    try {
      await accountApi.changePassword(current, next)
      toast.success('Password changed')
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (err) {
      toast.error((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Could not change the password')
    } finally {
      setSaving(false)
    }
  }

  const mcpUrl = typeof window !== 'undefined' && token ? `${window.location.origin}${token.mcp_url}` : ''

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-8">
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-semibold tracking-tight">Account</h1>
            <p className="text-sm text-muted-foreground">
              {user?.display_name || user?.username} · {isAdmin ? 'Administrator' : 'Member'}. Your notebooks, chats, files and usage are private to you.
            </p>
          </div>

          <Section title="Password" description="Choose a password only you know. Your administrator can also reset it.">
            <form onSubmit={changePassword} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="current">Current password</Label>
                <Input id="current" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="next">New password</Label>
                  <Input id="next" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="confirm">Repeat new password</Label>
                  <Input id="confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                </div>
              </div>
              <Button type="submit" className="self-start" disabled={saving || !current || next.length < 4}>
                Change password
              </Button>
            </form>
          </Section>

          <Section
            title="Studio connection"
            description="Studio drafts with your own Tut Agent, then the Craft engines build the files. Create a personal API key in Tut Agent with model:invoke, chat:write and agent:write scopes, then connect it here. The key is encrypted in your private workspace."
          >
            <p className="text-sm text-muted-foreground">
              {tutConnected ? 'Tut Agent is connected for Studio.' : 'Connect Tut Agent before using Studio.'}{' '}
              <Link href="/tut" className="text-primary underline">Open Tut Agent</Link>
            </p>
            <form
              className="flex gap-2"
              onSubmit={async (e) => {
                e.preventDefault()
                try {
                  await tutApi.connect(tutKey)
                  setTutKey('')
                  queryClient.invalidateQueries({ queryKey: ['tut-connection'] })
                  toast.success('Tut Agent connected')
                } catch {
                  toast.error('Could not connect your Tut Agent key')
                }
              }}
            >
              <Input
                type="password"
                autoComplete="off"
                aria-label="Tut Agent API key"
                placeholder="Personal Tut Agent API key"
                value={tutKey}
                onChange={(e) => setTutKey(e.target.value)}
              />
              <Button type="submit" disabled={tutKey.length < 12}>Connect</Button>
            </form>
            {tutConnected && (
              <Button
                variant="outline"
                className="self-start"
                onClick={async () => {
                  await tutApi.disconnect()
                  queryClient.invalidateQueries({ queryKey: ['tut-connection'] })
                }}
              >Disconnect</Button>
            )}
          </Section>

          <Section
            title="Connect Tut Agent to MCIT AI"
            description="Add MCIT AI as an MCP server in Tut Agent (Settings, then MCP) so it can read your notebooks, search sources and produce Studio files. Craft engines run behind Studio."
          >
            {!token ? (
              <Button variant="outline" className="self-start" onClick={async () => setToken(await accountApi.agentToken())}>
                <KeyRound className="mr-1.5 h-4 w-4" /> Create a connection token
              </Button>
            ) : (
              <div className="flex flex-col gap-3">
                {[
                  ['Server URL', mcpUrl],
                  ['Authorization header', `Bearer ${token.token}`],
                ].map(([label, value]) => (
                  <div key={label} className="flex flex-col gap-1.5">
                    <Label>{label}</Label>
                    <div className="flex gap-2">
                      <Input readOnly value={value} className="font-mono text-xs" />
                      <Button
                        variant="outline"
                        size="icon"
                        aria-label={`Copy ${label}`}
                        onClick={() => navigator.clipboard.writeText(value).then(() => toast.success('Copied'))}
                      >
                        <Copy className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                ))}
                <p className="text-xs text-muted-foreground">
                  Valid until {new Date(token.expires_at).toLocaleDateString()}. Anyone with this token can act as you, so keep it private.
                </p>
              </div>
            )}
          </Section>
        </div>
      </div>
    </AppShell>
  )
}
