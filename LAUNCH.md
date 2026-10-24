# Launch kit: har2mcp (draft — nothing has been posted)

**Best time:** Tue or Wed, 8:30–9:30 AM ET (HN US-morning ramp). Post the Reddit threads 1–2 hours after HN, and the X thread at the same time as HN.

Before posting: make sure the GIF renders on the repo page, `pip install git+https://github.com/hydope/har2mcp` works from a clean venv, and you're around for 3–4 hours to answer comments.

## Show HN

**Title:** Show HN: har2mcp – record your browser, get an MCP server for any site's private API

**Body:**
> Most sites I use every day have no public API, but they all have a private one: the JSON their own frontend calls. har2mcp takes a HAR file (DevTools → Network → Save all as HAR) and generates a single-file MCP server, with one tool per endpoint, so Claude Code, Cursor or Codex can use that site.
>
> It's deterministic and needs no LLM. It filters out analytics and static noise, templates IDs in paths, infers typed params (values that varied between requests become required, constants become defaults), and moves cookies and auth headers into env vars so secrets never end up in the generated code.
>
> The README demo is a real capture of hn.algolia.com, turned into a `query` tool that returns live HN results.
>
> Known limits: sessions expire, GraphQL is one raw tool per endpoint for now, and sites that sign requests in JS won't replay. I'd love HARs (sanitized) from sites where the inference gets it wrong.
>
> https://github.com/hydope/har2mcp

## Reddit

**r/mcp:** "I built a tool that turns any HAR file into an MCP server (no spec, no LLM, secrets kept in env vars)"
> Record yourself using a site, run `har2mcp session.har`, and get a working stdio MCP server. It works with Claude Code, Cursor and Codex (`har2mcp config` prints the snippets). There's a demo GIF of a real hn.algolia.com capture in the repo. Feedback on param inference is very welcome. https://github.com/hydope/har2mcp

**r/ClaudeAI:** "Give Claude Code access to sites that have no API: har2mcp turns your browser traffic into an MCP server"
> Same tool, framed around the `claude mcp add` workflow. Include the GIF, and be upfront about the ToS and only-your-own-account caveat.

**r/Python:** "har2mcp: HAR file → typed, single-file MCP server (stdlib urllib + mcp SDK)"
> Focus on the implementation: noise filtering, path templating heuristics, and param inference across samples. 11 tests, including a real stdio MCP end-to-end test.

## X thread

1/ Every website has a private API. Its own frontend uses it all day. Now your agent can too. `har2mcp session.har` → a working MCP server. [GIF]
2/ How: record the site in DevTools (or `har2mcp record <url>`), save the HAR, run har2mcp. Noise is filtered, IDs are templated, params are typed, auth goes into env vars.
3/ No LLM, no API key, deterministic. The output is one readable Python file you can edit.
4/ Works with Claude Code, Cursor and Codex: `har2mcp config server.py` prints the snippets.
5/ MIT, early, honest limits in the README. HARs where it guesses wrong are the best contribution → github.com/hydope/har2mcp
