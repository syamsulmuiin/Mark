# Browser and Search Workflow

MARK-LIV supports two distinct search paths.

## Server-side information search

Use `web_search` for ordinary information lookup, current facts, news, prices, research, and comparison.

1. Classify the request as `search`, `news`, `research`, `price`, or `compare`.
2. Query the server search ladder (`Gemini grounding` -> `DDG` fallback where available).
3. Return bounded results with title/snippet/source URL.
4. Synthesize only from returned results; preserve uncertainty when sources disagree.
5. Do not open a Companion browser for ordinary lookup.

This path works on a headless VPS and does not require a desktop or visible browser.

## Server-side browser automation

Use server `browser_control` only when the user explicitly targets the server/host or a headless browser is required for a webpage workflow.

1. Resolve an installed browser executable.
2. Use visible mode when a desktop display is available; automatically use headless mode on a display-less Linux host.
3. Open or search with a URL-encoded query.
4. Inspect/read the page.
5. Use semantic locators and bounded auto-waiting for click/type actions.
6. Verify the URL, visible result, page text, or requested state after each action.
7. Stop at login/PIN/password/OTP/biometric/payment credential boundaries.

A headless browser is not the same as a user's visible browser and must not receive the Companion's cookie/session state.

## Android Companion browser

Use this path when the user explicitly asks to use the browser on the current phone.

1. Call `browser.open` or `browser.search` through `call_current_device`.
2. Inspect with `android.ui.inspect`.
3. Choose a visible `view_id` and perform one action: `android.ui.click`, `android.ui.text`, or `android.ui.scroll`.
4. Inspect again and verify the state change.
5. Repeat until the requested page/result is reached.
6. Stop before credential entry; the user completes sensitive authentication directly.

Cookies, sessions, visible browser UI, and device-local app state remain on Android. Do not replace this path with server `browser_control` merely because both can open a URL.

## Desktop Companion browser

Use the desktop Companion's existing `browser_control` dispatcher. Preserve its real browser profile for explicitly requested visible workflows, then use semantic browser actions and verify the resulting page state.

## Reference principles

- Playwright locators are preferred over brittle coordinates/selectors because they auto-wait for visibility, stability, event reception, enabled state, and uniqueness.
- Browser navigation should be verified by resulting URL/page state rather than assuming a click succeeded.
- Android Accessibility is a UI-state/action interface; it requires the user-enabled Accessibility Service and should operate on discovered nodes, not invented coordinates.

## Official references

- Playwright locators and auto-waiting: https://playwright.dev/python/docs/locators and https://playwright.dev/python/docs/actionability
- Playwright navigation and URL verification: https://playwright.dev/python/docs/navigations
- Playwright headed/headless browser setup: https://playwright.dev/python/docs/browsers
- Android Accessibility Service and node actions: https://developer.android.com/guide/topics/ui/accessibility/views/service
