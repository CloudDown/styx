import { useStore } from '@nanostores/react'
import { useMemo } from 'react'

import { sessionAwaitingInput } from '@/store/prompts'

export function FastPromptNotice({ sessionId }: { sessionId: string | null }) {
  const blocked = useStore(useMemo(() => sessionAwaitingInput(sessionId), [sessionId]))
  if (!blocked) return null

  const query = new URLSearchParams(location.search)
  query.set('_styx_view', 'hermes')
  return (
    <aside className="styx-fast-waiting" role="status">
      Hermes needs your input. <a className="underline" href={`/?${query}`}>Open full Hermes</a> and reopen this session.
    </aside>
  )
}
