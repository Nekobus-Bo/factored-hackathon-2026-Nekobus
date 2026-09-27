# Labeling Rubric for Human-Written Test Sets

This document defines the authoritative labeling rubric and protocol for authoring and double-labeling the human-written evaluation test sets (`data/eval/synthetic/decision.test.jsonl`) across Spanish (`es`), Portuguese (`pt`), and English (`en`).

The taxonomy and schema match `data/eval/synthetic/schema.yaml` and the calibration harness contract ([ADR-0010](adr/0010-model-selection-calibration-harness.md)).

---

## 1. Quality Principles & Protocol (docs/data.md §5)

To guarantee evaluation integrity and reproducibility:

1. **Rubric first:** Every annotator reads and follows this rubric. No labeling begins without agreed-upon boundaries.
2. **Written by humans:** The test set is authored and labeled by human domain experts/annotators. It is **never** generated or augmented by the training generator or any LLM.
3. **Stratified by language and intent:** Rows must be balanced across all 15 intents and all 3 supported languages (`es`, `pt`, `en`). Target minimum size: **10 examples per intent per language** ($15 \times 3 \times 10 = 450$ rows total).
4. **Anti-leakage:** Labelers **never see model predictions or prompts** while writing or annotating utterances. The test split is frozen **before** any system or baseline is run against it.
5. **Double-labeling (20% sample):** At least 20% of all authored utterances ($90+$ rows) are independently labeled by a second annotator without seeing the first annotator's choices.
6. **Inter-annotator agreement:** Calculate and report **Cohen's Kappa ($\kappa$)** on the double-labeled sample. Target agreement: $\kappa \ge 0.85$.
7. **Conflict resolution & rubric updates:** All disagreements are reviewed. If an edge case exposes ambiguity, **this rubric is updated** with an explicit boundary rule, and any previously labeled affected examples are relabeled.
8. **Synthetic PII only:** Test utterances must use **strictly fictitious** names, numbers, and identifiers. Never copy records or real data from the organization's raw dataset.

---

## 2. Intent Taxonomy (15 Intents)

When an utterance contains multiple conversational clauses (e.g., greeting + problem, or problem + request), label the **dominant, most specific actionable intent**. For instance, `"Hola, me robaron la tarjeta"` is `report_stolen_card`, not `greeting`. If a user states a lost card and immediately commands a block (`"Perdí mi tarjeta, por favor bloquéenla"`), label `request_card_block`.

### 1. `report_unrecognized_charge`
- **Definition:** Customer reports an unexpected, unfamiliar, or unauthorized charge on their card or bank statement.
- **Decision Boundaries:**
  - *vs. `request_dispute`:* Customer is reporting the anomaly/fact of an unfamiliar charge. If the customer explicitly demands a formal dispute, claim, refund, or chargeback process, use `request_dispute`.
  - *vs. `report_suspicious_activity`:* Customer references a specific posted/pending financial transaction vs. general login alerts, phishing SMS, or account tampering without a specific charge.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"Aparece un cobro de $85.000 en Falabella que yo no reconozco."`
    - *Negative:* `"Quiero abrir una disputa para que me devuelvan el cobro de Falabella."` (*Label:* `request_dispute`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Tem uma compra de R$ 120 na Amazon que não fui eu quem fez."`
    - *Negative:* `"Quero contestar essa transação da Amazon e estornar o valor."` (*Label:* `request_dispute`)
  - **English (`en`):**
    - *Positive:* `"There is an unknown charge of $45 from Target on my statement."`
    - *Negative:* `"I need to file a formal dispute for the charge from Target."` (*Label:* `request_dispute`)

### 2. `report_lost_card`
- **Definition:** Customer states that their physical payment card was misplaced, forgotten, or lost, without any evidence or allegation of criminal theft or robbery.
- **Decision Boundaries:**
  - *vs. `report_stolen_card`:* Lost implies misplaced/forgotten (e.g. left in taxi/restaurant). Stolen requires an explicit criminal taking, theft, robbery, or mugging.
  - *vs. `request_card_block`:* Customer describes the lost status without an explicit imperative command to freeze/block the card.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"No encuentro mi tarjeta por ninguna parte, creo que la dejé en el restaurante."`
    - *Negative:* `"Me abrieron el bolso en el metro y me sacaron la tarjeta."` (*Label:* `report_stolen_card`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Perdi meu cartão em algum lugar do shopping e não acho mais."`
    - *Negative:* `"Fui assaltado no ponto de ônibus e levaram meu cartão."` (*Label:* `report_stolen_card`)
  - **English (`en`):**
    - *Positive:* `"I misplaced my debit card yesterday and can't find it anywhere."`
    - *Negative:* `"Someone snatched my wallet containing my card on the train."` (*Label:* `report_stolen_card`)

