# ChatHR – Project Brief

## Overview

ChatHR is a secure AI chat system for HR employees in Israeli government and civil service. It answers professional HR questions grounded exclusively in official sources, using RAG (Retrieval-Augmented Generation), citations, source authority hierarchy, privacy safeguards, RBAC, user feedback, and an internal LLM Gateway connected to OpenRouter.

## Core Principles

- **No answer without a source.** If no sufficiently clear official source exists, the system says so.
- **Cite precisely.** Answers include links to sources and, when possible, specific sections, clauses, pages, or paragraphs.
- **Expose conflicts.** When sources conflict, the system shows both and applies authority hierarchy.
- **Privacy first.** No personally identifiable employee information is collected, processed, or sent to external models.
- **No anonymous access.** All users must be authenticated and authorized.

## Civil Service Contexts

Users select one of the following contexts:

- Government ministries (default)
- Defense system
- Health system

Answers are scoped to the selected context.

## Knowledge Sources

1. Official Civil Service Commission documents from gov.il  
   (policies, procedures, guidelines, circulars)
2. Civil Service Regulations — התקשי״ר
3. Salary agreements
4. Approved internal FAQ database
5. Additional sources defined by knowledge admins

## Authority Hierarchy

1. Salary agreements and התקשי״ר — highest priority
2. Commissioner guidelines, official circulars, binding procedures
3. Policy documents, implementation guidelines, helper documents
4. Professionally approved FAQ items
5. General explanatory documents

## Privacy Requirements

The system must detect and block or warn on input containing:

- Israeli ID number
- Employee number
- Full name combined with sensitive employment details
- Health details
- Disciplinary details
- Address, phone, personal email, or other identifiers

## Target Users

HR employees in Israeli government ministries and civil service organizations.

## MVP Goal

A working local development environment via `docker compose up --build`, demonstrating the core chat flow with RAG, citations, RBAC, and LLM Gateway integration.
