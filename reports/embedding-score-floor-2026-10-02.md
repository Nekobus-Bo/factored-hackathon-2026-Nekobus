# kb.search score floor for granite-embedding-311m-multilingual-r2

- **Date:** 2026-10-02
- **Model:** `ibm-granite/granite-embedding-311m-multilingual-r2` at `44399559930365213510b1ee2eb15ded83374f0e`, fp32, through `SentenceTransformersAdapter` (the vectors the model server returns)
- **Decision it backs:** `RETRIEVAL_SCORE_FLOOR` 0.3 → 0.80 ([ADR-0006](../docs/adr/0006-single-postgres-pgvector.md), amendment 2026-10-01)
- **Environment:** Darwin arm64, sentence-transformers 6.1.0, transformers 5.16.1

## Method

`kb.search` keeps a same-language result only if its normalized score (cosine clipped to [0, 1]) reaches the floor. If none does, it searches the other languages, and returns nothing if nothing there reaches it either. The floor should therefore sit above off-topic queries and below in-domain ones.

- **In-domain:** the 360 `validation` queries of `data/eval/synthetic/retrieval/queries.jsonl`, top-1 same-language score against the 120-snippet KB (`packages/retrieval/kb/snippets.jsonl`).
- **Off-topic:** 30 team-written queries with no banking content (below), top-1 same-language and cross-language scores.

## Results

| | Top-1 score |
|---|---|
| In-domain, lowest | 0.807 (es 0.807, pt 0.837, en 0.826) |
| In-domain, p5 / p50 / p95 (correct top-1) | 0.856 / 0.896 / 0.938 |
| Off-topic, highest same-language | es 0.787, pt 0.807, en 0.794 |
| Off-topic, highest cross-language | es 0.781, pt 0.806, en 0.789 |

| Floor | In-domain below the floor | Off-topic kept (same-language) | Off-topic kept (cross-language) |
|---:|---:|---:|---:|
| 0.30 (old seed) | 0 / 360 | 30 / 30 | 30 / 30 |
| 0.75 | 0 / 360 | 63% | 80% |
| 0.78 | 0 / 360 | 17% | 23% |
| 0.79 | 0 / 360 | 7% | 3% |
| **0.80** | **0 / 360** | **3% (1)** | **3% (1)** |
| 0.81 | 1 / 360 | 0% | 0% |
| 0.82 | 2 / 360 | 0% | 0% |

For comparison, MiniLM (`e8f8c211`) at 0.3 kept 1 of 12 off-topic queries (the first four of each language below) and put 3 of the 360 in-domain queries under the floor.

**Choice: 0.80.** It loses no in-domain query and keeps one off-topic query in 30, no worse than MiniLM at 0.3. The gap between the two populations is a few hundredths wide, so the value is provisional: re-derive it on a human-written set with out-of-scope queries, and on any model change.

## Off-topic queries

- **es:** receta de pizza casera con masa madre · quién ganó el partido de fútbol anoche · cómo arreglo la cadena de mi bicicleta · recomiéndame una película de terror · cuál es la capital de Australia · cómo cuido una planta de suculentas · letra de una canción de cumpleaños · qué tiempo hará mañana en Bogotá · ejercicios para el dolor de espalda · cuántas calorías tiene un aguacate
- **pt:** receita de bolo de cenoura com chocolate · qual a previsão do tempo para amanhã em São Paulo · como trocar o óleo do carro · me indica um livro de ficção científica · quem descobriu o Brasil · como treinar meu cachorro para sentar · melhores praias do nordeste · como fazer um currículo · qual a distância da Terra à Lua · dicas para dormir melhor
- **en:** best hiking trails near Denver · how do I fix a leaking kitchen faucet · who won the world cup in 2010 · write me a poem about the ocean · how many legs does a spider have · what's a good name for a cat · translate hello into Japanese · how long to boil an egg · who painted the Mona Lisa · tips for learning the guitar
