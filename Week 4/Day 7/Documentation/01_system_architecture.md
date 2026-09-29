# Week 4 --- Day 7: System Architecture

## 1. Product

The Real Estate Voice Agent is a production-oriented conversational
system for handling property inquiries, retrieving grounded property
information, recommending eligible properties, handling objections, and
managing appointments.

The capstone deployment is organized around:

-   FastAPI backend
-   Voice-service layer
-   LangGraph orchestration
-   Retrieval / vector database layer
-   SQLite local/test database or pooled PostgreSQL production database
-   Calendar integration
-   Employee email notification
-   Monitoring and metrics

The system is designed so that factual property claims come from
grounded data rather than being invented by the conversational model.

## 2. High-level flow

``` text
Customer
   |
   v
Voice / Speech Layer
   |
   v
FastAPI
   |
   v
LangGraph conversation workflow
   |
   +--> Intent / conversation state
   |
   +--> Property retrieval / RAG
   |
   +--> Recommendation logic
   |
   +--> Appointment availability
   |
   +--> Calendar action
   |
   +--> Email notification
   |
   v
Response to customer

Operational data <----> SQLite/PostgreSQL / DB tools
Property knowledge <----> Vector retrieval layer
Observability <----> Metrics / logs
```

## 3. Application boundaries

### FastAPI

The FastAPI application is the HTTP boundary for the service. It
receives requests, invokes the application workflow, and exposes
operational endpoints used by deployment and testing.

### LangGraph

LangGraph owns the stateful conversation workflow. It is the
orchestration layer rather than an unrestricted autonomous agent.

The compiled graph is exposed by the application as `COMPILED_GRAPH` in
`app.graph`.

### Tools / database layer

The operational tool layer is exposed through `app.tools.DB`. It is
responsible for durable operational state such as appointments and
notification records.

The deployment tests explicitly inspect database state after appointment
and email actions.

### Retrieval

Property descriptions, brochures, FAQs, and other unstructured property
knowledge are retrieved through the RAG/vector layer. Structured facts
such as price, availability, area, and appointment state belong in
structured data sources.

## 4. Data responsibility

  Information                    Primary source
  ------------------------------ ------------------------------
  Price                          Structured property database
  Availability                   Structured property database
  Area / size                    Structured property database
  Agent / employee information   Structured database
  Property descriptions          Retrieval/vector layer
  Brochure / FAQ content         Retrieval/vector layer
  Appointment state              Operational database
  Email notification state       Operational database
  Calendar event                 Calendar provider
  Conversation state             LangGraph/application state

This separation reduces hallucination risk and makes updates auditable.

## 5. Core conversation behavior

The demonstrated workflow covers:

1.  Opening customer interaction.
2.  Capturing budget and area requirements.
3.  Recommending eligible properties.
4.  Detecting a real appointment conflict.
5.  Offering a new time after the conflict.
6.  Creating the appointment.
7.  Recording the appointment in the database.
8.  Sending and recording the employee notification.
9.  Excluding sold properties from recommendations.
10. Abstaining when the RAG layer does not contain sufficient factual
    evidence.
11. Blocking prompt-injection attempts.
12. Reporting operational metrics.

## 6. Production principles

-   Never invent property facts when grounded evidence is unavailable.
-   Do not recommend sold/ineligible inventory.
-   Treat calendar state as authoritative for appointment conflicts.
-   Persist consequential actions.
-   Keep customer-facing errors safe and non-technical.
-   Keep internal implementation details out of public responses.
-   Log enough metadata to diagnose failures without unnecessarily
    logging sensitive content.
-   Keep orchestration explicit and testable.
