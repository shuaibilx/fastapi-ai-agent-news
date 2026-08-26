## Purpose

Provide authenticated users with a concise AI-generated digest of an existing news article while avoiding repeated model calls for unchanged article content.

## ADDED Requirements

### Requirement: Authenticated news summary request
The system SHALL expose `POST /api/ai/news/{news_id}/summary` to authenticated users. The endpoint MUST generate or retrieve a summary for the identified news article and MUST NOT require the client to supply a model-provider credential.

#### Scenario: Request a summary for an existing article
- **WHEN** an authenticated user requests a summary for an existing `news_id`
- **THEN** the system returns a successful response containing that article's identifier and a non-empty summary

#### Scenario: Request a summary without authentication
- **WHEN** a request does not include valid user authentication
- **THEN** the system rejects the request using the application's standard authentication error response

#### Scenario: Request a summary for missing news
- **WHEN** an authenticated user requests a summary for a `news_id` that does not exist
- **THEN** the system returns the application's standard not-found response and does not call the model provider

### Requirement: Summary result and cache status
The successful summary response SHALL include the summary text and a cache-status value of `hit`, `miss`, or `unavailable`. A `hit` value means the returned summary was retrieved from a valid cache entry; a `miss` value means it was generated during the request; an `unavailable` value means the summary was generated without a usable cache.

#### Scenario: First request generates a summary
- **WHEN** an authenticated user requests a summary for unchanged news with no valid cached summary
- **THEN** the system generates a summary, returns cache status `miss`, and makes the result eligible for future cache retrieval

#### Scenario: Repeat request uses the cached summary
- **WHEN** an authenticated user requests a summary for unchanged news with a valid cached summary
- **THEN** the system returns the cached summary with cache status `hit` and does not call the model provider

### Requirement: Cache freshness for article content
The system SHALL treat a summary as valid only for the title and body content from which it was generated. It MUST NOT return a cached summary created for earlier article content after the article's summarizable content changes.

#### Scenario: Article content changes after a summary is cached
- **WHEN** a news article's title or body changes after a summary has been cached
- **THEN** the next summary request generates a summary for the updated content rather than returning the prior cached summary

### Requirement: Resilient dependency failures
The system SHALL continue to generate a summary when the cache is unavailable, but it MUST report cache status `unavailable` and MUST NOT persist the result as if it were cached. When the model provider cannot generate a summary, the system MUST return a clear service-unavailable response without returning fabricated summary content.

#### Scenario: Redis is unavailable on a cache miss
- **WHEN** an authenticated user requests a summary and the cache cannot be read or written
- **THEN** the system returns a generated summary with cache status `unavailable` if the model provider succeeds

#### Scenario: Model provider is unavailable
- **WHEN** an authenticated user requests a summary and the model provider fails or times out
- **THEN** the system returns a service-unavailable response and does not store an incomplete summary

### Requirement: Server-side provider credential protection
The system SHALL obtain model-provider connection settings only from server-side configuration. It MUST NOT include a model-provider API key in the summary endpoint response, browser-delivered source, or client request contract.

#### Scenario: Summary is requested by the browser
- **WHEN** the frontend requests a news summary through the backend endpoint
- **THEN** the browser sends only application authentication and request data, and no model-provider API key is required or returned
