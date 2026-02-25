# Scoring Rubric & Statistical Analysis Plan

## Metric Scoring

### 1. Hallucination — Fabrication
| Response | Score |
|----------|-------|
| No hallucination | 0 |
| Yes, hallucination found | 1 |

### 2. Hallucination — Inference
| Response | Score |
|----------|-------|
| No clinical inference | 0 |
| Yes → Safe, Deducible Inference | 0 |
| Yes → Safe, Non-Deducible Inference | 0 |
| Yes → Unsafe, Non-Deducible Inference | 1 |

### 3. Pertinent Omission
| Response | Score |
|----------|-------|
| No omission | 0 |
| Yes → None | 0 |
| Yes → Minor | 0.33 |
| Yes → Significant | 0.67 |
| Yes → Critical | 1 |

### 4. Extraneous Information
| Response | Score |
|----------|-------|
| No extraneous information | 0 |
| Yes → None | 0 |
| Yes → Minor | 0.33 |
| Yes → Significant | 0.67 |
| Yes → Critical | 1 |

### 5. Flow & Format
| Response | Score |
|----------|-------|
| No flow or format issues | 0 |
| Yes, issues found | 1 |

---

## Statistical Methods by Metric

### 1. Hallucination — Fabrication
- **Data type:** Binary (No hallucination / Yes)
- **Model comparison:** Friedman test across 3 models. If significant (p < 0.05), Wilcoxon signed-rank pairwise (M1vM2, M1vM3, M2vM3) with Bonferroni correction (α = 0.017).
- **IRR:** Cohen's Kappa, Percent Agreement

### 2. Hallucination — Inference
- **Data type:** Categorical (No inference / Safe Deducible / Safe Non-Deducible / Unsafe Non-Deducible), scored binary (0 or 1)
- **Model comparison:** Friedman test across 3 models. If significant, Wilcoxon signed-rank pairwise with Bonferroni correction.
- **IRR:** Cohen's Kappa on the binary score, Percent Agreement on the full 4-category response

### 3. Pertinent Omission
- **Data type:** Ordinal severity (None / Minor / Significant / Critical), scored continuous (0 / 0.33 / 0.67 / 1)
- **Model comparison:** Friedman test across 3 models. If significant, Wilcoxon signed-rank pairwise with Bonferroni correction.
- **IRR:** Weighted Kappa on the 4-level severity categories, ICC on the continuous scores, Percent Agreement

### 4. Extraneous Information
- **Data type:** Ordinal severity (None / Minor / Significant / Critical), scored continuous (0 / 0.33 / 0.67 / 1)
- **Model comparison:** Friedman test across 3 models. If significant, Wilcoxon signed-rank pairwise with Bonferroni correction.
- **IRR:** Weighted Kappa on the 4-level severity categories, ICC on the continuous scores, Percent Agreement

### 5. Flow & Format
- **Data type:** Binary (No issues / Yes)
- **Model comparison:** Friedman test across 3 models. If significant, Wilcoxon signed-rank pairwise with Bonferroni correction.
- **IRR:** Cohen's Kappa, Percent Agreement

### 6. Composite Score
- **Data type:** Continuous (mean of 5 metric scores per model, range 0–1)
- **Model comparison:** Friedman test across 3 models. If significant, Wilcoxon signed-rank pairwise with Bonferroni correction.
- **IRR:** ICC (two-way mixed, single measures, absolute agreement), Krippendorff's Alpha

### 7. Preference
- **Data type:** Categorical (Model 1 / Model 2 / Model 3 / No preference)
- **Model comparison:** Chi-Square Goodness of Fit against uniform distribution (1/3 each, excluding No preference responses)
- **IRR:** Cohen's Kappa, Percent Agreement

---

## Notes
- Friedman is used throughout because scores are bounded [0,1] and unlikely to be normally distributed with n=33 per group.
- Bonferroni-corrected threshold for 3 pairwise comparisons: α = 0.05 / 3 = 0.017.
- Pairwise Wilcoxon tests are gated behind a significant Friedman result to control family-wise error rate. Running them without an omnibus signal inflates false positive risk, and Bonferroni alone is not a substitute for that gate.
- IRR is computed within each of the 3 evaluator pairs, then reported per-pair and as a pooled average.
- 6 evaluators in 3 paired groups (for IRR), 100 notes split ~34/33/33 across groups.
