# ZeroLeak OS 🛡️

**Symmetrical Adversarial Multi-Agent Engine for B2B Deal Desks.**

### The Bloodbath (The Problem)
Enterprise B2B negotiation is a zero-sum game plagued by human error and psychological pressure. 

*   **The Sales Bleed (Margin Leakage):** A junior Account Executive gets ambushed on a Zoom call by a veteran buyer. They panic and yield just **₹2 per parcel** on a 1.5M parcel/month contract to save the deal. That single 30-second mistake silently bleeds **₹3.6 Crores in pure profit annually** (1.5M x 12 months x ₹2) from a single account. Multiply that across a sales floor, and it is an EBITDA crisis.
*   **The Procurement Bleed (Cost Inefficiency):** Junior Procurement Officers fail to leverage market conditions or competitor quotes, overpaying for multi-year vendor lock-ins and failing to secure RTO (Return to Origin) waivers. 

Both sides are leaving millions on the table because, right now, their only practice arena is when real money is on the line.

### The Engine (The Solution)
ZeroLeak OS is a Neuro-Symbolic, Adversarial Self-Play Arena. We deploy two autonomous, data-driven AI agents against each other in a live Telegram environment: **SwiftRoute Logistics (Sales)** vs. **MegaMart (Procurement)**.

Both agents negotiate fiercely based on distinct SQLite databases (CPQ floors vs. Target Mandates). Meanwhile, human executives (VP of Sales & Head of Sourcing) sit in isolated "War Rooms," whispering strategic overrides to their respective AIs in real-time. Post-match, our Split-Persona Judge audits the transcript and sends tailored executive reports to both department heads.

---

### Symmetrical Architecture (The Arena)

```mermaid
flowchart TB
    %% Buyer side (left): database outermost, human inside
    subgraph Buyer ["🔴 MegaMart · Buyer Side"]
        direction TB
        ProcDB[(🗄️ Mandates DB<br/>target · walk-away)]
        HumanBuyer(👤 Head of Sourcing)
        ProcAgent[🤖 Procurement Agent]
        ProcDB ==>|hard limits| ProcAgent
        HumanBuyer -.->|live whispers| ProcAgent
    end

    %% Seller side (right): mirror image
    subgraph Seller ["🟢 SwiftRoute · Seller Side"]
        direction TB
        HumanSales(👤 VP of Sales)
        SalesDB[(🗄️ CPQ DB<br/>list price · floor price)]
        SalesAgent[🤖 Sales Agent]
        HumanSales -.->|live whispers| SalesAgent
        SalesDB ==>|hard limits| SalesAgent
    end

    %% Every offer is checked before the opponent sees it
    ProcAgent -->|draft offer| Guardrails{{⚙️ Python Guardrails<br/>checks every price}}
    SalesAgent -->|draft offer| Guardrails
    Guardrails ==>|only valid offers posted| Boardroom[[💬 The Boardroom<br/>live Telegram negotiation]]

    %% Colours: red = buyer, green = seller, amber = humans, slate = data, purple = control, blue = arena
    classDef buyer fill:#ff4757,stroke:#c0392b,color:#fff,stroke-width:2px
    classDef seller fill:#2ed573,stroke:#1e9e50,color:#fff,stroke-width:2px
    classDef human fill:#ffd166,stroke:#e09f00,color:#3d2c00
    classDef data fill:#2f3542,stroke:#1e2229,color:#fff
    classDef control fill:#5352ed,stroke:#3742fa,color:#fff,stroke-width:2px
    classDef arena fill:#1e90ff,stroke:#0b5ed7,color:#fff,stroke-width:2px

    class ProcAgent buyer
    class SalesAgent seller
    class HumanBuyer,HumanSales human
    class ProcDB,SalesDB data
    class Guardrails control
    class Boardroom arena

    style Buyer fill:#fff1f2,stroke:#ff4757,stroke-width:2px,color:#c0392b
    style Seller fill:#effcf3,stroke:#2ed573,stroke-width:2px,color:#1e7e45
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
