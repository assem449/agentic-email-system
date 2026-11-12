# Prompt: final fixes and page cuts

**Attach:** `paper_final.tex` (the version the other Claude produced) and
`paper/figures/fig3.pdf` from the repo.

**Before sending,** fill in the three `<<...>>` placeholders in item 7 (name,
affiliation, email).

---

## Prompt (copy everything below)

Attached is the camera-ready LaTeX of my IEEE conference paper
(`paper_final.tex`) and a redrawn Fig. 2 (`fig3.pdf`). Apply the fixes
below **exactly as written**, then make the paper fit in 6 pages using the
cuts in Part B, in the order given. All numbers below are verified against
the experiment outputs. Do not change any other number.

### Part A: corrections (apply all)

1. §V-C, replace `\textbf{[TODO]} of 28 errors` with `11 of 28 errors`.

2. §V-D, replace `rises from 45.6\% to \textbf{[TODO]}\%` with
   `rises from 45.6\% to 46.7\%`.

3. §V-E, replace the sentence starting "The decline is concentrated in
   support…" up to "…essentially unchanged." with:
   ```latex
   The decline is concentrated in support, which falls from 0.942 to 0.759 F1, well beyond any other category; ambiguous, spam, FAQ and acknowledgment show a smaller decline of 0.055--0.088 F1, while meeting and emotional are essentially unchanged.
   ```

4. §VI-B: keep "7.2\%" as it is. It is correct (7.153% from unrounded
   values).

