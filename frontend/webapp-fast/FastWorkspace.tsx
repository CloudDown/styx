import { useStore } from '@nanostores/react'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { ContribWiring, WiredPane } from '@/app/contrib/wiring'
import { isNewChatRoute, routeSessionId, sessionRoute } from '@/app/routes'
import { BrandMark } from '@/components/brand-mark'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { SidebarProvider } from '@/components/ui/sidebar'
import { webappSessionKey } from '@/lib/browser-launch-session'
import { $desktopBoot } from '@/store/boot'
import { useTheme } from '@/themes'
import './workspace.css'

function chatSession(pathname: string) {
  try {
    return routeSessionId(pathname)
  } catch {
    return null
  }
}

export default function FastWorkspace() {
  const [sessions, setSessions] = useState(false)
  const [settings, setSettings] = useState(false)
  const { mode, setMode } = useTheme()
  const { pathname } = useLocation()
  const { error } = useStore($desktopBoot)
  const sessionId = chatSession(pathname)
  const isChat = isNewChatRoute(pathname) || Boolean(sessionId)
  const navigate = useNavigate()
  useEffect(() => setSessions(false), [pathname])
  useEffect(() => {
    const url = new URL(location.href)
    const session = url.searchParams.get('session')
    if (!session) return
    url.searchParams.delete('session')
    history.replaceState(history.state, '', url)
    if (!url.hash) navigate(sessionRoute(session), { replace: true })
  }, [navigate])
  useEffect(() => {
    if (!isChat) navigate('/', { replace: true })
  }, [isChat, navigate])

  const profile = new URLSearchParams(location.search).get('profile')
  const official = new URLSearchParams({ _styx_view: 'hermes' })
  const reconnect = new URLSearchParams()
  if (profile) {
    official.set('profile', profile)
    reconnect.set('profile', profile)
  }
  if (sessionId) reconnect.set('session', sessionId)
  const reconnectURL = '/_styx/fast/connect' + (reconnect.size ? `?${reconnect}` : '')

  if (!isChat) return null

  return (
    <SidebarProvider className="h-dvh min-h-0" defaultOpen>
      <ContribWiring>
        <div className="styx-fast-workspace" data-sessions={sessions}>
          <header className="styx-fast-top">
            <Button aria-controls="fast-sessions" aria-expanded={sessions} aria-label="Sessions"
              className="styx-fast-mobile" onClick={() => setSessions(v => !v)} size="icon" variant="ghost">
              <Codicon name="layout-sidebar-left" />
            </Button>
            <BrandMark className="size-6" />
            <span>Hermes <b>Fast</b></span>
            <Button aria-controls="fast-settings" aria-expanded={settings} className="ml-auto" onClick={() => setSettings(v => !v)} size="sm" variant="ghost">
              <Codicon name="gear" /> Settings
            </Button>
            {settings && (
              <section id="fast-settings" aria-label="Fast settings" className="styx-fast-settings">
                <label>Appearance
                  <select value={mode} onChange={event => setMode(event.target.value as typeof mode)}>
                    <option value="system">System</option>
                    <option value="light">Light</option>
                    <option value="dark">Dark</option>
                  </select>
                </label>
                <a href={`/?${official}`}>Open full Hermes</a>
                <a href="/_styx/tui">Open terminal (TUI)</a>
                <a href={reconnectURL}>Reconnect to Hermes</a>
                <form method="post" action="/logout" onSubmit={() => {
                  try { sessionStorage.removeItem(webappSessionKey('')) } catch {}
                }}>
                  <button type="submit">Sign out of Styx</button>
                </form>
              </section>
            )}
          </header>
          <aside id="fast-sessions" aria-label="Sessions" className="styx-fast-rail"><WiredPane part="sidebar" /></aside>
          <main className="styx-fast-chat">
            {error ? (
              <p className="p-4 text-sm" role="alert">
                Fast could not connect. <a className="underline" href={reconnectURL}>Reconnect</a>
                {' or '}<a className="underline" href={`/?${official}`}>open full Hermes</a>.
              </p>
            ) : <WiredPane part="chatRoutes" />}
          </main>
        </div>
      </ContribWiring>
    </SidebarProvider>
  )
}