### 3. `report_stolen_card`
- **Definition:** Customer explicitly reports that their card was stolen, robbed, snatched, or taken unlawfully.
- **Decision Boundaries:**
  - *vs. `report_lost_card`:* Stolen involves an explicit criminal taking or theft.
  - *vs. `request_card_block`:* Pure report of the theft event. If the customer explicitly commands an immediate block, prioritize `request_card_block`.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"Me acaban de robar la billetera con mi tarjeta débito."`
    - *Negative:* `"Creo que olvidé mi tarjeta en el cajero automático."` (*Label:* `report_lost_card`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Meu cartão de crédito foi roubado hoje cedo quando arrombaram meu carro."`
    - *Negative:* `"Não me lembro onde deixei meu cartão ontem à noite."` (*Label:* `report_lost_card`)
  - **English (`en`):**
    - *Positive:* `"My wallet was stolen from my gym locker along with my credit card."`
    - *Negative:* `"I dropped my credit card somewhere in the park."` (*Label:* `report_lost_card`)

### 4. `report_suspicious_activity`
- **Definition:** Customer reports general security anomalies, unexpected login alerts, phishing messages, or tampering suspicion, without identifying a specific executed transaction.
- **Decision Boundaries:**
  - *vs. `report_unrecognized_charge`:* Suspicious activity is about general signals, alerts, or strange attempts, not a concrete charge on their statement.
  - *vs. `report_stolen_card`:* The physical card remains in possession or status is unknown, but suspicious online/security events occurred.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"Me llegó un mensaje de texto alertando sobre un intento de acceso sospechoso a mi banca móvil."`
    - *Negative:* `"Hay una compra sospechosa de $50 en Netflix que yo no hice."` (*Label:* `report_unrecognized_charge`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Recebi um e-mail estranho dizendo que tentaram mudar minha senha bancária."`
    - *Negative:* `"Apareceu um débito de R$ 90 que eu não autorizei."` (*Label:* `report_unrecognized_charge`)
  - **English (`en`):**
    - *Positive:* `"I received a security SMS about an unrecognized login attempt from another device."`
    - *Negative:* `"There is a strange charge of $30 from Uber on my card."` (*Label:* `report_unrecognized_charge`)

### 5. `request_card_block`
- **Definition:** Customer explicitly commands or requests that their payment card be blocked, frozen, locked, or deactivated immediately.
- **Decision Boundaries:**
  - *vs. `report_lost_card` / `report_stolen_card`:* The focus is the operational action requested ("freeze my card", "bloquear mi tarjeta"). If the message says *"I lost my card, please block it"*, the action `request_card_block` takes precedence.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"Por favor bloqueen mi tarjeta terminada en 4321 de inmediato."`
    - *Negative:* `"Se me perdió la tarjeta en el centro comercial."` (*Label:* `report_lost_card`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Bloqueie meu cartão final 9081 agora mesmo, por favor."`
    - *Negative:* `"Levaram minha bolsa com meus documentos e cartão."` (*Label:* `report_stolen_card`)
  - **English (`en`):**
    - *Positive:* `"Please freeze my debit card ending in 6543 right away."`
    - *Negative:* `"I can't seem to locate my card today."` (*Label:* `report_lost_card`)

