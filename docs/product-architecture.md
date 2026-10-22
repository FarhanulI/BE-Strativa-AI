# AI CONTENT STUDIO — PRODUCT ARCHITECTURE SOURCE OF TRUTH

## ROLE

You are the Principal Software Architect and AI Systems Architect for this product.

Your responsibility is to design, implement, review, and evolve the system according to the architecture, product principles, domain boundaries, intelligence model, learning loop, AI infrastructure, retrieval architecture, experimentation framework, and engineering constraints defined in this document.

This document is the canonical architectural source of truth.

Do not introduce architectural decisions that conflict with these principles unless explicitly requested.

The system must be designed as a production-oriented, AI-native **Content Operating System**, not as a simple AI content generator.

---

# 1. PRODUCT DEFINITION

Build an AI-powered Content Operating System that tells businesses and creators:

* what content to create,
* why they should create it,
* how they should create it,
* helps them create it,
* measures what happened,
* understands why it happened,
* learns from the result,
* learns from human decisions and edits,
* experiments with new possibilities,
* and continuously improves future content strategy.

### Primary Positioning

> An AI-powered content operating system that tells businesses and creators what to create, helps them create it, and learns what works.

### Short Positioning

> AI that figures out what content you should create next.

The core product value is:

> Personalized, intelligent, adaptive content strategy.

The product is NOT primarily:

* an AI content generator,
* a trend feed,
* an analytics dashboard,
* a social media scheduler,
* an AI image generator,
* an AI video generator.

These are execution capabilities inside the larger Content Operating System.

---

# 2. CORE PRODUCT LOOP

The canonical product loop is:

```text
UNDERSTAND
    ↓
DECIDE
    ↓
OPPORTUNITY
    ↓
BRIEF
    ↓
CREATE
    ↓
PUBLISH
    ↓
MEASURE
    ↓
LEARN
    ↓
UNDERSTAND
```

The expanded architecture is:

```text
Content Intelligence
        ↓
Raw Intelligence Events
        ↓
Signal Synthesis
        ↓
Strategic Signals
        ↓
Opportunity Engine
        ↓
Exploration / Exploitation
        ↓
Content Brief
        ↓
Human Review / Editing
        ↓
Channel Execution Specification
        ↓
Content Creation
        ↓
Human Review / Editing
        ↓
Asset Assembly
        ↓
Human Review / Editing
        ↓
Publish
        ↓
Performance Ingestion
        ↓
Metric Snapshots
        ↓
Performance Intelligence
        ↓
Human Feedback + Performance Signals
        ↓
Learning
        ↓
Content Intelligence
```

Every architectural decision should strengthen this loop.

---

# 3. UNIVERSAL CONTENT PROFILE

Do NOT create separate strategy engines for businesses and creators.

Use one universal strategic root entity:

```text
ContentProfile
```

Supported profile types may include:

```text
creator
business
personal_brand
expert
coach
startup
local_business
ecommerce_brand
```

The system must treat these as profile types, not fundamentally different products.

### ContentProfile

```typescript
interface ContentProfile {
  id: string;
  workspaceId: string;
  type: ProfileType;

  identity: ProfileIdentity;
  brand: BrandIntelligence;
  audience: AudienceIntelligence;
  market: MarketIntelligence;
  performance: PerformanceIntelligence;

  businessContext?: BusinessContext;
}
```

### ProfileIdentity

```typescript
interface ProfileIdentity {
  name: string;
  positioning: string;
  topics: string[];
  expertise: string[];
  goals: StrategyGoal[];
}
```

### BusinessContext

BusinessContext is OPTIONAL.

Creators must be able to use the complete strategy system without products, services, or offers.

```typescript
interface BusinessContext {
  products: Product[];
  services: Service[];
  offers: Offer[];
  commercialObjectives: Goal[];
}
```

BusinessContext can be added later without changing the fundamental ContentProfile architecture.

---

# 4. WORKSPACE ARCHITECTURE

Workspace is the collaboration and tenant boundary.

When a user registers:

```text
User
  ↓
Create Workspace
  ↓
Create Workspace Membership
  ↓
Membership role = OWNER
```

The registering user becomes the owner of the newly created workspace.

Later, additional users can be invited into the workspace.

Recommended model:

```text
User
  │
  └── WorkspaceMembership
          │
          └── Workspace
                 │
                 ├── ContentProfile
                 ├── Content
                 ├── Intelligence
                 ├── Opportunities
                 ├── Experiments
                 └── Members
```

Recommended roles:

```text
OWNER
ADMIN
MEMBER
```

Prefer:

```text
workspace_members.role = OWNER
```

as the canonical ownership source.

Avoid maintaining two independent sources of truth such as:

```text
workspace_members.role = OWNER
```

and:

```text
workspaces.owner_id
```

unless explicitly required.

### Workspace responsibility

Workspace represents:

> Who is allowed to access and collaborate on the data.

ContentProfile represents:

> Whose content strategy is being developed.

Intelligence represents:

> What the system knows about that profile.

---

# 5. AUTHORIZATION PRINCIPLE

Authorization must be workspace-centric.

Every request involving workspace resources must verify:

```text
Authenticated User
        ↓
Workspace Membership
        ↓
Role / Permission
        ↓
Resource Access
```

Never treat:

```text
workspace_id
```

from a URL as sufficient authorization.

Example:

```http
GET /api/v1/workspaces/{workspace_id}/profiles
```

The backend must verify that the authenticated user belongs to that workspace before returning data.

---

# 6. CONTENT INTELLIGENCE — CENTRAL BRAIN

Content Intelligence is the central brain of the platform.

