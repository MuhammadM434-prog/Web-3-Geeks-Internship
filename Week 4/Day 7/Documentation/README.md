# Week 4 --- Day 7 Capstone Handover Package

## Contents

1.  `01_system_architecture.md` --- system architecture and component
    responsibilities.
2.  `02_api_documentation.md` --- API/application contract and
    integration behavior.
3.  `03_user_guide.md` --- customer/user operating guide.
4.  `04_admin_guide.md` --- administrator operations and security guide.
5.  `05_maintenance_plan.md` --- monitoring, maintenance, backup,
    retraining, vector refresh, prompt updates, and security cadence.
6.  `06_troubleshooting_guide.md` --- operational failure diagnosis and
    recovery.
7.  `07_stakeholder_demo.md` --- scripted 10-minute live demonstration.
8.  `08_future_enhancements.md` --- requested future-enhancement
    roadmap.

## Day 7 acceptance flow

## Day 7 acceptance flow
The handover is based on the current service integration sequence and its
focused regression tests:

-   property inquiry;
-   budget/area capture;
-   grounded recommendation;
-   real appointment conflict at 3 PM;
-   retry at 4 PM;
-   appointment database verification;
-   employee email notification verification;
-   sold-property exclusion;
-   RAG abstention;
-   prompt-injection resistance;
-   monitoring/metrics.
-   non-Roman STT transcript normalization with provider fallback;
-   durable session recovery after process-local state reset;
-   safe provider failure handling without secret/transcript logging;
-   authenticated and rate-limited API boundary checks.

## Important deployment note

The documentation describes the implemented architecture and the
validated capstone workflow. Production deployment still requires the
Production deployment still requires the target environment's real
credentials, provider/model access, provider configuration, dependency
installation, and live integration checks. The local test suite and notebook
prove the application behavior and adapter contracts; they do not prove
third-party delivery, latency, pronunciation quality, or telephony readiness.

The earlier notebook import issue is resolved by importing
`COMPILED_GRAPH` from `app.graph`, not the local `graph` builder
variable.
