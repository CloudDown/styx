// Apply a deliberately versioned subtraction to a private copy of the renderer.
// Starting anchors must match exactly once on the pinned source; a missing
// anchor must fail the build instead of silently reintroducing a screen.
export function prune(edit) {
  edit('vite.config.ts', replace('cachedCompilerPass(command), ', ''))
  edit('index.html', replace('<title>Hermes</title>', '<title>Hermes Fast</title>'))
  // This is Hermes' native tab-grant mode, not an anonymous client. The
  // Styx launch redirects to the official Webapp for account sign-in providers.
  edit('index.html', replace('    <script>\n', `    <script>
      window.__HERMES_UI_SURFACE__ = 'webapp'
      window.__HERMES_BASE_PATH__ = ''
      window.__HERMES_AUTH_REQUIRED__ = false
      window.__HERMES_INITIAL_PROFILE__ = new URLSearchParams(location.search).get('profile') || ''
`))
  edit('src/main.tsx', replace("import App from './app'", "import App from './styx-fast/FastWorkspace'"))
  edit('src/main.tsx', between("if (winParam === 'overlay')", '  // CSS animations', '{\n'))
  edit('src/main.tsx', drop("import './store/keep-awake'\n"))
  edit('src/main.tsx', replace("import { ProfileI18nProvider as I18nProvider } from './i18n/profile-provider'",
    "import { I18nProvider } from './i18n/context'"))
  edit('src/i18n/catalog.ts', between('  zh,\n', '\n}', '  fr'))
  edit('src/app/gateway/hooks/use-gateway-boot.ts', text => {
    const matches = text.match(/^[ \t]*void warnIfTerminalBackendUnavailable\(\)\n/gm)
    if (matches?.length !== 3) throw new Error('Unexpected terminal backend checks')
    return text.replace(/^[ \t]*void warnIfTerminalBackendUnavailable\(\)\n/gm, '')
  })
  edit('src/themes/context.tsx', between('  if (typo.fontUrl &&', '  // Inject / clear customCSS', ''))

  const wiring = 'src/app/contrib/wiring.tsx'
  edit(wiring, between('const AgentsView = lazy(', '// Surfaces (the four', ''))
  edit(wiring, drop('  useOpenKeybindsListener(navigate)\n'))
  edit(wiring, drop("  useFirstRunOnboarding(requestGateway, adoptSessionRoute, gatewayState === 'open')\n"))
  edit(wiring, between('  // Agent-driven preview routing', '  const {\n    archiveSession', ''))
  edit(wiring, between('  // Runs outside the selected ChatBar', '  // Clear a failed turn', ''))
  edit(wiring, between('  // Plugins hear the stream FIRST', '  useGatewayBoot({', ''))
  edit(wiring, replace('    handleGatewayEvent: handleGatewayEventWithPlugins,', '    handleGatewayEvent,'))
  edit(wiring, drop('      resetProjectTreeState()\n      closeAllTerminals()\n'))
  edit(wiring, between("  useEffect(() => {\n    if (gatewayState === 'open')", '  const activeIsMessaging', ''))
  edit(wiring, between('  // Electron-main / OS / cross-window integrations:', '  // Pin/unpin the selected session', ''))
  edit(wiring, between('  useKeybinds({', '  // One owner-aware door', ''))
  edit(wiring, replace('    openSession(sessionId, navigate)\n', '    navigate(sessionRoute(sessionId))\n'))
  edit(wiring, replace('    onNewSessionInWorkspace: (path, owner) => startSessionInWorkspace(path, { openTab: true, owner }),', '    onNewSessionInWorkspace: () => startFreshSessionDraft({ workspaceTarget: null }),'))
  edit(wiring, between('  const terminalNode =', '  // The voice cap', ''))
  edit(wiring, between('  const api = useMemo<WiringApi>', '    </ContribWiringContext.Provider>', `  const api = useMemo<WiringApi>(() => ({ chatRoutes: chatRoutesNode, sidebar: sidebarNode, statusbar: null, terminal: null }), [chatRoutesNode, sidebarNode])
  return (
    <ContribWiringContext.Provider value={api}>
      {children}
      <NotificationStack />
      <ConfirmHost />
      <ExternalOpenFailedDialog />
`))
  edit(wiring, replace('    refreshCronJobs,\n', '    refreshCronJobs: noAuxiliaryRefresh,\n'))
  edit(wiring, replace('    refreshMessagingSessions,\n', '    refreshMessagingSessions: noAuxiliaryRefresh,\n'))
  edit(wiring, replace('export function ContribWiring', 'const noAuxiliaryRefresh = () => undefined\n\nexport function ContribWiring'))
  edit('src/app/contrib/hooks/use-background-sync.ts', drop('  useLiveWorkRoster()\n'))
  const sessionList = 'src/app/session/hooks/use-session-list-actions.ts'
  edit(sessionList, between('      // Cron *jobs* are', '    },\n    [profileScope, refreshCronJobs]', ''))
  edit(sessionList, between('  // A Bot Mode switch', '  return {\n    loadMoreMessagingForPlatform,', ''))
  // Only the two official wired panes are reachable. Keep their native
  // session, model, transcript and audio hooks; omit Desktop's app pages.
  const surfaces = 'src/app/contrib/surfaces.tsx'
  edit(surfaces, between('const ArtifactsView = lazy(', 'export function LegacySessionRedirect', ''))
  edit(surfaces, replace("import { ChatSidebar } from '../chat/sidebar'", "import { FastSidebar } from '@/styx-fast/FastSidebar'"))
  edit(surfaces, replace("currentView: ComponentProps<typeof ChatSidebar>['currentView']", "currentView: string"))
  edit(surfaces, replace('<ChatSidebar currentView={currentView} {...latestActions} />', '<FastSidebar {...latestActions} />'))
  edit(surfaces, between('  // FULL-PAGE views', '      <Route element={<Navigate replace to={NEW_CHAT_ROUTE} />} path="new" />', `  return (
    <Routes>
      <Route element={chatView} index />
      <Route element={chatView} path=":sessionId" />
`))
  edit('src/app/shell/model-menu-panel.tsx', drop('      header={<LocalSetupMenuRow />}\n      includeMoa\n'))
  const modelOptions = 'src/app/shell/model-edit-submenu.tsx'
  edit(modelOptions, between('  const setFast =', '    <div className="px-2.5 py-3', '  return !reasoning ? (\n'))
  edit(modelOptions, between('      {unsupportedSpeed ? (', '      {reasoning ? (', ''))
  // The original dropdown, rename dialog and canonical delete guard remain.
  const menus = 'src/app/chat/sidebar/session-actions-menu.tsx'
  edit(menus, between('  const openItems:', '  const renameDialog', `  const renderItems = (kit: MenuKit) => (
    <>
      {renameable && renderActionItem(kit, {
        disabled: !sessionId, icon: 'edit', label: r.rename,
        onSelect: () => { suppressCloseFocusRef.current = true; setRenameOpen(true) }
      })}
      {onDelete && renderActionItem(kit, {
        disabled: !sessionId, icon: 'trash', label: t.common.delete,
        className: 'text-destructive focus:text-destructive', variant: 'destructive',
        onSelect: () => setDeleteOpen(true)
      })}
    </>
  )

`))
  const attachmentMenu = 'src/app/chat/composer/context-menu.tsx'
  edit(attachmentMenu, between('          <ContextMenuItem disabled={!onPickFolders}', '          <ContextMenuItem disabled={!onPickImages}', ''))
  edit(attachmentMenu, between('          <ContextMenuItem icon={Link}', '        </DropdownMenuContent>', ''))
  edit(attachmentMenu, drop('      <PromptSnippetsDialog onInsertText={onInsertText} onOpenChange={setSnippetsOpen} open={snippetsOpen} />\n'))
  edit(attachmentMenu, drop("  const [snippetsOpen, setSnippetsOpen] = useState(false)\n"))
  edit(attachmentMenu, drop("  const attachmentProviders = useComposerAttachmentProviders()\n"))
  const chat = 'src/app/chat/index.tsx'
  edit(chat, replace("import { PromptOverlays } from '@/components/prompt-overlays'",
    "import { FastPromptNotice } from '@/styx-fast/FastPromptNotice'"))
  edit(chat, replace('      <PromptOverlays sessionId={activeSessionId} />', '      <FastPromptNotice sessionId={activeSessionId} />'))
  edit(chat, drop('      <Backdrop />\n'))
  edit(chat, between('          {/* Vibe hearts', '          <ChatSwapOverlay', ''))
  edit(chat, drop('            onBranchInNewChat={onBranchInNewChat}\n'))
  edit(chat, drop('            onRestoreToMessage={onRestoreToMessage}\n'))
  edit('src/components/assistant-ui/thread/list.tsx', drop('          <PendingApprovalStack />\n'))
  const assistant = 'src/components/assistant-ui/thread/assistant-message.tsx'
  edit(assistant, drop('            <AssistantStatusSlot />\n            <AssistantPreviewEmbeds />\n'))
  edit(assistant, between('          {/* Sealed interims', '          <StreamingMarker />', ''))
  edit('src/components/assistant-ui/thread/message-parts.tsx', between(
    '  Reasoning: ReasoningTextPart,', '} as const',
    '  Reasoning: () => null,\n  Text: TimelineMarkdownText,\n  ToolGroup: () => null,\n  tools: { Fallback: () => null }\n'))
  const markdown = 'src/components/assistant-ui/markdown-text.tsx'
  edit(markdown, between('  // Keep code parsing enabled', '  const components = useMemo(', ''))
  edit(markdown, between('        // ```mermaid /', '      }) as StreamdownTextComponents', `
        SyntaxHighlighter: ({ code }: SyntaxHighlighterProps) => (
          <pre className="overflow-x-auto p-2"><code>{code}</code></pre>
        )
`))
  edit(markdown, drop('        plugins={plugins}\n'))
  // The upstream preview helpers are referenced from shared code even without
  // a review pane. Render plain text if one of those helpers renders a diff.
  edit('src/components/chat/diff-lines.tsx', replace("const LazySyntaxDiff = React.lazy(() => import('./syntax-diff'))",
    'const LazySyntaxDiff = ({ lines }: { lines: DiffLine[]; language: string }) => <DiffBody lines={lines} />'))
  edit('src/components/chat/shiki-highlighter.tsx', between('function importShikiBlock()', 'export function exceedsHighlightBudget', `export const LazyShiki: FC<CachedShikiBlockProps> = ({ code }) => <PlainShiki code={code} />

`))
  const serverRequests = 'src/app/session/hooks/use-message-stream/gateway-event/server-requests.ts'
  edit(serverRequests, between('export const SERVER_REQUEST_HANDLERS:', '/** Dispatch one server', `export const SERVER_REQUEST_HANDLERS: Record<string, Handler> = {
  approval,
  clarify,
  secret,
  sudo,
  'vault.code': vaultCode,
  'vault.save_login': vaultSaveLogin,
  'vault.unlock_prompt': vaultUnlockPrompt
}

`))
  edit(serverRequests, replace('  if (!handler) {\n    return false\n  }',
    "  if (!handler) {\n    if (!request.decline) return false\n    request.decline('Open the full Hermes Webapp for this action.')\n    return true\n  }"))
  const composer = 'src/app/chat/composer/index.tsx'
  edit(composer, between('  const busyInputMode = useBusyInputMode({', '  // Status items', '  const busyInputMode = null\n\n'))
  edit(composer, between('  const slash = useSlashCompletions({', '  const emoji =', '  const slash = { adapter: null, loading: false }\n'))
  edit('src/app/chat/composer/hooks/use-emoji-completions.ts', replace(
    "fetch('./emojibase/en/data.json')", "fetch(`${import.meta.env.BASE_URL}emojibase/en/data.json`)"))
  edit('src/app/chat/composer/hooks/use-emoji-completions.ts', replace(
    "fetch('./emojibase/en/shortcodes/emojibase.json')", "fetch(`${import.meta.env.BASE_URL}emojibase/en/shortcodes/emojibase.json`)"))
  edit(composer, between('    // Cmd/Ctrl+Enter queues a follow-up', "    if (event.key === 'Enter' && !event.shiftKey)", ''))
  edit(composer, between('      // Decide from the DOM, not React state.', '      submitDraft()', '      if (disabled || busy) return\n\n'))
  edit(composer, drop('            {isHelpHint && <HelpHint />}\n'))
  edit(composer, between('          {/* Aligned to the composer SURFACE', '          <ComposerPrimitive.Root', ''))
  edit(composer, between('                {codingRowShown && (', "                <div\n                  className", ''))
  edit(composer, drop('                  {queueEdit && editingQueuedPrompt && <QueuedEditBanner onExit={exitQueuedEdit} />}\n'))
  edit('src/app/chat/composer/voice-menu.tsx', between('        <DropdownMenuCheckboxItem\n          checked={autoSpeak}', '      </DropdownMenuContent>', ''))
  edit('src/app/chat/composer/voice-menu.tsx', between("  const wake = useStore($wakeWord)", '  const active =', '  const wakeListening = false\n  const dictating = state.voice.active || voiceStatus !== \'idle\'\n'))
  edit('src/app/chat/composer/voice-menu.tsx', between('  const wakeLabel =', '  return (', '  const triggerLabel = dictating ? dictationLabel : c.voiceControls\n\n'))
  edit('src/app/chat/composer/voice-menu.tsx', replace('label={wake.notice && !dictating ? `${triggerLabel} — ${wake.notice}` : triggerLabel}', 'label={triggerLabel}'))
  edit('src/app/chat/composer/voice-fan.tsx', between('  const items = useMemo<FanMenuItem[]>(', '  return <FanMenu', '  const items: FanMenuItem[] = []\n\n'))
  edit('src/app/chat/composer/voice-fan.tsx', between('  const wake = useStore($wakeWord)', '  const dictationLabel', "  const dictating = state.voice.active || voiceStatus !== 'idle'\n\n"))
  // The official composer still owns validation and editing. During an
  // admitted turn its only action is stop; it must never queue or steer.
  const controls = 'src/app/chat/composer/controls.tsx'
  edit(controls, replace('  const showStop = busy && !hasComposerPayload', '  const showStop = busy'))
  edit(controls, drop('      <WakeWordButton disabled={disabled} pausedForVoice />\n'))
  edit(controls, between('      {renderSteerButton(busy', '      {showVoicePrimary ? (', ''))
  edit(controls, replace('disabled={disabled || !canSubmit}', 'disabled={disabled || (!showStop && !canSubmit)}'))
  edit(controls, replace('  onDictate,\n  onQueue,', '  onDictate,\n  onStop,\n  onQueue,'))
  edit(controls, replace('  onDictate: () => void\n  onQueue:', '  onDictate: () => void\n  onStop: () => unknown\n  onQueue:'))
  // Don't reuse the Stop DOM node as Send if streaming settles mid-click.
  edit(controls, replace('            aria-label={showStop ? c.stop : sendLabel}',
    "            key={showStop ? 'stop' : 'send'}\n            aria-label={showStop ? c.stop : sendLabel}"))
  edit(controls, replace(`            onClick={() => recordAction(showStop ? 'composer.cancel' : 'composer.send', 'click')}
            onMouseDown={keepEditorFocus}
            type="submit"`, `            onClick={showStop ? event => { event.preventDefault(); void onStop() } : undefined}
            onMouseDown={keepEditorFocus}
            type={showStop ? 'button' : 'submit'}`))
  edit(composer, replace('      onDictate={dictate}\n      onQueue=', '      onDictate={dictate}\n      onStop={haltRun}\n      onQueue='))
  const submit = 'src/app/chat/composer/hooks/use-composer-submit.ts'
  edit(submit, between('  const submitWhileBusy =', '  const submitDraft =', ''))
  edit(submit, between('    if (refusedDuringSetup(text)) {', '    } else if (payloadPresent) {', '    if (busy) return\n\n    if (payloadPresent) {\n'))
  edit(submit, drop('    } else if (payloadPresent) {\n'))
  const prompts = 'src/app/session/hooks/use-prompt-actions/index.ts'
  edit(prompts, between('      const visibleText = sanitizeComposerInput(rawText).trim()', '      return await submitPromptText(rawText, options)', ''))
  edit(prompts, replace('    [executeSlashCommand, submitPromptText]', '    [submitPromptText]'))
  const userMessage = 'src/components/assistant-ui/thread/user-message.tsx'
  edit(userMessage, replace('  const readOnly = isWatchWindow()', '  const readOnly = true'))
  edit(userMessage, between('            <BranchPickerPrimitive.Root', '          </div>\n        </ActionBarPrimitive.Root>', ''))
}

function replace(from, to) {
  return text => {
    const at = single(text, from)
    return text.slice(0, at) + to + text.slice(at + from.length)
  }
}

const drop = from => replace(from, '')

function between(from, until, to) {
  return text => {
    const a = single(text, from), b = text.indexOf(until, a + from.length)
    if (b <= a) throw new Error(`Out-of-order anchor: ${from}`)
    return text.slice(0, a) + to + text.slice(b)
  }
}

function single(text, needle) {
  const at = text.indexOf(needle)
  if (at < 0 || at !== text.lastIndexOf(needle)) throw new Error(`Missing or ambiguous anchor: ${needle}`)
  return at
}
