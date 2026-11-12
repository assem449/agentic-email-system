# Prompt for updating the paper with Claude

**Attach these files:**
1. The paper's LaTeX source (`main.tex`, or whatever it's called, plus any
   `.tex` files it `\input`s). Attach the source, not the PDF; Claude needs
   the source to make edits.
2. `paper/camera_ready_edit_list.md`: every number change, by section.
3. `paper/camera_ready_revisions.md`: the LaTeX for the new paragraphs.
4. `data/DATASET.md`: the prompt reconstructions for Appendix A.
5. Optional: `paper_v15.pdf`, so Claude can see the current layout.

**Before sending,** replace the two `[[...]]` in the prompt with the outputs
of the two commands at the top of the edit list.

---

## Prompt (copy everything below)

I'm preparing the camera-ready version of my accepted paper. Attached are
the LaTeX source, an edit list (`camera_ready_edit_list.md`), a file of
LaTeX paragraphs to insert (`camera_ready_revisions.md`), and a dataset card
(`DATASET.md`).

Update the LaTeX source so that it reflects the edit list exactly:

1. Apply every "v15 → Final" replacement in the edit list. Change only the
   numbers and phrases listed, and keep the surrounding wording.
2. Insert each new paragraph the edit list asks for, using the LaTeX from
   `camera_ready_revisions.md`. Fill in any remaining placeholders from the
   edit list.
3. Replace Table I and the DistilBERT primary-corpus columns of Table II
   with the values in the edit list. Keep the existing table style.
4. Add Appendix A from `DATASET.md`: the two prompt frames and the two
   category tables, headed by the note that these are approximate
   reconstructions, not the original prompts.
5. Two values I computed:
   - DistilBERT now makes 28 errors, and [[N]] of them involve the
     ambiguous category (replaces "12 of 27").
   - The routed output-token share under DistilBERT is [[X]]% (baseline
     45.6%) (replaces "45.5% to 46.6%").
6. Update the data in the Fig. 2 source: rules 28.98 measured / 13.57
   attributable, DistilBERT 38.53 / 35.78. Add TF-IDF + SVM 40.71 / 34.11 as
   a third pair. If the figure is an image rather than LaTeX, tell me and
   give me the values to redraw it.

Rules:
- Do not change any number that is not in the edit list.
- Do not invent numbers. If something needs a value the edit list doesn't
  give, leave `\textbf{[TODO]}` and tell me.
- Keep the paper within the conference page limit. If the additions make
  it too long, suggest what to shorten instead of cutting content yourself.

Return:
(a) the complete updated `.tex` file(s), ready to compile;
(b) a changelog listing every edit by section, so I can check each one;
(c) any TODOs left, and anything in the edit list you couldn't place.

After that, check consistency: every number that appears in more than one
place (abstract, tables, body, conclusion) must agree. List any mismatch.