It answers:

> What is happening around this profile, its audience, its market, and its content performance—and what does that mean for what should be created next?

Content Intelligence has four primary domains:

```text
1. Brand / Profile Intelligence
2. Audience Intelligence
3. Market / Topic Intelligence
4. Performance Intelligence
```

These domains generate raw intelligence events and evidence.

They should NOT directly generate content opportunities from every raw event.

All strategic events must pass through the Signal Synthesis layer.

---

# 7. BRAND / PROFILE INTELLIGENCE

Brand Intelligence understands:

* positioning,
* identity,
* voice,
* tone,
* expertise,
* topics,
* content pillars,
* goals,
* visual rules,
* USP,
* creator preferences,
* successful content patterns,
* brand constraints.

The system should use Brand Intelligence to determine whether a content opportunity actually fits the profile.

---

# 8. AUDIENCE INTELLIGENCE

Audience Intelligence understands:

* audience personas,
* pain points,
* desires,
* questions,
* objections,
* interests,
* engagement patterns,
* audience language,
* recurring topics,
* content preferences.

Possible sources include:

* comments,
* questions,
* DMs or derived insights,
* engagement data,
* audience research,
* personas,
* published content responses.

Audience Intelligence should help answer:

> What does this audience currently care about?

---

# 9. MARKET / TOPIC INTELLIGENCE

Market Intelligence understands:

* trends,
* topic movements,
* market signals,
* competitor observations,
* creator ecosystem signals,
* format trends,
* platform trends,
* emerging conversations.

Trends are inputs.

Trends must NEVER directly generate content.

Forbidden architecture:

```text
Trend
  ↓
AI Generate Content
```

Required architecture:

```text
Trend
  +
Audience
  +
Brand/Profile
  +
Goals
  +
Performance
  ↓
Signal
  ↓
Opportunity
  ↓
Brief
  ↓
Creation
```

---

# 10. PERFORMANCE INTELLIGENCE

Performance Intelligence must not merely display metrics.

It must answer:

> WHY did this content work or fail?

It should analyze:

* reach,
* impressions,
* engagement,
* shares,
* saves,
* comments,
* retention,
* clicks,
* conversions where available,
* format,
* hook,
* topic,
* narrative angle,
* CTA,
* publishing context,
* audience response,
* historical comparisons,
* growth velocity,
* experiment outcomes.

Performance Intelligence must produce reusable learning signals.

Example:

```text
POV-style short videos
→ higher share rate
→ compared with static educational posts
→ for this profile
→ during the observed period
```

The system must preserve the evidence behind such insights.

---

# 11. PERFORMANCE INGESTION ENGINE

Performance Intelligence depends on reliable ingestion of external platform data.

Introduce a dedicated:

```text
Performance Ingestion & Metric Snapshotting Engine
```

Its responsibilities include:

* social platform API ingestion,
* webhook ingestion,
* scheduled metric polling,
* rate-limit handling,
* token expiration handling,
* retry handling,
* metric normalization,
* immutable metric snapshots.

Supported integrations may eventually include:

```text
Meta
Instagram
Facebook
LinkedIn
YouTube
TikTok
Other supported platforms
```

Do not couple the core Performance Intelligence domain directly to a specific social platform.

Use platform adapters.

```text
Platform API
      ↓
Platform Adapter
      ↓
Normalized Performance Event
      ↓
Ingestion Queue
      ↓
Metric Snapshot
      ↓
Performance Intelligence
```

---

# 12. PERFORMANCE POLLING WINDOWS

Performance metrics should be collected at scheduled intervals.

Example:

```text
T + 1 hour
T + 24 hours
T + 7 days
T + 30 days
```

These windows should be configurable by platform and content type.

The system must account for the fact that performance does not stabilize immediately.

Do not assume that the first available metric is the final result.

---

# 13. IMMUTABLE PERFORMANCE SNAPSHOTS

Do NOT simply overwrite performance metrics.

Store timestamped metric snapshots.

Example:

```typescript
interface PerformanceMetricSnapshot {
  id: string;

  contentId: string;
  platform: string;

  observedAt: Date;

  views?: number;
  impressions?: number;
  likes?: number;
  comments?: number;
  shares?: number;
  saves?: number;

  retentionRate?: number;
  clickThroughRate?: number;

  rawMetrics?: Record<string, any>;
}
```

This allows the system to calculate:

```text
Growth Velocity
Performance Acceleration
Metric Delta
Retention Change
Early Performance vs Final Performance
```

For example:

```text
Growth Velocity =
Δ views / Δ time
```

Historical snapshots must remain immutable.

---

# 14. WEBHOOK BUFFERING

Incoming platform webhooks must be processed asynchronously.

Preferred flow:

```text
Platform Webhook
      ↓
Webhook Endpoint
      ↓
Redis / Queue
      ↓
Background Worker
      ↓
Validation / Normalization
      ↓
Metric Snapshot
```

Do not perform expensive intelligence processing directly inside the webhook request.

---

# 15. SIGNAL ARCHITECTURE

Use a universal Signal abstraction.

Possible signal types:

```text
MarketSignal
AudienceSignal
PerformanceSignal
HumanFeedbackSignal
```

Signals are strategic abstractions derived from raw evidence.

They feed the Opportunity Engine.

However:

> Raw intelligence events must NOT directly become individual opportunities.

They must pass through the Signal Synthesizer.

---

# 16. SIGNAL SYNTHESIZER / AGGREGATOR

Introduce a dedicated:

```text
Signal Synthesizer
```

between Intelligence Domains and the Opportunity Engine.

Canonical flow:

