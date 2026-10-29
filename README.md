# ZeroLeak OS 🛡️

**Symmetrical Adversarial Multi-Agent Engine for B2B Deal Desks.**

### The Bloodbath (The Problem)
Enterprise B2B negotiation is a zero-sum game plagued by human error and psychological pressure. 
*   **The Margin Leakage:** Junior Sales Execs panic under pressure, yielding on SLAs and Payment Terms, silently bleeding 3% of corporate profit margins.
*   **The Cost Inefficiency:** Junior Procurement Officers fail to leverage market conditions or competitor quotes, overpaying for multi-year vendor lock-ins.

Both sides are leaving millions on the table because they only practice when real money is on the line. 

### The Engine (The Solution)
ZeroLeak OS is a Neuro-Symbolic, Adversarial Self-Play Arena. We deploy two autonomous, data-driven AI agents against each other in a live Telegram environment: **SwiftRoute Logistics (Sales)** vs. **MegaMart (Procurement)**.

Both agents negotiate fiercely based on distinct SQLite databases (CPQ floors vs. Target Mandates). Meanwhile, human executives (VP of Sales & Head of Sourcing) sit in isolated "War Rooms," whispering strategic overrides to their respective AIs in real-time. Post-match, our Split-Persona Judge audits the transcript and sends tailored executive reports to both department heads.

---

### Symmetrical Architecture (The Arena)

```mermaid
graph TD
    subgraph ProcWarRoom ["Procurement War Room"]
        HeadSourcing[Human Head of Sourcing] -.->|Tactical Whispers / Overrides| ProcAgent
    end

    subgraph Boardroom ["The Boardroom (Live Negotiation)"]
        ProcAgent[MegaMart Procurement Agent] <====>|Adversarial Self-Play| SalesAgent[SwiftRoute Sales Agent]
    end
    
    subgraph SalesWarRoom ["Sales War Room"]
        VPSales[Human VP of Sales] -.->|Tactical Whispers / Overrides| SalesAgent
    end

    subgraph DataGuardrails ["Data & Guardrails"]
        ProcDB[(Buyer Mandates DB)] --- ProcAgent
        SalesAgent --- SalesDB[(Sales CPQ DB)]
    end
    
    style ProcAgent fill:#ff6b6b,stroke:#c0392b,color:#fff
    style SalesAgent fill:#4ecdc4,stroke:#16a085,color:#fff
    style VPSales fill:#feca57,stroke:#f39c12,color:#fff
    style HeadSourcing fill:#feca57,stroke:#f39c12,color:#fff
    style ProcDB fill:#2c3e50,stroke:#2c3e50,color:#fff
    style SalesDB fill:#2c3e50,stroke:#2c3e50,color:#fff

```

### Cognitive Memory & Dual Executive Reporting

ZeroLeak OS features a Split-Persona Judge Agent. Because negotiation is zero-sum, a single AI judge would suffer from Reward Model Bias. We solve this by splitting the Judge's personality post-match to audit each agent independently.

```mermaid
graph TD
    A[Match Concludes] --> B(Match Transcript)
    B --> C{Split-Persona Judge}
    
    C -->|Persona: VP of Sales| D[Sales Audit]
    C -->|Persona: Head of Sourcing| E[Procurement Audit]
    
    D --> F[Sales Executive Report]
    D --> G[(Upsert: Sales Heuristics)]
    
    E --> H[Procurement Executive Report]
    E --> I[(Upsert: Procurement Heuristics)]

    style C fill:#5f27cd,stroke:#341f97,color:#fff
    style G fill:#0abde3,stroke:#0984e3,color:#fff
    style I fill:#0abde3,stroke:#0984e3,color:#fff

```

### Key Technical Innovations

1. **Symmetrical JIT (Just-In-Time) Retrieval:** To prevent LLM context-bloat, agents use In-Band JSON tagging (`"current_friction_points": ["RTO", "Price"]`). The Orchestrator intercepts these tags to fetch only the relevant opponent heuristics for the next turn. Memory stays at O(1).
2. **Dual-Way HITL Escalation:** If either agent hits a mathematical deadlock or is pushed to their absolute walk-away limit, they automatically pause the Boardroom and ping their respective Human Manager for a final decision ("Walk Away" vs "Close the gap").
3. **Neuro-Symbolic Guardrails:** The LLM's pricing outputs are constrained by deterministic Python logic. If an agent hallucinates a price outside its SQLite limits, the API call is intercepted and blocked before the opponent ever sees it.
