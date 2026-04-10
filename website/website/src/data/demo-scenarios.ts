export type DemoPhase =
  | 'idle'
  | 'learning'
  | 'recalling'
  | 'composing'
  | 'evaluating'
  | 'improving'
  | 'complete';

export interface DemoPattern {
  id: string;
  title: string;
  description: string;
  confidence: number;
  uses: number;
}

export interface ScenarioMetrics {
  reuseRate: number;
  costSaved: number;
  qualityScore: number;
  tokensSaved: number;
}

export interface DemoScenario {
  id: string;
  name: string;
  description: string;
  icon: string;
  terminalLines: Record<DemoPhase, string[]>;
  evalBefore: number;
  evalAfter: number;
  patterns: DemoPattern[];
  metrics: ScenarioMetrics;
}

export const scenarios: DemoScenario[] = [
  {
    id: 'email-drafting',
    name: 'Email Drafting',
    description: 'Agent learns from past emails and improves drafts over time',
    icon: '✉',
    terminalLines: {
      idle: [],
      learning: [
        '$ engramia.learn(task="draft-email", scope="sales")',
        '> Scanning 47 previous email drafts...',
        '> Identified 12 high-scoring patterns (score ≥ 0.85)',
        '> Subject line pattern: concise + value prop → +18% open rate',
        '> Opening hook pattern: personalized context → +23% reply rate',
        '> Stored 4 new patterns to memory.',
        '✓ Learning complete. Memory updated.',
      ],
      recalling: [
        '$ engramia.recall("draft sales outreach email")',
        '> Querying memory with semantic search...',
        '> Found 3 matching patterns (similarity ≥ 0.82):',
        '  [1] subject-line-value-prop  conf=0.94',
        '  [2] opening-personalization  conf=0.88',
        '  [3] cta-soft-close           conf=0.81',
        '> Injecting patterns into prompt context...',
        '✓ Recall complete. 3 patterns ready.',
      ],
      composing: [
        '$ agent.run(task="draft-email", memory=patterns)',
        '> Composing email with pattern guidance...',
        '> Draft v1: subject "Quick question about [Company]"',
        '> Applying subject-line-value-prop pattern...',
        '> Draft v2: subject "How [Company] cut LLM costs 40%"',
        '> Applying opening-personalization pattern...',
        '> Draft v3: added context from LinkedIn profile',
        '> Final draft ready for evaluation.',
      ],
      evaluating: [
        '$ engramia.evaluate(output=draft, rubric="email-quality")',
        '> Running evaluation rubric...',
        '> Criteria: clarity, personalization, value prop, CTA strength',
        '  clarity:           0.91',
        '  personalization:   0.88',
        '  value_prop:        0.93',
        '  cta_strength:      0.86',
        '> Composite score: 0.895',
      ],
      improving: [
        '> Score 0.895 exceeds threshold 0.80 ✓',
        '> Storing draft pattern to memory...',
        '> pattern_id: email_draft_2024_001',
        '> Updating pattern weights based on outcome...',
        '> Previous best score: 0.71 → New best: 0.895',
        '> Memory improvement: +26% quality delta',
        '✓ Pattern stored. Future drafts will improve further.',
      ],
      complete: [
        '✓ Demo complete. Memory cycle finished.',
        '> Reuse rate:    87%  (patterns reused vs. regenerated)',
        '> Cost saved:    $0.043  (vs. baseline generation)',
        '> Quality score: 0.895  (up from 0.71 baseline)',
        '> Tokens saved:  1,240  (via pattern injection)',
        '',
        '$ # Your agent now remembers what works.',
      ],
    },
    evalBefore: 71,
    evalAfter: 90,
    patterns: [
      {
        id: 'p1',
        title: 'subject-line-value-prop',
        description: 'Lead with concrete outcome, not a generic intro',
        confidence: 0.94,
        uses: 34,
      },
      {
        id: 'p2',
        title: 'opening-personalization',
        description: 'Reference specific company context in first sentence',
        confidence: 0.88,
        uses: 28,
      },
      {
        id: 'p3',
        title: 'cta-soft-close',
        description: 'End with low-friction question, not a hard ask',
        confidence: 0.81,
        uses: 19,
      },
    ],
    metrics: { reuseRate: 87, costSaved: 43, qualityScore: 90, tokensSaved: 1240 },
  },
  {
    id: 'code-review',
    name: 'Code Review',
    description: "Agent remembers your team's coding standards and past review feedback",
    icon: '⌥',
    terminalLines: {
      idle: [],
      learning: [
        '$ engramia.learn(task="code-review", scope="backend-team")',
        '> Scanning 156 past code reviews...',
        '> Identified 8 recurring feedback patterns...',
        '> Pattern: missing error handling → flagged 41 times',
        '> Pattern: SQL injection risk → flagged 12 times',
        '> Pattern: N+1 query → flagged 23 times',
        '> Stored 8 patterns with team-specific context.',
        '✓ Team coding standards learned.',
      ],
      recalling: [
        '$ engramia.recall("review Python FastAPI endpoint")',
        '> Querying memory for relevant review patterns...',
        '> Found 4 patterns (similarity ≥ 0.79):',
        '  [1] error-handling-fastapi    conf=0.96',
        '  [2] sqlalchemy-n-plus-one    conf=0.89',
        '  [3] input-validation-pydantic conf=0.84',
        '  [4] async-context-manager    conf=0.77',
        '✓ Review context loaded. Patterns injected.',
      ],
      composing: [
        '$ agent.run(task="code-review", diff=pr_123, memory=patterns)',
        '> Analyzing PR diff (847 lines)...',
        '> Checking against error-handling-fastapi pattern...',
        '  → FOUND: Missing try/except in /api/users endpoint',
        '> Checking against sqlalchemy-n-plus-one...',
        '  → FOUND: N+1 query in user.posts loop (line 94)',
        '> Checking against input-validation-pydantic...',
        '  → OK: All inputs properly validated',
        '> Review comments generated: 7 issues, 2 suggestions.',
      ],
      evaluating: [
        '$ engramia.evaluate(output=review, rubric="review-quality")',
        '> Evaluating review quality...',
        '  coverage:      0.94  (issues caught vs. known bugs)',
        '  specificity:   0.91  (actionable vs. vague comments)',
        '  false_pos:     0.03  (false positives rate)',
        '  tone:          0.89  (constructive phrasing score)',
        '> Composite score: 0.917',
        '> Benchmark team average: 0.73',
      ],
      improving: [
        '> Score 0.917 significantly exceeds threshold 0.80 ✓',
        '> Updating pattern confidence scores...',
        '> error-handling-fastapi: 0.91 → 0.96 (+0.05)',
        '> sqlalchemy-n-plus-one:  0.84 → 0.89 (+0.05)',
        '> Adding new pattern from this review...',
        '> pattern: async-generator-cleanup (conf=0.79)',
        '✓ Team standards sharpened. Review quality: +25.6%',
      ],
      complete: [
        '✓ Code review cycle complete.',
        '> Reuse rate:    94%  (issues caught via memory)',
        '> Cost saved:    $0.071  (vs. re-analysis from scratch)',
        '> Quality score: 0.917  (vs. 0.73 team baseline)',
        '> Tokens saved:  2,180  (pattern injection efficiency)',
        '',
        '$ # Your reviewer now knows your codebase.',
      ],
    },
    evalBefore: 73,
    evalAfter: 92,
    patterns: [
      {
        id: 'p1',
        title: 'error-handling-fastapi',
        description: 'Require try/except on all route handlers with HTTPException fallback',
        confidence: 0.96,
        uses: 41,
      },
      {
        id: 'p2',
        title: 'sqlalchemy-n-plus-one',
        description: 'Flag loops over ORM relations without selectinload/joinedload',
        confidence: 0.89,
        uses: 23,
      },
      {
        id: 'p3',
        title: 'input-validation-pydantic',
        description: 'All API inputs must use Pydantic models with field validators',
        confidence: 0.84,
        uses: 31,
      },
    ],
    metrics: { reuseRate: 94, costSaved: 71, qualityScore: 92, tokensSaved: 2180 },
  },
  {
    id: 'data-analysis',
    name: 'Data Analysis',
    description: 'Agent reuses previous analyses and adapts them to new datasets',
    icon: '◈',
    terminalLines: {
      idle: [],
      learning: [
        '$ engramia.learn(task="data-analysis", scope="growth-team")',
        '> Scanning 23 past analysis reports...',
        '> Identified 6 reusable analysis frameworks...',
        '> Framework: cohort-retention-curve → used 9 times',
        '> Framework: funnel-drop-off-analysis → used 7 times',
        '> Framework: revenue-attribution-model → used 5 times',
        '> Stored 6 frameworks with methodology notes.',
        '✓ Analysis playbooks stored to memory.',
      ],
      recalling: [
        '$ engramia.recall("analyze user churn for Q1 cohort")',
        '> Searching memory for churn analysis patterns...',
        '> Found 3 matching frameworks (similarity ≥ 0.85):',
        '  [1] cohort-retention-curve   conf=0.95',
        '  [2] churn-signal-indicators  conf=0.87',
        '  [3] ltv-segmentation         conf=0.82',
        '> Loading Q4 analysis as baseline template...',
        '✓ Frameworks loaded. Adapting to Q1 dataset.',
      ],
      composing: [
        '$ agent.run(task="churn-analysis", data=q1_users.csv, memory=frameworks)',
        '> Loading dataset: 12,847 users, 90-day window',
        '> Applying cohort-retention-curve framework...',
        '> Week 1 retention: 68.4% (Q4: 71.2%, Δ -2.8%)',
        '> Week 4 retention: 41.3% (Q4: 44.1%, Δ -2.8%)',
        '> Applying churn-signal-indicators...',
        '> High-risk signal: users with <3 sessions in week 1',
        '> Generating insights and recommendations...',
      ],
      evaluating: [
        '$ engramia.evaluate(output=analysis, rubric="analysis-quality")',
        '> Evaluating analysis against team standards...',
        '  depth:         0.92  (coverage of key metrics)',
        '  accuracy:      0.95  (validated against source data)',
        '  actionability: 0.88  (concrete next steps provided)',
        '  consistency:   0.91  (matches prior report format)',
        '> Composite score: 0.915',
        '> Previous Q4 analysis score: 0.79',
      ],
      improving: [
        '> Score 0.915 exceeds threshold 0.80 ✓',
        '> Updating cohort-retention-curve framework...',
        '> Added: week-1 session threshold as churn predictor',
        '> Confidence updated: 0.95 → 0.97',
        '> Analysis completed 73% faster than Q4 (template reuse)',
        '> Token usage: 1,890 vs. 7,040 baseline',
        '✓ Playbook updated. Next quarter will be even faster.',
      ],
      complete: [
        '✓ Analysis complete. Memory cycle finished.',
        '> Reuse rate:    91%  (framework reuse vs. from-scratch)',
        '> Cost saved:    $0.062  (token reduction via templates)',
        '> Quality score: 0.915  (vs. 0.79 Q4 baseline)',
        '> Tokens saved:  5,150  (template injection)',
        '',
        '$ # Your analyst now builds on prior work.',
      ],
    },
    evalBefore: 79,
    evalAfter: 92,
    patterns: [
      {
        id: 'p1',
        title: 'cohort-retention-curve',
        description: 'Weekly retention tracking with week-1 session threshold as churn signal',
        confidence: 0.97,
        uses: 9,
      },
      {
        id: 'p2',
        title: 'churn-signal-indicators',
        description: 'Multi-signal churn prediction: sessions, feature depth, support contacts',
        confidence: 0.87,
        uses: 7,
      },
      {
        id: 'p3',
        title: 'ltv-segmentation',
        description: 'Segment users by LTV quartile for targeted intervention strategies',
        confidence: 0.82,
        uses: 5,
      },
    ],
    metrics: { reuseRate: 91, costSaved: 62, qualityScore: 92, tokensSaved: 5150 },
  },
];
