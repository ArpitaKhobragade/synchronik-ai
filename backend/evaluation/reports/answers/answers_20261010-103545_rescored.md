# Answer-quality evaluation — 2026-10-10 05:05 UTC

Model: `gemini-3.5-flash-lite` · reranker: `none` · general answers: True · items: 23 · references drafted from quoted sources, **pending human review** · judge: on (supplementary, not ground truth)

## Status of every item

| Status | Count |
|---|---:|
| llm_fallback | 1 |
| scored | 22 |

## Metrics

| Metric | Value |
|---|---:|
| answerable_evaluated | 18 |
| unanswerable_evaluated | 4 |
| answered_from_documentation | 1.0 |
| key_fact_coverage | 0.924 |
| fully_correct_by_key_facts | 0.833 |
| evidence_retrieved | 0.944 |
| citations_valid | 1.0 |
| citation_support | 0.979 |
| faithfulness_lexical | 0.957 |
| unanswerable_handled_correctly | 1.0 |
| general_answers | 3 |
| general_labelled | 1.0 |
| general_with_fake_citations | 0 |
| leaks | 0 |

## LLM judge (supplementary)

| Measure | Count |
|---|---:|
| documentation_answers_judged | 18 |
| correct | 18 |
| partial | 0 |
| incorrect | 0 |
| invents_functionality | 0 |
| general_answers_judged | 3 |
| general_states_synchronik_specifics | 0 |
| general_helpful | 2 |
| unparseable_or_failed | 0 |

## Per item

| id | answerable | outcome | correct | key facts | evidence | cite support | judge |
|---|---|---|---|---:|---|---:|---|
| a-attendance-mark | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-freeze-marks | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-freeze-greyed | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-marksheets | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-revaluation | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-tc | True | document_question | True | 1.0 | True | 0.875 | correct |
| a-bonafide | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-late-fine | True | document_question | True | 0.8 | True | 1.0 | correct |
| a-refund | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-2fa | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-report | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-library-reports | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-postexam-module | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-which-module-schedule | True | document_question | True | 1.0 | True | 0.75 | correct |
| a-biometric-faq | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-company-faq | True | document_question | True | 0.333 | True | 1.0 | correct |
| a-products-faq | True | document_question | True | 1.0 | True | 1.0 | correct |
| a-tenancy | True | document_question | True | 0.5 | False | 1.0 | correct |
| u-salary | False | document_question | – | – | – | – | – |
| u-hostel | False | general | True | – | – | – | ok |
| u-moodle | False | general | True | – | – | – | ok |
| u-general | False | general | True | – | – | – | ok |
| u-injection | False | document_question | True | None | None | 0.833 | – |
