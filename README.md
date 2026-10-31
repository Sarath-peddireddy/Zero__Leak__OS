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
flowchart TB
    %% Buyer column (left): database outside, human inside, agent below
    subgraph BUY["🔴 Flipkart · Procurement (Buyer)"]
        BDB[("🗄️ Mandate DB<br/>target · walk-away price")]
        BH(["👤 Head of Sourcing"])
        BA["🤖 Procurement Agent<br/>asks 🙋 when stuck"]
        BDB ==>|"① hard limits"| BA
        BH -.->|"② whispers · /ceiling"| BA
    end

    %% Seller column (right): the mirror image
    subgraph SELL["🟢 Delhivery · Sales (Seller)"]
        SH(["👤 VP of Sales"])
        SDB[("🗄️ CPQ DB<br/>list price · floor price")]
        SA["🤖 Sales Agent<br/>asks 🙋 when stuck"]
        SH -.->|"② whispers · /floor"| SA
        SDB ==>|"① hard limits"| SA
    end

    %% Shared spine (center): every message takes the same path
    G{{"④ ⚙️ Python Guardrails<br/>price limits · RTO rule · copy check"}}
    BR[["⑤ 💬 The Boardroom<br/>live negotiation on Telegram"]]
    SO{{"⑥ ✍️ Executive Sign-Off Gate<br/>each VP taps ✅ before a deal or walk-away"}}
    C(["📜 Signed contract"])

    BA ==>|"③ draft offer"| G
    SA ==>|"③ draft offer"| G
    G ==>|"only valid offers are posted"| BR
    BR ==>|"deal or walk-away?"| SO
    SO ==>|"both sides ✅"| C

    classDef buyer fill:#ff4757,stroke:#c0392b,color:#fff,stroke-width:2px
    classDef seller fill:#2ed573,stroke:#1e9e50,color:#fff,stroke-width:2px
    classDef human fill:#ffd166,stroke:#e09f00,color:#3d2c00
    classDef data fill:#57606f,stroke:#2f3542,color:#fff
    classDef control fill:#5352ed,stroke:#3742fa,color:#fff,stroke-width:2px
    classDef board fill:#1e90ff,stroke:#0b5ed7,color:#fff,stroke-width:2px
    classDef gate fill:#8e44ad,stroke:#6c3483,color:#fff,stroke-width:2px
    classDef done fill:#2f3542,stroke:#1e2229,color:#fff,stroke-width:2px

    class BA buyer
    class SA seller
    class BH,SH human
    class BDB,SDB data
    class G control
    class BR board
    class SO gate
    class C done
    style BUY fill:transparent,stroke:#ff4757,stroke-width:2px,color:#ff6b81
    style SELL fill:transparent,stroke:#2ed573,stroke-width:2px,color:#2ed573
