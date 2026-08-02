import json

out_dir = "E:/AIwork/Self-Agent/.ua/intermediate"

# ============================================================
# PART 1: files 1-9 (alphabetically sorted)
# ============================================================

nodes_p1 = []
edges_p1 = []

# --- File nodes (9) ---
nodes_p1.extend([
{
    "id": "file:app/a2a/executor.py",
    "type": "file", "name": "executor.py", "filePath": "app/a2a/executor.py",
    "summary": "Implements the A2A (Agent-to-Agent) protocol executor that wraps the LangGraph agent, exposing execute and cancel operations for remote agent invocation.",
    "tags": ["a2a", "executor", "agent", "service"], "complexity": "moderate",
    "languageNotes": "Subclasses the a2a-sdk AgentExecutor base class; delegates to run_agent from the core graph."
},
{
    "id": "file:app/a2a/server.py",
    "type": "file", "name": "server.py", "filePath": "app/a2a/server.py",
    "summary": "Mounts A2A JSON-RPC and REST routes onto a FastAPI application, wiring up the executor, agent card, and in-memory task store.",
    "tags": ["a2a", "server", "fastapi", "routing"], "complexity": "moderate",
},
{
    "id": "file:app/a2a/standalone.py",
    "type": "file", "name": "standalone.py", "filePath": "app/a2a/standalone.py",
    "summary": "Standalone entry point that creates a minimal FastAPI app exposing only the A2A endpoint, runnable via uvicorn with configurable host and port.",
    "tags": ["a2a", "entry-point", "standalone-server"], "complexity": "simple",
    "languageNotes": "Uses argparse for CLI arguments and uvicorn.run() for the ASGI server."
},
{
    "id": "file:app/agent/registry.py",
    "type": "file", "name": "registry.py", "filePath": "app/agent/registry.py",
    "summary": "Central tool registry managing tool registration, lookup, and risk classification (safe vs destructive) for the agent's tool-calling system.",
    "tags": ["tool-registry", "agent", "risk-classification", "singleton"], "complexity": "moderate",
},
{
    "id": "file:app/agent/tools/__init__.py",
    "type": "file", "name": "__init__.py", "filePath": "app/agent/tools/__init__.py",
    "summary": "Built-in agent tools including a safe AST-based arithmetic calculator, current-time lookup with timezone support, and a mock weather query.",
    "tags": ["agent-tools", "calculator", "utility", "entry-point"], "complexity": "moderate",
    "languageNotes": "The calculator uses Python's ast module to safely evaluate arithmetic expressions without eval()."
},
{
    "id": "file:app/agent/tools/files.py",
    "type": "file", "name": "files.py", "filePath": "app/agent/tools/files.py",
    "summary": "File-system tools for the agent: read, list, glob, grep, write, edit, and delete, all routed through workspace path resolution and sensitive-file guards.",
    "tags": ["agent-tools", "filesystem", "file-operations", "sandboxed"], "complexity": "complex",
},
{
    "id": "file:app/agent/tools/shell.py",
    "type": "file", "name": "shell.py", "filePath": "app/agent/tools/shell.py",
    "summary": "Shell command execution tool that integrates sandbox wrapping (bubblewrap/Landlock), blocks destructive commands, and captures output with timeout handling.",
    "tags": ["agent-tools", "shell-execution", "sandboxed", "security"], "complexity": "moderate",
},
{
    "id": "file:app/core/logging.py",
    "type": "file", "name": "logging.py", "filePath": "app/core/logging.py",
    "summary": "Centralized logging configuration with OpenTelemetry trace-ID injection via a custom log filter, configurable format and log level from application settings.",
    "tags": ["logging", "observability", "otel", "configuration"], "complexity": "moderate",
    "languageNotes": "Uses a contextvars-based trace ID propagated from OpenTelemetry, injected into every log record via a logging.Filter subclass."
},
{
    "id": "file:app/db/manager.py",
    "type": "file", "name": "manager.py", "filePath": "app/db/manager.py",
    "summary": "Unified database connection manager for PostgreSQL, MongoDB, Redis, and Neo4j with lazy connect/disconnect lifecycle and settings-driven backend selection.",
    "tags": ["database", "connection-manager", "postgres", "mongodb", "redis"], "complexity": "complex",
    "languageNotes": "Exposes each backend as a lazily-initialized property; _try wrapper logs and swallows connection errors so missing backends degrade gracefully."
},
])

# --- Function/Class nodes (Part 1: 26) ---

# executor.py
nodes_p1.append({
    "id": "class:app/a2a/executor.py:SelfAgentExecutor",
    "type": "class", "name": "SelfAgentExecutor",
    "filePath": "app/a2a/executor.py", "lineRange": [31, 75],
    "summary": "A2A executor that receives remote agent messages, delegates to the core run_agent function, and returns the reply as a task artifact.",
    "tags": ["a2a", "executor", "agent-delegation"], "complexity": "moderate",
})
nodes_p1.append({
    "id": "function:app/a2a/executor.py:build_agent_card",
    "type": "function", "name": "build_agent_card",
    "filePath": "app/a2a/executor.py", "lineRange": [78, 96],
    "summary": "Constructs the AgentCard metadata describing this agent's capabilities, skills, and endpoints for A2A discovery.",
    "tags": ["a2a", "agent-card", "metadata", "factory"], "complexity": "simple",
})

