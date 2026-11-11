# Changelog

## Unreleased

- Make Amazon `page_turning` optional and map documentation sort labels to the
  schema values before submitting requests.

## 0.3.0 - 2026-11-10

- Enforce the total Web Scraper deadline through body reads and parsing and
  prohibit automatic redirects.
- Close owned asynchronous clients in the event loop that uses them instead
  of retaining retired connection pools.
- Preserve ordinary signed URLs and result fields while masking known request
  and download credentials.
- Retrieve failure diagnostics within the remaining budget and expose
  `service_code` without retrying submissions.
- Align integer validation across both SDKs and add a standalone scraper example.
- Keep short credential values from changing ordinary business text while still
  masking exact credential fields and explicit credential syntax.
- Bound immediate retries after a timed-out injected synchronous transport and
  preserve task metadata while the previous transport finishes.

- Add fixed-scope Web Scraper support for seven Thordata spider IDs.
- Add synchronous and asynchronous `scrape` methods and an independent
  `ThorDataWebScraperTool`.
- Add five-second polling, a 300-second maximum wait, partial-result handling,
  trusted download URL validation, and API-key redaction.
- Send Web Scraper attribution as POST form fields for the Python integration.
- Preserve long result strings and newlines, and flatten concatenated download chunks.

## 0.2.1 - 2026-10-16

- Update the Thordata links in the README.

## 0.2.0

- Switch the default API endpoint from `/fast_request` to `/request`.
- Support every SERP engine and form parameter handled by `/request`.
- Keep `google_search` and `google_places` as compatibility aliases.
- Allow specialized engines that do not use a `q` parameter.
- Treat `/request` responses with `code=0` as API failures.
- Reuse synchronous and asynchronous HTTP connection pools per client instance.
- Keep the public client JSON-focused because the current `/request` endpoint does not guarantee HTML.
- Normalize convenience parameter aliases consistently with the JavaScript SDK.
- Add a dedicated `ThorDataNotCollectedError` for business code `300`.
- Normalize JSON-string response envelopes before LangChain serialization.

## 0.1.0

- Add synchronous and asynchronous ThorData SERP clients.
- Add the `ThorDataSearchTool` LangChain tool.
- Restrict V1 to supported SERP engines and exclude Web Scraper access.
- Add unit tests, examples, type information, and CI configuration.