```text
Raw Intelligence Events
        ↓
Signal Synthesizer
        ↓
Deduplication
        ↓
Clustering
        ↓
Thresholding
        ↓
Confidence Calculation
        ↓
Aggregated Strategic Signals
        ↓
Opportunity Engine
```

The Signal Synthesizer must prevent:

* signal flooding,
* duplicate opportunities,
* repeated recommendations,
* unnecessary LLM calls,
* excessive token usage,
* redundant embeddings.

---

# 17. SIGNAL CLUSTERING

Related raw events should be grouped.

Example:

```text
Comment 1:
"How do I start Reels?"

Comment 2:
"How can beginners make Reels?"

Comment 3:
"How do I create my first Reel?"

Comment 4:
"Reels for beginners?"
...
```

These should not create 20 separate opportunities.

They should become one strategic signal:

```text
Audience Question:
"Audience repeatedly needs beginner Reel guidance."
```

The signal should retain evidence metadata such as:

```text
frequency_weight
source_count
confidence
first_observed_at
last_observed_at
```

---

# 18. SIGNAL DEDUPLICATION

The Signal Synthesizer should identify semantically and structurally similar signals.

Deduplication may use:

* semantic similarity,
* normalized topic keys,
* source IDs,
* time windows,
* signal type,
* profile scope,
* existing active signals.

The same underlying evidence must not continuously create duplicate opportunities.

---

# 19. SIGNAL THRESHOLDING

Not every event deserves strategic attention.

Signals should be promoted only when they satisfy configurable criteria such as:

```text
Frequency
Confidence
Recency
Strategic Relevance
Performance Evidence
Audience Importance
Market Velocity
```

Example:

```text
1 isolated comment
→ raw event

15 related comments
→ candidate signal

Repeated across multiple weeks
→ high-confidence strategic signal
```

Thresholds must be configurable by intelligence type.

---

# 20. SIGNAL EXPIRATION / TTL

Signals have different lifetimes.

Market signals are often short-lived.

Performance signals may remain useful for months.

Brand signals may remain useful for years.

Therefore, signal freshness must be explicit.

Example:

```text
Market Signal
TTL = 48–72 hours
```

Possible fields:

```typescript
interface StrategicSignal {
  id: string;

  profileId?: string;

  signalType: string;

  confidence: number;

  frequencyWeight?: number;
  sourceCount?: number;

  firstObservedAt: Date;
  lastObservedAt: Date;

  expiresAt?: Date;

  metadata: Record<string, any>;
}
```

Expired signals should automatically lose eligibility for new opportunities unless explicitly retained as historical evidence.

---

# 21. OPPORTUNITY ENGINE

The Opportunity Engine is mandatory.

It prevents the system from blindly turning trends or raw data into content.

A Content Opportunity represents:

> A strategically relevant reason to create a specific piece of content now.

```typescript
interface ContentOpportunity {
  id: string;
  profileId: string;

  sourceSignal:
    | 'trend'
    | 'performance_gap'
    | 'audience_question'
    | 'pillar_rotation'
    | 'human_feedback';

  relevanceScore: number;

  strategicRationale: string;

  targetObjective:
    | 'growth'
    | 'authority'
    | 'lead_gen'
    | 'sales';

  recommendedFormat: string;

  explorationMode?: 'exploration' | 'exploitation';
}
```

Opportunity generation should consider:

```text
Profile Fit
+
Audience Relevance
+
Goal Fit
+
Performance Evidence
+
Market Relevance
+
Confidence
+
Exploration Factor
```

---

# 22. EXPLORATION VS EXPLOITATION

The learning system must NOT repeatedly recommend only historically successful content.

This creates:

```text
Creative Stagnation
```

The system must balance:

```text
EXPLOITATION
```

with:

```text
EXPLORATION
```

### Exploitation

Use proven patterns:

* successful topics,
* successful formats,
* successful hooks,
* successful narrative structures,
* successful content pillars,
* successful CTAs.

### Exploration

Test:

* new formats,
* new hooks,
* adjacent topics,
* new narrative angles,
* new content structures,
* new visual approaches,
* new CTA patterns,
* new content pillars where strategically relevant.

---

# 23. ADAPTIVE EXPLORATION

Exploration must adapt to profile maturity.

Do NOT use a fixed exploration percentage for every profile.

A cold-start profile has little or no evidence for exploitation.

Therefore:

```text
Cold Start
→ high exploration

Early Growth
→ balanced exploration/exploitation

Mature Profile
→ controlled exploration + stronger exploitation
```

A conceptual adaptive function may be:

```text
ε = max(ε_min, ε_base × e^(-k × N))
```

where:

```text
N = number of published assets with verified performance data
ε_min = minimum exploration rate
k = learning velocity constant
```

However, this formula is a strategy model, not an immutable implementation requirement.

The exploration system should eventually consider additional maturity indicators:

```text
Verified Performance Count
+
Signal Confidence
+
Experiment Coverage
+
Pattern Stability
+
Profile Learning Confidence
```

---

# 24. INITIAL EXPLORATION POLICY

For the MVP, use deterministic maturity-based rules rather than a complex Multi-Armed Bandit implementation.

Example:

```text
Profile Stage        Exploration Focus

Cold Start           80–100%
Early Growth         30–50%
Mature Profile       10–15%
```

These values must be configurable.

Future versions may implement:

```text
Multi-Armed Bandit
Bayesian Optimization
Contextual Bandits
Other Experimentation Algorithms
```

Do not introduce these prematurely.

---

# 25. CONTENT EXPERIMENTS

Exploration should be measurable.

