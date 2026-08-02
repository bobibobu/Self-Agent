import json

nodes = [
  # ===== CSS / markup =====
  {"id":"file:clients/web/src/App.css","type":"file","name":"App.css","filePath":"clients/web/src/App.css","summary":"Catppuccin-themed stylesheet for the web chat client covering the sidebar, login page, message bubbles, tool-step chips, and input area.","tags":["stylesheet","web-client","chat-ui","catppuccin-theme"],"complexity":"moderate"},
  {"id":"file:clients/web/src/index.css","type":"file","name":"index.css","filePath":"clients/web/src/index.css","summary":"Global CSS reset and base typography for the web client, setting full-height layout with a system font stack including CJK fallbacks.","tags":["stylesheet","css-reset","base-styles","typography"],"complexity":"simple"},
  # ===== web build config =====
  {"id":"config:clients/web/vite.config.js","type":"config","name":"vite.config.js","filePath":"clients/web/vite.config.js","summary":"Vite build configuration for the React web client, wiring the React plugin and proxying /api requests to the FastAPI backend on port 8000.","tags":["build-config","vite","react","dev-proxy"],"complexity":"simple","languageNotes":"Dev-server proxy rewrites the /api prefix to avoid CORS during local development."},
  # ===== docs =====
  {"id":"document:docs/00-overview/02-从零读懂.md","type":"document","name":"02-从零读懂.md","filePath":"docs/00-overview/02-从零读懂.md","summary":"Comprehensive from-zero onboarding guide walking new developers from project setup through the agent graph, workspace confinement, sandboxing, and the LLM provider layer.","tags":["documentation","onboarding","architecture","entry-point"],"complexity":"complex"},
  {"id":"document:docs/00-overview/README.md","type":"document","name":"README.md","filePath":"docs/00-overview/README.md","summary":"Project structure manual describing the repository layout, module responsibilities, and how the CLI and web clients relate to the core application.","tags":["documentation","project-structure","overview","manual"],"complexity":"complex"},
  {"id":"document:docs/01-architecture/README.md","type":"document","name":"README.md","filePath":"docs/01-architecture/README.md","summary":"Architecture overview explaining the layered design: agent graph, workspace and sandbox confinement, LLM providers, and the CLI/web client boundaries.","tags":["documentation","architecture","overview","layers"],"complexity":"moderate"},
  {"id":"document:docs/03-development/01-setup.md","type":"document","name":"01-setup.md","filePath":"docs/03-development/01-setup.md","summary":"Development setup guide covering dependency installation, environment configuration, and bootstrapping the Docker-based infrastructure stack.","tags":["documentation","setup","getting-started","infrastructure"],"complexity":"moderate"},
  {"id":"document:docs/03-development/README.md","type":"document","name":"README.md","filePath":"docs/03-development/README.md","summary":"Index page for the development docs section, linking to setup, conventions, and workflow guides.","tags":["documentation","index","development"],"complexity":"simple"},
  {"id":"document:docs/04-guides/README.md","type":"document","name":"README.md","filePath":"docs/04-guides/README.md","summary":"Index page for the guides section, listing how-to and topical walkthroughs.","tags":["documentation","index","guides"],"complexity":"simple"},
  {"id":"document:docs/05-interview/README.md","type":"document","name":"README.md","filePath":"docs/05-interview/README.md","summary":"Interview-preparation notes distilling the project design decisions and trade-offs into Q&A form for technical discussion.","tags":["documentation","interview-prep","design-decisions","q-a"],"complexity":"moderate"},
  {"id":"document:infra/README.md","type":"document","name":"README.md","filePath":"infra/README.md","summary":"Infrastructure README explaining the five-service Docker stack (Postgres, Mongo, Redis, Neo4j, Jaeger), their roles, and operational commands.","tags":["documentation","infrastructure","docker","operations"],"complexity":"moderate"},
  # ===== infra =====
  {"id":"service:infra/docker-compose.yml","type":"service","name":"docker-compose.yml","filePath":"infra/docker-compose.yml","summary":"Core infrastructure orchestrator bringing up the five-service stack: pgvector Postgres, MongoDB, Redis, Jaeger, and Neo4j, with health checks and persistent volumes.","tags":["infrastructure","docker-compose","orchestration","database-stack"],"complexity":"complex","languageNotes":"Uses China-mirror images (daocloud/1panel) since docker.io is blocked regionally; the pgvector image is required for LangGraph PostgresStore semantic search."},
  {"id":"config:infra/mongo/init.js","type":"config","name":"init.js","filePath":"infra/mongo/init.js","summary":"MongoDB initialization script creating the conversation_events and app_logs collections with indexes on thread_id, user_id, and timestamps.","tags":["database","initialization","mongodb","schema-definition"],"complexity":"simple"},
  {"id":"schema:infra/postgres/init.sql","type":"schema","name":"init.sql","filePath":"infra/postgres/init.sql","summary":"PostgreSQL initialization schema installing pgcrypto, pg_trgm, and vector extensions and creating the users and conversations tables with tenant-scoped indexes and a demo user.","tags":["database","schema-definition","postgresql","migration"],"complexity":"moderate","languageNotes":"Uses ALTER TABLE ADD COLUMN IF NOT EXISTS for idempotent in-place upgrades, since init.sql only runs on first volume creation."},
  {"id":"config:mcp_servers.json.example","type":"config","name":"mcp_servers.json.example","filePath":"mcp_servers.json.example","summary":"Example configuration for external MCP server connections, demonstrating stdio (local subprocess) and http (streamable-http remote) transports consumed by MultiServerMCPClient.","tags":["configuration","mcp","example","transport"],"complexity":"simple"},
  # ===== scripts =====
  {"id":"file:scripts/cleanup_test_data.py","type":"file","name":"cleanup_test_data.py","filePath":"scripts/cleanup_test_data.py","summary":"Utility script that purges test-generated threads, conversations, and memory records from the database, identifying them by test thread-id prefixes.","tags":["script","test-cleanup","database","maintenance"],"complexity":"moderate"},
  {"id":"file:scripts/verify_e2e.py","type":"file","name":"verify_e2e.py","filePath":"scripts/verify_e2e.py","summary":"End-to-end verification script that exercises the chat API NDJSON and SSE streaming endpoints against a mock LLM to validate the full request/response contract.","tags":["script","e2e-test","streaming","verification"],"complexity":"moderate"},
  {"id":"file:scripts/verify_phase3.py","type":"file","name":"verify_phase3.py","filePath":"scripts/verify_phase3.py","summary":"Phase-3 verification script validating the long-term memory store, user profile service, conversation logger, and the agent graph memory-injected system prompt.","tags":["script","verification","memory","phase-validation"],"complexity":"moderate"},
  {"id":"file:scripts/verify_phase4.py","type":"file","name":"verify_phase4.py","filePath":"scripts/verify_phase4.py","summary":"Phase-4 verification script validating the A2A (agent-to-agent) executor, server mounting, client delegation, and tool registration against a mock LLM.","tags":["script","verification","a2a","phase-validation"],"complexity":"moderate"},
  {"id":"file:scripts/verify_phase8.py","type":"file","name":"verify_phase8.py","filePath":"scripts/verify_phase8.py","summary":"Phase-8 verification script exercising JWT auth, tenant namespacing, RAG chunking, cost estimation, observability metrics, and the mounted FastAPI app.","tags":["script","verification","auth","observability"],"complexity":"complex"},
  {"id":"file:scripts/verify_sessions.py","type":"file","name":"verify_sessions.py","filePath":"scripts/verify_sessions.py","summary":"Verification script for session-management features: context compression, the cancel registry, and cancellation of in-flight streams through the API.","tags":["script","verification","session-management","cancellation"],"complexity":"moderate"},
  # ===== tests =====
  {"id":"file:tests/conftest.py","type":"file","name":"conftest.py","filePath":"tests/conftest.py","summary":"Shared pytest fixtures that block external I/O (network and disk) and reset in-memory singletons (checkpointer, store, db_manager) for test isolation.","tags":["test","pytest","fixtures","test-isolation"],"complexity":"moderate"},
  {"id":"file:tests/test_api_smoke.py","type":"file","name":"test_api_smoke.py","filePath":"tests/test_api_smoke.py","summary":"Smoke tests for the FastAPI API: health, root, chat (with tool calls, multi-turn, streaming), tool listing, and skill listing, all against a mock LLM.","tags":["test","api","smoke-test","fastapi"],"complexity":"moderate"},
  {"id":"file:tests/test_client_contract.py","type":"file","name":"test_client_contract.py","filePath":"tests/test_client_contract.py","summary":"Contract tests pinning the SSE/NDJSON wire format between the web and CLI clients and the server, covering CRLF separators, ping skipping, and CLI auth handling.","tags":["test","contract-test","sse","ndjson"],"complexity":"complex"},
  {"id":"file:tests/test_coding_tools.py","type":"file","name":"test_coding_tools.py","filePath":"tests/test_coding_tools.py","summary":"Tests for the coding agent tools: workspace path confinement, file tools (read/write/edit/delete/grep with secret refusal), shell execution, and the approval policy gating.","tags":["test","coding-tools","sandbox","approval-policy"],"complexity":"complex"},
  # ===== table sub-nodes =====
  {"id":"table:infra/postgres/init.sql:users","type":"table","name":"users","filePath":"infra/postgres/init.sql","summary":"Core users/accounts table with username, email, tenant_id, and password_hash columns, seeded with a demo user.","tags":["database","table","users","accounts"],"complexity":"simple","lineRange":[22,30]},
  {"id":"table:infra/postgres/init.sql:conversations","type":"table","name":"conversations","filePath":"infra/postgres/init.sql","summary":"Conversation metadata table keyed by (tenant_id, thread_id) to align with the LangGraph checkpointer thread_id.","tags":["database","table","conversations","tenant-scoped"],"complexity":"simple","lineRange":[49,57]},
  # ===== function/class sub-nodes: scripts =====
  {"id":"function:scripts/cleanup_test_data.py:main","type":"function","name":"main","filePath":"scripts/cleanup_test_data.py","summary":"Async entry point that scans conversations and memory for test threads and deletes them, with an apply flag switching between dry-run and commit.","tags":["entry-point","cleanup","async"],"complexity":"moderate","lineRange":[43,99]},
  {"id":"class:scripts/verify_e2e.py:E2EMockLLM","type":"class","name":"E2EMockLLM","filePath":"scripts/verify_e2e.py","summary":"Mock LLM client implementing the provider interface used by the e2e verification to feed deterministic chat and streaming responses.","tags":["mock","llm-client","test-double"],"complexity":"simple","lineRange":[21,53]},
  {"id":"function:scripts/verify_e2e.py:test_ndjson_stream","type":"function","name":"test_ndjson_stream","filePath":"scripts/verify_e2e.py","summary":"Validates that the chat NDJSON streaming endpoint emits one JSON object per line that the CLI client can parse.","tags":["verification","streaming","ndjson"],"complexity":"moderate","lineRange":[56,85]},
  {"id":"function:scripts/verify_e2e.py:test_sse_stream","type":"function","name":"test_sse_stream","filePath":"scripts/verify_e2e.py","summary":"Validates that the chat SSE streaming endpoint emits CRLF-separated events matching the web client parser contract.","tags":["verification","streaming","sse"],"complexity":"moderate","lineRange":[88,123]},
  {"id":"function:scripts/verify_e2e.py:main","type":"function","name":"main","filePath":"scripts/verify_e2e.py","summary":"Entry point that wires the mock LLM into the FastAPI routes and runs the NDJSON and SSE streaming verifications.","tags":["entry-point","verification"],"complexity":"moderate","lineRange":[131,165]},
  {"id":"class:scripts/verify_phase4.py:MockLLM","type":"class","name":"MockLLM","filePath":"scripts/verify_phase4.py","summary":"Mock LLM client returning canned ChatResponse and StreamChunk sequences for the A2A phase-4 verification.","tags":["mock","llm-client","test-double"],"complexity":"simple","lineRange":[22,36]},
  {"id":"function:scripts/verify_phase4.py:main","type":"function","name":"main","filePath":"scripts/verify_phase4.py","summary":"Entry point that validates agent-card building, A2A server mounting, client delegation, and tool registration.","tags":["entry-point","verification","a2a"],"complexity":"moderate","lineRange":[39,101]},
  {"id":"function:scripts/verify_phase3.py:main","type":"function","name":"main","filePath":"scripts/verify_phase3.py","summary":"Entry point that validates the memory service, profile service, conversation logger, and the graph memory-augmented system prompt.","tags":["entry-point","verification","memory"],"complexity":"moderate","lineRange":[22,93]},
  {"id":"function:scripts/verify_phase8.py:main","type":"function","name":"main","filePath":"scripts/verify_phase8.py","summary":"Entry point that exercises JWT hashing and tokens, tenant namespacing, RAG chunking, cost estimation, and observability metrics end-to-end.","tags":["entry-point","verification","auth"],"complexity":"complex","lineRange":[24,153]},
  {"id":"function:scripts/verify_sessions.py:main","type":"function","name":"main","filePath":"scripts/verify_sessions.py","summary":"Entry point that validates context-window compression, the cancel registry, and stream cancellation through the API.","tags":["entry-point","verification","session"],"complexity":"moderate","lineRange":[21,93]},
  # ===== function/class sub-nodes: tests =====
  {"id":"function:tests/conftest.py:_no_external_io","type":"function","name":"_no_external_io","filePath":"tests/conftest.py","summary":"Pytest autouse fixture that monkeypatches network and filesystem call-sites so no test can reach a real socket or disk.","tags":["fixture","test-isolation","monkeypatch"],"complexity":"moderate","lineRange":[58,84]},
  {"id":"function:tests/conftest.py:_fresh_memory_singletons","type":"function","name":"_fresh_memory_singletons","filePath":"tests/conftest.py","summary":"Fixture that resets the in-memory checkpointer, store, and db_manager singletons before each test for clean state.","tags":["fixture","test-isolation","singleton-reset"],"complexity":"simple","lineRange":[88,96]},
  {"id":"class:tests/test_api_smoke.py:_MockLLM","type":"class","name":"_MockLLM","filePath":"tests/test_api_smoke.py","summary":"Mock LLM client backing the smoke-test fixture, emitting scripted chat replies and stream chunks with tool calls.","tags":["mock","llm-client","test-double"],"complexity":"simple","lineRange":[25,70]},
  {"id":"function:tests/test_api_smoke.py:client","type":"function","name":"client","filePath":"tests/test_api_smoke.py","summary":"Pytest fixture that builds a FastAPI TestClient with the mock LLM wired in and external I/O disabled.","tags":["fixture","testclient","fastapi"],"complexity":"simple","lineRange":[74,90]},
  {"id":"class:tests/test_client_contract.py:TestWebSSEContract","type":"class","name":"TestWebSSEContract","filePath":"tests/test_client_contract.py","summary":"Contract tests asserting the web SSE stream uses CRLF separators, recovers every token, and the frontend parser handles ping and separator variants.","tags":["test","contract","sse","web-client"],"complexity":"moderate","lineRange":[156,210]},
  {"id":"class:tests/test_client_contract.py:TestCliAuthSupport","type":"class","name":"TestCliAuthSupport","filePath":"tests/test_client_contract.py","summary":"Contract tests for CLI auth: stream_chat token acceptance, auth-header shape, query-param URL encoding, and owner-only credential files.","tags":["test","contract","auth","cli"],"complexity":"moderate","lineRange":[225,291]},
  {"id":"function:tests/test_client_contract.py:parse_sse_stream","type":"function","name":"parse_sse_stream","filePath":"tests/test_client_contract.py","summary":"Reference SSE parser used by the contract tests to model the frontend expected event extraction behavior.","tags":["utility","sse-parser","reference"],"complexity":"moderate","lineRange":[37,66]},
  {"id":"class:tests/test_coding_tools.py:TestWorkspaceConfinement","type":"class","name":"TestWorkspaceConfinement","filePath":"tests/test_coding_tools.py","summary":"Tests that the workspace guard rejects parent traversal, absolute-path escapes, and symlink breakouts while allowing in-tree paths.","tags":["test","sandbox","path-traversal","security"],"complexity":"moderate","lineRange":[46,84]},
  {"id":"class:tests/test_coding_tools.py:TestFileTools","type":"class","name":"TestFileTools","filePath":"tests/test_coding_tools.py","summary":"Tests that the file tools (read/write/edit/delete/grep) enforce secret refusal, workspace confinement, and ambiguous-edit rejection.","tags":["test","file-tools","security"],"complexity":"moderate","lineRange":[90,155]},
  {"id":"class:tests/test_coding_tools.py:TestShellTool","type":"class","name":"TestShellTool","filePath":"tests/test_coding_tools.py","summary":"Tests that the shell tool runs commands without shell interpretation, denies dangerous commands, and confines cwd to the workspace.","tags":["test","shell-tool","sandbox"],"complexity":"moderate","lineRange":[161,197]},
  {"id":"class:tests/test_coding_tools.py:TestApprovalPolicy","type":"class","name":"TestApprovalPolicy","filePath":"tests/test_coding_tools.py","summary":"Tests the approval gating: gated mode asks for write and exec, readonly denies writes, auto approves all, and unknown tools fail closed.","tags":["test","approval-policy","security"],"complexity":"moderate","lineRange":[203,283]},
]

