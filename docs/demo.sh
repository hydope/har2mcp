#!/usr/bin/env bash
# Records docs/demo.gif:  asciinema rec -c "bash docs/demo.sh" demo.cast && agg demo.cast docs/demo.gif
set -e
export FORCE_COLOR=1
source /workspace/tools/demo_type.sh 2>/dev/null || run() { echo "\$ $1"; eval "$1"; }
cd "$(mktemp -d)" && cp "$OLDPWD/examples/hn_algolia.har" .
comment "a real HAR: 10 seconds of searching hn.algolia.com in Chrome"
run "har2mcp hn_algolia.har -o hn_server.py --save-secrets"
comment "it's a real MCP server. call it like an agent would:"
run "har2mcp call hn_server.py query_item_dev query='model context protocol' hits_per_page=5 --jq 'data.hits[*].title'"
run "har2mcp config hn_server.py --client claude"
