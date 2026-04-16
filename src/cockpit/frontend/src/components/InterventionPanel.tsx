import { useState } from 'react'

import type { InterventionKind, InterventionRecord } from '../types'

const KINDS: { kind: InterventionKind; label: string; placeholder: string }[] = [
  { kind: 'reject', label: 'Reject', placeholder: 'user rejected this hypothesis' },
  { kind: 'approve', label: 'Approve', placeholder: 'user approved this direction' },
  { kind: 'redirect', label: 'Redirect', placeholder: 'redirect toward a different question or baseline' },
  { kind: 'constrain', label: 'Constrain', placeholder: 'respect this constraint before continuing' },
  { kind: 'halt', label: 'Halt', placeholder: 'stop and wait for further instruction' },
]

interface InterventionPanelProps {
  apiBase: string
  interventions: InterventionRecord[]
  selectedNodeId: string | null
  onQueued: () => void
}

export function InterventionPanel({
  apiBase,
  interventions,
  selectedNodeId,
  onQueued,
}: InterventionPanelProps) {
  const [payload, setPayload] = useState('')
  const [activeKind, setActiveKind] = useState<InterventionKind>('reject')
  const [notice, setNotice] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const submit = async (kind: InterventionKind) => {
    if (!selectedNodeId) {
      setNotice('Select a node before sending an intervention.')
      return
    }

    const defaultPayload = KINDS.find((item) => item.kind === kind)?.placeholder ?? ''
    const message = payload.trim() || defaultPayload
    setIsSubmitting(true)

    try {
      const response = await fetch(new URL('/intervene', `${apiBase}/`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, target: selectedNodeId, payload: message }),
      })

      if (!response.ok) {
        setNotice('Cockpit backend is unavailable.')
        return
      }

      setNotice(`Queued ${kind} for ${selectedNodeId}.`)
      setPayload('')
      onQueued()
    } catch {
      setNotice('Cockpit backend is unavailable.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <section className="flex h-full flex-col rounded-[28px] border border-white/8 bg-[#111713]/85">
      <header className="border-b border-white/6 px-5 py-4">
        <p className="mono text-[11px] uppercase tracking-[0.28em] text-[#8e9889]">Intervention queue</p>
        <h2 className="mt-2 text-lg font-semibold text-[#e5eadf]">Guide the next turn</h2>
        <p className="mt-2 text-sm text-[#a6aea0]">
          Selected target: <span className="mono text-[#d4dccd]">{selectedNodeId ?? 'none'}</span>
        </p>
      </header>
      <div className="flex flex-1 flex-col gap-4 px-5 py-5">
        <div className="grid grid-cols-2 gap-2 xl:grid-cols-3">
          {KINDS.map((item) => (
            <button
              key={item.kind}
              className={`rounded-2xl border px-3 py-3 text-left transition ${
                activeKind === item.kind
                  ? 'border-[#d5dfb8]/40 bg-[#d5dfb8]/10 text-[#eef5db]'
                  : 'border-white/8 bg-white/[0.03] text-[#b7c0b1]'
              }`}
              onClick={() => {
                setActiveKind(item.kind)
                setNotice('')
              }}
              type="button"
            >
              <span className="mono text-[11px] uppercase tracking-[0.18em]">{item.label}</span>
            </button>
          ))}
        </div>

        <textarea
          className="min-h-32 flex-1 rounded-[22px] border border-white/8 bg-[#0f1411] px-4 py-4 text-sm leading-6 text-[#dbe2d5] outline-none placeholder:text-[#6d766d]"
          onChange={(event) => setPayload(event.target.value)}
          placeholder={KINDS.find((item) => item.kind === activeKind)?.placeholder}
          value={payload}
        />

        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-[#8e9889]">
            {notice || 'Queued interventions are delivered on the next prompt or turn stop.'}
          </p>
          <button
            className="mono rounded-full border border-[#d5dfb8]/30 bg-[#d5dfb8]/12 px-4 py-2 text-[11px] uppercase tracking-[0.24em] text-[#eef5db] disabled:opacity-50"
            disabled={isSubmitting || !selectedNodeId}
            onClick={() => void submit(activeKind)}
            type="button"
          >
            {isSubmitting ? 'queueing' : 'queue action'}
          </button>
        </div>

        <div className="rounded-[22px] border border-white/8 bg-white/[0.03] px-4 py-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="mono text-[11px] uppercase tracking-[0.22em] text-[#879281]">Recent queue</p>
              <p className="mt-2 text-sm text-[#a6aea0]">
                The latest instructions waiting for delivery into the next Claude turn.
              </p>
            </div>
            <span className="mono rounded-full border border-white/8 px-2 py-1 text-[11px] text-[#d0d6cb]">
              {interventions.length}
            </span>
          </div>

          <div className="mt-4 space-y-3">
            {interventions.length === 0 ? (
              <p className="text-sm text-[#8e9889]">No interventions queued yet.</p>
            ) : (
              interventions.slice(0, 4).map((item) => (
                <div key={item.id} className="rounded-2xl border border-white/8 bg-[#0f1411] px-3 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="mono text-[11px] uppercase tracking-[0.18em] text-[#dbe2d5]">{item.kind}</p>
                    <p className="mono text-[11px] uppercase tracking-[0.16em] text-[#7f897e]">
                      {new Date(item.created_at).toLocaleString()}
                    </p>
                  </div>
                  <p className="mt-2 text-sm text-[#dbe2d5]">{item.payload}</p>
                  <p className="mt-2 text-xs text-[#8e9889]">
                    target: <span className="mono">{item.target ?? 'none'}</span>
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
