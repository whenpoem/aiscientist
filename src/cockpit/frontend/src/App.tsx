import { startTransition, useEffect, useEffectEvent, useRef, useState } from 'react'

import { resolveApiBase, resolveWsUrl } from './config'
import { HypothesisGraph } from './components/HypothesisGraph'
import { InterventionPanel } from './components/InterventionPanel'
import { VerificationTable } from './components/VerificationTable'
import { useWebSocket } from './hooks/useWebSocket'
import type { CockpitStateResponse, WsEvent } from './types'

const API_BASE = resolveApiBase()
const WS_BASE = resolveWsUrl(API_BASE)

const EMPTY_STATE: CockpitStateResponse = {
  graph: { nodes: [], edges: [] },
  failures: [],
  interventions: [],
  meta: {
    api_base_url: API_BASE,
    ws_url: WS_BASE,
    last_event_id: 0,
    mcp: { transport: 'http', url: `${API_BASE}/mcp` },
  },
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    throw new Error(`Failed to load ${path}`)
  }
  return (await response.json()) as T
}

export default function App() {
  const [cockpitState, setCockpitState] = useState<CockpitStateResponse>(EMPTY_STATE)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [streamLabel, setStreamLabel] = useState('offline')
  const [syncLabel, setSyncLabel] = useState('loading')
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null)
  const [errorNotice, setErrorNotice] = useState('')
  const [isRefreshing, setIsRefreshing] = useState(false)
  const refreshPromiseRef = useRef<Promise<void> | null>(null)
  const refreshQueuedRef = useRef(false)

  const graph = cockpitState.graph
  const failures = cockpitState.failures
  const interventions = cockpitState.interventions
  const meta = cockpitState.meta

  const refreshAll = useEffectEvent(async () => {
    if (refreshPromiseRef.current) {
      refreshQueuedRef.current = true
      await refreshPromiseRef.current
      return
    }

    const refreshTask = (async () => {
      setIsRefreshing(true)
      setSyncLabel((current) => (current === 'loading' ? current : 'syncing'))

      try {
        const nextState = await fetchJson<CockpitStateResponse>('/state')

        startTransition(() => {
          setCockpitState(nextState)
          if (selectedNodeId && !nextState.graph.nodes.some((node) => node.node_id === selectedNodeId)) {
            setSelectedNodeId(null)
          }
        })
        setLastUpdatedAt(new Date().toLocaleTimeString())
        setErrorNotice('')
        setSyncLabel('synced')
      } catch {
        setSyncLabel('degraded')
        setErrorNotice('Cockpit backend is not responding. The dashboard will keep retrying.')
      } finally {
        setIsRefreshing(false)
      }
    })()

    refreshPromiseRef.current = refreshTask

    try {
      await refreshTask
    } finally {
      refreshPromiseRef.current = null

      if (refreshQueuedRef.current) {
        refreshQueuedRef.current = false
        void refreshAll()
      }
    }
  })

  useEffect(() => {
    void refreshAll()
    const intervalId = window.setInterval(() => {
      void refreshAll()
    }, 15000)

    return () => window.clearInterval(intervalId)
  }, [])

  useWebSocket(meta.ws_url || WS_BASE, {
    onOpen: () => {
      setStreamLabel('live')
      void refreshAll()
    },
    onClose: () => setStreamLabel('reconnecting'),
    onError: () => setStreamLabel('offline'),
    onMessage: (event) => {
      let message: WsEvent
      try {
        message = JSON.parse(event.data) as WsEvent
      } catch {
        setSyncLabel('degraded')
        return
      }

      if (
        ['graph_delta', 'failure_added', 'turn_end', 'intervention'].includes(message.kind) ||
        message.id > meta.last_event_id
      ) {
        void refreshAll()
      }
    },
    retryDelayMs: 1000,
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
          <div className="flex flex-col gap-3 lg:items-end">
            <button
              className="mono rounded-full border border-white/10 bg-white/[0.03] px-4 py-2 text-[11px] uppercase tracking-[0.2em] text-[#dbe2d5] disabled:opacity-50"
              disabled={isRefreshing}
              onClick={() => void refreshAll()}
              type="button"
            >
              {isRefreshing ? 'refreshing' : 'refresh state'}
            </button>
            <div className="grid gap-2 text-sm text-[#aeb7a8] sm:grid-cols-4">
              <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
                <p className="mono text-[11px] uppercase tracking-[0.18em] text-[#7d877c]">nodes</p>
                <p className="mt-2 text-xl font-semibold text-[#eef2e8]">{graph.nodes.length}</p>
              </div>
              <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
                <p className="mono text-[11px] uppercase tracking-[0.18em] text-[#7d877c]">failures</p>
                <p className="mt-2 text-xl font-semibold text-[#eef2e8]">{failures.length}</p>
              </div>
              <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
                <p className="mono text-[11px] uppercase tracking-[0.18em] text-[#7d877c]">stream</p>
                <p className="mt-2 text-xl font-semibold text-[#eef2e8]">{streamLabel}</p>
              </div>
              <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3">
                <p className="mono text-[11px] uppercase tracking-[0.18em] text-[#7d877c]">mcp</p>
                <p className="mt-2 text-sm font-semibold text-[#eef2e8]">{meta.mcp.transport}</p>
                <p className="mono mt-1 text-[11px] text-[#8e9889]">/mcp</p>
              </div>
            </div>
          </div>
        </header>

        {errorNotice ? (
          <div className="border-b border-[#6f2c30] bg-[#311619]/70 px-6 py-3 text-sm text-[#f1d4d8]">
            {errorNotice}
          </div>
        ) : null}

        <div className="flex min-h-0 flex-1 flex-col gap-4 p-4 xl:flex-row">
          <div className="min-h-[420px] min-w-0 xl:w-3/5">
            <HypothesisGraph
              connectionLabel={`${streamLabel} / ${syncLabel}`}
              graph={graph}
              onSelectNode={setSelectedNodeId}
              selectedNodeId={selectedNodeId}
            />
          </div>

          <div className="flex min-h-0 flex-1 flex-col gap-4 xl:w-2/5">
            <div className="min-h-[280px] min-h-0 flex-1">
              <VerificationTable rows={failures} />
            </div>
            <div className="min-h-[280px] min-h-0 flex-1">
              <InterventionPanel
                apiBase={meta.api_base_url || API_BASE}
                interventions={interventions}
                onQueued={() => void refreshAll()}
                selectedNodeId={selectedNodeId}
              />
            </div>
          </div>
        </div>

        <footer className="shrink-0 flex flex-col gap-2 border-t border-white/6 px-6 py-4 text-sm text-[#8e9889] md:flex-row md:items-center md:justify-between">
          <p>State snapshot comes from one backend request, with live refresh from the event stream when available.</p>
          <div className="mono flex flex-col gap-1 text-[11px] uppercase tracking-[0.16em] text-[#7f897e] md:items-end">
            <span>last sync {lastUpdatedAt ?? 'pending'}</span>
            <span>{meta.mcp.url}</span>
          </div>
        </footer>
      </div>
    </main>
  )
}
