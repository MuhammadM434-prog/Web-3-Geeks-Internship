# Week 4 --- Day 7: Troubleshooting Guide

## Application will not start

Check:

1.  Python environment.
2.  Installed dependencies.
3.  Environment variables.
4.  Import errors in `app.main`.
5.  LangGraph import/compilation.
6.  Database path and permissions.

The deployment notebook should be able to import the application and the
compiled graph.

## `cannot import name 'graph' from app.graph`

Use the compiled module-level object exposed by the project:

``` python
from app.graph import COMPILED_GRAPH
```

Do not confuse the local `graph` builder inside `build_graph()` with the
compiled application graph.

## Property answer is unsupported

If RAG cannot provide enough evidence, abstention is expected behavior.

Check:

-   source document exists;
-   document is current;
-   document was indexed;
-   retrieval query is appropriate;
-   chunking/embedding process completed;
-   vector index is available.

Do not solve an abstention failure by instructing the model to guess.

## Sold property is recommended

This is a data/eligibility incident.

Check:

1.  property status in the structured database;
2.  recommendation filtering;
3.  stale vector documents;
4.  cache/state;
5.  test fixture data.

The sold property must be removed from the eligible recommendation set.

## Appointment conflicts

If a requested slot is occupied:

1.  verify the existing appointment;
2.  verify calendar availability;
3.  return the conflict to the workflow;
4.  offer another available slot;
5.  create the appointment only after the new slot is confirmed.

Do not overwrite an existing appointment to force the requested time.

## Appointment exists but employee email is missing

Check:

-   email provider credentials;
-   notification tool execution;
-   `emails_sent` database record;
-   provider response;
-   retry/error logs.

The appointment record should remain auditable even if notification
delivery fails.

## Calendar event missing

Check:

-   calendar credentials;
-   calendar identifier;
-   provider response;
-   appointment-to-event mapping;
-   duplicate/idempotency handling.

Never create duplicate events simply because the first provider response
was slow.

## Prompt injection succeeds

Treat this as a security incident.

Immediately:

1.  capture the test case;
2.  confirm which tool/action was reached;
3.  block the pattern or strengthen the boundary;
4.  add the case to regression tests;
5.  retest all consequential actions.

## High latency

Break latency into:

-   request parsing;
-   LangGraph execution;
-   retrieval;
-   database;
-   calendar provider;
-   email provider;
-   voice/STT/TTS.

Do not optimize blindly. Identify the slow component first.

## Database inconsistency

Compare:

-   appointment state;
-   calendar event state;
-   email notification state;
-   conversation/audit state.

Use the operational record as the source for application state and
reconcile external-provider state through an explicit recovery process.

## Escalation

Escalate when:

-   customer data may be exposed;
-   appointment state is corrupted;
-   calendar events are duplicated or lost;
-   sold inventory is recommended;
-   grounded factual responses are repeatedly wrong;
-   security controls are bypassed;
-   backup restoration fails.