def E(s, t, tp, w, d="forward"):
    return {"source": s, "target": t, "type": tp, "direction": d, "weight": w}

edges = [
  # ===== contains (file -> sub-node) =====
  E("schema:infra/postgres/init.sql","table:infra/postgres/init.sql:users","contains",1.0),
  E("schema:infra/postgres/init.sql","table:infra/postgres/init.sql:conversations","contains",1.0),
  E("file:scripts/cleanup_test_data.py","function:scripts/cleanup_test_data.py:main","contains",1.0),
  E("file:scripts/verify_e2e.py","class:scripts/verify_e2e.py:E2EMockLLM","contains",1.0),
  E("file:scripts/verify_e2e.py","function:scripts/verify_e2e.py:test_ndjson_stream","contains",1.0),
  E("file:scripts/verify_e2e.py","function:scripts/verify_e2e.py:test_sse_stream","contains",1.0),
  E("file:scripts/verify_e2e.py","function:scripts/verify_e2e.py:main","contains",1.0),
  E("file:scripts/verify_phase4.py","class:scripts/verify_phase4.py:MockLLM","contains",1.0),
  E("file:scripts/verify_phase4.py","function:scripts/verify_phase4.py:main","contains",1.0),
  E("file:scripts/verify_phase3.py","function:scripts/verify_phase3.py:main","contains",1.0),
  E("file:scripts/verify_phase8.py","function:scripts/verify_phase8.py:main","contains",1.0),
  E("file:scripts/verify_sessions.py","function:scripts/verify_sessions.py:main","contains",1.0),
  E("file:tests/conftest.py","function:tests/conftest.py:_no_external_io","contains",1.0),
  E("file:tests/conftest.py","function:tests/conftest.py:_fresh_memory_singletons","contains",1.0),
  E("file:tests/test_api_smoke.py","class:tests/test_api_smoke.py:_MockLLM","contains",1.0),
  E("file:tests/test_api_smoke.py","function:tests/test_api_smoke.py:client","contains",1.0),
  E("file:tests/test_client_contract.py","class:tests/test_client_contract.py:TestWebSSEContract","contains",1.0),
  E("file:tests/test_client_contract.py","class:tests/test_client_contract.py:TestCliAuthSupport","contains",1.0),
  E("file:tests/test_client_contract.py","function:tests/test_client_contract.py:parse_sse_stream","contains",1.0),
  E("file:tests/test_coding_tools.py","class:tests/test_coding_tools.py:TestWorkspaceConfinement","contains",1.0),
  E("file:tests/test_coding_tools.py","class:tests/test_coding_tools.py:TestFileTools","contains",1.0),
  E("file:tests/test_coding_tools.py","class:tests/test_coding_tools.py:TestShellTool","contains",1.0),
  E("file:tests/test_coding_tools.py","class:tests/test_coding_tools.py:TestApprovalPolicy","contains",1.0),
  # ===== exports (file -> exported symbol) =====
  E("file:scripts/cleanup_test_data.py","function:scripts/cleanup_test_data.py:main","exports",0.8),
  E("file:scripts/verify_e2e.py","class:scripts/verify_e2e.py:E2EMockLLM","exports",0.8),
  E("file:scripts/verify_e2e.py","function:scripts/verify_e2e.py:main","exports",0.8),
  E("file:scripts/verify_phase4.py","class:scripts/verify_phase4.py:MockLLM","exports",0.8),
  E("file:scripts/verify_phase4.py","function:scripts/verify_phase4.py:main","exports",0.8),
  E("file:scripts/verify_phase3.py","function:scripts/verify_phase3.py:main","exports",0.8),
  E("file:scripts/verify_phase8.py","function:scripts/verify_phase8.py:main","exports",0.8),
  E("file:scripts/verify_sessions.py","function:scripts/verify_sessions.py:main","exports",0.8),
  # ===== tested_by (production -> test/verify) =====
  E("file:app/agent/tools/files.py","class:tests/test_coding_tools.py:TestFileTools","tested_by",0.5),
  E("file:app/agent/tools/shell.py","class:tests/test_coding_tools.py:TestShellTool","tested_by",0.5),
  E("file:app/workspace.py","class:tests/test_coding_tools.py:TestWorkspaceConfinement","tested_by",0.5),
  E("file:app/agent/nodes/tools_node.py","class:tests/test_coding_tools.py:TestApprovalPolicy","tested_by",0.5),
  E("file:app/api/routes.py","file:tests/test_api_smoke.py","tested_by",0.5),
  E("file:app/main.py","file:tests/test_api_smoke.py","tested_by",0.5),
  E("file:app/llm/models.py","file:tests/test_api_smoke.py","tested_by",0.5),
  E("file:app/llm/factory.py","file:tests/test_api_smoke.py","tested_by",0.5),
  E("file:app/api/routes.py","class:tests/test_client_contract.py:TestWebSSEContract","tested_by",0.5),
  E("file:app/main.py","class:tests/test_client_contract.py:TestWebSSEContract","tested_by",0.5),
  E("file:app/llm/models.py","file:tests/test_client_contract.py","tested_by",0.5),
  E("file:app/memory/store.py","file:tests/conftest.py","tested_by",0.5),
  E("file:app/memory/checkpointer.py","file:tests/conftest.py","tested_by",0.5),
  E("file:app/memory/pg.py","file:tests/conftest.py","tested_by",0.5),
  E("file:app/db/manager.py","file:tests/conftest.py","tested_by",0.5),
  E("file:app/api/routes.py","file:scripts/verify_e2e.py","tested_by",0.5),
  E("file:app/core/exceptions.py","file:scripts/verify_e2e.py","tested_by",0.5),
  E("file:app/llm/factory.py","file:scripts/verify_e2e.py","tested_by",0.5),
  E("file:app/memory/store.py","file:scripts/verify_phase3.py","tested_by",0.5),
  E("file:app/profile/service.py","file:scripts/verify_phase3.py","tested_by",0.5),
  E("file:app/logging_service/__init__.py","file:scripts/verify_phase3.py","tested_by",0.5),
  E("file:app/agent/graph.py","file:scripts/verify_phase3.py","tested_by",0.5),
  E("file:app/a2a/executor.py","file:scripts/verify_phase4.py","tested_by",0.5),
  E("file:app/a2a/server.py","file:scripts/verify_phase4.py","tested_by",0.5),
  E("file:app/a2a/client.py","file:scripts/verify_phase4.py","tested_by",0.5),
  E("file:app/agent/registry.py","file:scripts/verify_phase4.py","tested_by",0.5),
  E("file:app/auth/jwt_service.py","file:scripts/verify_phase8.py","tested_by",0.5),
  E("file:app/auth/tenant.py","file:scripts/verify_phase8.py","tested_by",0.5),
  E("file:app/rag/service.py","file:scripts/verify_phase8.py","tested_by",0.5),
  E("file:app/services/stats_service.py","file:scripts/verify_phase8.py","tested_by",0.5),
  E("file:app/services/observability.py","file:scripts/verify_phase8.py","tested_by",0.5),
  E("file:app/agent/context_manager.py","file:scripts/verify_sessions.py","tested_by",0.5),
  E("file:app/agent/cancel_registry.py","file:scripts/verify_sessions.py","tested_by",0.5),
  E("file:app/main.py","file:scripts/verify_sessions.py","tested_by",0.5),
  E("file:app/db/manager.py","file:scripts/cleanup_test_data.py","tested_by",0.5),
  E("file:app/core/config.py","file:scripts/cleanup_test_data.py","tested_by",0.5),
  # ===== documents (doc -> code) =====
  E("document:docs/00-overview/02-从零读懂.md","file:app/agent/graph.py","documents",0.5),
  E("document:docs/00-overview/02-从零读懂.md","file:app/workspace.py","documents",0.5),
  E("document:docs/00-overview/README.md","file:app/main.py","documents",0.5),
  E("document:docs/01-architecture/README.md","file:app/agent/graph.py","documents",0.5),
  E("document:docs/03-development/01-setup.md","service:infra/docker-compose.yml","documents",0.5),
  E("document:infra/README.md","service:infra/docker-compose.yml","documents",0.5),
  # ===== defines_schema (schema/init -> code that consumes it) =====
  E("schema:infra/postgres/init.sql","file:app/db/manager.py","defines_schema",0.8),
  E("schema:infra/postgres/init.sql","file:app/memory/pg.py","defines_schema",0.8),
  E("config:infra/mongo/init.js","file:app/logging_service/__init__.py","defines_schema",0.8),
  # ===== infra provisions/depends_on =====
  E("service:infra/docker-compose.yml","schema:infra/postgres/init.sql","depends_on",0.6),
  E("service:infra/docker-compose.yml","config:infra/mongo/init.js","depends_on",0.6),
  E("service:infra/docker-compose.yml","file:app/db/manager.py","provisions",0.7),
  E("service:infra/docker-compose.yml","file:app/memory/pg.py","provisions",0.7),
  # ===== configures =====
  E("config:clients/web/vite.config.js","file:clients/web/src/main.jsx","configures",0.6),
  E("config:mcp_servers.json.example","file:app/mcp/client.py","configures",0.6),
  # ===== related (css consumed by jsx components, per neighborMap) =====
  E("file:clients/web/src/App.css","file:clients/web/src/App.jsx","related",0.5),
  E("file:clients/web/src/index.css","file:clients/web/src/main.jsx","related",0.5),
]

