export interface BudgetSummary {
  dollar_budget: number;
  dollar_spent: number;
  dollar_remaining: number;
  budget_utilization: number;
}

export interface QualityScore {
  relevance: number;
  completeness: number;
  coherence: number;
  conciseness: number;
  overall: number;
  rationale: string;
}

export interface TextMetrics {
  word_count: number;
  type_token_ratio: number;
  compression_ratio: number;
  ngram_repetition_rate: number;
  avg_sentence_length: number;
  filler_phrase_count: number;
}

export interface SubtaskMetrics {
  subtask_id: number;
  name: string;
  description: string;
  output: string;
  tier: string;
  tokens_budgeted: number;
  tokens_consumed: number;
  cost_dollars: number;
  surplus_returned: number;
  quality?: QualityScore;
  text_metrics?: TextMetrics;
}

export interface TierDistribution {
  tier: string;
  count: number;
  percentage: number;
}

export interface DowngradeEntry {
  subtask_id: number;
  name: string;
  original_tier: string;
  final_tier: string;
}

export interface DowngradeReport {
  original_plan_cost: number;
  final_plan_cost: number;
  downgrades: DowngradeEntry[];
  subtasks_skipped: string[];
}

export interface EfficiencyStats {
  total_tokens_budgeted: number;
  total_tokens_consumed: number;
  total_surplus_generated: number;
  token_efficiency: number;
}

export interface TaskGraphSummary {
  total_subtasks: number;
  max_depth: number;
  parallelizable_subtasks: number;
  complexity_distribution: Record<string, number>;
}

export interface DagNode {
  id: number;
  label: string;
  complexity: string;
}

export interface DagEdge {
  from: number;
  to: number;
}

export interface Dag {
  nodes: DagNode[];
  edges: DagEdge[];
}

export interface SavingsItem {
  subtask_id: number;
  name: string;
  tier_used: string;
  naive_cost: number;
  actual_cost: number;
  saved: number;
}

export interface SavingsReport {
  naive_total: number;
  actual_total: number;
  total_saved: number;
  savings_pct: number;
  items: SavingsItem[];
  explanation: string;
}

export interface TraceEntry {
  run_id: string;
  task: string;
  budget: number;
  spent: number;
  quality: number | null;
  subtask_count: number;
  timestamp: string;
}

export interface CostReport {
  budget_summary: BudgetSummary;
  subtask_metrics: SubtaskMetrics[];
  tier_distribution: TierDistribution[];
  downgrade_report: DowngradeReport | null;
  efficiency_stats: EfficiencyStats;
  task_graph_summary: TaskGraphSummary;
  dag: Dag;
  savings?: SavingsReport;
  task_input?: string;
  budget_input?: number;
  deliverable?: string;
  deliverable_quality?: QualityScore;
  deliverable_text_metrics?: TextMetrics;
  evaluation_cost?: number;
}
