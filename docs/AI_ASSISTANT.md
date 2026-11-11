# AI_ASSISTANT: the local AI helper (Ollama)

## 1. Purpose and limits
_Kairos (`docs/KAIROS.md`) builds on this helper as a tool-calling agent; D-56 sets what it may do.
Metis (`docs/METIS.md`), Kairos's AI researcher, uses it with thinking on to propose ideas that code
then tests (D-76)._

The AI helper explains and drafts. It **never** places, sizes, modifies, or cancels orders,
and it never runs during the bar-processing loop. Everything it produces is shown to the
user before anything is saved. Agora must be 100% usable without it.

## 2. Hardware and models
- Target machine: Windows laptop, RTX 3060 **6 GB** VRAM.
- Default model: **`qwen3.5:4b`** (Q4_K_M, ~3.4 GB): tool calling, thinking mode, long
  context; leaves room for context on 6 GB.
- Alternative: **`gemma4:e4b`**: stronger writing and instruction following, less context
  headroom.
- Do **not** default to 7–9B models on this card; they spill out of VRAM and slow down
  badly once context is added.
- Context: `num_ctx` Automatic by default (D-141): 32,768, stepping down one size when Ollama
  reports the model only partly on the graphics card; the setting also offers 8,192–65,536.
  (Was 8,192 until 2026-11-03: too small for Metis's brief plus its thinking.)
- Settings screen lists installed models and lets the user pick any; show a warning if the
  model's size + context likely exceeds available VRAM.
- Verify these model tags exist in the Ollama library at build time; if renamed, pick the
  closest equivalent and record it in `DECISIONS.md`. (Checked 2026-10-21, D-51: both exist;
  `gemma4:e4b` is larger than expected, so Settings warns about it on a 6 GB card.)

## 3. Provider interface
```python
class AIProvider(Protocol):
    def status(self) -> AIStatus: ...                 # installed, running, models, version
    def pull(self, model: str) -> Iterator[PullProgress]: ...
    def chat(self, messages, *, model, stream=True, format=None,
             options=None) -> Iterator[str] | str: ...
```
- `OllamaProvider` talks to `http://localhost:11434` (`/api/tags`, `/api/pull`,
  `/api/chat`, `/api/version`).
- `FakeAIProvider` returns canned, deterministic responses for tests and cloud sessions.
- Timeouts: 120 s per response; cancel button in the UI.

## 4. Detection and setup UX
1. On startup and when opening AI features, call `status()`.
2. States and what the UI shows:
   - **Not installed** → card: "Install the free AI helper" with a button opening
     ollama.com/download and two plain steps.
   - **Installed, not running** → "Start Ollama from your Start menu, then click Retry."
   - **Running, model missing** → "Download" button with a progress bar (size from Ollama).
   - **Ready** → features enabled; a small green "AI ready" pill in the top bar.
   - **Ready, model loaded** → "Running on: the graphics card (fast)", or, when Ollama's
     `/api/ps` reports less than 95% of the model on the graphics card, a warning with the fix
     (charger, laptop power/graphics mode, quit and restart Ollama) (D-100).
   - **Ollama started without the graphics card** (Windows, NVIDIA card present, Ollama's log
     says it found only the processor): Agora restarts Ollama by itself once nothing is using the
     AI, at most twice per run, and loads the model once so the first question is quick
     (`backend/ai/gpu.py`, setting `ai.fix_gpu`, D-101). Every request asks Ollama to keep the
     model loaded for 30 minutes, since Kairos and Metis work all the time.
3. Never block other features while checking.

### 4a. Agora keeps Ollama running (D-108)
While Agora is open and the AI helper is on, Agora checks every minute that Ollama answers and starts
it if it doesn't (Windows and macOS), then loads the model, at most once every 5 minutes.

## 5. Features

### 5.1 Explain a backtest
Context sent: strategy definition (or code summary), run params, metrics, warnings, top 5
best/worst trades, monthly returns, benchmark comparison. Prompt asks for: what worked,
what didn't, the biggest risk, and 2–3 concrete things to try next, in plain English, under
200 words. The response must not invent numbers: instruct it to use only the provided
figures, and post-check that every number in the reply appears in the context (strip or
flag otherwise).

### 5.2 Explain a trade
Context: the bars around entry/exit, indicator values at those bars, the rules that fired,
costs. Output: 3–5 sentences.

### 5.3 Metric Q&A
"What does Sharpe ratio mean?" → short answer using the user's actual value as the example.
Seed a small local glossary (`GLOSSARY.md` terms) into the system prompt.

### 5.4 Draft a strategy from an idea
Since D-119 (draft prompt version 3) every draft includes a 3 × ATR trailing stop unless the idea gives
its own or says not to.
_Since 2026-10-24 (D-104) the reply schema fixes only the outer shape; Agora tidies small-model
slips and its validator checks the rules._
- Input: the user's idea in plain English + market.
- Call `chat` with `format` = the Strategy Definition **JSON schema** (Ollama structured
  outputs).
- Validate with the same validator the builder uses. On failure, send the plain-English
  errors back to the model and retry (max 2 retries).
- Show the result in the visual builder as an **unsaved draft** with the AI's one-paragraph
  explanation. The user clicks Save. Saved versions are marked `created_by = ai_draft`.
- Indicators/blocks not supported by Agora → the draft says so instead of inventing them.

### 5.5 Paper-trading day summary
At the user's request (button on the session screen): trades taken, P&L, notable events,
data issues, vs backtest expectation.

## 6. Prompts
- Store prompts as versioned templates in `backend/ai/prompts/`.
- System prompt essentials: you are Agora's helper; plain English; no financial advice or
  predictions; only use provided data; say "I don't know" when the data doesn't say.
- Show a subtle footer under AI text: "AI-generated. Check important numbers."

## 7. Testing
- Unit tests use `FakeAIProvider`.
- Validation/retry loop tested with fake responses that are invalid, then valid.
- A `@pytest.mark.live` test checks real Ollama on the laptop (Diagnostics runs it).
