export interface BudgetSummary {
  dollar_budget: number;
  dollar_spent: number;
  dollar_remaining: number;
  budget_utilization: number;
}

export interface SubtaskMetrics {
  subtask_id: number;
  name: string;
  tier: string;
  tokens_budgeted: number;
  tokens_consumed: number;
  cost_dollars: number;
  surplus_returned: number;
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

export interface CostReport {
  budget_summary: BudgetSummary;
  subtask_metrics: SubtaskMetrics[];
  tier_distribution: TierDistribution[];
  downgrade_report: DowngradeReport | null;
  efficiency_stats: EfficiencyStats;
  task_graph_summary: TaskGraphSummary;
  dag: Dag;
  task_input?: string;
  budget_input?: number;
}