5. Table I and §V-C wording:
   - Table I `\caption{...}` → `Routing Systems on the 363-Email, Seven-Category Corpus`
   - First sentence of §V-C ("Table~\ref{tab1} compares both classifiers
     against three baselines.") →
     `Table~\ref{tab1} compares DistilBERT against the always-LLM and random-routing baselines, the frozen rule set and the two TF-IDF classifiers.`
   - First footnote line of Table I → `Trained classifiers are scored out-of-fold per \eqref{eq2}; rules v1 is evaluated`
     (the next line, starting "frozen.", stays).

6. §VI-A, replace "Acknowledgments are the clearest case: 50 of the 52
   acknowledgments answered from a fixed template at zero token cost, both
   frequent and trivially identifiable in real inboxes." with:
   ```latex
   Acknowledgments are the clearest case: 50 of the 52 are answered from a fixed template at zero token cost, and they are both frequent and trivially identifiable in real inboxes.
   ```

7. De-anonymise (this is the camera-ready). Replace the author block with:
   ```latex
   \author{\IEEEauthorblockN{<<Full Name>>}
   \IEEEauthorblockA{<<Affiliation, City, Country>>\\
   <<email>>}
   }
   ```
   Add `\usepackage{url}` to the preamble. Add a footnote to the first
   sentence of §III-A ("The pipeline has three sequential layers"):
   `\footnote{Code and data: \url{https://github.com/assem449/agentic-email-system}}`

8. Fig. 2: change `\includegraphics[width=0.85\linewidth]{fig3.png}` to
   `\includegraphics[width=\linewidth]{fig3.pdf}` and replace its caption
   with:
   ```latex
   \caption{Measured cost reduction against the portion attributable to correctly routed email. More than half of the rule-based system's apparent savings come from misroutes; the TF-IDF SVM's measured lead over DistilBERT reverses once misroutes are excluded.}
   ```

9. In §V-D, replace "0.3~ms for the TF-IDF baselines" with
   "0.3--0.4~ms for the TF-IDF baselines". Skip this if cut B2 below
   replaces that paragraph.

### Part B: cuts to reach 6 pages

Apply these in order. After each one, compile and check the page count.
**Stop as soon as the paper is 6 pages.** Count references in the total
unless I tell you the venue excludes them.

**B1. Move Appendix A to the repository.** Delete everything from
`\appendices` up to (not including) `\section*{Acknowledgment}`. Replace the
whole `\paragraph{Generation details.}` paragraph in §V-A with:
```latex
\paragraph{Generation details.} The primary corpus was generated with Claude Sonnet~5 (Anthropic) and the held-out corpus with GPT-4o (OpenAI), both in August 2026 through the vendors' chat interfaces at default settings, so the corpora differ in model and vendor as well as in prompts. Each came from seven category-specific role-play prompts (``Imagine you are\ldots'') specifying the category and a sender persona and requesting canonical phrasings, natural paraphrases and a minority of trap cases. The verbatim prompts were not retained; approximate reconstructions, written after the fact and not the original text, are released with the corpora, labels and adjudication record. Replies on the LLM path come from Claude Sonnet~4.6, which generated neither corpus.
```
In the Acknowledgment, change "reconstructed in Appendix A" to
"reconstructed in the released repository".

**B2. Shorter latency text.** In §V-D, replace everything from "Latency in
Table~I is end-to-end within the pipeline" to the end of that paragraph
with:
```latex
Latency in Table~I is end-to-end: classifier inference plus handler time, excluding Gmail I/O. DistilBERT inference takes a median 14.1~ms per email benchmarked on a laptop CPU (2.0~s one-off model load) and averages 40.8~ms inside the pipeline, where it runs on a CPU idled by multi-second API waits; the TF-IDF and rule classifiers take under 3~ms. Under the in-pipeline figures used in Table~I, inference lowers DistilBERT's latency reduction from 38.00\% (handler only) to 36.72\%. Calendar latency is a lower bound: the handler is replaced by a fixed 0.1~ms stub during evaluation, and the live handler's date extraction is a naive fuzzy parse. Excluding the 51 calendar-routed emails, DistilBERT's end-to-end reduction is 27.49\% (SVM 32.00\%, rules 19.54\%).
```

**B3. Merge §VI-C.** Replace the whole body of "Limitations and Future
Work" with:
```latex
Both corpora are synthetic and 363 examples is small for fine-tuning. Three questions are left explicitly to future work. \emph{Response quality and review burden:} we measure whether an email reaches the intended handler, not whether its draft is acceptable; a planned user study will measure draft acceptance and editing effort per handler, supplying the human-review term missing from our cost accounting. \emph{Real email and annotation:} the held-out corpus (different model and vendor, reworded prompts, $\kappa = 0.900$) tests robustness to the generation process, not to real inbox traffic with its formatting noise and quoted threads; evaluation on consented real email, and double annotation of the single-annotated primary corpus, come next. \emph{Untuned components:} the retrieval threshold, cache design and rate limiting are fixed a priori or not yet implemented.
```

**B4. Shorter LLM-side paragraph.** In §VI-A, replace the paragraph
starting "These reductions are LLM-side compute savings only" with:
```latex
These are LLM-side savings only. Every draft is staged for human review, so an email's full cost also includes the time a person spends checking, correcting or discarding it, which we do not measure and which need not track token cost: a templated reply to a misrouted email is free to generate but may cost more to repair than an LLM draft. Cost figures also exclude the compute cost of running the classifier and retrieval embedding model locally. The planned user study (Section~VI-C) would supply the missing review-time term.
```
(If you don't apply B4, still fix the original paragraph: replace "The
figures also exclude the classifier's own compute and the embedding model
behind retrieval, both of which run locally." with "Cost figures also
exclude the compute cost of running the classifier and the retrieval
embedding model locally.")

**B5. Shorter TF-IDF paragraphs.**

§V-C, replace the paragraph starting "The linear baselines close most of
the gap" with:
```latex
The linear baselines close most of the gap: TF-IDF with a linear SVM attains 84.57\% (95\% CI 80.5--87.9) and macro-F1 0.842 (0.802--0.878), logistic regression 79.06\% and 0.792. DistilBERT's 7.72-point lead over the SVM lies outside both intervals, but 44.9 of the 52.6 points separating DistilBERT from the rules are recovered by a bag-of-words model that classifies an email in under a millisecond.
```
§V-E, replace the paragraph starting "The linear baselines generalise
differently" with:
```latex
The linear baselines generalise differently. Refitted on all 363 primary emails, the SVM attains 85.71\% (90/105, 95\% CI 77.8--91.2) and macro-F1 0.860 (0.784--0.919) on the held-out corpus, and logistic regression 80.95\% and 0.814, neither declining from cross-validation. On the held-out corpus the SVM and DistilBERT are indistinguishable (exact McNemar test on paired predictions: 7 emails only DistilBERT gets right, 8 only the SVM; $p=1.00$), so DistilBERT's in-corpus lead does not survive a change of generator: part of what fine-tuning learned is the primary generator's style.
```

**B6. Only if still over:** in §III-B Calendar, delete ", the confirmation
token is held by the operator and never appears in the draft" and the
words "to the sender" before it, so the sentence ends "…returns a draft
stating the extracted time for confirmation."

If all of B1–B6 still leave the paper over 6 pages, stop and tell me by
how much. Do not cut anything else on your own; suggest options instead.

### Return

1. The complete updated `.tex`, ready to compile, and the compiled PDF.
2. The final page count, and which B-cuts you applied.
3. A short list of every edit made.
4. A consistency check: every number appearing in more than one place
   (abstract, tables, body, conclusion, figure caption) agrees. List any
   mismatch rather than fixing it silently.
