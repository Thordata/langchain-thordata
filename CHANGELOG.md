# Changelog

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