# ---- validation ----
seen = {}
dups = []
for n in nodes:
    seen[n["id"]] = seen.get(n["id"], 0) + 1
dups = [i for i, c in seen.items() if c > 1]
assert not dups, "duplicate ids: %s" % dups
selfref = [e for e in edges if e["source"] == e["target"]]
assert not selfref, "self-ref edges: %s" % selfref
# every node has required fields
valid_types = {"file","function","class","config","document","service","table","endpoint","pipeline","schema","resource"}
for n in nodes:
    assert n.get("type") in valid_types, "bad type %s" % n
    assert n.get("summary"), "empty summary %s" % n.get("id")
    assert n.get("tags"), "empty tags %s" % n.get("id")
    assert n.get("complexity") in {"simple","moderate","complex"}, "bad complexity %s" % n.get("id")
# valid edge types
valid_edges = {"contains","imports","calls","inherits","implements","exports","depends_on","tested_by","configures","documents","deploys","migrates","triggers","defines_schema","serves","provisions","routes","related"}
for e in edges:
    assert e["type"] in valid_edges, "bad edge type %s" % e["type"]

print("nodes:", len(nodes), "edges:", len(edges))
n_import = sum(1 for e in edges if e["type"] == "imports")
print("imports edges:", n_import, "(expected 0: batchImportData all empty)")

out = {"nodes": nodes, "edges": edges}
with open(".ua/intermediate/batch-14.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("WROTE batch-14.json OK")