Introduce:

```text
ContentExperiment
ExperimentVariant
```

Example:

```typescript
interface ContentExperiment {
  id: string;
  profileId: string;
  opportunityId: string;

  experimentType: string;
  hypothesis: string;

  explorationBudget: number;

  status: string;

  createdAt: Date;
  completedAt?: Date;
}
```

Variants should record:

* what changed,
* why it changed,
* whether it was exploration or exploitation,
* performance outcome.

The objective is to learn:

> Which content patterns work for this specific profile, audience, goal, and context?

---

# 26. CONTENT BRIEF — STRATEGY CONTRACT

A Content Brief is mandatory before content creation.

Creation must NOT bypass the Brief layer.

```text
Opportunity
    ↓
Content Brief
    ↓
Channel Execution Specification
    ↓
Creation
```

The Brief connects strategy with execution.

The Brief should contain platform-agnostic strategic direction.

```typescript
interface ContentBrief {
  id: string;
  opportunityId: string;

  coreHook: string;
  narrativeAngle: string;

  formatSpecs: Record<string, any>;

  targetEmotion: string;
  keyMessage: string;

  associatedProductOrOffer?: string;

  callToAction: string;

  successMetrics: string[];
}
```

The Brief should contain strategic direction, not unnecessarily finalized creative copy.

Maintain the distinction between:

```text
Strategic Decision
```

and:

```text
Creative Execution
```

---

# 27. BRIEF-TO-EXECUTION CARDINALITY

A single strategic Content Brief may produce multiple platform-specific executions.

Do NOT assume:

```text
1 Opportunity
→ 1 Brief
→ 1 Draft
```

Instead:

```text
Opportunity
      ↓
ContentBrief
      ↓
ChannelExecutionSpec
      ↓
Platform-specific Draft
```

One Content Brief may fan out to:

```text
Instagram
LinkedIn
YouTube
Facebook
TikTok
Other supported channels
```

---

# 28. CHANNEL EXECUTION SPECIFICATION

Introduce:

```text
ChannelExecutionSpec
```

The ContentBrief remains platform-agnostic.

The ChannelExecutionSpec defines platform-specific execution requirements.

Example:

```typescript
interface ChannelExecutionSpec {
  id: string;

  contentBriefId: string;

  platform: string;
  format: string;

  constraints: Record<string, any>;

  visualSpecifications?: Record<string, any>;
  copySpecifications?: Record<string, any>;
  pacingSpecifications?: Record<string, any>;
}
```

Examples of constraints:

```text
Instagram Reel
→ vertical video
→ short-form pacing
→ caption requirements

LinkedIn
→ long-form text
→ professional formatting

YouTube
→ long-form or short-form video
→ title/description requirements
```

The strategic core must remain consistent across executions.

Only execution should adapt.

---

# 29. HUMAN-IN-THE-LOOP

Human-in-the-loop is a first-class product capability.

AI output must never be treated as immutable.

The user must be able to review and edit AI output at major stages.

Required interactive stages:

```text
Brief
Draft
Asset Assembly
```

The flow should support:

```text
AI Generated
    ↓
User Reviews
    ↓
User Edits
    ↓
User Approves
```

The same principle should apply to:

* hooks,
* captions,
* scripts,
* CTAs,
* visual instructions,
* asset selections,
* content structure.

---

# 30. CONTENT VERSIONING

AI-generated and human-edited content must preserve version history.

Example:

```text
Version 1
AI Generated

Version 2
Human Edited

Version 3
Human Approved
```

Do not silently overwrite important versions.

Version history enables:

* human preference learning,
* auditability,
* regeneration,
* rollback,
* lineage,
* debugging.

---

# 31. HUMAN EDITS ARE LEARNING SIGNALS

A user's manual edits are valuable behavioral data.

The system must capture them.

Example:

```text
AI Hook
    ↓
User edits hook
    ↓
Human Feedback Signal
    ↓
Learning Signal
    ↓
Future Brief / Draft generation
```

Preserve meaningful information about:

```text
Original AI value
User-edited value
Edit type
Stage
Field
Profile
Content
Timestamp
```

Example:

```typescript
interface HumanFeedbackSignal {
  id: string;

  profileId: string;
  contentId?: string;

  stage:
    | 'brief'
    | 'draft'
    | 'asset_assembly';

  field: string;

  originalValue: string;
  editedValue: string;

  editType:
    | 'rewrite'
    | 'delete'
    | 'replace'
    | 'reorder'
    | 'approve'
    | 'reject'
    | 'regenerate';

  createdAt: Date;
}
```

---

# 32. UPSTREAM INVALIDATION CASCADE

Upstream edits can make downstream artifacts strategically or technically obsolete.

The system must implement state-driven invalidation.

Example:

```text
ContentBrief
    ↓
ChannelExecutionSpec
    ↓
ContentDraft
    ↓
AssetAssembly
```

If an upstream artifact changes, downstream state must be evaluated.

---

# 33. INVALIDATION MATRIX

Example:

| Upstream Change               | Downstream Target            | Result                           |
| ----------------------------- | ---------------------------- | -------------------------------- |
| Brief core hook changed       | ContentDraft                 | `STALE_STRATEGY_MISMATCH`        |
| Brief narrative angle changed | ContentDraft                 | `STALE_STRATEGY_MISMATCH`        |
| Brief objective changed       | ChannelExecutionSpec         | `STALE_STRATEGY_MISMATCH`        |
| Draft script changed          | AssetAssembly                | `ASSET_REGENERATION_REQUIRED`    |
| Draft text changed            | Generated captions/voiceover | `PARTIAL_REGENERATION_REQUIRED`  |
| Human feedback updated        | Learning Engine              | Recalculate preference weighting |
| Channel constraints changed   | Channel Draft                | `EXECUTION_SPEC_CHANGED`         |

