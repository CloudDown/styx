import { useStore } from '@nanostores/react'
import type { ComponentProps } from 'react'

import { SidebarLoadMoreRow } from '@/app/chat/sidebar/load-more-row'
import { SidebarLoadErrorState, SidebarSessionSkeletons } from '@/app/chat/sidebar/section-states'
import { SidebarSessionsSection } from '@/app/chat/sidebar/sessions-section'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { useI18n } from '@/i18n'
import { SIDEBAR_SESSIONS_PAGE_SIZE } from '@/store/layout'
import { $selectedStoredSessionId, $sessions, $sessionProfilesTruncated, $sessionsLoading, $sessionsLoadError } from '@/store/session'

type Actions = Pick<ComponentProps<typeof SidebarSessionsSection>, 'onDeleteSession' | 'onResumeSession'> & {
  onLoadMoreSessions: () => unknown
  onNewSessionInWorkspace: (cwd: null) => void
  onRetrySessions: () => unknown
}

export function FastSidebar(actions: Actions) {
  const { t } = useI18n()
  const active = useStore($selectedStoredSessionId)
  const sessions = useStore($sessions)
  const loading = useStore($sessionsLoading)
  const error = useStore($sessionsLoadError)
  const more = Object.values(useStore($sessionProfilesTruncated)).some(Boolean)
  const empty = loading ? <SidebarSessionSkeletons /> : error
    ? <SidebarLoadErrorState onRetry={() => void actions.onRetrySessions()} />
    : <p className="px-2 py-3 text-xs text-muted-foreground">{t.sidebar.noSessions}</p>

  return (
    <>
      <Button className="m-3 justify-start" onClick={() => actions.onNewSessionInWorkspace(null)} variant="ghost">
        <Codicon name="robot" /> {t.sidebar.nav['new-session']}
      </Button>
      <SidebarSessionsSection
        activeSessionId={active}
        collapsible={false}
        contentClassName="min-h-0 overflow-y-auto"
        emptyState={empty}
        footer={more ? (
          <SidebarLoadMoreRow loading={loading} onClick={() => void actions.onLoadMoreSessions()} step={SIDEBAR_SESSIONS_PAGE_SIZE} />
        ) : null}
        grouping="date"
        label={t.sidebar.sessions}
        onArchiveSession={() => {}}
        onDeleteSession={actions.onDeleteSession}
        onResumeSession={actions.onResumeSession}
        onToggle={() => {}}
        onTogglePin={() => {}}
        onToggleUnread={() => {}}
        open
        pinned={false}
        rootClassName="min-h-0 flex-1 overflow-hidden px-3"
        sessions={sessions}
      />
    </>
  )
}
