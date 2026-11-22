import { cpSync, existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

import { prune } from './prune.mjs'

const revision = '4162ecf11f611400fa6e5c42d2f360188ce50b39'
const [checkout, output, generation] = process.argv.slice(2)
if (!checkout || !output || !/^[0-9a-f]{24}$/.test(generation ?? '')) {
  throw new Error('Usage: node build.mjs <Hermes checkout> <empty output dir> <generation>')
}
const root = resolve(checkout)
const git = (...args) => execFileSync('git', ['-C', root, ...args], { encoding: 'utf8' })
if (git('rev-parse', 'HEAD').trim() !== revision || git('status', '--porcelain', '--untracked-files=no')) {
  throw new Error(`Fast requires a clean Hermes source checkout at ${revision}. The installed Webapp has not been changed.`)
}
const out = resolve(output)
const sourceApp = join(root, 'apps/desktop')
const depsRoot = ['.build/webapp-workspace', '.'].map(p => join(root, p)).find(p => {
  try {
    return existsSync(join(p, 'apps/desktop/node_modules/vite/package.json')) &&
      readFileSync(join(p, 'pnpm-lock.yaml'), 'utf8') === readFileSync(join(root, 'pnpm-lock.yaml'), 'utf8')
  } catch { return false }
})
if (!depsRoot) {
  throw new Error('Hermes Webapp build dependencies are missing. Run `hermes webapp --build-only` first.')
}
// Keep source edits and build caches out of the installed Hermes checkout.
const work = mkdtempSync(join(dirname(out), 'fast-workspace-'))
try {
  const app = join(work, 'apps/desktop')
  const shared = join(work, 'apps/shared')
  mkdirSync(app, { recursive: true })
  mkdirSync(shared, { recursive: true })
  const copy = (from, to) => cpSync(from, to, { recursive: true })
  for (const name of ['index.html', 'package.json', 'vite.config.ts', 'src', 'scripts', 'electron']) {
    copy(join(sourceApp, name), join(app, name))
  }
  mkdirSync(join(app, 'public'))
  for (const name of ['apple-touch-icon.png', 'nous-girl.png', 'nous-girl-dark.png']) {
    copy(join(sourceApp, 'public', name), join(app, 'public', name))
  }
  for (const name of ['package.json', 'src']) copy(join(root, 'apps/shared', name), join(shared, name))
  for (const prefix of ['apps/desktop', 'apps/shared', '']) {
    const src = join(depsRoot, prefix, 'node_modules')
    if (existsSync(src)) symlinkSync(src, join(work, prefix, 'node_modules'), 'junction')
  }
  const local = dirname(fileURLToPath(import.meta.url))
  const overlay = join(app, 'src/styx-fast')
  mkdirSync(overlay)
  for (const name of ['FastWorkspace.tsx', 'FastSidebar.tsx', 'FastPromptNotice.tsx', 'workspace.css']) {
    copy(join(local, name), join(overlay, name))
  }
  prune((file, transform) => {
    const path = join(app, file)
    try {
      writeFileSync(path, transform(readFileSync(path, 'utf8').replace(/\r\n/g, '\n')))
    } catch (error) {
      throw new Error(`${file}: ${error.message}`, { cause: error })
    }
  })
  const require = createRequire(join(app, 'package.json'))
  const { build } = await import(pathToFileURL(require.resolve('vite')).href)
  await build({
    root: app,
    base: `/_styx/fast/build/${generation}/`,
    configLoader: 'runner',
    cacheDir: join(work, 'vite-cache'),
    build: { outDir: out, emptyOutDir: false },
  })
  copy(join(root, 'LICENSE'), join(out, 'LICENSE-hermes'))
} finally {
  rmSync(work, { recursive: true, force: true })
}
