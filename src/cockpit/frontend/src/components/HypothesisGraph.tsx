import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from '@xyflow/react'

import type { GraphNodeRecord, GraphResponse } from '../types'

interface HypothesisGraphProps {
  graph: GraphResponse
  selectedNodeId: string | null
  onSelectNode: (nodeId: string) => void
  connectionLabel: string
}

function nodeTone(node: GraphNodeRecord) {
  if (node.state === 'refuted') {
    return {
      background: '#3b1618',
      borderColor: '#c75b60',
      color: '#f5d3d5',
    }
  }

  const tones = {
    question: { background: '#1d2b24', borderColor: '#74b47d', color: '#dcf5df' },
    hypothesis: { background: '#1c232d', borderColor: '#7da5d6', color: '#dce8f8' },
    experiment: { background: '#2a2218', borderColor: '#d9a65a', color: '#f8e4c8' },
    evidence: { background: '#261f2b', borderColor: '#b48ed4', color: '#f0e0ff' },
    conclusion: { background: '#132328', borderColor: '#63b8c4', color: '#d6f3f6' },
  }

  return tones[node.kind]
}

function toFlowNodes(records: GraphNodeRecord[], selectedNodeId: string | null): Node[] {
  const counts: Record<string, number> = {}

  return records.map((record) => {
    const depth = record.parent_id ? 1 : 0
    const lane = `${record.kind}-${depth}`
    counts[lane] = (counts[lane] ?? 0) + 1

    const column = {
      question: 0,
      hypothesis: 1,
      experiment: 2,
      evidence: 2,
      conclusion: 3,
    }[record.kind]

    const tone = nodeTone(record)

    return {
      id: record.node_id,
      position: { x: column * 260 + depth * 30, y: (counts[lane] - 1) * 122 },
      data: {
        label: (
          <div className="space-y-2 text-left">
            <div className="flex items-center justify-between gap-3">
              <span className="mono text-[11px] uppercase tracking-[0.24em] opacity-80">{record.kind}</span>
              <span className="mono text-[11px] uppercase tracking-[0.2em] opacity-70">{record.state}</span>
            </div>
            <p className="text-sm leading-5">{record.text}</p>
          </div>
        ),
      },
      style: {
        width: 220,
        minHeight: 94,
        borderRadius: 18,
        borderWidth: selectedNodeId === record.node_id ? 2 : 1,
        borderStyle: 'solid',
        borderColor: selectedNodeId === record.node_id ? '#d8ddd2' : tone.borderColor,
        background: tone.background,
        color: tone.color,
        boxShadow: selectedNodeId === record.node_id ? '0 0 0 1px rgba(216,221,210,0.25)' : 'none',
      },
    }
  })
}

function toFlowEdges(graph: GraphResponse): Edge[] {
  return graph.edges.map((edge) => ({
    id: String(edge.edge_id),
    source: edge.src,
    target: edge.dst,
    label: edge.relation,
    markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18, color: '#7b8477' },
    labelStyle: { fill: '#a7afa2', fontSize: 11, letterSpacing: '0.08em', textTransform: 'uppercase' },
    style: { stroke: '#7b8477', strokeWidth: 1.2 },
    animated: edge.relation === 'supports' || edge.relation === 'refutes',
  }))
}

export function HypothesisGraph({
  graph,
  selectedNodeId,
  onSelectNode,
  connectionLabel,
}: HypothesisGraphProps) {
  const flowNodes = toFlowNodes(graph.nodes, selectedNodeId)
  const flowEdges = toFlowEdges(graph)

  return (
    <section className="flex h-full min-h-[420px] flex-col overflow-hidden rounded-[28px] border border-white/8 bg-[#111713]/85">
      <header className="flex items-center justify-between border-b border-white/6 px-5 py-4">
        <div>
          <p className="mono text-[11px] uppercase tracking-[0.28em] text-[#8e9889]">Hypothesis graph</p>
          <h2 className="mt-2 text-lg font-semibold text-[#e5eadf]">Live research frontier</h2>
        </div>
        <span className="mono rounded-full border border-white/8 px-3 py-1 text-[11px] uppercase tracking-[0.24em] text-[#9cad94]">
          {connectionLabel}
        </span>
      </header>
      <div className="relative flex-1 bg-[linear-gradient(180deg,rgba(255,255,255,0.02),transparent)]">
        {graph.nodes.length === 0 ? (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-[#111713]/88 px-10 text-center">
            <p className="mono text-[11px] uppercase tracking-[0.28em] text-[#8e9889]">Awaiting frontier</p>
            <p className="max-w-sm text-sm leading-6 text-[#a6aea0]">
              No question or hypothesis nodes yet. The first `mcp__memory__propose_hypothesis` call will appear here.
            </p>
          </div>
        ) : null}
        <ReactFlow
          fitView
          minZoom={0.35}
          maxZoom={1.25}
          nodes={flowNodes}
          edges={flowEdges}
          onNodeClick={(_, node) => onSelectNode(node.id)}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#2a332d" gap={28} size={1} />
          <Controls className="!border !border-white/10 !bg-[#151c17] !shadow-none" />
        </ReactFlow>
      </div>
    </section>
  )
}

