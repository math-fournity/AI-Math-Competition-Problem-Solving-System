# Formal verification report — clean Lean fixture

<!-- FORMAL_STATEMENT -->
## 1. Formal statement
For every `n : Nat`, prove `n + 0 = n`.

<!-- CLAIM_COVERAGE -->
## 2. Claim coverage
The sole proof claim maps to `nat_add_zero_checked` in `formal/Main.lean`.

<!-- TOOLCHAIN -->
## 3. Toolchain
Lean 4 trusted kernel; exact installed version is captured by the run record.

<!-- REPRODUCE -->
## 4. Reproduce
`lean formal/Main.lean`

<!-- RESULTS_AND_LOGS -->
## 5. Results and logs
The runner writes `formal_logs/lean_clean.run.json` and its stdout/stderr logs.

<!-- ESCAPE_HATCHES -->
## 6. Escape hatches
No sorry, admit, or added axiom is intended; the deterministic scanner records direct findings.

<!-- FINITE_SEARCH_BOUNDARY -->
## 7. Finite-search boundary
No finite search is used.

<!-- UNCOVERED -->
## 8. Uncovered
No uncovered claim in this deliberately small fixture.

<!-- SUFFICIENCY_ARGUMENT -->
## 9. Sufficiency argument
There is one claim and it maps to one kernel-checked theorem. Independent audit is still required.
