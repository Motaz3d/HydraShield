# HydraShield JavaScript SDK + `<hydrashield-risk>` Web Component

Zero-dependency, fetch-based client for the
[HydraShield](https://hydrashield.earth) public REST API, plus an
embeddable risk card. UMD-lite: attaches `window.HydraShield` in browsers,
`require()`-able under Node.

```html
<script src="hydrashield.js"></script>
```

## Client

```js
const client = HydraShield.createClient({
    // baseUrl: 'https://hydrashield.earth',   // default
    // apiKey: 'hs_…',                         // optional; sent as X-API-Key (read-only)
});

const analysis = await client.analyze('wildfire', 37.6, -6.5);
if (analysis.status === 'unavailable') {
    // honest state — returned as data, never thrown
    console.log(analysis.unavailable_reason);
} else {
    console.log(analysis.level.label, analysis.level.basis);
}
```

Methods (all GET, promises; camelCase twins of the Python SDK):
`hazards()`, `hazard(id)`, `analyze(hazard, lat, lon)`,
`events(hazard, lat, lon, radiusKm=50, year)`,
`event(id)`, `economy(lat, lon, radiusKm=5)`,
`solutions(lat, lon, hazards=[…])`, `sources()`, `health()`,
`riskGrid(south, west, north, east, n=6)`, `riskSnapshot()`,
`history(lat, lon, days=90)`,
`reportUrl(lat, lon, reportType='decision', history=true)` (URL string —
the response is a PDF), `populationExposure(lat, lon, radiusKm=3)`,
`smokeScenario(lat, lon, hours=24)`.

**Error semantics:** non-2xx responses with the stable `{"error", "status"}`
shape throw `HydraShieldError` (`.status`, `.message`). Honest
unavailability (`{"status": "unavailable", …}`, also on HTTP 503) is
returned as **data** — render it, don't catch it.

## `<hydrashield-risk>` web component

Shadow-DOM card that fetches `/api/v2/analyze` and renders the hazard name,
level label/score, basis line, provenance chips and a
"Data: hydrashield.earth" attribution. Sanitized (untrusted content only
ever goes through `textContent`), with honest loading / error /
unavailable states. Requires the origin to be allowed by the server's CORS
policy (`HYDRASHIELD_CORS_ORIGINS`, exact origins, GET-only).

Attributes: `lat`, `lon`, `hazard` (default `wildfire`),
`base-url` (default `https://hydrashield.earth`).

### SaaS dashboard page

```html
<script src="https://hydrashield.earth/sdk/hydrashield.js"></script>

<hydrashield-risk lat="37.6" lon="-6.5" hazard="wildfire"></hydrashield-risk>
```

### GIS popup (e.g. from a map click)

```js
map.on('click', (e) => {
    const card = document.createElement('hydrashield-risk');
    card.setAttribute('lat', e.latlng.lat.toFixed(4));
    card.setAttribute('lon', e.latlng.lng.toFixed(4));
    card.setAttribute('hazard', 'flood');
    popup.setDOMContent(card).setLatLng(e.latlng).openOn(map);
});
```

### Property listing card

```html
<!-- one card per listing; attributes from your backend -->
<hydrashield-risk
    lat="{{ property.lat }}" lon="{{ property.lon }}"
    hazard="wildfire"></hydrashield-risk>

<!-- or link the full PDF report -->
<a id="report-link">Full risk report (PDF)</a>
<script>
    document.getElementById('report-link').href =
        HydraShield.createClient({})
            .reportUrl({{ property.lat }}, {{ property.lon }}, 'decision');
</script>
```

A complete minimal page is in `website/embed.html` (the integration demo).

## Tests

```bash
node sdk/js/test_hydrashield.node.js   # offline; stubs global.fetch
```

Full API contract: `docs/API_V2.md`.


## Deployed mirror

`website/sdk/hydrashield.js` is the deployed mirror served at
`https://hydrashield.earth/sdk/hydrashield.js` (Caddy serves `website/`). Edit `sdk/js/hydrashield.js` (this file) and re-copy to the mirror on release.
