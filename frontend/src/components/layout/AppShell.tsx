'use client'

import { AppSidebar } from './AppSidebar'
import { SetupBanner } from './SetupBanner'
import { AppFooter } from './AppFooter'
import { FilePanelHost } from '@/components/files/FilePanel'

interface AppShellProps {
  children: React.ReactNode
  hideSidebar?: boolean
}

export function AppShell({ children, hideSidebar = false }: AppShellProps) {
  return (
    <div className="flex h-screen overflow-hidden">
      {!hideSidebar && <AppSidebar />}
      <main className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <SetupBanner />
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">{children}</div>
        <AppFooter />
      </main>
      <FilePanelHost />
    </div>
  )
}
