import { useDeferredValue, useState } from 'react'

import type { FailureRecord } from '../types'

type SortKey = 'last_seen' | 'seen_count' | 'trigger'

interface VerificationTableProps {
  rows: FailureRecord[]
}

export function VerificationTable({ rows }: VerificationTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('last_seen')
  const [descending, setDescending] = useState(true)
  const deferredRows = useDeferredValue(rows)

  const sortedRows = [...deferredRows].sort((left, right) => {
    if (sortKey === 'seen_count') {
      return descending ? right.seen_count - left.seen_count : left.seen_count - right.seen_count
    }

    if (sortKey === 'trigger') {
      return descending
        ? right.trigger.localeCompare(left.trigger)
        : left.trigger.localeCompare(right.trigger)
    }

    return descending
      ? right.last_seen.localeCompare(left.last_seen)
      : left.last_seen.localeCompare(right.last_seen)
  })

  const applySort = (nextKey: SortKey) => {
    if (nextKey === sortKey) {
      setDescending((value) => !value)
      return
    }
    setSortKey(nextKey)
    setDescending(true)
  }

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-[28px] border border-white/8 bg-[#121814]/85">
      <header className="flex items-center justify-between border-b border-white/6 px-5 py-4">
        <div>
          <p className="mono text-[11px] uppercase tracking-[0.28em] text-[#8e9889]">Failure ledger</p>
          <h2 className="mt-2 text-lg font-semibold text-[#e5eadf]">Recent verification scars</h2>
        </div>
        <div className="flex gap-2 text-[11px]">
          <button
            className="rounded-full border border-white/10 px-3 py-1 text-[#a9b1a3]"
            onClick={() => applySort('last_seen')}
            type="button"
          >
            latest
          </button>
          <button
            className="rounded-full border border-white/10 px-3 py-1 text-[#a9b1a3]"
            onClick={() => applySort('seen_count')}
            type="button"
          >
            frequency
          </button>
        </div>
      </header>
      <div className="overflow-auto px-3 pb-3">
        <table className="min-w-full border-separate border-spacing-y-2 text-left text-sm">
          <thead className="mono text-[11px] uppercase tracking-[0.22em] text-[#798377]">
            <tr>
              <th className="px-3 py-3">
                <button onClick={() => applySort('trigger')} type="button">
                  trigger
                </button>
              </th>
              <th className="px-3 py-3">symptom</th>
              <th className="px-3 py-3">resolution</th>
              <th className="px-3 py-3">count</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.length === 0 ? (
              <tr>
                <td className="px-3 py-4 text-[#90998b]" colSpan={4}>
                  No failure signatures recorded yet.
                </td>
              </tr>
            ) : (
              sortedRows.map((row) => (
                <tr key={row.failure_id} className="overflow-hidden rounded-2xl bg-white/[0.03] text-[#cbd2c7]">
                  <td className="max-w-[16rem] rounded-l-2xl px-3 py-3 align-top">
                    <p className="font-medium text-[#edf1e8]">{row.trigger}</p>
                    <p className="mono mt-1 text-[11px] uppercase tracking-[0.16em] text-[#818c7e]">
                      {new Date(row.last_seen).toLocaleString()}
                    </p>
                  </td>
                  <td className="max-w-[18rem] px-3 py-3 align-top text-[#b7c0b1]">
                    <p>{row.symptom}</p>
                    <p className="mt-2 text-xs leading-5 text-[#8e9889]">
                      Root cause: {row.root_cause || 'not captured yet'}
                    </p>
                  </td>
                  <td className="max-w-[18rem] px-3 py-3 align-top text-[#b7c0b1]">{row.resolution || 'pending'}</td>
                  <td className="rounded-r-2xl px-3 py-3 align-top">
                    <span className="mono rounded-full border border-white/8 px-2 py-1 text-[11px] text-[#d0d6cb]">
                      {row.seen_count}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