# server.py
nodes_p1.append({
    "id": "function:app/a2a/server.py:mount_a2a",
    "type": "function", "name": "mount_a2a",
    "filePath": "app/a2a/server.py", "lineRange": [24, 61],
    "summary": "Mounts A2A JSON-RPC and REST routes onto a FastAPI app, creating the executor, request handler, and in-memory task store.",
    "tags": ["a2a", "mount", "fastapi", "routing"], "complexity": "moderate",
})

# standalone.py
nodes_p1.append({
    "id": "function:app/a2a/standalone.py:create_a2a_app",
    "type": "function", "name": "create_a2a_app",
    "filePath": "app/a2a/standalone.py", "lineRange": [24, 34],
    "summary": "Creates a minimal FastAPI application with logging configured and the A2A endpoint mounted.",
    "tags": ["a2a", "app-factory", "fastapi"], "complexity": "simple",
})
nodes_p1.append({
    "id": "function:app/a2a/standalone.py:main",
    "type": "function", "name": "main",
    "filePath": "app/a2a/standalone.py", "lineRange": [37, 45],
    "summary": "CLI entry point that parses host/port arguments and launches the standalone A2A server via uvicorn.",
    "tags": ["a2a", "cli", "entry-point", "uvicorn"], "complexity": "simple",
})

# registry.py
nodes_p1.append({
    "id": "class:app/agent/registry.py:ToolRisk",
    "type": "class", "name": "ToolRisk",
    "filePath": "app/agent/registry.py", "lineRange": [25, 36],
    "summary": "Enum classifying tool risk levels (safe, destructive) used to gate which tools require user approval.",
    "tags": ["enum", "risk-classification", "type-definition"], "complexity": "simple",
})
nodes_p1.append({
    "id": "function:app/agent/registry.py:_risk_from_metadata",
    "type": "function", "name": "_risk_from_metadata",
    "filePath": "app/agent/registry.py", "lineRange": [50, 61],
    "summary": "Infers a ToolRisk level from a tool's metadata dictionary, falling back to safe when unspecified.",
    "tags": ["risk-classification", "metadata", "utility"], "complexity": "simple",
})
nodes_p1.append({
    "id": "function:app/agent/registry.py:register_tool",
    "type": "function", "name": "register_tool",
    "filePath": "app/agent/registry.py", "lineRange": [70, 75],
    "summary": "Registers a single tool with its risk level in the global tool registry.",
    "tags": ["tool-registry", "registration"], "complexity": "simple",
})
nodes_p1.append({
    "id": "function:app/agent/registry.py:register_tools",
    "type": "function", "name": "register_tools",
    "filePath": "app/agent/registry.py", "lineRange": [78, 84],
    "summary": "Batch-registers multiple tools with a shared risk level by delegating to register_tool.",
    "tags": ["tool-registry", "registration", "batch"], "complexity": "simple",
})
nodes_p1.append({
    "id": "function:app/agent/registry.py:refresh_from_mcp",
    "type": "function", "name": "refresh_from_mcp",
    "filePath": "app/agent/registry.py", "lineRange": [111, 125],
    "summary": "Rebuilds the tool registry from a set of MCP-provided tools, reclassifying risk levels for each.",
    "tags": ["tool-registry", "mcp", "refresh"], "complexity": "moderate",
})

# tools/__init__.py
nodes_p1.append({
    "id": "function:app/agent/tools/__init__.py:_safe_eval_node",
    "type": "function", "name": "_safe_eval_node",
    "filePath": "app/agent/tools/__init__.py", "lineRange": [50, 73],
    "summary": "Recursively evaluates a Python AST node using a whitelist of safe arithmetic and comparison operators, rejecting anything else.",
    "tags": ["calculator", "ast", "safe-eval", "validation"], "complexity": "moderate",
})
nodes_p1.append({
    "id": "function:app/agent/tools/__init__.py:calculator",
    "type": "function", "name": "calculator",
    "filePath": "app/agent/tools/__init__.py", "lineRange": [80, 92],
    "summary": "Agent tool that safely evaluates an arithmetic expression string by parsing it to an AST and applying the safe evaluator.",
    "tags": ["agent-tool", "calculator", "arithmetic"], "complexity": "simple",
})
nodes_p1.append({
    "id": "function:app/agent/tools/__init__.py:get_current_time",
    "type": "function", "name": "get_current_time",
    "filePath": "app/agent/tools/__init__.py", "lineRange": [96, 108],
    "summary": "Agent tool that returns the current time formatted for an optional IANA timezone string.",
    "tags": ["agent-tool", "time", "utility"], "complexity": "simple",
})
nodes_p1.append({
    "id": "function:app/agent/tools/__init__.py:get_weather",
    "type": "function", "name": "get_weather",
    "filePath": "app/agent/tools/__init__.py", "lineRange": [112, 130],
    "summary": "Agent tool that returns mock weather data for a given city, intended as a demo placeholder tool.",
    "tags": ["agent-tool", "weather", "mock"], "complexity": "simple",
})

