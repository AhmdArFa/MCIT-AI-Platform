'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { AlertCircle, Eye, EyeOff } from 'lucide-react'
import { useAuth } from '@/lib/hooks/use-auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { TutAvatar } from '@/components/tut/TutAvatar'

export function LoginForm() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const { login, isLoading, error, isAuthenticated } = useAuth()
  const router = useRouter()
  const params = useSearchParams()
  const next = params.get('next')

  useEffect(() => {
    // Already signed in: finish a pending Tut Agent sign-in or go home
    if (isAuthenticated && !isLoading) {
      if (next?.startsWith('/api/oidc/')) window.location.href = next
      else router.replace('/notebooks')
    }
  }, [isAuthenticated, isLoading, next, router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (username.trim() && password) await login(username, password, next)
  }

  if (isAuthenticated && !error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-background">
      <section className="hidden lg:flex flex-col justify-between border-r border-border bg-card p-12">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/mcit-logo.png" alt="Ministry of Communications and Information Technology" className="h-14 w-auto self-start object-contain" />
        <div className="flex flex-col gap-6 max-w-md">
          <TutAvatar size={88} />
          <h1 className="text-4xl font-semibold tracking-tight text-foreground">MCIT AI</h1>
          <p className="text-base leading-relaxed text-muted-foreground">
            Notebooks, Studio and Tut Agent in one workspace. Research your sources, chat with them, and produce
            reports, decks, infographics and spreadsheets.
          </p>
        </div>
        <p className="text-xs text-muted-foreground">Ministry of Communications and Information Technology</p>
      </section>

      <section className="flex items-center justify-center p-6">
        <form onSubmit={handleSubmit} className="w-full max-w-sm flex flex-col gap-6" aria-label="Sign in">
          <div className="flex flex-col gap-2">
            <div className="lg:hidden mb-2"><TutAvatar size={56} /></div>
            <h2 className="text-2xl font-semibold tracking-tight">Sign in</h2>
            <p className="text-sm text-muted-foreground">
              {next?.startsWith('/api/oidc/')
                ? 'Sign in to continue to Tut Agent.'
                : 'Use the account your administrator created for you.'}
            </p>
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              name="username"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={isLoading}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="password">Password</Label>
            <div className="relative">
              <Input
                id="password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
                className="pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-muted-foreground hover:text-foreground"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {error && (
            <div role="alert" className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <Button type="submit" className="w-full" disabled={isLoading || !username.trim() || !password}>
            {isLoading ? 'Signing in…' : 'Sign in'}
          </Button>

          <p className="text-xs text-muted-foreground">
            Accounts are created by your administrator. Contact them if you need access or a new password.
          </p>
        </form>
      </section>
    </div>
  )
}
