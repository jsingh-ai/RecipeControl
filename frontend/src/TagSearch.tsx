import { useInfiniteQuery } from '@tanstack/react-query'
import { KeyboardEvent, useEffect, useId, useMemo, useState } from 'react'
import { api, Tag, TagPage } from './api'

type Props = {
  machineId: number
  value?: Tag | null
  onSelect: (tag: Tag) => void
  disabled?: boolean
  label: string
  exclude?: string[]
}

export default function TagSearch({ machineId, value, onSelect, disabled, label, exclude = [] }: Props) {
  const listId = useId()
  const [input, setInput] = useState(value?.display_name ?? '')
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  useEffect(() => setInput(value?.display_name ?? ''), [value?.key, value?.display_name])
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(input === value?.display_name ? '' : input.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [input, value?.display_name])
  const tags = useInfiniteQuery({
    queryKey: ['tag-search', machineId, query],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api<TagPage>(`/machines/${machineId}/tags?q=${encodeURIComponent(query)}&limit=25&offset=${pageParam}`),
    getNextPageParam: (page) => page.has_more ? page.offset + page.limit : undefined,
    enabled: Boolean(machineId) && open && !disabled,
  })
  const options = useMemo(() => tags.data?.pages.flatMap((page) => page.items).filter((tag) => !exclude.includes(tag.key)) ?? [], [tags.data, exclude])
  function choose(tag: Tag) {
    onSelect(tag)
    setInput(tag.display_name)
    setOpen(false)
  }
  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') { event.preventDefault(); setOpen(true); setActive((index) => Math.min(index + 1, Math.max(0, options.length - 1))) }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActive((index) => Math.max(0, index - 1)) }
    if (event.key === 'Enter' && open && options[active]) { event.preventDefault(); choose(options[active]) }
    if (event.key === 'Escape') setOpen(false)
  }
  return <div className="relative">
    <label>{label}
      <input role="combobox" aria-expanded={open} aria-controls={listId} aria-autocomplete="list" aria-activedescendant={options[active] ? `${listId}-${options[active].key}` : undefined} value={input} disabled={disabled} placeholder="Search display name, node ID, or OPC path" onFocus={() => setOpen(true)} onChange={(event) => { setInput(event.target.value); setOpen(true); setActive(0) }} onKeyDown={keyDown} />
    </label>
    {open && <div id={listId} role="listbox" className="absolute z-30 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-slate-600 bg-slate-950 p-1 shadow-2xl">
      {tags.isLoading && <p className="p-3 text-sm text-slate-400">Loading variables…</p>}
      {tags.isError && <p role="alert" className="p-3 text-sm text-red-300">Source tag search failed.</p>}
      {!tags.isLoading && !tags.isError && options.length === 0 && <p className="p-3 text-sm text-slate-400">No enabled tags match.</p>}
      {options.map((tag, index) => <button id={`${listId}-${tag.key}`} role="option" aria-selected={value?.key === tag.key} type="button" key={tag.key} className={`block w-full rounded p-2 text-left ${active === index ? 'bg-slate-700' : ''}`} onMouseEnter={() => setActive(index)} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(tag)}><span className="block font-medium">{tag.display_name}</span><span className="block text-xs text-slate-400">{tag.raw_data_type || 'Unknown OPC type'} · {tag.data_kind} · {tag.node_id || tag.key}</span></button>)}
      {tags.hasNextPage && <button type="button" className="button-secondary m-2" disabled={tags.isFetchingNextPage} onMouseDown={(event) => event.preventDefault()} onClick={() => tags.fetchNextPage()}>{tags.isFetchingNextPage ? 'Loading…' : 'Load more'}</button>}
    </div>}
  </div>
}
