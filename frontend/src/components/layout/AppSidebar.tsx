'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/hooks/use-auth'
import { useSidebarStore } from '@/lib/stores/sidebar-store'
import { useCreateDialogs } from '@/lib/hooks/use-create-dialogs'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { TutAvatar } from '@/components/tut/TutAvatar'
import type { TFunction } from 'i18next'
import { useTranslation } from '@/lib/hooks/use-translation'
import {
  Book,
  Search,
  Bot,
  Shuffle,
  Settings,
  LogOut,
  ChevronLeft,
  Menu,
  FileText,
  Plus,
  Wrench,
  Command,
  Info,
  MessageSquareText,
  Gauge,
  FolderOpen,
  Mic,
  ShieldCheck,
  UserRound,
} from 'lucide-react'

type NavItem = { name: string; href: string; icon: typeof Book; adminOnly?: boolean }
type NavSection = { title: string; items: NavItem[]; adminOnly?: boolean }

const getNavigation = (t: TFunction, isAdmin: boolean): NavSection[] =>
  ([
    {
      title: 'Workspace',
      items: [
        { name: 'Tut Agent', href: '/tut', icon: MessageSquareText },
        { name: t('navigation.notebooks'), href: '/notebooks', icon: Book },
        { name: t('navigation.sources'), href: '/sources', icon: FileText },
        { name: t('navigation.askAndSearch'), href: '/search', icon: Search },
        { name: 'Files', href: '/files', icon: FolderOpen },
        { name: t('navigation.podcasts'), href: '/podcasts', icon: Mic },
      ],
    },
    {
      title: 'Account',
      items: [
        { name: 'My usage', href: '/usage', icon: Gauge },
        { name: 'Account', href: '/account', icon: UserRound },
      ],
    },
    {
      title: 'Administration',
      adminOnly: true,
      items: [
        { name: 'Admin console', href: '/admin', icon: ShieldCheck },
        { name: t('navigation.models'), href: '/settings/models', icon: Bot },
        { name: t('navigation.transformations'), href: '/transformations', icon: Shuffle },
        { name: t('navigation.settings'), href: '/settings', icon: Settings },
        { name: t('navigation.advanced'), href: '/advanced', icon: Wrench },
      ],
    },
    {
      title: 'MCIT AI',
      items: [{ name: 'About', href: '/about', icon: Info }],
    },
  ] as NavSection[]).filter((s) => isAdmin || !s.adminOnly)

// Official MCIT logo from /public/mcit-logo.png, shown exactly as supplied.
// If the file is absent, fall back to a plain text wordmark.
function MCITLogo({ compact = false }: { compact?: boolean }) {
  const [failed, setFailed] = useState(false)
  if (compact || failed) {
    return <span className="text-[13px] font-semibold tracking-tight">{compact ? 'MCIT' : 'MCIT AI'}</span>
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/mcit-logo.png"
      alt="Ministry of Communications and Information Technology"
      className="h-11 w-auto object-contain"
      onError={() => setFailed(true)}
    />
  )
}

type CreateTarget = 'source' | 'notebook'

