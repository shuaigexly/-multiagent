export interface TaskPlanResponse {
  task_id: string;
  task_type: string;
  task_type_label: string;
  selected_modules: string[];
  reasoning: string;
}

export interface AgentInfo {
  id: string;
  name: string;
  description: string;
  suitable_for: string[];
}

export interface ResultSection {
  title: string;
  content: string;
}

export interface AgentResult {
  agent_id: string;
  agent_name: string;
  sections: ResultSection[];
  action_items: string[];
}

export interface TaskResultsResponse {
  task_id: string;
  task_type_label: string;
  status: string;
  result_summary: string | null;
  agent_results: AgentResult[];
  published_assets: PublishedAsset[];
}

export interface PublishedAsset {
  type: string;
  title: string;
  url?: string;
  id?: string;
  count?: number;
  message_id?: string;
}

export interface TaskListItem {
  id: string;
  status: string;
  task_type_label: string | null;
  input_text: string | null;
  created_at: string;
}

export interface SSEEvent {
  sequence: number;
  event_type: string;
  agent_name: string | null;
  message: string;
  payload: Record<string, unknown>;
}
