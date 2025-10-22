export type Priority = "Must" | "Should" | "Could";

export type RunCreate = {
  title?: string;            // optional label for the run row
  run_title?: string;        // tolerated by backend
  requirement_title: string;
  requirement_description: string;
  constraints?: string[];
  non_functionals?: string[];
  priority?: "Must" | "Should" | "Could";
};

export interface RunSummary {
  id: string;
  title: string;
  status?: string;
  created_at?: string;
  requirement_title?: string;
  requirement_description?: string;
}

export interface AcceptanceCriteria { story_id: string; gherkin: string; }
export interface Task { id: string; story_id: string; title: string; order?: number; status?: string; }
export interface DesignNote {
  id: string; title: string; kind: string; body_md: string;
  tags?: string[]; related_epic_ids?: string[]; related_story_ids?: string[];
}
export interface ProductVision { id: string; goals: string[]; personas?: string[]; features: string[]; }
export interface TechnicalSolution { id: string; stack: string[]; modules: string[]; interfaces: Record<string,string>; decisions: string[]; }
export interface Epic { id: string; title: string; description?: string; priority_rank: number; }
export interface Story {
  id: string; epic_id: string; title: string; description?: string; priority_rank: number;
  acceptance: AcceptanceCriteria[]; tests: string[]; tasks?: Task[];
}
export interface PlanBundle {
  product_vision: ProductVision;
  technical_solution: TechnicalSolution;
  epics: Epic[];
  stories: Story[];
  design_notes?: DesignNote[];
}

export type VisionSolution = {
  product_vision: ProductVision;
  technical_solution: TechnicalSolution;
};


export type Requirement = {
  id: string;
  title: string;
  description: string;
  constraints?: string[];
  non_functionals?: string[];
  priority?: "Must" | "Should" | "Could";
};

export type RunDetail = {
  run: {
    id: string;
    title?: string | null;
    status: string;
    started_at?: string | null;
    finished_at?: string | null;
  };
  manifest?: { data?: any } | null;
  requirement?: Requirement | null;
};