# files.py tools
for fname, lr, summ, tags in [
    ("read_file", [53, 89], "Agent tool that reads a text file within the workspace, supporting line-range slicing and blocking access to sensitive paths.", ["agent-tool", "filesystem", "read"]),
    ("list_dir", [93, 127], "Agent tool that lists directory contents with file/directory type and size annotations, respecting workspace boundaries.", ["agent-tool", "filesystem", "list"]),
    ("glob_files", [131, 155], "Agent tool that finds files matching a glob pattern within the workspace root.", ["agent-tool", "filesystem", "glob"]),
    ("grep_files", [159, 199], "Agent tool that searches file contents for a query string or regex, with optional case-insensitive and file-pattern filtering.", ["agent-tool", "filesystem", "grep", "search"]),
    ("write_file", [206, 234], "Agent tool that writes content to a file within the workspace, creating parent directories as needed.", ["agent-tool", "filesystem", "write"]),
    ("edit_file", [238, 283], "Agent tool that performs a string replacement edit in a file, with optional replace-all semantics.", ["agent-tool", "filesystem", "edit"]),
    ("delete_file", [287, 311], "Agent tool that deletes a file from the workspace after resolving and validating the path.", ["agent-tool", "filesystem", "delete"]),
]:
    nodes_p1.append({
        "id": f"function:app/agent/tools/files.py:{fname}",
        "type": "function", "name": fname,
        "filePath": "app/agent/tools/files.py", "lineRange": lr,
        "summary": summ, "tags": tags, "complexity": "moderate",
    })

# shell.py
nodes_p1.append({
    "id": "function:app/agent/tools/shell.py:_looks_destructive",
    "type": "function", "name": "_looks_destructive",
    "filePath": "app/agent/tools/shell.py", "lineRange": [51, 65],
    "summary": "Checks whether a parsed command argv matches known destructive patterns (rm -rf, mkfs, dd, etc.) and returns a reason string if so.",
    "tags": ["security", "validation", "destructive-check"], "complexity": "simple",
})
nodes_p1.append({
    "id": "function:app/agent/tools/shell.py:run_command",
    "type": "function", "name": "run_command",
    "filePath": "app/agent/tools/shell.py", "lineRange": [69, 145],
    "summary": "Agent tool that executes a shell command inside the workspace sandbox, blocking destructive commands and capturing stdout/stderr with process-group timeout handling.",
    "tags": ["agent-tool", "shell", "sandboxed", "execution"], "complexity": "complex",
})

# logging.py
nodes_p1.append({
    "id": "class:app/core/logging.py:TraceIdFilter",
    "type": "class", "name": "TraceIdFilter",
    "filePath": "app/core/logging.py", "lineRange": [21, 31],
    "summary": "Logging filter that injects the current OpenTelemetry trace ID into each log record so logs can be correlated with distributed traces.",
    "tags": ["logging", "otel", "trace-correlation", "filter"], "complexity": "simple",
})
nodes_p1.append({
    "id": "function:app/core/logging.py:setup_logging",
    "type": "function", "name": "setup_logging",
    "filePath": "app/core/logging.py", "lineRange": [57, 73],
    "summary": "Configures the root logger with a formatter, the trace-ID filter, and a log level derived from application settings.",
    "tags": ["logging", "configuration", "setup"], "complexity": "simple",
})

# db/manager.py
nodes_p1.append({
    "id": "class:app/db/manager.py:DBManager",
    "type": "class", "name": "DBManager",
    "filePath": "app/db/manager.py", "lineRange": [31, 172],
    "summary": "Manages lazy connections to PostgreSQL, MongoDB, Redis, and Neo4j backends, with graceful connect/disconnect lifecycle and per-backend error tolerance.",
    "tags": ["database", "connection-manager", "postgres", "mongodb", "redis"], "complexity": "complex",
})