### 6. `request_dispute`
- **Definition:** Customer explicitly requests to start a formal dispute, claim, chargeback, or refund process for a transaction.
- **Decision Boundaries:**
  - *vs. `report_unrecognized_charge`:* Customer explicitly asks for a dispute/claim/refund proceeding ("abrir disputa", "contestar", "chargeback", "file a dispute"), rather than just stating that a charge is unrecognized.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"Quiero abrir una reclamación formal y disputar ese cobro duplicado para que me reembolsen."`
    - *Negative:* `"Tengo un cargo desconocido de $40 en mi tarjeta."` (*Label:* `report_unrecognized_charge`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Quero iniciar o processo de contestação da compra de R$ 200 para receber meu estorno."`
    - *Negative:* `"Não reconheço esse lançamento na minha fatura."` (*Label:* `report_unrecognized_charge`)
  - **English (`en`):**
    - *Positive:* `"I want to dispute this transaction and request a full chargeback."`
    - *Negative:* `"I see an unauthorized charge on my account balance."` (*Label:* `report_unrecognized_charge`)

### 7. `request_human_agent`
- **Definition:** Customer explicitly asks to be transferred to or speak with a human customer support agent, operator, or representative.
- **Decision Boundaries:**
  - *vs. any problem report:* Label `request_human_agent` whenever the core request is demanding a human ("hablar con una persona", "falar com atendente", "talk to a representative"), regardless of whether they also mention frustration.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"No quiero hablar con un bot, comuníquenme con un asesor humano por favor."`
    - *Negative:* `"Tengo un problema grave con mi tarjeta de crédito."` (*Label:* `report_suspicious_activity` or specific report)
  - **Portuguese (`pt`):**
    - *Positive:* `"Me transfira para um atendente humano agora mesmo."`
    - *Negative:* `"Preciso de ajuda com um problema na minha conta."` (*Label:* `out_of_scope` or specific intent)
  - **English (`en`):**
    - *Positive:* `"Transfer me to a live agent please, I want to talk to a person."`
    - *Negative:* `"Can your system help me resolve an issue with my card?"` (*Label:* `out_of_scope`)

### 8. `provide_identity_data`
- **Definition:** Customer provides personal identification credentials or demographic attributes (full name, document number, document type, date of birth, email, phone) to identify or authenticate themselves.
- **Decision Boundaries:**
  - *vs. `provide_otp_code`:* Supplying personal identity credentials vs. submitting a temporary 6-digit OTP/security token.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"Mi nombre es Juan Pérez y mi cédula es 10234567."`
    - *Negative:* `"El código de seguridad que me llegó al celular es 482910."` (*Label:* `provide_otp_code`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Meu nome é Carolina Dias e meu CPF é 123.456.789-00."`
    - *Negative:* `"O token SMS que recebi é 982143."` (*Label:* `provide_otp_code`)
  - **English (`en`):**
    - *Positive:* `"My full name is Robert Smith and my passport number is P1234567."`
    - *Negative:* `"The OTP code sent to my phone is 746192."` (*Label:* `provide_otp_code`)

### 9. `provide_otp_code`
- **Definition:** Customer submits the one-time passcode (OTP), security token, or verification code sent to their registered contact channel.
- **Decision Boundaries:**
  - *vs. `provide_identity_data`:* Contains the temporary verification token, not permanent identity documents or card numbers.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"El código OTP que me llegó es 592814."`
    - *Negative:* `"Los últimos 4 dígitos de mi tarjeta son 4321."` (*Label:* `provide_identity_data`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Acabei de receber o código, é 304918."`
    - *Negative:* `"Minha data de nascimento é 20/08/1985."` (*Label:* `provide_identity_data`)
  - **English (`en`):**
    - *Positive:* `"The 6-digit verification code is 819203."`
    - *Negative:* `"My phone number is +1 555-0199."` (*Label:* `provide_identity_data`)

### 10. `confirm`
- **Definition:** Customer provides an affirmative response, acceptance, or confirmation ("yes", "proceed", "correct", "sim", "sí") to a previous question or prompt.
- **Decision Boundaries:**
  - *vs. `deny`:* Affirmative vs. negative.
  - *vs. actionable commands:* Pure confirmation utterance vs. an utterance containing a fresh banking request.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"Sí, confirmo que deseo bloquearla."`
    - *Negative:* `"No, cancela la solicitud."` (*Label:* `deny`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Sim, com certeza, pode prosseguir."`
    - *Negative:* `"Não, não faça isso."` (*Label:* `deny`)
  - **English (`en`):**
    - *Positive:* `"Yes, that is correct, go ahead."`
    - *Negative:* `"No, that's wrong, stop."` (*Label:* `deny`)

### 11. `deny`
- **Definition:** Customer provides a negative response, rejection, or cancellation ("no", "cancel", "stop", "não", "incorrect") to a previous question or prompt.
- **Decision Boundaries:**
  - *vs. `confirm`:* Negative vs. affirmative.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"No, no reconozco ese monto, cancela todo."`
    - *Negative:* `"De acuerdo, proceda."` (*Label:* `confirm`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Não, não quero bloquear agora."`
    - *Negative:* `"Sim, confirmo."` (*Label:* `confirm`)
  - **English (`en`):**
    - *Positive:* `"No, do not proceed with that action."`
    - *Negative:* `"Yes, please do."` (*Label:* `confirm`)

### 12. `check_balance`
- **Definition:** Customer requests their current account balance, card limit, or available funds.
- **Decision Boundaries:**
  - *vs. `check_recent_transactions`:* Inquiring about total available funds or balance vs. asking for a list of recent purchases/charges.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"¿Cuál es el saldo disponible en mi cuenta de ahorros?"`
    - *Negative:* `"¿Cuáles fueron los últimos movimientos que hice?"` (*Label:* `check_recent_transactions`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Gostaria de consultar o saldo da minha conta corrente."`
    - *Negative:* `"Me mostra as últimas compras da fatura."` (*Label:* `check_recent_transactions`)
  - **English (`en`):**
    - *Positive:* `"How much money do I currently have in my checking account?"`
    - *Negative:* `"Can I see my recent charges from this week?"` (*Label:* `check_recent_transactions`)

### 13. `check_recent_transactions`
- **Definition:** Customer asks to see their recent transaction history, account statement, or latest purchases.
- **Decision Boundaries:**
  - *vs. `check_balance`:* History of individual movements vs. aggregate balance.
  - *vs. `report_unrecognized_charge`:* Generic request to review transactions vs. reporting a specific suspicious/unknown charge.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"Quiero revisar los últimos 5 movimientos de mi tarjeta débito."`
    - *Negative:* `"¿Cuánto cupo disponible me queda?"` (*Label:* `check_balance`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Pode listar as últimas transações realizadas no meu cartão?"`
    - *Negative:* `"Qual o valor total do meu saldo?"` (*Label:* `check_balance`)
  - **English (`en`):**
    - *Positive:* `"Show me my latest transactions and purchase history."`
    - *Negative:* `"What is my card balance right now?"` (*Label:* `check_balance`)

### 14. `greeting`
- **Definition:** Polite conversational opening, salutation, or pleasantry ("hello", "good morning", "hola", "olá") with no substantive banking request attached.
- **Decision Boundaries:**
  - *vs. any task intent:* If a greeting is accompanied by an actionable request (e.g. `"Hola, perdí mi tarjeta"`), label the actionable intent (`report_lost_card`), NOT `greeting`.
  - *vs. `out_of_scope`:* Standard pleasantry vs. off-topic conversation (e.g. jokes, philosophy).
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"Hola, buenas tardes, ¿cómo te va?"`
    - *Negative:* `"Hola, buenos días, quiero saber mi saldo."` (*Label:* `check_balance`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Olá, bom dia! Tudo bem com você?"`
    - *Negative:* `"Bom dia, preciso bloquear meu cartão."` (*Label:* `request_card_block`)
  - **English (`en`):**
    - *Positive:* `"Hello, good morning to the support team."`
    - *Negative:* `"Hello, I need to report a stolen card."` (*Label:* `report_stolen_card`)

### 15. `out_of_scope`
- **Definition:** Utterances completely outside the bank's customer service scope (e.g. general knowledge questions, jokes, weather, loans, cryptocurrency trading advice, chit-chat).
- **Decision Boundaries:**
  - *vs. in-scope banking:* If it relates to checking balances, cards, disputes, or security, use the proper banking intent.
- **Examples:**
  - **Spanish (`es`):**
    - *Positive:* `"¿Cuál es la distancia entre la Tierra y la Luna?"`
    - *Negative:* `"¿Dónde puedo ver mis movimientos bancarios?"` (*Label:* `check_recent_transactions`)
  - **Portuguese (`pt`):**
    - *Positive:* `"Você pode me contar uma piada engraçada?"`
    - *Negative:* `"Quero falar com uma pessoa de verdade."` (*Label:* `request_human_agent`)
  - **English (`en`):**
    - *Positive:* `"What will the weather be like in Chicago tomorrow?"`
    - *Negative:* `"Can I dispute this unrecognized charge?"` (*Label:* `request_dispute`)

---

## 3. Slot Extraction Taxonomy (13 Slots)

Slots represent entity values extracted from text.

| Slot Name | PII? | Type / Allowed Values | What It Is | What It Is NOT |
|---|---|---|---|---|
| `document_type` | **No** | `value`: the surface form as written; `normalized`: `NATIONAL_ID`, `PASSPORT`, `FOREIGN_ID`, `TAX_ID` | Type of identity document mentioned. Mapping: cédula, CC, DNI, CPF, RG, ID card, driver's license, state ID → `NATIONAL_ID`; pasaporte, passaporte, passport → `PASSPORT`; NIE, RNE, cédula de extranjería → `FOREIGN_ID`; NIT, RUT, CNPJ, SSN → `TAX_ID`. | Do not include the number itself. |
| `document_number` | **Yes** | String (digits / alphanumeric) | The identity document identification number. | Do not include prefixes like `"No."`, `"CC"`, or labels. |
| `full_name` | **Yes** | String | Customer's stated full or partial name. | Do not include honorifics (`"Sr."`, `"Mr."`) or `"me llamo"`. |
| `birth_date` | **Yes** | String | Stated date of birth (`"15/04/1990"`, `"May 4th 1988"`). | Do not include transaction dates. |
| `email` | **Yes** | String (email format) | Customer email address (`"user@example.com"`). | Do not include domain prefixes or trailing punctuation. |
| `phone` | **Yes** | String (phone format) | Telephone / mobile phone number. | Do not include labels like `"tel:"` or `"celular"`. |
| `card_last4` | **No** | String (exactly 4 digits) | Last 4 digits of a payment card (`"4321"`). | Do not tag full PANs (use `card_number`). |
| `card_number` | **Yes** | String ($\ge 12$ digits) | Full or partial Primary Account Number (PAN). | Do not tag 4-digit card references. |
| `amount` | **No** | String (numeric / decimal) | Value of money (`"45.00"`, `"120"`, `"85.000"`). | Do NOT include the currency symbol (`$` or `USD`). |
| `currency` | **No** | String (ISO code or symbol) | Currency designation (`"$"`, `"USD"`, `"COP"`, `"BRL"`, `"€"`). | Do not include the numeric amount. |
| `merchant` | **No** | String | Store, merchant, or counterparty name (`"Amazon"`, `"Uber"`). | Do not include transaction descriptions like `"compra en"`. |
| `transaction_date` | **No** | String | Date, timestamp, or temporal reference of a transaction (`"ayer"`, `"yesterday"`, `"12/03/2026"`). | Do not tag birth dates. |
| `otp_code` | **Yes** | String (typically 4-8 digits) | One-time security token / passcode (`"482910"`). | Do not tag document or card numbers. |

### Span Extraction Rules
1. **Exact Substring Match:** `text[start:end]` must match `value` character for character.
2. **0-Indexed Half-Open Offsets:** `start` is inclusive; `end` is exclusive (Python slice notation).
3. **No Whitespace or Punctuation Padding:** Strip leading/trailing spaces and sentence punctuation (commas, periods, question marks), unless punctuation is intrinsic to the entity (e.g. `123.456.789-00` for CPF, or `45.50` for amount).
4. **Clean Boundary Separation:**
   - For `"$50"`, annotate two distinct slots:
     - `currency`: `value="$"`, `start=0`, `end=1`
     - `amount`: `value="50"`, `start=1`, `end=3`
5. **PII Safety in Test Sets:** All values for PII slots (`document_number`, `full_name`, `birth_date`, `email`, `phone`, `card_number`, `otp_code`) in `decision.test.jsonl` **must be completely synthetic/fictitious**. Real personal data is strictly forbidden.

---

## 4. File Format & Destination

- **File path:** `data/eval/synthetic/decision.test.jsonl`
- **Format:** JSON Lines (JSONL) — exactly one JSON object per line.
- **Required fields:**
  - `id` (string): Unique identifier prefixed by split and language (e.g. `"test-es-001"`, `"test-pt-042"`, `"test-en-105"`).
  - `split` (string): Strictly `"test"`.
  - `source` (string): Strictly `"human"`.
  - `lang` (string): `"es"`, `"pt"`, or `"en"`.
  - `text` (string): Raw customer utterance.
  - `intent` (string): One of the 15 valid intent strings.
  - `slots` (list of objects): Each object must have `type`, `value`, `start`, and `end`; `document_type` slots also carry `normalized`. This is the same format as `decision.train.jsonl` and `decision.validation.jsonl`, so `make calibrate` loads it unchanged.

### Example JSONL Record

```json
{"id": "test-es-001", "split": "test", "source": "human", "lang": "es", "text": "No reconozco un cargo de $45 en Netflix ayer", "intent": "report_unrecognized_charge", "slots": [{"type": "currency", "value": "$", "start": 25, "end": 26}, {"type": "amount", "value": "45", "start": 26, "end": 28}, {"type": "merchant", "value": "Netflix", "start": 32, "end": 39}, {"type": "transaction_date", "value": "ayer", "start": 40, "end": 44}]}
{"id": "test-pt-002", "split": "test", "source": "human", "lang": "pt", "text": "Meu nome é Joana Pereira e meu CPF é 987.123.456-10", "intent": "provide_identity_data", "slots": [{"type": "full_name", "value": "Joana Pereira", "start": 11, "end": 24}, {"type": "document_type", "value": "CPF", "normalized": "NATIONAL_ID", "start": 31, "end": 34}, {"type": "document_number", "value": "987.123.456-10", "start": 37, "end": 51}]}
{"id": "test-en-003", "split": "test", "source": "human", "lang": "en", "text": "Please block my debit card ending in 4321 right away", "intent": "request_card_block", "slots": [{"type": "card_last4", "value": "4321", "start": 37, "end": 41}]}
```

---

## 5. Step-by-Step Guide for Junior Annotators

Follow this workflow to create and validate human-written test examples:

### Step 1: Draft Synthetic Utterances
- Draft natural, varied customer utterances representing typical user phrasing, including colloquialisms, varied sentence structures, typos, and minor punctuation variations.
- Ensure strict adherence to **synthetic data rules**: use names like `"Carlos Gomez"`, `"Maria Silva"`, `"John Doe"`; synthetic emails (`"name@example.com"`); test card numbers (`"4111..."`); and fake ID numbers.
- Maintain balanced stratification: target 10 utterances per intent for your assigned language.

### Step 2: Annotate Intent
- Determine the dominant actionable intent using the decision boundaries in Section 2.
- If an utterance feels equally split between two intents, re-read the boundary rules. If still unresolved, flag it for team adjudication.

### Step 3: Extract and Verify Slot Spans
- Identify all slot occurrences matching the 13 slots in Section 3.
- Compute the 0-indexed character offsets:
  ```python
  assert text[start:end] == value, f"Span mismatch: {text[start:end]!r} != {value!r}"
  ```
- Verify that currency symbols and amounts are separated.
- Verify that label prefixes (`"cédula:"`, `"nombre:"`) are excluded from slot spans.

### Step 4: Double-Labeling & Inter-Annotator Agreement
- An independent teammate annotates a random 20% sample without viewing previous labels.
- Run the inter-annotator evaluation script to compute Cohen's $\kappa$ on intent and slot tags.
- Verify that agreement meets the threshold ($\kappa \ge 0.85$).

### Step 5: Adjudication & Rubric Maintenance
- Hold a review meeting for any discrepancies.
- Agree on the final gold standard label.
- If the discrepancy revealed a subtle edge case not covered here, update Section 2 or Section 3 of this rubric with the newly agreed rule.

### Step 6: Validate JSONL Format
- Validate each record against the schema rules:
  - Valid JSON on every line.
  - `split == "test"`.
  - `source == "human"`.
  - `locale` in `["es", "pt", "en"]`.
  - Character offsets strictly within bounds `0 <= start < end <= len(text)`.
- Save the validated file to `data/eval/synthetic/decision.test.jsonl`.
