export type GraphNodeKind = 'question' | 'hypothesis' | 'experiment' | 'evidence' | 'conclusion'
export type GraphNodeState = 'active' | 'refuted' | 'superseded' | 'archived'

export interface GraphNodeRecord {
  node_id: string
  kind: GraphNodeKind
  text: string
  state: GraphNodeState
  created_at: string
  parent_id: string | null
}

export interface GraphEdgeRecord {
  edge_id: number
  src: string
  dst: string
  relation: 'refines' | 'contradicts' | 'supports' | 'refutes' | 'supersedes' | 'blocks'
  rationale: string | null
}

export interface GraphResponse {
  nodes: GraphNodeRecord[]
  edges: GraphEdgeRecord[]
}

export interface FailureRecord {
  failure_id: number
  trigger: string
  symptom: string
  root_cause: string
  resolution: string
  signature: string
  seen_count: number
  first_seen: string
  last_seen: string
}

export interface WsEvent {
  id: number
  kind: string
  payload: Record<string, unknown>
  ts: string
}

export type InterventionKind = 'reject' | 'approve' | 'redirect' | 'constrain' | 'halt'

export interface InterventionRecord {
  id: number
  kind: string
  target: string | null
  payload: string
  created_at: string
  delivered_at: string | null
}

export interface CockpitMeta {
  api_base_url: string
  ws_url: string
  last_event_id: number
  mcp: {
    transport: string
    url: string
  }
}

export interface CockpitStateResponse {
  graph: GraphResponse
  failures: FailureRecord[]
  interventions: InterventionRecord[]
  meta: CockpitMeta
}