# --- Edges Part 1 ---
# contains
for src, targets in {
    "file:app/a2a/executor.py": ["class:app/a2a/executor.py:SelfAgentExecutor", "function:app/a2a/executor.py:build_agent_card"],
    "file:app/a2a/server.py": ["function:app/a2a/server.py:mount_a2a"],
    "file:app/a2a/standalone.py": ["function:app/a2a/standalone.py:create_a2a_app", "function:app/a2a/standalone.py:main"],
    "file:app/agent/registry.py": ["class:app/agent/registry.py:ToolRisk", "function:app/agent/registry.py:_risk_from_metadata", "function:app/agent/registry.py:register_tool", "function:app/agent/registry.py:register_tools", "function:app/agent/registry.py:refresh_from_mcp"],
    "file:app/agent/tools/__init__.py": ["function:app/agent/tools/__init__.py:_safe_eval_node", "function:app/agent/tools/__init__.py:calculator", "function:app/agent/tools/__init__.py:get_current_time", "function:app/agent/tools/__init__.py:get_weather"],
    "file:app/agent/tools/files.py": [f"function:app/agent/tools/files.py:{n}" for n in ["read_file","list_dir","glob_files","grep_files","write_file","edit_file","delete_file"]],
    "file:app/agent/tools/shell.py": ["function:app/agent/tools/shell.py:_looks_destructive", "function:app/agent/tools/shell.py:run_command"],
    "file:app/core/logging.py": ["class:app/core/logging.py:TraceIdFilter", "function:app/core/logging.py:setup_logging"],
    "file:app/db/manager.py": ["class:app/db/manager.py:DBManager"],
}.items():
    for tgt in targets:
        edges_p1.append({"source": src, "target": tgt, "type": "contains", "direction": "forward", "weight": 1.0})

# exports
for src, targets in {
    "file:app/a2a/executor.py": ["class:app/a2a/executor.py:SelfAgentExecutor", "function:app/a2a/executor.py:build_agent_card"],
    "file:app/a2a/server.py": ["function:app/a2a/server.py:mount_a2a"],
    "file:app/a2a/standalone.py": ["function:app/a2a/standalone.py:create_a2a_app", "function:app/a2a/standalone.py:main"],
    "file:app/agent/registry.py": ["class:app/agent/registry.py:ToolRisk", "function:app/agent/registry.py:_risk_from_metadata", "function:app/agent/registry.py:register_tool", "function:app/agent/registry.py:register_tools", "function:app/agent/registry.py:refresh_from_mcp"],
    "file:app/agent/tools/__init__.py": ["function:app/agent/tools/__init__.py:_safe_eval_node", "function:app/agent/tools/__init__.py:calculator", "function:app/agent/tools/__init__.py:get_current_time", "function:app/agent/tools/__init__.py:get_weather"],
    "file:app/agent/tools/files.py": [f"function:app/agent/tools/files.py:{n}" for n in ["read_file","list_dir","glob_files","grep_files","write_file","edit_file","delete_file"]],
    "file:app/agent/tools/shell.py": ["function:app/agent/tools/shell.py:_looks_destructive", "function:app/agent/tools/shell.py:run_command"],
    "file:app/core/logging.py": ["class:app/core/logging.py:TraceIdFilter", "function:app/core/logging.py:setup_logging"],
    "file:app/db/manager.py": ["class:app/db/manager.py:DBManager"],
}.items():
    for tgt in targets:
        edges_p1.append({"source": src, "target": tgt, "type": "exports", "direction": "forward", "weight": 0.8})

# imports (self-import in logging.py skipped)
for src, targets in {
    "file:app/a2a/executor.py": ["file:app/agent/graph.py", "file:app/core/logging.py"],
    "file:app/a2a/server.py": ["file:app/a2a/executor.py", "file:app/core/logging.py"],
    "file:app/a2a/standalone.py": ["file:app/a2a/server.py", "file:app/core/logging.py"],
    "file:app/agent/registry.py": ["file:app/agent/tools/__init__.py", "file:app/core/logging.py"],
    "file:app/agent/tools/__init__.py": ["file:app/core/logging.py"],
    "file:app/agent/tools/files.py": ["file:app/core/config.py", "file:app/core/logging.py", "file:app/workspace.py"],
    "file:app/agent/tools/shell.py": ["file:app/core/config.py", "file:app/core/logging.py", "file:app/sandbox.py", "file:app/workspace.py"],
    "file:app/core/logging.py": ["file:app/core/config.py"],
    "file:app/db/manager.py": ["file:app/core/config.py", "file:app/core/logging.py"],
}.items():
    for tgt in targets:
        edges_p1.append({"source": src, "target": tgt, "type": "imports", "direction": "forward", "weight": 0.7})

# calls (cross-file, confident from callGraph + source inspection)
for src, tgt in [
    ("class:app/a2a/executor.py:SelfAgentExecutor", "function:app/agent/graph.py:run_agent"),
    ("function:app/a2a/server.py:mount_a2a", "function:app/a2a/executor.py:build_agent_card"),
    ("function:app/a2a/server.py:mount_a2a", "class:app/a2a/executor.py:SelfAgentExecutor"),
    ("function:app/a2a/standalone.py:create_a2a_app", "function:app/a2a/server.py:mount_a2a"),
    ("function:app/agent/tools/shell.py:run_command", "function:app/sandbox.py:wrap_command"),
    ("function:app/agent/tools/shell.py:run_command", "function:app/workspace.py:get_workspace"),
    ("function:app/agent/tools/files.py:read_file", "function:app/workspace.py:get_workspace"),
]:
    edges_p1.append({"source": src, "target": tgt, "type": "calls", "direction": "forward", "weight": 0.8})


# ============================================================
# PART 2: files 10-18 (alphabetically sorted)
# ============================================================

nodes_p2 = []
edges_p2 = []

