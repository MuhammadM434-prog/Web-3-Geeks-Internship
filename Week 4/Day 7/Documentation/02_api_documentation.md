# Week 4 --- Day 7: API Documentation

## 1. Purpose

The FastAPI service is the HTTP entry point for the real-estate
voice-agent application.

The exact route names and request models are defined by the deployed
`app.main` module. This document describes the contract at the system
level and should be kept synchronized with the route definitions
whenever the API changes.

## 2. Application

The application is imported from:

``` python
from app.main import app
```

The LangGraph workflow is imported from:

``` python
from app.graph import COMPILED_GRAPH
```

The operational database/tool layer is imported from:

``` python
from app.tools import DB
```

## 3. Request lifecycle

``` text
HTTP request
  -> validation
  -> conversation state
  -> LangGraph orchestration
  -> retrieval / database / calendar / email tools
  -> state update
  -> response
```

## 4. Expected API capabilities

The deployed API must support the application capabilities demonstrated
by the Day 7 validation flow:

-   Customer conversation / voice-agent interaction
-   Property inquiry
-   Property recommendation
-   Grounded RAG answers
-   Appointment availability checking
-   Appointment creation
-   Appointment rescheduling
-   Appointment cancellation
-   Calendar event creation
-   Employee notification
-   Safe refusal / abstention
-   Prompt-injection resistance
-   Operational metrics / health monitoring

## 5. Error behavior

Public errors should be actionable but must not expose:

-   stack traces
-   database credentials
-   provider credentials
-   hidden prompts
-   internal file paths
-   raw exception objects
-   private customer records

Typical public outcomes are:

  -----------------------------------------------------------------------
  Situation                           Expected behavior
  ----------------------------------- -----------------------------------
  Missing required input              Validation response

  Property not found                  Explain that no matching grounded
                                      record was found

  Insufficient RAG evidence           Abstain rather than invent

  Sold property                       Exclude from active recommendations

  Appointment conflict                Do not create the conflicting
                                      booking; offer another slot

  Calendar provider failure           Return a safe retry/escalation
                                      message

  Email failure                       Preserve appointment state and
                                      record notification failure

  Prompt injection                    Refuse the instruction and continue
                                      protecting system behavior
  -----------------------------------------------------------------------

## 6. Testing

The Day 7 notebook should be executed with the project dependencies
installed and the application importable. The important integration
assertions include:

-   application imports successfully;
-   compiled LangGraph workflow is available as `COMPILED_GRAPH`;
-   appointment creation creates the expected database row;
-   email notification creates the expected `emails_sent` record;
-   a seeded 3 PM conflict is detected;
-   retry at 4 PM succeeds;
-   sold properties are excluded;
-   unsupported RAG questions produce abstention;
-   prompt injection does not override the agent's rules;
-   metrics are produced.

## 7. Deployment check

A deployment should not be called production-ready until the real
service, real database, retrieval layer, calendar integration, and email
integration have all been exercised in the target environment.

A notebook that merely imports the modules is an integration smoke test,
not proof of production uptime.
