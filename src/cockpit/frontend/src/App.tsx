import { startTransition, useEffect, useEffectEvent, useState } from 'react'

import { HypothesisGraph } from './components/HypothesisGraph'
import { InterventionPanel } from './components/InterventionPanel'
import { VerificationTable } from './components/VerificationTable'
import { useWebSocket } from './hooks/useWebSocket'
import type { FailureRecord, GraphResponse, WsEvent } from './types'

const API_BASE = 'http://localhost:7777'
const WS_BASE = 'ws://localhost:7777/ws/state'

const EMPTY_GRAPH: GraphResponse = { nodes: [], edges: [] }

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    throw new Error(`Failed to load ${path}`)
  }
  return (await response.json()) as T
}

export default function App() {
  const [graph, setGraph] = useState<GraphResponse>(EMPTY_GRAPH)
  const [failures, setFailures] = useState<FailureRecord[]>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [connectionLabel, setConnectionLabel] = useState('offline')

  const refreshAll = useEffectEvent(async () => {
    try {
      const [nextGraph, nextFailures] = await Promise.all([
        fetchJson<GraphResponse>('/graph'),
        fetchJson<FailureRecord[]>('/failures'),
      ])

      startTransition(() => {
        setGraph(nextGraph)
        setFailures(nextFailures)
        if (selectedNodeId && !nextGraph.nodes.some((node) => node.node_id === selectedNodeId)) {
          setSelectedNodeId(null)
        }
      })
    } catch {
      setConnectionLabel('backend down')
    }
  })

  useEffect(() => {
    void refreshAll()
  }, [])

  useWebSocket(WS_BASE, {
    onOpen: () => setConnectionLabel('live'),
    onClose: () => setConnectionLabel('reconnecting'),
    onError: () => setConnectionLabel('offline'),
    onMessage: (event) => {
      const message = JSON.parse(event.data) as WsEvent
      if (['graph_delta', 'failure_added', 'turn_end', 'intervention'].includes(message.kind)) {
        void refreshAll()
      }
    },
  })

  return (
    <main className="min-h-screen px-4 py-4 text-[#d8ddd2] md:px-5">
      <div className="mx-auto flex min-h-[calc(100vh-2rem)] max-w-[1600px] flex-col overflow-hidden rounded-[34px] border border-white/8 bg-[#0f1411]/88 shadow-[0_32px_120px_rgba(0,0,0,0.35)]">
        <header className="flex flex-col gap-3 border-b border-white/6 px-6 py-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <p className="mono text-[11px] uppercase tracking-[0.32em] text-[#8e9889]">Research cockpit</p>
            <h1 className="text-2xl font-semibold tracking-[-0.04em] text-[#f1f5ec] md:text-[2.4rem]">
              Observe the frontier, then intervene with intent.
            </h1>
            <p className="max-w-3xl text-sm leading-6 text-[#9ca598] md:text-base">
              Hypotheses stream in from memory, failures accumulate as evidence, and the next prompt can be steered without leaving the workspace.
            </p>
          </div>
          <div className="grid gap-2 text-sm text-[#aeb7a8] sm:grid-cols-3">
            <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
              <p className="mono text-[11px] uppercase tracking-[0.18em] text-[#7d877c]">nodes</p>
              <p className="mt-2 text-xl font-semibold text-[#eef2e8]">{graph.nodes.length}</p>
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
              <p className="mono text-[11px] uppercase tracking-[0.18em] text-[#7d877c]">failures</p>
              <p className="mt-2 text-xl font-semibold text-[#eef2e8]">{failures.length}</p>
            </div>
            <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
              <p className="mono text-[11px] uppercase tracking-[0.18em] text-[#7d877c]">socket</p>
              <p className="mt-2 text-xl font-semibold text-[#eef2e8]">{connectionLabel}</p>
            </div>
          </div>
        </header>

        <div className="flex flex-1 flex-col gap-4 p-4 xl:flex-row">
          <div className="min-h-[420px] xl:w-3/5">
            <HypothesisGraph
              connectionLabel={connectionLabel}
              graph={graph}
              onSelectNode={setSelectedNodeId}
              selectedNodeId={selectedNodeId}
            />
          </div>

          <div className="flex flex-1 flex-col gap-4 xl:w-2/5">
            <div className="min-h-[280px] flex-1">
              <VerificationTable rows={failures} />
            </div>
            <div className="min-h-[280px] flex-1">
              <InterventionPanel onQueued={() => void refreshAll()} selectedNodeId={selectedNodeId} />
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}

