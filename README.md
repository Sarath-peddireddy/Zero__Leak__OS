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
flowchart LR
    %% Buyer Side (Left)
    subgraph Procurement [MegaMart Procurement]
        HumanBuyer(👤 Head of Sourcing) -.->|HITL Overrides| ProcAgent[🤖 Procurement Agent]
        ProcDB[(🗄️ Mandates DB)] ===>|"Limits & Ammo"| ProcAgent
    end

    %% Seller Side (Right)
    subgraph Sales [SwiftRoute Sales]
        HumanSales(👤 VP of Sales) -.->|HITL Overrides| SalesAgent[🤖 Sales Agent]
        SalesDB[(🗄️ CPQ DB)] ===>|"Floor Price & Ammo"| SalesAgent
    end

    %% The Arena (Center)
    subgraph Arena [ZeroLeak Orchestrator]
        Guardrails{⚙️ Deterministic<br/>Python Guardrails}
    end

    %% Arena links (declared outside the boxes so each agent stays in its own side)
    ProcAgent <===>|Live Telegram<br/>Adversarial Play| SalesAgent
    Guardrails -.->|Intercepts Hallucinations<br/>Forces JSON Math| ProcAgent
    Guardrails -.->|Intercepts Hallucinations<br/>Forces JSON Math| SalesAgent

    %% Custom Colors
    style ProcAgent fill:#ff4757,stroke:#c0392b,color:#fff,stroke-width:2px
    style SalesAgent fill:#2ed573,stroke:#27ae60,color:#fff,stroke-width:2px
    style HumanBuyer fill:#feca57,stroke:#e67e22,color:#fff
    style HumanSales fill:#feca57,stroke:#e67e22,color:#fff
    style Guardrails fill:#5352ed,stroke:#3742fa,color:#fff
    style ProcDB fill:#2f3542,color:#fff
    style SalesDB fill:#2f3542,color:#fff
    style Arena fill:#f1f2f6,stroke:#ced6e0,stroke-width:2px,stroke-dasharray: 5 5
```

### Cognitive Memory & Dual Executive Reporting

ZeroLeak OS features a Split-Persona Judge Agent. Because negotiation is zero-sum, a single AI judge would suffer from Reward Model Bias. We solve this by splitting the Judge's personality post-match to audit each agent independently.

```mermaid
flowchart TD
    Transcript(📄 Match Concludes:<br/>Raw Transcript) --> Judge{⚖️ Split-Persona<br/>Judge Engine}

    %% Procurement Analysis Route
    subgraph ProcEval [Buyer Analysis]
        ProcReport[📊 Executive Buyer Report]
        ProcHeuristics[(🧠 Buyer Heuristics DB)]
    end

    %% Sales Analysis Route
    subgraph SalesEval [Seller Analysis]
        SalesReport[📊 Executive Sales Report]
        SalesHeuristics[(🧠 Sales Heuristics DB)]
    end

    %% Judge links (declared outside the boxes so the Judge stays above both)
    Judge -->|Loads Sourcing Persona| ProcReport
    Judge -->|Extracts Margin Leaks| ProcHeuristics
    Judge -->|Loads Sales VP Persona| SalesReport
    Judge -->|Extracts Margin Leaks| SalesHeuristics

    %% RLHF Feedback Loop
    ProcHeuristics -.->|In-Band JSON Tagging<br/>JIT Retrieval| NextMatch(Next Match Inject)
    SalesHeuristics -.->|In-Band JSON Tagging<br/>JIT Retrieval| NextMatch

    %% Custom Colors
    style Judge fill:#5f27cd,stroke:#341f97,color:#fff,stroke-width:2px
    style ProcHeuristics fill:#ff4757,stroke:#c0392b,color:#fff
    style SalesHeuristics fill:#2ed573,stroke:#27ae60,color:#fff
    style ProcReport fill:#f1f2f6,stroke:#ced6e0
    style SalesReport fill:#f1f2f6,stroke:#ced6e0
```

### Key Technical Innovations

1. **Symmetrical JIT (Just-In-Time) Retrieval:** To prevent LLM context-bloat, agents use In-Band JSON tagging (`"current_friction_points": ["RTO", "Price"]`). The Orchestrator intercepts these tags to fetch only the relevant opponent heuristics for the next turn. Memory stays at O(1).
2. **Dual-Way HITL Escalation:** If either agent hits a mathematical deadlock or is pushed to their absolute walk-away limit, they automatically pause the Boardroom and ping their respective Human Manager for a final decision ("Walk Away" vs "Close the gap").
3. **Neuro-Symbolic Guardrails:** The LLM's pricing outputs are constrained by deterministic Python logic. If an agent hallucinates a price outside its SQLite limits, the API call is intercepted and blocked before the opponent ever sees it.
