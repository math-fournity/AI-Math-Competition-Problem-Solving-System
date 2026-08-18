# Selection Task

You are a problem selection assistant for the Mid-Hint experiment.
You will decide whether a problem is suitable for the Mid-Hint experiment,
AND provide additional metadata for downstream POC experiments.

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

## POC Preparation Metadata

In addition to the selection decision, provide the following metadata
for downstream POC experiments. These are **SECONDARY tasks** — your primary
task is still the selection decision. Provide your best judgment based on
the analysis result text (d1_explanation, d2_explanation, etc.) — you do NOT
need to read the original problem or thinking.

**1. false_friend_candidate (yes/no/unclear):**
   For suitable=NO problems: Could this problem be a "false friend" —
   i.e., it LOOKS like it needs local-global switching (surface features
   similar) but the key structure is MISSING (mechanism different)?
   Answer "yes" if d1_explanation suggests the AI tried something that resembles
   local-global switching but the problem's core is actually different.

**2. boundary_case_candidate (yes/no/unclear):**
   Is this problem a "boundary case" — i.e., it is CLOSE to the trigger
   boundary of local-global switching, where only one key condition is
   different from a clear positive or clear negative?
   Answer "yes" if the problem partially matches the trigger but has
   a complicating factor that makes it uncertain.

**3. process_signal_observability (high/medium/low/unclear):**
   Based on d2_explanation and standard_solution_key_technique: If the AI were
   to use local-global switching on this problem, would the process
   signals (introducing new representation, finding hidden structure,
   lifting back to global) be OBSERVABLE in thinking?
   - "high" if d2_explanation describes a clear, distinct technique (e.g., "mod 4 grouping")
   - "medium" if d2_explanation describes a technique that might blend with other steps
   - "low" if d2_explanation is vague or the technique is hard to distinguish
   - "unclear" if insufficient information

**4. leakage_risk (low/medium/high):**
   If we give a hint about local-global switching for this problem,
   how likely is it that the hint would LEAK the answer?
   - "low" if the hint can only give strategy ("switch to local representation")
     without revealing the specific technique or answer
   - "medium" if the hint might partially reveal the technique
     (e.g., "use mod p" when p is obvious from the problem)
   - "high" if the hint would almost give away the key step
     (e.g., "use mod 4 grouping" when mod 4 grouping IS the answer)

**5. difficulty_estimate (easy/medium/hard):**
   Based on d2 subtype and d1_explanation: How difficult is this problem for
   GLM-5.2 High?
   - "easy" if d2 is mod_p_grouping (Batch 1) and d1_explanation suggests
     a straightforward wrong direction
   - "medium" if d2 is multi_step_mod_p or mod_p_non_obvious (Batch 2)
   - "hard" if d2 is quadratic_residue_euler or crt (Batch 3)
   - Use d1_explanation to adjust: if AI's wrong direction was very naive,
     the problem might be easier than its batch suggests

**6. branch_position_hint (root/line/unclear):**
   Based on d1_explanation: Did the AI go wrong from the ROOT (first step)
   or from a POINT ALONG THE LINE (mid-reasoning)?
   - "root" if d1_explanation suggests AI chose a wrong approach from the start
     (e.g., "AI tried polynomial analysis" when mod p was needed)
   - "line" if d1_explanation suggests AI's initial direction was reasonable
     but went wrong mid-way (e.g., "AI used p-adic but expansion was wrong")
   - "unclear" if d1_explanation doesn't clearly indicate the position

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
  <false_friend_candidate>yes/no/unclear</false_friend_candidate>
  <boundary_case_candidate>yes/no/unclear</boundary_case_candidate>
  <process_signal_observability>high/medium/low/unclear</process_signal_observability>
  <leakage_risk>low/medium/high</leakage_risk>
  <difficulty_estimate>easy/medium/hard</difficulty_estimate>
  <branch_position_hint>root/line/unclear</branch_position_hint>
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
- For the 6 POC metadata fields: provide your best judgment based on the analysis result text. "unclear" is an acceptable answer when information is insufficient.

## Analysis Result (from Pipe 1)

{analysis_result_text}

## Audit Status (from Pipe 2)

audit_status: {audit_status}
