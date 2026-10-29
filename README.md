# ZeroLeak OS 🛡️

**Adversarial Multi-Agent Simulation for Enterprise Deal Desks.**

### The Bleed (The Problem)
Your junior Account Executives are bleeding 3% of your profit margin every time a veteran procurement buyer bluffs them on a Zoom call. They panic. They yield on RTO (Return to Origin) penalties. They give away 60-day payment terms for free. 

**That 30-second panic attack costs your logistics company ₹2 Crores a year.** 

You cannot train humans to handle extreme psychological pressure using PowerPoint. They have to feel the heat. 

### The Plug (The Solution)
ZeroLeak OS is a Neuro-Symbolic, Multi-Agent training arena. We drop your junior Sales Reps into a live Telegram environment against an aggressive, autonomous AI Procurement Buyer. 

*   If the rep panics and drops the price, the AI takes their fake money.
*   The human VP of Sales watches live in the "War Room" and whispers strategic overrides to the rep mid-negotiation.
*   Post-match, our asynchronous **Judge Agent** analyzes the transcript, extracts the margin-leakage mistakes, and compacts them into a self-pruning SQLite Memory Playbook for future matches.

---

### System Architecture (The Arena)

```mermaid
graph TD
    subgraph Boardroom ["The Boardroom (Telegram Group)"]
        Procurement[MegaMart Procurement Agent] <-->|Negotiates| Sales[SwiftRoute Sales Agent]
    end
    
    subgraph WarRoom ["The War Room (Private DM)"]
        Manager[Human VP of Sales] -->|Whispers / Absolute Overrides| Sales
    end
    
    subgraph Guardrails ["Deterministic Guardrails"]
        Sales -->|JSON Output Validation| CPQ[(SQLite CPQ Database)]
        CPQ -.->|Blocks hallucinatory math| Sales
    end
    
    style Procurement fill:#ff6b6b,stroke:#c0392b,color:#fff
    style Sales fill:#4ecdc4,stroke:#16a085,color:#fff
    style Manager fill:#feca57,stroke:#f39c12,color:#fff
    style CPQ fill:#5f27cd,stroke:#341f97,color:#fff
```