The user should be given an explicit choice where appropriate:

```text
Re-align with AI
Keep Custom Edit
Regenerate
Cancel
```

Never silently destroy user-authored edits.

---

# 34. HUMAN PREFERENCE VS AUDIENCE PERFORMANCE

Do NOT treat human preference and audience performance as the same thing.

They are separate signals.

```text
Human Feedback
    ↓
"What does the creator prefer?"
```

while:

```text
Performance Data
    ↓
"What does the audience respond to?"
```

The learning system should combine:

```text
Human Preference
+
Audience Performance
+
Strategic Fit
+
Experiment Results
```

to produce long-term learning.

Human preference must not automatically override audience evidence.

Audience performance must not automatically override creator preference.

The system should preserve both as separate dimensions.

---

# 35. LEARNING ENGINE

The Learning Engine converts observed results into reusable intelligence.

Core flow:

```text
Published Content
      ↓
Metric Snapshots
      ↓
Performance Analysis
      ↓
Performance Insight
      ↓
Learning Signal
      ↓
Profile Intelligence
```

With human feedback:

```text
Human Edit
      ↓
Human Feedback Signal
      ↓
Learning Signal
      ↓
Profile Intelligence
```

The final learning model becomes:

```text
Performance
+
Human Feedback
+
Audience Signals
+
Market Signals
+
Experiment Results
        ↓
Learning
        ↓
Profile Intelligence
```

---

# 36. HYBRID RAG ARCHITECTURE

Use one universal RAG infrastructure.

Do NOT create separate vector databases for:

* Brand,
* Audience,
* Market,
* Performance.

Use:

```text
Neon PostgreSQL
+
pgVector
+
Structured PostgreSQL Filtering
```

The system must use Hybrid Retrieval:

```text
Semantic Search
+
Keyword / Structured Filtering
+
Temporal Filtering
```

---

# 37. GLOBAL VS TENANT KNOWLEDGE

Not all knowledge should be tenant-isolated.

Separate knowledge into logical scopes:

```text
GLOBAL
WORKSPACE
PROFILE
```

### Global Knowledge

Examples:

* platform algorithm changes,
* broad industry trends,
* macro market trends,
* public benchmark information,
* general niche knowledge,
* general platform knowledge.

### Workspace Knowledge

Examples:

* workspace-specific research,
* shared brand assets,
* workspace-level knowledge.

### Profile Knowledge

Examples:

* brand intelligence,
* audience intelligence,
* historical performance,
* user edits,
* profile-specific market observations.

Recommended conceptual architecture:

```text
                  KNOWLEDGE
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
       GLOBAL                TENANT
     KNOWLEDGE             KNOWLEDGE
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
                WORKSPACE            PROFILE
```

Global knowledge must NEVER bypass tenant authorization or be treated as private user knowledge.

Tenant-specific retrieval must always enforce workspace/profile scope.

---

# 38. KNOWLEDGE CHUNKS

Use a universal knowledge representation.

Recommended structure:

```typescript
interface KnowledgeChunk {
  id: string;

  scopeType:
    | 'GLOBAL'
    | 'WORKSPACE'
    | 'PROFILE';

  workspaceId?: string;
  profileId?: string;

  intelligenceType:
    | 'brand'
    | 'audience'
    | 'market'
    | 'performance';

  sourceType: string;
  sourceId: string;

  content: string;

  metadata: Record<string, any>;

  embedding: vector;

  embeddingModel?: string;
  embeddingVersion?: string;

  createdAt: Date;
  updatedAt: Date;
}
```

Rules:

```text
GLOBAL
→ workspaceId = null
→ profileId = null

WORKSPACE
→ workspaceId required
→ profileId optional

PROFILE
→ workspaceId required
→ profileId required
```

Do not rely on nullable IDs alone to express authorization semantics.

`scopeType` must explicitly represent the knowledge boundary.

---

# 39. RAG RETRIEVAL PIPELINE

Canonical retrieval flow:

```text
Query Builder
      ↓
Scope Resolution
      ↓
Workspace Scope
      ↓
Profile Scope
      ↓
Intelligence Domain Scope
      ↓
Metadata Filtering
      ↓
Semantic pgVector Search
      +
Keyword / Structured Search
      +
Temporal Filtering
      ↓
Hybrid Ranking / Reranking
      ↓
Context Builder
      ↓
AI Task
      ↓
Structured Insight
```

The retrieval layer must understand both:

```text
Global Knowledge
```

and:

```text
Tenant/Profile Knowledge
```

---

# 40. INTELLIGENCE-SPECIFIC RETRIEVAL

### Brand

Retrieve:

* positioning,
* voice,
* tone,
* expertise,
* pillars,
* previous briefs,
* successful content,
* creator identity,
* brand guidelines.

### Audience

Retrieve:

* questions,
* comments,
* audience pain points,
* desires,
* objections,
* personas,
* engagement patterns.

### Market

Retrieve:

* global market signals,
* profile-specific market signals,
* trends,
* competitor observations,
* topic movements,
* format trends,
* platform signals.

### Performance

Retrieve:

* published content,
* performance metrics,
* performance insights,
* experiments,
* historical learnings,
* metric snapshots.

---

# 41. PERFORMANCE DUAL-PASS RETRIEVAL

Performance Intelligence requires accurate numerical filtering.

Vector similarity must NOT be responsible for mathematical comparisons.

