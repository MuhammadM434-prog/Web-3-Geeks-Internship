# Week 4 --- Day 7: Admin Guide

## 1. Responsibilities

The administrator is responsible for:

-   keeping property inventory current;
-   keeping property availability accurate;
-   maintaining the retrieval knowledge base;
-   checking appointment records;
-   checking notification records;
-   monitoring errors and latency;
-   validating integrations;
-   reviewing security events;
-   maintaining backups.

## 2. Property data

Before publishing inventory, verify:

-   property identifier;
-   active/sold status;
-   price;
-   location/area;
-   size;
-   descriptive content;
-   source/update timestamp.

A property marked sold must not remain eligible for active
recommendations.

## 3. Knowledge base maintenance

RAG documents should be:

1.  collected from approved source material;
2.  cleaned;
3.  chunked consistently;
4.  embedded;
5.  indexed;
6.  versioned;
7.  tested with representative questions.

After a refresh, test both:

-   questions that should retrieve an answer;
-   questions that should cause abstention.

## 4. Appointment administration

Review:

-   appointment ID;
-   customer;
-   property;
-   requested time;
-   current status;
-   calendar synchronization status;
-   notification status.

Conflicting appointments must never be silently overwritten.

## 5. Email notifications

The notification record should allow an administrator to determine
whether the employee notification was created/sent.

The operational database's `emails_sent` record is part of the Day 7
integration validation.

## 6. Incident handling

For repeated errors:

1.  identify the request/time window;
2.  inspect structured logs;
3.  identify the failing component;
4.  check database and provider health;
5.  reproduce safely;
6.  apply the smallest controlled fix;
7.  rerun regression tests;
8.  document the incident.

## 7. Security

Administrators must protect:

-   API keys;
-   calendar credentials;
-   email credentials;
-   database files;
-   customer information;
-   retrieval source material;
-   logs.

Credentials must be supplied through environment/configuration
management rather than committed to source control.
