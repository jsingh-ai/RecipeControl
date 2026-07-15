import { useState } from 'react'
import RuleBuilder from './RuleBuilder'
import TimelinePage from './TimelinePage'

export default function App() {
  const [page, setPage] = useState<'timeline' | 'rules'>('timeline')
  return <div className="min-h-screen">
    <nav className="sticky top-0 z-20 border-b border-slate-800/90 bg-slate-950/90 px-4 py-3 shadow-lg shadow-black/20 backdrop-blur-xl sm:px-6">
      <div className="mx-auto flex max-w-[1760px] items-center justify-between gap-4">
        <button className="button-quiet p-1 text-xl font-black tracking-tight" onClick={() => setPage('timeline')}>Recipe<span className="text-cyan-300">Control</span><span className="ml-2 hidden text-xs font-semibold uppercase tracking-widest text-slate-500 sm:inline">Historical operations</span></button>
        <div className="flex rounded-xl border border-slate-700 bg-slate-900 p-1" aria-label="Application sections"><button aria-current={page === 'timeline' ? 'page' : undefined} className={page === 'timeline' ? 'bg-cyan-400 text-slate-950' : 'button-quiet'} onClick={() => setPage('timeline')}>Timeline</button><button aria-current={page === 'rules' ? 'page' : undefined} className={page === 'rules' ? 'bg-cyan-400 text-slate-950' : 'button-quiet'} onClick={() => setPage('rules')}>Rule Builder</button></div>
      </div>
    </nav>
    {page === 'timeline' ? <TimelinePage /> : <RuleBuilder />}
  </div>
}
