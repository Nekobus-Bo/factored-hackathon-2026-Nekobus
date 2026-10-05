# Pattern Blue · The Unveiling — narration script

3:00 film, 13 scenes, 266 words of voice-over. Times match the animatic (https://claude.ai/artifact/7HWUGZ4ttfUE7YwwzjyggW); after you record, the picture is retimed to your voice, so read naturally rather than chasing the clock.

## How to read it

- **Pace:** calm and unhurried, like a product keynote. About 130 words a minute. Let the pauses breathe; the music fills them.
- **Tone:** confident, never alarmed. Say numbers plainly, without emphasis tricks.
- **Emphasis:** the words in **bold**. Everything else stays even.
- **Pauses:** `/` is a short breath, `//` a full stop of about one second.
- **Pronunciation:** *Pattern Blue* (two even words). *banking-core* is never spoken. *es-CO*, *pt-BR* appear on screen only.
- **Recording:** a quiet, soft room (a closet with clothes works), phone or USB mic a hand's width away, 48 kHz WAV. Record each scene as its own take, then one full read. Leave 2 seconds of silence at the start of the file.

## Script

| # | Time | Voice-over | On screen |
|---|---|---|---|
| S01 | 0:03 | It's two in the morning. / And that charge **wasn't you**. | Lock screen: "Compra aprobada · USD 1.240,00 · Miami". The battery clock appears |
| S02 | 0:11 | In Latin America, fraud costs financial firms over **three and a half times** what was stolen. | 3.68× · LexisNexis True Cost of Fraud, Latin America, 2026 |
| | 0:17 | *(music only)* | CO ≈ 962,000 · MX 1.5 M · BR R$ 10.1 B · AR +21 % |
| | 0:21 | Automate badly, and you block **the wrong card**. / Wait, and **the card stays open**. | Title cards on the beat |
| | 0:25 | The hard part isn't answering. // It's deciding **safely**. | |
| S03 | 0:29 | *(music only: the alarm)* | PATTERN BLUE · compromised card reported |
| | 0:34 | Introducing **Pattern Blue**. / Customer service for banks that knows when to **act**, / when to **ask**, / and when to **hand off**. | Title card |
| S04 | 0:41 | It **acts**. The card is blocked in the conversation, / and it only says so after the bank's own database **confirms it**. | Chat in Spanish, receipt card |
| | 0:51 | Every action, / **a receipt**. | VERIFICADO CONTRA LA BASE DE DATOS |
| S05 | 0:59 | It **asks**. A small model inside the bank, / grounded in how Latin America **really writes**, / reads every message in about **twenty milliseconds**. | Four market phrases, confidence gauges |
| | 1:09 | When it isn't sure, / it **asks first**. | The clarifying question |
| S06 | 1:15 | And it knows **when to stop**. / A dispute goes to a person, / with **a brief**, not a transcript. | Back office case, then "100 %" |
| S07 | 1:31 | Here's the difference. // The language model writes the words and proposes the action. / But it holds **no keys**. | Exploded view |
| S08 | 1:45 | Three deterministic checks decide: / the state of the conversation, / the bank's policy, / and the database. | STATE · POLICY · DATABASE → Approved |
| S09 | 1:54 | Even when someone tries to **talk it out of the rules**. | Injection, Refused |
| | 2:01 | *(one second of silence)* The AI has a **voice**. // Not a **vote**. | Thesis title card |
| S10 | 2:05 | **Zero** unsafe actions across fifty-eight live scenarios. | Proof tiles |
| | 2:10 | About a twentieth of a cent per conversation. | |
| | 2:13 | And because safety lives in the core: / swap the model, / **keep the safety**. | |
| S11 | 2:20 | **One more thing.** | |
| | 2:23 | Your risk team can change a policy, / or switch on a whole new workflow, / in **seconds**. | Guardrails switch flips |
| | 2:29 | No code. / No deploy. / Every change on a hash-chained ledger. | |
| S12 | 2:34 | *(music only: next-episode cuts)* | A real OTP channel · Human-certified thresholds · Replayable evaluation · Your next workflow |
| | 2:42 | Next episode: / **Pattern Blue, in your bank.** | |
| S13 | 2:47 | Pattern Blue. // The AI has a voice. / Not a vote. | End card; the clock reaches 00:00.00 |

## Where every number comes from

| On screen | Source |
|---|---|
| 3.68× the amount lost | LexisNexis Risk Solutions, *True Cost of Fraud* Latin America, 2026-05-11 (risk.lexisnexis.com/global/en/about-us/press-room/press-release/20260511-tcof-mexico) |
| CO ≈ 962,000 | Superintendencia Financiera via La República, 2025-04-08: 3,073,403 complaints in 2024, 31.3 % unrecognized transactions |
| MX 1.5 M in one quarter | CONDUSEF via El Informador, 2026-07-06: 1.515 M complaints for possible fraud, Q1 2026, 3 of every 4 complaints |
| BR R$ 10.1 B | FEBRABAN via Poder360: losses to fraud and scams in 2024, +17 % |
| AR +21 % | UFECI (Ministerio Público Fiscal) via Chequeado, 2025-07-04: 34,000+ cybercrime reports in 2024 |
| 0 unsafe actions · 58 live scenarios · 100 % complete handoffs · USD 0.0005 | `reports/eval-live-2026-10-02-gpt-6-luna.md` |
| Local model 35 of 58, hosted 36 of 58 | `reports/eval-live-2026-10-02-qwen3.6-35b-a3b-think.md` |
| ~20 ms, four markets, 120,000+ real texts | `docs/00-problem.md` §4.6, `reports/intent-models-regional-datasets.md` |
| New workflow with no code | `docs/00-problem.md` §3.1 (account inquiry, 8 of 8) |

Sample values in the mockups (•••• 4821, aud_00020481, the gauge readings 0.82 / 0.31 with τ 0.37, the hashes) are demo data in the product's real formats, not measurements.

## Never say, even off-script

"Detects fraud", "real OTP", "biometrics", "certified", "replayable", "production-ready", "resolves disputes", "tamper-proof", "three languages", a pass rate.

## Music and sound

- **Music** (royalty-free only: YouTube Audio Library, Pixabay Music, Uppbeat). Search terms: "minimal piano tension" for 0:00–0:28, "dark cinematic choir build" for 1:30–2:04, a single piece with a quiet intro also works. Leave 2:01–2:02 silent before "The AI has a voice".
- **Sound effects** (Freesound CC0, Pixabay): a soft phone buzz at 0:02.6, low hits on each title card in S02, an alarm tone at 0:28.4, a stamp thud at 0:51.2, a hard digital glitch at 1:54, a sub-drop at 2:00.4, a switch click at 2:26.6.