# --- File nodes (9) ---
nodes_p2.extend([
{
    "id": "file:app/logging_service/__init__.py",
    "type": "file", "name": "__init__.py", "filePath": "app/logging_service/__init__.py",
    "summary": "Conversation logging service that persists chat events to MongoDB, with graceful fallback when the database backend is unavailable.",
    "tags": ["logging", "conversation", "mongodb", "service"], "complexity": "moderate",
},
{
    "id": "file:app/mcp/server.py",
    "type": "file", "name": "server.py", "filePath": "app/mcp/server.py",
    "summary": "MCP (Model Context Protocol) server that exposes the agent's built-in tools over stdio or HTTP/SSE transports using the FastMCP framework.",
    "tags": ["mcp", "server", "tool-exposure", "service"], "complexity": "moderate",
},
{
    "id": "file:app/memory/local_store.py",
    "type": "file", "name": "local_store.py", "filePath": "app/memory/local_store.py",
    "summary": "SQLite-based LangGraph checkpointer factory for local development, deriving per-workspace database paths via content hashing.",
    "tags": ["memory", "sqlite", "checkpointer", "langgraph"], "complexity": "moderate",
},
{
    "id": "file:app/middleware/rate_limit.py",
    "type": "file", "name": "rate_limit.py", "filePath": "app/middleware/rate_limit.py",
    "summary": "ASGI rate-limiting middleware using Redis sliding-window counters with configurable limits and per-identity tracking.",
    "tags": ["middleware", "rate-limiting", "redis", "asgi"], "complexity": "moderate",
},
{
    "id": "file:app/profile/service.py",
    "type": "file", "name": "service.py", "filePath": "app/profile/service.py",
    "summary": "User profile service managing interests and preferences, backed by Neo4j graph storage with an in-memory fallback when Neo4j is unavailable.",
    "tags": ["profile", "neo4j", "service", "user-data"], "complexity": "complex",
},
{
    "id": "file:app/sandbox.py",
    "type": "file", "name": "sandbox.py", "filePath": "app/sandbox.py",
    "summary": "Command sandboxing layer using Linux Landlock LSM and bubblewrap for filesystem confinement, network restriction, and private temporary directories.",
    "tags": ["sandbox", "security", "landlock", "bubblewrap", "containerization"], "complexity": "complex",
    "languageNotes": "Uses ctypes to call landlock syscalls directly (landlock_create_ruleset, landlock_add_rule) and falls back to bubblewrap when Landlock is unavailable."
},
{
    "id": "file:app/services/session_service.py",
    "type": "file", "name": "session_service.py", "filePath": "app/services/session_service.py",
    "summary": "Chat session CRUD service backed by PostgreSQL, managing session lifecycle, renaming, deletion, and thread-state cleanup.",
    "tags": ["session", "postgres", "crud", "service"], "complexity": "complex",
},
{
    "id": "file:app/services/stats_service.py",
    "type": "file", "name": "stats_service.py", "filePath": "app/services/stats_service.py",
    "summary": "Usage statistics service aggregating conversation events from MongoDB, with per-model token usage and cost estimation.",
    "tags": ["statistics", "mongodb", "cost-estimation", "analytics"], "complexity": "moderate",
},
{
    "id": "file:app/workspace.py",
    "type": "file", "name": "workspace.py", "filePath": "app/workspace.py",
    "summary": "Workspace abstraction enforcing path confinement to a root directory, with .gitignore-aware ignore matching and sensitive-file protection.",
    "tags": ["workspace", "path-security", "gitignore", "sandboxed"], "complexity": "moderate",
},
])

# --- Function/Class nodes (Part 2: 24) ---

# logging_service
nodes_p2.append({
    "id": "class:app/logging_service/__init__.py:ConversationLogger",
    "type": "class", "name": "ConversationLogger",
    "filePath": "app/logging_service/__init__.py", "lineRange": [23, 88],
    "summary": "Logs conversation events (user/assistant messages, tool calls) to a MongoDB collection, with structured event payloads and history retrieval.",
    "tags": ["logging", "conversation", "mongodb"], "complexity": "moderate",
})

# mcp/server.py
nodes_p2.append({
    "id": "function:app/mcp/server.py:build_mcp_server",
    "type": "function", "name": "build_mcp_server",
    "filePath": "app/mcp/server.py", "lineRange": [30, 58],
    "summary": "Creates a FastMCP server instance and registers all built-in agent tools as MCP tool endpoints with auto-generated JSON schemas.",
    "tags": ["mcp", "server-factory", "tool-registration"], "complexity": "moderate",
})
nodes_p2.append({
    "id": "function:app/mcp/server.py:main",
    "type": "function", "name": "main",
    "filePath": "app/mcp/server.py", "lineRange": [78, 90],
    "summary": "CLI entry point that parses transport arguments and launches the MCP server over stdio or HTTP.",
    "tags": ["mcp", "cli", "entry-point"], "complexity": "simple",
})

