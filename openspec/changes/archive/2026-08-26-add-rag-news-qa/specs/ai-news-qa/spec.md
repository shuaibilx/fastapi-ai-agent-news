## Purpose

Provide authenticated users with grounded answers to news-related questions, using retrieved news articles as the only factual source and exposing supporting citations.

## ADDED Requirements

### Requirement: Authenticated news question answering
The system SHALL expose `POST /api/ai/qa` to authenticated users. The endpoint SHALL accept a non-empty user question and SHALL return an answer generated from retrieved news articles. It MUST NOT require or accept a model-provider credential from the client.

#### Scenario: Answer a question with retrieved context
- **WHEN** an authenticated user submits a question about news covered in the database
- **THEN** the system returns a successful answer with the supporting news citations

#### Scenario: Reject an unauthenticated request
- **WHEN** a request has no valid bearer token
- **THEN** the system returns the application standard authentication error

#### Scenario: Reject an empty question
- **WHEN** an authenticated user submits an empty or whitespace-only question
- **THEN** the system returns a validation error without calling the model provider

### Requirement: Keyword-based retrieval over existing news
The system SHALL retrieve candidate news articles from the existing `news` table using keyword-based search against title, description, and content. The retrieval step MUST NOT require a vector database or embedding provider in this Change.

#### Scenario: Question matches news content
- **WHEN** a user asks a question whose keywords appear in one or more news articles
- **THEN** the system selects the matching articles as answer context

#### Scenario: No matching news
- **WHEN** a user asks a question whose keywords do not appear in any news article
- **THEN** the system returns a refusal answer stating it cannot find supporting news and includes no fabricated citations

### Requirement: Source-grounded answer and citations
The answer MUST be based only on the retrieved news articles. The system SHALL include for each answer the citation metadata: news ID, title, and one or more matched excerpts used to support the answer.

#### Scenario: Answer cites its sources
- **WHEN** an answer is generated from retrieved news
- **THEN** the response includes the source news IDs, titles, and the relevant excerpt text used

#### Scenario: Model avoids out-of-context invention
- **WHEN** the question cannot be answered from retrieved news
- **THEN** the model response explicitly refuses or says it cannot answer, and the response includes no unverified facts

### Requirement: Provider failure handling
If the model provider fails, times out, or returns unusable output, the system SHALL return a clear service-unavailable response. It MUST NOT return an empty answer, a partial fabricated answer, or a response without the documented error semantics.

#### Scenario: Provider returns an error
- **WHEN** the model provider fails or times out during question answering
- **THEN** the system returns a service-unavailable response with a clear error message

### Requirement: Server-side provider credential protection
The system SHALL obtain LLM provider settings only from server-side configuration. The browser MUST NOT send or receive an LLM provider API key as part of the QA request or response.

#### Scenario: QA is called from the browser
- **WHEN** the frontend calls the QA endpoint
- **THEN** the request carries only the application bearer token and question, and the response contains no provider credential