Use a performance-specific retrieval pipeline:

```text
PASS 1
Relational / SQL Filtering
        ↓
Candidate Content IDs
        ↓
PASS 2
Semantic pgVector Search
        ↓
Semantic Reranking
        ↓
PASS 3
Context Assembly
```

### Pass 1 — SQL Filtering

Example:

```sql
WHERE profile_id = :profile_id
  AND published_at >= :date_from
  AND retention_rate > :threshold
  AND shares > :share_threshold
```

Use proper indexes for frequently queried numerical and temporal fields.

### Pass 2 — Semantic Filtering

Use the candidate IDs from Pass 1 to evaluate qualitative relevance.

Example:

```text
"Find high-performing posts discussing SaaS onboarding."
```

### Pass 3 — Context Assembly

Combine:

```text
Numerical Statistics
+
Performance Deltas
+
Semantic Content
+
Historical Context
```

into the Context Engine.

---

# 42. TEMPORAL INTELLIGENCE

Time is a first-class retrieval dimension.

Especially for:

```text
Market Intelligence
Performance Intelligence
```

Support:

```text
created_at
published_at
observed_at
expires_at
```

The system must distinguish between:

```text
historical knowledge
```

and:

```text
recent signals
```

---

# 43. RAG LINEAGE

Every important insight should be traceable.

Required lineage:

```text
Insight
   ↓
Evidence
   ↓
KnowledgeChunk
   ↓
Source ID
   ↓
Original Record
```

The system must avoid generating unsupported claims.

AI-generated insights should be grounded in retrieved evidence whenever evidence is required.

---

# 44. AI ARCHITECTURE

AI is infrastructure.

Business/domain logic must NOT be tightly coupled to a specific model provider.

Never write business logic such as:

```text
ContentBriefService → Gemini
```

Instead:

```text
ContentBriefService
        ↓
AI Orchestrator
        ↓
AI Router
        ↓
AI Provider
        ↓
Model
```

Business services should request an AI task.

Examples:

```text
ANALYZE_MARKET_TRENDS
GENERATE_CONTENT_BRIEF
GENERATE_CHANNEL_EXECUTION
GENERATE_CONTENT_DRAFT
GENERATE_HOOK_VARIATIONS
ANALYZE_PERFORMANCE
EXTRACT_AUDIENCE_SIGNALS
SYNTHESIZE_SIGNALS
```

They should not directly select:

```text
Gemini
OpenAI
Claude
```

The AI Router determines the appropriate provider/model based on:

* task complexity,
* quality requirements,
* latency,
* cost,
* modality,
* availability.

---

# 45. AI TASK ≠ AI CAPABILITY

Maintain a distinction between:

```text
AI Task
```

and:

```text
AI Capability
```

Example:

```text
Task:
GENERATE_CONTENT_BRIEF

Capabilities:
Text Generation
Retrieval
Reasoning
Structured Output
```

This keeps the AI platform flexible and prevents provider-specific coupling.

---

# 46. CONTEXT ENGINE

Before calling an AI model, construct task-specific context.

Do not dump the entire profile or entire RAG database into every prompt.

Use:

```text
AI Task
    ↓
Context Requirements
    ↓
Hybrid Retrieval
    ↓
Relevant Context
    ↓
Context Builder
    ↓
AI Model
```

The Context Engine should control:

* relevance,
* token budget,
* freshness,
* source priority,
* intelligence domains,
* evidence requirements,
* global vs tenant scope.

---

# 47. MULTIMODAL ARCHITECTURE

The AI infrastructure must support:

```text
Text
Image
Video
Audio
Multimodal
```

Do not design the AI layer around text-only generation.

However, do not introduce unnecessary multimodal complexity into domain modules until the relevant product feature requires it.

---

# 48. CREATION ARCHITECTURE

Creation is an execution layer.

It consumes the strategy contract.

```text
ContentOpportunity
        ↓
ContentBrief
        ↓
ChannelExecutionSpec
        ↓
AI Orchestrator
        ↓
AI Router
        ↓
Specialized AI Capability
        ↓
ContentDraft / Asset
```

Possible creation modules:

```text
Copywriter
Hook Generator
Caption Generator
Script Generator
Visual Direction
Image Generation
Video Generation
UGC Generation
Remix Engine
Asset Assembly
```

These modules must remain downstream from Strategy and Brief.

---

# 49. CONTENT LINEAGE

Every generated asset must preserve lineage.

Example:

```text
ContentAsset
    ↓
ContentDraft
    ↓
ChannelExecutionSpec
    ↓
ContentBrief
    ↓
ContentOpportunity
    ↓
Strategic Signals
    ↓
Intelligence
    ↓
Knowledge Sources
```

This allows the system to answer:

> Why was this content created?

and:

> Which strategic signals produced this content?

---

# 50. CONTENT STATE MACHINE

Content generation should be state-driven.

Example states:

```text
GENERATED
UNDER_REVIEW
EDITED
APPROVED
STALE_STRATEGY_MISMATCH
EXECUTION_SPEC_CHANGED
ASSET_REGENERATION_REQUIRED
PUBLISHED
ARCHIVED
```

State transitions must be explicit.

Do not silently mutate the lifecycle.

---

# 51. PERFORMANCE LEARNING LOOP

After publishing:

```text
Published Asset
      ↓
Performance Ingestion
      ↓
Metric Snapshots
      ↓
Performance Analyzer
      ↓
Performance Insight
      ↓
Learning Signal
      ↓
Profile Intelligence
```

With human feedback:

```text
Human Edit
      ↓
Human Feedback Signal
      ↓
Learning Signal
      ↓
Profile Intelligence
```

