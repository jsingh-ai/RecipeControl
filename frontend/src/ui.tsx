import { ReactNode } from 'react'

export function Alert({ tone = 'info', children, role }: { tone?: 'info' | 'warning' | 'error' | 'success'; children: ReactNode; role?: 'alert' | 'status' }) {
  const icon = { info: 'ⓘ', warning: '⚠', error: '✕', success: '✓' }[tone]
  return <div className={'alert alert-' + tone} role={role ?? (tone === 'error' ? 'alert' : 'status')}><span aria-hidden="true">{icon}</span><div>{children}</div></div>
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="max-w-md"><div className="mx-auto mb-3 grid size-10 place-items-center rounded-full border border-slate-700 bg-slate-900 text-cyan-300" aria-hidden="true">◇</div><h2 className="text-lg font-bold">{title}</h2><p className="mt-1 text-sm text-slate-400">{description}</p>{action && <div className="mt-4">{action}</div>}</div></div>
}

export function LoadingSkeleton({ label = 'Loading' }: { label?: string }) {
  return <div className="panel space-y-3" role="status" aria-label={label}><span className="sr-only">{label}</span><div className="skeleton h-5 w-40" /><div className="skeleton h-12 w-full" /><div className="skeleton h-12 w-4/5" /></div>
}

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toUpperCase()
  const style = normalized === 'COMPLETE' ? 'badge-good' : normalized === 'FAILED' ? 'badge-bad' : normalized === 'RUNNING' || normalized === 'QUEUED' ? 'border-amber-600/50 bg-amber-950 text-amber-200' : 'badge-muted'
  const icon = normalized === 'COMPLETE' ? '✓' : normalized === 'FAILED' ? '✕' : normalized === 'RUNNING' || normalized === 'QUEUED' ? '◷' : '○'
  return <span className={'badge ' + style}><span aria-hidden="true">{icon}</span>{status}</span>
}
