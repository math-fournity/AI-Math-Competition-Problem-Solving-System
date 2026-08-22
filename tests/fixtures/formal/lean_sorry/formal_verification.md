# Formal verification report — intentional escape-hatch fixture

<!-- FORMAL_STATEMENT -->
## 1. Formal statement
For every `n : Nat`, prove `n = n`.

<!-- CLAIM_COVERAGE -->
## 2. Claim coverage
The claim points to `intentionally_unfinished`.

<!-- TOOLCHAIN -->
## 3. Toolchain
Lean 4; this fixture intentionally tests that kernel invocation alone is not sufficient evidence.

<!-- REPRODUCE -->
## 4. Reproduce
`lean formal/Main.lean`

<!-- RESULTS_AND_LOGS -->
## 5. Results and logs
The runner archives exit code and warning output.

<!-- ESCAPE_HATCHES -->
## 6. Escape hatches
The source intentionally contains an admitted proof gap and must never be treated as sufficient.

<!-- FINITE_SEARCH_BOUNDARY -->
## 7. Finite-search boundary
No finite search is used.

<!-- UNCOVERED -->
## 8. Uncovered
The theorem body is not proved.

<!-- SUFFICIENCY_ARGUMENT -->
## 9. Sufficiency argument
No sufficiency claim is made; independent audit must reject the escape hatch.
