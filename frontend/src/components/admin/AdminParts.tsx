'use client'

import { useAuth } from '@/lib/hooks/use-auth'
import { AppShell } from '@/components/layout/AppShell'

/** Admin pages render only for administrators (the API enforces it too). */
export function AdminGate({ children }: { children: React.ReactNode }) {
  const { isAdmin, user } = useAuth()
  if (!user) return null
  if (!isAdmin) {
    return (
      <AppShell>
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
          <h1 className="text-xl font-semibold">Administrators only</h1>
          <p className="text-sm text-muted-foreground">This area is available to administrator accounts.</p>
        </div>
      </AppShell>
    )
  }
  return <>{children}</>
}

export function StatCard({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-border bg-card p-4">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  )
}

export function when(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

const ACTIONS: Record<string, string> = {
  'auth.login': 'Signed in',
  'auth.failed': 'Failed sign-in',
  'auth.tut_agent_login': 'Opened Tut Agent',
  'auth.password_changed': 'Changed password',
  'auth.agent_token': 'Created a Tut Agent token',
  'user.created': 'Account created',
  'admin.user_created': 'Created an account',
  'admin.user_updated': 'Updated an account',
  'admin.password_reset': 'Reset a password',
  'admin.user_deleted': 'Deleted an account',
  'file.saved': 'Saved a file in the office viewer',
}

export function actionLabel(action: string) {
  return ACTIONS[action] ?? action
}
