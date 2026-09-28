# FORMA Creative Brain

Permanent creative doctrine for every FORMA build video and every agent review.
Established from the sea-cave reference and the Alpine (Video #2) failures.
Machine-readable copy: `app/forma/doctrine.py` (every train-car prompt embeds it;
`tests/test_forma_doctrine.py` keeps the two in sync).

## Temporal realism — permanent rules

1. **SKIP REPETITION, NOT EXPLANATION.** A jump cut may remove repeated work,
   never the work that explains how something came to exist.
2. **Checkpoints define states; clips must visibly perform the work between them.**
3. **One major construction idea per sequence.**
4. **Show 70–90% of the task before a jump cut.**
5. **Causal labor:** visible progress must be caused by the builder's visible actions.
6. **Construction frontier: COMPLETED | ACTIVE WORK | UNTOUCHED** — every working frame reads this way.
7. **Stable cameras during tasks:** the camera never moves while construction happens;
   camera changes happen only at cuts.
8. **No magical spawning** of materials, structure, or furniture — everything has a visible
   source (stack, pile, delivery) and a visible installation.
9. **Interior work is shown progressively too** — no empty shell → finished room.
10. **Temporal realism matters more than photorealistic individual frames.**
11. **Distribute repetitive work with hard jump cuts:
    LOCAL ACTION → HARD JUMP CUT → REPOSITIONED LOCAL ACTION → HARD JUMP CUT → ADVANCED PHASE.**
    Repetitive physical work (clearing, framing, boarding, cladding, insulating, one opening
    after another…) is never shown as one long take on a single small patch. It is edited as
    short beats (≈3 beats of ~2 s in a 6 s clip), each one at a different place in the actual
    work area:
    - each cut implies elapsed time; the next beat shows the builder repositioned further along,
      with the surrounding area visibly further advanced;
    - within a beat: one continuous take, progress caused only by visible labor, the full work
      cycle shown (e.g. scoop → lift → carry → dump) — no debris or material vanishing, appearing
      or morphing inside a shot;
    - across a cut: tool, wheelbarrow and material positions may change (time has passed), but
      the railcar, location, light, builder and clothing never do;
    - the camera never glides, pans or zooms between work locations — hard editorial cuts only,
      same locked framing unless the storyboard changes the camera at a checkpoint;
    - the cuts skip repetition, not the mechanism: the first beat must show how the work is done;
    - the last beat converges on the approved end checkpoint.
    Established 2026-09-27 from the Seedance 2.5 Clip 03 proof (motion passed; labor too localized).

## Production lessons — Projects #1 and #2

Binding from Project #3 on. Rules 1–11 say what the viewer must see; these say how a shot is
planned and routed so a model can actually deliver it. Established 2026-09-28.

1. **One physical task per continuous shot.**
2. **Repetitive work uses hard editorial jump cuts:
   ACTION → CUT → REPOSITION → ACTION → CUT → PHASE ADVANCED.** (Rule 11 above.)
3. **Never ask a model to simulate an entire repetitive construction phase continuously.**
   Wan 3.0 morphed toward the end frame; Seedance 2.5 performed real labor but stayed on one
   patch. Neither can carry a whole phase in one take.
4. **Every visible change inside a continuous shot must be caused by visible labor.**
5. **Tools and materials have a plausible source and destination** — they come from somewhere
   visible and go somewhere visible (stack → wall, shovel → wheelbarrow → pile).
6. **No unexplained object spawning or disappearing during a continuous shot.** Positions may
   change only across a cut.
7. **Camera movement and construction complexity do not happen in the same shot** unless that
   model has already proven it can do that kind of shot.
8. **Approved checkpoint pixels are authoritative** over any prompt text.
9. **Use a phase-completion image edit when a jump in elapsed time is more believable than
   video generation.**
10. **Add checkpoints whenever they reduce the physical change one clip must produce.**
11. **Select the video model by task difficulty, never one model for the whole video:**
    - simple environmental motion / reveal → economical model;
    - broad repetitive labor → stronger motion model with internal jump cuts;
    - precision tool / material interaction → premium model;
    - static completion / time jump → image edit instead of video.
    A model is promoted to a harder class only after it passes a proof shot of that class.

## Provider policy (from Project #3)

- Checkpoint stills: made and approved manually in ChatGPT; the stills folder is the source of truth.
- Video: fal.ai, routed per shot by difficulty class (production lesson 11).
- Higgsfield: retired from the active production path. The Clip 03 Seedance 2.5 / Kling O3 work
  is kept as R&D history (Project #2 manifest `clip03__attempt3`, `provider_tests/higgsfield_clip03/`);
  no new production is built on it.

## Related standing rules (train-car storyboard deck)

- A checkpoint must exist wherever a viewer could reasonably ask "how did that get there?"
- The same railcar, location, proportions, builder, deck side, window layout and design
  language hold throughout.
- Actual previous pixels are authoritative over the text prompt.
- A later checkpoint must never visually regress to an earlier construction state.

North star: no viewer should ever ask, "Wait — how did that get built?"
