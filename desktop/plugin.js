/**
 * Styx status chip. Opt-in (Capabilities → Plugins).
 */
import { cn, host, Tip, usePluginI18n, useQuery } from '@hermes/plugin-sdk'
import { jsx } from 'react/jsx-runtime'

const ID = 'styx'

function Chip() {
  const t = usePluginI18n(ID)
  const { data } = useQuery({
    queryKey: ['styx', 'status'],
    queryFn: fetchStatus,
    refetchInterval: 8000,
  })
  const up = !!(data && data.running)

  return jsx(Tip, {
    label: t(up ? 'upTip' : 'downTip'),
    children: jsx('button', {
      type: 'button',
      className: cn(
        'inline-flex h-full items-center gap-1 px-1.5 text-[0.6875rem] transition-colors',
        up ? 'text-(--ui-accent)' : 'text-(--ui-text-tertiary) hover:text-foreground'
      ),
      onClick: () => host.notify({
        kind: 'info',
        message: up ? t('upTip') : t('downTip'),
      }),
      children: up ? 'styx ●' : 'styx',
    }),
  })
}

async function fetchStatus() {
  try {
    const r = await fetch('/api/plugins/styx/status')
    if (!r.ok) return { running: false }
    return await r.json()
  } catch {
    return { running: false }
  }
}

export default {
  id: ID,
  name: 'Styx',
  defaultEnabled: false,
  register(ctx) {
    ctx.i18n.register({
      en: {
        upTip: 'Styx onion gate is up',
        downTip: 'Styx onion gate is down',
      },
      fr: {
        upTip: 'Styx est ouvert',
        downTip: 'Styx est fermé',
      },
    })
    ctx.register({
      id: 'styx-chip',
      area: 'statusBar.right',
      order: 80,
      render: Chip,
    })
  },
}
