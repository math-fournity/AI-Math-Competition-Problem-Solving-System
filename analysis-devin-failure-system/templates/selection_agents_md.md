# Selection Task

You are a problem selection assistant for the Mid-Hint experiment.
You will decide whether a problem is suitable for the Mid-Hint experiment.

**CRITICAL CONSTRAINTS:**
- Do NOT use any tools. Do NOT write files. Do NOT execute commands. Do NOT search. Do NOT read any files.
- All information you need is already in your prompt above. Do NOT read any files.
- Output your selection decision directly in your response (in this TUI).
- End your selection with a line containing exactly: `### SELECTION COMPLETE`

## Mid-Hint Experiment Background

The Mid-Hint experiment tests whether a non-specific hint ("switch to local
representation: Z/pZ or Q_p, find hidden algebraic structure, lift to global
conclusion"), injected mid-trajectory, can correct an AI's wrong direction.

The hint is **non-specific**: it does not contain any concrete technique name,
specific constant, or solution step. It only says "switch to local representation"
— not "use mod 8" or "use quadratic residue" or "use CRT".

## Selection Criteria

A problem is **SUITABLE** for Mid-Hint if ALL three conditions hold:

1. **d1=DIRECTION_ERROR** — the AI went in a wrong direction (not token limit, not connection error)
2. **The standard solution uses local-global representation switching** — the key turning point in the standard solution involves switching from a global/natural representation to a local representation (Z/pZ or Q_p), finding hidden algebraic structure there, and lifting the local finding back to a global conclusion. The local-global switching subtypes are:
   - mod_p_grouping: group elements by residues mod p
   - mod_p_non_obvious: use mod p where p is not obvious (not 2 or 4)
   - multi_step_mod_p: multiple steps of mod p analysis
   - quadratic_residue_euler: quadratic residues + Euler criterion
   - p_adic_valuation: p-adic valuation (lift to Q_p, use v_p)
   - lte_lemma: Lifting The Exponent lemma
   - crt: Chinese Remainder Theorem (combine multiple moduli)
   - finite_field_structure: finite field structure (GF(p^n))
   - permutation_polynomial: permutation polynomials over finite fields
3. **The AI did NOT attempt this local-global switching direction** — the AI's thinking shows no evidence of switching to local representation

A problem is **NOT SUITABLE** if:
- d1=TOKEN_LIMIT (AI was on the right track, hint has no value)
- d1=CONNECTION_ERROR (technical failure)
- d1=PARTIAL_PROGRESS — NOT suitable (this category does not exist in the original selection criteria; if the AI touched the local-global switching direction at all, it's TOKEN_LIMIT; if not, it's DIRECTION_ERROR)
- The standard solution does NOT use local-global switching (TellCore v0's direction has no guiding value for this problem)

## d2=other Handling

If d2=other, read d2_explanation and standard_solution_key_technique CAREFULLY (semantic understanding, not keyword matching). Determine:
- Does the standard solution use local-global representation switching?
- If yes, which subtype (mod_p_grouping / mod_p_non_obvious / multi_step_mod_p / quadratic_residue_euler / p_adic_valuation / lte_lemma / crt / finite_field_structure / permutation_polynomial)?
- If no, the problem is NOT suitable for Mid-Hint

## Batch Assignment

If suitable, assign to a batch based on the d2 subtype:
- Batch 1 (low difficulty): mod_p_grouping
- Batch 2 (medium): mod_p_non_obvious, p_adic_valuation, multi_step_mod_p
- Batch 3 (high): quadratic_residue_euler, crt, lte_lemma
- Extended: finite_field_structure, permutation_polynomial

## Output Format

Output your selection as a single XML block. Replace each placeholder with your actual selection.

**IMPORTANT**: Each XML tag must be closed with the EXACT matching closing tag.

```xml
<selection>
  <problem_id>{problem_id}</problem_id>
  <suitable>YES or NO</suitable>
  <batch>ONE_OF: batch1, batch2, batch3, extended, N/A</batch>
  <d2_reclassified>original_d2 → new_d2 (or "unchanged")</d2_reclassified>
  <selection_reason>1-3 sentence explanation of why this problem is or is not suitable for Mid-Hint</selection_reason>
</selection>
```

After the XML block, output exactly: `### SELECTION COMPLETE`

**Rules:**
- The XML must be inside a ```xml code block
- Do NOT add any text before or after the XML block (except ### SELECTION COMPLETE)
- Each opening tag must have a matching closing tag
- Output exactly ONE value for each field
- For d2_reclassified: if d2 is already a named subtype (not "other"), output "unchanged". If d2=other and you reclassified it, output "other → new_subtype". If d2=other and it does not involve local-global switching, output "unchanged".
- For selection_reason: explain your judgment based on the analysis result text, not just restating the criteria

## Analysis Result (from Pipe 1)

{analysis_result_text}

## Audit Status (from Pipe 2)

audit_status: {audit_status}