# local_store.py
nodes_p2.append({
    "id": "function:app/memory/local_store.py:sqlite_path_for",
    "type": "function", "name": "sqlite_path_for",
    "filePath": "app/memory/local_store.py", "lineRange": [37, 50],
    "summary": "Derives a unique SQLite database path for a workspace by content-hashing its resolved root path.",
    "tags": ["memory", "sqlite", "path-resolution"], "complexity": "simple",
})
nodes_p2.append({
    "id": "function:app/memory/local_store.py:resolve_sqlite_path",
    "type": "function", "name": "resolve_sqlite_path",
    "filePath": "app/memory/local_store.py", "lineRange": [53, 63],
    "summary": "Resolves the SQLite checkpointer path for the current workspace, selecting configured or computed paths.",
    "tags": ["memory", "sqlite", "resolution"], "complexity": "simple",
})
nodes_p2.append({
    "id": "function:app/memory/local_store.py:create_sqlite_checkpointer",
    "type": "function", "name": "create_sqlite_checkpointer",
    "filePath": "app/memory/local_store.py", "lineRange": [66, 91],
    "summary": "Creates a LangGraph AsyncSqliteSaver checkpointer at the resolved workspace-specific database path.",
    "tags": ["memory", "langgraph", "checkpointer", "sqlite"], "complexity": "moderate",
})

# rate_limit.py
nodes_p2.append({
    "id": "class:app/middleware/rate_limit.py:RateLimitMiddleware",
    "type": "class", "name": "RateLimitMiddleware",
    "filePath": "app/middleware/rate_limit.py", "lineRange": [27, 61],
    "summary": "ASGI middleware that enforces per-identity request rate limits using Redis sliding-window counters, returning 429 when exceeded.",
    "tags": ["middleware", "rate-limiting", "redis", "asgi"], "complexity": "moderate",
})
nodes_p2.append({
    "id": "function:app/middleware/rate_limit.py:_send_429",
    "type": "function", "name": "_send_429",
    "filePath": "app/middleware/rate_limit.py", "lineRange": [64, 81],
    "summary": "Constructs and sends an HTTP 429 Too Many Requests response with a Retry-After header.",
    "tags": ["middleware", "http-429", "response"], "complexity": "simple",
})
nodes_p2.append({
    "id": "function:app/middleware/rate_limit.py:_get_identity",
    "type": "function", "name": "_get_identity",
    "filePath": "app/middleware/rate_limit.py", "lineRange": [84, 97],
    "summary": "Extracts the client identity key (user ID or IP) from the ASGI scope for rate-limit bucketing.",
    "tags": ["middleware", "identity", "rate-limiting"], "complexity": "simple",
})

# profile/service.py
nodes_p2.append({
    "id": "class:app/profile/service.py:ProfileService",
    "type": "class", "name": "ProfileService",
    "filePath": "app/profile/service.py", "lineRange": [18, 151],
    "summary": "Manages user profile data (interests, preferences, attributes) via Neo4j graph queries, with an in-memory fallback dictionary when Neo4j is unavailable.",
    "tags": ["profile", "neo4j", "service", "user-data"], "complexity": "complex",
})

# sandbox.py
nodes_p2.append({
    "id": "class:app/sandbox.py:SandboxBackend",
    "type": "class", "name": "SandboxBackend",
    "filePath": "app/sandbox.py", "lineRange": [43, 46],
    "summary": "Enum of available sandbox backends (none, bubblewrap, landlock) used for command isolation strategy selection.",
    "tags": ["enum", "sandbox", "type-definition"], "complexity": "simple",
})
nodes_p2.append({
    "id": "class:app/sandbox.py:SandboxedCommand",
    "type": "class", "name": "SandboxedCommand",
    "filePath": "app/sandbox.py", "lineRange": [292, 296],
    "summary": "Dataclass holding the wrapped command argv, environment overrides, preexec hook, and selected backend for a sandboxed process.",
    "tags": ["sandbox", "dataclass", "command-wrapper"], "complexity": "simple",
})
nodes_p2.append({
    "id": "function:app/sandbox.py:_apply_landlock",
    "type": "function", "name": "_apply_landlock",
    "filePath": "app/sandbox.py", "lineRange": [113, 171],
    "summary": "Applies Linux Landlock filesystem restrictions via ctypes syscalls, confining reads and writes to approved path sets.",
    "tags": ["sandbox", "landlock", "ctypes", "security"], "complexity": "complex",
})
nodes_p2.append({
    "id": "function:app/sandbox.py:_landlock_available",
    "type": "function", "name": "_landlock_available",
    "filePath": "app/sandbox.py", "lineRange": [202, 231],
    "summary": "Probes whether the Linux Landlock LSM is available and functional by testing the landlock_create_ruleset syscall.",
    "tags": ["sandbox", "landlock", "detection"], "complexity": "moderate",
})
nodes_p2.append({
    "id": "function:app/sandbox.py:detect_backend",
    "type": "function", "name": "detect_backend",
    "filePath": "app/sandbox.py", "lineRange": [234, 253],
    "summary": "Detects the best available sandbox backend, preferring Landlock, then bubblewrap, falling back to none.",
    "tags": ["sandbox", "detection", "backend-selection"], "complexity": "moderate",
})
nodes_p2.append({
    "id": "function:app/sandbox.py:wrap_command",
    "type": "function", "name": "wrap_command",
    "filePath": "app/sandbox.py", "lineRange": [299, 329],
    "summary": "Wraps a command argv with the selected sandbox backend, returning a SandboxedCommand with env overrides and a preexec hook.",
    "tags": ["sandbox", "command-wrapping", "factory"], "complexity": "moderate",
})
nodes_p2.append({
    "id": "function:app/sandbox.py:_bwrap_argv",
    "type": "function", "name": "_bwrap_argv",
    "filePath": "app/sandbox.py", "lineRange": [332, 372],
    "summary": "Builds the bubblewrap argument list for filesystem bind-mounts, network policy, and private tmp directory setup.",
    "tags": ["sandbox", "bubblewrap", "argv-builder"], "complexity": "moderate",
})