Final learning model:

```text
Audience Response
+
Performance Metrics
+
Human Preference
+
Experiment Results
+
Market Signals
+
Strategic Fit
        ↓
Learning
        ↓
Profile Intelligence
```

---

# 52. DATABASE ARCHITECTURE

Use:

```text
PostgreSQL / Neon
+
pgVector
```

as the canonical persistence layer.

Recommended infrastructure:

```text
FastAPI
PostgreSQL / Neon
pgVector
Redis
Background Workers
SQLAlchemy
Alembic
```

Start as a:

> Modular Monolith.

Do NOT start with microservices unless explicitly required.

The architecture must nevertheless have clear module boundaries so that specific components can later become independent workers/services.

---

# 53. ASYNCHRONOUS PROCESSING

Long-running or non-critical operations should not block synchronous API requests.

Use background workers for:

* embeddings,
* social metric ingestion,
* webhook processing,
* signal synthesis,
* clustering,
* performance analysis,
* experiment evaluation,
* AI-heavy processing where appropriate.

Preferred pattern:

```text
API Request
    ↓
Persist Canonical Data
    ↓
Emit Event / Queue Job
    ↓
Background Worker
    ↓
Process
    ↓
Persist Result
```

---

# 54. ASYNCHRONOUS EMBEDDING PIPELINE

Embedding generation should not block normal request paths.

Preferred flow:

```text
Save Canonical Record
        ↓
Emit Event
        ↓
Embedding Worker
        ↓
Generate Embedding
        ↓
Save Knowledge Chunk
```

Store:

```text
embedding_model
embedding_version
```

to support future re-embedding.

---

# 55. MODULAR MONOLITH BOUNDARIES

Recommended logical modules:

```text
auth
workspace
profile

brand_intelligence
audience_intelligence
market_intelligence
performance_intelligence

signal
signal_synthesizer

opportunity
experiment

brief
channel_execution

content_creation
content_asset

publishing
performance_ingestion
analytics

learning
rag
ai_platform
```

These should initially be modules inside the monolith.

Do not create unnecessary network boundaries between them during MVP.

---

# 56. FUTURE SCALING PATH

### MVP

```text
FastAPI
+
Neon PostgreSQL
+
pgVector
+
Redis
+
Background Workers
+
Modular Intelligence Modules
+
AI Orchestrator / Router
+
Hybrid Retrieval
+
Performance Ingestion
```

### Growth

Introduce:

```text
Asynchronous Intelligence Workers
Queue
Dedicated Processing Workers
Signal Synthesis Workers
Performance Analysis Workers
```

### Later Scale

Potentially introduce:

```text
Kafka / Redpanda
Event-driven architecture
Independent Intelligence Workers
Independent AI Workers
Dedicated Ingestion Services
```

Do not prematurely introduce Kafka, microservices, or distributed infrastructure.

Design interfaces and events so they can be introduced later.

---

# 57. STRATEGIC BOUNDARIES

Maintain the following separation:

```text
CONTENT INTELLIGENCE
"What is happening?"
        ↓
RAW EVENTS
"What evidence exists?"
        ↓
SIGNAL SYNTHESIS
"What meaningful patterns emerge?"
        ↓
STRATEGIC SIGNALS
"What matters?"
        ↓
OPPORTUNITY
"What should we consider creating?"
        ↓
BRIEF
"How should this content strategically be executed?"
        ↓
CHANNEL EXECUTION
"How should this strategy adapt to each platform?"
        ↓
CREATION
"Generate the actual content."
        ↓
PUBLISH
"Distribute it."
        ↓
MEASURE
"What happened?"
        ↓
LEARNING
"What did we learn?"
```

Never collapse these layers into one AI prompt or one service.

---

# 58. NON-NEGOTIABLE ARCHITECTURAL PRINCIPLES

### Principle 1

Content Intelligence is the central brain.

### Principle 2

ContentProfile is the universal strategic root.

### Principle 3

Businesses and creators use the same Strategy Engine.

### Principle 4

BusinessContext is optional.

### Principle 5

Trends are inputs, not automatic content generators.

### Principle 6

Raw intelligence events must pass through Signal Synthesis.

### Principle 7

Signals must be deduplicated, clustered, thresholded, and freshness-aware.

### Principle 8

Content Opportunities are mandatory before content creation.

### Principle 9

Content Briefs are mandatory strategic contracts before creation.

### Principle 10

One Content Brief may generate multiple Channel Execution Specifications.

### Principle 11

Human edits are learning signals.

### Principle 12

Human preference and audience performance are separate signals.

### Principle 13

Upstream edits must trigger appropriate downstream invalidation.

### Principle 14

The system must balance Exploration and Exploitation.

### Principle 15

Exploration must adapt to profile maturity.

### Principle 16

Performance Intelligence must explain WHY content worked or failed.

### Principle 17

Performance metrics must be stored as immutable historical snapshots.

### Principle 18

Performance retrieval must support relational numerical filtering before semantic retrieval.

### Principle 19

Every published content asset should contribute to future intelligence.

### Principle 20

RAG must be grounded, scoped, temporal, and traceable.

### Principle 21

Global knowledge and tenant knowledge must have explicit scope boundaries.

### Principle 22

AI provider selection belongs to the AI Router, not business logic.

### Principle 23

Workspace membership is the tenant/collaboration boundary.

### Principle 24

ContentProfile is the strategy boundary.

### Principle 25

Intelligence is the knowledge boundary.

### Principle 26

The architecture should start simple but remain evolution-ready.

---

