import { useState } from 'react'
import RuleBuilder from './RuleBuilder'
import TimelinePage from './TimelinePage'

export default function App() {
  const [page, setPage] = useState<'timeline' | 'rules'>('timeline')
  return <div className="min-h-screen">
    <nav className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-800 bg-slate-950/95 px-6 py-3 backdrop-blur">
      <button className="p-0 text-xl font-bold tracking-tight" onClick={() => setPage('timeline')}>Recipe<span className="text-cyan-400">Control</span></button>
      <div className="flex gap-2"><button className={page === 'timeline' ? 'bg-slate-800' : ''} onClick={() => setPage('timeline')}>Timeline</button><button className={page === 'rules' ? 'bg-slate-800' : ''} onClick={() => setPage('rules')}>Rule Builder</button></div>
    </nav>
    {page === 'timeline' ? <TimelinePage /> : <RuleBuilder />}
  </div>
}
