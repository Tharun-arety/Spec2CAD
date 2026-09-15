# Public guardrail evaluation

Result: **10/10 passed**

| Category | Assertion | Result |
|---|---|---|
| rate_limit | burst is capped | PASS |
| rate_limit | window resets | PASS |
| ai_budget | per-client daily cap | PASS |
| ai_budget | global daily cap | PASS |
| access | run id has 128 bits | PASS |
| resource_caps | B-Rep cache is bounded | PASS |
| resource_caps | nonfinite CAD value refused | PASS |
| resource_caps | operation flood refused | PASS |
| model_controls | output tokens capped | PASS |
| model_controls | provider timeout capped | PASS |
