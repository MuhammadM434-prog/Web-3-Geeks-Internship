# Week 4 --- Day 7: Monitoring & Maintenance Plan

## 1. Operational targets

These are proposed operating thresholds for the production service and
should be calibrated against measured baseline traffic.

  ----------------------------------------------------------------------------------------
  Signal                   Target / warning   Critical condition Action
  -------------------- -------------------- -------------------- -------------------------
  API availability          ≥ 99.5% monthly               \< 99% Incident response

  Normal response      p95 \< 2 s excluding           p95 \> 4 s Investigate
  latency                 external provider                      dependency/tool latency
                                       wait                      

  Tool error rate                     \< 2%    \> 5% over 15 min Page/on-call
                                                                 investigation

  Calendar failures                   \< 1%                \> 3% Check
                                                                 provider/authentication

  Email failures                      \< 2%                \> 5% Check
                                                                 provider/authentication

  RAG abstention             Track baseline   Sudden unexplained Check ingestion/index
                                                        increase 

  RAG                           0 confirmed        Any confirmed Immediate investigation
  unsupported-answer              incidents hallucinated factual 
  leakage                                                 answer 

  Sold-property                           0    Any sold property Immediate inventory/data
  leakage                                            recommended investigation
  ----------------------------------------------------------------------------------------

## 2. Daily monitoring

Review:

-   uptime;
-   request volume;
-   p50/p95 latency;
-   tool failures;
-   appointment failures;
-   email failures;
-   calendar synchronization failures;
-   RAG abstentions;
-   prompt-injection blocks.

## 3. Weekly maintenance

### Knowledge base

Refresh the vector index when approved property descriptions, brochures,
FAQs, or other source material changes.

Validate:

-   document count;
-   embedding/index health;
-   duplicate documents;
-   stale documents;
-   representative retrieval queries;
-   abstention cases.

### Model/prompt review

Review sampled conversations and identify:

-   repeated misunderstandings;
-   unsupported factual answers;
-   poor objection handling;
-   unnecessary verbosity;
-   unsafe tool behavior.

Prompt changes must go through regression tests before deployment.

## 4. Retraining

If recommendation or ranking models are introduced, retraining should be
performed on a controlled schedule rather than automatically replacing
the production artifact.

Every candidate model should record:

-   dataset version;
-   feature version;
-   training cutoff;
-   evaluation metrics;
-   test results;
-   approval;
-   deployment version.

Keep the previous approved artifact available for rollback.

## 5. Backup strategy

Back up:

-   operational database;
-   configuration metadata;
-   knowledge-base source documents;
-   vector-index metadata;
-   appointment/audit records;
-   deployment configuration.

Recommended policy:

-   daily database backup;
-   weekly retained snapshot;
-   monthly restore test;
-   encrypted backup storage;
-   documented recovery procedure.

## 6. Security review cadence

-   Continuous: credential and access monitoring.
-   Monthly: dependency/security review.
-   Quarterly: access-control and secret-rotation review.
-   After any security incident: immediate review and regression
    testing.

## 7. Prompt-update policy

Every prompt update should be accompanied by:

1.  regression suite;
2.  RAG grounding tests;
3.  prompt-injection tests;
4.  appointment conflict tests;
5.  recommendation eligibility tests;
6.  human review of representative conversations.

## 8. Rollback

Rollback immediately when a release causes:

-   factual grounding failures;
-   sold-property leakage;
-   calendar corruption;
-   repeated booking failures;
-   prompt-injection bypass;
-   material latency degradation.

Rollback means restoring the last known-good
application/prompt/index/model version and then investigating the failed
release.
