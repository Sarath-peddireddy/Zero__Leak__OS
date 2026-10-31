# ZeroLeak OS 🛡️
**The Autonomous B2B Deal Desk & Adversarial Negotiation Engine**

### The Bleed (The Problem)
Enterprise B2B negotiation is a zero-sum game plagued by human emotion and psychological pressure. 

Imagine a junior sales rep at a logistics company like **Delhivery** negotiating a contract with a veteran procurement buyer at **Flipkart**. On a live Zoom call, the Flipkart buyer bluffs and threatens to walk away. The junior rep panics and drops the price by just **₹2 per parcel** to save the deal. 

On a 1.5 million parcel/month contract, that single 30-second panic attack silently bleeds **₹3.6 Crores in pure profit annually**. Multiply that across a global sales floor, and it is an EBITDA crisis. 

### The Engine (The Solution)
ZeroLeak OS is an autonomous, multi-agent Deal Desk that removes human panic from the equation. 

We deploy two AI agents against each other in a live environment: **Sales** vs. **Procurement**. They handle the grueling, emotionally exhausting back-and-forth of contract negotiation, driven purely by data and limits in their backend databases. 

**The Side Effect (Extreme Training):** While the system is built to negotiate real contracts, it naturally serves as a brutal, risk-free training arena. Junior reps can jump in, take control of the AI, and practice against ruthless simulated buyers before they ever touch real company money.

---

### The Architecture (Symmetrical Self-Play)
The system is perfectly balanced. Both sides have an AI agent doing the talking, constrained by strict database limits, while Human VPs sit behind the scenes steering the strategy.

```mermaid
flowchart LR
    %% Buyer Side (Left)
    subgraph Procurement [Flipkart Procurement]
        HumanBuyer(👤 Head of Sourcing) -.->|Strategic Whispers| ProcAgent[🤖 Procurement Agent]
        ProcDB[(🗄️ Buyer Target DB)] ===>|Max Budget Limits| ProcAgent
    end

    %% The Arena (Center)
    subgraph Arena [ZeroLeak Orchestrator]
        ProcAgent <===>|Live Negotiation| SalesAgent
        Guardrails{⚙️ Python Guardrails} -.->|Blocks AI Hallucinations| ProcAgent
        Guardrails -.->|Blocks AI Hallucinations| SalesAgent
    end

    %% Seller Side (Right)
    subgraph Sales [Delhivery Sales]
        HumanSales(👤 VP of Sales) -.->|Strategic Whispers| SalesAgent[🤖 Sales Agent]
        SalesDB[(🗄️ Sales CPQ DB)] ===>|Floor Price Limits| SalesAgent
    end

    %% Custom Colors (Clear Theme)
    style ProcAgent fill:#e74c3c,stroke:#c0392b,color:#fff,stroke-width:2px
    style SalesAgent fill:#2ecc71,stroke:#27ae60,color:#fff,stroke-width:2px
    style HumanBuyer fill:#f39c12,stroke:#e67e22,color:#fff
    style HumanSales fill:#f39c12,stroke:#e67e22,color:#fff
    style Guardrails fill:#34495e,stroke:#2c3e50,color:#fff
    style ProcDB fill:#bdc3c7,color:#333
    style SalesDB fill:#bdc3c7,color:#333
    style Arena fill:#f8f9fa,stroke:#ced6e0,stroke-width:2px,stroke-dasharray: 5 5

```

### Careful AI (Governance & HITL)

No AI goes rogue. We built ZeroLeak OS with **"Defense in Depth"** so humans never lose control of the financial outcome.

* **The Executive Sign-Off Gate:** The AI agents do all the talking, but they cannot legally sign a deal or walk away. When they reach an agreement, the system pauses and pings the Human VP on Telegram: *"Deal reached at ₹41. ✅ Authorize Signature or ❌ Reject."*
* **InfoSec Constraints:** The AI is strictly trained to bluff without ever revealing its true walk-away price to the opponent.

### The Memory Pipeline (CI/CD for AI)

When an AI makes a mistake, our "Judge Agent" reads the chat and writes a new rule so it never happens again. But we don't just trust the AI blindly.

* **Shadow Testing:** Before a new rule goes live, the system instantly plays 5 silent background matches using the new rule.
* **Mathematical Proof:** It proves the rule makes more money, then sends a message to the Human VP: *"New tactic found. Shadow test shows it increases margin by +₹0.50. ✅ Approve."*

### The Scoreboard (Metrics)

We measure success through raw business impact:

1. **Margin Retained:** Average closing price vs. absolute floor price.
2. **Deal Velocity:** How many turns it takes to close.
3. **Deadlock Resolution:** How often the AI successfully de-escalates without bothering the human VP.

### The Frontier (Known Challenges)

Building autonomous negotiators exposed two fascinating challenges that we engineered around:

1. **Goal Displacement:** AI naturally wants to please people. It will often ignore its own rules just to make the opponent happy and close the deal. We fixed this by building an "Attention Hierarchy" that forces the AI to prioritize profit over agreement.
2. **Instruction Bleed:** When a human manager types an urgent command, the AI sometimes panics and quotes the manager directly to the opponent. We built anti-plagiarism filters to force the AI to act naturally.
