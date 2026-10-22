<!--
  Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-->

# NoteCad Companion test run, 21 October 2026

Machine: 2 virtual CPUs, 7 GB RAM, no GPU (a slow laptop is faster than this). Models: Gemma 4 E2B
instruction-tuned, Q4_K_M GGUF (3.1 GB), and EmbeddingGemma 300M Q8_0 (0.33 GB), through llama-cpp-python 0.3.36.

## Update 22 October: the same tests on WABAKIPI's GPU

RTX 4060 Laptop GPU (8 GB), Ryzen 7 8845HS, Ollama 0.40.8 serving the same two GGUF files.

| | Cloud CPU (21 Oct) | WABAKIPI GPU (22 Oct) |
|---|---|---|
| All 42 tests incl. 3 live | 107 s | 5.7 s |
| Three-week owner simulation | 275 s | 10 s |
| One chat turn | 20-50 s | 0.6-2.4 s |
| Offline route | 20 s | 1.1 s |
| Generation speed | about 5 tokens/s | about 100 tokens/s |

The replies, learned facts, style and route matched the CPU run (`gemma4-e2b_owner-demo_gpu.json`, `pytest_gpu.txt`). Found on
the way: Ollama lets Gemma 4 think before answering, which used up the token budget and returned empty JSON;
the client now sends `reasoning_effort: none`. Smart App Control blocked the unsigned llama.cpp binaries, so
the desktop uses Ollama.

## Results

| Check | Result |
|---|---|
| Unit and API tests (scripted model) | 37 passed |
| Live tests with Gemma 4 E2B + EmbeddingGemma | 3 passed: Afrikaans question finds the English memory; recall plus style; offline router picks "die groot pomp" |
| Three-week owner simulation (`gemma4-e2b_owner-demo.json`) | See below |
| LoRA layer, tiny model (`lora_base-vs-owner.json`) | Owner's way of answering on 0 of 6 unseen questions before, 6 of 6 after |

## Three-week owner simulation, real model

- Facts learned from the first message, correctly typed: name Dennis, farmer, near Bronkhorstspruit,
  120 sheep, 300 cattle. "The vet, Dr Botha" is filed as `people.vet`.
- Recall a week later: "The vet, Dr Botha, is coming on Thursday at 10 for the ewes."
- Afrikaans in, Afrikaans out. After "Antwoord asseblief in Afrikaans van nou af" the language is fixed to
  Afrikaans: "Vir Donderdag is Dr Botha om 10:00 vir die ewes."
- Style learned from one edit, one complaint and a few thumbs: short 0.89, bullets 0.86, suggest a next step 0.80.
- Speech-to-text keyterms from the owner's own words: Dr Botha, Dennis, Bronkhorstspruit, dipping, ewes,
  weaners, borehole, rams, Dohne, Merino, paddock.
- Offline router on "die groot pomp lek baie erg, die bone het water nodig": note, critical status, alert and
  urgent task on Main Water Pump.
- Speed on this CPU: 20-50 s per chat turn (two model calls: fact extraction and reply), 20 s per offline route.
  Published phone figures for Gemma 4 E2B are about 55 tokens/s on LiteRT-LM and 47 on MLX (iPhone 17 Pro).

## Problems found with the real model, and what was changed

| Seen in the first run | Fix |
|---|---|
| A voice note "the rams in the north camp" overwrote `owns.cattle = 300` with "rams" | Model guesses can no longer overwrite a count, nor a fact the owner stated, unless the same guess repeats. Model fact extraction no longer runs on voice notes |
| Dr Botha filed as `people.manager` | Rule for "the vet, Dr Botha" (English and Afrikaans); model facts that repeat a rule value under another key are dropped |
| "What do I still need to do this week?" did not see the vet visit | Memories the owner asked to keep stay in view for 60 days |
| Keyterms included "near Bronkhorstspruit", "again", "morning" | Prefix stripped, filler words added to the stop lists |
| "Just give me the steps" was not taken as a style instruction | Added (English and Afrikaans) |

## Still open

- With the vet visit in view, the model still answered "I do not have a list of your tasks". The brain
  should send open tasks to the companion; a 2B model answers from a list it is given, not from scattered notes.
- Gemma 4 E2B wrote "vet" for the Afrikaans "veearts" once. Check Afrikaans quality on E4B before the pilot.
- The adapter learned the owner's phrasing but also made up a detail ("service the tractor in July"). The
  adapter is for how the owner likes answers; facts must keep coming from memory, never from the adapter.
- Tone did not settle in three weeks (formal 0.75, neutral 0.60): a thumbs-up rewards every style dimension
  at once. A per-dimension "too long / too formal" quick reply in the UI would give cleaner signal.
- Not yet run on a phone: LiteRT-LM (Android), MLX Swift (iOS) and Transformers.js (PWA) still need their thin
  client wrappers in Phase 3.