# session_service.py
nodes_p2.append({
    "id": "class:app/services/session_service.py:SessionService",
    "type": "class", "name": "SessionService",
    "filePath": "app/services/session_service.py", "lineRange": [23, 200],
    "summary": "PostgreSQL-backed service for chat session CRUD operations including listing, creation, renaming, deletion, and thread-state cleanup.",
    "tags": ["session", "postgres", "crud", "service"], "complexity": "complex",
})

# stats_service.py
nodes_p2.append({
    "id": "function:app/services/stats_service.py:estimate_cost",
    "type": "function", "name": "estimate_cost",
    "filePath": "app/services/stats_service.py", "lineRange": [36, 41],
    "summary": "Estimates the monetary cost of an LLM call from the model name and token counts using a price lookup table.",
    "tags": ["cost-estimation", "pricing", "utility"], "complexity": "simple",
})
nodes_p2.append({
    "id": "class:app/services/stats_service.py:StatsService",
    "type": "class", "name": "StatsService",
    "filePath": "app/services/stats_service.py", "lineRange": [44, 117],
    "summary": "Aggregates usage statistics from MongoDB conversation events, computing token counts, cost estimates, and daily usage trends.",
    "tags": ["statistics", "mongodb", "aggregation", "analytics"], "complexity": "moderate",
})

# workspace.py
nodes_p2.append({
    "id": "class:app/workspace.py:WorkspaceError",
    "type": "class", "name": "WorkspaceError",
    "filePath": "app/workspace.py", "lineRange": [45, 49],
    "summary": "Custom exception raised when workspace path resolution or access validation fails.",
    "tags": ["exception", "error-handling", "workspace"], "complexity": "simple",
})
nodes_p2.append({
    "id": "class:app/workspace.py:Workspace",
    "type": "class", "name": "Workspace",
    "filePath": "app/workspace.py", "lineRange": [52, 133],
    "summary": "Enforces path confinement to a workspace root directory with .gitignore-aware ignore matching and sensitive-file protection.",
    "tags": ["workspace", "path-security", "gitignore", "sandboxed"], "complexity": "moderate",
})
nodes_p2.append({
    "id": "function:app/workspace.py:get_workspace",
    "type": "function", "name": "get_workspace",
    "filePath": "app/workspace.py", "lineRange": [142, 153],
    "summary": "Returns the process-global Workspace singleton, initializing it from settings on first access.",
    "tags": ["workspace", "singleton", "factory"], "complexity": "simple",
})
nodes_p2.append({
    "id": "function:app/workspace.py:set_workspace",
    "type": "function", "name": "set_workspace",
    "filePath": "app/workspace.py", "lineRange": [156, 162],
    "summary": "Sets the process-global Workspace singleton to a new root path, primarily for testing.",
    "tags": ["workspace", "singleton", "configuration"], "complexity": "simple",
})

# --- Edges Part 2 ---
for src, targets in {
    "file:app/logging_service/__init__.py": ["class:app/logging_service/__init__.py:ConversationLogger"],
    "file:app/mcp/server.py": ["function:app/mcp/server.py:build_mcp_server", "function:app/mcp/server.py:main"],
    "file:app/memory/local_store.py": ["function:app/memory/local_store.py:sqlite_path_for", "function:app/memory/local_store.py:resolve_sqlite_path", "function:app/memory/local_store.py:create_sqlite_checkpointer"],
    "file:app/middleware/rate_limit.py": ["class:app/middleware/rate_limit.py:RateLimitMiddleware", "function:app/middleware/rate_limit.py:_send_429", "function:app/middleware/rate_limit.py:_get_identity"],
    "file:app/profile/service.py": ["class:app/profile/service.py:ProfileService"],
    "file:app/sandbox.py": ["class:app/sandbox.py:SandboxBackend", "class:app/sandbox.py:SandboxedCommand", "function:app/sandbox.py:_apply_landlock", "function:app/sandbox.py:_landlock_available", "function:app/sandbox.py:detect_backend", "function:app/sandbox.py:wrap_command", "function:app/sandbox.py:_bwrap_argv"],
    "file:app/services/session_service.py": ["class:app/services/session_service.py:SessionService"],
    "file:app/services/stats_service.py": ["function:app/services/stats_service.py:estimate_cost", "class:app/services/stats_service.py:StatsService"],
    "file:app/workspace.py": ["class:app/workspace.py:WorkspaceError", "class:app/workspace.py:Workspace", "function:app/workspace.py:get_workspace", "function:app/workspace.py:set_workspace"],
}.items():
    for tgt in targets:
        edges_p2.append({"source": src, "target": tgt, "type": "contains", "direction": "forward", "weight": 1.0})