export function AppSidebar() {
  const { t } = useTranslation()
  const { logout, user, isAdmin } = useAuth()
  const navigation = getNavigation(t, isAdmin)
  const pathname = usePathname()
  const { isCollapsed, toggleCollapse } = useSidebarStore()
  const { openSourceDialog, openNotebookDialog } = useCreateDialogs()

  // The active item is the longest href that prefixes the current path.
  // Longest-wins keeps `/settings` from also highlighting on `/settings/models`
  // (the Models page is a URL child of the Settings page but a distinct item).
  const activeHref = navigation
    .map((section) => section.items)
    .flat()
    .filter((item) => pathname === item.href || pathname?.startsWith(`${item.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href

  const [createMenuOpen, setCreateMenuOpen] = useState(false)
  const [isMac, setIsMac] = useState(true) // Default to Mac for SSR

  // Detect platform for keyboard shortcut display
  useEffect(() => {
    setIsMac(navigator.platform.toLowerCase().includes('mac'))
  }, [])

  const handleCreateSelection = (target: CreateTarget) => {
    setCreateMenuOpen(false)

    if (target === 'source') {
      openSourceDialog()
    } else if (target === 'notebook') {
      openNotebookDialog()
    }
  }

  return (
    <TooltipProvider delayDuration={0}>
      <div
        className={cn(
          'app-sidebar flex h-full flex-col bg-sidebar border-sidebar-border border-r transition-all duration-300',
          isCollapsed ? 'w-16' : 'w-64'
        )}
      >
        <div
          className={cn(
            'flex items-center group py-4',
            isCollapsed ? 'justify-center px-2 h-20' : 'justify-between gap-1 px-3'
          )}
        >
          {isCollapsed ? (
            <div className="relative flex items-center justify-center w-full">
              <span className="transition-opacity group-hover:opacity-0"><MCITLogo compact /></span>
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleCollapse}
                className="absolute text-sidebar-foreground hover:bg-sidebar-accent opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <Menu className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-1.5 min-w-0 flex-1">
                <MCITLogo />
                <span className="text-[13px] font-semibold tracking-tight text-sidebar-foreground px-0.5">
                  {t('common.appName')}
                </span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleCollapse}
                className="text-sidebar-foreground hover:bg-sidebar-accent"
                data-testid="sidebar-toggle"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
            </>
          )}
        </div>

        <nav
          className={cn(
            'flex-1 space-y-1 py-4',
            isCollapsed ? 'px-2' : 'px-3'
          )}
        >
          <div
            className={cn(
              'mb-4',
              isCollapsed ? 'px-0' : 'px-3'
            )}
          >
            <DropdownMenu open={createMenuOpen} onOpenChange={setCreateMenuOpen}>
              {isCollapsed ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <DropdownMenuTrigger asChild>
                      <Button
                        onClick={() => setCreateMenuOpen(true)}
                        variant="default"
                        size="sm"
                        className="w-full justify-center px-2 font-medium rounded-lg"
                        aria-label={t('common.create')}
                      >
                        <Plus className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                  </TooltipTrigger>
                   <TooltipContent side="right">{t('common.create')}</TooltipContent>
                </Tooltip>
              ) : (
                <DropdownMenuTrigger asChild>
                  <Button
                    onClick={() => setCreateMenuOpen(true)}
                    variant="default"
                    size="sm"
                    className="w-full justify-start font-medium rounded-lg"
                   >
                    <Plus className="h-4 w-4 mr-2" />
                    {t('common.create')}
                  </Button>
                </DropdownMenuTrigger>
              )}

              <DropdownMenuContent
                align={isCollapsed ? 'end' : 'start'}
                side={isCollapsed ? 'right' : 'bottom'}
                className="w-48"
              >
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault()
                    handleCreateSelection('source')
                  }}
                  className="gap-2"
                >
                   <FileText className="h-4 w-4" />
                  {t('common.source')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={(event) => {
                    event.preventDefault()
                    handleCreateSelection('notebook')
                  }}
                  className="gap-2"
                >
                   <Book className="h-4 w-4" />
                  {t('common.notebook')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          {navigation.map((section, index) => (
            <div key={section.title}>
              {index > 0 && (
                <div className="h-3" />
              )}
              <div className="space-y-1">
                {!isCollapsed && (
                  <h3 className="mb-1 px-3 text-xs font-medium text-muted-foreground">
                    {section.title}
                  </h3>
                )}

                {section.items.map((item) => {
                  const isActive = item.href === activeHref
                  const button = (
                    <Button
                      variant="ghost"
                      aria-current={isActive ? 'page' : undefined}
                      className={cn(
                        'w-full gap-2.5 text-[13.5px] font-normal text-sidebar-foreground/80 sidebar-menu-item relative rounded-lg h-9',
                        isActive &&
                          'bg-sidebar-accent font-medium text-sidebar-foreground',
                        isCollapsed ? 'justify-center px-2' : 'justify-start'
                      )}
                    >
                      {item.href === '/tut' ? <TutAvatar size={20} /> : <item.icon className="h-4 w-4 opacity-85" />}
                      {!isCollapsed && <span>{item.name}</span>}
                    </Button>
                  )

                  if (isCollapsed) {
                    return (
                      <Tooltip key={item.name}>
                        <TooltipTrigger asChild>
                          <Link href={item.href}>
                            {button}
                          </Link>
                        </TooltipTrigger>
                        <TooltipContent side="right">{item.name}</TooltipContent>
                      </Tooltip>
                    )
                  }

                  return (
                    <Link key={item.name} href={item.href}>
                      {button}
                    </Link>
                  )
                })}
              </div>
            </div>
          ))}
        </nav>

        <div
          className={cn(
            'border-t border-sidebar-border p-3 space-y-2',
            isCollapsed && 'px-2'
          )}
        >
          {user && !isCollapsed && (
            <div className="flex items-center gap-2.5 px-3 py-1.5">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-xs font-semibold uppercase text-sidebar-foreground">
                {(user.display_name || user.username).slice(0, 2)}
              </span>
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-sm font-medium text-sidebar-foreground">{user.display_name || user.username}</span>
                <span className="truncate text-xs text-muted-foreground">{isAdmin ? 'Administrator' : 'Member'} · {user.username}</span>
              </div>
            </div>
          )}

          {/* Command Palette hint */}
          {!isCollapsed && (
            <div className="px-3 py-1.5 text-xs text-sidebar-foreground/60">
              <div className="flex items-center justify-between">
                 <span className="flex items-center gap-1.5">
                  <Command className="h-3 w-3" />
                  {t('common.quickActions')}
                </span>
                <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
                  {isMac ? <span className="text-xs">⌘</span> : <span>Ctrl+</span>}K
                </kbd>
              </div>
               <p className="mt-1 text-[10px] text-muted-foreground">
                {t('common.quickActionsDesc')}
              </p>
            </div>
          )}

           <div
            className={cn(
              'flex flex-col gap-2',
              isCollapsed ? 'items-center' : 'items-stretch'
            )}
          >
            {isCollapsed ? (
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div>
                      <ThemeToggle iconOnly />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent side="right">{t('common.theme')}</TooltipContent>
                </Tooltip>
              </>
            ) : (
              <>
                <ThemeToggle />
              </>
            )}
          </div>

          {isCollapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="outline"
                  className="w-full justify-center sidebar-menu-item"
                  onClick={logout}
                  aria-label={t('common.signOut')}
                >
                  <LogOut className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
               <TooltipContent side="right">{t('common.signOut')}</TooltipContent>
            </Tooltip>
          ) : (
            <Button
              variant="outline"
              className="w-full justify-start gap-2 sidebar-menu-item"
              onClick={logout}
              aria-label={t('common.signOut')}
             >
              <LogOut className="h-4 w-4" />
              {t('common.signOut')}
            </Button>
          )}
        </div>
      </div>
    </TooltipProvider>
  )
}