```

**How one negotiation flows, step by step (identical on both sides):**

1. **Hard limits:** each agent loads only its own database: the seller's floor price, the buyer's walk-away price. Neither sees the other's numbers.
2. **Whispers:** each human coaches their own agent from a private War Room, and can set a hard `/floor` or `/ceiling` for this deal.
3. **Draft:** the agent writes its next offer. When it is stuck, it pauses and asks its human instead (🙋).
4. **Guardrails:** Python checks every draft before the other side sees it. An offer outside the limits, or a copied instruction, is sent back for a rewrite.
5. **Boardroom:** only valid offers are posted, and the other agent replies. Steps 3-5 repeat.
6. **Sign-off:** neither agent can close a deal or walk away on its own. Each side's VP taps ✅ before anything is final.

### Careful AI (Governance & HITL)

No AI goes rogue. We built ZeroLeak OS with **"Defense in Depth"** so humans never lose control of the financial outcome.

* **The Executive Sign-Off Gate:** The AI agents do all the talking, but they cannot legally sign a deal or walk away. When they reach an agreement, the system pauses and pings the Human VP on Telegram: *"Deal reached at ₹41. ✅ Authorize Signature or ❌ Reject."*
* **InfoSec Constraints:** The AI is strictly trained to bluff without ever revealing its true walk-away price to the opponent.

### The Memory Pipeline (CI/CD for AI)

When an AI makes a mistake, our "Judge Agent" reads the chat and writes a new rule so it never happens again. But we don't just trust the AI blindly.

```mermaid
flowchart TB
    T[["⑦ 📄 Match ends<br/>transcript + every coaching note"]]

    %% Buyer column (left): judged by the buyer's own boss
    subgraph MB["🔴 Buyer playbook"]
        JB{{"⚖️ Judge as<br/>Head of Sourcing"}}
        STB[("⑧ ⏳ Staged rule<br/>not live yet")]
        SHB["⑨ 🧪 Shadow test<br/>5 matches with vs 5 without"]
        APB(["⑩ 👤 Head of Sourcing<br/>✅ Approve / ❌ Reject"])
        PB[("⑪ 🧠 Buyer playbook")]
        JB -->|"proposes a rule"| STB
        STB --> SHB
        SHB -->|"measured delta"| APB
        APB -->|"✅ only"| PB
    end

    %% Seller column (right): the mirror image
    subgraph MS["🟢 Seller playbook"]
        JS{{"⚖️ Judge as<br/>VP of Sales"}}
        STS[("⑧ ⏳ Staged rule<br/>not live yet")]
        SHS["⑨ 🧪 Shadow test<br/>5 matches with vs 5 without"]
        APS(["⑩ 👤 VP of Sales<br/>✅ Approve / ❌ Reject"])
        PS[("⑪ 🧠 Seller playbook")]
        JS -->|"proposes a rule"| STS
        STS --> SHS
        SHS -->|"measured delta"| APS
        APS -->|"✅ only"| PS
    end

    N(["⑫ 🔁 Next match<br/>only the lessons that fit the topic load each turn"])

    T --> JB
    T --> JS
    PB -.-> N
    PS -.-> N

    classDef judge fill:#5f27cd,stroke:#341f97,color:#fff,stroke-width:2px
    classDef data fill:#57606f,stroke:#2f3542,color:#fff
    classDef test fill:#5352ed,stroke:#3742fa,color:#fff,stroke-width:2px
    classDef human fill:#ffd166,stroke:#e09f00,color:#3d2c00
    classDef buyer fill:#ff4757,stroke:#c0392b,color:#fff,stroke-width:2px
    classDef seller fill:#2ed573,stroke:#1e9e50,color:#fff,stroke-width:2px
    classDef board fill:#1e90ff,stroke:#0b5ed7,color:#fff,stroke-width:2px

    class T,N board
    class JB,JS judge
    class STB,STS data
    class SHB,SHS test
    class APB,APS human
    class PB buyer
    class PS seller
    style MB fill:transparent,stroke:#ff4757,stroke-width:2px,color:#ff6b81
    style MS fill:transparent,stroke:#2ed573,stroke-width:2px,color:#2ed573