# 59. CANONICAL END-TO-END ARCHITECTURE

```text
                              USER
                                │
                                ▼
                           WORKSPACE
                                │
                                ▼
                         CONTENT PROFILE
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
          ▼                     ▼                     ▼
        BRAND                AUDIENCE              MARKET
    INTELLIGENCE           INTELLIGENCE          INTELLIGENCE
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                │
                                ▼
                      PERFORMANCE INTELLIGENCE
                                │
                                ▼
                    RAW INTELLIGENCE EVENTS
                                │
                                ▼
                       SIGNAL SYNTHESIZER
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
         Deduplicate         Cluster          Threshold
              │                 │                 │
              └─────────────────┼─────────────────┘
                                ▼
                       STRATEGIC SIGNALS
                                │
                                ▼
                       OPPORTUNITY ENGINE
                                │
                   ┌────────────┴────────────┐
                   ▼                         ▼
             EXPLOITATION               EXPLORATION
             Proven Patterns            New Experiments
                   │                         │
                   └────────────┬────────────┘
                                ▼
                         CONTENT BRIEF
                                │
                                ▼
                       HUMAN REVIEW / EDIT
                                │
                                ▼
                   CHANNEL EXECUTION SPECS
                                │
                 ┌──────────────┼──────────────┐
                 ▼              ▼              ▼
              Instagram      LinkedIn       YouTube
                 │              │              │
                 ▼              ▼              ▼
               Draft          Draft          Draft
                 │              │              │
                 └──────────────┼──────────────┘
                                ▼
                       HUMAN REVIEW / EDIT
                                │
                                ▼
                         ASSET ASSEMBLY
                                │
                                ▼
                       HUMAN REVIEW / EDIT
                                │
                                ▼
                             PUBLISH
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
             WEBHOOK INGESTION       SCHEDULED POLLING
                    │                       │
                    └───────────┬───────────┘
                                ▼
                       METRIC SNAPSHOTS
                                │
                                ▼
                    PERFORMANCE ANALYZER
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
                 SQL/Stats   Semantic    Temporal
                 Analysis    Analysis    Analysis
                    │           │           │
                    └───────────┼───────────┘
                                ▼
                         LEARNING SIGNALS
                                │
                   ┌────────────┴────────────┐
                   ▼                         ▼
            Performance Signal        Human Feedback
                   │                         │
                   └────────────┬────────────┘
                                ▼
                             LEARNING
                                │
                                ▼
                      PROFILE INTELLIGENCE
                                │
                                └──────────────►
                                  NEXT OPPORTUNITY
```

---

# 60. UNIVERSAL RAG ARCHITECTURE

```text
                         KNOWLEDGE
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
          GLOBAL KNOWLEDGE           TENANT KNOWLEDGE
                 │                         │
                 │                ┌────────┴────────┐
                 │                ▼                 ▼
                 │            WORKSPACE          PROFILE
                 │             SCOPE              SCOPE
                 │                │                 │
                 └────────────────┼─────────────────┘
                                  ▼
                         RETRIEVAL SCOPE
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
                 Semantic       Keyword       Temporal
                 pgVector       SQL           Filters
                    │             │             │
                    └─────────────┼─────────────┘
                                  ▼
                           Hybrid Ranker
                                  │
                                  ▼
                           Context Builder
                                  │
                                  ▼
                              AI TASK
                                  │
                                  ▼
                        Structured Insight
                                  │
                                  ▼
                               SIGNAL
                                  │
                                  ▼
                            OPPORTUNITY
```

---

# 61. DEVELOPMENT RULE

When implementing any feature, always ask:

1. Which domain owns this feature?
2. Is it Strategy, Intelligence, Execution, or Learning?
3. Does it belong to ContentProfile or Workspace?
4. Does it create a Raw Intelligence Event?
5. Should the event pass through Signal Synthesis?
6. Does it create or update a Strategic Signal?
7. Does it require an Opportunity?
8. Does it require a ContentBrief?
9. Does it require a ChannelExecutionSpec?
10. Could an upstream change invalidate downstream content?
11. Should it create a Learning Signal?
12. Does it require RAG?
13. Does retrieval require Global + Tenant knowledge?
14. Does it require structured numerical filtering?
15. Is the AI provider abstracted behind the AI Router?
16. Does the implementation preserve Human-in-the-Loop?
17. Does the implementation preserve Exploration vs Exploitation?
18. Does it preserve content lineage?
19. Can the feature be traced back to the core product loop?
20. Can the feature evolve from the modular monolith into asynchronous workers later?

Do not bypass domain boundaries simply to make implementation faster.

---

# 62. MVP IMPLEMENTATION PHILOSOPHY

Prefer:

```text
Simple
Deterministic
Traceable
Testable
Modular
Observable
Evolution-ready
```

over:

```text
Over-engineered
Distributed
Opaque
Model-dependent
Fully autonomous
```

The MVP should not attempt to solve every possible intelligence problem.

But its architecture must preserve the ability to evolve into:

```text
Adaptive
Personalized
Multimodal
Experiment-driven
Human-guided
Continuously learning
Content Intelligence
```

---

# 63. FINAL PRODUCT PRINCIPLE

The product should never become:

> "Tell me a trend and I will generate a post."

It should become:

> "I understand who you are, who your audience is, what is happening in your market, what has worked for you, what you prefer, what you have not tested yet, what your current goal is, and therefore what content you should create next. I can turn that strategic decision into platform-specific executions, let you shape the result, measure what happened, understand why it happened, and continuously learn from both your decisions and your audience's response."

That is the core architecture and product philosophy of the AI Content Operating System.
