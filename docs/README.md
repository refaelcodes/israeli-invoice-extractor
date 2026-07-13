# docs/ — media for the README

Put the demo recording here so the main README can link to it.

## What to add
- **`demo.gif`** — a short (≤10 MB) autoplaying GIF of the extract → compare flow. GitHub renders a
  GIF inline; it does **not** embed YouTube/Vimeo iframes or `<video>` tags in Markdown, so a GIF
  preview + a link to the full video is the reliable pattern.
- **Full video** — record a 2–3 min walkthrough (Loom / YouTube) and paste the link into the README
  (`Live demo` and the hero caption).

## Suggested demo script (2–3 min)
1. First ~5 seconds: show the **result** — a document turning into JSON — not a logo/intro.
2. Extract one dataset document → point at the green/red field-by-field accuracy screen.
3. Show one **edge case**: upload a low-res or slightly-wrong document and show the arithmetic
   validator catching it (`NO_AMOUNTS` / a totals mismatch) — this is the "it doesn't hallucinate
   silently" moment.
4. Show a `null` field = the model declining to guess.
5. Close with one clear next step (CTA).

## Recording tips
- Clean audio matters more than 4K video. Export 1080p.
- Tools: OBS (free) or Loom; on Windows, Rapidemo / FocuSee add auto-zoom and cursor smoothing.