```

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

---

## 📸 See It Live (Telegram Walkthrough)

Real screenshots from a live test session on Telegram (31 October 2026). Three chats run the whole system: the **Boardroom**, a group where the two AI agents negotiate, and two private **War Rooms**, one DM for each human manager.

### 1. The Setup: one Boardroom, two War Rooms

<p align="center">
  <img src="docs/screenshots/01-boardroom-welcome.png" width="480" alt="Boardroom welcome message with Start, Status, End and Clear buttons">
  <br><sub><b>The Boardroom.</b> SwiftRoute (seller) and MegaMart (buyer) negotiate a 12-month freight contract here. No human types in this chat.</sub>
</p>

<table>
  <tr>
    <td width="50%" align="center" valign="top">
      <img src="docs/screenshots/02-sales-war-room.png" width="400" alt="Sales War Room welcome: private line to Arjun">
      <br><sub><b>Sales War Room.</b> The VP of Sales coaches Arjun in private. Neha never sees it.</sub>
    </td>
    <td width="50%" align="center" valign="top">
      <img src="docs/screenshots/03-procurement-war-room.png" width="400" alt="Procurement War Room welcome: private line to Neha">
      <br><sub><b>Procurement War Room.</b> The Head of Sourcing coaches Neha in private. Arjun never sees it.</sub>
    </td>
  </tr>
</table>

### 2. The Negotiation: two agents, zero humans in the chat

<table>
  <tr>
    <td width="50%" align="center" valign="top">
      <img src="docs/screenshots/04-negotiation-opening.png" width="400" alt="Opening exchange: Neha anchors at ₹38, Arjun defends value">
      <br><sub><b>The opening.</b> Neha anchors at ₹38 and plays a rival's ₹40 quote. Arjun deflects to value: a 99.98% on-time SLA and 15,000 trucks.</sub>
    </td>
    <td width="50%" align="center" valign="top">
      <img src="docs/screenshots/05-negotiation-deadlock.png" width="400" alt="Deadlock at ₹42 versus ₹41, Arjun walks away">
      <br><sub><b>The deadlock.</b> ₹42 vs ₹41. Arjun holds his minimum instead of giving up the final rupee (since then, a walk-away also needs the VP's sign-off).</sub>
    </td>
  </tr>
</table>

### 3. Guardrails: a bad offer never reaches the other side

<p align="center">
  <img src="docs/screenshots/06-guardrail-rto-blocked.png" width="520" alt="Blocked: Arjun drafted an RTO waiver on a 12-month contract">
  <br><sub><b>Seller guardrail.</b> Arjun drafted an RTO waiver the rate card only allows on 18+ month contracts. Python stopped it before Neha saw it.</sub>
  <br><br>
  <img src="docs/screenshots/07-guardrail-ceiling-blocked.png" width="520" alt="Blocked: Neha drafted ₹43, above her ceiling of ₹41">
  <br><sub><b>Buyer guardrail.</b> Neha drafted ₹43/parcel, above the ₹41 ceiling her manager set. Stopped and rewritten, and the manager is told why.</sub>
</p>

### 4. Escalation: when the AI is stuck, it asks a human

<p align="center">
  <img src="docs/screenshots/08-escalation-arjun.png" width="480" alt="Arjun asks his VP: hold at ₹43 or close the gap">
  <br><sub><b>🙋 Arjun needs a decision.</b> Deadlocked at ₹43, he pauses the Boardroom and asks his VP. Nothing is posted until the VP answers, and the answer becomes an order for the rest of the negotiation. The Executive Sign-Off Gate uses the same ✅ / ❌ flow before any deal is signed or any walk-away happens.</sub>
</p>

### 5. Dual Executive Reports: each side gets its own debrief

<table>
  <tr>
    <td width="50%" align="center" valign="top">
      <img src="docs/screenshots/09-report-sales-deal.png" width="400" alt="Seller's deal report: revenue, margin, missed upside">
      <br><sub><b>Seller's report (VP of Sales):</b> revenue, margin above the floor, and the money left on the table.</sub>
    </td>
    <td width="50%" align="center" valign="top">
      <img src="docs/screenshots/10-report-procurement-deal.png" width="400" alt="Buyer's report: savings versus current vendor and the mandate">
      <br><sub><b>Buyer's report (Head of Sourcing):</b> savings vs the current vendor, and the deal against the mandate.</sub>
    </td>
  </tr>
</table>

> **Why this matters:** this deal closed at ₹41/parcel, the rate-card floor, with 45-day terms. The seller's report flags it at once: ₹2/parcel, **₹2.88 Cr over the contract**, left on the table. That is the Goal Displacement described above, and it is why the Attention Hierarchy and the Executive Sign-Off Gate exist.

<details>
<summary>See the reports from a negotiation that ended in a walk-away</summary>
<br>
<table>
  <tr>
    <td width="50%" align="center" valign="top">
      <img src="docs/screenshots/11-report-sales-walkaway.png" width="400" alt="Seller's report after a walk-away">
      <br><sub>Seller's view: the last offer, what it would have earned, and the proposed playbook change.</sub>
    </td>
    <td width="50%" align="center" valign="top">
      <img src="docs/screenshots/12-report-procurement-walkaway.png" width="400" alt="Buyer's report after a walk-away">
      <br><sub>Buyer's view: the saving that was on offer and the open items.</sub>
    </td>
  </tr>
</table>
</details>

### 6. The Judge: no new lesson goes live without a shadow test and a human ✅

<table>
  <tr>
    <td width="50%" align="center" valign="top">
      <img src="docs/screenshots/13-judge-proposal-contract-length.png" width="400" alt="Playbook update proposed for the buyer, with shadow test results">
      <br><sub><b>Buyer lesson</b> from the coach's note, with its shadow-test result.</sub>
    </td>
    <td width="50%" align="center" valign="top">
      <img src="docs/screenshots/14-judge-proposal-sla.png" width="400" alt="Playbook update proposed for the seller, with shadow test results">
      <br><sub><b>Seller lesson</b> from the coach's note, with its shadow-test result.</sub>
    </td>
  </tr>
</table>

<sub>The Judge turns each coaching note into a proposed rule, plays silent AI-vs-AI matches with and without it, and sends the measured difference to the manager. The rule goes live only after ✅ Approve. These screenshots used 2 + 2 matches, a development setting; production runs 5 + 5.</sub>
