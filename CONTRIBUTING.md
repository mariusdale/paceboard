# Contributing

Issues and pull requests are welcome. Describe the behavior you expected, the
behavior you observed, your OS, and the relevant version. Never attach account
tokens, `.env`, real health exports or unredacted logs.

## Development

Install uv and Node.js 22+, then run `make install`. For live development,
configure `.env` and Garmin authentication as described in the README, run
`make garmin-mcp` in one terminal and `make dev` in another.

For changes that do not need accounts, use the synthetic fixture workflow in
[the technical reference](docs/REFERENCE.md#testing). Fixture data must remain
clearly labelled. Do not add personal data as a test fixture.

Before opening a pull request:

```bash
make check
make e2e
```

The browser suite requires `cd dashboard && npx playwright install chromium`.
It uses an isolated database and ports, with live provider access disabled.

Keep changes focused and include tests for changed behavior. Preserve source
attribution and missing-data states. Provider credentials must never enter the
frontend bundle. Keep dependency lockfiles updated when changing dependencies.

Open pull requests against `mariusdale/paceboard`, not the Garmin MCP upstream,
unless your change is specifically intended for that upstream project.
