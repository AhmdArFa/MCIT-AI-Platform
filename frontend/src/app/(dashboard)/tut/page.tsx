'use client'

import { Suspense } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'next/navigation'
import { ExternalLink } from 'lucide-react'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { TutAvatar } from '@/components/tut/TutAvatar'
import { tutApi } from '@/lib/api/admin'

/**
 * Tut Agent: the MCIT-Agent app (agent runtime, tools, skills, knowledge,
 * memory, multi-agent groups) embedded in MCIT AI. It signs in with the same
 * MCIT AI account through the shared login.
 */
function TutAgent() {
  const params = useSearchParams()
  const { data: url = '', isLoading } = useQuery({ queryKey: ['tut-url'], queryFn: tutApi.url, staleTime: Infinity })
  const notebook = params.get('notebook')
  const src = url ? `${url}/` : ''

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-5">
          <TutAvatar size={28} />
          <div className="flex min-w-0 flex-col">
            <span className="text-sm font-semibold">Tut Agent</span>
            <span className="truncate text-xs text-muted-foreground">
              {notebook ? 'Ask Tut to work with this notebook: its MCIT AI tools can read it.' : 'Plans and runs multi-step work across your notebooks, files and Studio.'}
            </span>
          </div>
          {url && (
            <Button asChild size="sm" variant="outline" className="ml-auto">
              <a href={src} target="_blank" rel="noreferrer">
                <ExternalLink className="mr-1.5 h-4 w-4" /> Open in a new window
              </a>
            </Button>
          )}
        </header>
        <div className="min-h-0 flex-1">
          {isLoading ? null : url ? (
            <iframe
              title="Tut Agent"
              src={src}
              className="h-full w-full border-0 bg-background"
              allow="clipboard-read; clipboard-write; microphone; camera"
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
              <TutAvatar size={72} />
              <h1 className="text-xl font-semibold">Tut Agent is not connected yet</h1>
              <p className="max-w-md text-sm text-muted-foreground">
                Your administrator needs to start the Tut Agent service and set its address
                (TUT_AGENT_PUBLIC_URL). Notebook chat and Studio keep working in the meantime.
              </p>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  )
}

export default function TutAgentPage() {
  return (
    <Suspense>
      <TutAgent />
    </Suspense>
  )
}