for src, targets in {
    "file:app/logging_service/__init__.py": ["class:app/logging_service/__init__.py:ConversationLogger"],
    "file:app/mcp/server.py": ["function:app/mcp/server.py:build_mcp_server", "function:app/mcp/server.py:main"],
    "file:app/memory/local_store.py": ["function:app/memory/local_store.py:sqlite_path_for", "function:app/memory/local_store.py:resolve_sqlite_path", "function:app/memory/local_store.py:create_sqlite_checkpointer"],
    "file:app/middleware/rate_limit.py": ["class:app/middleware/rate_limit.py:RateLimitMiddleware", "function:app/middleware/rate_limit.py:_send_429", "function:app/middleware/rate_limit.py:_get_identity"],
    "file:app/profile/service.py": ["class:app/profile/service.py:ProfileService"],
    "file:app/sandbox.py": ["class:app/sandbox.py:SandboxBackend", "class:app/sandbox.py:SandboxedCommand", "function:app/sandbox.py:_apply_landlock", "function:app/sandbox.py:_landlock_available", "function:app/sandbox.py:detect_backend", "function:app/sandbox.py:wrap_command", "function:app/sandbox.py:_bwrap_argv"],
    "file:app/services/session_service.py": ["class:app/services/session_service.py:SessionService"],
    "file:app/services/stats_service.py": ["function:app/services/stats_service.py:estimate_cost", "class:app/services/stats_service.py:StatsService"],
    "file:app/workspace.py": ["class:app/workspace.py:WorkspaceError", "class:app/workspace.py:Workspace", "function:app/workspace.py:get_workspace", "function:app/workspace.py:set_workspace"],
}.items():
    for tgt in targets:
        edges_p2.append({"source": src, "target": tgt, "type": "exports", "direction": "forward", "weight": 0.8})

for src, targets in {
    "file:app/logging_service/__init__.py": ["file:app/core/logging.py", "file:app/db/manager.py"],
    "file:app/mcp/server.py": ["file:app/agent/tools/__init__.py", "file:app/core/logging.py"],
    "file:app/memory/local_store.py": ["file:app/core/logging.py"],
    "file:app/middleware/rate_limit.py": ["file:app/core/config.py", "file:app/core/logging.py", "file:app/db/manager.py"],
    "file:app/profile/service.py": ["file:app/core/logging.py", "file:app/db/manager.py"],
    "file:app/sandbox.py": ["file:app/core/logging.py"],
    "file:app/services/session_service.py": ["file:app/core/logging.py", "file:app/db/manager.py"],
    "file:app/services/stats_service.py": ["file:app/core/logging.py", "file:app/db/manager.py"],
    "file:app/workspace.py": ["file:app/core/exceptions.py", "file:app/core/logging.py"],
}.items():
    for tgt in targets:
        edges_p2.append({"source": src, "target": tgt, "type": "imports", "direction": "forward", "weight": 0.7})

# --- Write output ---
with open(f"{out_dir}/batch-1-part-1.json", "w", encoding="utf-8") as f:
    json.dump({"nodes": nodes_p1, "edges": edges_p1}, f, indent=2, ensure_ascii=False)

with open(f"{out_dir}/batch-1-part-2.json", "w", encoding="utf-8") as f:
    json.dump({"nodes": nodes_p2, "edges": edges_p2}, f, indent=2, ensure_ascii=False)

# --- Validation ---
print(f"PART 1: {len(nodes_p1)} nodes, {len(edges_p1)} edges")
print(f"PART 2: {len(nodes_p2)} nodes, {len(edges_p2)} edges")
print(f"TOTAL: {len(nodes_p1)+len(nodes_p2)} nodes, {len(edges_p1)+len(edges_p2)} edges")

all_ids = [n["id"] for n in nodes_p1 + nodes_p2]
dupes = set(x for x in all_ids if all_ids.count(x) > 1)
print(f"Duplicate IDs: {dupes if dupes else 'NONE'}")

self_refs = [(e["source"], e["target"]) for e in edges_p1 + edges_p2 if e["source"] == e["target"]]
print(f"Self-referencing edges: {self_refs if self_refs else 'NONE'}")

for n in nodes_p1 + nodes_p2:
    assert n.get("summary"), f"Missing summary for {n['id']}"
    assert n.get("tags"), f"Missing tags for {n['id']}"
    assert n.get("complexity"), f"Missing complexity for {n['id']}"
print("All nodes validated OK.")
