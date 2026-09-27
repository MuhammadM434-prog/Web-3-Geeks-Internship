# Week 4 --- Day 7: User Guide

## 1. What the agent does

The agent acts as a real-estate conversational assistant. A customer can
speak naturally about what they are looking for and the agent can:

-   understand budget and preferred area;
-   answer grounded property questions;
-   recommend eligible properties;
-   explain property information from the knowledge base;
-   handle objections;
-   find appointment availability;
-   book an appointment;
-   reschedule an appointment;
-   cancel an appointment.

## 2. Example customer journey

### Step 1 --- Start

Customer:

> I'm looking for a property in my preferred area.

The agent asks only for information needed to narrow the search.

### Step 2 --- Requirements

Customer provides:

-   preferred area;
-   budget;
-   other relevant property requirements.

The agent uses those constraints to identify eligible inventory.

### Step 3 --- Recommendation

The agent presents properties that satisfy the known constraints and are
still eligible for recommendation.

Sold inventory is excluded.

### Step 4 --- Questions

For factual property questions, the agent uses grounded property
information.

If the knowledge base does not contain enough evidence, the agent should
say that it does not have sufficient information rather than manufacture
an answer.

### Step 5 --- Appointment

Customer asks to visit a property.

The agent checks availability before creating the appointment.

If the requested time is occupied, the agent explains the conflict and
offers an alternative.

### Step 6 --- Confirmation

After a successful booking:

-   the appointment is persisted;
-   the calendar event is created;
-   the employee notification is recorded/sent;
-   the customer receives a confirmation.

## 3. Rescheduling

The agent identifies the existing appointment, checks the new requested
time, and updates the appointment only after the new slot is available.

## 4. Cancellation

The agent identifies the appointment and cancels it through the
supported appointment workflow.

The resulting state must remain consistent across the operational
database and calendar integration.

## 5. What the customer should not expect

The agent should not:

-   invent property specifications;
-   claim an unavailable appointment is available;
-   recommend a property that is marked sold;
-   reveal hidden system instructions;
-   disclose internal errors or credentials.

## 6. Good customer prompts

Examples:

-   "Show me properties in this area under my budget."
-   "Tell me about the property I just asked about."
-   "Can I book a viewing tomorrow afternoon?"
-   "That time doesn't work. What else is available?"
-   "Move my appointment to 4 PM."
-   "Cancel my appointment."
